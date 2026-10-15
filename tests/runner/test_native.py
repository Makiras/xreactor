"""Exercise native lifetime and unfiltered merge through a real coverage tool."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from .test_execution import run_cli

TOOL = shutil.which("verilator_coverage")
pytestmark = pytest.mark.skipif(TOOL is None, reason="requires Verilator coverage processor")

NATIVE = r'''
from pathlib import Path
import pytest

class DUT:
    def __init__(self): self.count = 0; self.path = None
    def SetCoverage(self, filename): self.path = Path(filename)
    def GetCovMetrics(self): return 1
    def GetXClock(self): return None
    def Finish(self):
        source = str(Path(__file__).with_suffix('.sv'))
        records = [(1, 'v_line', self.count), (2, 'v_toggle', 7), (3, 'v_branch', 0)]
        self.path.write_text('# SystemC::Coverage-3\n' + ''.join(
            f"C '\x01f\x02{source}\x01l\x02{line}\x01page\x02{kind}/DUT\x01o\x02{line}\x01h\x02TOP.DUT' {count}\n"
            for line, kind, count in records))

@pytest.fixture
def dut():
    dut = DUT()
    try: yield dut
    finally: dut.Finish()

@pytest.mark.parametrize('n', range(1, 41))
def test_counter(dut, n):
    dut.count = n
'''
# Keep this source a normal user test: the fixture owns the DUT and calls
# Finish(); it never imports XReactor's collector or emits a receipt.


def points(path):
    import re
    return {match[1]: int(match[2]) for line in path.read_bytes().splitlines()
            if (match := re.fullmatch(rb"C '(.*)' ([0-9]+)", line)) is not None}


def test_native_serial_parallel_counts_zero_points_and_cleanup(tmp_path):
    (tmp_path / "test_user.sv").write_text("module DUT;\nwire toggle;\nendmodule\n")
    measurements = []
    for workers in (1, 3):
        output, _ = run_cli(tmp_path, NATIVE, workers=workers,
            options=("--native-coverage-tool", TOOL), output_name=f"artifacts-{workers}")
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["state"] == "committed" and manifest["cleanup_complete"]
        assert manifest["tests"] == {"PASS": 40}
        assert sum(w["native_inputs"] for w in manifest["workers"]) == 40
        native, = output.glob("native/*/coverage.dat")
        measurement = points(native)
        assert sorted(measurement.values()) == [0, 280, 820]
        assert not (output / "_workers").exists()
        info, = output.glob("native/*/coverage.info")
        text = info.read_text()
        assert "DA:1,820" in text and "DA:3,0" in text and "DA:2," not in text
        measurements.append(measurement)
    assert measurements[0] == measurements[1]


def test_debug_retains_raw_native_inputs(tmp_path):
    (tmp_path / "test_user.sv").write_text("module DUT;\nwire toggle;\nendmodule\n")
    output, _ = run_cli(tmp_path, NATIVE, workers=2,
        options=("--native-coverage-tool", TOOL, "--keep-coverage-inputs"))
    assert len(list(output.glob("_workers/*/native/raw/*.dat"))) == 40
    assert len(list(output.glob("native/*/coverage.dat"))) == 1


def test_native_merge_failure_keeps_unconsumed_data(tmp_path):
    tool = tmp_path / "broken-merger"
    tool.write_text("#!/bin/sh\necho 'injected merger failure' >&2\nexit 9\n")
    tool.chmod(0o755)
    (tmp_path / "test_user.sv").write_text("module DUT;\nwire toggle;\nendmodule\n")
    text = NATIVE.replace("range(1, 41)", "range(1, 3)")
    output, _ = run_cli(tmp_path, text, workers=2, expected=1,
        options=("--native-coverage-tool", str(tool)))
    assert json.loads((output / "manifest.json").read_text())["state"] == "incomplete"
    assert list(output.glob("_workers/*/native/raw/*.dat"))
    assert not list(output.glob("native/*/coverage.dat"))


def test_session_dut_is_exported_once_per_worker(tmp_path):
    (tmp_path / "test_user.sv").write_text("module DUT;\nwire toggle;\nendmodule\n")
    text = NATIVE.replace("@pytest.fixture\n", "@pytest.fixture(scope='session')\n")
    text = text.replace("dut.count = n", "dut.count += n")
    output, _ = run_cli(tmp_path, text, workers=2, options=("--native-coverage-tool", TOOL))
    manifest = json.loads((output / "manifest.json").read_text())
    assert sum(w["native_inputs"] for w in manifest["workers"]) == 2
    native, = output.glob("native/*/coverage.dat")
    assert sorted(points(native).values()) == [0, 14, 820]


def test_toggle_only_tables_are_retained_without_fake_line_hits(tmp_path):
    (tmp_path / "test_user.sv").write_text("module DUT;\nwire toggle;\nendmodule\n")
    text = NATIVE.replace("[(1, 'v_line', self.count), (2, 'v_toggle', 7), (3, 'v_branch', 0)]",
                          "[(2, 'v_toggle', 7)]").replace("range(1, 41)", "range(1, 3)")
    output, _ = run_cli(tmp_path, text, workers=2, options=("--native-coverage-tool", TOOL))
    native, = output.glob("native/*/coverage.dat")
    assert list(points(native).values()) == [14]
    assert not list(output.glob("native/*/coverage.info"))
    assert (output / "coverage.html").is_file()


def test_duplicate_worker_native_receipt_is_rejected(tmp_path):
    (tmp_path / "test_user.sv").write_text("module DUT;\nwire toggle;\nendmodule\n")
    text = NATIVE.replace("range(1, 41)", "range(1, 3)") + '''
def test_duplicate():
    from xreactor._native_coverage import NativeCollector
    original = NativeCollector.finish
    def duplicated(self):
        records = original(self)
        return records + records
    NativeCollector.finish = duplicated
'''
    output, _ = run_cli(tmp_path, text, workers=1, expected=1, options=("--native-coverage-tool", TOOL))
    assert json.loads((output / "manifest.json").read_text())["state"] == "incomplete"
    assert list(output.glob("_workers/*/native/*/merged.dat"))


def test_dut_created_by_fixture_factory_in_body_is_discovered_before_finish(tmp_path):
    (tmp_path / "test_user.sv").write_text("module DUT;\nwire toggle;\nendmodule\n")
    header = NATIVE[:NATIVE.index('@pytest.fixture')]
    text = header + '''
class Factory:
    def __init__(self): self._instances = []
    def create(self):
        dut = DUT()
        self._instances.append(dut)
        return dut
    def close(self):
        for dut in self._instances: dut.Finish()
@pytest.fixture
def factory():
    result = Factory()
    try: yield result
    finally: result.close()
@pytest.mark.parametrize('n', [1, 2, 3])
def test_factory(factory, n):
    factory.create().count = n
'''
    output, _ = run_cli(tmp_path, text, workers=2, options=("--native-coverage-tool", TOOL))
    native, = output.glob("native/*/coverage.dat")
    assert sorted(points(native).values()) == [0, 6, 21]
