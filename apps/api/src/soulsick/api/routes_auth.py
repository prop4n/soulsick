import time

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ..auth import COOKIE, MAX_AGE
from ..core import Core
from ..messages import M
from .deps import get_core
from .errors import http_error

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILURES = 5
WINDOW = 15 * 60
_failures: dict[str, list[float]] = {}


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _check_rate(ip: str) -> None:
    now = time.monotonic()
    recent = [t for t in _failures.get(ip, []) if now - t < WINDOW]
    _failures[ip] = recent
    if len(recent) >= MAX_FAILURES:
        raise http_error(429, "error.too_many_attempts")


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)


def _set_cookie(resp: Response, token: str, request: Request) -> None:
    resp.set_cookie(
        COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax",
        secure=request.url.scheme == "https",
    )


@router.get("/state")
async def state(request: Request, core: Core = Depends(get_core)) -> dict:
    admin = await core.auth.admin()
    user = await core.auth.check(request.cookies.get(COOKIE))
    return {"setup_required": admin is None, "authenticated": user is not None, "username": user}


@router.post("/setup")
async def setup(body: Credentials, request: Request, response: Response, core: Core = Depends(get_core)) -> dict:
    if await core.auth.admin() is not None:
        raise http_error(409, "error.admin_exists")
    await core.auth.setup(body.username, body.password)
    _set_cookie(response, await core.auth.issue(body.username), request)
    await core.journal.emit("auth.setup", M("auth.setup", name=body.username))
    return {"ok": True}


@router.post("/login")
async def login(body: Credentials, request: Request, response: Response, core: Core = Depends(get_core)) -> dict:
    _check_rate(_ip(request))
    if not await core.auth.verify(body.username, body.password):
        _failures.setdefault(_ip(request), []).append(time.monotonic())
        await core.journal.emit(
            "auth.failed", M("auth.failed", name=body.username), level="warning",
            data={"ip": request.client.host if request.client else None},
        )
        raise http_error(401, "error.invalid_credentials")
    _set_cookie(response, await core.auth.issue(body.username), request)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}
