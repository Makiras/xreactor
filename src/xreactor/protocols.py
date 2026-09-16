from __future__ import annotations

from collections.abc import Callable
import inspect
from typing import Any

from ._context import current_reactor
from .events import XEvent, XPhase
from .signals import read_bool, write_signal
from .triggers import FallingEdge, RisingEdge, Value


def _refresh_comb() -> None:
    backend = current_reactor().backend
    refresh = getattr(backend, "refresh_comb", None)
    if refresh is not None:
        refresh()


async def drive_ready_valid(
    clock: Any,
    valid: Any,
    ready: Any,
    drive: Callable[[], None],
) -> XEvent:
    """Drive one ready/valid transaction and return its accepting rising edge.

    Payload and ``valid`` are driven in a falling-stable phase.  They remain
    stable through every non-accepting rising edge, and ``valid`` is withdrawn
    immediately after the first rising edge whose preceding falling phase had
    ``ready`` asserted.

    ``drive`` must be synchronous: allowing it to await would lose the stable
    drive phase and make transaction ownership ambiguous.
    """

    reactor = current_reactor()
    if getattr(reactor.backend, "phase", None) is not XPhase.FALLING_STABLE:
        await FallingEdge(clock)

    drive_result = drive()
    if inspect.isawaitable(drive_result):
        close = getattr(drive_result, "close", None)
        if close is not None:
            close()
        raise TypeError("drive callback must be synchronous and return None")
    if drive_result is not None:
        raise TypeError("drive callback must return None")
    valid_asserted = False
    try:
        write_signal(valid, 1, "valid")
        valid_asserted = True
        _refresh_comb()
        if not read_bool(ready, "ready"):
            # Stay in the native TriggerEngine while backpressured instead of
            # waking Python on every intermediate rising/falling phase.
            await Value(ready, 1, sample=FallingEdge(clock))
        return await RisingEdge(clock)
    finally:
        if valid_asserted:
            write_signal(valid, 0, "valid")
            _refresh_comb()
