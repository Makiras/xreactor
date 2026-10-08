"""Type-checkable API proposal; api.pyi has no runtime implementation."""

from dataclasses import dataclass

from xreactor import RisingEdge
from xreactor.ir import Sequence, SequenceSpec, Wait, Within, XExpr
from xreactor.triggers import CompiledTrigger, ConditionMode

from api import (
    Bin, BoolSignal, PatternBin, SignalCoverGroup, TemporalCoverPoint,
    TriggerPattern, UIntSignal, covergroup, xtrigger,
)


@dataclass(frozen=True)
class RequestPins:
    valid: BoolSignal
    ready: BoolSignal
    opcode: UIntSignal


@dataclass(frozen=True)
class ResponsePins:
    valid: BoolSignal
    ready: BoolSignal


@dataclass(frozen=True)
class ProtocolPins:
    clock: BoolSignal
    request: RequestPins
    response: ResponsePins


@xtrigger(mode=ConditionMode.EACH_SAMPLE)
def read_accepted(pins: ProtocolPins) -> XExpr:
    return (
        pins.request.valid & pins.request.ready
        & (pins.request.opcode == 0)
    )


@xtrigger()
def roundtrip(pins: ProtocolPins, *, maximum: int = 4) -> SequenceSpec:
    # Only valid when there is at most one outstanding request.
    return Sequence(
        Wait(pins.request.valid & pins.request.ready),
        Within(1, maximum, pins.response.valid & pins.response.ready),
    )


class RequestPoint(TemporalCoverPoint[ProtocolPins]):
    read = read_accepted


class RoundTripPoint(TemporalCoverPoint[ProtocolPins]):
    # Common annotation lets a subclass replace a direct definition with a rule.
    within_four_cycles: PatternBin[ProtocolPins] = roundtrip
    repeated = Bin.pattern(roundtrip, at_least=10)


class ExtendedRoundTripPoint(RoundTripPoint):
    within_four_cycles: PatternBin[ProtocolPins] = Bin.pattern(roundtrip, at_least=2)
    within_eight_cycles = roundtrip.with_args(maximum=8)


@covergroup(schema_id="protocol.patterns")
class ProtocolCoverage(SignalCoverGroup[ProtocolPins]):
    request = RequestPoint()
    roundtrip = RoundTripPoint()


class ExtendedProtocolCoverage(ProtocolCoverage):
    roundtrip = ExtendedRoundTripPoint()


def bind_and_read(pins: ProtocolPins, coverage: ProtocolCoverage) -> int:
    coverage.bind(pins=pins, sample=RisingEdge(pins.clock), strategy="native")
    return coverage.roundtrip.count(RoundTripPoint.within_four_cycles)


def bind_specialization(pins: ProtocolPins) -> CompiledTrigger:
    pattern: TriggerPattern[ProtocolPins] = roundtrip.with_args(maximum=8)
    return pattern.bind(pins, sample=RisingEdge(pins.clock))


async def wait_for_completion(pins: ProtocolPins) -> None:
    # Resolves the Execution default sample, just like the existing trigger path.
    await roundtrip(pins, maximum=4)
