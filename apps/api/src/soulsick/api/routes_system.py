import asyncio
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from ..core import Core
from ..journal import event_to_dict
from ..models import AlbumStatus, Artist, Event, LibraryFile, QualityProfile, ReleaseGroup, Transfer
from ..quality import ALL_FORMATS
from ..settings_store import AppSettings
from .deps import get_core, require_user
from .serializers import library_file_dict, profile_dict

router = APIRouter(prefix="/api", tags=["system"], dependencies=[Depends(require_user)])
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@router.get("/status")
async def status(core: Core = Depends(get_core)) -> dict:
    async with core.db.session() as s:
        counts = dict(
            (await s.execute(select(ReleaseGroup.status, func.count()).group_by(ReleaseGroup.status))).all()
        )
        artists = (await s.execute(select(func.count()).select_from(Artist))).scalar_one()
        lib = (await s.execute(select(func.count(), func.coalesce(func.sum(LibraryFile.size), 0)).select_from(LibraryFile))).one()
        active = dict(
            (
                await s.execute(
                    select(Transfer.direction, func.count())
                    .where(Transfer.state.in_(["queued", "initializing", "transferring"]))
                    .group_by(Transfer.direction)
                )
            ).all()
        )
    return {
        "engine": core.engine.status(),
        "hunter": core.hunter.state(),
        "library": {"files": lib[0], "size": lib[1], "scanning": core.library.scanning},
        "artists": artists,
        "albums": {k: v for k, v in counts.items()},
        "attention": counts.get(AlbumStatus.PENDING_APPROVAL, 0) + counts.get(AlbumStatus.NEEDS_REVIEW, 0),
        "active_transfers": {"download": active.get("download", 0), "upload": active.get("upload", 0)},
        "paths": {
            "music": str(core.env.music_dir.resolve()),
            "downloads": str(core.env.downloads_dir.resolve()),
            "config": str(core.env.config_dir.resolve()),
        },
    }


# --- Réglages -----------------------------------------------------------------


def _redact(s: AppSettings) -> dict:
    d = s.model_dump()
    d["soulseek"]["password"] = "••••••••" if s.soulseek.password else ""
    d["navidrome"]["password"] = "••••••••" if s.navidrome.password else ""
    return d


@router.get("/settings")
async def get_settings(core: Core = Depends(get_core)) -> dict:
    return _redact(await core.settings.get())


@router.put("/settings")
async def put_settings(body: AppSettings, core: Core = Depends(get_core)) -> dict:
    current = await core.settings.get()
    if body.soulseek.password == "••••••••":
        body.soulseek.password = current.soulseek.password
    if body.navidrome.password == "••••••••":
        body.navidrome.password = current.navidrome.password
    await core.settings.save(body)
    changed = [k for k in ("soulseek", "hunter", "library", "navidrome") if getattr(body, k) != getattr(current, k)]
    await core.journal.emit(
        "settings.updated", "Réglages modifiés : " + (", ".join(changed) or "aucun changement"), data={"sections": changed}
    )
    if body.soulseek != current.soulseek:
        only_library = body.soulseek.model_copy(update={"share_library": current.soulseek.share_library}) == current.soulseek
        if only_library:
            # Activer/désactiver le partage de /music ne nécessite pas de reconnexion
            asyncio.create_task(core.shares.rescan())
        else:
            await core.restart_engine()
    return _redact(body)


@router.post("/settings/navidrome/test")
async def test_navidrome(core: Core = Depends(get_core)) -> dict:
    return await core.navidrome.trigger_scan(force=True)


@router.post("/hunter/run")
async def run_hunter(core: Core = Depends(get_core)) -> dict:
    """Lance tout de suite une chasse sur les albums recherchés (sans attendre l'intervalle)."""
    if not core.engine.logged_in:
        raise HTTPException(503, "Non connecté au réseau Soulseek")
    limit = (await core.settings.get()).hunter.max_searches_per_run
    async with core.db.session() as s:
        n = (
            await s.execute(
                select(func.count())
                .select_from(ReleaseGroup)
                .join(Artist, Artist.id == ReleaseGroup.artist_id)
                .where(
                    ReleaseGroup.status == AlbumStatus.WANTED,
                    ReleaseGroup.monitored.is_(True),
                    Artist.monitored.is_(True),
                )
            )
        ).scalar_one()
    asyncio.create_task(core.hunter.run_wanted(limit, force=True))
    return {"queued": min(n, limit)}


@router.post("/engine/reconnect")
async def reconnect(core: Core = Depends(get_core)) -> dict:
    await core.restart_engine()
    return {"ok": True}


# --- Profils qualité -----------------------------------------------------------


class ProfileIn(BaseModel):
    name: str = Field(min_length=1)
    formats: list[str]
    upgrade_until: str | None = None
    max_missing_tracks: int = Field(default=0, ge=0)


@router.get("/formats")
async def formats() -> list[dict]:
    return [{"key": k, "label": label} for k, label in ALL_FORMATS]


@router.get("/profiles")
async def list_profiles(core: Core = Depends(get_core)) -> list[dict]:
    async with core.db.session() as s:
        return [profile_dict(p) for p in (await s.execute(select(QualityProfile).order_by(QualityProfile.id))).scalars()]


@router.post("/profiles")
async def create_profile(body: ProfileIn, core: Core = Depends(get_core)) -> dict:
    async with core.db.session() as s:
        p = QualityProfile(**body.model_dump())
        s.add(p)
        await s.commit()
        await s.refresh(p)
    await core.journal.emit("profile.created", f"Profil qualité « {p.name} » créé : {' > '.join(p.formats)}")
    return profile_dict(p)


@router.put("/profiles/{pid}")
async def update_profile(pid: int, body: ProfileIn, core: Core = Depends(get_core)) -> dict:
    async with core.db.session() as s:
        p = await s.get(QualityProfile, pid)
        if not p:
            raise HTTPException(404)
        for k, v in body.model_dump().items():
            setattr(p, k, v)
        await s.commit()
    await core.journal.emit("profile.updated", f"Profil qualité « {p.name} » modifié : {' > '.join(p.formats)}")
    return profile_dict(p)


@router.delete("/profiles/{pid}")
async def delete_profile(pid: int, core: Core = Depends(get_core)) -> dict:
    async with core.db.session() as s:
        used = (await s.execute(select(func.count()).where(Artist.quality_profile_id == pid))).scalar_one()
        if used:
            raise HTTPException(409, f"Profil utilisé par {used} artiste(s)")
        p = await s.get(QualityProfile, pid)
        if p:
            await s.delete(p)
            await s.commit()
    return {"ok": True}


# --- Journal -------------------------------------------------------------------


@router.get("/events")
async def events(
    core: Core = Depends(get_core),
    before: int | None = None,
    limit: int = 100,
    kind: str | None = None,
    level: str | None = None,
    artist_id: int | None = None,
    release_group_id: int | None = None,
    q: str | None = None,
) -> list[dict]:
    stmt = select(Event).order_by(desc(Event.id)).limit(min(limit, 500))
    if before:
        stmt = stmt.where(Event.id < before)
    if kind:
        stmt = stmt.where(Event.kind.startswith(kind))
    if level:
        stmt = stmt.where(Event.level == level)
    if artist_id:
        stmt = stmt.where(Event.artist_id == artist_id)
    if release_group_id:
        stmt = stmt.where(Event.release_group_id == release_group_id)
    if q:
        stmt = stmt.where(Event.message.ilike(f"%{q}%"))
    async with core.db.session() as s:
        return [event_to_dict(e) for e in (await s.execute(stmt)).scalars()]


# --- Console (logs techniques en direct) -----------------------------------------


@router.get("/logs")
async def logs(after: int = 0, limit: int = 1000) -> dict:
    from ..logbuffer import BUFFER

    return {"logs": BUFFER.since(after, min(limit, 3000)), "capacity": BUFFER.records.maxlen}


@router.get("/activity")
async def activity(core: Core = Depends(get_core)) -> dict:
    """Ce sur quoi Soulsick travaille en ce moment."""
    now = time.time()
    searches = [
        {
            "ticket": ls.ticket,
            "query": ls.query,
            "age": round(now - ls.started, 1),
            "responses": len(ls.results),
            "files": sum(len(r.files) for r in ls.results),
        }
        for ls in sorted(core.engine.searches.values(), key=lambda x: -x.started)
        if now - ls.started < 60
    ]
    return {
        "hunter": core.hunter.state(),
        "searches": searches,
        "library_scanning": core.library.scanning,
        "retrying": len(core.hunter._retrying),
        "engine": core.engine.status(),
    }


# --- Bibliothèque --------------------------------------------------------------


@router.post("/library/scan")
async def scan_library(core: Core = Depends(get_core)) -> dict:
    asyncio.create_task(core.library.scan())
    return {"ok": True}


@router.get("/library/unmatched")
async def unmatched(core: Core = Depends(get_core)) -> list[dict]:
    return [library_file_dict(f) for f in await core.library.unmatched_files()]


# --- Pochettes -----------------------------------------------------------------


@router.get("/covers/{kind}/{mbid}")
async def cover(kind: str, mbid: str, size: int = 500, core: Core = Depends(get_core)):
    if kind not in {"release-group", "release"} or size not in {250, 500, 1200} or not _UUID.fullmatch(mbid):
        raise HTTPException(400)
    path = await core.mb.cover(kind, mbid, size)
    if not path:
        return Response(status_code=404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})
