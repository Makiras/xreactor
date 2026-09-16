from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Generic, TypeVar

from ._context import current_reactor
from .components import Driver
from .data import drive_data, iter_data_leaves
from .events import XEvent
from .interfaces import ReadyValid, Role
from .protocols import drive_ready_valid
from .signals import signal_identity

T = TypeVar("T")
Encoder = Callable[[Any, T], None]


class ReadyValidDriver(Driver[T], Generic[T]):
    def __init__(
        self,
        interface: ReadyValid,
        *,
        encoder: Encoder[T] | None = None,
    ) -> None:
        if interface.role is not Role.PRODUCER:
            raise ValueError("ReadyValidDriver requires role=PRODUCER")
        self.interface = interface
        self.encoder = encoder
        self._lock = asyncio.Lock()
        self._reactor: Any = None
        self._claimed = False

    async def send(self, transaction: T) -> XEvent:
        reactor = current_reactor()
        self._claim(reactor)
        async with self._lock:
            def drive() -> None:
                if self.encoder is None:
                    drive_data(
                        self.interface.bits,
                        transaction,
                        f"{self.interface.name}.bits",
                    )
                else:
                    result = self.encoder(self.interface.bits, transaction)
                    if result is not None:
                        raise TypeError("driver encoder must return None")

            return await drive_ready_valid(
                self.interface.clock,
                self.interface.valid,
                self.interface.ready,
                drive,
            )

    def close(self) -> None:
        if self._claimed and self._reactor is not None:
            self._reactor.release_driver(self)
        self._claimed = False
        self._reactor = None

    async def __aenter__(self) -> "ReadyValidDriver[T]":
        self._claim(current_reactor())
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _claim(self, reactor: Any) -> None:
        if self._claimed:
            if self._reactor is not reactor:
                raise RuntimeError(
                    "driver is already bound to another Execution"
                )
            return
        signals = [self.interface.valid]
        signals.extend(
            signal
            for _, signal in iter_data_leaves(
                self.interface.bits, f"{self.interface.name}.bits"
            )
        )
        outputs = [
            signal
            for signal in signals
            if callable(getattr(signal, "IsOutIO", None))
            and signal.IsOutIO()
        ]
        if outputs:
            raise ValueError(
                "ReadyValidDriver cannot drive DUT output signals"
            )
        reactor.claim_driver(
            self,
            tuple((signal_identity(signal), signal) for signal in signals),
        )
        self._reactor = reactor
        self._claimed = True
