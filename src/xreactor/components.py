from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from .events import XEvent
from .interfaces import Interface, Transfer

T = TypeVar("T")


class Driver(ABC, Generic[T]):
    """Minimal common contract for an active protocol component."""

    interface: Interface

    @abstractmethod
    async def send(self, transaction: T) -> XEvent:
        """Drive one transaction and return its accepting simulation event."""

    @abstractmethod
    def close(self) -> None:
        """Release signal ownership held by this driver."""


class Monitor(ABC, Generic[T]):
    """Minimal common contract for a passive protocol component."""

    interface: Interface

    @abstractmethod
    def start(self, execution: Any) -> "Monitor[T]":
        """Attach this monitor to an active Execution."""

    @abstractmethod
    async def recv(self) -> Transfer[T]:
        """Receive the next immutable observed transfer."""

    @abstractmethod
    async def aclose(self) -> None:
        """Detach the monitor and cancel its internal registrations."""
