"""Déclenchement optionnel d'un scan Navidrome (API Subsonic) après un import."""

from __future__ import annotations

import hashlib
import secrets
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from ..core import Core


class NavidromeService:
    def __init__(self, core: Core) -> None:
        self.core = core

    async def trigger_scan(self, force: bool = False) -> dict:
        cfg = (await self.core.settings.get()).navidrome
        if not cfg.enabled and not force:
            return {"skipped": True}
        if not cfg.url:
            return {"ok": False, "error": "URL Navidrome non configurée"}
        salt = secrets.token_hex(6)
        token = hashlib.md5((cfg.password + salt).encode()).hexdigest()
        params = {"u": cfg.username, "t": token, "s": salt, "v": "1.16.1", "c": "soulsick", "f": "json"}
        url = cfg.url.rstrip("/") + "/rest/startScan"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(url, params=params)
            body = r.json().get("subsonic-response", {})
            ok = body.get("status") == "ok"
            err = (body.get("error") or {}).get("message")
        except Exception as e:
            ok, err = False, str(e)
        await self.core.journal.emit(
            "navidrome.scan",
            "Scan Navidrome déclenché" if ok else f"Scan Navidrome impossible : {err}",
            level="info" if ok else "warning",
            data={"url": cfg.url},
        )
        return {"ok": ok, "error": err}
