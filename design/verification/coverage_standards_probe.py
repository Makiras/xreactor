"""Small, reproducible coverage observations for the standards review.

Run from the repository root:
    PYTHONPATH=src python3 design/verification/coverage_standards_probe.py

These probes describe current behavior; they are not a standards certification.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from xreactor import Bin, CoverGroup, CoverGroupDef, CoverPointDef, CrossDef, CoverageMergeError


def exclusion(kind: str) -> dict:
    excluded = Bin.ignore if kind == "ignore" else Bin.illegal
    definition = CoverGroupDef(
        "exclusion",
        (
            CoverPointDef("a", {
                "zero": Bin.values(0),
                "one": Bin.values(1),
                "excluded_one": excluded(Bin.values(1)),
            }),
            CoverPointDef("b", {"zero": Bin.values(0)}),
        ),
        (CrossDef("ab", ("a", "b")),),
    )
    group = definition.instantiate("dut", illegal_policy="record")
    for value in (0, 1):
        group.sample({"a": value, "b": 0})
    return {
        "point_coverage": group.point_coverage("a"),
        "cross_coverage": group.cross_coverage("ab"),
        "uncovered": list(group.uncovered()),
        "expected_after_excluding_empty_bins": {
            "point_coverage": 100.0, "cross_coverage": 100.0,
        },
    }


def goals() -> dict:
    definition = CoverGroupDef(
        "goals",
        (
            CoverPointDef("a", {"zero": Bin.values(0)}, goal=100),
            CoverPointDef("b", {"zero": Bin.values(0)}, goal=100),
        ),
        (CrossDef("ab", ("a", "b"), goal=100),),
        goal=30,
    )
    group = definition.instantiate("dut")
    group.sample({"a": 0, "b": 1})
    try:
        group.assert_coverage()
    except AssertionError as error:
        failure = str(error)
    else:
        failure = None
    report = group.report()
    return {
        "group_coverage": report["coverage"],
        "group_covered": report["covered"],
        "assert_coverage_passed": failure is None,
        "assert_coverage_failure": failure,
        "group_goal_met": report["goal_met"],
        "items_goal_met": report["items_goal_met"],
        "b_coverage": group.point_coverage("b"),
        "b_goal": 100,
        "ab_coverage": group.cross_coverage("ab"),
        "ab_goal": 100,
        "interpretation": "raw group percentage is unchanged; child goals gate default acceptance",
    }


def illegal_status() -> dict:
    group = CoverGroupDef("status", (CoverPointDef("a", {
        "zero": Bin.values(0), "bad": Bin.illegal(Bin.values(1)),
    }),)).instantiate("dut", illegal_policy="record")
    group.sample({"a": 0})
    group.sample({"a": 1})
    try:
        group.assert_coverage()
    except AssertionError as error:
        failure = type(error).__name__
    else:
        failure = None
    return {
        "coverage": group.coverage,
        "covered": group.covered,
        "illegal_hit_count": len(group.illegal_hits),
        "assert_coverage_failure": failure,
    }


def duplicate_snapshot() -> dict:
    group = CoverGroupDef("duplicate", (CoverPointDef("a", {
        "zero": Bin.values(0, at_least=2),
    }),)).instantiate("dut")
    group.sample({"a": 0}, metadata={"run_id": "run-1"})
    snapshot = group.report()
    merged = CoverGroup.from_report(snapshot)
    before = merged.coverage
    try:
        merged.merge(CoverGroup.from_report(snapshot))
    except CoverageMergeError as error:
        failure = str(error)
    else:
        failure = None
    return {
        "one_run_one_hit_coverage": before,
        "same_snapshot_imported_twice_coverage": merged.coverage,
        "count_after_duplicate": merged.report()["points"][0]["counts"]["zero"],
        "duplicate_rejected": failure is not None,
        "merge_failure": failure,
    }


def cross_identity() -> dict:
    group = CoverGroupDef(
        "identity",
        (
            CoverPointDef("a", {"a": Bin.values(0), "a × b": Bin.values(1)}),
            CoverPointDef("b", {"b × c": Bin.values(0), "c": Bin.values(1)}),
        ),
        (CrossDef("ab", ("a", "b")),),
    ).instantiate("dut")
    group.sample({"a": 0, "b": 0})
    cross = group.report()["crosses"][0]
    return {
        "eligible_tuple_count": (
            len(group.definition.points[0].normal_bins)
            * len(group.definition.points[1].normal_bins)
        ),
        "counter_key_count": len(cross["counts"]),
        "coverage_after_one_tuple": cross["coverage"],
        "expected_coverage_after_one_tuple": 25.0,
        "counts": cross["counts"],
    }


def normal_hit_metadata() -> dict:
    definition = CoverGroupDef("provenance", (CoverPointDef("a", {
        "zero": Bin.values(0),
    }),))
    group = definition.instantiate("dut", run_id="run-a", run_metadata={"test": "case-a", "seed": 17})
    group.sample({"a": 0}, metadata={"test": "case-a", "seed": 17, "tick": 42})
    report = group.report()
    return {
        "normal_count": report["points"][0]["counts"]["zero"],
        "normal_bin_provenance_present": "case-a" in json.dumps(report),
        "provenance": report["points"][0]["provenance"],
        "origins": report["origins"],
        "description_changes_schema_digest": (
            definition.digest != replace(definition, description="Comment only").digest
        ),
    }


def controls() -> dict:
    definition = CoverGroupDef(
        "controls",
        (
            CoverPointDef("a", {"zero": Bin.values(0), "one": Bin.values(1)}),
            CoverPointDef("b", {"zero": Bin.values(0), "one": Bin.values(1)}),
        ),
        (CrossDef("ab", ("a", "b")),),
    )
    left, right = definition.instantiate("dut"), definition.instantiate("dut")
    left.sample({"a": 0, "b": 0})
    right.sample({"a": 1, "b": 1})
    left.merge(right)
    report = left.report()
    return {
        "merged_point_coverage": [left.point_coverage("a"), left.point_coverage("b")],
        "merged_cross_coverage": left.cross_coverage("ab"),
        "json_round_trip_preserves_report": (
            CoverGroup.from_report(json.loads(json.dumps(report))).report() == report
        ),
        "interpretation": "cross merge retains observed tuples without inventing combinations",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    print(json.dumps({
        "baseline": {
            "date": "2026-09-30",
            "source_sha256": {
                path: sha256((root / path).read_bytes()).hexdigest()
                for path in (
                    "src/xreactor/coverage.py",
                    "src/xreactor/_coverage_exclusions.py",
                    "src/xreactor/_coverage_runtime.py",
                    "src/xreactor/coverage_report.py",
                )
            },
        },
        "ignore_exclusion": exclusion("ignore"),
        "illegal_exclusion": exclusion("illegal"),
        "child_goals": goals(),
        "illegal_status": illegal_status(),
        "duplicate_snapshot": duplicate_snapshot(),
        "cross_identity": cross_identity(),
        "normal_hit_metadata": normal_hit_metadata(),
        "controls": controls(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
