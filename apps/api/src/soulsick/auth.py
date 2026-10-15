"""Compte administrateur unique, session par cookie signé."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING

from itsdangerous import BadSignature, URLSafeTimedSerializer

if TYPE_CHECKING:
    from .settings_store import SettingsStore

COOKIE = "soulsick_session"
MAX_AGE = 60 * 60 * 24 * 30


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    return digest, salt


class Auth:
    def __init__(self, store: SettingsStore) -> None:
        self.store = store
        self._serializer: URLSafeTimedSerializer | None = None

    async def serializer(self) -> URLSafeTimedSerializer:
        if self._serializer is None:
            raw = await self.store.get_raw("secret")
            if not raw:
                raw = {"key": secrets.token_hex(32)}
                await self.store.set_raw("secret", raw)
            self._serializer = URLSafeTimedSerializer(raw["key"], salt="soulsick-session")
        return self._serializer

    async def admin(self) -> dict | None:
        return await self.store.get_raw("admin")

    async def setup(self, username: str, password: str) -> None:
        digest, salt = hash_password(password)
        await self.store.set_raw("admin", {"username": username, "hash": digest, "salt": salt})

    async def verify(self, username: str, password: str) -> bool:
        admin = await self.admin()
        if not admin or not hmac.compare_digest(admin["username"], username):
            return False
        digest, _ = hash_password(password, admin["salt"])
        return hmac.compare_digest(digest, admin["hash"])

    async def issue(self, username: str) -> str:
        return (await self.serializer()).dumps({"u": username})

    async def check(self, token: str | None) -> str | None:
        if not token:
            return None
        try:
            data = (await self.serializer()).loads(token, max_age=MAX_AGE)
        except BadSignature:
            return None
        admin = await self.admin()
        if not admin or admin["username"] != data.get("u"):
            return None
        return data["u"]
