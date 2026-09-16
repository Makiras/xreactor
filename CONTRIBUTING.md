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

From this directory, with an xspcomm Python binding on `PYTHONPATH` when native
tests are required:

```bash
python3 -m pytest -q
```

Pure-Python tests use `MemoryBackend`; native integration tests are skipped when
the required xspcomm trigger API is unavailable.
