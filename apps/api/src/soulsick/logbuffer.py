"""Logs techniques en direct : tampon circulaire + diffusion par paquets vers l'interface (page Console).

Le journal (journal.py) raconte les décisions ; ici, c'est le travail brut : connexions aux pairs,
réponses de recherche, transferts, requêtes MusicBrainz…
"""

import asyncio
import itertools
import logging
from collections import deque
from datetime import UTC, datetime

# logger → source affichée dans l'interface
SOURCES = [
    ("aioslsk", "soulseek"),
    ("soulsick.slsk", "soulseek"),
    ("soulsick.search", "recherche"),
    ("soulsick.services.hunter", "chasse"),
    ("soulsick.services.importer", "import"),
    ("soulsick.services", "app"),
    ("soulsick.musicbrainz", "musicbrainz"),
    ("httpx", "http"),
    ("uvicorn.access", "web"),
    ("uvicorn", "web"),
    ("soulsick.journal", "journal"),
]


def source_of(name: str) -> str:
    for prefix, src in SOURCES:
        if name == prefix or name.startswith(prefix + "."):
            return src
    return "app"


class LogBuffer(logging.Handler):
    def __init__(self, capacity: int = 3000) -> None:
        super().__init__(level=logging.INFO)
        self.records: deque[dict] = deque(maxlen=capacity)
        self._pending: list[dict] = []
        self._ids = itertools.count(1)
        self._loop: asyncio.AbstractEventLoop | None = None
        self.publish = None  # callable(type, data), branché sur le Hub

    def attach(self, loop: asyncio.AbstractEventLoop, publish) -> None:
        self._loop = loop
        self.publish = publish

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        source = source_of(record.name)
        if source == "http" and ("musicbrainz.org" in msg or "coverartarchive.org" in msg):
            source = "musicbrainz"
        entry = {
            "id": next(self._ids),
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "source": source,
            "logger": record.name,
            "message": msg if len(msg) < 2000 else msg[:2000] + "…",
        }
        # Peut être appelé depuis un thread (asyncio.to_thread) : deque.append est thread-safe
        self.records.append(entry)
        self._pending.append(entry)

    async def flush_loop(self) -> None:
        """Envoie les nouvelles lignes par paquets (2 fois par seconde) : jamais de rafale par ligne."""
        while True:
            await asyncio.sleep(0.5)
            if not self._pending or not self.publish:
                continue
            batch, self._pending = self._pending, []
            self.publish("logs", batch[-500:])

    def since(self, after: int = 0, limit: int = 1000) -> list[dict]:
        return [r for r in list(self.records) if r["id"] > after][-limit:]


class _QuietForStdout(logging.Filter):
    """Sortie console du conteneur : aioslsk seulement en erreur (sinon illisible).
    La page Console, elle, reçoit tout."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("aioslsk"):
            return record.levelno >= logging.ERROR
        return True


BUFFER = LogBuffer()


def install() -> LogBuffer:
    root = logging.getLogger()
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    if BUFFER not in root.handlers:
        for h in root.handlers:
            h.addFilter(_QuietForStdout())
        root.addHandler(BUFFER)
        logging.getLogger("aioslsk").setLevel(logging.INFO)
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            lg = logging.getLogger(name)
            if BUFFER not in lg.handlers and not lg.propagate:
                lg.addHandler(BUFFER)
    return BUFFER
