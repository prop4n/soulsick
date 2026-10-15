from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..auth import COOKIE, MAX_AGE
from ..core import Core
from .deps import get_core

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
        raise HTTPException(409, "Le compte administrateur existe déjà")
    await core.auth.setup(body.username, body.password)
    _set_cookie(response, await core.auth.issue(body.username), request)
    await core.journal.emit("auth.setup", f"Compte administrateur « {body.username} » créé")
    return {"ok": True}


@router.post("/login")
async def login(body: Credentials, request: Request, response: Response, core: Core = Depends(get_core)) -> dict:
    if not await core.auth.verify(body.username, body.password):
        await core.journal.emit(
            "auth.failed", f"Tentative de connexion refusée pour « {body.username} »", level="warning",
            data={"ip": request.client.host if request.client else None},
        )
        raise HTTPException(401, "Identifiants invalides")
    _set_cookie(response, await core.auth.issue(body.username), request)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE)
    return {"ok": True}
