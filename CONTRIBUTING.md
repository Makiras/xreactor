# XReactor development guide

XReactor is maintained as an independent Python project. Native clock, data,
and trigger primitives are provided by xcomm.

## Organize changes by feature

Every user-visible feature should be delivered as a coherent vertical slice:

1. implementation in `src/xreactor/`, using a focused module or subpackage;
2. user behavior in `docs/guides/` or `docs/reference/`, with implementation
   decisions and validation records isolated under `design/`;
3. unit tests in the matching `tests/` category;
4. a minimal example under `examples/` when the API is user-facing;
5. a benchmark under `benchmarks/` when the change affects a hot path.

Do not grow an unrelated catch-all module or test file. Split a module when it
starts owning more than one independent concept. Integration code for a real
DUT belongs in `examples/integration/<dut>/`.

## Project boundaries

- `src/xreactor`: Python API, scheduling, methodology and reports.
- xcomm: native clock/data/trigger engine.
- `examples/integration`: XReactor environments for external DUTs.
- `tests/integration`: automated backend and host-asyncio integration tests.

`Execution` never owns its backend. It clears execution-local state on exit;
the backend creator is responsible for calling `close()`.

## Verification

The default command runs pure-Python tests and uses a native xspcomm binding
when one is already importable. It also discovers the standard sibling Picker
build at `../picker/build/dependence/xcomm/python`:

```bash
python3 -m pytest -q
```

Pure-Python tests use `MemoryBackend`. Before merging a backend or scheduling
change, require the native suite explicitly so a missing binding cannot turn
into a successful run with skipped tests:

```bash
XCOMM_PYTHON=/path/to/xcomm/build/python \
  python3 -m pytest -q --require-xspcomm
```

The binding must provide `XClock.StepHalf` and `XTriggerEngine`. Building it
requires SWIG 4.2 or newer. To install it from xcomm source, both build switches
are required:

```bash
BUILD_XSPCOMM_SWIG=python XSPCOMM_BUILD_WHEEL=1 \
  python3 -m pip install /path/to/xcomm
```

CI always installs the pinned xcomm source and runs with
`--require-xspcomm`; native integration coverage therefore cannot be silently
skipped there.

## Versions and releases

Package versions come from Git tags through setuptools-scm. Do not add a second
version string to the source. Each PR targeting `main` needs exactly one of
`release:patch`, `release:minor`, or `release:major`; the first feature release
uses `release:minor` to produce `v0.1.0`. Merge results are tagged automatically.
Tagged CI repeats tests, strict documentation, distribution checks, a rebuild
from the source archive, and an isolated wheel install before GitHub publishing.

The xcomm checkout and required coverage ABI live in
`.github/native-dependencies.json`. Update this pin alongside the relevant
regressions; do not use a floating branch for release verification.
Authored Markdown and Python records under `design/verification` are committed;
write new generated reports, logs and coverage databases under `output/` so they
remain ignored. Reusable report templates, fixtures and verification plans stay
with the source files.

See [versioning and releases](docs/guides/versioning-and-releases.md) for setup,
failure recovery, artifact provenance and local pre-commit commands.
