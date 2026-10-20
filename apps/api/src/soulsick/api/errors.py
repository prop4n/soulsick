"""Translatable API errors: `detail` carries the English text plus key + params."""

from typing import Any

from fastapi import HTTPException

from ..messages import Msg, UserError


def http_error(status: int, key: str | Msg, **params: Any) -> HTTPException:
    msg = key if isinstance(key, Msg) else Msg(key, params)
    return HTTPException(status, {"message": msg.text, **msg.to_json()})


def as_http(e: Exception, status: int = 400) -> HTTPException:
    """A service error turned into an API error (translatable when it is a `UserError`)."""
    from ..slsk.engine import EngineUnavailable

    if isinstance(e, UserError):
        return http_error(status, e.msg)
    if isinstance(e, EngineUnavailable):
        return http_error(503, e.msg)
    return HTTPException(status, str(e))
