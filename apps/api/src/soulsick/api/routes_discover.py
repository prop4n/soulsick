import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..core import Core
from .deps import get_core, require_user
from .routes_system import _UUID

router = APIRouter(prefix="/api", tags=["discover"], dependencies=[Depends(require_user)])


class DismissIn(BaseModel):
    mbid: str
    # Passed for now: proposed again after that many days. None: not interested, never again
    days: int | None = Field(None, ge=1, le=365)


class WantIn(BaseModel):
    artist_mbid: str
    release_group_mbid: str


def _mbid(value: str) -> str:
    if not _UUID.fullmatch(value):
        raise HTTPException(400)
    return value


@router.get("/discover")
async def recommendations(core: Core = Depends(get_core)) -> dict:
    return await core.discover.recommendations()


@router.post("/discover/refresh")
async def refresh(core: Core = Depends(get_core)) -> dict:
    """Asks ListenBrainz again for every followed artist, now."""
    return {"refreshed": await core.discover.refresh_all()}


@router.post("/discover/dismiss")
async def dismiss(body: DismissIn, core: Core = Depends(get_core)) -> dict:
    await core.discover.dismiss(body.mbid, body.days)
    return {"ok": True}


@router.get("/discover/deck")
async def deck(avoid: str | None = None, core: Core = Depends(get_core)) -> dict:
    """A few artists to discover from one angle, a different one from the last visit."""
    return await core.discover.deck(avoid)


@router.get("/discover/profile/{mbid}")
async def profile(mbid: str, core: Core = Depends(get_core)) -> dict:
    found = await core.discover.profile(_mbid(mbid))
    return (await core.discover.with_states([found]))[0] or {}


@router.get("/discover/preview/{mbid}")
async def preview(mbid: str, core: Core = Depends(get_core)):
    audio = await core.discover.preview(_mbid(mbid))
    if not audio:
        return Response(status_code=404)
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/discover/want")
async def want(body: WantIn, core: Core = Depends(get_core)) -> dict:
    """Its artist and the album are read on MusicBrainz first: in the background, the album
    shows up on its artist's page a few seconds later."""
    asyncio.create_task(core.discover.want(_mbid(body.artist_mbid), _mbid(body.release_group_mbid)))
    return {"ok": True}


@router.get("/artists/{aid}/similar")
async def similar(aid: int, core: Core = Depends(get_core)) -> list[dict]:
    return await core.discover.similar(aid)


@router.get("/artist-photos/{mbid}")
async def artist_photo(mbid: str, core: Core = Depends(get_core)):
    if not _UUID.fullmatch(mbid):
        raise HTTPException(400)
    path = await core.discover.photo(mbid)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=86400"})
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})
