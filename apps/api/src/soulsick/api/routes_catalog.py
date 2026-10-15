import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from ..core import Core
from ..journal import event_to_dict
from ..models import (
    AlbumStatus,
    Artist,
    ArtistMode,
    Candidate,
    CandidateStatus,
    Event,
    LibraryFile,
    Release,
    ReleaseGroup,
    SearchRun,
    Transfer,
)
from ..musicbrainz import MusicBrainzError
from ..services.transfers import transfer_to_dict
from .deps import get_core, require_user
from .serializers import artist_dict, candidate_dict, iso, library_file_dict, release_dict, rg_dict

router = APIRouter(prefix="/api", tags=["catalog"], dependencies=[Depends(require_user)])


# --- Artistes -------------------------------------------------------------------


@router.get("/musicbrainz/artists")
async def mb_search(q: str, core: Core = Depends(get_core)) -> list[dict]:
    try:
        results = await core.mb.search_artists(q)
    except MusicBrainzError as e:
        raise HTTPException(502, str(e)) from e
    async with core.db.session() as s:
        known = set((await s.execute(select(Artist.mbid))).scalars())
    return [r | {"in_library": r["mbid"] in known} for r in results]


class ArtistIn(BaseModel):
    mbid: str
    mode: ArtistMode = ArtistMode.VALIDATION
    quality_profile_id: int | None = None
    primary_types: list[str] = ["album", "ep"]
    secondary_types: list[str] = []
    monitor: str = "all"


class ArtistPatch(BaseModel):
    monitored: bool | None = None
    mode: ArtistMode | None = None
    quality_profile_id: int | None = None
    primary_types: list[str] | None = None
    secondary_types: list[str] | None = None


async def _artist_stats(core: Core, ids: list[int]) -> dict[int, dict]:
    async with core.db.session() as s:
        rows = (
            await s.execute(
                select(ReleaseGroup.artist_id, ReleaseGroup.status, func.count())
                .where(ReleaseGroup.artist_id.in_(ids))
                .group_by(ReleaseGroup.artist_id, ReleaseGroup.status)
            )
        ).all()
        covers = (
            await s.execute(
                select(ReleaseGroup.artist_id, ReleaseGroup.mbid, ReleaseGroup.first_release_date, ReleaseGroup.status)
                .where(ReleaseGroup.artist_id.in_(ids), ReleaseGroup.primary_type == "album")
            )
        ).all()
    out: dict[int, dict] = {i: {"total": 0, "monitored": 0, "imported": 0, "wanted": 0, "attention": 0} for i in ids}
    for aid, status, n in rows:
        st = out[aid]
        st["total"] += n
        if status == AlbumStatus.IMPORTED:
            st["imported"] += n
        elif status in (AlbumStatus.WANTED, AlbumStatus.SEARCHING, AlbumStatus.DOWNLOADING, AlbumStatus.IMPORTING):
            st["wanted"] += n
        elif status in (AlbumStatus.PENDING_APPROVAL, AlbumStatus.NEEDS_REVIEW):
            st["attention"] += n
        if status != AlbumStatus.IGNORED:
            st["monitored"] += n
    # Pochette représentative : le dernier album présent, sinon le dernier album
    best: dict[int, tuple] = {}
    for aid, mbid, date, status in covers:
        key = (status == AlbumStatus.IMPORTED, date or "")
        if aid not in best or key > best[aid][0]:
            best[aid] = (key, mbid)
    for aid, (_, mbid) in best.items():
        out[aid]["cover_mbid"] = mbid
    return out


@router.get("/artists")
async def list_artists(core: Core = Depends(get_core)) -> list[dict]:
    async with core.db.session() as s:
        artists = list((await s.execute(select(Artist).order_by(Artist.sort_name))).scalars())
    stats = await _artist_stats(core, [a.id for a in artists])
    return [artist_dict(a, stats.get(a.id)) for a in artists]


@router.post("/artists")
async def add_artist(body: ArtistIn, core: Core = Depends(get_core)) -> dict:
    try:
        a = await core.catalog.add_artist(
            body.mbid,
            mode=body.mode,
            quality_profile_id=body.quality_profile_id,
            primary_types=body.primary_types,
            secondary_types=body.secondary_types,
            monitor=body.monitor,
        )
    except MusicBrainzError as e:
        raise HTTPException(502, str(e)) from e
    stats = await _artist_stats(core, [a.id])
    return artist_dict(a, stats.get(a.id))


@router.get("/artists/{aid}")
async def get_artist(aid: int, core: Core = Depends(get_core)) -> dict:
    async with core.db.session() as s:
        a = await s.get(Artist, aid)
        if not a:
            raise HTTPException(404)
        rgs = list(
            (
                await s.execute(
                    select(ReleaseGroup)
                    .where(ReleaseGroup.artist_id == aid)
                    .order_by(desc(ReleaseGroup.first_release_date))
                )
            ).scalars()
        )
    stats = await _artist_stats(core, [aid])
    return artist_dict(a, stats.get(aid)) | {"release_groups": [rg_dict(rg) for rg in rgs]}


@router.patch("/artists/{aid}")
async def patch_artist(aid: int, body: ArtistPatch, core: Core = Depends(get_core)) -> dict:
    changes = body.model_dump(exclude_unset=True)
    async with core.db.session() as s:
        a = await s.get(Artist, aid)
        if not a:
            raise HTTPException(404)
        for k, v in changes.items():
            setattr(a, k, v)
        await s.commit()
        await s.refresh(a)
    labels = {
        "monitored": lambda v: "suivi activé" if v else "suivi désactivé",
        "mode": lambda v: "mode automatique" if v == "auto" else "mode validation",
        "quality_profile_id": lambda v: f"profil qualité #{v}",
        "primary_types": lambda v: "types : " + ", ".join(v),
        "secondary_types": lambda v: "secondaires : " + (", ".join(v) or "aucun"),
    }
    await core.journal.emit(
        "artist.updated",
        f"{a.name} : " + ", ".join(labels[k](v) for k, v in changes.items() if k in labels),
        artist_id=aid, data=changes,
    )
    stats = await _artist_stats(core, [aid])
    return artist_dict(a, stats.get(aid))


@router.delete("/artists/{aid}")
async def delete_artist(aid: int, core: Core = Depends(get_core)) -> dict:
    await core.catalog.delete_artist(aid)
    return {"ok": True}


@router.post("/artists/{aid}/sync")
async def sync_artist(aid: int, core: Core = Depends(get_core)) -> dict:
    asyncio.create_task(core.catalog.sync_artist(aid))
    return {"ok": True}


@router.post("/artists/{aid}/hunt")
async def hunt_artist(aid: int, core: Core = Depends(get_core)) -> dict:
    async with core.db.session() as s:
        ids = list(
            (
                await s.execute(
                    select(ReleaseGroup.id).where(
                        ReleaseGroup.artist_id == aid, ReleaseGroup.status == AlbumStatus.WANTED
                    )
                )
            ).scalars()
        )

    async def run():
        for i in ids:
            await core.hunter.hunt(i, trigger="manual")

    asyncio.create_task(run())
    return {"queued": len(ids)}


# --- Albums ---------------------------------------------------------------------


@router.get("/albums")
async def list_albums(
    status: str | None = None, core: Core = Depends(get_core), limit: int = 500
) -> list[dict]:
    stmt = select(ReleaseGroup, Artist).join(Artist, Artist.id == ReleaseGroup.artist_id)
    if status:
        stmt = stmt.where(ReleaseGroup.status.in_(status.split(",")))
    stmt = stmt.order_by(desc(ReleaseGroup.updated_at)).limit(limit)
    async with core.db.session() as s:
        rows = (await s.execute(stmt)).all()
    return [rg_dict(rg, a) for rg, a in rows]


@router.get("/albums/{rid}")
async def get_album(rid: int, core: Core = Depends(get_core)) -> dict:
    async with core.db.session() as s:
        rg = await s.get(ReleaseGroup, rid)
        if not rg:
            raise HTTPException(404)
        artist = await s.get(Artist, rg.artist_id)
    try:
        releases = await core.catalog.releases_with_tracks(rid)
    except MusicBrainzError:
        releases = []
    async with core.db.session() as s:
        rg = await s.get(ReleaseGroup, rid)
        assert rg
        cands = list(
            (
                await s.execute(
                    select(Candidate)
                    .where(Candidate.release_group_id == rid)
                    .order_by(Candidate.status == CandidateStatus.REJECTED, desc(Candidate.score))
                )
            ).scalars()
        )
        runs = list(
            (
                await s.execute(
                    select(SearchRun).where(SearchRun.release_group_id == rid).order_by(desc(SearchRun.id)).limit(20)
                )
            ).scalars()
        )
        rel_mbids = [r.mbid for r in releases]
        files = list(
            (
                await s.execute(
                    select(LibraryFile)
                    .where(
                        (LibraryFile.release_group_mbid == rg.mbid)
                        | (LibraryFile.release_mbid.in_(rel_mbids) if rel_mbids else False)
                    )
                    .order_by(LibraryFile.path)
                )
            ).scalars()
        )
        transfers = list(
            (
                await s.execute(
                    select(Transfer).where(Transfer.release_group_id == rid).order_by(desc(Transfer.id)).limit(200)
                )
            ).scalars()
        )
        events = list(
            (
                await s.execute(
                    select(Event).where(Event.release_group_id == rid).order_by(desc(Event.id)).limit(200)
                )
            ).scalars()
        )
    return rg_dict(rg, artist) | {
        "releases": [release_dict(r) for r in releases],
        "candidates": [candidate_dict(c) for c in cands],
        "search_runs": [
            {
                "id": r.id,
                "query": r.query,
                "kind": r.kind,
                "started_at": iso(r.started_at),
                "result_count": r.result_count,
                "peer_count": r.peer_count,
            }
            for r in runs
        ],
        "files": [library_file_dict(f) for f in files],
        "transfers": [transfer_to_dict(t) | (core.transfers.live(t.id) or {}) for t in transfers],
        "events": [event_to_dict(e) for e in events],
    }


class AlbumPatch(BaseModel):
    monitored: bool | None = None
    selected_release_id: int | None = None


@router.patch("/albums/{rid}")
async def patch_album(rid: int, body: AlbumPatch, core: Core = Depends(get_core)) -> dict:
    if body.monitored is not None:
        await core.catalog.set_album_monitored(rid, body.monitored)
    if body.selected_release_id is not None:
        async with core.db.session() as s:
            rg = await s.get(ReleaseGroup, rid)
            rel = await s.get(Release, body.selected_release_id)
            if not rg or not rel or rel.release_group_id != rid:
                raise HTTPException(400, "Édition invalide")
            rg.selected_release_id = rel.id
            await s.commit()
        await core.journal.emit(
            "album.release_selected",
            f"« {rg.title} » : édition retenue → {rel.title} ({rel.date or '?'}, {rel.country or '?'}, "
            f"{rel.formats}, {rel.track_count} pistes)",
            artist_id=rg.artist_id, release_group_id=rid,
        )
    async with core.db.session() as s:
        rg = await s.get(ReleaseGroup, rid)
        return rg_dict(rg)


@router.post("/albums/{rid}/hunt")
async def hunt_album(rid: int, core: Core = Depends(get_core)) -> dict:
    asyncio.create_task(core.hunter.hunt(rid, trigger="manual"))
    return {"ok": True}


@router.post("/candidates/{cid}/approve")
async def approve(cid: int, core: Core = Depends(get_core)) -> dict:
    async with core.db.session() as s:
        c = await s.get(Candidate, cid)
        if not c:
            raise HTTPException(404)
        if c.status not in (CandidateStatus.PROPOSED, CandidateStatus.REJECTED, CandidateStatus.FAILED):
            raise HTTPException(409, "Ce candidat est déjà en cours ou utilisé")
    await core.hunter.start_download(cid, by="user")
    return {"ok": True}


@router.post("/albums/{rid}/dismiss")
async def dismiss(rid: int, core: Core = Depends(get_core)) -> dict:
    """Refuse toutes les propositions : l'album repasse en « recherché »."""
    async with core.db.session() as s:
        rg = await s.get(ReleaseGroup, rid)
        if not rg:
            raise HTTPException(404)
        rg.status = AlbumStatus.WANTED if rg.monitored else AlbumStatus.IGNORED
        rg.status_reason = "Propositions refusées"
        await s.commit()
    await core.journal.emit(
        "hunt.dismissed", f"« {rg.title} » : propositions refusées, nouvel essai plus tard",
        artist_id=rg.artist_id, release_group_id=rid,
    )
    return {"ok": True}


@router.get("/candidates/{cid}/plan")
async def get_plan(cid: int, core: Core = Depends(get_core)) -> dict:
    built = await core.importer.build_plan(cid)
    if built is None:
        raise HTTPException(404)
    plan, info = built
    return {"plan": plan, "info": info}


class PlanIn(BaseModel):
    release_id: int
    plan: list[dict]


@router.post("/candidates/{cid}/import")
async def apply_plan(cid: int, body: PlanIn, core: Core = Depends(get_core)) -> dict:
    try:
        await core.importer.apply_plan(cid, body.plan, body.release_id, by_user=True)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}
