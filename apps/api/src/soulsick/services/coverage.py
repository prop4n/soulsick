"""Couverture d'un album, piste par piste : ce qui est reçu, d'où, ce qui manque, et qui peut compléter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from ..matching import FileRef, TrackRef, match_files
from ..models import Artist, Candidate, CandidateStatus, LibraryFile, Release, ReleaseGroup, Transfer
from ..quality import is_audio

if TYPE_CHECKING:
    from ..core import Core

SOURCE_STATUSES = {CandidateStatus.CHOSEN, CandidateStatus.DOWNLOADED, CandidateStatus.FAILED}
FILLER_STATUSES = {CandidateStatus.PROPOSED, CandidateStatus.REJECTED}
_RANK = {"complete": 0, "transferring": 1, "initializing": 2, "queued": 3, "paused": 4, "failed": 5, "aborted": 6}


def _track_map(c: Candidate, release: Release, artist: str) -> dict[int, dict]:
    """Associe les fichiers distants d'un candidat aux pistes de l'édition (par nom + durée annoncée)."""
    audio = [f for f in c.files if not f.get("extra") and is_audio(f["filename"])]
    tracks = [TrackRef(t.disc, t.position, t.title, (t.length_ms or 0) / 1000 or None) for t in release.tracks]
    m = match_files(tracks, [FileRef(f["filename"], f.get("duration")) for f in audio], artist_hint=artist)
    out = {}
    for a in m.assignments:
        if a.title_score < 0.5 and not a.number_match:
            continue
        t = release.tracks[a.track_index]
        out[t.id] = audio[a.file_index]
    return out


class CoverageService:
    def __init__(self, core: Core) -> None:
        self.core = core

    async def album(self, rg_id: int) -> dict:
        releases = await self.core.catalog.releases_with_tracks(rg_id)
        async with self.core.db.session() as s:
            rg = await s.get(ReleaseGroup, rg_id)
            assert rg
            artist = await s.get(Artist, rg.artist_id)
            assert artist
            cands = list((await s.execute(select(Candidate).where(Candidate.release_group_id == rg_id))).scalars())
            transfers = list(
                (await s.execute(select(Transfer).where(Transfer.release_group_id == rg_id))).scalars()
            )
            in_library = set(
                (
                    await s.execute(
                        select(LibraryFile.recording_mbid).where(LibraryFile.release_group_mbid == rg.mbid)
                    )
                ).scalars()
            )
        sources = [c for c in cands if c.status in SOURCE_STATUSES]
        preferred = next((c.matched_release_id for c in sorted(sources, key=lambda c: -c.id) if c.matched_release_id), None)
        release = next((r for r in releases if r.id == (preferred or rg.selected_release_id)), releases[0] if releases else None)
        if release is None:
            return {"release_id": None, "tracks": [], "summary": {}, "fillers": []}

        by_path = {(t.candidate_id, t.remote_path): t for t in transfers}
        per_track: dict[int, list[dict]] = {t.id: [] for t in release.tracks}
        for c in sources:
            for track_id, f in _track_map(c, release, artist.name).items():
                t = by_path.get((c.id, f["filename"]))
                if t is None:
                    continue  # fichier du candidat jamais demandé (complément partiel)
                live = self.core.transfers.live(t.id) or {}
                per_track[track_id].append(
                    {
                        "candidate_id": c.id,
                        "username": c.username,
                        "transfer_id": t.id,
                        "state": live.get("state", t.state),
                        "format": f.get("format"),
                        "filename": f["filename"],
                        "bytes": live.get("bytes_transferred", t.bytes_transferred),
                        "size": t.size,
                    }
                )

        tracks = []
        counts = {"received": 0, "downloading": 0, "missing": 0, "in_library": 0}
        for t in release.tracks:
            srcs = sorted(per_track[t.id], key=lambda x: _RANK.get(x["state"], 9))
            ok = [x for x in srcs if x["state"] not in ("failed", "aborted")]
            if any(x["state"] == "complete" for x in srcs):
                state = "received"
            elif any(x["state"] in ("queued", "initializing", "transferring", "paused") for x in srcs):
                state = "downloading"
            elif t.recording_mbid in in_library:
                state = "in_library"
            else:
                state = "missing"
            if state in ("received", "in_library"):
                # La piste est obtenue : les tentatives ratées ou annulées ailleurs ne sont plus pertinentes
                srcs = ok
            counts[state] += 1
            tracks.append(
                {
                    "track_id": t.id, "disc": t.disc, "position": t.position, "title": t.title,
                    "length_ms": t.length_ms, "state": state, "sources": srcs,
                }
            )

        missing_ids = {t["track_id"] for t in tracks if t["state"] == "missing"}
        fillers = []
        if missing_ids:
            for c in sorted((c for c in cands if c.status in FILLER_STATUSES), key=lambda c: -c.score)[:60]:
                m = _track_map(c, release, artist.name)
                got = [
                    {"track_id": tid, "title": next(x.title for x in release.tracks if x.id == tid),
                     "filename": f["filename"], "format": f.get("format")}
                    for tid, f in m.items() if tid in missing_ids
                ]
                if got:
                    fillers.append(
                        {
                            "candidate_id": c.id, "username": c.username, "directory": c.directory,
                            "format": c.format, "score": c.score, "status": c.status,
                            "has_free_slots": c.has_free_slots, "queue_size": c.queue_size, "avg_speed": c.avg_speed,
                            "tracks": sorted(got, key=lambda x: x["track_id"]),
                        }
                    )
            fillers.sort(key=lambda f: (-len(f["tracks"]), not f["has_free_slots"], -f["score"]))
        received_formats = sorted(
            {x["format"] for t in tracks for x in t["sources"] if x["state"] == "complete" and x["format"]}
        )
        return {
            "release_id": release.id,
            "release_title": release.title,
            "tracks": tracks,
            "summary": {**counts, "total": len(tracks)},
            "received_formats": received_formats,
            "fillers": fillers[:8],
        }
