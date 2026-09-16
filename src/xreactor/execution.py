from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import Token
from typing import AsyncIterator

from ._context import bind_reactor, reset_reactor
from .backend import RunLimit, SimulationBackend
from .events import XPhase
from .reactor import XReactor
from .reactor import Subscription
from .subscriptions import BoundSubscriptionSpec
from .triggers import DriveStable, FallingEdge, PhaseTrigger, RisingEdge


class Execution:
    def __init__(
        self,
        backend: SimulationBackend,
        *,
        default_sample: PhaseTrigger | None = None,
        max_batch_ticks: int = 4096,
        quantum_ms: float = 10.0,
        budget_check_interval: int = 64,
    ) -> None:
        if max_batch_ticks <= 0:
            raise ValueError("max_batch_ticks must be positive")
        if quantum_ms <= 0:
            raise ValueError("quantum_ms must be positive")
        if budget_check_interval <= 0:
            raise ValueError("budget_check_interval must be positive")
        if default_sample is not None and not isinstance(
            default_sample, (RisingEdge, FallingEdge, DriveStable)
        ):
            raise TypeError(
                "default_sample must be RisingEdge, FallingEdge, or "
                "DriveStable"
            )
        capabilities = getattr(backend, "capabilities", None)
        if capabilities is None:
            raise TypeError("simulation backend must declare capabilities")
        if not capabilities.half_step or not capabilities.stable_sample:
            raise RuntimeError(
                "simulation backend must provide half-step stable sampling"
            )
        self.backend = backend
        self.default_sample = default_sample
        self.max_batch_ticks = max_batch_ticks
        self.quantum_ms = quantum_ms
        self.budget_check_interval = budget_check_interval
        self.reactor: XReactor | None = None
        self._pump_task: asyncio.Task[None] | None = None
        self._context_token: Token[XReactor | None] | None = None
        self._closing = False
        self._pause_depth = 0
        self._resume = asyncio.Event()
        self._resume.set()

    async def __aenter__(self) -> "Execution":
        if self.reactor is not None:
            raise RuntimeError("Execution cannot be entered twice")
        self.backend.acquire(self)
        try:
            self.reactor = XReactor(
                self.backend, default_sample=self.default_sample
            )
            self._context_token = bind_reactor(self.reactor)
            self._pump_task = asyncio.create_task(
                self._run_pump(), name="xreactor-execution-pump"
            )
        except BaseException:
            self.backend.release(self)
            raise
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self._closing = True
        self._resume.set()
        assert self.reactor is not None
        self.reactor.work_available.set()
        try:
            if self._pump_task is not None:
                await self._pump_task
        finally:
            try:
                await self.reactor.aclose()
            finally:
                try:
                    self.backend.clear_execution_state()
                finally:
                    try:
                        if self._context_token is not None:
                            reset_reactor(self._context_token)
                    finally:
                        self.backend.release(self)

    @asynccontextmanager
    async def paused(self) -> AsyncIterator[None]:
        self._pause_depth += 1
        self._resume.clear()
        await asyncio.sleep(0)
        try:
            yield
        finally:
            self._pause_depth -= 1
            if self._pause_depth == 0:
                self._resume.set()

    def subscribe(self, spec: BoundSubscriptionSpec) -> Subscription:
        if self.reactor is None:
            raise RuntimeError("subscribe requires an active Execution")
        return self.reactor.subscribe(spec)

    async def _run_pump(self) -> None:
        assert self.reactor is not None
        try:
            while not self._closing:
                await self.reactor.work_available.wait()
                self.reactor.raise_background_error()
                if self._closing:
                    break
                await self._resume.wait()
                if not self.reactor.has_execution_work:
                    self.reactor.work_available.clear()
                    continue
                result = self.backend.run_until(
                    RunLimit(
                        max_ticks=self.max_batch_ticks,
                        max_wall_time_ms=self.quantum_ms,
                        budget_check_interval=self.budget_check_interval,
                    )
                )
                if result.advanced_ticks == 0 and not result.hits:
                    raise RuntimeError(
                        f"simulation backend stalled: {result.stop_reason}"
                    )
                self.reactor.publish(result)
                # A phase barrier must give resolved waiters a chance to run
                # before this task may enter the backend again.
                await asyncio.sleep(0)
                self.reactor.raise_background_error()
                if (
                    result.stopped_phase is XPhase.FALLING_STABLE
                    and self.reactor.has_drive_stable_work
                ):
                    drive_result = self.backend.sample_drive_stable()
                    if drive_result is not None:
                        self.reactor.publish(drive_result)
                        await asyncio.sleep(0)
                        self.reactor.raise_background_error()
        except BaseException as error:
            if not isinstance(error, asyncio.CancelledError):
                self.reactor.fail(error)
            raise
