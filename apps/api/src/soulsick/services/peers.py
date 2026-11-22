"""A peer, seen from here: what we exchanged with them (local history) and what the network says."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import case, desc, func, select

from ..models import (
    Artist,
    Candidate,
    CandidateStatus,
    ChatMessage,
    ReleaseGroup,
    Transfer,
    TransferState,
    iso_utc,
)
from ..scoring import DELIVERED, SILENT
from .transfers import transfer_to_dict

if TYPE_CHECKING:
    from ..core import Core

PROFILE_TTL = 60.0
# A source dropped before this, without a byte, may just have been replaced quickly (by you, or
# by a faster peer): not enough to call the peer silent
SILENT_AFTER = timedelta(minutes=10)


class PeerService:
    def __init__(self, core: Core) -> None:
        self.core = core
        self._profiles: dict[str, tuple[float, dict]] = {}

    async def profile(self, username: str, refresh: bool = False) -> dict:
        """Network profile, kept a minute (asking a peer opens a connection to it)."""
        hit = self._profiles.get(username)
        if hit and not refresh and time.monotonic() - hit[0] < PROFILE_TTL:
            return hit[1]
        p = await self.core.engine.peer_profile(username)
        self._profiles[username] = (time.monotonic(), p)
        if len(self._profiles) > 200:
            oldest = min(self._profiles, key=lambda k: self._profiles[k][0])
            del self._profiles[oldest]
        return p

    async def track_records(self, usernames: set[str]) -> dict[str, str]:
        """What each peer did the last time an album was asked from it: it sent (at least a
        byte), or it stayed silent until the source was dropped. Peers never asked are left out.

        Measured on the homelab (Nov 2026): every peer announced a free slot, half of the sources
        never sent anything, and a peer's previous outcome matched the next one 45 times out of 48.
        """
        if not usernames:
            return {}
        async with self.core.db.session() as s:
            rows = (await s.execute(
                select(
                    Candidate.id, Candidate.username, Candidate.status, Transfer.state, Transfer.started_at,
                    Transfer.bytes_transferred, Transfer.requested_at, Transfer.created_at, Transfer.completed_at,
                )
                .join(Transfer, Transfer.candidate_id == Candidate.id)
                .where(Candidate.username.in_(usernames), Transfer.direction == "download")
            )).all()
        by_candidate: dict[int, list] = defaultdict(list)
        for row in rows:
            by_candidate[row[0]].append(row)
        out: dict[str, str] = {}
        for cid in sorted(by_candidate):  # oldest first: the last outcome wins
            ts = by_candidate[cid]
            username, status = ts[0][1], ts[0][2]
            if any(st == TransferState.COMPLETE or started or (sent or 0) > 0 for _, _, _, st, started, sent, *_ in ts):
                out[username] = DELIVERED
                continue
            if status != CandidateStatus.FAILED:
                continue  # still waiting, or given back: nothing to say yet
            asked = min(_aware(req or created) for *_, req, created, _ in ts)
            ended = max((_aware(done) for *_, done in ts if done), default=None)
            if ended and ended - asked >= SILENT_AFTER:
                out[username] = SILENT
        return out

    async def history(self, username: str) -> dict:
        async with self.core.db.session() as s:
            done = Transfer.state == TransferState.COMPLETE
            failed = Transfer.state.in_([TransferState.FAILED, TransferState.ABORTED])
            rows = (await s.execute(
                select(
                    Transfer.direction,
                    func.count(),
                    func.sum(case((done, 1), else_=0)),
                    func.sum(case((failed, 1), else_=0)),
                    func.coalesce(func.sum(case((done, Transfer.size), else_=0)), 0),
                    func.min(Transfer.created_at),
                    func.max(Transfer.created_at),
                ).where(Transfer.username == username).group_by(Transfer.direction)
            )).all()
            totals = {
                d: {"files": n, "complete": ok or 0, "failed": ko or 0, "bytes": size or 0,
                    "first": iso_utc(first), "last": iso_utc(last)}
                for d, n, ok, ko, size, first, last in rows
            }
            # Average speed of what they sent us (finished files with a known duration)
            spans = (await s.execute(
                select(Transfer.size, Transfer.started_at, Transfer.completed_at).where(
                    Transfer.username == username, Transfer.direction == "download", done,
                    Transfer.started_at.is_not(None), Transfer.completed_at.is_not(None),
                ).order_by(desc(Transfer.id)).limit(200)
            )).all()
            secs = sum(max((b - a).total_seconds(), 0.001) for _, a, b in spans)
            measured = sum(sz or 0 for sz, _, _ in spans)
            recent = list((await s.execute(
                select(Transfer).where(Transfer.username == username).order_by(desc(Transfer.id)).limit(40)
            )).scalars())
            cands = (await s.execute(
                select(Candidate, ReleaseGroup, Artist)
                .join(ReleaseGroup, ReleaseGroup.id == Candidate.release_group_id)
                .join(Artist, Artist.id == ReleaseGroup.artist_id)
                .where(Candidate.username == username)
                .order_by(desc(Candidate.id))
                .limit(200)
            )).all()
            chat = (await s.execute(
                select(func.count(), func.max(ChatMessage.ts)).where(
                    ChatMessage.kind == "private", ChatMessage.target == username
                )
            )).one()

        # One line per album: the most advanced source from this peer
        rank = {CandidateStatus.IMPORTED: 4, CandidateStatus.DOWNLOADED: 3, CandidateStatus.CHOSEN: 2,
                CandidateStatus.FAILED: 1}
        albums: dict[int, dict] = {}
        for c, rg, a in cands:
            r = rank.get(c.status, 0)
            if r == 0:
                continue  # only proposed / rejected: nothing came from them
            cur = albums.get(rg.id)
            if cur and cur["_rank"] >= r:
                continue
            albums[rg.id] = {
                "_rank": r, "id": rg.id, "mbid": rg.mbid, "title": rg.title, "artist": a.name, "artist_id": a.id,
                "year": (rg.first_release_date or "")[:4] or None, "candidate_status": c.status,
                "album_status": rg.status, "format": c.format, "date": iso_utc(c.created_at),
            }
        proposed = sum(1 for c, *_ in cands if c.status in (CandidateStatus.PROPOSED, CandidateStatus.REJECTED))
        return {
            "username": username,
            "downloads": totals.get("download"),
            "uploads": totals.get("upload"),
            "measured_speed": round(measured / secs) if secs and measured else None,
            "albums": [{k: v for k, v in x.items() if k != "_rank"} for x in albums.values()],
            "proposals": proposed,
            "messages": {"count": chat[0], "last": iso_utc(chat[1])},
            "recent": [transfer_to_dict(t) for t in recent],
        }


def _aware(dt: datetime) -> datetime:
    """SQLite gives the dates back without their time zone: they are UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
