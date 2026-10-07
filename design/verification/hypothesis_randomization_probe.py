"""Optional-library research probes, outside the framework's default test suite.

Run with Hypothesis, constrainedrandom, pytest and pytest-asyncio installed:
    PYTHONPATH=src:. python -m pytest -q design/verification/hypothesis_randomization_probe.py

Set XREACTOR_HYPOTHESIS_RESULT to save the case evidence as JSON.
The corrupt-DUT experiment expects detection and checks the reduced reproducer.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import asdict, dataclass
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import sys

from constrainedrandom import RandObj
from constrainedrandom.utils import RandomizationError
from hypothesis import event, given, seed, settings, strategies as st, target
from hypothesis.errors import HypothesisException, NonInteractiveExampleWarning
from hypothesis.stateful import Bundle, RuleBasedStateMachine, consumes, invariant, precondition, rule, run_state_machine_as_test
import pytest

from xreactor import Bin, ClockCycles, CoverGroupDef, CoverPointDef, Execution, ScoreboardMismatch


# A research dependency installs a top-level examples package. Load the existing
# repository sample explicitly, without changing global package resolution.
_sample_path = Path(__file__).resolve().parents[2] / "examples/transactions/reference_model.py"
_sample_spec = importlib.util.spec_from_file_location("xreactor_research_accumulator", _sample_path)
_sample = importlib.util.module_from_spec(_sample_spec)
sys.modules[_sample_spec.name] = _sample
_sample_spec.loader.exec_module(_sample)
AccumulatorAgent, AccumulatorDut = _sample.AccumulatorAgent, _sample.AccumulatorDut
AccumulatorModel, Command = _sample.AccumulatorModel, _sample.Command


@dataclass(frozen=True)
class MemoryRequest:
    op: str
    addr: int
    beats: int
    data: int


class HistoryFaultDut(AccumulatorDut):
    """Inject a tag-2 response error only after two earlier accepted inputs."""

    def sample(self, phase, tick):
        self.corrupt = len(self.operands) >= 2
        super().sample(phase, tick)


EVIDENCE = {}
CASE_NAMES = {"composite", "stateful", "async_online", "sync_executor", "async_shrink", "example_guard", "constrainedrandom"}
DETERMINISTIC = settings(max_examples=40, deadline=None, database=None, derandomize=True)
ONLINE_SETTINGS = (
    settings(deadline=None, derandomize=False)
    if os.environ.get("XREACTOR_HYPOFUZZ_PROBE") == "1" else DETERMINISTIC
)


@pytest.fixture(scope="session", autouse=True)
def save_case_evidence():
    yield
    output = os.environ.get("XREACTOR_HYPOTHESIS_RESULT")
    if output:
        record = {
            "date": "2026-10-01", "backend": "MemoryBackend",
            "case_evidence_complete": set(EVIDENCE) == CASE_NAMES,
            "python": platform.python_version(),
            "versions": {name: importlib.metadata.version(name) for name in
                         ("hypothesis", "constrainedrandom", "pytest", "pytest-asyncio")},
            "cases": EVIDENCE,
        }
        Path(output).write_text(json.dumps(record, indent=2) + "\n")


@st.composite
def burst_requests(draw):
    beats = draw(st.sampled_from((1, 2, 4, 8, 16)))
    page = draw(st.integers(0, 15))
    word = draw(st.integers(0, 512 - beats))
    op = draw(st.sampled_from(("read", "write")))
    data = draw(st.integers(0, (1 << 64) - 1)) if op == "write" else 0
    return MemoryRequest(op, 0x10000 + page * 4096 + word * 8, beats, data)


@settings(max_examples=300, deadline=None, database=None, derandomize=True)
@given(burst_requests())
def test_composite_burst_legality(request):
    assert request.addr % 8 == 0
    assert 0x10000 <= request.addr < 0x20000
    assert request.addr % 4096 + request.beats * 8 <= 4096
    assert request.beats in {1, 2, 4, 8, 16}
    assert request.op in {"read", "write"} and 0 <= request.data < 1 << 64
    case = EVIDENCE.setdefault("composite", {"samples": 0})
    case["samples"] += 1


def test_rule_machine_has_bounded_state_dependent_actions():
    """Probe the action grammar and Bundle semantics; this is not an RTL model."""
    counts = Counter()
    totals = {"machines": 0, "max_reserved": 0}

    class Reservations(RuleBasedStateMachine):
        live = Bundle("live")

        def __init__(self):
            super().__init__()
            self.reserved = {}
            self.next_tag = 0
            totals["machines"] += 1

        @precondition(lambda self: len(self.reserved) < 3)
        @rule(target=live, operand=st.integers(0, 255))
        def reserve(self, operand):
            tag = self.next_tag
            self.next_tag += 1
            assert tag not in self.reserved
            self.reserved[tag] = operand
            counts["reserve"] += 1
            return tag

        @rule(tag=consumes(live))
        def complete(self, tag):
            assert tag in self.reserved
            del self.reserved[tag]
            counts["complete"] += 1

        @rule(tag=consumes(live))
        def cancel_pending(self, tag):
            assert tag in self.reserved
            del self.reserved[tag]
            counts["cancel_pending"] += 1

        @invariant()
        def bounded(self):
            assert len(self.reserved) <= 3
            totals["max_reserved"] = max(totals["max_reserved"], len(self.reserved))
            counts["invariant"] += 1

    run_state_machine_as_test(Reservations, settings=settings(
        max_examples=40, stateful_step_count=30,
        deadline=None, database=None, derandomize=True,
    ))
    assert all(counts[name] > 0 for name in ("reserve", "complete", "cancel_pending"))
    EVIDENCE["stateful"] = {**totals, "action_counts": dict(counts), "rtl_executed": False}


async def execute_online(data, steps, *, corrupt=False, traces=None):
    """Draw only in the scenario task; every Hypothesis example owns a fresh DUT."""
    model = AccumulatorModel()
    dut = HistoryFaultDut("memory") if corrupt else AccumulatorDut("memory")
    coverage = CoverGroupDef(
        "checked-responses",
        (CoverPointDef("tag", {str(tag): Bin.values(tag) for tag in (1, 2, 3)}),),
    ).instantiate("research.response", contract="checked-response/v1")
    rows = []
    responses = []
    tasks_before = asyncio.all_tasks()
    try:
        agent = AccumulatorAgent(dut, response_timeout_cycles=5)
        agent.connect(model)
        async with asyncio.timeout(2), Execution(dut.backend, agents=[agent]):
            for index in range(steps):
                before = model.total
                limit = 1 + before % 16
                tag = data.draw(st.sampled_from((1, 3, 2)), label=f"tag-{index}")
                operand = data.draw(st.integers(0, limit), label=f"operand-{index}")
                gap = data.draw(st.integers(0, 2), label=f"gap-{index}")
                assert tag in (1, 2, 3) and 0 <= operand <= limit and 0 <= gap <= 2
                row = {"tag": tag, "operand": operand, "gap_cycles": gap,
                       "model_before": before, "operand_limit": limit}
                rows.append(row)
                if gap:
                    await ClockCycles(dut.clock, gap)
                transfer = agent.submit(Command(tag, operand))
                assert model.total == before
                response = await transfer
                assert response.total == before + operand
                coverage.sample({"tag": response.tag})
                responses.append(asdict(response))
                # Response completion is the feedback point, before the next draw.
                assert model.total == sum(row["operand"] for row in rows)
            await agent.finish(timeout_cycles=30, observe_cycles=1)
        counts = coverage.report()["points"][0]["counts"]
        reached = sorted(name for name, count in counts.items() if count)
        return {"requests": rows, "responses": responses, "total": model.total,
                "reached_response_bins": reached}
    except ScoreboardMismatch:
        if traces is not None:
            traces.append([dict(row) for row in rows])
        raise
    finally:
        dut.close()
        assert asyncio.all_tasks() == tasks_before


@pytest.mark.asyncio
@ONLINE_SETTINGS
@given(data=st.data(), steps=st.integers(1, 12))
async def test_async_online_draws_use_the_updated_model(data, steps):
    result = await execute_online(data, steps)
    # Once per label per example, using a deterministic observation.
    target(result["total"], label="accepted-total")
    for name in result["reached_response_bins"]:
        event(f"functional/v1/response.tag/{name}")
    case = EVIDENCE.setdefault("async_online", {"examples": 0, "checked_requests": 0,
                                               "max_operand_limit": 0})
    case["examples"] += 1
    case["checked_requests"] += len(result["requests"])
    case["max_operand_limit"] = max(case["max_operand_limit"], *(row["operand_limit"] for row in result["requests"]))
    case["data_draw_after_await"] = True
    case["target_called"] = True
    case["functional_events"] = sorted(set(case.get("functional_events", ())) |
                                       {f"functional/v1/response.tag/{name}" for name in result["reached_response_bins"]})


@ONLINE_SETTINGS
@given(data=st.data(), steps=st.integers(1, 12))
def test_sync_executor_for_continuous_fuzzing(data, steps):
    result = asyncio.run(execute_online(data, steps))
    target(result["total"], label="accepted-total")
    for name in result["reached_response_bins"]:
        event(f"functional/v1/response.tag/{name}")
    case = EVIDENCE.setdefault("sync_executor", {"examples": 0, "checked_requests": 0})
    case["examples"] += 1
    case["checked_requests"] += len(result["requests"])


def test_async_execution_is_shrunk_and_explicitly_replayed():
    failures = []

    @seed(20261001)
    @settings(max_examples=100, deadline=None, database=None, report_multiple_bugs=False)
    @given(data=st.data(), steps=st.integers(1, 12))
    def search(data, steps):
        # Synchronous Hypothesis executor owns one fresh loop for each example.
        asyncio.run(execute_online(data, steps, corrupt=True, traces=failures))

    with pytest.raises(ScoreboardMismatch) as caught:
        search()
    reduced = failures[-1]
    assert len(reduced) == 3
    assert [row["tag"] for row in reduced] == [1, 1, 2]
    assert all(row["operand"] == 0 and row["gap_cycles"] == 0 for row in reduced)
    assert caught.value.expected.total == 0 and caught.value.actual.total == 1

    class ExplicitReplay:
        def __init__(self, rows):
            self.values = iter(value for row in rows for value in
                               (row["tag"], row["operand"], row["gap_cycles"]))

        def draw(self, strategy, *, label):
            # Schema/domain compatibility is checked explicitly for this toy trace.
            return next(self.values)

    stored = json.loads(json.dumps(reduced))
    with pytest.raises(ScoreboardMismatch):
        asyncio.run(execute_online(ExplicitReplay(stored), len(stored), corrupt=True))
    corrected = asyncio.run(execute_online(ExplicitReplay(stored), len(stored)))
    assert corrected["total"] == 0
    EVIDENCE["async_shrink"] = {
        "failing_evaluations": len(failures),
        "largest_failing_prefix": max(map(len, failures)),
        "reduced_trace": stored,
        "expected_total": 0, "faulty_total": 1,
        "fault_reproduced": True, "correct_dut_passed": True,
        "failure_type": type(caught.value).__name__,
    }


@settings(max_examples=1, deadline=None, database=None)
@given(st.just(None))
def test_example_is_rejected_inside_given(dummy):
    with pytest.warns(NonInteractiveExampleWarning), pytest.raises(HypothesisException, match="example"):
        st.integers(0, 255).example()
    EVIDENCE["example_guard"] = {"inside_given_rejected": True}


def test_constrainedrandom_dynamic_constraints_and_repeatability():
    def generate():
        randobj = RandObj(random.Random(17), max_iterations=100, max_domain_size=1024)
        randobj.add_rand_var("beats", domain=(1, 2, 4, 8, 16))
        randobj.add_rand_var("word", domain=range(512))
        randobj.add_constraint(lambda word, beats: word + beats <= 512, ("word", "beats"))
        accepted_beats = 0
        result = []
        for _ in range(100):
            limit = 1 + accepted_beats % 16
            randobj.randomize(with_constraints=[(lambda beats: beats <= limit, ("beats",))])
            row = randobj.get_results()
            assert row["word"] + row["beats"] <= 512
            assert row["beats"] <= limit
            accepted_beats += row["beats"]
            result.append(dict(row))
        return result

    first = generate()
    assert first == generate()
    impossible = RandObj(random.Random(17), max_iterations=2)
    impossible.add_rand_var("value", domain=(0, 1))
    impossible.add_constraint(lambda value: value > 2, ("value",))
    with pytest.raises(RandomizationError):
        impossible.randomize()
    EVIDENCE["constrainedrandom"] = {
        "samples_per_run": len(first), "same_seed_repeated": True,
        "temporary_state_constraints": True, "impossible_finite_domain_rejected": True,
        "failure_type": "RandomizationError",
    }
