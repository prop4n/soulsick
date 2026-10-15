"""Assemblage des services (un seul objet partagé par l'application)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from .auth import Auth
from .config import Env
from .db import Database
from .journal import Hub, Journal
from .models import AlbumStatus, Artist, ReleaseGroup, Transfer, TransferState
from .musicbrainz import MusicBrainz
from .services.catalog import CatalogService
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
        self._tasks: list[asyncio.Task] = []

        self.engine.on_transfer = self.transfers.on_update
        self.engine.on_status = lambda st: self.hub.publish("status", st)
        self.engine.on_info = self._engine_info

    async def _engine_info(self, kind: str, message: str, data: dict) -> None:
        level = data.pop("level", "info")
        await self.journal.emit(kind, message, level=level, data=data)

    async def start(self) -> None:
        await self.db.create_all()
        await self.catalog.ensure_default_profiles()
        await self._recover()
        await self.journal.emit("app.started", "Soulsick démarré")
        if not self.env.disable_engine:
            await self.restart_engine()
            self._tasks.append(asyncio.create_task(self.hunter.loop()))
            self._tasks.append(asyncio.create_task(self._sync_loop()))
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
