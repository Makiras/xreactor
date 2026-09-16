from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .components import Monitor
from .data import sample_data
from .events import XEvent
from .interfaces import ReadyValid, Role, Transfer
from .reactor import Registration, Subscription
from .execution import Execution
from .subscriptions import BoundSubscriptionSpec
from .triggers import RisingEdge

T = TypeVar("T")
Decoder = Callable[[Any], T]


class MonitorOverflowError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Candidate:
    value: Any
    rising: Registration


class ReadyValidMonitor(Monitor[T], Generic[T]):
    def __init__(
        self,
        interface: ReadyValid,
        *,
        decoder: Decoder[T] | None = None,
        delivery: str = "lossless",
        capacity: int = 64,
    ) -> None:
        if interface.role is not Role.MONITOR:
            raise ValueError("ReadyValidMonitor requires role=MONITOR")
        if delivery not in ("lossless", "latest"):
            raise ValueError("delivery must be 'lossless' or 'latest'")
        if capacity <= 0:
            raise ValueError("monitor capacity must be positive")
        self.interface = interface
        self.decoder = decoder
        self.delivery = delivery
        self.capacity = capacity
        self._queue: asyncio.Queue[Transfer[T]] = asyncio.Queue(capacity)
        self._execution: Execution | None = None
        self._subscription: Subscription | None = None

    def start(self, execution: Execution) -> "ReadyValidMonitor[T]":
        if self._subscription is not None:
            raise RuntimeError("monitor is already started")
        if execution.reactor is None:
            raise RuntimeError("monitor requires an active Execution")
        reactor = execution.reactor

        def capture(event: XEvent) -> _Candidate:
            del event
            value = sample_data(self.interface.bits)
            rising = reactor.register(RisingEdge(self.interface.clock))
            return _Candidate(value, rising)

        async def deliver(candidate: _Candidate) -> None:
            try:
                event = await candidate.rising.future
            finally:
                reactor.cancel(candidate.rising)
            value = (
                candidate.value
                if self.decoder is None
                else self.decoder(candidate.value)
            )
            self._put(Transfer(event=event, value=value))

        self._subscription = execution.subscribe(
            BoundSubscriptionSpec(
                trigger=self.interface.fire,
                handler=deliver,
                delivery="lossless",
                capacity=self.capacity,
                capture=capture,
            )
        )
        self._execution = execution
        return self

    async def recv(self) -> Transfer[T]:
        if self._subscription is None:
            raise RuntimeError("monitor is not started")
        return await self._queue.get()

    def __aiter__(self) -> "ReadyValidMonitor[T]":
        return self

    async def __anext__(self) -> Transfer[T]:
        return await self.recv()

    async def aclose(self) -> None:
        subscription = self._subscription
        execution = self._execution
        self._subscription = None
        self._execution = None
        if subscription is None or execution is None:
            return
        reactor = execution.reactor
        if reactor is None:
            return
        task = subscription.task
        reactor.cancel_subscription(subscription)
        while True:
            try:
                candidate = subscription.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                if isinstance(candidate, _Candidate):
                    reactor.cancel(candidate.rising)
            finally:
                subscription.queue.task_done()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    def _put(self, transfer: Transfer[T]) -> None:
        if self.delivery == "latest" and self._queue.full():
            self._queue.get_nowait()
            self._queue.task_done()
        try:
            self._queue.put_nowait(transfer)
        except asyncio.QueueFull as error:
            raise MonitorOverflowError(
                f"monitor queue overflow (capacity={self.capacity})"
            ) from error
