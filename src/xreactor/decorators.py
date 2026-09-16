from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar, cast

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


def xtrigger(
    *,
    sample: PhaseTrigger | None = None,
    mode: ConditionMode | str = ConditionMode.ENTER,
) -> Callable[[F], F]:
    if sample is not None and not isinstance(
        sample, (RisingEdge, FallingEdge, DriveStable)
    ):
        raise TypeError(
            "xtrigger sample must be RisingEdge, FallingEdge, or DriveStable"
        )

    mode = normalize_condition_mode(mode)

    def decorate(function: F) -> F:
        @wraps(function)
        def factory(dut: Any, *args: Any, **kwargs: Any) -> CompiledTrigger:
            symbolic = SymbolicDut()
            declared = function(symbolic, *args, **kwargs)
            if isinstance(declared, (SequenceSpec, FsmSpec)):
                if mode is not ConditionMode.ENTER:
                    raise ValueError(
                        "condition mode applies only to expression xtrigger; "
                        "Sequence/FSM already emit discrete terminal events"
                    )
                program: XExpr | SequenceSpec | FsmSpec = declared
            else:
                program = as_expr(declared)
            return CompiledTrigger(
                name=function.__name__,
                dut=dut,
                program=program,
                sample=None if sample is None else _bind_phase(sample, dut),
                mode=mode,
            )

        return cast(F, factory)

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
