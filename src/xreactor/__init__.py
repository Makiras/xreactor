from .backend import (
    BackendCapabilities,
    BackendHandle,
    BackendHit,
    MemoryBackend,
    RunLimit,
    RunResult,
    StopReason,
    SimulationBackend,
    XCommClockBackend,
)
from .decorators import pytrigger, xtrigger
from .components import Driver, Monitor
from .coverage import (
    Bin,
    BinKind,
    BinSpec,
    CoverageDatabase,
    CoverageMergeError,
    CoverageSample,
    CoverageSchemaError,
    CoverGroup,
    CoverGroupDef,
    CoverPointDef,
    CrossDef,
    Iff,
    IllegalBinError,
    IllegalHit,
    IllegalPolicy,
    OverlapPolicy,
)
from .data import (
    Bundle,
    BundleValue,
    Field,
    PackedArray,
    PackedLayout,
    PackedView,
    split_packed,
)
from .drivers import ReadyValidDriver
from .combinators import AllOf, AnyOf
from .events import (
    ConditionEvent,
    EdgeEvent,
    FsmEvent,
    LogicValue,
    PhaseEvent,
    XEvent,
    XEventKind,
    XPhase,
)
from .ir import (
    FSM,
    FsmSpec,
    Hold,
    Sequence,
    SequenceSpec,
    State,
    Wait,
    Within,
    XExpr,
)
from .external import AsyncioEventTrigger, QueueTrigger, TaskComplete, WallTimeout
from .interfaces import Decoupled, Interface, ReadyValid, Role, Transfer
from .monitors import MonitorOverflowError, ReadyValidMonitor
from .reactor import (
    Registration,
    Subscription,
    SubscriptionOverflowError,
    XReactor,
)
from .subscriptions import (
    BoundSubscriptionSpec,
    XSubscriptionSpec,
    on,
)
from .execution import Execution
from .protocols import drive_ready_valid
from .signals import as_xdata
from .triggers import (
    ClockCycles,
    CompiledTrigger,
    ConditionMode,
    DriveStable,
    FallingEdge,
    PhaseTrigger,
    PythonPredicateTrigger,
    RisingEdge,
    SimTimeout,
    Value,
    ValueChange,
    XTrigger,
)

__all__ = [
    "BackendHandle",
    "BackendCapabilities",
    "BackendHit",
    "Bundle",
    "BundleValue",
    "Bin",
    "BinKind",
    "BinSpec",
    "BoundSubscriptionSpec",
    "AllOf",
    "AnyOf",
    "AsyncioEventTrigger",
    "ClockCycles",
    "CompiledTrigger",
    "ConditionMode",
    "ConditionEvent",
    "CoverageDatabase",
    "CoverageMergeError",
    "CoverageSample",
    "CoverageSchemaError",
    "build_unified_coverage_model",
    "CoverGroup",
    "CoverGroupDef",
    "CoverPointDef",
    "CrossDef",
    "Decoupled",
    "DriveStable",
    "Driver",
    "EdgeEvent",
    "FallingEdge",
    "Field",
    "FSM",
    "FsmSpec",
    "FsmEvent",
    "generate_unified_coverage_report",
    "generate_unified_coverage_site",
    "Hold",
    "LogicValue",
    "Interface",
    "Iff",
    "IllegalBinError",
    "IllegalHit",
    "IllegalPolicy",
    "MemoryBackend",
    "MonitorOverflowError",
    "Monitor",
    "OverlapPolicy",
    "PackedArray",
    "PackedLayout",
    "PackedView",
    "parse_lcov",
    "PhaseEvent",
    "PhaseTrigger",
    "PythonPredicateTrigger",
    "QueueTrigger",
    "Registration",
    "render_unified_coverage_html",
    "ReadyValid",
    "ReadyValidDriver",
    "ReadyValidMonitor",
    "RisingEdge",
    "RunLimit",
    "RunResult",
    "Role",
    "StopReason",
    "Sequence",
    "SequenceSpec",
    "Execution",
    "SimulationBackend",
    "SimTimeout",
    "State",
    "Subscription",
    "SubscriptionOverflowError",
    "TaskComplete",
    "Transfer",
    "Value",
    "ValueChange",
    "WallTimeout",
    "Wait",
    "Within",
    "XEvent",
    "XEventKind",
    "XExpr",
    "XPhase",
    "XReactor",
    "XCommClockBackend",
    "XTrigger",
    "XSubscriptionSpec",
    "on",
    "as_xdata",
    "pytrigger",
    "split_packed",
    "xtrigger",
    "drive_ready_valid",
]


_LAZY_REPORT_EXPORTS = {
    "build_unified_coverage_model",
    "generate_unified_coverage_report",
    "generate_unified_coverage_site",
    "parse_lcov",
    "render_unified_coverage_html",
}


def __getattr__(name: str):
    if name in _LAZY_REPORT_EXPORTS:
        from . import coverage_report

        return getattr(coverage_report, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
