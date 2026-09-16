# Runtime benchmark

The benchmark compares scheduling overhead with a no-op synthetic `XClock`.
It is a regression baseline, not a simulator performance claim.

```bash
PYTHONPATH=src:/path/to/xcomm-build/python \
  python3 benchmarks/benchmark_runtime.py \
  --ticks 200000 --repeats 5 --json
```

Keep the host, xcomm build type, compiler flags, waveform/coverage settings,
tick count and repeat count unchanged when comparing revisions. Report the
median and retain all raw nanosecond samples from the JSON output.

Cases:

- one native `XClock.Step` crossing;
- one Python crossing per `StepHalf`;
- `RunUntil` with no watcher, Value, compiled Expr and compiled FSM;
- explicit Python predicate sampling at each rising phase;
- full `XReactor -> Future -> asyncio task` resume per cycle.

Functional coverage has a separate transaction-level benchmark:

```bash
PYTHONPATH=src \
  python3 benchmarks/benchmark_coverage.py \
  --iterations 100000 --repeats 5 --json
```

It compares transaction-field access, `details=False`, and per-sample detail
construction. `--max-fast-ns` enables a fixed-runner CI threshold. The real
e203 A/B benchmark is `examples/integration/e203/benchmark_coverage.py` and
supports the relative `--max-slowdown-percent` threshold.
