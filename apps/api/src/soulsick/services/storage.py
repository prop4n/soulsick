"""Disk space: for each folder Soulsick uses, which disk it is on, what is left, what Soulsick takes."""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from ..models import LibraryFile, Share

if TYPE_CHECKING:
    from ..core import Core

# Below this, the disk is "low" (warning); below CRITICAL, downloads may fail
LOW_RATIO, LOW_BYTES = 0.05, 5 * 1024**3
CRITICAL_BYTES = 1024**3
CACHE_S = 60


def _tree_size(path: str) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def _mount_point(path: str) -> str:
    p = os.path.realpath(path)
    while not os.path.ismount(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def level(total: int, free: int) -> str:
    if free < CRITICAL_BYTES:
        return "critical"
    if free < LOW_BYTES or (total and free / total < LOW_RATIO):
        return "low"
    return "ok"


class StorageService:
    def __init__(self, core: Core) -> None:
        self.core = core
        self._cache: tuple[float, dict] | None = None
        self._lock = asyncio.Lock()

    def _folders(self) -> list[tuple[str, str]]:
        env = self.core.env
        return [("music", str(env.music_dir)), ("downloads", str(env.downloads_dir)), ("config", str(env.config_dir))]

    def quick_level(self) -> str:
        """Worst level of the library and download disks (statvfs only: cheap, for /status)."""
        worst = "ok"
        for _key, path in self._folders()[:2]:
            try:
                u = shutil.disk_usage(path)
            except OSError:
                continue
            lv = level(u.total, u.free)
            if lv == "critical" or (lv == "low" and worst == "ok"):
                worst = lv
        return worst

    async def snapshot(self, force: bool = False) -> dict:
        async with self._lock:
            if self._cache and not force and time.monotonic() - self._cache[0] < CACHE_S:
                return self._cache[1]
            data = await self._compute()
            self._cache = (time.monotonic(), data)
            return data

    async def _compute(self) -> dict:
        async with self.core.db.session() as s:
            library_size = (await s.execute(select(func.coalesce(func.sum(LibraryFile.size), 0)))).scalar_one()
            shares = list((await s.execute(select(Share).where(Share.enabled.is_(True)))).scalars())

        folders: list[dict] = []
        for key, path in self._folders():
            if key == "music":
                size = int(library_size)
            else:
                size = await asyncio.to_thread(_tree_size, path) if os.path.isdir(path) else 0
            folders.append({"key": key, "path": os.path.realpath(path), "size": size})
        for sh in shares:
            folders.append({"key": "share", "path": sh.path, "size": sh.total_size or 0})

        disks: dict[int, dict] = {}
        for f in folders:
            try:
                dev = os.stat(f["path"]).st_dev
                u = shutil.disk_usage(f["path"])
            except OSError:
                f["missing"] = True
                disks.setdefault(-1, {"id": -1, "mount": None, "total": 0, "used": 0, "free": 0, "level": "ok", "folders": []})["folders"].append(f)
                continue
            d = disks.setdefault(dev, {
                "id": dev, "mount": _mount_point(f["path"]), "total": u.total, "used": u.used, "free": u.free,
                "level": level(u.total, u.free), "folders": [],
            })
            d["folders"].append(f)
        for d in disks.values():
            d["soulsick"] = sum(f["size"] for f in d["folders"] if f["key"] != "share")
        return {"disks": sorted(disks.values(), key=lambda d: d["free"]), "checked_at": time.time()}
