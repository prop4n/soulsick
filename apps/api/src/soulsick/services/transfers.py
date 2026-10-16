"""Suivi des transferts (téléchargements et uploads) : base + temps réel + journal."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..models import Transfer, TransferState, iso_utc
from ..naming import safe_component
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
            t.remotely_queued = u.remotely_queued
            t.error = u.error if u.state in (TransferState.FAILED, TransferState.ABORTED) else None
            if u.state == TransferState.TRANSFERRING and t.started_at is None:
                t.started_at = datetime.now(UTC)
            if u.state in TERMINAL:
                t.completed_at = datetime.now(UTC)
            else:
                t.completed_at = None
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

    async def requeue(self, tid: int, reset_attempts: bool = False) -> Transfer | None:
        """Relance un téléchargement sur SA ligne (même id, même lien candidat/album)."""
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

    def register(self, direction: str, username: str, remote_path: str, tid: int) -> None:
        """Associe un transfert aioslsk à la ligne créée en base par Soulsick."""
        self._ids[(direction, username, remote_path)] = tid

    def live(self, tid: int) -> dict | None:
        return self._live.get(tid)

    async def download_manual(self, username: str, files: list[str]) -> list[int]:
        """Téléchargement manuel (recherche ou parcours) vers downloads/manual/<pair>/<dossier>."""
        ids = []
        root = os.path.join(str(self.core.env.downloads_dir), "manual")
        for path in files:
            parts = path.replace("\\", "/").split("/")
            folder = safe_component(parts[-2]) if len(parts) >= 2 else "_"
            # Pseudo et dossier viennent du réseau : on les neutralise avant d'en faire un chemin
            dest = os.path.join(root, safe_component(username), folder)
            if not os.path.realpath(dest).startswith(os.path.realpath(root) + os.sep):
                raise ValueError(f"Chemin de destination refusé : {dest}")
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
            f"Téléchargement manuel de {len(files)} fichier(s) depuis {username} vers "
            f"{os.path.join(root, safe_component(username))}",
            data={"username": username, "folders": folders, "files": files},
        )
        return ids


def _snapshot(t: Transfer) -> dict:
    return transfer_to_dict(t)

