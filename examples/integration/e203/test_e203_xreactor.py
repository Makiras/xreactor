from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from e203_xreactor_env import (
    E203Harness,
    FetchRequest,
    convert_line_coverage,
    load_generated_dut,
    run_campaign,
    write_artifacts,
)
from xreactor import (
    Execution,
    XCommClockBackend,
    generate_unified_coverage_report,
    generate_unified_coverage_site,
)


REPOSITORY = Path(__file__).resolve().parents[4]


@pytest.mark.asyncio
async def test_e203_reference_stress_and_coverage() -> None:
    generated = Path(
        os.environ.get("E203_DUT_DIR", REPOSITORY / "output" / "xreactor_e203")
    ).resolve()
    artifacts = Path(
        os.environ.get(
            "E203_ARTIFACT_DIR",
            REPOSITORY / "output" / "e203-verification",
        )
    ).resolve()
    seed = int(os.environ.get("E203_SEED", "0xE203"), 0)
    random_count = int(os.environ.get("E203_RANDOM_COUNT", "500"), 0)
    minimum_tps = float(os.environ.get("E203_MIN_TRANSACTIONS_PER_SECOND", "0"))
    timeout = float(os.environ.get("E203_WALL_TIMEOUT", "60"))
    if random_count < 0:
        raise ValueError("E203_RANDOM_COUNT must not be negative")

    coverage_dat = artifacts / "verilator-coverage.dat"
    DUT = load_generated_dut(generated)
    dut = DUT(coverage_filename=str(coverage_dat))
    harness = None
    summary = None
    try:
        async with asyncio.timeout(timeout):
            harness, summary = await run_campaign(
                dut,
                seed=seed,
                random_count=random_count,
            )
        paths = write_artifacts(harness, summary, artifacts)
    finally:
        # Verilator writes its code-coverage database during Finish().
        dut.Finish()

    assert harness is not None and summary is not None
    assert summary["transactions"] == 10 + random_count
    assert summary["commands"] > 0
    assert summary["half_ticks"] > summary["transactions"]
    assert summary["transactions_per_second"] >= minimum_tps
    harness.coverage.assert_coverage(100.0)

    functional = json.loads(paths["functional_coverage"].read_text(encoding="utf-8"))
    assert functional["coverage"] == pytest.approx(100.0)
    functional_group = functional["groups"][0]
    assert functional_group["covered"] is True
    assert all(item["coverage"] == pytest.approx(100.0) for item in functional_group["points"])
    assert all(item["coverage"] == pytest.approx(100.0) for item in functional_group["crosses"])

    line_info, line_summary = convert_line_coverage(coverage_dat, artifacts)
    assert line_info.is_file()
    assert line_summary["lines_found"] > 0
    assert line_summary["lines_hit"] > 0
    assert 0.0 < line_summary["line_coverage"] <= 100.0
    report = generate_unified_coverage_report(
        functional_paths=[paths["functional_coverage"]],
        line_coverage=[("Verilator", line_info)],
        output=artifacts / "coverage-report.html",
        title="e203 IFU-to-ICB Coverage",
    )
    assert report.is_file()
    assert report.stat().st_size > 10_000
    site = generate_unified_coverage_site(
        functional_paths=[paths["functional_coverage"]],
        line_coverage=[("Verilator", line_info)],
        output_dir=artifacts / "coverage-report",
        title="e203 IFU-to-ICB Coverage",
    )
    assert site.is_file()
    source_pages = list((artifacts / "coverage-report" / "line").rglob("*.gcov.html"))
    assert source_pages
    assert any("e203_ifu_ift2icb.v" in path.name for path in source_pages)
    target_page = next(
        path for path in source_pages if "e203_ifu_ift2icb.v" in path.name
    )
    assert "Unified coverage overview" in target_page.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_e203_missing_response_times_out() -> None:
    """A permanently delayed ICB response must fail with execution context."""

    generated = Path(
        os.environ.get("E203_DUT_DIR", REPOSITORY / "output" / "xreactor_e203")
    ).resolve()
    artifacts = Path(
        os.environ.get(
            "E203_ARTIFACT_DIR",
            REPOSITORY / "output" / "e203-verification",
        )
    ).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    DUT = load_generated_dut(generated)
    dut = DUT(coverage_filename=str(artifacts / "timeout-coverage.dat"))
    dut.InitClock("clk")
    harness = E203Harness(dut, seed=0xBAD)
    harness.initialize_inputs()
    backend = XCommClockBackend(dut.GetXClock())
    try:
        async with Execution(backend, max_batch_ticks=128, quantum_ms=5.0):
            await harness.reset()
            with pytest.raises(TimeoutError, match=r"timed out after 5 cycles"):
                await harness.fetch(
                    FetchRequest(0x0001_0020, response_delay=1_000),
                    timeout_cycles=5,
                )
    finally:
        dut.Finish()
