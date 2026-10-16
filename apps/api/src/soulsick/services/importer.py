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
from ..matching import FileRef, MatchResult, TrackRef, match_files
from ..models import (
    AlbumStatus,
    Artist,
    Candidate,
    CandidateStatus,
    LibraryFile,
    QualityProfile,
    Release,
    ReleaseGroup,
    Transfer,
    TransferState,
)
from ..naming import TrackNaming, render_path
from ..quality import ALL_FORMATS, is_audio, is_better_or_equal, worst_format

if TYPE_CHECKING:
    from ..core import Core

log = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.75
_TERMINAL = {TransferState.COMPLETE, TransferState.FAILED, TransferState.ABORTED}


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
        """Les fichiers d'un candidat sont arrivés : on tente l'import de l'album (toutes sources confondues)."""
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

    async def _sources(self, rg_id: int) -> tuple[list[tuple[Candidate, list[str]]], list[Candidate]]:
        """Sources d'un album : candidats actifs ou abandonnés ayant des fichiers reçus EN ENTIER.

        Retourne (sources avec leurs fichiers complets, candidats ayant encore des transferts en cours).
        Un fichier en échec (souvent partiel) n'est jamais utilisé.
        """
        async with self.core.db.session() as s:
            cands = list(
                (
                    await s.execute(
                        select(Candidate).where(
                            Candidate.release_group_id == rg_id,
                            Candidate.status.in_(
                                [CandidateStatus.CHOSEN, CandidateStatus.DOWNLOADED, CandidateStatus.FAILED]
                            ),
                        )
                    )
                ).scalars()
            )
            rows = list(
                (
                    await s.execute(
                        select(Transfer).where(Transfer.candidate_id.in_([c.id for c in cands]))
                    )
                ).scalars()
            ) if cands else []
        by_cand: dict[int, list[Transfer]] = {}
        for t in rows:
            by_cand.setdefault(t.candidate_id or 0, []).append(t)
        sources: list[tuple[Candidate, list[str]]] = []
        inflight: list[Candidate] = []
        for c in cands:
            ts = [t for t in by_cand.get(c.id, []) if is_audio(t.remote_path)]
            if c.status == CandidateStatus.CHOSEN and any(t.state not in _TERMINAL for t in ts):
                inflight.append(c)
            if ts:
                files = [
                    t.local_path for t in ts
                    if t.state == TransferState.COMPLETE and t.local_path and os.path.isfile(t.local_path)
                ]
            else:
                files = self._local_files(c.download_dir or "")  # anciens téléchargements sans lignes
            if files:
                sources.append((c, sorted(files)))
        return sources, inflight

    async def build_album_plan(self, rg_id: int) -> tuple[list[dict], dict]:
        """Plan d'import multi-sources : pour chaque piste MusicBrainz, le meilleur fichier reçu.

        Doublons (même piste chez deux pairs) : meilleur format d'abord, puis source active,
        puis la plus récente. Les fichiers non retenus sont listés, jamais importés.
        """
        async with self.core.db.session() as s:
            rg = await s.get(ReleaseGroup, rg_id)
            assert rg
            artist = await s.get(Artist, rg.artist_id)
            assert artist
        releases = await self.core.catalog.releases_with_tracks(rg_id)
        sources, _ = await self._sources(rg_id)
        meta: dict[str, object] = {}
        for _, files in sources:
            for f in files:
                meta[f] = await asyncio.to_thread(read_meta, f)

        preferred = next((c.matched_release_id for c, _ in sources if c.matched_release_id), None)
        ordered = sorted(releases, key=lambda r: r.id != (preferred or rg.selected_release_id))
        order = [k for k, _ in ALL_FORMATS]
        best = None
        for rel in ordered:
            tracks = [TrackRef(t.disc, t.position, t.title, (t.length_ms or 0) / 1000 or None) for t in rel.tracks]
            picks: dict[int, tuple[tuple, dict]] = {}
            all_files: list[tuple[Candidate, str]] = []
            unmatched_files: list[str] = []
            for c, files in sources:
                refs = [
                    FileRef(path=f, duration_s=meta[f].duration, tag_title=meta[f].title,
                            tag_track=meta[f].track, tag_disc=meta[f].disc)
                    for f in files
                ]
                m = match_files(tracks, refs, artist_hint=artist.name)
                for i in m.unmatched_files:
                    unmatched_files.append(files[i])
                for a in m.assignments:
                    f = files[a.file_index]
                    fmt = meta[f].format
                    key = (
                        order.index(fmt) if fmt in order else len(order),
                        0 if c.status != CandidateStatus.FAILED else 1,
                        -c.id,
                        -a.score,
                    )
                    entry = {"file": f, "candidate": c, "assignment": a}
                    if a.track_index not in picks or key < picks[a.track_index][0]:
                        picks[a.track_index] = (key, entry)
                all_files.extend((c, f) for f in files)
            result = MatchResult()
            result.assignments = [e["assignment"] for _, e in picks.values()]
            result.unmatched_tracks = [i for i in range(len(tracks)) if i not in picks]
            result.title_score = sum(a.title_score for a in result.assignments) / max(1, len(tracks))
            result.count_ratio = len(picks) / max(1, len(tracks))
            deltas = [a.duration_delta for a in result.assignments if a.duration_delta is not None]
            if deltas:
                result.duration_score = sum(1 for d in deltas if d <= 3.0) / len(tracks)
            if best is None or result.confidence > best[0].confidence + 0.02:
                best = (result, rel, picks, all_files, unmatched_files)
        if best is None:
            return [], {"confidence": 0, "release_id": None, "unmatched_tracks": [], "unmatched_files": [], "sources": 0}
        result, rel, picks, all_files, unmatched_files = best
        chosen = {e["file"]: (ti, e) for ti, (_, e) in picks.items()}
        plan = []
        for c, f in all_files:
            m = meta[f]
            hit = chosen.get(f)
            t = rel.tracks[hit[0]] if hit else None
            plan.append(
                {
                    "file": f,
                    "name": os.path.basename(f),
                    "format": m.format,
                    "duration": m.duration,
                    "source": c.username,
                    "candidate_id": c.id,
                    "track_id": t.id if t else None,
                    "track_title": t.title if t else None,
                    "disc": t.disc if t else None,
                    "position": t.position if t else None,
                    "score": hit[1]["assignment"].score if hit else None,
                    "duplicate": hit is None and f not in unmatched_files,
                }
            )
        info = {
            "confidence": round(result.confidence, 3),
            "release_id": rel.id,
            "release_title": rel.title,
            "unmatched_tracks": [rel.tracks[i].title for i in result.unmatched_tracks],
            "unmatched_files": [os.path.basename(f) for f in unmatched_files],
            "sources": len(sources),
            "per_source": {c.username: sum(1 for _, e in picks.values() if e["candidate"].id == c.id) for c, _ in sources},
        }
        return plan, info

    async def build_plan(self, candidate_id: int) -> tuple[list[dict], dict] | None:
        async with self.core.db.session() as s:
            c = await s.get(Candidate, candidate_id)
            if not c:
                return None
            rg_id = c.release_group_id
        return await self.build_album_plan(rg_id)

    async def _import(self, candidate_id: int) -> None:
        ctx = await self._context(candidate_id)
        if not ctx:
            return
        c, rg, artist, profile, releases = ctx
        label = f"{artist.name} – {rg.title}"
        sources, inflight = await self._sources(rg.id)
        if inflight:
            # Une autre source est encore en cours : on importera quand tout sera arrivé
            names = ", ".join(x.username for x in inflight)
            await self._status(rg.id, AlbumStatus.DOWNLOADING, f"Fichiers reçus de {c.username}, en attente de {names}")
            return

        await self._status(rg.id, AlbumStatus.IMPORTING, None)
        plan, info = await self.build_album_plan(rg.id)
        missing_ok = profile.max_missing_tracks if profile else 0
        missing = info.get("unmatched_tracks", [])

        async with self.core.db.session() as s:
            row = await s.get(Candidate, candidate_id)
            assert row
            row.import_plan = plan
            row.matched_release_id = info["release_id"]
            await s.commit()

        if len(missing) > missing_ok:
            received = sum(1 for p in plan if p["track_id"])
            total = received + len(missing)
            reason = f"{received}/{total} pistes reçues — manquante(s) : {', '.join(missing[:4])}{'…' if len(missing) > 4 else ''}"
            await self._status(rg.id, AlbumStatus.PENDING_APPROVAL, reason + ". Complète depuis un autre pair.")
            await self.core.journal.emit(
                "import.incomplete",
                f"{label} : {reason}. Rien n'a été rangé ; tu peux compléter les pistes manquantes depuis un autre pair.",
                level="warning", artist_id=artist.id, release_group_id=rg.id, candidate_id=candidate_id, data=info,
            )
            return

        problems = []
        if info["confidence"] < MIN_CONFIDENCE:
            problems.append(f"confiance {round(info['confidence'] * 100)} % < {round(MIN_CONFIDENCE * 100)} %")
        if info.get("unmatched_files") and info.get("sources", 1) <= 1:
            problems.append(f"{len(info['unmatched_files'])} fichier(s) sans piste")
        if problems:
            reason = "Association incertaine : " + ", ".join(problems)
            await self._status(rg.id, AlbumStatus.NEEDS_REVIEW, reason)
            await self.core.journal.emit(
                "import.needs_review",
                f"{label} : {reason}. Rien n'a été déplacé, vérifie le plan d'import.",
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
        # Le plan peut venir de l'interface : on n'accepte que des fichiers des dossiers de réception de l'album
        async with self.core.db.session() as s:
            album_cands = list(
                (await s.execute(select(Candidate).where(Candidate.release_group_id == rg.id))).scalars()
            )
        roots = [os.path.realpath(x.download_dir) for x in album_cands if x.download_dir]
        for item in plan:
            real = os.path.realpath(item.get("file", ""))
            if not any(real.startswith(r + os.sep) for r in roots):
                raise ValueError(f"Fichier hors des dossiers de réception : {item.get('file')}")
        used = [i for i in plan if tracks.get(i.get("track_id"))]
        if len({i["track_id"] for i in used}) != len(used):
            raise ValueError("Une piste est associée à plusieurs fichiers")
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
            moved.append({"from": src, "to": dest, "track": t.title, "source": item.get("source")})
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

        # Réception nettoyée : fichiers non retenus (doublons, sources abandonnées) supprimés
        leftovers = 0
        for x in album_cands:
            if x.download_dir and os.path.isdir(x.download_dir):
                leftovers += sum(len(f) for _, _, f in os.walk(x.download_dir))
                shutil.rmtree(x.download_dir, ignore_errors=True)

        # Indexer les fichiers AVANT d'annoncer l'album comme rangé (sinon : « rangé » avec 0 fichier)
        await self.core.library.scan()

        metas = [read_meta(p) for p in new_paths]
        fmt = worst_format([m.format for m in metas], [])
        cutoff = profile.upgrade_until if profile else None
        upgrade = bool(cutoff and not is_better_or_equal(fmt, cutoff))
        contributors = {i.get("candidate_id") or candidate_id for i in used}
        per_source: dict[str, int] = {}
        for i in used:
            per_source[i.get("source") or c.username] = per_source.get(i.get("source") or c.username, 0) + 1
        async with self.core.db.session() as s:
            for cid in contributors:
                row = await s.get(Candidate, cid)
                if row:
                    row.status = CandidateStatus.IMPORTED
                    row.reject_reason = None
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
            + (
                " ; sources : " + ", ".join(f"{u} ({n})" for u, n in per_source.items())
                if len(per_source) > 1 else ""
            )
            + (f" ; {len(removed_old)} ancien(s) fichier(s) remplacé(s)" if removed_old else "")
            + (f" ; {leftovers - len(moved)} fichier(s) non retenu(s) supprimé(s) de la réception"
               if leftovers > len(moved) else "")
            + (" ; validé par toi" if by_user else ""),
            artist_id=artist.id, release_group_id=rg.id, candidate_id=candidate_id,
            data={"moves": moved, "replaced": removed_old, "format": fmt, "release": rel.title, "sources": per_source},
        )
        self.core.hub.publish("album", {"id": rg.id, "status": g.status})
        await self.core.navidrome.trigger_scan()
