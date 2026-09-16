# Cache integration example

These scripts verify Picker's `example/CacheSignalCFG/Cache.v` through a
memory-direct generated Python DUT:

- `example_xreactor.py`: short trigger/backend smoke test;
- `cache_functional_xreactor.py`: directed and randomized read/write campaign;
- `cache_direct_protocol_probe.py`: low-level memory-direct protocol probe.

Generate the DUT with Picker first, then place the generated module and xspcomm
binding on `PYTHONPATH`. From the XReactor project root:

```bash
PYTHONPATH=src:/path/to/generated/cache:/path/to/xspcomm/python \
  python3 examples/integration/cache/example_xreactor.py
```
