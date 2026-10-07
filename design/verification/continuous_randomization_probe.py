"""Research probe; this is not a public XReactor randomization API.

Run from the repository root:
    PYTHONPATH=src:. python3 design/verification/continuous_randomization_probe.py
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import platform
import random

from examples.transactions.reference_model import (
    AccumulatorAgent, AccumulatorDut, AccumulatorModel, Command,
)
from xreactor import Execution


class RngStreams:
    """Cache independent streams derived from a root seed and explicit names."""

    def __init__(self, seed: int):
        if type(seed) is not int or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        self.seed = seed
        self._streams: dict[tuple[str, ...], random.Random] = {}

    def derived_seed(self, *path: str) -> int:
        if not path or any(not isinstance(part, str) or not part for part in path):
            raise ValueError("path must contain nonempty string segments")
        encoded = json.dumps(
            ["xreactor.rng.v1", self.seed, list(path)],
            ensure_ascii=True, separators=(",", ":"),
        ).encode("utf-8")
        return int.from_bytes(hashlib.sha256(encoded).digest(), "big")

    def rng(self, *path: str) -> random.Random:
        if path not in self._streams:
            self._streams[path] = random.Random(self.derived_seed(*path))
        return self._streams[path]


@dataclass(frozen=True)
class MemoryRequest:
    op: str
    addr: int
    beats: int
    data: int


def draw_memory_request(rng: random.Random) -> MemoryRequest:
    """Construct an aligned burst within a 4 KiB page, without rejection."""
    beats = rng.choice((1, 2, 4, 8, 16))
    page = rng.randrange(16)
    word = rng.randrange(512 - beats + 1)
    op = rng.choices(("read", "write"), weights=(3, 2), k=1)[0]
    return MemoryRequest(
        op, 0x10000 + page * 4096 + word * 8, beats,
        rng.getrandbits(64) if op == "write" else 0,
    )


def request_trace(seed: int, count: int, *, noise: bool = False) -> list[MemoryRequest]:
    streams = RngStreams(seed)
    traffic = streams.rng("port0", "traffic")
    result = []
    for _ in range(count):
        if noise:
            streams.rng("port0", "delay").randrange(16)
            streams.rng("observer", "debug").getrandbits(32)
        result.append(draw_memory_request(traffic))
    return result


def trace_digest(trace) -> str:
    encoded = json.dumps(trace, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


async def run_agent(seed: int, *, replay=None):
    """Eight bounded batches; model-dependent choices follow a complete drain.

    The existing toy DUT only defines tags 1..3, reused after draining a batch.
    Each run gets a fresh DUT, model, Agent and Execution.
    """
    model = AccumulatorModel()
    dut = AccumulatorDut("memory")
    rng = RngStreams(seed).rng("accumulator", "traffic")
    rows = []
    responses = []
    try:
        agent = AccumulatorAgent(dut, response_timeout_cycles=5)
        agent.connect(model)
        async with asyncio.timeout(5), Execution(dut.backend, agents=[agent]):
            for batch in range(8):
                before = model.total
                # This is generator state, not a speculative model update.
                limit = 1 + before % 15
                transfers = []
                for index, tag in enumerate((1, 2, 3)):
                    row = (
                        dict(replay[batch * 3 + index]) if replay is not None else
                        {"tag": tag, "operand": rng.randint(1, limit)}
                    )
                    assert row["tag"] == tag and 1 <= row["operand"] <= limit
                    rows.append(row)
                    transfers.append(agent.submit(Command(**row)))
                assert model.total == before, "submission must not advance the model"
                await agent.drain(timeout_cycles=30)
                for transfer in transfers:
                    responses.append(asdict(await transfer))
                assert model.total == sum(row["operand"] for row in rows)
            await agent.finish(timeout_cycles=30, observe_cycles=1)
        return {
            "requests": rows, "responses": responses,
            "emission_order": dut.emitted_tags, "model_total": model.total,
            "last_tick": dut.backend.tick,
        }
    finally:
        dut.close()


async def main():
    count = 10_000
    original = request_trace(17, count)
    assert original == request_trace(17, count)
    assert original == request_trace(17, count, noise=True)
    assert original != request_trace(23, count)
    for request in original:
        assert request.op in {"read", "write"}
        assert request.addr % 8 == 0
        assert 0x10000 <= request.addr < 0x20000
        assert request.beats in {1, 2, 4, 8, 16}
        assert request.addr % 4096 + request.beats * 8 <= 4096
        assert 0 <= request.data < 1 << 64

    streams = RngStreams(17)
    assert streams.rng("port0", "traffic") is streams.rng("port0", "traffic")
    assert streams.rng("port0", "traffic") is not streams.rng("port0", "delay")
    rng = streams.rng("checkpoint")
    state = rng.getstate()
    sequence = [rng.getrandbits(32) for _ in range(16)]
    rng.setstate(state)
    assert sequence == [rng.getrandbits(32) for _ in range(16)]

    first = await run_agent(17)
    repeated = await run_agent(17)
    other = await run_agent(23)
    # Changing the RNG seed has no effect when explicit requests are replayed.
    restored = await run_agent(999, replay=json.loads(json.dumps(first["requests"])))
    assert first == repeated == restored
    assert first["requests"] != other["requests"]
    assert first["emission_order"] == [2, 1, 3] * 8
    print(json.dumps({
        "status": "passed", "backend": "MemoryBackend",
        "python": platform.python_version(), "probe_contract": "randomization-research/v1",
        "legal_samples": count,
        "same_seed_trace": True, "observer_and_delay_isolation": True,
        "rng_state_restore": True, "different_seed_changes_trace": True,
        "agent_runs": 4, "requests_per_agent_run": 24,
        "submission_does_not_advance_model": True,
        "state_dependent_batches": True, "out_of_order_checks": True,
        "explicit_request_replay_with_changed_seed": True,
        "trace_sha256": trace_digest([asdict(row) for row in original]),
        "agent_trace_sha256": trace_digest(first["requests"]),
        "agent_model_total": first["model_total"],
        "agent_last_tick": first["last_tick"],
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
