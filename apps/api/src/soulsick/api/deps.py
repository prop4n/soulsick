from fastapi import Depends, HTTPException, Request

from ..auth import COOKIE
from ..core import Core


def get_core(request: Request) -> Core:
    return request.app.state.core


async def require_user(request: Request, core: Core = Depends(get_core)) -> str:
    user = await core.auth.check(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "Authentification requise")
    return user
