"""Chasse : albums recherchés → recherches Soulseek → candidats notés → décision → téléchargement."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import or_, select

from ..matching import TrackRef
from ..models import (
    AlbumStatus,
    Artist,
    ArtistMode,
    Candidate,
    CandidateStatus,
    QualityProfile,
    ReleaseGroup,
    SearchRun,
    Transfer,
    TransferState,
)
from ..quality import FORMAT_LABELS, is_better_or_equal
from ..scoring import PeerResult, ReleaseOption, ScoredCandidate, rank_candidates
from ..slsk.engine import EngineUnavailable

if TYPE_CHECKING:
    from ..core import Core

log = logging.getLogger(__name__)

TERMINAL = {TransferState.COMPLETE, TransferState.FAILED, TransferState.ABORTED}
STALL_MINUTES = 30
RETRY_HOURS = 12


def clean_query(text: str) -> str:
    text = re.sub(r"[\[\(].*?[\]\)]", " ", text)
    text = re.sub(r"[^\w\s']", " ", text)
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text).strip()


def build_queries(artist: str, album: str) -> list[str]:
    a, b = clean_query(artist), clean_query(album)
    queries = [f"{a} {b}"]
    if a.lower().startswith("the "):
        queries.append(f"{a[4:]} {b}")
    out: list[str] = []
    for q in queries:
        if q and q.lower() not in [x.lower() for x in out]:
            out.append(q)
    return out


def summarize_rejections(cands: list[ScoredCandidate]) -> dict[str, int]:
    c: Counter[str] = Counter()
    for x in cands:
        if x.reject_reason:
            # On regroupe par type de raison (avant les chiffres)
            c[re.sub(r"\d+", "N", x.reject_reason.split("(")[0]).strip()] += 1
    return dict(c.most_common(6))


class HunterService:
    def __init__(self, core: Core) -> None:
        self.core = core
        self._lock = asyncio.Lock()
        self.current: dict | None = None
        self.last_run_at: datetime | None = None
        self.next_run_at: datetime | None = None

    # --- Boucle -----------------------------------------------------------

    async def loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("boucle de chasse")
            await asyncio.sleep(60)

    async def tick(self) -> None:
        await self.check_stalled()
        cfg = (await self.core.settings.get()).hunter
        now = datetime.now(UTC)
        if not cfg.enabled:
            self.next_run_at = None
            return
        if self.last_run_at and now - self.last_run_at < timedelta(minutes=cfg.interval_minutes):
            self.next_run_at = self.last_run_at + timedelta(minutes=cfg.interval_minutes)
            return
        self.last_run_at = now
        self.next_run_at = now + timedelta(minutes=cfg.interval_minutes)
        if not self.core.engine.logged_in:
            return
        await self.run_wanted(cfg.max_searches_per_run)

    async def run_wanted(self, limit: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=RETRY_HOURS)
        async with self.core.db.session() as s:
            res = await s.execute(
                select(ReleaseGroup.id)
                .join(Artist, Artist.id == ReleaseGroup.artist_id)
                .where(
                    ReleaseGroup.status == AlbumStatus.WANTED,
                    ReleaseGroup.monitored.is_(True),
                    Artist.monitored.is_(True),
                    or_(ReleaseGroup.last_searched_at.is_(None), ReleaseGroup.last_searched_at < cutoff),
                )
                .order_by(ReleaseGroup.last_searched_at.is_not(None), ReleaseGroup.last_searched_at)
                .limit(limit)
            )
            ids = list(res.scalars())
        for rg_id in ids:
            await self.hunt(rg_id, trigger="auto")
        return len(ids)

    # --- Chasse d'un album --------------------------------------------------

    async def _load(self, rg_id: int) -> tuple[ReleaseGroup, Artist, QualityProfile] | None:
        async with self.core.db.session() as s:
            rg = await s.get(ReleaseGroup, rg_id)
            if not rg:
                return None
            artist = await s.get(Artist, rg.artist_id)
            assert artist
            profile = None
            if artist.quality_profile_id:
                profile = await s.get(QualityProfile, artist.quality_profile_id)
            if profile is None:
                profile = (await s.execute(select(QualityProfile).order_by(QualityProfile.id))).scalars().first()
            assert profile
            return rg, artist, profile

    async def _set_status(self, rg_id: int, status: str, reason: str | None = None, searched: bool = False) -> None:
        async with self.core.db.session() as s:
            rg = await s.get(ReleaseGroup, rg_id)
            if not rg:
                return
            rg.status = status
            rg.status_reason = reason
            if searched:
                rg.last_searched_at = datetime.now(UTC)
            await s.commit()
        self.core.hub.publish("album", {"id": rg_id, "status": status, "status_reason": reason})

    async def hunt(self, rg_id: int, trigger: str = "manual") -> None:
        async with self._lock:
            try:
                await self._hunt(rg_id, trigger)
            finally:
                self.current = None
                self.core.hub.publish("hunter", self.state())

    async def _hunt(self, rg_id: int, trigger: str) -> None:
        loaded = await self._load(rg_id)
        if not loaded:
            return
        rg, artist, profile = loaded
        previous_status = rg.status
        label = f"{artist.name} – {rg.title}"
        cfg = (await self.core.settings.get()).hunter
        self.current = {"release_group_id": rg_id, "label": label, "step": "tracklist"}
        self.core.hub.publish("hunter", self.state())

        try:
            releases = await self.core.catalog.releases_with_tracks(rg_id)
        except Exception as e:
            await self.core.journal.emit(
                "hunt.error", f"{label} : impossible de récupérer la tracklist MusicBrainz ({e})",
                level="error", artist_id=artist.id, release_group_id=rg_id,
            )
            return
        if not releases:
            await self._set_status(rg_id, previous_status, "Aucune édition connue sur MusicBrainz", searched=True)
            return

        await self._set_status(rg_id, AlbumStatus.SEARCHING)
        queries = build_queries(artist.name, rg.title)
        await self.core.journal.emit(
            "hunt.started",
            f"Recherche de « {label} » ({'manuelle' if trigger == 'manual' else 'automatique'}) — "
            f"profil « {profile.name} », requêtes : {', '.join(repr(q) for q in queries)}",
            artist_id=artist.id, release_group_id=rg_id,
            data={"queries": queries, "profile": profile.name, "formats": profile.formats, "trigger": trigger},
        )

        all_results: list[PeerResult] = []
        run_ids: list[int] = []
        for q in queries:
            self.current = {"release_group_id": rg_id, "label": label, "step": "search", "query": q}
            self.core.hub.publish("hunter", self.state())
            try:
                results = await self.core.engine.search(q, cfg.search_wait_seconds)
            except EngineUnavailable as e:
                await self._set_status(rg_id, AlbumStatus.WANTED, f"Soulseek indisponible : {e}")
                await self.core.journal.emit(
                    "hunt.skipped", f"{label} : recherche impossible, {e}",
                    level="warning", artist_id=artist.id, release_group_id=rg_id,
                )
                return
            files = sum(len(r.files) for r in results)
            async with self.core.db.session() as s:
                run = SearchRun(
                    release_group_id=rg_id, query=q, kind=trigger, result_count=files, peer_count=len(results)
                )
                s.add(run)
                await s.commit()
                run_ids.append(run.id)
            await self.core.journal.emit(
                "search.done",
                f"Requête « {q} » : {files} fichiers chez {len(results)} pairs",
                artist_id=artist.id, release_group_id=rg_id, data={"query": q, "files": files, "peers": len(results)},
            )
            all_results.extend(results)

        self.current = {"release_group_id": rg_id, "label": label, "step": "scoring"}
        options = [
            ReleaseOption(
                r.id,
                f"{r.title} ({r.date or '?'} · {r.country or '?'} · {r.formats or '?'} · {r.track_count} pistes)",
                [TrackRef(t.disc, t.position, t.title, (t.length_ms or 0) / 1000 or None) for t in r.tracks],
            )
            for r in releases
            if r.tracks
        ]
        # On privilégie l'édition choisie : si elle est définie, on la teste en premier (à score égal elle gagne)
        options.sort(key=lambda o: o.release_id != rg.selected_release_id)
        scored = rank_candidates(
            all_results, options, profile.formats, profile.max_missing_tracks, cfg.min_match, artist.name
        )

        # En amélioration : seul un format strictement meilleur que l'existant est utile
        if rg.imported_format:
            for c in scored:
                if not c.rejected and is_better_or_equal(rg.imported_format, c.format):
                    c.reject_reason = (
                        f"Pas mieux que la version présente ({FORMAT_LABELS.get(rg.imported_format, rg.imported_format)})"
                    )
            scored.sort(key=lambda c: (c.rejected, -c.score))

        valid = [c for c in scored if not c.rejected]
        keep = valid[:30] + [c for c in scored if c.rejected][:30]
        async with self.core.db.session() as s:
            # Les anciennes propositions non utilisées sont remplacées par les nouvelles
            old = await s.execute(
                select(Candidate).where(
                    Candidate.release_group_id == rg_id,
                    Candidate.status.in_([CandidateStatus.PROPOSED, CandidateStatus.REJECTED]),
                )
            )
            for o in old.scalars():
                await s.delete(o)
            rows = []
            for c in keep:
                row = Candidate(
                    release_group_id=rg_id,
                    search_run_id=run_ids[-1] if run_ids else None,
                    username=c.username,
                    directory=c.directory,
                    files=[f.to_dict() for f in c.audio_files] + [f.to_dict() | {"extra": True} for f in c.extra_files],
                    format=c.format,
                    score=c.score,
                    score_detail=c.detail,
                    status=CandidateStatus.REJECTED if c.rejected else CandidateStatus.PROPOSED,
                    reject_reason=c.reject_reason,
                    matched_release_id=c.release_id,
                    has_free_slots=c.has_free_slots,
                    queue_size=c.queue_size,
                    avg_speed=c.avg_speed,
                )
                s.add(row)
                rows.append(row)
            await s.commit()
            valid_ids = [r.id for r in rows if r.status == CandidateStatus.PROPOSED]

        rejections = summarize_rejections(scored)
        if not valid:
            reason = f"Aucun candidat valable parmi {len(scored)} dossiers"
            await self._set_status(rg_id, AlbumStatus.WANTED, reason, searched=True)
            await self.core.journal.emit(
                "hunt.no_candidate",
                f"{label} : {reason}. Nouvel essai dans {RETRY_HOURS} h."
                + (" Rejets : " + "; ".join(f"{k} ×{v}" for k, v in rejections.items()) if rejections else ""),
                level="warning", artist_id=artist.id, release_group_id=rg_id,
                data={"folders": len(scored), "rejections": rejections},
            )
            return

        best = valid[0]
        await self.core.journal.emit(
            "hunt.scored",
            f"{label} : {len(valid)} candidat(s) valable(s) sur {len(scored)} dossiers. "
            f"Meilleur : {best.username} · {best.directory} — {best.score}/100 "
            f"({FORMAT_LABELS.get(best.format or '', best.format)}, "
            f"{best.detail.get('match', {}).get('tracks_matched', '?')}/"
            f"{best.detail.get('match', {}).get('tracks_expected', '?')} pistes)",
            artist_id=artist.id, release_group_id=rg_id, candidate_id=valid_ids[0],
            data={
                "top": [
                    {"username": c.username, "directory": c.directory, "score": c.score, "format": c.format}
                    for c in valid[:5]
                ],
                "rejections": rejections,
            },
        )

        if artist.mode == ArtistMode.AUTO:
            await self._set_status(rg_id, AlbumStatus.SEARCHING, None, searched=True)
            await self.start_download(valid_ids[0], by="auto")
        else:
            n = min(cfg.proposals, len(valid))
            await self._set_status(
                rg_id, AlbumStatus.PENDING_APPROVAL, f"{n} proposition(s) en attente de validation", searched=True
            )
            await self.core.journal.emit(
                "hunt.awaiting_approval",
                f"{label} : {n} proposition(s) en attente de ta validation (artiste en mode validation)",
                artist_id=artist.id, release_group_id=rg_id,
            )

    # --- Téléchargement -----------------------------------------------------

    async def start_download(self, candidate_id: int, by: str = "user") -> None:
        cfg = (await self.core.settings.get()).hunter
        async with self.core.db.session() as s:
            c = await s.get(Candidate, candidate_id)
            if not c:
                return
            rg = await s.get(ReleaseGroup, c.release_group_id)
            assert rg
            artist = await s.get(Artist, rg.artist_id)
            assert artist
            dest = os.path.join(str(self.core.env.downloads_dir), f"album-{rg.id}", f"candidate-{c.id}")
            c.status = CandidateStatus.CHOSEN
            c.download_dir = dest
            files = [f for f in c.files if not f.get("extra") or cfg.download_covers]
            transfers = []
            for f in files:
                t = Transfer(
                    direction="download",
                    username=c.username,
                    remote_path=f["filename"],
                    local_path=os.path.join(dest, f["filename"].replace("\\", "/").rsplit("/", 1)[-1]),
                    size=f.get("size"),
                    state=TransferState.QUEUED,
                    candidate_id=c.id,
                    release_group_id=rg.id,
                )
                s.add(t)
                transfers.append(t)
            rg.status = AlbumStatus.DOWNLOADING
            rg.status_reason = f"Depuis {c.username}"
            await s.commit()
            label = f"{artist.name} – {rg.title}"
            username, directory, rg_id, artist_id = c.username, c.directory, rg.id, artist.id
            paths = [f["filename"] for f in files]
            for t in transfers:
                self.core.transfers.register("download", t.username, t.remote_path, t.id)

        self.core.hub.publish("album", {"id": rg_id, "status": AlbumStatus.DOWNLOADING})
        await self.core.journal.emit(
            "download.started",
            f"{label} : téléchargement de {len(paths)} fichiers depuis {username} "
            f"({directory}) vers {dest} — choisi {'automatiquement' if by == 'auto' else 'par toi'}",
            artist_id=artist_id, release_group_id=rg_id, candidate_id=candidate_id,
            data={"username": username, "directory": directory, "destination": dest, "files": paths, "by": by},
        )
        try:
            for p in paths:
                await self.core.engine.download(username, p, dest)
        except EngineUnavailable as e:
            await self.core.journal.emit(
                "download.error", f"{label} : téléchargement impossible, {e}", level="error",
                artist_id=artist_id, release_group_id=rg_id, candidate_id=candidate_id,
            )
            await self._fail_candidate(candidate_id, str(e), try_next=False)

    async def on_transfer_terminal(self, candidate_id: int) -> None:
        """Appelé quand un transfert lié à un candidat atteint un état final."""
        async with self.core.db.session() as s:
            c = await s.get(Candidate, candidate_id)
            if not c or c.status != CandidateStatus.CHOSEN:
                return
            ts = list((await s.execute(select(Transfer).where(Transfer.candidate_id == candidate_id))).scalars())
        audio = [t for t in ts if not _is_extra(t.remote_path)]
        if any(t.state not in TERMINAL for t in audio):
            return
        failed = [t for t in audio if t.state != TransferState.COMPLETE]
        if failed:
            reasons = Counter(t.error or t.state for t in failed)
            await self._fail_candidate(
                candidate_id,
                f"{len(failed)} fichier(s) en échec : " + ", ".join(f"{k} ×{v}" for k, v in reasons.items()),
            )
            return
        # Les fichiers annexes encore en cours sont abandonnés
        for t in ts:
            if t.state not in TERMINAL:
                await self.core.engine.abort(t.username, t.remote_path, "download")
        async with self.core.db.session() as s:
            c = await s.get(Candidate, candidate_id)
            assert c
            c.status = CandidateStatus.DOWNLOADED
            await s.commit()
        await self.core.journal.emit(
            "download.complete",
            f"Tous les fichiers de {c.username} sont arrivés ({len(audio)} pistes) — import en cours",
            release_group_id=c.release_group_id, candidate_id=candidate_id,
        )
        asyncio.create_task(self.core.importer.import_candidate(candidate_id))

    async def _fail_candidate(self, candidate_id: int, reason: str, try_next: bool = True) -> None:
        async with self.core.db.session() as s:
            c = await s.get(Candidate, candidate_id)
            if not c:
                return
            c.status = CandidateStatus.FAILED
            c.reject_reason = reason
            rg = await s.get(ReleaseGroup, c.release_group_id)
            assert rg
            artist = await s.get(Artist, rg.artist_id)
            assert artist
            pending = list(
                (await s.execute(select(Transfer).where(
                    Transfer.candidate_id == candidate_id, Transfer.state.not_in(list(TERMINAL))
                ))).scalars()
            )
            nxt = (
                await s.execute(
                    select(Candidate)
                    .where(Candidate.release_group_id == rg.id, Candidate.status == CandidateStatus.PROPOSED)
                    .order_by(Candidate.score.desc())
                )
            ).scalars().first()
            await s.commit()
            rg_id, label, mode = rg.id, f"{artist.name} – {rg.title}", artist.mode
            next_id = nxt.id if nxt else None
            next_label = f"{nxt.username} ({nxt.score}/100)" if nxt else None

        for t in pending:
            await self.core.engine.abort(t.username, t.remote_path, "download")

        await self.core.journal.emit(
            "download.failed", f"{label} : candidat abandonné — {reason}", level="warning",
            release_group_id=rg_id, candidate_id=candidate_id,
        )
        if try_next and next_id and mode == ArtistMode.AUTO:
            await self.core.journal.emit(
                "hunt.fallback", f"{label} : bascule sur le candidat suivant, {next_label}",
                release_group_id=rg_id, candidate_id=next_id,
            )
            await self.start_download(next_id, by="auto")
        elif try_next and next_id:
            await self._set_status(rg_id, AlbumStatus.PENDING_APPROVAL, "Le candidat choisi a échoué, choisis-en un autre")
        else:
            await self._set_status(rg_id, AlbumStatus.WANTED, f"Dernier essai échoué : {reason}")

    async def check_stalled(self) -> None:
        """Abandonne un candidat dont aucun fichier n'a démarré depuis STALL_MINUTES."""
        limit = datetime.now(UTC) - timedelta(minutes=STALL_MINUTES)
        async with self.core.db.session() as s:
            chosen = list(
                (await s.execute(select(Candidate).where(Candidate.status == CandidateStatus.CHOSEN))).scalars()
            )
            stalled = []
            for c in chosen:
                ts = list((await s.execute(select(Transfer).where(Transfer.candidate_id == c.id))).scalars())
                if not ts:
                    continue
                started = any(t.started_at is not None or t.bytes_transferred > 0 for t in ts)
                created = min(t.created_at for t in ts)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                if not started and created < limit:
                    stalled.append(c.id)
        for cid in stalled:
            await self._fail_candidate(cid, f"aucun transfert n'a démarré en {STALL_MINUTES} minutes (pair absent ou file pleine)")

    def state(self) -> dict:
        return {
            "current": self.current,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
        }


def _is_extra(path: str) -> bool:
    from ..quality import is_audio

    return not is_audio(path)
