# XReactor examples

- `triggers/`: execution, edges, sampled values, and compiled triggers;
- `coverage/`: covergroups, bins, crosses, and JSON output;
- `integration/`: DUT-specific verification environments.

Run the standalone examples from the project root:

```bash
PYTHONPATH=src python3 examples/triggers/basic_execution.py
PYTHONPATH=src python3 examples/coverage/functional_coverage.py
```

Integration environments list their own DUT and tool dependencies in their
README files.
