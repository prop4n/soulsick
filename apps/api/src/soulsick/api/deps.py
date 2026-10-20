from fastapi import Depends, Request

from ..auth import COOKIE
from ..core import Core
from .errors import http_error


def get_core(request: Request) -> Core:
    return request.app.state.core


async def require_user(request: Request, core: Core = Depends(get_core)) -> str:
    user = await core.auth.check(request.cookies.get(COOKIE))
    if not user:
        raise http_error(401, "error.auth_required")
    return user
