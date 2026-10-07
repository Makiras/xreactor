"""Run from the repository root: python3 -m pytest -q -s <this file>."""

import itertools
import random

import pytest

from examples.transactions.verification_flow import verified_pipeline


@pytest.fixture
def pipeline(request, tmp_path):
    runs = itertools.count()

    def open_run(*, seed, backend="memory"):
        output = tmp_path / f"seed-{seed}-run-{next(runs)}"
        print(f"verification artifacts: {output}")
        return verified_pipeline(
            output=output, nodeid=request.node.nodeid, seed=seed, backend=backend,
        )

    return open_run


@pytest.mark.asyncio
@pytest.mark.parametrize("seed, requests", [
    pytest.param(17, (1, 2), id="first"),
    pytest.param(23, (2, 3), id="second"),
])
async def test_responses(pipeline, seed, requests):
    # Each case contributes part of the same coverage model. Closure is checked
    # after merging runs, rather than requiring every case to hit every bin.
    requests = list(requests)
    random.Random(seed).shuffle(requests)
    async with pipeline(seed=seed) as agent:
        transfers = [agent.submit(request) for request in requests]
        await agent.finish(timeout_cycles=30, observe_cycles=1)
        assert [response.tag for response in [await item for item in transfers]] == requests
