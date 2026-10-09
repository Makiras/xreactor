from __future__ import annotations

import asyncio

import pytest

from xreactor import (
    ClockCycles, ConditionMode, Execution, FallingEdge, RisingEdge, Sequence,
    Wait, Within, xtrigger, CoverGroup as CoreGroup, CoverGroupDef,
    CoverPointDef, Iff, CrossDef,
)
from xreactor.coverage import PatternMatcher, BinSpec
from xreactor.declarative import (
    Bin, DefinitionError, SignalCoverGroup, TemporalCoverPoint, covergroup,
)
from xreactor.ir import signal_expr, program_to_dict
from examples.coverage.declarative_protocol import ProtocolBundle, ToyResponder
from examples.coverage.trigger_bins import ProtocolCoverage, Completions, checked_tag_one, roundtrip, run

MODES = [("memory", "python"), ("xcomm", "python"), ("xcomm", "native")]


def point(report, name):
    return next(p for p in report["points"] if p["name"] == name)


@pytest.mark.parametrize("engine,strategy", MODES)
def test_full_programs_run_independently(engine, strategy):
    report = asyncio.run(run(engine=engine, strategy=strategy))
    assert report["samples"] == 12
    assert point(report, "requests")["counts"] == {"handshake": 3}
    assert point(report, "completions")["counts"] == {
        "tag_one": 1, "tag_one_fast": 0, "tag_two_ready": 1, "correct_data": 1, "bad_data": 0,
    }
    assert report["sampling_backend"] == strategy
    restored = CoreGroup.from_report(report)
    assert restored.definition.to_dict()["version"] == 3
    assert restored.report()["points"] == report["points"]


@pytest.mark.parametrize("engine,strategy", MODES)
def test_unselected_fsm_terminal_still_ends_attempt(engine, strategy):
    report = asyncio.run(run(engine=engine, strategy=strategy, wrong=(1,)))
    counts = point(report, "completions")["counts"]
    assert counts["bad_data"] == 1 and counts["correct_data"] == 0
    assert counts["tag_one"] == 1  # Illegal bin cannot suppress another program.
    assert len(report["illegal_hits"]) == 1


@xtrigger(sample=RisingEdge("clock"))
def delayed(pins: ProtocolBundle):
    return Sequence(Wait(signal_expr(pins.request.valid)), Within(1, 5, signal_expr(pins.response.valid)))


@xtrigger(sample=RisingEdge("clock"), mode=ConditionMode.EACH_SAMPLE)
def level(pins: ProtocolBundle):
    return signal_expr(pins.request.valid)


@xtrigger(sample=RisingEdge("clock"), mode=ConditionMode.CHANGE)
def change(pins: ProtocolBundle):
    return signal_expr(pins.request.valid)


@xtrigger(sample=RisingEdge("clock"))
def enter(pins: ProtocolBundle):
    return signal_expr(pins.request.valid)


class Events(TemporalCoverPoint[ProtocolBundle]):
    many = Bin.pattern(delayed, overlap=True, max_active=4)
    single = delayed
    high = level
    changed = change
    rising = enter


@covergroup(contract="test.trigger-bins/v1")
class EventCoverage(SignalCoverGroup[ProtocolBundle]):
    first = Events()
    second = Events()  # Same declarations, separate execution state and counters.


async def manual_run(engine, strategy, rows, *, group_type=EventCoverage, abort=False, reset_at=None, groups=None):
    toy = ToyResponder(engine=engine)
    if toy.native:
        toy.clock.RemoveStepRisCbByDesc("_evaluate_native")
    else:
        toy.backend.on_phase = None
    # Avoid the DUT substituting a response; the rows are the observed waveforms.
    group = group_type(instance="test")
    if groups is not None:
        groups.append(group)
    group.bind(pins=toy.pins, sample=RisingEdge(toy.clock), strategy=strategy,
               abort=toy.pins.response.ready if abort else None)
    try:
        async with Execution(toy.backend, coverage=[group.runtime]):
            for index, row in enumerate(rows):
                if index == reset_at:
                    group.runtime.clear_history()
                toy.pins.request.valid.Set(row[0])
                toy.pins.response.valid.Set(row[1])
                toy.pins.response.ready.Set(row[2] if len(row) > 2 else 0)
                await ClockCycles(toy.clock, 1)
            report = group.report()
            progress = group.runtime.inspect()
        assert toy.backend.watcher_count == 0
        return report, progress
    finally:
        toy.close()


@pytest.mark.parametrize("engine,strategy", MODES)
def test_overlapping_completion_count_and_expression_modes(engine, strategy):
    report, progress = asyncio.run(manual_run(engine, strategy, [(1, 0), (1, 0), (1, 0), (0, 1), (0, 0)]))
    expected = {"many": 3, "single": 1, "high": 3, "changed": 2, "rising": 1}
    assert point(report, "first")["counts"] == point(report, "second")["counts"] == expected
    assert progress["bins"] == {}


@pytest.mark.parametrize("engine,strategy", MODES)
@pytest.mark.parametrize("reset", [False, True])
def test_abort_and_clear_discard_pending_attempts(engine, strategy, reset):
    rows = [(1, 0, 0), (0, 0, int(not reset)), (0, 1, 0)]
    report, _ = asyncio.run(manual_run(engine, strategy, rows, abort=not reset, reset_at=1 if reset else None))
    assert point(report, "first")["counts"]["many"] == 0
    assert point(report, "first")["counts"]["single"] == 0


def test_definition_checks_and_frozen_specialization():
    assert program_to_dict(roundtrip.with_args(tag=2, maximum=3).program) != program_to_dict(roundtrip.program)
    toy = ToyResponder(engine="memory")
    try:
        fixed = roundtrip.with_args(tag=2, maximum=3)
        assert fixed(toy.pins).program is fixed.program
        with pytest.raises(ValueError, match="phase conflicts"):
            fixed.bind(toy.pins, sample=FallingEdge(toy.clock))
        group = ProtocolCoverage(instance="test")
        with pytest.raises(TypeError, match="Execution"):
            group.sample(toy.pins)
        with pytest.raises(DefinitionError, match="E_CAPACITY"):
            Bin.pattern(roundtrip, overlap=True)
        with pytest.raises(DefinitionError, match="E_TERMINAL"):
            Bin.pattern(checked_tag_one)
        with pytest.raises(TypeError, match="immutable"):
            roundtrip.with_args(tag=[1])
    finally:
        toy.close()


def test_no_cross_between_pattern_points():
    schema = ProtocolCoverage.compile().schema
    with pytest.raises(ValueError, match="pattern"):
        CoverGroupDef("bad", schema.points, (CrossDef("cross", ("requests", "completions")),))


@pytest.mark.parametrize("engine,strategy", MODES)
def test_point_gate_clears_patterns_and_expression_history(engine, strategy):
    toy = ToyResponder(engine=engine)
    if toy.native:
        toy.clock.RemoveStepRisCbByDesc("_evaluate_native")
    else:
        toy.backend.on_phase = None
    bins = {"path": BinSpec(PatternMatcher(delayed.program)),
            "edge": BinSpec(PatternMatcher(enter.program))}
    group = CoverGroupDef("gate", (CoverPointDef("events", bins, iff=Iff("gate", (1,))),)).instantiate("test")
    group.bind(trigger=RisingEdge(toy.clock), root=toy.pins, strategy=strategy,
               fields={"gate": toy.pins.request.ready, "request.valid": toy.pins.request.valid,
                       "response.valid": toy.pins.response.valid}, diagnostics="summary")
    try:
        async def execute():
            async with Execution(toy.backend, coverage=[group]):
                for request, response, gate in [(1, 0, 1), (1, 0, 0), (1, 1, 1), (0, 1, 1)]:
                    toy.pins.request.valid.Set(request)
                    toy.pins.response.valid.Set(response)
                    toy.pins.request.ready.Set(gate)
                    await ClockCycles(toy.clock, 1)
        asyncio.run(execute())
        report = group.report()
        assert point(report, "events")["counts"] == {"path": 1, "edge": 2}
        assert point(report, "events")["gated"] == 1
        path = next(p for p in report["diagnostics"]["patterns"] if p["bin"] == "path")
        assert path["cleared"] == path["completed"] == 1
    finally:
        toy.close()


class SmallCapacity(TemporalCoverPoint[ProtocolBundle]):
    path = Bin.pattern(delayed, overlap=True, max_active=1)


@covergroup(contract="test.small-capacity/v1")
class SmallCapacityGroup(SignalCoverGroup[ProtocolBundle]):
    events = SmallCapacity()


@pytest.mark.parametrize("engine,strategy", MODES)
def test_bin_capacity_failure_marks_collection_incomplete_and_cleans_up(engine, strategy):
    groups = []
    with pytest.raises((RuntimeError, OverflowError), match="capacity"):
        asyncio.run(manual_run(engine, strategy, [(1, 0), (1, 0)],
                               group_type=SmallCapacityGroup, groups=groups))
    assert groups[0].report()["collection_complete"] is False
    assert groups[0].runtime._collector is None


@pytest.mark.parametrize("engine,strategy", MODES)
def test_cancelled_ordinary_wait_does_not_reset_coverage_pattern(engine, strategy):
    toy = ToyResponder(engine=engine)
    if toy.native:
        toy.clock.RemoveStepRisCbByDesc("_evaluate_native")
    else:
        toy.backend.on_phase = None
    group = EventCoverage(instance="test").bind(pins=toy.pins, sample=RisingEdge(toy.clock), strategy=strategy)
    try:
        async def execute():
            async with Execution(toy.backend, coverage=[group.runtime]):
                async def waiter():
                    await delayed(toy.pins)
                task = asyncio.create_task(waiter())
                toy.pins.request.valid.Set(1)
                await ClockCycles(toy.clock, 1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                toy.pins.request.valid.Set(0)
                toy.pins.response.valid.Set(1)
                await ClockCycles(toy.clock, 1)
        asyncio.run(execute())
        assert group.first.count(Events.many) == group.first.count(Events.single) == 1
        assert toy.backend.watcher_count == 0
    finally:
        toy.close()


@pytest.mark.parametrize("strategy", ["auto", "native"])
def test_old_native_abi_fallback_is_explicit(monkeypatch, strategy):
    toy = ToyResponder(engine="xcomm")
    monkeypatch.setattr(toy.backend._engine, "CoverageVersion", lambda: 3)
    group = ProtocolCoverage(instance="test").bind(pins=toy.pins, sample=RisingEdge(toy.clock), strategy=strategy)
    try:
        async def execute():
            async with Execution(toy.backend, coverage=[group.runtime]):
                await ClockCycles(toy.clock, 1)
        if strategy == "native":
            with pytest.raises(NotImplementedError, match="version 4"):
                asyncio.run(execute())
        else:
            asyncio.run(execute())
            report = group.report()
            assert report["sampling_backend"] == "python"
            assert "version 4" in report["sampling_fallback"]
        assert toy.backend.watcher_count == 0
    finally:
        toy.close()


def test_native_bins_count_without_python_sampling_or_per_hit_wakeups(monkeypatch):
    toy = ToyResponder(engine="xcomm")
    toy.clock.RemoveStepRisCbByDesc("_evaluate_native")
    toy.pins.request.valid.Set(1)
    group = EventCoverage(instance="test").bind(pins=toy.pins, sample=RisingEdge(toy.clock), strategy="native")
    calls = []
    original = toy.backend.run_until
    def run_until(limit):
        calls.append(limit)
        return original(limit)
    def forbidden(*args, **kwargs):
        raise AssertionError("native coverage called the Python sample path")
    monkeypatch.setattr(toy.backend, "run_until", run_until)
    monkeypatch.setattr(group.runtime, "_sample", forbidden)
    try:
        async def execute():
            async with Execution(toy.backend, coverage=[group.runtime]):
                # Four pending attempts fit the declared capacity; no completions needed.
                await ClockCycles(toy.clock, 4)
        asyncio.run(execute())
        assert group.first.count(Events.high) == 4
        assert len(calls) == 1
    finally:
        toy.close()


def test_schema_and_contract_include_bin_parameters():
    class Longer(Completions):
        tag_one_fast = Bin.pattern(roundtrip.with_args(maximum=3))
    class Changed(ProtocolCoverage):
        completions = Longer()
    assert Changed.compile().schema.digest != ProtocolCoverage.compile().schema.digest
    assert Changed.compile().diff(ProtocolCoverage.compile())
    assert "WithinStep" in ProtocolCoverage.compile().explain()


@xtrigger(mode=ConditionMode.EACH_SAMPLE)
def always(pins: ProtocolBundle) -> bool:
    return True


class ConstantEvents(TemporalCoverPoint[ProtocolBundle]):
    every_sample = always


@covergroup(contract="test.constant-program/v1")
class ConstantCoverage(SignalCoverGroup[ProtocolBundle]):
    events = ConstantEvents()


@pytest.mark.parametrize("engine,strategy", MODES)
def test_constant_program_requires_no_dummy_signal(engine, strategy):
    toy = ToyResponder(engine=engine)
    coverage = ConstantCoverage(instance="test").bind(pins=toy.pins, sample=RisingEdge(toy.clock), strategy=strategy)
    try:
        async def execute():
            async with Execution(toy.backend, coverage=[coverage.runtime]):
                await ClockCycles(toy.clock, 2)
        asyncio.run(execute())
        assert coverage.events.count(ConstantEvents.every_sample) == 2
        assert coverage.runtime._binding["fields"] == {}
    finally:
        toy.close()
