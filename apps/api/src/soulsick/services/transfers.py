"""Suivi des transferts (téléchargements et uploads) : base + temps réel + journal."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..messages import M, UserError
from ..models import Transfer, TransferState, iso_utc
from ..naming import safe_component
from ..slsk.engine import TransferUpdate

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..core import Core

TERMINAL = {TransferState.COMPLETE, TransferState.FAILED, TransferState.ABORTED}


def transfer_to_dict(t: Transfer) -> dict:
    return {
        "id": t.id,
        "direction": t.direction,
        "username": t.username,
        "remote_path": t.remote_path,
        "local_path": t.local_path,
        "size": t.size,
        "bytes_transferred": t.bytes_transferred,
        "speed": t.speed,
        "state": t.state,
        "place_in_queue": t.place_in_queue,
        "remotely_queued": t.remotely_queued,
        "error": t.error,
        "attempts": t.attempts,
        "candidate_id": t.candidate_id,
        "release_group_id": t.release_group_id,
        "created_at": iso_utc(t.created_at),
        "started_at": iso_utc(t.started_at),
        "completed_at": iso_utc(t.completed_at),
    }


class TransferService:
    def __init__(self, core: Core) -> None:
        self.core = core
        # Progression en mémoire (la base n'est écrite qu'aux changements d'état)
        self._live: dict[int, dict] = {}
        self._ids: dict[tuple[str, str, str], int] = {}
        # Downloads you cancelled, and downloads already received: final. The engine may still
        # report on them (a late peer, an aioslsk re-queue); they stay as they are until you
        # retry or resume them explicitly
        self._cancelled: set[int] = set()
        self._done: set[int] = set()
        self._lock = asyncio.Lock()

    async def _find_id(self, u: TransferUpdate) -> int | None:
        key = (u.direction, u.username, u.remote_path)
        if key in self._ids:
            return self._ids[key]
        async with self.core.db.session() as s:
            row = (
                await s.execute(
                    select(Transfer.id)
                    .where(
                        Transfer.direction == u.direction,
                        Transfer.username == u.username,
                        Transfer.remote_path == u.remote_path,
                    )
                    .order_by(Transfer.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if row is not None:
            self._ids[key] = row
        return row

    async def on_update(self, u: TransferUpdate) -> None:
        async with self._lock:
            tid = await self._find_id(u)
            created = False
            new_upload = (
                tid is not None
                and u.direction == "upload"
                and u.state_changed
                and u.state not in TERMINAL
                and await self._is_terminal(tid)
            )
            if tid is None or new_upload:
                # Inconnu en base : upload demandé par un pair (ou nouvelle demande du même fichier).
                # Un téléchargement relancé, lui, réutilise TOUJOURS sa ligne : elle porte le lien
                # vers le candidat et l'album, et c'est elle que tu vois dans l'interface.
                async with self.core.db.session() as s:
                    t = Transfer(
                        direction=u.direction,
                        username=u.username,
                        remote_path=u.remote_path,
                        local_path=u.local_path,
                        size=u.size,
                        state=u.state,
                    )
                    s.add(t)
                    await s.commit()
                    tid = t.id
                self._ids[(u.direction, u.username, u.remote_path)] = tid
                created = True

            if u.direction == "download" and (
                (tid in self._cancelled and u.state not in TERMINAL) or tid in self._done
            ):
                # A late update for a file you cancelled or already received: ignore it, and make
                # sure the engine doesn't download it again
                if u.state not in TERMINAL:
                    asyncio.create_task(self.stop_on_engine(u.username, u.remote_path))
                return

            prev = self._live.get(tid, {})
            live = {
                "id": tid,
                "bytes_transferred": u.bytes_transferred,
                "speed": u.speed,
                "state": u.state,
                "size": u.size,
                "place_in_queue": u.place_in_queue,
                "remotely_queued": u.remotely_queued,
            }
            self._live[tid] = live
            queue_changed = (
                prev.get("place_in_queue") != u.place_in_queue or prev.get("remotely_queued") != u.remotely_queued
            )

            if u.state_changed or created or queue_changed:
                await self._persist(tid, u)
            if created and u.direction == "upload":
                name = u.remote_path.replace("\\", "/").rsplit("/", 1)[-1]
                await self.core.journal.emit(
                    "upload.requested", M("upload.requested", peer=u.username, name=name),
                    transfer_id=tid, data={"remote_path": u.remote_path, "local_path": u.local_path},
                )
            self.core.hub.publish("transfer", live)

    async def _is_terminal(self, tid: int) -> bool:
        async with self.core.db.session() as s:
            t = await s.get(Transfer, tid)
            return bool(t and t.state in TERMINAL)

    async def _persist(self, tid: int, u: TransferUpdate) -> None:
        async with self.core.db.session() as s:
            t = await s.get(Transfer, tid)
            if not t:
                return
            prev = t.state
            t.state = u.state
            t.bytes_transferred = u.bytes_transferred
            t.speed = u.speed
            t.size = u.size or t.size
            t.local_path = u.local_path or t.local_path
            t.place_in_queue = u.place_in_queue
            t.remotely_queued = u.remotely_queued
            t.error = u.error if u.state in (TransferState.FAILED, TransferState.ABORTED) else None
            if u.state == TransferState.TRANSFERRING and t.started_at is None:
                t.started_at = datetime.now(UTC)
            if u.state in TERMINAL:
                t.completed_at = datetime.now(UTC)
            if u.state == TransferState.COMPLETE and t.direction == "download":
                self._done.add(tid)
            else:
                t.completed_at = None
            await s.commit()
            data = _snapshot(t)
        self.core.hub.publish("transfer", data)
        if prev == u.state:
            return
        await self._journal(data, prev)
        if u.state in TERMINAL and data["candidate_id"]:
            # Outside the lock: what follows (import, fallback) starts transfers again
            asyncio.create_task(self.core.hunter.on_transfer_terminal(data["candidate_id"]))

    async def _journal(self, t: dict, prev: str) -> None:
        name = t["remote_path"].replace("\\", "/").rsplit("/", 1)[-1]
        rg = t["release_group_id"]
        if t["direction"] == "upload":
            if t["state"] == TransferState.TRANSFERRING:
                await self.core.journal.emit(
                    "upload.started", M("upload.started", name=name, peer=t["username"]),
                    transfer_id=t["id"], data={"path": t["local_path"] or t["remote_path"]},
                )
            elif t["state"] == TransferState.COMPLETE:
                await self.core.journal.emit(
                    "upload.complete", M("upload.complete", name=name, peer=t["username"]), transfer_id=t["id"],
                )
            elif t["state"] in (TransferState.FAILED, TransferState.ABORTED):
                await self.core.journal.emit(
                    "upload.failed", M("upload.failed", name=name, peer=t["username"], error=t["error"] or t["state"]),
                    level="warning", transfer_id=t["id"],
                )
            return
        if t["state"] == TransferState.COMPLETE:
            await self.core.journal.emit(
                "download.file_complete", M("download.file_complete", name=name, peer=t["username"], path=t["local_path"]),
                transfer_id=t["id"], release_group_id=rg, candidate_id=t["candidate_id"],
            )
        elif t["state"] == TransferState.FAILED:
            await self.core.journal.emit(
                "download.file_failed",
                M("download.file_failed", name=name, peer=t["username"], error=t["error"] or M("word.unknown_reason")),
                level="warning", transfer_id=t["id"], release_group_id=rg, candidate_id=t["candidate_id"],
            )

    async def requeue(self, tid: int, reset_attempts: bool = False) -> Transfer | None:
        """Restarts a download on ITS row (same id, same candidate/album link)."""
        self._cancelled.discard(tid)
        self._done.discard(tid)
        async with self.core.db.session() as s:
            t = await s.get(Transfer, tid)
            if not t or t.direction != "download":
                return None
            t.attempts = 1 if reset_attempts else (t.attempts or 1) + 1
            t.state = TransferState.QUEUED
            t.remotely_queued = False
            t.place_in_queue = None
            t.error = None
            t.completed_at = None
            await s.commit()
            data = transfer_to_dict(t)
        self.register("download", t.username, t.remote_path, t.id)
        self._live.pop(tid, None)
        self.core.hub.publish("transfer", data)
        dest = os.path.dirname(t.local_path) if t.local_path else os.path.join(str(self.core.env.downloads_dir), "manual")
        await self.core.engine.download(t.username, t.remote_path, dest)
        return t

    async def pause(self, tid: int) -> bool:
        """Met un téléchargement en pause (il garde sa place dans l'album ; rien n'est abandonné)."""
        async with self.core.db.session() as s:
            t = await s.get(Transfer, tid)
            if not t or t.direction != "download" or t.state in TERMINAL or t.state == TransferState.PAUSED:
                return False
            username, path = t.username, t.remote_path
        await self.core.engine.pause(username, path, "download")
        async with self.core.db.session() as s:
            t = await s.get(Transfer, tid)
            assert t
            t.state = TransferState.PAUSED
            t.speed = 0
            await s.commit()
            data = transfer_to_dict(t)
        self._live[tid] = {**self._live.get(tid, {}), "state": TransferState.PAUSED, "speed": 0}
        self.core.hub.publish("transfer", data)
        return True

    async def resume(self, tid: int) -> bool:
        """Resumes a paused download where it stopped (the peer restarts at the right byte)."""
        self._cancelled.discard(tid)
        self._done.discard(tid)
        async with self.core.db.session() as s:
            t = await s.get(Transfer, tid)
            if not t or t.state != TransferState.PAUSED:
                return False
            t.state = TransferState.QUEUED
            await s.commit()
            data = transfer_to_dict(t)
            username, path, local = t.username, t.remote_path, t.local_path
        self.register("download", username, path, tid)
        self.core.hub.publish("transfer", data)
        dest = os.path.dirname(local) if local else os.path.join(str(self.core.env.downloads_dir), "manual")
        await self.core.engine.download(username, path, dest)
        return True

    async def load_cancelled(self) -> None:
        """At start-up: downloads cancelled or received before stay so, whatever the engine reports."""
        async with self.core.db.session() as s:
            rows = (await s.execute(select(Transfer.id, Transfer.state).where(
                Transfer.direction == "download",
                Transfer.state.in_([TransferState.ABORTED, TransferState.COMPLETE]),
            ))).all()
        self._cancelled |= {i for i, st in rows if st == TransferState.ABORTED}
        self._done |= {i for i, st in rows if st == TransferState.COMPLETE}

    async def cancel(self, tid: int) -> bool:
        """Cancels a transfer for good, even paused or never accepted by the peer
        (the engine may not track it any more: the row is closed here)."""
        async with self.core.db.session() as s:
            t = await s.get(Transfer, tid)
            if not t or t.state in TERMINAL:
                return False
            username, path, direction = t.username, t.remote_path, t.direction
        if direction == "download":
            self._cancelled.add(tid)
        await self.stop_on_engine(username, path, direction)
        async with self.core.db.session() as s:
            t = await s.get(Transfer, tid)
            assert t
            if t.state not in TERMINAL:
                t.state = TransferState.ABORTED
                t.error = M("reason.cancelled_by_you", n=1).text
                t.speed = 0
                t.completed_at = datetime.now(UTC)
                await s.commit()
            data = transfer_to_dict(t)
        self._live.pop(tid, None)
        self.core.hub.publish("transfer", data)
        if data["candidate_id"]:
            asyncio.create_task(self.core.hunter.on_transfer_terminal(data["candidate_id"]))
        return True

    def register(self, direction: str, username: str, remote_path: str, tid: int) -> None:
        """Associe un transfert aioslsk à la ligne créée en base par Soulsick."""
        self._ids[(direction, username, remote_path)] = tid

    def live(self, tid: int) -> dict | None:
        return self._live.get(tid)

    def forget(self, tid: int) -> None:
        """A download cancelled outside this service (an album source dropped): it stays cancelled."""
        self._live.pop(tid, None)
        self._cancelled.add(tid)

    async def stop_on_engine(self, username: str, path: str, direction: str = "download") -> None:
        """Aborts on the engine side and drops it from the engine's list (it won't come back)."""
        for step in (self.core.engine.abort, self.core.engine.remove):
            try:
                await step(username, path, direction)
            except Exception as e:  # offline, or unknown to the engine
                log.info("%s %s: %s", step.__name__, path, e)

    async def download_manual(self, username: str, files: list[str]) -> list[int]:
        """Manual download (search or browse) to downloads/manual/<peer>/<folder>."""
        ids = []
        root = os.path.join(str(self.core.env.downloads_dir), "manual")
        for path in files:
            parts = path.replace("\\", "/").split("/")
            folder = safe_component(parts[-2]) if len(parts) >= 2 else "_"
            # Username and folder come from the network: neutralise them before building a path
            dest = os.path.join(root, safe_component(username), folder)
            if not os.path.realpath(dest).startswith(os.path.realpath(root) + os.sep):
                raise UserError("error.destination_refused", path=dest)
            async with self.core.db.session() as s:
                t = Transfer(
                    direction="download", username=username, remote_path=path,
                    local_path=os.path.join(dest, safe_component(parts[-1])), state=TransferState.QUEUED,
                )
                s.add(t)
                await s.commit()
                ids.append(t.id)
                self.register("download", username, path, t.id)
            await self.core.engine.download(username, path, dest)
        folders = sorted({p.replace("\\", "/").rsplit("/", 1)[0] for p in files})
        await self.core.journal.emit(
            "download.manual",
            M("download.manual", n=len(files), peer=username, dest=os.path.join(root, safe_component(username))),
            data={"username": username, "folders": folders, "files": files},
        )
        return ids


def _snapshot(t: Transfer) -> dict:
    return transfer_to_dict(t)

