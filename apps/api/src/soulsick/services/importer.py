"""Import : fichiers téléchargés → tags MusicBrainz → renommage → /music.

Règle d'or : jamais de déplacement silencieux. Si l'association fichiers ↔ pistes n'est pas
assez sûre, l'album passe en « à vérifier » avec un plan proposé, modifiable dans l'interface.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..audiotags import TagSet, read_meta, write_tags
from ..matching import FileRef, TrackRef, match_files
from ..models import (
    AlbumStatus,
    Artist,
    Candidate,
    CandidateStatus,
    LibraryFile,
    QualityProfile,
    Release,
    ReleaseGroup,
)
from ..naming import TrackNaming, render_path
from ..quality import is_audio, is_better_or_equal, worst_format

if TYPE_CHECKING:
    from ..core import Core

log = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.75


class ImportService:
    def __init__(self, core: Core) -> None:
        self.core = core
        self._lock = asyncio.Lock()

    async def _context(self, candidate_id: int):
        async with self.core.db.session() as s:
            c = await s.get(Candidate, candidate_id)
            if not c:
                return None
            rg = await s.get(ReleaseGroup, c.release_group_id)
            assert rg
            artist = await s.get(Artist, rg.artist_id)
            assert artist
            profile = await s.get(QualityProfile, artist.quality_profile_id) if artist.quality_profile_id else None
        releases = await self.core.catalog.releases_with_tracks(rg.id)
        return c, rg, artist, profile, releases

    async def import_candidate(self, candidate_id: int) -> None:
        async with self._lock:
            try:
                await self._import(candidate_id)
            except Exception as e:
                log.exception("import")
                ctx = await self._context(candidate_id)
                if ctx:
                    _, rg, *_ = ctx
                    await self._status(rg.id, AlbumStatus.NEEDS_REVIEW, f"Erreur à l'import : {e}")
                    await self.core.journal.emit(
                        "import.error", f"« {rg.title} » : erreur pendant l'import ({e})", level="error",
                        release_group_id=rg.id, candidate_id=candidate_id,
                    )

    async def _status(self, rg_id: int, status: str, reason: str | None) -> None:
        async with self.core.db.session() as s:
            rg = await s.get(ReleaseGroup, rg_id)
            if rg:
                rg.status = status
                rg.status_reason = reason
                await s.commit()
        self.core.hub.publish("album", {"id": rg_id, "status": status, "status_reason": reason})

    def _local_files(self, directory: str) -> list[str]:
        out = []
        for dirpath, _, filenames in os.walk(directory):
            for fn in filenames:
                if is_audio(fn) and not fn.endswith(".incomplete"):
                    out.append(os.path.join(dirpath, fn))
        return sorted(out)

    async def build_plan(self, candidate_id: int) -> tuple[list[dict], dict] | None:
        """Plan d'import : pour chaque fichier local, la piste MusicBrainz associée (ou aucune)."""
        ctx = await self._context(candidate_id)
        if not ctx:
            return None
        c, rg, artist, profile, releases = ctx
        files = self._local_files(c.download_dir or "")
        metas = [await asyncio.to_thread(read_meta, f) for f in files]
        refs = [
            FileRef(path=f, duration_s=m.duration, tag_title=m.title, tag_track=m.track, tag_disc=m.disc)
            for f, m in zip(files, metas, strict=True)
        ]
        # On teste d'abord l'édition retenue pendant la chasse, puis les autres
        ordered = sorted(releases, key=lambda r: r.id != (c.matched_release_id or rg.selected_release_id))
        best = None
        for rel in ordered:
            tracks = [TrackRef(t.disc, t.position, t.title, (t.length_ms or 0) / 1000 or None) for t in rel.tracks]
            m = match_files(tracks, refs, artist_hint=artist.name)
            if best is None or m.confidence > best[0].confidence + 0.02:
                best = (m, rel)
        if best is None:
            return [], {"confidence": 0, "release_id": None}
        m, rel = best
        by_file = {a.file_index: a for a in m.assignments}
        plan = []
        for i, f in enumerate(files):
            a = by_file.get(i)
            t = rel.tracks[a.track_index] if a else None
            plan.append(
                {
                    "file": f,
                    "name": os.path.basename(f),
                    "format": metas[i].format,
                    "duration": metas[i].duration,
                    "track_id": t.id if t else None,
                    "track_title": t.title if t else None,
                    "disc": t.disc if t else None,
                    "position": t.position if t else None,
                    "score": a.score if a else None,
                }
            )
        info = {
            "confidence": round(m.confidence, 3),
            "release_id": rel.id,
            "release_title": rel.title,
            "unmatched_tracks": [rel.tracks[i].title for i in m.unmatched_tracks],
            "unmatched_files": [os.path.basename(files[i]) for i in m.unmatched_files],
        }
        return plan, info

    async def _import(self, candidate_id: int) -> None:
        ctx = await self._context(candidate_id)
        if not ctx:
            return
        c, rg, artist, profile, releases = ctx
        await self._status(rg.id, AlbumStatus.IMPORTING, None)
        built = await self.build_plan(candidate_id)
        assert built
        plan, info = built
        missing_ok = profile.max_missing_tracks if profile else 0

        problems = []
        if info["confidence"] < MIN_CONFIDENCE:
            problems.append(f"confiance {round(info['confidence'] * 100)} % < {round(MIN_CONFIDENCE * 100)} %")
        if len(info.get("unmatched_tracks", [])) > missing_ok:
            problems.append(f"{len(info['unmatched_tracks'])} piste(s) sans fichier")
        if info.get("unmatched_files"):
            problems.append(f"{len(info['unmatched_files'])} fichier(s) sans piste")

        async with self.core.db.session() as s:
            row = await s.get(Candidate, candidate_id)
            assert row
            row.import_plan = plan
            row.matched_release_id = info["release_id"]
            await s.commit()

        if problems:
            reason = "Association incertaine : " + ", ".join(problems)
            await self._status(rg.id, AlbumStatus.NEEDS_REVIEW, reason)
            await self.core.journal.emit(
                "import.needs_review",
                f"{artist.name} – {rg.title} : {reason}. Rien n'a été déplacé, vérifie le plan d'import.",
                level="warning", artist_id=artist.id, release_group_id=rg.id, candidate_id=candidate_id,
                data=info,
            )
            return
        await self.apply_plan(candidate_id, plan, info["release_id"])

    async def apply_plan(self, candidate_id: int, plan: list[dict], release_id: int, by_user: bool = False) -> None:
        ctx = await self._context(candidate_id)
        if not ctx:
            return
        c, rg, artist, profile, releases = ctx
        rel = next((r for r in releases if r.id == release_id), None)
        if rel is None:
            raise ValueError("Édition inconnue")
        tracks = {t.id: t for t in rel.tracks}
        # Le plan peut venir de l'interface : on n'accepte que des fichiers du dossier du candidat
        root = os.path.realpath(c.download_dir or "")
        for item in plan:
            if not c.download_dir or not os.path.realpath(item.get("file", "")).startswith(root + os.sep):
                raise ValueError(f"Fichier hors du dossier de téléchargement : {item.get('file')}")
        settings = await self.core.settings.get()
        music = str(self.core.env.music_dir)
        year = (rel.date or rg.first_release_date or "")[:4]

        # Pochette : toujours écrite en cover.jpg (Navidrome), intégrée aux fichiers si demandé
        p = await self.core.mb.cover("release", rel.mbid, 1200) or await self.core.mb.cover(
            "release-group", rg.mbid, 1200
        )
        cover = p.read_bytes() if p else None

        # Remplacement d'une version précédente (amélioration de qualité)
        async with self.core.db.session() as s:
            old = list(
                (await s.execute(select(LibraryFile).where(LibraryFile.release_group_mbid == rg.mbid))).scalars()
            )
        moved: list[dict] = []
        new_paths: list[str] = []
        for item in plan:
            t = tracks.get(item.get("track_id"))
            if t is None:
                continue
            src = item["file"]
            ext = src.rsplit(".", 1)[-1].lower()
            rel_path = render_path(
                settings.library.naming_template,
                TrackNaming(
                    albumartist=artist.name,
                    artist=t.artist_credit or artist.name,
                    album=rg.title,
                    year=year,
                    title=t.title,
                    track=t.position,
                    disc=t.disc,
                    disc_count=rel.disc_count,
                    ext=ext,
                    release_type=rg.primary_type or "",
                ),
            )
            dest = os.path.join(music, rel_path)
            if settings.library.write_tags:
                tags = TagSet(
                    title=t.title,
                    artist=t.artist_credit or artist.name,
                    album=rg.title,
                    albumartist=artist.name,
                    date=rel.date or rg.first_release_date or "",
                    tracknumber=t.position,
                    tracktotal=sum(1 for x in rel.tracks if x.disc == t.disc),
                    discnumber=t.disc,
                    disctotal=rel.disc_count,
                    musicbrainz_trackid=t.recording_mbid,
                    musicbrainz_releasetrackid=t.mbid,
                    musicbrainz_albumid=rel.mbid,
                    musicbrainz_releasegroupid=rg.mbid,
                    musicbrainz_artistid=artist.mbid,
                    musicbrainz_albumartistid=artist.mbid,
                    releasetype=rg.primary_type or "",
                    label=rel.label or "",
                    barcode=rel.barcode or "",
                )
                await asyncio.to_thread(write_tags, src, tags, cover if settings.library.embed_cover else None)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            await asyncio.to_thread(shutil.move, src, dest)
            moved.append({"from": src, "to": dest, "track": t.title})
            new_paths.append(dest)

        album_dir = os.path.commonpath([os.path.dirname(p) for p in new_paths]) if new_paths else None
        if album_dir and cover:
            with open(os.path.join(album_dir, "cover.jpg"), "wb") as fh:
                fh.write(cover)

        removed_old = []
        for f in old:
            if f.path not in new_paths and os.path.exists(f.path):
                os.remove(f.path)
                removed_old.append(f.path)

        if c.download_dir and os.path.isdir(c.download_dir):
            shutil.rmtree(c.download_dir, ignore_errors=True)

        metas = [read_meta(p) for p in new_paths]
        fmt = worst_format([m.format for m in metas], [])
        cutoff = profile.upgrade_until if profile else None
        upgrade = bool(cutoff and not is_better_or_equal(fmt, cutoff))
        async with self.core.db.session() as s:
            row = await s.get(Candidate, candidate_id)
            assert row
            row.status = CandidateStatus.IMPORTED
            g = await s.get(ReleaseGroup, rg.id)
            assert g
            g.selected_release_id = rel.id
            g.imported_format = fmt
            g.imported_path = album_dir
            g.status = AlbumStatus.WANTED if upgrade else AlbumStatus.IMPORTED
            g.status_reason = f"Importé en {fmt}, recherche d'une meilleure qualité" if upgrade else None
            await s.commit()

        await self.core.journal.emit(
            "import.done",
            f"{artist.name} – {rg.title} importé : {len(moved)} fichiers rangés dans {album_dir}"
            + (" (tags MusicBrainz écrits" + (", pochette intégrée)" if cover else ")") if settings.library.write_tags else "")
            + (f" ; {len(removed_old)} ancien(s) fichier(s) remplacé(s)" if removed_old else "")
            + (" ; validé par toi" if by_user else ""),
            artist_id=artist.id, release_group_id=rg.id, candidate_id=candidate_id,
            data={"moves": moved, "replaced": removed_old, "format": fmt, "release": rel.title},
        )
        self.core.hub.publish("album", {"id": rg.id, "status": g.status})
        await self.core.library.scan()
        await self.core.navidrome.trigger_scan()
