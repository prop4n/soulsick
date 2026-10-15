"""Journal append-only + diffusion temps réel.

Chaque décision ou action de Soulsick passe par `Journal.emit`, qui persiste un
`Event` et le pousse aux clients WebSocket connectés via le `Hub`.
"""

import asyncio
import logging
from typing import Any

from .db import Database
from .models import Event

log = logging.getLogger(__name__)


class Hub:
    """Bus de diffusion vers les WebSockets (une file par client)."""

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
                # Client trop lent : on le déconnecte plutôt que de bloquer le moteur
                self._clients.discard(q)


def event_to_dict(e: Event) -> dict:
    return {
        "id": e.id,
        "ts": e.ts.isoformat(),
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
        message: str,
        *,
        level: str = "info",
        artist_id: int | None = None,
        release_group_id: int | None = None,
        transfer_id: int | None = None,
        candidate_id: int | None = None,
        data: dict | None = None,
    ) -> None:
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
