from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class SupportsEval(Protocol):
    def evaluate(self, dut: Any) -> Any: ...


class XExpr:
    def evaluate(self, dut: Any) -> Any:
        raise NotImplementedError

    def __bool__(self) -> bool:
        raise TypeError(
            "XExpr cannot be converted to bool; use '&', '|' and '~' "
            "instead of Python 'and', 'or' and 'not'"
        )

    def __and__(self, other: Any) -> "XExpr":
        return BinaryExpr("and", self, as_expr(other))

    def __rand__(self, other: Any) -> "XExpr":
        return BinaryExpr("and", as_expr(other), self)

    def __or__(self, other: Any) -> "XExpr":
        return BinaryExpr("or", self, as_expr(other))

    def __ror__(self, other: Any) -> "XExpr":
        return BinaryExpr("or", as_expr(other), self)

    def __invert__(self) -> "XExpr":
        return UnaryExpr("not", self)

    def __eq__(self, other: Any) -> "XExpr":  # type: ignore[override]
        return BinaryExpr("eq", self, as_expr(other))

    def __ne__(self, other: Any) -> "XExpr":  # type: ignore[override]
        return BinaryExpr("ne", self, as_expr(other))

    def __lt__(self, other: Any) -> "XExpr":
        return BinaryExpr("lt", self, as_expr(other))

    def __le__(self, other: Any) -> "XExpr":
        return BinaryExpr("le", self, as_expr(other))

    def __gt__(self, other: Any) -> "XExpr":
        return BinaryExpr("gt", self, as_expr(other))

    def __ge__(self, other: Any) -> "XExpr":
        return BinaryExpr("ge", self, as_expr(other))


@dataclass(frozen=True, slots=True, eq=False)
class ConstantExpr(XExpr):
    value: Any

    def evaluate(self, dut: Any) -> Any:
        return self.value


@dataclass(frozen=True, slots=True, eq=False)
class SignalExpr(XExpr):
    path: tuple[str, ...]

    def __getattr__(self, name: str) -> "SignalExpr":
        return SignalExpr(self.path + (name,))

    def evaluate(self, dut: Any) -> Any:
        value = resolve_path(dut, self.path)
        return _read_bound_signal(value)


@dataclass(frozen=True, slots=True, eq=False)
class BoundSignalExpr(XExpr):
    signal: Any

    def evaluate(self, dut: Any) -> Any:
        del dut
        return _read_bound_signal(self.signal)


@dataclass(frozen=True, slots=True, eq=False)
class UnaryExpr(XExpr):
    op: str
    operand: XExpr

    def evaluate(self, dut: Any) -> Any:
        value = self.operand.evaluate(dut)
        if self.op == "not":
            return not bool(value)
        raise ValueError(f"unsupported unary operation: {self.op}")


@dataclass(frozen=True, slots=True, eq=False)
class BinaryExpr(XExpr):
    op: str
    left: XExpr
    right: XExpr

    def evaluate(self, dut: Any) -> Any:
        left = self.left.evaluate(dut)
        if self.op == "and":
            return bool(left) and bool(self.right.evaluate(dut))
        if self.op == "or":
            return bool(left) or bool(self.right.evaluate(dut))
        right = self.right.evaluate(dut)
        operations = {
            "eq": lambda: left == right,
            "ne": lambda: left != right,
            "lt": lambda: left < right,
            "le": lambda: left <= right,
            "gt": lambda: left > right,
            "ge": lambda: left >= right,
        }
        try:
            return operations[self.op]()
        except KeyError as exc:
            raise ValueError(f"unsupported binary operation: {self.op}") from exc


def as_expr(value: Any) -> XExpr:
    return value if isinstance(value, XExpr) else ConstantExpr(value)


def signal_expr(signal: Any) -> BoundSignalExpr:
    from .signals import as_xdata

    return BoundSignalExpr(as_xdata(signal))


def _read_bound_signal(signal: Any) -> Any:
    from .signals import read_signal

    return read_signal(signal)


def resolve_path(root: Any, path: tuple[str, ...]) -> Any:
    value = root
    for name in path:
        value = getattr(value, name)
    return value


class SymbolicDut:
    def __getattr__(self, name: str) -> SignalExpr:
        return SignalExpr((name,))


@dataclass(frozen=True, slots=True)
class WaitStep:
    condition: XExpr


@dataclass(frozen=True, slots=True)
class WithinStep:
    minimum: int
    maximum: int
    condition: XExpr

    def __post_init__(self) -> None:
        if self.minimum < 0 or self.maximum < self.minimum:
            raise ValueError("Within requires 0 <= minimum <= maximum")


@dataclass(frozen=True, slots=True)
class HoldStep:
    condition: XExpr
    cycles: int

    def __post_init__(self) -> None:
        if self.cycles <= 0:
            raise ValueError("Hold cycles must be positive")


SequenceStep = WaitStep | WithinStep | HoldStep


@dataclass(frozen=True, slots=True)
class SequenceSpec:
    steps: tuple[SequenceStep, ...]

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("Sequence requires at least one step")


def Wait(condition: Any) -> WaitStep:
    return WaitStep(as_expr(condition))


def Within(minimum: int, maximum: int, condition: Any) -> WithinStep:
    return WithinStep(minimum, maximum, as_expr(condition))


def Hold(condition: Any, *, cycles: int) -> HoldStep:
    return HoldStep(as_expr(condition), cycles)


def Sequence(*steps: SequenceStep) -> SequenceSpec:
    return SequenceSpec(tuple(steps))


@dataclass(frozen=True, slots=True)
class FsmTransitionSpec:
    condition: XExpr | None
    target: str | None = None
    terminal: str | None = None


@dataclass(frozen=True, slots=True)
class FsmStateSpec:
    transitions: tuple[FsmTransitionSpec, ...]


@dataclass(frozen=True, slots=True)
class FsmSpec:
    start: str
    states: tuple[tuple[str, FsmStateSpec], ...]

    def __post_init__(self) -> None:
        names = {name for name, _ in self.states}
        if self.start not in names:
            raise ValueError(f"FSM start state does not exist: {self.start}")
        for state_name, state in self.states:
            for transition in state.transitions:
                if transition.target is not None and transition.target not in names:
                    raise ValueError(
                        f"FSM state {state_name} targets unknown state "
                        f"{transition.target}"
                    )


class State:
    def __init__(self) -> None:
        self._transitions: list[FsmTransitionSpec] = []

    def when(self, condition: Any) -> "_TransitionBuilder":
        return _TransitionBuilder(self, as_expr(condition))

    def otherwise(self) -> "_TransitionBuilder":
        return _TransitionBuilder(self, None)

    def _append(self, transition: FsmTransitionSpec) -> "State":
        if self._transitions and self._transitions[-1].condition is None:
            raise ValueError("unconditional FSM transition must be last")
        self._transitions.append(transition)
        return self

    def freeze(self) -> FsmStateSpec:
        return FsmStateSpec(tuple(self._transitions))


class _TransitionBuilder:
    def __init__(self, state: State, condition: XExpr | None) -> None:
        self._state = state
        self._condition = condition

    def goto(self, target: str) -> State:
        return self._state._append(
            FsmTransitionSpec(self._condition, target=target)
        )

    def trigger(self, terminal: str = "MATCHED") -> State:
        return self._state._append(
            FsmTransitionSpec(self._condition, terminal=terminal)
        )


def FSM(*, start: str, states: dict[str, State]) -> FsmSpec:
    if not states:
        raise ValueError("FSM requires at least one state")
    return FsmSpec(
        start=start,
        states=tuple((name, state.freeze()) for name, state in states.items()),
    )
