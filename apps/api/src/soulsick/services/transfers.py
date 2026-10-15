"""Suivi des transferts (téléchargements et uploads) : base + temps réel + journal."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..models import Transfer, TransferState
from ..slsk.engine import TransferUpdate

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
        "error": t.error,
        "candidate_id": t.candidate_id,
        "release_group_id": t.release_group_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }


class TransferService:
    def __init__(self, core: Core) -> None:
        self.core = core
        # Progression en mémoire (la base n'est écrite qu'aux changements d'état)
        self._live: dict[int, dict] = {}
        self._ids: dict[tuple[str, str, str], int] = {}
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
            if tid is None or (u.state_changed and await self._is_terminal(tid) and u.state not in TERMINAL):
                # Nouveau transfert (upload demandé par un pair, ou téléchargement manuel relancé)
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

            live = {
                "id": tid,
                "bytes_transferred": u.bytes_transferred,
                "speed": u.speed,
                "state": u.state,
                "size": u.size,
                "place_in_queue": u.place_in_queue,
            }
            self._live[tid] = live

            if u.state_changed or created:
                await self._persist(tid, u)
            if created and u.direction == "upload":
                name = u.remote_path.replace("\\", "/").rsplit("/", 1)[-1]
                await self.core.journal.emit(
                    "upload.requested", f"{u.username} demande « {name} »",
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
            t.error = u.error if u.state in (TransferState.FAILED, TransferState.ABORTED) else None
            if u.state == TransferState.TRANSFERRING and t.started_at is None:
                t.started_at = datetime.now(UTC)
            if u.state in TERMINAL:
                t.completed_at = datetime.now(UTC)
            await s.commit()
            data = _snapshot(t)
        self.core.hub.publish("transfer", data)
        if prev == u.state:
            return
        await self._journal(data, prev)
        if u.state in TERMINAL and data["candidate_id"]:
            # Hors du verrou : la suite (import, bascule de candidat) relance des transferts
            asyncio.create_task(self.core.hunter.on_transfer_terminal(data["candidate_id"]))

    async def _journal(self, t: dict, prev: str) -> None:
        name = t["remote_path"].replace("\\", "/").rsplit("/", 1)[-1]
        rg = t["release_group_id"]
        if t["direction"] == "upload":
            if t["state"] == TransferState.TRANSFERRING:
                await self.core.journal.emit(
                    "upload.started", f"Envoi de « {name} » à {t['username']}",
                    transfer_id=t["id"], data={"path": t["local_path"] or t["remote_path"]},
                )
            elif t["state"] == TransferState.COMPLETE:
                await self.core.journal.emit(
                    "upload.complete", f"« {name} » envoyé à {t['username']}", transfer_id=t["id"],
                )
            elif t["state"] in (TransferState.FAILED, TransferState.ABORTED):
                await self.core.journal.emit(
                    "upload.failed", f"Envoi de « {name} » à {t['username']} interrompu ({t['error'] or t['state']})",
                    level="warning", transfer_id=t["id"],
                )
            return
        if t["state"] == TransferState.COMPLETE:
            await self.core.journal.emit(
                "download.file_complete", f"Reçu « {name} » de {t['username']} → {t['local_path']}",
                transfer_id=t["id"], release_group_id=rg, candidate_id=t["candidate_id"],
            )
        elif t["state"] == TransferState.FAILED:
            await self.core.journal.emit(
                "download.file_failed", f"Échec de « {name} » chez {t['username']} : {t['error'] or 'raison inconnue'}",
                level="warning", transfer_id=t["id"], release_group_id=rg, candidate_id=t["candidate_id"],
            )

    def register(self, direction: str, username: str, remote_path: str, tid: int) -> None:
        """Associe un transfert aioslsk à la ligne créée en base par Soulsick."""
        self._ids[(direction, username, remote_path)] = tid

    def live(self, tid: int) -> dict | None:
        return self._live.get(tid)

    async def download_manual(self, username: str, files: list[str]) -> list[int]:
        """Téléchargement manuel (recherche ou parcours) vers downloads/manual/<pair>/<dossier>."""
        ids = []
        for path in files:
            parts = path.replace("\\", "/").split("/")
            folder = parts[-2] if len(parts) >= 2 else ""
            dest = os.path.join(str(self.core.env.downloads_dir), "manual", username, folder)
            async with self.core.db.session() as s:
                t = Transfer(
                    direction="download", username=username, remote_path=path,
                    local_path=os.path.join(dest, parts[-1]), state=TransferState.QUEUED,
                )
                s.add(t)
                await s.commit()
                ids.append(t.id)
                self.register("download", username, path, t.id)
            await self.core.engine.download(username, path, dest)
        folders = sorted({p.replace("\\", "/").rsplit("/", 1)[0] for p in files})
        await self.core.journal.emit(
            "download.manual",
            f"Téléchargement manuel de {len(files)} fichier(s) depuis {username} vers "
            f"{os.path.join(str(self.core.env.downloads_dir), 'manual', username)}",
            data={"username": username, "folders": folders, "files": files},
        )
        return ids


def _snapshot(t: Transfer) -> dict:
    return transfer_to_dict(t)

