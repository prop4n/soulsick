"""Bibliothèque locale (/music) : scan, rapprochement avec le catalogue via les tags MusicBrainz."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from ..audiotags import read_meta
from ..models import AlbumStatus, Artist, LibraryFile, QualityProfile, Release, ReleaseGroup
from ..quality import is_audio, is_better_or_equal, worst_format

if TYPE_CHECKING:
    from ..core import Core

ACTIVE = {
    AlbumStatus.SEARCHING,
    AlbumStatus.DOWNLOADING,
    AlbumStatus.IMPORTING,
    AlbumStatus.NEEDS_REVIEW,
    AlbumStatus.PENDING_APPROVAL,
}


class LibraryService:
    def __init__(self, core: Core) -> None:
        self.core = core
        self._lock = asyncio.Lock()
        self.scanning = False

    async def scan(self) -> dict:
        async with self._lock:
            self.scanning = True
            try:
                return await self._scan()
            finally:
                self.scanning = False

    async def _scan(self) -> dict:
        root = str(self.core.env.music_dir)
        on_disk: dict[str, tuple[int, float]] = {}

        def walk() -> None:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fn in filenames:
                    if is_audio(fn):
                        p = os.path.join(dirpath, fn)
                        try:
                            st = os.stat(p)
                        except OSError:
                            continue
                        on_disk[p] = (st.st_size, st.st_mtime)

        await asyncio.to_thread(walk)

        async with self.core.db.session() as s:
            known = {f.path: f for f in (await s.execute(select(LibraryFile))).scalars()}
            removed = [p for p in known if p not in on_disk]
            if removed:
                await s.execute(delete(LibraryFile).where(LibraryFile.path.in_(removed)))
            changed = [p for p, (_, mt) in on_disk.items() if p not in known or known[p].mtime != mt]
            for p in changed:
                meta = await asyncio.to_thread(read_meta, p)
                row = known.get(p) or LibraryFile(path=p)
                row.size, row.mtime = on_disk[p]
                row.format = meta.format
                row.bitrate = meta.bitrate
                row.duration = meta.duration
                row.tag_artist = meta.albumartist or meta.artist
                row.tag_album = meta.album
                row.tag_title = meta.title
                row.release_group_mbid = meta.release_group_mbid
                row.release_mbid = meta.release_mbid
                row.recording_mbid = meta.recording_mbid
                row.scanned_at = datetime.now(UTC)
                s.add(row)
            await s.commit()

        await self.refresh_all()
        stats = {"files": len(on_disk), "new_or_changed": len(changed), "removed": len(removed)}
        await self.core.journal.emit(
            "library.scanned",
            f"Bibliothèque analysée : {len(on_disk)} fichiers audio "
            f"({len(changed)} nouveaux/modifiés, {len(removed)} disparus)",
            data=stats,
        )
        return stats

    async def refresh_all(self) -> None:
        async with self.core.db.session() as s:
            ids = list((await s.execute(select(Artist.id))).scalars())
        for aid in ids:
            await self.refresh_artist(aid)

    async def refresh_artist(self, artist_id: int) -> None:
        """Met à jour le statut des albums de l'artiste selon ce qui est présent dans /music."""
        async with self.core.db.session() as s:
            artist = await s.get(Artist, artist_id)
            if not artist:
                return
            profile = await s.get(QualityProfile, artist.quality_profile_id) if artist.quality_profile_id else None
            rgs = list((await s.execute(select(ReleaseGroup).where(ReleaseGroup.artist_id == artist_id))).scalars())
            if not rgs:
                return
            mbids = [rg.mbid for rg in rgs]
            files = list(
                (await s.execute(select(LibraryFile).where(LibraryFile.release_group_mbid.in_(mbids)))).scalars()
            )
            # Fichiers tagués seulement avec l'id de release : on remonte au release group connu
            rel_map = {
                r.mbid: r.release_group_id
                for r in (
                    await s.execute(select(Release).where(Release.release_group_id.in_([rg.id for rg in rgs])))
                ).scalars()
            }
            if rel_map:
                extra = (
                    await s.execute(
                        select(LibraryFile).where(
                            LibraryFile.release_group_mbid.is_(None), LibraryFile.release_mbid.in_(list(rel_map))
                        )
                    )
                ).scalars()
                files.extend(extra)

            by_rg: dict[int, list[LibraryFile]] = {}
            mbid_to_id = {rg.mbid: rg.id for rg in rgs}
            for f in files:
                rid = mbid_to_id.get(f.release_group_mbid or "") or rel_map.get(f.release_mbid or "")
                if rid:
                    by_rg.setdefault(rid, []).append(f)

            for rg in rgs:
                fs = by_rg.get(rg.id, [])
                if not fs:
                    if rg.status == AlbumStatus.IMPORTED:
                        rg.status = AlbumStatus.WANTED if rg.monitored else AlbumStatus.IGNORED
                        rg.status_reason = "Fichiers absents de la bibliothèque"
                        rg.imported_format = None
                        rg.imported_path = None
                    continue
                fmt = worst_format([f.format for f in fs], [])
                rg.imported_format = fmt
                rg.imported_path = os.path.commonpath([os.path.dirname(f.path) for f in fs])
                if rg.status in ACTIVE:
                    continue
                cutoff = profile.upgrade_until if profile else None
                if rg.monitored and cutoff and not is_better_or_equal(fmt, cutoff):
                    rg.status = AlbumStatus.WANTED
                    rg.status_reason = f"Présent en {fmt or 'format inconnu'}, recherche d'une meilleure qualité"
                else:
                    rg.status = AlbumStatus.IMPORTED
                    rg.status_reason = None
            await s.commit()

    async def unmatched_files(self, limit: int = 500) -> list[LibraryFile]:
        async with self.core.db.session() as s:
            res = await s.execute(
                select(LibraryFile)
                .where(LibraryFile.release_group_mbid.is_(None), LibraryFile.release_mbid.is_(None))
                .order_by(LibraryFile.path)
                .limit(limit)
            )
            return list(res.scalars())
