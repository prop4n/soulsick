"""Moteur Soulseek : enveloppe d'aioslsk exposant une API simple au reste de Soulsick.

- recherches (collecte des résultats pendant une fenêtre de temps) ;
- téléchargements routés vers un dossier précis (pas de dossier de téléchargement global) ;
- parcours des partages d'un pair ;
- partages filtrés par nos règles (extensions autorisées, motifs exclus).
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from aioslsk.client import SoulSeekClient
from aioslsk.commands import PeerGetSharesCommand
from aioslsk.events import (
    SearchResultEvent,
    SessionDestroyedEvent,
    SessionInitializedEvent,
    TransferAddedEvent,
    TransferProgressEvent,
)
from aioslsk.exceptions import AuthenticationError
from aioslsk.protocol.primitives import AttributeKey, FileData
from aioslsk.search.model import SearchResult
from aioslsk.settings import (
    CredentialsSettings,
    NetworkLimitSettings,
    NetworkSettings,
    ReconnectSettings,
    ServerSettings,
    Settings,
    SharedDirectorySettingEntry,
    SharesSettings,
    TransferLimitSettings,
    TransfersSettings,
    UpnpSettings,
    UserInfoSettings,
)
from aioslsk.settings import ListeningSettings as SlskListening
from aioslsk.shares.manager import SharesManager
from aioslsk.shares.model import SharedDirectory
from aioslsk.transfer.model import Transfer as SlskTransfer
from aioslsk.transfer.model import TransferDirection
from aioslsk.transfer.state import TransferState as SlskState

from ..models import TransferState
from ..scoring import PeerResult, RemoteFile
from ..settings_store import SoulseekSettings
from .rules import ShareRules

log = logging.getLogger(__name__)


class EngineUnavailable(Exception):
    pass


_STATE_MAP = {
    SlskState.VIRGIN: TransferState.QUEUED,
    SlskState.QUEUED: TransferState.QUEUED,
    SlskState.INITIALIZING: TransferState.INITIALIZING,
    SlskState.INCOMPLETE: TransferState.QUEUED,  # aioslsk relance automatiquement
    SlskState.DOWNLOADING: TransferState.TRANSFERRING,
    SlskState.UPLOADING: TransferState.TRANSFERRING,
    SlskState.COMPLETE: TransferState.COMPLETE,
    SlskState.FAILED: TransferState.FAILED,
    SlskState.ABORTED: TransferState.ABORTED,
    SlskState.PAUSED: TransferState.PAUSED,
}


@dataclass
class TransferUpdate:
    direction: str
    username: str
    remote_path: str
    local_path: str | None
    size: int | None
    bytes_transferred: int
    speed: float
    state: str
    place_in_queue: int | None
    error: str | None
    state_changed: bool


@dataclass
class LiveSearch:
    ticket: int
    query: str
    started: float
    results: list[PeerResult] = field(default_factory=list)


def remote_file(fd: FileData, directory: str | None = None) -> RemoteFile:
    attrs = fd.get_attribute_map()
    name = fd.filename if directory is None else f"{directory}\\{fd.filename}"
    return RemoteFile(
        filename=name,
        size=fd.filesize,
        bitrate=attrs.get(AttributeKey.BITRATE),
        duration=attrs.get(AttributeKey.DURATION),
        sample_rate=attrs.get(AttributeKey.SAMPLE_RATE),
        bit_depth=attrs.get(AttributeKey.BIT_DEPTH),
        vbr=bool(attrs.get(AttributeKey.VBR)),
    )


class FilteringSharesManager(SharesManager):
    """SharesManager qui applique nos règles après chaque scan : un fichier exclu n'est
    ni indexé, ni proposé en résultat de recherche, ni téléchargeable."""

    rules: dict[str, ShareRules]

    async def scan_directory_files(self, shared_directory: SharedDirectory):
        await super().scan_directory_files(shared_directory)
        rules = getattr(self, "rules", {}).get(shared_directory.absolute_path)
        if rules is None:
            return
        kept = {
            item
            for item in shared_directory.items
            if rules.check(os.path.join(item.subdir, item.filename)) is None
        }
        removed = shared_directory.items - kept
        if removed:
            shared_directory.items = kept
            self._term_map = {}
            for d in self._shared_directories:
                self._build_term_map(d)
            self._cleanup_term_map()


class _Client(SoulSeekClient):
    def create_shares_manager(self, cache, executor_factory=None):
        return FilteringSharesManager(
            self.settings, self.events, self.network, cache=cache, executor_factory=executor_factory
        )


TransferCallback = Callable[[TransferUpdate], Awaitable[None]]
StatusCallback = Callable[[dict], None]


class SlskEngine:
    def __init__(self, downloads_dir: str) -> None:
        self.downloads_dir = downloads_dir
        self.client: _Client | None = None
        self.config: SoulseekSettings | None = None
        self.shares: list[ShareRules] = []
        self.logged_in = False
        self.connecting = False
        self.error: str | None = None
        self.searches: dict[int, LiveSearch] = {}
        self.on_transfer: TransferCallback | None = None
        self.on_status: StatusCallback | None = None
        self.on_info: Callable[[str, str, dict], Awaitable[None]] | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._stopping = False

    # --- Cycle de vie ---------------------------------------------------------

    def _build_settings(self, cfg: SoulseekSettings) -> Settings:
        return Settings(
            credentials=CredentialsSettings(
                username=cfg.username,
                password=cfg.password,
                info=UserInfoSettings(description=cfg.description),
            ),
            network=NetworkSettings(
                server=ServerSettings(reconnect=ReconnectSettings(auto=True)),
                listening=SlskListening(port=cfg.listen_port, obfuscated_port=cfg.listen_port + 1),
                upnp=UpnpSettings(enabled=cfg.upnp),
                limits=NetworkLimitSettings(
                    upload_speed_kbps=cfg.upload_speed_kbps,
                    download_speed_kbps=cfg.download_speed_kbps,
                ),
            ),
            shares=SharesSettings(
                scan_on_start=True,
                download=os.path.join(self.downloads_dir, "manual"),
                directories=[SharedDirectorySettingEntry(path=s.path) for s in self.shares],
            ),
            transfers=TransfersSettings(limits=TransferLimitSettings(upload_slots=cfg.upload_slots)),
        )

    def status(self) -> dict:
        c = self.client
        dirs, files = c.shares.get_stats() if c else (0, 0)
        return {
            "configured": bool(self.config and self.config.username and self.config.password),
            "connected": self.logged_in,
            "connecting": self.connecting,
            "username": self.config.username if self.config else None,
            "error": self.error,
            "download_speed": c.transfers.get_download_speed() if c else 0,
            "upload_speed": c.transfers.get_upload_speed() if c else 0,
            "free_upload_slots": c.transfers.get_free_upload_slots() if c else 0,
            "upload_slots": self.config.upload_slots if self.config else 0,
            "shared_folders": dirs,
            "shared_files": files,
        }

    def _publish_status(self) -> None:
        if self.on_status:
            self.on_status(self.status())

    async def start(self, cfg: SoulseekSettings, shares: list[ShareRules]) -> None:
        await self.stop()
        self._stopping = False
        self.config = cfg
        self.shares = [s for s in shares if os.path.isdir(s.path)]
        self.error = None
        if not (cfg.username and cfg.password):
            self.error = "Identifiants Soulseek non configurés"
            self._publish_status()
            return
        self._reconnect_task = asyncio.create_task(self._connect_loop())

    async def _connect_loop(self) -> None:
        delay = 5
        while not self._stopping:
            self.connecting = True
            self._publish_status()
            try:
                await self._connect_once()
                self.connecting = False
                self._publish_status()
                return
            except AuthenticationError as e:
                self.error = f"Authentification refusée par le serveur : {e.reason or 'identifiants invalides'}"
                self.connecting = False
                await self._info("slsk.auth_failed", self.error, {})
                self._publish_status()
                await self._teardown()
                return
            except Exception as e:  # réseau, ports…
                self.error = f"Connexion impossible : {e!r}"
                await self._info("slsk.connect_failed", f"{self.error} — nouvel essai dans {delay}s", {})
                await self._teardown()
                self._publish_status()
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)

    async def _connect_once(self) -> None:
        assert self.config
        client = _Client(self._build_settings(self.config))
        client.shares.rules = {os.path.normpath(os.path.abspath(s.path)): s for s in self.shares}
        self.client = client
        client.events.register(SessionInitializedEvent, self._on_session_init)
        client.events.register(SessionDestroyedEvent, self._on_session_destroyed)
        client.events.register(SearchResultEvent, self._on_search_result)
        client.events.register(TransferProgressEvent, self._on_progress)
        client.events.register(TransferAddedEvent, self._on_transfer_added)
        await client.start()
        await client.login()

    async def _teardown(self) -> None:
        c, self.client = self.client, None
        self.logged_in = False
        if c:
            try:
                await c.stop()
            except Exception:
                log.exception("arrêt du client aioslsk")

    async def stop(self) -> None:
        self._stopping = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        await self._teardown()
        self.connecting = False

    async def _info(self, kind: str, message: str, data: dict, level: str = "warning") -> None:
        if self.on_info:
            await self.on_info(kind, message, {**data, "level": level})

    def _require(self) -> _Client:
        if not self.client or not self.logged_in:
            raise EngineUnavailable(self.error or "Non connecté au réseau Soulseek")
        return self.client

    # --- Événements aioslsk ---------------------------------------------------

    async def _on_session_init(self, event: SessionInitializedEvent) -> None:
        self.logged_in = True
        self.error = None
        await self._info(
            "slsk.connected",
            f"Connecté au réseau Soulseek en tant que {event.session.user.name}",
            {"ip": event.session.ip_address, "greeting": event.session.greeting},
            level="info",
        )
        self._publish_status()

    async def _on_session_destroyed(self, event: SessionDestroyedEvent) -> None:
        self.logged_in = False
        if not self._stopping:
            await self._info("slsk.disconnected", "Déconnecté du serveur Soulseek (reconnexion automatique)", {})
        self._publish_status()

    async def _on_search_result(self, event: SearchResultEvent) -> None:
        live = self.searches.get(event.query.ticket)
        if live is None:
            return
        r: SearchResult = event.result
        live.results.append(
            PeerResult(
                username=r.username,
                has_free_slots=r.has_free_slots,
                avg_speed=r.avg_speed,
                queue_size=r.queue_size,
                files=[remote_file(f) for f in r.shared_items],
            )
        )

    async def _on_transfer_added(self, event: TransferAddedEvent) -> None:
        t = event.transfer
        await self._emit_transfer(t, t.progress_snapshot.state, changed=True)

    async def _on_progress(self, event: TransferProgressEvent) -> None:
        for t, prev, cur in event.updates:
            await self._emit_transfer(t, cur.state, changed=prev.state != cur.state)

    async def _emit_transfer(self, t: SlskTransfer, state: SlskState.State, changed: bool) -> None:
        if not self.on_transfer:
            return
        mapped = _STATE_MAP.get(state, TransferState.QUEUED)
        upd = TransferUpdate(
            direction="upload" if t.direction == TransferDirection.UPLOAD else "download",
            username=t.username,
            remote_path=t.remote_path,
            local_path=t.local_path,
            size=t.filesize,
            bytes_transferred=t.bytes_transfered,
            speed=t.get_speed() if hasattr(t, "get_speed") else 0.0,
            state=mapped,
            place_in_queue=t.place_in_queue,
            error=t.fail_reason or t.abort_reason,
            state_changed=changed,
        )
        try:
            await self.on_transfer(upd)
        except Exception:
            log.exception("callback de transfert")

    # --- Recherche ------------------------------------------------------------

    async def start_search(self, query: str) -> LiveSearch:
        c = self._require()
        req = await c.searches.search(query)
        live = LiveSearch(ticket=req.ticket, query=query, started=time.time())
        self.searches[req.ticket] = live
        # Nettoyage des vieilles recherches (on garde les 50 dernières)
        if len(self.searches) > 50:
            for k in sorted(self.searches, key=lambda k: self.searches[k].started)[:-50]:
                self.searches.pop(k, None)
        return live

    async def search(self, query: str, wait_s: float) -> list[PeerResult]:
        live = await self.start_search(query)
        await asyncio.sleep(wait_s)
        return list(live.results)

    # --- Transferts -----------------------------------------------------------

    async def download(self, username: str, remote_path: str, dest_dir: str) -> None:
        """Télécharge un fichier distant vers `dest_dir` (le nom de fichier distant est conservé)."""
        c = self._require()
        os.makedirs(dest_dir, exist_ok=True)
        name = remote_path.replace("\\", "/").rsplit("/", 1)[-1]
        existing = c.transfers.find_transfer(username, remote_path, TransferDirection.DOWNLOAD)
        if existing is not None:
            existing.local_path = os.path.join(dest_dir, name)
            await c.transfers.queue(existing)
            return
        t = await c.transfers.download(username, remote_path, paused=True)
        t.local_path = os.path.join(dest_dir, name)
        await c.transfers.queue(t)

    def _find(self, username: str, remote_path: str, direction: str) -> SlskTransfer | None:
        c = self._require()
        d = TransferDirection.UPLOAD if direction == "upload" else TransferDirection.DOWNLOAD
        return c.transfers.find_transfer(username, remote_path, d)

    async def abort(self, username: str, remote_path: str, direction: str) -> None:
        t = self._find(username, remote_path, direction)
        if t:
            try:
                await self._require().transfers.abort(t)
            except Exception as e:
                log.info("abort : %s", e)

    async def retry(self, username: str, remote_path: str, direction: str = "download") -> bool:
        t = self._find(username, remote_path, direction)
        if t is None:
            return False
        await self._require().transfers.queue(t)
        return True

    async def remove(self, username: str, remote_path: str, direction: str) -> None:
        t = self._find(username, remote_path, direction)
        if t:
            await self._require().transfers.remove(t)

    # --- Parcourir un pair ----------------------------------------------------

    async def browse(self, username: str, timeout: float = 90) -> dict:
        c = self._require()
        directories, locked = await c.execute(PeerGetSharesCommand(username), response=True, timeout=timeout)
        def conv(dirs):
            return [
                {
                    "path": d.name,
                    "files": [
                        remote_file(f, d.name).to_dict() | {"name": f.filename}
                        for f in d.files
                    ],
                }
                for d in dirs
            ]
        return {"directories": conv(directories), "locked": conv(locked)}

    # --- Partages -------------------------------------------------------------

    async def apply_shares(self, shares: list[ShareRules]) -> None:
        """Met à jour les dossiers partagés à chaud puis relance un scan."""
        self.shares = [s for s in shares if os.path.isdir(s.path)]
        c = self.client
        if not c:
            return
        mgr: FilteringSharesManager = c.shares  # type: ignore[assignment]
        mgr.rules = {os.path.normpath(os.path.abspath(s.path)): s for s in self.shares}
        wanted = set(mgr.rules)
        for d in list(mgr.shared_directories):
            if d.absolute_path not in wanted:
                mgr.remove_shared_directory(d)
        for path in wanted:
            if not mgr.is_directory_shared(path):
                mgr.add_shared_directory(path)
        await mgr.scan()
        self._publish_status()

    def uploads_snapshot(self) -> list[SlskTransfer]:
        return self.client.transfers.get_uploads() if self.client else []
