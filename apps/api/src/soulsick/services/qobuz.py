"""Qobuz as a download source, next to Soulseek.

Qobuz retired email/password sign-in for third-party apps (around April 2026): the account is
reached with the `user_auth_token` of the web player, copied once from play.qobuz.com. The app id
and the secret that signs file requests are read from the web player's bundle (or forced in the
settings when Qobuz changes it).

An album found on Qobuz becomes a candidate like a Soulseek folder: its files are named
`qobuz:album-<id>\\<NN> - <title>.<ext>`, a path no Soulseek peer can have. Downloads go through the
same transfer rows (progress, pause, retry, cancel) and the same import.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
import time
from collections import OrderedDict
from typing import TYPE_CHECKING

import httpx

from ..messages import M, Msg
from ..models import TransferState
from ..naming import safe_component
from ..scoring import PeerResult, RemoteFile
from ..slsk.engine import TransferUpdate

if TYPE_CHECKING:
    from ..core import Core

log = logging.getLogger(__name__)

API = "https://www.qobuz.com/api.json/0.2/"
PLAYER = "https://play.qobuz.com"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
# Shown as the "peer" of Qobuz candidates and transfers
QOBUZ_USER = "Qobuz"
PREFIX = "qobuz:album-"
# A track every account can stream: used to find the secret that signs file requests
_PROBE_TRACK = 5966783

# Qobuz format ids, best first
QUALITIES: dict[int, str] = {27: "FLAC 24-bit ≤ 192 kHz", 7: "FLAC 24-bit ≤ 96 kHz", 6: "FLAC 16-bit (CD)", 5: "MP3 320"}

_BUNDLE_URL = re.compile(r'<script src="(/resources/\d+\.\d+\.\d+-[a-z]\d{3}/bundle\.js)"></script>')
_APP_ID = re.compile(r'production:\{api:\{appId:"(?P<app_id>\d{9})",appSecret:"\w{32}"')
_SEED = re.compile(r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)')
_INFO_EXTRAS = r'name:"\w+/(?P<timezone>{timezones})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'


class QobuzError(Exception):
    def __init__(self, msg: Msg) -> None:
        super().__init__(msg.text)
        self.msg = msg


def is_qobuz(remote_path: str | None) -> bool:
    return bool(remote_path) and remote_path.startswith(PREFIX)


def album_id_of(remote_path: str) -> str:
    return remote_path[len(PREFIX):].split("\\", 1)[0]


def parse_bundle(bundle: str) -> tuple[str, list[str]]:
    """(app id, candidate secrets) from the web player's bundle.js."""
    m = _APP_ID.search(bundle)
    if not m:
        raise QobuzError(M("qobuz.error.bundle"))
    seeds: OrderedDict[str, str] = OrderedDict()
    for s in _SEED.finditer(bundle):
        seeds[s.group("timezone")] = s.group("seed")
    if not seeds:
        raise QobuzError(M("qobuz.error.bundle"))
    # Like the web player: the second timezone is tried first
    keys = list(seeds)
    if len(keys) > 1:
        keys[0], keys[1] = keys[1], keys[0]
    rx = re.compile(_INFO_EXTRAS.format(timezones="|".join(k.capitalize() for k in keys)))
    parts = {x.group("timezone").lower(): (x.group("info"), x.group("extras")) for x in rx.finditer(bundle)}
    secrets = []
    for tz in keys:
        if tz not in parts:
            continue
        info, extras = parts[tz]
        try:
            secrets.append(base64.standard_b64decode((seeds[tz] + info + extras)[:-44]).decode())
        except (ValueError, UnicodeDecodeError):
            continue
    return m.group("app_id"), secrets


def file_sig(track_id: int | str, format_id: int, ts: str, secret: str) -> str:
    raw = f"trackgetFileUrlformat_id{format_id}intentstreamtrack_id{track_id}{ts}{secret}"
    return hashlib.md5(raw.encode()).hexdigest()


def _track_title(t: dict) -> str:
    title = (t.get("title") or "").strip()
    version = (t.get("version") or "").strip()
    return f"{title} ({version})" if version and version.lower() not in title.lower() else title


def _quality(album: dict, wanted: int) -> tuple[str, int | None, int | None, int | None]:
    """(extension, bit depth, sample rate, bitrate) of what Qobuz will deliver for this album."""
    if wanted == 5:
        return "mp3", None, None, 320
    depth = int(album.get("maximum_bit_depth") or 16)
    rate_khz = float(album.get("maximum_sampling_rate") or 44.1)
    if wanted == 6 or depth < 24:
        return "flac", 16, 44100, None
    if wanted == 7:
        rate_khz = min(rate_khz, 96)
    return "flac", 24, int(rate_khz * 1000), None


def track_path(album_id: str, t: dict, multi_disc: bool, ext: str) -> str:
    disc = f"{t.get('media_number') or 1}-" if multi_disc else ""
    name = safe_component(f"{disc}{int(t.get('track_number') or 0):02d} - {_track_title(t)}.{ext}")
    return f"{PREFIX}{album_id}\\{name}"


class QobuzService:
    def __init__(self, core: Core, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.core = core
        self.transport = transport
        self._app: tuple[str, str] | None = None  # (app id, working secret)
        self._tasks: dict[str, asyncio.Task] = {}
        self._albums: dict[str, dict] = {}
        self._slots = asyncio.Semaphore(2)

    # --- API ---------------------------------------------------------------------------

    def _client(self, **kw) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, timeout=30, headers={"User-Agent": UA}, **kw)

    async def _token(self) -> str:
        token = (await self.core.settings.get()).qobuz.token.strip()
        if not token:
            raise QobuzError(M("qobuz.error.no_token"))
        return token

    async def _bundle_app(self) -> tuple[str, list[str]]:
        try:
            async with self._client() as c:
                page = await c.get(f"{PLAYER}/login")
                m = _BUNDLE_URL.search(page.text)
                if not m:
                    raise QobuzError(M("qobuz.error.bundle"))
                bundle = await c.get(PLAYER + m.group(1))
        except httpx.HTTPError as e:
            raise QobuzError(M("qobuz.error.network", error=str(e) or type(e).__name__)) from e
        return parse_bundle(bundle.text)

    async def _api(self, endpoint: str, params: dict, app_id: str, token: str | None) -> dict:
        headers = {"X-App-Id": app_id}
        if token:
            headers["X-User-Auth-Token"] = token
        try:
            async with self._client() as c:
                r = await c.get(API + endpoint, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise QobuzError(M("qobuz.error.network", error=str(e) or type(e).__name__)) from e
        if r.status_code in (401, 403):
            raise QobuzError(M("qobuz.error.token", status=r.status_code))
        if r.status_code >= 400:
            raise QobuzError(M("qobuz.error.http", endpoint=endpoint, status=r.status_code))
        return r.json()

    async def _file_url(self, track_id: int | str, format_id: int, app_id: str, secret: str, token: str) -> dict:
        ts = str(time.time())
        params = {
            "request_ts": ts, "request_sig": file_sig(track_id, format_id, ts, secret),
            "track_id": track_id, "format_id": format_id, "intent": "stream",
        }
        return await self._api("track/getFileUrl", params, app_id, token)

    async def app(self) -> tuple[str, str]:
        """The app id and a secret Qobuz accepts (forced in the settings, or found in the web player)."""
        cfg = (await self.core.settings.get()).qobuz
        if cfg.app_id.strip() and cfg.app_secret.strip():
            return cfg.app_id.strip(), cfg.app_secret.strip()
        if self._app:
            return self._app
        token = await self._token()
        app_id, secrets = await self._bundle_app()
        for secret in secrets:
            try:
                await self._file_url(_PROBE_TRACK, 5, app_id, secret, token)
            except QobuzError as e:
                if e.msg.key == "qobuz.error.token":
                    raise
                continue
            self._app = (app_id, secret)
            return self._app
        raise QobuzError(M("qobuz.error.secret", n=len(secrets)))

    async def test(self) -> dict:
        """Checks each step and says which one fails: token, web player, signing secret."""
        self._app = None
        try:
            token = await self._token()
            app_id, secret = await self.app()
            user = await self._api("user/get", {}, app_id, token)
        except QobuzError as e:
            return {"ok": False, "error": e.msg.text, "error_t": e.msg.to_json()}
        except httpx.HTTPError as e:
            return {"ok": False, "error": str(e)}
        cred = (user.get("credential") or {}).get("parameters") or {}
        return {
            "ok": True,
            "user": user.get("display_name") or user.get("login") or user.get("email"),
            "subscription": cred.get("short_label") or (user.get("credential") or {}).get("label"),
            "hires": bool(cred.get("hires_streaming") or cred.get("hires_purchases_streaming")),
            "app_id": app_id,
        }

    async def album(self, album_id: str) -> dict:
        if album_id not in self._albums:
            app_id, _ = await self.app()
            self._albums[album_id] = await self._api("album/get", {"album_id": album_id}, app_id, await self._token())
        return self._albums[album_id]

    # --- Search -------------------------------------------------------------------------

    async def search(self, query: str, limit: int = 8) -> list[PeerResult]:
        """Albums matching the query, each as a folder of files ready to be scored."""
        cfg = (await self.core.settings.get()).qobuz
        app_id, _ = await self.app()
        token = await self._token()
        found = await self._api("album/search", {"query": query, "limit": limit}, app_id, token)
        out = []
        for item in (found.get("albums") or {}).get("items") or []:
            if item.get("streamable") is False:
                continue
            try:
                album = await self.album(str(item["id"]))
            except QobuzError as e:
                log.info("qobuz album %s: %s", item.get("id"), e)
                continue
            out.append(self.as_folder(album, cfg.quality))
        return [r for r in out if r.files]

    def as_folder(self, album: dict, quality: int) -> PeerResult:
        album_id = str(album["id"])
        tracks = [t for t in (album.get("tracks") or {}).get("items") or [] if t.get("streamable", True)]
        multi = len({t.get("media_number") or 1 for t in tracks}) > 1
        ext, depth, rate, bitrate = _quality(album, quality)
        files = []
        for t in tracks:
            duration = int(t.get("duration") or 0) or None
            bytes_per_s = (bitrate or 0) * 125 if bitrate else int((depth or 16) * (rate or 44100) * 2 / 8 * 0.6)
            files.append(RemoteFile(
                track_path(album_id, t, multi, ext), size=(duration or 0) * bytes_per_s,
                bitrate=bitrate, duration=duration, sample_rate=rate, bit_depth=depth,
            ))
        # Always a free slot and a fast source
        return PeerResult(QOBUZ_USER, True, 10_000_000, 0, files)

    # --- Downloads (same interface as the Soulseek engine) ---------------------------------

    async def download(self, username: str, remote_path: str, dest_dir: str) -> None:
        local = os.path.join(dest_dir, remote_path.rsplit("\\", 1)[-1])
        old = self._tasks.get(remote_path)
        if old and not old.done():
            return
        self._tasks[remote_path] = asyncio.create_task(self._fetch(remote_path, local))

    async def abort(self, username: str, remote_path: str, direction: str = "download") -> None:
        task = self._tasks.pop(remote_path, None)
        if task and not task.done():
            task.cancel()

    async def pause(self, username: str, remote_path: str, direction: str = "download") -> None:
        # The partial file stays: a resume continues from where it stopped
        await self.abort(username, remote_path, direction)

    async def remove(self, username: str, remote_path: str, direction: str = "download") -> None:
        self._tasks.pop(remote_path, None)

    async def _emit(self, path: str, local: str, state: str, done: int = 0, size: int | None = None,
                    speed: float = 0.0, error: str | None = None, changed: bool = True) -> None:
        await self.core.transfers.on_update(TransferUpdate(
            direction="download", username=QOBUZ_USER, remote_path=path, local_path=local, size=size,
            bytes_transferred=done, speed=speed, state=state, place_in_queue=None, error=error,
            state_changed=changed,
        ))

    async def _fetch(self, path: str, local: str) -> None:
        await self._emit(path, local, TransferState.QUEUED)
        async with self._slots:
            try:
                await self._emit(path, local, TransferState.INITIALIZING)
                url = await self._resolve(path)
                await self._stream(path, local, url)
            except asyncio.CancelledError:
                raise
            except QobuzError as e:
                await self._emit(path, local, TransferState.FAILED, error=e.msg.text)
            except (httpx.HTTPError, OSError) as e:
                await self._emit(path, local, TransferState.FAILED, error=f"Qobuz: {e}")
            finally:
                if self._tasks.get(path) is asyncio.current_task():
                    self._tasks.pop(path, None)

    async def _resolve(self, path: str) -> str:
        album_id = album_id_of(path)
        album = await self.album(album_id)
        tracks = (album.get("tracks") or {}).get("items") or []
        multi = len({t.get("media_number") or 1 for t in tracks}) > 1
        ext = path.rsplit(".", 1)[-1]
        track = next((t for t in tracks if track_path(album_id, t, multi, ext) == path), None)
        if track is None:
            raise QobuzError(M("qobuz.error.track_gone"))
        cfg = (await self.core.settings.get()).qobuz
        app_id, secret = await self.app()
        info = await self._file_url(track["id"], cfg.quality, app_id, secret, await self._token())
        if not info.get("url") or info.get("sample"):
            # Only a 30 s preview: the subscription doesn't cover it (or the track is restricted)
            raise QobuzError(M("qobuz.error.sample"))
        return info["url"]

    async def _stream(self, path: str, local: str, url: str) -> None:
        os.makedirs(os.path.dirname(local), exist_ok=True)
        part = local + ".incomplete"
        start = os.path.getsize(part) if os.path.exists(part) else 0
        headers = {"Range": f"bytes={start}-"} if start else {}
        async with self._client() as c, c.stream("GET", url, headers=headers) as r:
            if r.status_code == 416:  # already complete
                start, total = os.path.getsize(part), os.path.getsize(part)
            else:
                r.raise_for_status()
                if start and r.status_code != 206:
                    start = 0  # no resume support: from the start
                total = start + int(r.headers.get("content-length") or 0) or None
                done, t0, last = start, time.monotonic(), 0.0
                with open(part, "ab" if start else "wb") as f:
                    await self._emit(path, local, TransferState.TRANSFERRING, done, total)
                    async for chunk in r.aiter_bytes(256 * 1024):
                        f.write(chunk)
                        done += len(chunk)
                        now = time.monotonic()
                        if now - last >= 0.5:
                            last = now
                            speed = (done - start) / max(now - t0, 0.001)
                            await self._emit(path, local, TransferState.TRANSFERRING, done, total, speed, changed=False)
                total = done
        os.replace(part, local)
        await self._emit(path, local, TransferState.COMPLETE, total or 0, total)
