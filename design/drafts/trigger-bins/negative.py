"""Each EXPECT_ERROR line must be rejected by the draft's type checker."""

from dataclasses import dataclass

from xreactor import RisingEdge
from xreactor.ir import SequenceSpec, XExpr
from xreactor.triggers import CompiledTrigger

from api import Bin, BoolSignal, xtrigger
from example import ProtocolCoverage, ProtocolPins, roundtrip


@dataclass(frozen=True)
class OtherPins:
    clock: BoolSignal
    ready: BoolSignal


@xtrigger()
def other_ready(pins: OtherPins) -> XExpr:
    return pins.ready


def invalid(pins: ProtocolPins, other: OtherPins, coverage: ProtocolCoverage) -> None:
    roundtrip.with_args(maximum="8")  # EXPECT_ERROR
    roundtrip.with_args(maxmum=8)  # EXPECT_ERROR
    roundtrip.with_args(8)  # EXPECT_ERROR
    roundtrip.with_args(maximum=8).bind(other)  # EXPECT_ERROR
    coverage.bind(pins=other, sample=RisingEdge(other.clock))  # EXPECT_ERROR
    coverage.roundtrip.count(other_ready)  # EXPECT_ERROR
    coverage.roundtrip.count(Bin.pattern(other_ready))  # EXPECT_ERROR
    coverage.roundtrip.count("within_four_cycles")  # EXPECT_ERROR
    Bin.pattern(roundtrip, at_least="10")  # EXPECT_ERROR
    roundtrip(pins, maximum="8")  # EXPECT_ERROR
    declared: SequenceSpec = roundtrip(pins)  # EXPECT_ERROR
    bound: CompiledTrigger = roundtrip  # EXPECT_ERROR
    # Avoid unrelated unused-local diagnostics in this negative fixture.
    _ = declared, bound
