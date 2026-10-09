from typing import assert_type

from xreactor import RisingEdge, TriggerDefinition
from xreactor.declarative import Bin, BinRule, BoundPoint, PatternBin
from xreactor.triggers import CompiledTrigger
from examples.coverage.declarative_protocol import ProtocolBundle
from examples.coverage.trigger_bins import (
    Completions, ProtocolCoverage, accepted, roundtrip,
)

coverage = ProtocolCoverage(instance="typing.protocol")
assert_type(coverage.completions, BoundPoint[ProtocolBundle])
assert_type(Completions.tag_one_fast, BinRule[ProtocolBundle])


def observe(pins: ProtocolBundle) -> int:
    assert_type(accepted(pins), CompiledTrigger)
    assert_type(roundtrip(pins, maximum=3), CompiledTrigger)
    fixed: TriggerDefinition[ProtocolBundle, ...] = roundtrip.with_args(maximum=3)
    assert_type(fixed.bind(pins), CompiledTrigger)
    rule: PatternBin[ProtocolBundle] = Bin.pattern(fixed, at_least=2)
    _ = rule
    coverage.bind(pins=pins, sample=RisingEdge(pins.clock))
    return coverage.completions.count(Completions.tag_one)
