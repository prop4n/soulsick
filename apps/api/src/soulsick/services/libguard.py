"""Library guard: never shelve music into a folder that isn't the real library.

In Docker, a forgotten or broken volume line leaves /music inside the container (or in an
anonymous volume): imports would land there and vanish with the container, and a scan would
see an empty library and forget every album. While the library folder looks wrong, imports
wait and scans are skipped; everything resumes on its own once it is back.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from ..messages import M, Msg, UserError
from ..models import AlbumStatus, LibraryFile, ReleaseGroup, Transfer
from ..quality import is_audio

if TYPE_CHECKING:
    from ..core import Core

log = logging.getLogger(__name__)

HELD = "reason.library_unavailable"
# Docker anonymous volume: /var/lib/docker/volumes/<64 hex>/_data
_ANONYMOUS = re.compile(r"/volumes/[0-9a-f]{64}/_data$")


def in_container() -> bool:
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def _unescape(s: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def mount_kind(path: str, mountinfo: str | None) -> str | None:
    """How `path` reaches the host: "host" (bind mount or named volume), "anonymous" (Docker
    anonymous volume), "none" (only the container's own filesystem) or None (unknown)."""
    if mountinfo is None:
        return None
    real = os.path.realpath(path)
    best: tuple[str, str] | None = None  # (mount point, root inside its filesystem)
    for line in mountinfo.splitlines():
        parts = line.split(" ")
        if len(parts) < 5:
            continue
        root, point = _unescape(parts[3]), _unescape(parts[4])
        if point == "/" or not (real == point or real.startswith(point.rstrip("/") + "/")):
            continue
        if best is None or len(point) >= len(best[0]):
            best = (point, root)
    if best is None:
        return "none"
    return "anonymous" if _ANONYMOUS.search(best[1]) else "host"


def _read_mountinfo() -> str | None:
    try:
        return Path("/proc/self/mountinfo").read_text()
    except OSError:
        return None


def _has_audio(root: str) -> bool:
    for _, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if any(is_audio(f) for f in filenames):
            return True
    return False


class LibraryGuard:
    def __init__(self, core: Core) -> None:
        self.core = core
        env = core.env
        self.require_mount = in_container() if env.require_library_mount is None else env.require_library_mount
        self.problem: Msg | None = None
        self.warnings: list[Msg] = []
        self._checked = False

    @property
    def ok(self) -> bool:
        return self.problem is None

    def state(self) -> dict:
        return {
            "ok": self.ok,
            "path": str(self.core.env.music_dir),
            "problem": self.problem.text if self.problem else None,
            "problem_t": self.problem.to_json() if self.problem else None,
            "warnings": [w.text for w in self.warnings],
            "warnings_t": [w.to_json() for w in self.warnings],
        }

    async def _diagnose(self) -> tuple[Msg | None, list[Msg]]:
        env = self.core.env
        music = str(env.music_dir)
        mountinfo = await asyncio.to_thread(_read_mountinfo) if self.require_mount else None
        warnings = []
        if self.require_mount:
            # Not blocking, but worth knowing: these are lost when the container is recreated
            for name, p in (("downloads", env.downloads_dir), ("config", env.config_dir)):
                kind = mount_kind(str(p), mountinfo)
                if kind in ("none", "anonymous"):
                    warnings.append(M("library.guard.folder_not_mounted", name=name, path=str(p)))
        if not os.path.isdir(music):
            return M("library.guard.missing", path=music), warnings
        if self.require_mount:
            kind = mount_kind(music, mountinfo)
            if kind == "none":
                return M("library.guard.not_mounted", path=music), warnings
            if kind == "anonymous":
                return M("library.guard.anonymous", path=music), warnings
        if not os.access(music, os.W_OK | os.X_OK):
            return M("library.guard.readonly", path=music), warnings
        async with self.core.db.session() as s:
            known = (await s.execute(select(func.count()).select_from(LibraryFile))).scalar_one()
        if known and not await asyncio.to_thread(_has_audio, music):
            return M("library.guard.emptied", path=music, n=known), warnings
        return None, warnings

    async def check(self) -> bool:
        """Re-examines the library folder; reports changes. True when it can be used."""
        problem, self.warnings = await self._diagnose()
        was, first = self.problem, not self._checked
        self.problem, self._checked = problem, True
        if problem and (first or was is None or was.key != problem.key):
            log.warning("library guard: %s", problem.text)
            await self.core.journal.emit("library.guard.blocked", M("library.guard.blocked", problem=problem), level="error")
        elif not problem and was is not None:
            await self.core.journal.emit("library.guard.back", M("library.guard.back", path=str(self.core.env.music_dir)))
            asyncio.create_task(self._resume())
        if first:
            for w in self.warnings:
                await self.core.journal.emit("library.guard.warning", w, level="warning")
        if first or (was is None) != (problem is None) or (was and problem and was.key != problem.key):
            self.core.hub.publish("library_guard", self.state())
        return problem is None

    def require(self) -> None:
        """Raises a translatable error if the library folder can't be used right now."""
        if self.problem:
            raise UserError("error.library_unavailable", problem=self.problem)

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("library guard")

    async def held_albums(self) -> list[int]:
        async with self.core.db.session() as s:
            rows = (await s.execute(
                select(ReleaseGroup.id, ReleaseGroup.status_reason_t).where(ReleaseGroup.status == AlbumStatus.NEEDS_REVIEW)
            )).all()
        return [rid for rid, t in rows if isinstance(t, dict) and t.get("key") == HELD]

    async def _resume(self) -> None:
        """The library is back: scan it and import what was waiting."""
        await self.core.library.scan()
        for rid in await self.held_albums():
            async with self.core.db.session() as s:
                cid = (await s.execute(
                    select(Transfer.candidate_id)
                    .where(Transfer.release_group_id == rid, Transfer.candidate_id.is_not(None), Transfer.state == "complete")
                    .group_by(Transfer.candidate_id)
                    .order_by(func.count().desc())
                )).scalars().first()
            if cid:
                await self.core.importer.import_candidate(cid)
