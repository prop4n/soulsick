"""Soulseek chat: private messages and rooms, kept in the database with read state."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update

from ..messages import M
from ..models import ChatMessage, iso_utc
from ..slsk.engine import ChatEvent

if TYPE_CHECKING:
    from ..core import Core

log = logging.getLogger(__name__)

# Rooms can be very chatty: only the latest messages of each room are kept
ROOM_HISTORY = 2000
MAX_LENGTH = 2000


def message_dict(m: ChatMessage) -> dict:
    return {
        "id": m.id,
        "ts": iso_utc(m.ts),
        "kind": m.kind,
        "target": m.target,
        "username": m.username,
        "text": m.text,
        "outgoing": m.outgoing,
        "read": m.read,
    }


class ChatService:
    def __init__(self, core: Core) -> None:
        self.core = core
        self._inserted = 0

    # --- Rooms we stay in ---------------------------------------------------------

    async def joined_rooms(self) -> list[str]:
        return list((await self.core.settings.get_raw("chat") or {}).get("rooms", []))

    async def _set_rooms(self, rooms: list[str]) -> None:
        await self.core.settings.set_raw("chat", {"rooms": rooms})

    async def join(self, room: str) -> None:
        await self.core.engine.join_room(room)
        rooms = await self.joined_rooms()
        if room not in rooms:
            await self._set_rooms([*rooms, room])
            await self.core.journal.emit("chat.joined", M("chat.joined", room=room))
        self.core.hub.publish("chat_rooms", {"rooms": await self.joined_rooms()})

    async def leave(self, room: str) -> None:
        try:
            await self.core.engine.leave_room(room)
        finally:
            await self._set_rooms([r for r in await self.joined_rooms() if r != room])
            await self.core.journal.emit("chat.left", M("chat.left", room=room))
            self.core.hub.publish("chat_rooms", {"rooms": await self.joined_rooms()})

    async def on_room(self, room: str, joined: bool) -> None:
        self.core.hub.publish("chat_rooms", {"rooms": await self.joined_rooms(), "room": room, "joined": joined})

    # --- Messages -------------------------------------------------------------------

    async def _store(self, kind: str, target: str, username: str, text: str, outgoing: bool, ts: datetime | None = None) -> dict:
        async with self.core.db.session() as s:
            m = ChatMessage(
                kind=kind, target=target, username=username, text=text[:MAX_LENGTH], outgoing=outgoing,
                read=outgoing, ts=ts or datetime.now(UTC),
            )
            s.add(m)
            await s.commit()
            await s.refresh(m)
            data = message_dict(m)
        self.core.hub.publish("chat", data)
        self._inserted += 1
        if kind == "room" and self._inserted % 200 == 0:
            await self._prune()
        return data

    async def on_message(self, e: ChatEvent) -> None:
        ts = datetime.fromtimestamp(e.timestamp, UTC) if e.timestamp else None
        await self._store(e.kind, e.target, e.username, e.text, e.outgoing, ts)

    async def send(self, kind: str, target: str, text: str) -> dict | None:
        text = text.strip()[:MAX_LENGTH]
        if kind == "private":
            await self.core.engine.send_private(target, text)
            me = self.core.engine.config.username if self.core.engine.config else ""
            return await self._store("private", target, me or "", text, outgoing=True)
        # Room messages come back from the server and are stored then
        await self.core.engine.send_room(target, text)
        return None

    async def mark_read(self, kind: str, target: str) -> None:
        async with self.core.db.session() as s:
            await s.execute(
                update(ChatMessage)
                .where(ChatMessage.kind == kind, ChatMessage.target == target, ChatMessage.read.is_(False))
                .values(read=True)
            )
            await s.commit()
        self.core.hub.publish("chat_read", {"kind": kind, "target": target})

    async def forget(self, kind: str, target: str) -> int:
        async with self.core.db.session() as s:
            res = await s.execute(delete(ChatMessage).where(ChatMessage.kind == kind, ChatMessage.target == target))
            await s.commit()
        return res.rowcount

    async def messages(self, kind: str, target: str, before: int | None = None, limit: int = 100) -> list[dict]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.kind == kind, ChatMessage.target == target)
            .order_by(ChatMessage.id.desc())
            .limit(min(limit, 500))
        )
        if before:
            stmt = stmt.where(ChatMessage.id < before)
        async with self.core.db.session() as s:
            rows = list((await s.execute(stmt)).scalars())
        return [message_dict(m) for m in reversed(rows)]

    async def conversations(self) -> list[dict]:
        """Every private conversation and joined room, most recent first, with unread counts."""
        async with self.core.db.session() as s:
            last_ids = (
                select(func.max(ChatMessage.id).label("id"))
                .group_by(ChatMessage.kind, ChatMessage.target)
                .subquery()
            )
            lasts = list((await s.execute(select(ChatMessage).where(ChatMessage.id.in_(select(last_ids.c.id))))).scalars())
            unread = dict(
                ((k, t), n)
                for k, t, n in (
                    await s.execute(
                        select(ChatMessage.kind, ChatMessage.target, func.count())
                        .where(ChatMessage.read.is_(False))
                        .group_by(ChatMessage.kind, ChatMessage.target)
                    )
                ).all()
            )
        rooms = await self.joined_rooms()
        out = {
            (m.kind, m.target): {"kind": m.kind, "target": m.target, "last": message_dict(m), "unread": unread.get((m.kind, m.target), 0)}
            for m in lasts
            if m.kind == "private" or m.target in rooms
        }
        for r in rooms:
            out.setdefault(("room", r), {"kind": "room", "target": r, "last": None, "unread": 0})
        # Most recent first; a room just joined (no message yet) on top
        return sorted(out.values(), key=lambda c: (c["last"] or {}).get("ts") or "9999", reverse=True)

    async def unread_private(self) -> int:
        async with self.core.db.session() as s:
            return (
                await s.execute(
                    select(func.count()).where(ChatMessage.kind == "private", ChatMessage.read.is_(False))
                )
            ).scalar_one()

    async def _prune(self) -> None:
        async with self.core.db.session() as s:
            for room in (await s.execute(select(ChatMessage.target).where(ChatMessage.kind == "room").distinct())).scalars():
                cutoff = (
                    await s.execute(
                        select(ChatMessage.id)
                        .where(ChatMessage.kind == "room", ChatMessage.target == room)
                        .order_by(ChatMessage.id.desc())
                        .offset(ROOM_HISTORY)
                        .limit(1)
                    )
                ).scalar()
                if cutoff:
                    await s.execute(
                        delete(ChatMessage).where(
                            ChatMessage.kind == "room", ChatMessage.target == room, ChatMessage.id <= cutoff
                        )
                    )
            await s.commit()
