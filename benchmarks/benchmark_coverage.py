"""Measure transaction-level functional-coverage sampling overhead."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gc
import json
import platform
import statistics
import time
from typing import Callable

from xreactor import Bin, CoverGroupDef, CoverPointDef, CrossDef


@dataclass(frozen=True, slots=True)
class Transaction:
    target: str
    alignment: str
    response: str
    commands: int
    command_bp: bool
    response_bp: bool


SCHEMA = CoverGroupDef(
    "coverage_benchmark",
    (
        CoverPointDef("target", {"itcm": Bin.values("itcm"), "biu": Bin.values("biu")}),
        CoverPointDef(
            "alignment",
            {name: Bin.values(name) for name in ("begin", "middle", "cross")},
        ),
        CoverPointDef("response", {"ok": Bin.values("ok"), "error": Bin.values("error")}),
        CoverPointDef(
            "commands",
            {"zero": Bin.values(0), "one": Bin.values(1), "two": Bin.values(2)},
        ),
        CoverPointDef("command_bp", {"no": Bin.values(False), "yes": Bin.values(True)}),
        CoverPointDef("response_bp", {"no": Bin.values(False), "yes": Bin.values(True)}),
    ),
    (
        CrossDef("target_x_alignment", ("target", "alignment")),
        CrossDef("target_x_response", ("target", "response")),
        CrossDef("backpressure", ("command_bp", "response_bp")),
    ),
)

TRANSACTIONS = tuple(
    Transaction(
        "itcm" if index & 1 else "biu",
        ("begin", "middle", "cross")[index % 3],
        "error" if index % 17 == 0 else "ok",
        index % 3,
        bool(index & 2),
        bool(index & 4),
    )
    for index in range(256)
)


def _baseline(iterations: int) -> int:
    checksum = 0
    for index in range(iterations):
        item = TRANSACTIONS[index & 255]
        checksum += item.commands + item.command_bp + item.response_bp
    return checksum


def _coverage(iterations: int, *, details: bool) -> int:
    group = SCHEMA.instantiate("bench")
    for index in range(iterations):
        group.sample(TRANSACTIONS[index & 255], details=details)
    return group.samples


def _measure(operation: Callable[[int], int], iterations: int, repeats: int) -> dict:
    samples: list[int] = []
    operation(min(iterations, 2_000))
    for _ in range(repeats):
        gc.collect()
        gc.disable()
        try:
            started = time.perf_counter_ns()
            result = operation(iterations)
            elapsed = time.perf_counter_ns() - started
        finally:
            gc.enable()
        if result <= 0:
            raise RuntimeError("benchmark operation produced no observable result")
        samples.append(elapsed)
    median = statistics.median(samples)
    return {
        "median_ns": median,
        "ns_per_transaction": median / iterations,
        "transactions_per_second": iterations * 1_000_000_000 / median,
        "samples_ns": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--max-fast-ns",
        type=float,
        help="optional CI failure threshold for details=False",
    )
    args = parser.parse_args()
    if args.iterations <= 0 or args.repeats <= 0:
        parser.error("iterations and repeats must be positive")

    results = {
        "transaction_access_baseline": _measure(_baseline, args.iterations, args.repeats),
        "coverage_fast": _measure(
            lambda count: _coverage(count, details=False), args.iterations, args.repeats
        ),
        "coverage_with_details": _measure(
            lambda count: _coverage(count, details=True), args.iterations, args.repeats
        ),
    }
    baseline = results["transaction_access_baseline"]["ns_per_transaction"]
    for name in ("coverage_fast", "coverage_with_details"):
        results[name]["incremental_ns"] = results[name]["ns_per_transaction"] - baseline
    report = {
        "schema": 1,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "iterations": args.iterations,
        "repeats": args.repeats,
        "coverpoints": len(SCHEMA.points),
        "crosses": len(SCHEMA.crosses),
        "results": results,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"iterations={args.iterations} repeats={args.repeats} "
            f"points={len(SCHEMA.points)} crosses={len(SCHEMA.crosses)}"
        )
        for name, result in results.items():
            print(
                f"{name:30s} {result['ns_per_transaction']:10.1f} ns/transaction "
                f"{result['transactions_per_second']:12,.0f} transactions/s"
            )
    fast_ns = results["coverage_fast"]["ns_per_transaction"]
    if args.max_fast_ns is not None and fast_ns > args.max_fast_ns:
        print(
            f"coverage_fast {fast_ns:.1f} ns exceeds --max-fast-ns "
            f"{args.max_fast_ns:.1f}"
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
