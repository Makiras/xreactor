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

Passive native coverage and optional pattern diagnostics use the same script:

```bash
PYTHONPATH=src:/path/to/xcomm-build/python \
  python3 benchmarks/benchmark_coverage.py --native --iterations 20000 --repeats 5
```

The `native_overlap` and `native_overlap_summary` modes run identical overlapping
Sequence patterns, with three active attempts at steady state. Only the summary
diagnostics setting changes. Counts, pending attempts and RunUntil returns are
checked; timings include Execution startup and cleanup. This is a no-op XClock
measurement, not a prediction of RTL simulation cost.

Driver resource-lock and concurrency-slot handoffs have a native microbenchmark:

```bash
PYTHONPATH=src:/path/to/xcomm-build/python \
  python3 benchmarks/benchmark_driver_handoffs.py --requests 256 --repeats 7
```

It reports per-request wall time, all raw samples, and final half-ticks for
uncontended sequential input and contended two-stage input. Check simulated
timing as well as wall time: a faster run that misses stage overlap is incorrect.
This benchmark uses a no-op clock, not a real RTL throughput measurement.

Callback observation and unrelated host scheduling are measured separately:

```bash
PYTHONPATH=src:/path/to/xcomm-build/python \
  python3 benchmarks/benchmark_asyncio_observer.py --repeats 7
```

It measures per-cycle awaits, a long clock wait, and a native host Task yielding
100,000 times with and without an active Execution. The host Task is explicitly
outside simulation observation. Its relative cost measures the shared entry's
overhead; it is not an estimate of HTTP or real RTL application slowdown.
