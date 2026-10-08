"""Proposed signatures only. No runtime implementation or native support."""

from typing import Callable, Concatenate, Final, Generic, Literal, ParamSpec, Self, TypeAlias, TypeVar, overload

from xreactor.coverage import BinKind
from xreactor.ir import FsmSpec, SequenceSpec, XExpr
from xreactor.triggers import CompiledTrigger, ConditionMode, PhaseTrigger

P = TypeVar("P")
A = ParamSpec("A")
C = TypeVar("C", bound=type[object])
Program: TypeAlias = XExpr | SequenceSpec | FsmSpec

# Proposed signal-view leaves. Width/sign/runtime binding remain to implement.
class BoolSignal(XExpr):
    def __init__(self, source: object, *, source_id: str | None = None) -> None: ...
class UIntSignal(XExpr):
    def __init__(self, source: object, *, source_id: str | None = None) -> None: ...

class Terminal: ...
class AllTerminals: ...
ALL_TERMINALS: Final[AllTerminals]

class TriggerPattern(Generic[P]):
    def bind(self, pins: P, *, sample: PhaseTrigger | None = None) -> CompiledTrigger: ...

class TriggerDefinition(TriggerPattern[P], Generic[P, A]):
    def __call__(self, pins: P, *args: A.args, **kwargs: A.kwargs) -> CompiledTrigger: ...
    def with_args(self, *args: A.args, **kwargs: A.kwargs) -> TriggerPattern[P]: ...

def xtrigger(
    *, sample: PhaseTrigger | None = None, mode: ConditionMode = ConditionMode.ENTER
) -> Callable[[Callable[Concatenate[P, A], Program]], TriggerDefinition[P, A]]: ...

class PatternBinRule(Generic[P]): ...
PatternBin: TypeAlias = TriggerPattern[P] | PatternBinRule[P]

class Bin:
    @staticmethod
    def pattern(
        pattern: TriggerPattern[P], *, at_least: int = 1,
        kind: BinKind = BinKind.NORMAL,
        terminals: tuple[Terminal, ...] | AllTerminals | None = None,
        overlap: bool = False, max_active: int | None = None,
    ) -> PatternBinRule[P]: ...

class BoundTemporalPoint(Generic[P]):
    def count(self, bin: PatternBin[P]) -> int: ...
    @property
    def observations(self) -> int: ...

class TemporalCoverPoint(Generic[P]):
    @overload
    def __get__(self, instance: None, owner: type[object]) -> Self: ...
    @overload
    def __get__(self, instance: object, owner: type[object] | None = None) -> BoundTemporalPoint[P]: ...

class CompiledSignalGroup(Generic[P]):
    def explain(self) -> str: ...

class SignalCoverGroup(Generic[P]):
    def __init__(self, *, instance: str) -> None: ...
    @classmethod
    def compile(cls) -> CompiledSignalGroup[P]: ...
    def bind(
        self, *, pins: P, sample: PhaseTrigger,
        strategy: Literal["native", "python", "auto"] = "native",
    ) -> None: ...

def covergroup(*, schema_id: str, contract: str | None = None) -> Callable[[C], C]: ...
