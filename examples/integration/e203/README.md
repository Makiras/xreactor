# e203 IFU-to-ICB XReactor verification

This environment verifies the real `e203_ifu_ift2icb` RTL through Picker's
memory-direct Python binding and XReactor.

It contains:

- a deterministic byte-addressed instruction-memory model;
- an independent model of ITCM/BIU routing and 0/1/2-command fetch behavior;
- command/response backpressure, variable latency, and error injection;
- directed and seeded randomized stress traffic;
- protocol-stability and timeout checks;
- CoverGroup/Point/Bin/Cross functional coverage;
- Verilator line coverage converted to LCOV;
- throughput and half-tick performance artifacts.

Generate the DUT from an external Picker checkout:

```bash
export PICKER_ROOT=/path/to/picker
export PICKER_BIN="$PICKER_ROOT/build/bin/picker"
examples/integration/e203/build_xreactor.sh
```

Install the XReactor test extras and run pytest:

```bash
python3 -m pip install -e '.[test]'
export XCOMM_PYTHON=/path/to/xspcomm/python
examples/integration/e203/run_pytest.sh
```

Useful environment variables:

- `E203_RANDOM_COUNT` (default `500`);
- `E203_SEED` (default `0xE203`);
- `E203_WALL_TIMEOUT` (default `60` seconds);
- `E203_DUT_DIR` and `E203_ARTIFACT_DIR`;
- `E203_MIN_TRANSACTIONS_PER_SECOND` (default `0`, measurement only);
- `E203_TRACE=1` for transaction logging.

Measure functional coverage overhead against the same DUT and traffic:

```bash
PYTHONPATH=src:$XCOMM_PYTHON:examples/integration/e203 \
  python3 examples/integration/e203/benchmark_coverage.py \
  --dut-dir output/xreactor_e203 --random-count 500 --repeats 9 --json
```

Artifacts are written under `output/e203-verification` by default:

- `functional-coverage.json`;
- `line-coverage.info` and `line-coverage.json`;
- self-contained `coverage-report.html` combining functional and RTL line coverage;
- navigable `coverage-report/index.html` with per-group pages and annotated RTL source;
- `transactions.json`;
- `performance.json`;
- raw `verilator-coverage.dat`.

Functional coverage is sampled from the same immutable `FetchTransaction`
checked by the reference model. It never re-reads live DUT pins.
