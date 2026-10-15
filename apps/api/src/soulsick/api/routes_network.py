import asyncio
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, select

from ..core import Core
from ..models import Share, Transfer, TransferState
from ..scoring import group_results
from ..services.transfers import TERMINAL, transfer_to_dict
from ..slsk.engine import EngineUnavailable
from .deps import get_core, require_user
from .serializers import share_dict

router = APIRouter(prefix="/api", tags=["network"], dependencies=[Depends(require_user)])


def _unavailable(e: Exception) -> HTTPException:
    return HTTPException(503, str(e))


# --- Recherche manuelle -----------------------------------------------------------


class SearchIn(BaseModel):
    query: str = Field(min_length=2)


@router.post("/search")
async def start_search(body: SearchIn, core: Core = Depends(get_core)) -> dict:
    try:
        live = await core.engine.start_search(body.query)
    except EngineUnavailable as e:
        raise _unavailable(e) from e
    await core.journal.emit("search.manual", f"Recherche manuelle « {body.query} »", data={"ticket": live.ticket})
    return {"ticket": live.ticket, "query": live.query}


@router.get("/search/{ticket}")
async def get_search(ticket: int, core: Core = Depends(get_core)) -> dict:
    live = core.engine.searches.get(ticket)
    if not live:
        raise HTTPException(404, "Recherche expirée")
    groups = group_results(live.results)
    folders = []
    for g in groups:
        files = [f.to_dict() for f in g.audio_files] + [f.to_dict() | {"extra": True} for f in g.extra_files]
        formats = sorted({f["format"] for f in files if f.get("format")})
        folders.append(
            {
                "username": g.username,
                "directory": g.directory,
                "files": files,
                "formats": formats,
                "audio_count": len(g.audio_files),
                "size": sum(f.size for f in g.audio_files),
                "has_free_slots": g.has_free_slots,
                "avg_speed": g.avg_speed,
                "queue_size": g.queue_size,
            }
        )
    folders.sort(key=lambda f: (not f["has_free_slots"], f["queue_size"], -f["avg_speed"]))
    return {
        "ticket": ticket,
        "query": live.query,
        "elapsed": round(time.time() - live.started, 1),
        "peer_count": len(live.results),
        "file_count": sum(len(r.files) for r in live.results),
        "folders": folders[:300],
    }


class DownloadIn(BaseModel):
    username: str
    files: list[str] = Field(min_length=1)


@router.post("/downloads")
async def download(body: DownloadIn, core: Core = Depends(get_core)) -> dict:
    try:
        ids = await core.transfers.download_manual(body.username, body.files)
    except EngineUnavailable as e:
        raise _unavailable(e) from e
    return {"ids": ids}


# --- Transferts -------------------------------------------------------------------


@router.get("/transfers")
async def list_transfers(direction: str = "download", limit: int = 300, core: Core = Depends(get_core)) -> list[dict]:
    async with core.db.session() as s:
        rows = list(
            (
                await s.execute(
                    select(Transfer).where(Transfer.direction == direction).order_by(desc(Transfer.id)).limit(limit)
                )
            ).scalars()
        )
    return [transfer_to_dict(t) | (core.transfers.live(t.id) or {}) if t.state not in TERMINAL else transfer_to_dict(t) for t in rows]


async def _get_transfer(core: Core, tid: int) -> Transfer:
    async with core.db.session() as s:
        t = await s.get(Transfer, tid)
    if not t:
        raise HTTPException(404)
    return t


@router.post("/transfers/{tid}/cancel")
async def cancel_transfer(tid: int, core: Core = Depends(get_core)) -> dict:
    t = await _get_transfer(core, tid)
    try:
        await core.engine.abort(t.username, t.remote_path, t.direction)
    except EngineUnavailable as e:
        raise _unavailable(e) from e
    await core.journal.emit(
        "transfer.cancelled", f"Transfert annulé par toi : {t.remote_path} ({t.username})", transfer_id=tid,
        release_group_id=t.release_group_id,
    )
    return {"ok": True}


@router.post("/transfers/{tid}/retry")
async def retry_transfer(tid: int, core: Core = Depends(get_core)) -> dict:
    t = await _get_transfer(core, tid)
    if t.direction != "download":
        raise HTTPException(400)
    try:
        core.transfers.register("download", t.username, t.remote_path, t.id)
        dest = os.path.dirname(t.local_path) if t.local_path else os.path.join(str(core.env.downloads_dir), "manual")
        await core.engine.download(t.username, t.remote_path, dest)
    except EngineUnavailable as e:
        raise _unavailable(e) from e
    async with core.db.session() as s:
        row = await s.get(Transfer, tid)
        assert row
        row.state = TransferState.QUEUED
        row.error = None
        await s.commit()
    return {"ok": True}


@router.post("/transfers/clear")
async def clear_transfers(direction: str = "download", core: Core = Depends(get_core)) -> dict:
    """Retire de la liste les transferts terminés (l'historique reste dans le journal)."""
    async with core.db.session() as s:
        res = await s.execute(
            delete(Transfer).where(Transfer.direction == direction, Transfer.state.in_(list(TERMINAL)))
        )
        await s.commit()
    return {"removed": res.rowcount}


# --- Parcourir un pair -----------------------------------------------------------


@router.get("/users/{username}/browse")
async def browse(username: str, core: Core = Depends(get_core)) -> dict:
    try:
        data = await core.engine.browse(username)
    except EngineUnavailable as e:
        raise _unavailable(e) from e
    except TimeoutError as e:
        raise HTTPException(504, f"{username} n'a pas répondu (hors ligne ou injoignable)") from e
    await core.journal.emit(
        "browse", f"Partages de {username} parcourus : {len(data['directories'])} dossiers",
        data={"username": username},
    )
    return data


# --- Partages --------------------------------------------------------------------


class ShareIn(BaseModel):
    path: str
    enabled: bool = True
    allowed_extensions: list[str] = []
    exclude_patterns: list[str] = []


@router.get("/shares")
async def list_shares(core: Core = Depends(get_core)) -> dict:
    settings = await core.settings.get()
    async with core.db.session() as s:
        shares = [share_dict(x) for x in (await s.execute(select(Share).order_by(Share.path))).scalars()]
    for sh in shares:
        sh["exists"] = os.path.isdir(sh["path"])
    return {
        "shares": shares,
        "library": {"path": str(core.env.music_dir.resolve()), "shared": settings.soulseek.share_library},
        "engine": {
            "shared_folders": core.engine.status()["shared_folders"],
            "shared_files": core.engine.status()["shared_files"],
        },
    }


@router.post("/shares")
async def create_share(body: ShareIn, core: Core = Depends(get_core)) -> dict:
    path = os.path.abspath(body.path)
    if not os.path.isdir(path):
        raise HTTPException(400, f"Dossier introuvable dans le conteneur : {path}")
    async with core.db.session() as s:
        if (await s.execute(select(Share).where(Share.path == path))).scalar_one_or_none():
            raise HTTPException(409, "Ce dossier est déjà partagé")
        sh = Share(**(body.model_dump() | {"path": path}))
        s.add(sh)
        await s.commit()
        await s.refresh(sh)
    await core.journal.emit("share.added", f"Dossier partagé ajouté : {path}", data=body.model_dump())
    asyncio.create_task(core.shares.rescan())
    return share_dict(sh)


@router.put("/shares/{sid}")
async def update_share(sid: int, body: ShareIn, core: Core = Depends(get_core)) -> dict:
    async with core.db.session() as s:
        sh = await s.get(Share, sid)
        if not sh:
            raise HTTPException(404)
        sh.enabled = body.enabled
        sh.allowed_extensions = body.allowed_extensions
        sh.exclude_patterns = body.exclude_patterns
        await s.commit()
    await core.journal.emit(
        "share.updated",
        f"Règles du partage {sh.path} modifiées : "
        f"{'actif' if body.enabled else 'désactivé'}, extensions {', '.join(body.allowed_extensions) or 'par défaut'}, "
        f"exclusions {', '.join(body.exclude_patterns) or 'aucune'}",
        data=body.model_dump(),
    )
    asyncio.create_task(core.shares.rescan())
    return share_dict(sh)


@router.delete("/shares/{sid}")
async def delete_share(sid: int, core: Core = Depends(get_core)) -> dict:
    async with core.db.session() as s:
        sh = await s.get(Share, sid)
        if sh:
            await s.delete(sh)
            await s.commit()
            await core.journal.emit("share.removed", f"Dossier retiré des partages : {sh.path}")
    asyncio.create_task(core.shares.rescan())
    return {"ok": True}


@router.get("/shares/{sid}/preview")
async def preview_share(sid: int, core: Core = Depends(get_core)) -> dict:
    try:
        return await core.shares.preview(sid)
    except KeyError as e:
        raise HTTPException(404) from e


@router.post("/shares/rescan")
async def rescan(core: Core = Depends(get_core)) -> dict:
    asyncio.create_task(core.shares.rescan())
    return {"ok": True}


@router.get("/fs")
async def list_dirs(path: str = "/", core: Core = Depends(get_core)) -> dict:
    """Sélecteur de dossier pour ajouter un partage (dossiers uniquement)."""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise HTTPException(404)
    try:
        entries = sorted(
            e.name for e in os.scandir(path) if e.is_dir(follow_symlinks=True) and not e.name.startswith(".")
        )
    except PermissionError as e:
        raise HTTPException(403, "Accès refusé") from e
    return {"path": path, "parent": os.path.dirname(path) if path != "/" else None, "dirs": entries[:500]}
