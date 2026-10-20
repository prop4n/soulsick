"""Append-only journal + real-time broadcast.

Every Soulsick decision or action goes through `Journal.emit`, which stores an
`Event` and pushes it to connected WebSocket clients through the `Hub`.
A `Msg` message is stored in English with its key + params under `data["_t"]`
so the UI can render it in another language.
"""

import asyncio
import logging
from typing import Any

from .db import Database
from .messages import Msg
from .models import Event, iso_utc

log = logging.getLogger(__name__)


class Hub:
    """Broadcast bus to WebSockets (one queue per client)."""

    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[dict]] = set()

    def subscribe(self) -> asyncio.Queue[dict]:
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
        self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict]) -> None:
        self._clients.discard(q)

    def publish(self, type_: str, data: Any) -> None:
        msg = {"type": type_, "data": data}
        for q in list(self._clients):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # Client too slow: drop it rather than block the engine
                self._clients.discard(q)


def event_to_dict(e: Event) -> dict:
    return {
        "id": e.id,
        "ts": iso_utc(e.ts),
        "kind": e.kind,
        "level": e.level,
        "message": e.message,
        "artist_id": e.artist_id,
        "release_group_id": e.release_group_id,
        "transfer_id": e.transfer_id,
        "candidate_id": e.candidate_id,
        "data": e.data or {},
    }


class Journal:
    def __init__(self, db: Database, hub: Hub) -> None:
        self.db = db
        self.hub = hub

    async def emit(
        self,
        kind: str,
        message: Msg | str,
        *,
        level: str = "info",
        artist_id: int | None = None,
        release_group_id: int | None = None,
        transfer_id: int | None = None,
        candidate_id: int | None = None,
        data: dict | None = None,
    ) -> None:
        if isinstance(message, Msg):
            data = {**(data or {}), "_t": message.to_json()}
            message = message.text
        getattr(log, "warning" if level == "warning" else "error" if level == "error" else "info")(
            "[%s] %s", kind, message
        )
        async with self.db.session() as s:
            e = Event(
                kind=kind,
                level=level,
                message=message,
                artist_id=artist_id,
                release_group_id=release_group_id,
                transfer_id=transfer_id,
                candidate_id=candidate_id,
                data=data or {},
            )
            s.add(e)
            await s.commit()
            await s.refresh(e)
        self.hub.publish("event", event_to_dict(e))
