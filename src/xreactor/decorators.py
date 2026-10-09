from __future__ import annotations

from functools import wraps
from dataclasses import dataclass, field
import inspect
from typing import Any, Callable, Concatenate, Generic, ParamSpec, TypeVar, cast, get_type_hints

from .ir import FsmSpec, SequenceSpec, SymbolicDut, XExpr, as_expr, resolve_path
from .triggers import (
    CompiledTrigger,
    ConditionMode,
    DriveStable,
    FallingEdge,
    PythonPredicateTrigger,
    PhaseTrigger,
    RisingEdge,
    normalize_condition_mode,
)

F = TypeVar("F", bound=Callable[..., Any])


def _bind_phase(sample: PhaseTrigger, dut: Any) -> PhaseTrigger:
    source = sample.source
    if isinstance(source, str):
        source = resolve_path(dut, tuple(source.split(".")))
    return type(sample)(source)


P = TypeVar("P")
A = ParamSpec("A")
Program = XExpr | SequenceSpec | FsmSpec
DeclaredProgram = Program | int | bool


def _declared_program(function, mode, args, kwargs):
    declared = function(SymbolicDut(), *args, **kwargs)
    if isinstance(declared, (SequenceSpec, FsmSpec)):
        if mode is not ConditionMode.ENTER:
            raise ValueError("condition mode applies only to expression xtrigger; Sequence/FSM already emit discrete terminal events")
        return declared
    return as_expr(declared)


@dataclass(frozen=True, eq=False)
class TriggerDefinition(Generic[P, A]):
    """Immutable declaration metadata over the existing trigger IR/factory."""
    function: Callable[Concatenate[P, A], DeclaredProgram]
    sample: PhaseTrigger | None = None
    mode: ConditionMode = ConditionMode.ENTER
    _args: tuple = field(default=(), repr=False)
    _kwargs: tuple = field(default=(), repr=False)
    _program: Any = field(default=None, init=False, repr=False)

    @property
    def __name__(self):
        return self.function.__name__

    @property
    def __wrapped__(self):
        return self.function

    @property
    def input_type(self):
        first = next(iter(inspect.signature(self.function).parameters))
        return get_type_hints(self.function).get(first)

    def __call__(self, dut: P, *args: A.args, **kwargs: A.kwargs) -> CompiledTrigger:
        program = (self.program if not args and not kwargs else
                   _declared_program(self.function, self.mode, args, kwargs))
        return CompiledTrigger(self.__name__, dut, program,
                               None if self.sample is None else _bind_phase(self.sample, dut), self.mode)

    def with_args(self, *args: A.args, **kwargs: A.kwargs) -> "TriggerDefinition[P, A]":
        bound = inspect.signature(self.function).bind(SymbolicDut(), *args, **kwargs)
        bound.apply_defaults()
        def immutable(value):
            if type(value) in (bool, int, str, type(None)):
                return
            if isinstance(value, tuple):
                for item in value:
                    immutable(item)
                return
            raise TypeError("xtrigger frozen parameters must be immutable bool/int/str/None/tuples")
        for value in tuple(bound.arguments.values())[1:]:
            immutable(value)
        return TriggerDefinition(self.function, self.sample, self.mode,
                                 tuple(bound.args[1:]), tuple(bound.kwargs.items()))

    @property
    def program(self) -> Program:
        if self._program is None:
            fixed = self.with_args(*self._args, **dict(self._kwargs))
            object.__setattr__(self, "_program", _declared_program(self.function, self.mode, fixed._args, dict(fixed._kwargs)))
        return self._program

    def bind(self, dut: P, *, sample: PhaseTrigger | None = None) -> CompiledTrigger:
        declared = None if self.sample is None else _bind_phase(self.sample, dut)
        if sample is not None and declared is not None and (type(sample) is not type(declared) or sample.source is not declared.source):
            raise ValueError("xtrigger sampling phase conflicts with coverage binding")
        return CompiledTrigger(self.__name__, dut, self.program, sample or declared, self.mode)


def xtrigger(
    *, sample: PhaseTrigger | None = None,
    mode: ConditionMode | str = ConditionMode.ENTER,
) -> Callable[[Callable[Concatenate[P, A], DeclaredProgram]], TriggerDefinition[P, A]]:
    if sample is not None and not isinstance(sample, (RisingEdge, FallingEdge, DriveStable)):
        raise TypeError("xtrigger sample must be RisingEdge, FallingEdge, or DriveStable")
    normalized = normalize_condition_mode(mode)
    def decorate(function):
        return TriggerDefinition(function, sample, normalized)
    return decorate


def pytrigger(
    *,
    sample: PhaseTrigger | None = None,
    mode: ConditionMode | str = ConditionMode.ENTER,
) -> Callable[[F], F]:
    if sample is not None and not isinstance(
        sample, (RisingEdge, FallingEdge, DriveStable)
    ):
        raise TypeError(
            "pytrigger sample must be RisingEdge, FallingEdge, or DriveStable"
        )

    mode = normalize_condition_mode(mode)

    def decorate(function: F) -> F:
        @wraps(function)
        def factory(
            dut: Any, *args: Any, **kwargs: Any
        ) -> PythonPredicateTrigger:
            def predicate() -> bool:
                result = function(dut, *args, **kwargs)
                if hasattr(result, "__await__"):
                    close = getattr(result, "close", None)
                    if close is not None:
                        close()
                    raise TypeError(
                        "pytrigger predicates must be synchronous; "
                        "use an asyncio source adapter for async work"
                    )
                return bool(result)

            return PythonPredicateTrigger(
                name=function.__name__,
                predicate=predicate,
                sample=None if sample is None else _bind_phase(sample, dut),
                mode=mode,
            )

        return cast(F, factory)

    return decorate
