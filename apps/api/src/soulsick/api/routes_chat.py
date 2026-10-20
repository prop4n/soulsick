from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core import Core
from ..slsk.engine import EngineUnavailable
from .deps import get_core, require_user
from .errors import as_http, http_error

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(require_user)])

Kind = Literal["private", "room"]


class Target(BaseModel):
    kind: Kind
    target: str = Field(min_length=1, max_length=200)


class SendIn(Target):
    text: str = Field(min_length=1, max_length=2000)


class RoomIn(BaseModel):
    room: str = Field(min_length=1, max_length=200)



@router.get("")
async def overview(core: Core = Depends(get_core)) -> dict:
    return {
        "conversations": await core.chat.conversations(),
        "rooms": await core.chat.joined_rooms(),
        "unread_private": await core.chat.unread_private(),
        "me": core.engine.config.username if core.engine.config else None,
    }


@router.get("/messages")
async def messages(kind: Kind, target: str, before: int | None = None, limit: int = 100, core: Core = Depends(get_core)) -> list[dict]:
    return await core.chat.messages(kind, target, before, limit)


@router.post("/send")
async def send(body: SendIn, core: Core = Depends(get_core)) -> dict:
    if not body.text.strip():
        raise http_error(400, "error.empty_message")
    try:
        msg = await core.chat.send(body.kind, body.target, body.text)
    except EngineUnavailable as e:
        raise as_http(e) from e
    return {"ok": True, "message": msg}


@router.post("/read")
async def read(body: Target, core: Core = Depends(get_core)) -> dict:
    await core.chat.mark_read(body.kind, body.target)
    return {"ok": True}


@router.post("/forget")
async def forget(body: Target, core: Core = Depends(get_core)) -> dict:
    return {"removed": await core.chat.forget(body.kind, body.target)}


@router.get("/rooms")
async def room_list(core: Core = Depends(get_core)) -> list[dict]:
    try:
        rooms = await core.engine.room_list()
    except EngineUnavailable as e:
        raise as_http(e) from e
    except TimeoutError as e:
        raise http_error(504, "error.rooms_timeout") from e
    return sorted(rooms, key=lambda r: -r["users"])


@router.get("/rooms/users")
async def room_users(room: str, core: Core = Depends(get_core)) -> list[str]:
    try:
        return core.engine.room_users(room)
    except EngineUnavailable as e:
        raise as_http(e) from e


@router.post("/rooms/join")
async def join(body: RoomIn, core: Core = Depends(get_core)) -> dict:
    try:
        await core.chat.join(body.room)
    except EngineUnavailable as e:
        raise as_http(e) from e
    except TimeoutError as e:
        raise http_error(504, "error.room_join_timeout", room=body.room) from e
    return {"ok": True}


@router.post("/rooms/leave")
async def leave(body: RoomIn, core: Core = Depends(get_core)) -> dict:
    try:
        await core.chat.leave(body.room)
    except EngineUnavailable:
        pass  # forgotten locally anyway
    return {"ok": True}
