# Test organization

Tests mirror framework functionality:

- `runtime/`: Execution, trigger scheduling, subscriptions and cancellation;
- `interfaces/`: data layout, Bundle, Interface, Driver and Monitor behavior;
- `coverage/`: functional coverage schemas, counters and HTML reporting;
- `integration/`: xcomm native backend and coexistence with host asyncio/HTTP.

New tests should be placed with the feature they validate. A test belongs in
`integration/` only when it crosses a real subsystem boundary; using asyncio
alone does not automatically make a test an integration test.
