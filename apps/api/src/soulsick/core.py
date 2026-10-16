"""Assemblage des services (un seul objet partagé par l'application)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update

from .auth import Auth
from .config import Env
from .db import Database
from .journal import Hub, Journal
from .models import AlbumStatus, Artist, ReleaseGroup, Transfer, TransferState
from .musicbrainz import MusicBrainz
from .services.catalog import CatalogService
from .services.coverage import CoverageService
from .services.hunter import HunterService
from .services.importer import ImportService
from .services.library import LibraryService
from .services.navidrome import NavidromeService
from .services.shares import ShareService
from .services.transfers import TransferService
from .settings_store import SettingsStore
from .slsk.engine import SlskEngine

log = logging.getLogger(__name__)


class Core:
    def __init__(self, env: Env, mb: MusicBrainz | None = None, engine: SlskEngine | None = None) -> None:
        self.env = env
        env.ensure_dirs()
        self.db = Database(f"sqlite+aiosqlite:///{env.db_path}")
        self.hub = Hub()
        self.journal = Journal(self.db, self.hub)
        self.settings = SettingsStore(self.db)
        self.auth = Auth(self.settings)
        self.mb = mb or MusicBrainz(env.covers_dir)
        self.engine = engine or SlskEngine(str(env.downloads_dir))
        self.catalog = CatalogService(self)
        self.library = LibraryService(self)
        self.hunter = HunterService(self)
        self.importer = ImportService(self)
        self.transfers = TransferService(self)
        self.shares = ShareService(self)
        self.navidrome = NavidromeService(self)
        self.coverage = CoverageService(self)
        self._tasks: list[asyncio.Task] = []

        self.engine.on_transfer = self.transfers.on_update
        self.engine.on_status = lambda st: self.hub.publish("status", st)
        self.engine.on_info = self._engine_info

    async def _engine_info(self, kind: str, message: str, data: dict) -> None:
        level = data.pop("level", "info")
        await self.journal.emit(kind, message, level=level, data=data)

    async def start(self) -> None:
        await self.db.create_all()
        async with self.db.session() as s:
            # Bases d'avant les sorties partagées : chaque sortie est liée à son artiste principal
            await s.execute(text(
                "INSERT OR IGNORE INTO artist_release_group (artist_id, release_group_id) "
                "SELECT artist_id, id FROM release_group"
            ))
            await s.commit()
        await self.catalog.ensure_default_profiles()
        await self._recover()
        await self.journal.emit("app.started", "Soulsick démarré")
        if not self.env.disable_engine:
            await self.restart_engine()
            self._tasks.append(asyncio.create_task(self.hunter.loop()))
            self._tasks.append(asyncio.create_task(self._sync_loop()))
            self._tasks.append(asyncio.create_task(self._queue_loop()))
        self._tasks.append(asyncio.create_task(self.library.scan()))

    async def _recover(self) -> None:
        """Après un redémarrage, les étapes en cours ne peuvent pas reprendre telles quelles."""
        async with self.db.session() as s:
            await s.execute(
                update(ReleaseGroup)
                .where(ReleaseGroup.status == AlbumStatus.SEARCHING)
                .values(status=AlbumStatus.WANTED, status_reason="Recherche interrompue par un redémarrage")
            )
            await s.execute(
                update(Transfer)
                .where(Transfer.direction == "upload", Transfer.state.not_in(["complete", "failed", "aborted"]))
                .values(state=TransferState.ABORTED, error="Interrompu par un redémarrage")
            )
            await s.commit()
        await self._merge_orphan_downloads()

    async def _merge_orphan_downloads(self) -> None:
        """Répare les doublons laissés par d'anciennes versions : une relance créait une ligne sans
        lien vers son album. On replie l'orpheline sur la ligne d'origine, qui garde ce lien."""
        merged = 0
        async with self.db.session() as s:
            orphans = list(
                (
                    await s.execute(
                        select(Transfer).where(Transfer.direction == "download", Transfer.candidate_id.is_(None))
                    )
                ).scalars()
            )
            for o in orphans:
                linked = (
                    await s.execute(
                        select(Transfer)
                        .where(
                            Transfer.direction == "download",
                            Transfer.username == o.username,
                            Transfer.remote_path == o.remote_path,
                            Transfer.candidate_id.is_not(None),
                        )
                        .order_by(Transfer.id.desc())
                    )
                ).scalars().first()
                if not linked:
                    continue
                if linked.state != TransferState.COMPLETE:
                    linked.state = o.state
                    linked.error = o.error
                    linked.bytes_transferred = o.bytes_transferred
                    linked.completed_at = o.completed_at
                    linked.attempts = (linked.attempts or 1) + 1
                await s.delete(o)
                merged += 1
            await s.commit()
        if merged:
            await self.journal.emit(
                "transfer.repaired", f"{merged} transfert(s) relancé(s) rattaché(s) à leur album d'origine"
            )

    async def restart_engine(self) -> None:
        cfg = (await self.settings.get()).soulseek
        rules = await self.shares.rules()
        await self.engine.start(cfg, rules)
        # Relance des téléchargements non terminés (aioslsk ne garde pas d'état entre deux démarrages)
        self._tasks.append(asyncio.create_task(self._resume_downloads()))

    async def _resume_downloads(self) -> None:
        for _ in range(60):
            if self.engine.logged_in:
                break
            await asyncio.sleep(2)
        else:
            return
        async with self.db.session() as s:
            pending = list(
                (
                    await s.execute(
                        select(Transfer).where(
                            Transfer.direction == "download",
                            Transfer.state.in_(["queued", "initializing", "transferring", "paused"]),
                        )
                    )
                ).scalars()
            )
        for cid in {t.candidate_id for t in pending if t.candidate_id}:
            await self.hunter.reactivate(cid, "fichier(s) relancé(s) au redémarrage")
        for t in pending:
            if not t.local_path:
                continue
            self.transfers.register("download", t.username, t.remote_path, t.id)
            try:
                await self.engine.download(t.username, t.remote_path, t.local_path.rsplit("/", 1)[0])
            except Exception as e:
                log.warning("reprise %s : %s", t.remote_path, e)
        if pending:
            await self.journal.emit("download.resumed", f"{len(pending)} téléchargement(s) repris après redémarrage")

    async def _queue_loop(self) -> None:
        """Demande régulièrement aux pairs notre position dans leur file d'envoi."""
        while True:
            await asyncio.sleep(90)
            if not self.engine.logged_in:
                continue
            try:
                await self.engine.refresh_queue_positions()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("positions en file")

    async def _sync_loop(self) -> None:
        while True:
            await asyncio.sleep(300)
            try:
                hours = (await self.settings.get()).library.sync_interval_hours
                limit = datetime.now(UTC) - timedelta(hours=hours)
                async with self.db.session() as s:
                    ids = list(
                        (
                            await s.execute(
                                select(Artist.id).where(
                                    Artist.monitored.is_(True),
                                    (Artist.last_synced_at.is_(None)) | (Artist.last_synced_at < limit),
                                )
                            )
                        ).scalars()
                    )
                for aid in ids:
                    await self.catalog.sync_artist(aid)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("synchronisation MusicBrainz")

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.engine.stop()
        await self.mb.close()
        await self.db.dispose()
