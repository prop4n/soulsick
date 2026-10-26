from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core import Core
from .deps import get_core, require_user

router = APIRouter(prefix="/api", tags=["discover"], dependencies=[Depends(require_user)])


class DismissIn(BaseModel):
    mbid: str


@router.get("/discover")
async def recommendations(core: Core = Depends(get_core)) -> dict:
    return await core.discover.recommendations()


@router.post("/discover/refresh")
async def refresh(core: Core = Depends(get_core)) -> dict:
    """Asks ListenBrainz again for every followed artist, now."""
    return {"refreshed": await core.discover.refresh_all()}


@router.post("/discover/dismiss")
async def dismiss(body: DismissIn, core: Core = Depends(get_core)) -> dict:
    await core.discover.dismiss(body.mbid)
    return {"ok": True}


@router.get("/artists/{aid}/similar")
async def similar(aid: int, core: Core = Depends(get_core)) -> list[dict]:
    return await core.discover.similar(aid)
