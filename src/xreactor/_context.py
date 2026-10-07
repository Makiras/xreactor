from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .reactor import XReactor

_current_reactor: ContextVar["XReactor | None"] = ContextVar(
    "xreactor_current_reactor", default=None
)


def current_reactor() -> "XReactor":
    reactor = _current_reactor.get()
    if reactor is None:
        raise RuntimeError("XTrigger must be awaited inside an active Execution")
    return reactor


def bind_reactor(reactor: "XReactor | None") -> Token["XReactor | None"]:
    return _current_reactor.set(reactor)


def reset_reactor(token: Token["XReactor | None"]) -> None:
    _current_reactor.reset(token)
