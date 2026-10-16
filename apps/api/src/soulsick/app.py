import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import logbuffer
from .api import routes_auth, routes_catalog, routes_network, routes_system
from .auth import COOKIE
from .config import Env, get_env
from .core import Core

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# aioslsk est très bavard : la sortie du conteneur ne garde que ses erreurs, la page Console reçoit tout
logbuffer.install()


def create_app(env: Env | None = None, core: Core | None = None) -> FastAPI:
    env = env or get_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = core or Core(env)
        app.state.core = c
        logbuffer.BUFFER.attach(asyncio.get_running_loop(), c.hub.publish)
        await c.start()
        ticker = asyncio.create_task(_status_ticker(c))
        flusher = asyncio.create_task(logbuffer.BUFFER.flush_loop())
        try:
            yield
        finally:
            ticker.cancel()
            flusher.cancel()
            await c.stop()

    app = FastAPI(title="Soulsick", version=__version__, lifespan=lifespan)
    for r in (routes_auth, routes_system, routes_catalog, routes_network):
        app.include_router(r.router)

    @app.websocket("/api/ws")
    async def ws(socket: WebSocket):
        c: Core = socket.app.state.core
        origin = socket.headers.get("origin")
        if origin and urlparse(origin).netloc != socket.headers.get("host"):
            # Un autre site ne peut pas ouvrir le flux temps réel avec ta session
            await socket.close(code=4403)
            return
        if not await c.auth.check(socket.cookies.get(COOKIE)):
            await socket.close(code=4401)
            return
        await socket.accept()
        q = c.hub.subscribe()
        try:
            await socket.send_json({"type": "status", "data": c.engine.status()})
            await socket.send_json({"type": "hunter", "data": c.hunter.state()})
            while True:
                msg = await q.get()
                await socket.send_json(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            c.hub.unsubscribe(q)

    _mount_web(app, env.web_dist)
    return app


async def _status_ticker(core: Core) -> None:
    """Statut réseau (vitesses, slots) poussé toutes les 2 s."""
    while True:
        await asyncio.sleep(2)
        with contextlib.suppress(Exception):
            core.hub.publish("status", core.engine.status())


def _mount_web(app: FastAPI, dist: Path | None) -> None:
    """Sert le front compilé (SPA) si disponible."""
    if dist is None:
        candidate = Path(__file__).resolve().parents[3] / "web" / "dist"
        dist = candidate if candidate.is_dir() else None
    if dist is None or not dist.is_dir():
        return
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    index = dist / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return FileResponse(index, status_code=404)
        f = (dist / path).resolve()
        if path and f.is_file() and dist.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(index)
