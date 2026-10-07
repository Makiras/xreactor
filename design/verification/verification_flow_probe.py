"""Maintainer probes for the verification-flow audit and follow-up fixes.

Run with the project's test environment. The original pre-fix JSON is retained
separately; current lifecycle contracts are asserted by the regression suite.
The retired pytest feature-label probes are not rerun by this script.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from xreactor import (
    Bundle, ClockCycles, Execution, MemoryBackend, ReadyValid, ReadyValidMonitor,
    Role, drive_ready_valid,
)


class Signal:
    def __init__(self, value=0):
        self.value = value

    def Set(self, value):
        self.value = value

    def U(self):
        return self.value

    def W(self):
        return 8


async def monitor_probes():
    clock = object()
    valid, ready, data = Signal(), Signal(1), Signal()
    backend = MemoryBackend(clock)
    monitor = ReadyValidMonitor(ReadyValid(
        clock, valid, ready, Bundle(data=data), role=Role.MONITOR,
    ))
    result = {}
    try:
        async with Execution(backend) as execution:
            async with execution.paused():
                monitor.start(execution)
                waiting = asyncio.create_task(monitor.recv())
                try:
                    await asyncio.sleep(0)
                    await monitor.aclose()
                    await asyncio.sleep(0)
                    result["recv_done_after_close"] = waiting.done()
                    if waiting.done():
                        result["recv_close_error"] = type(waiting.exception()).__name__
                finally:
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)

            monitor = ReadyValidMonitor(ReadyValid(
                clock, valid, ready, Bundle(data=data), role=Role.MONITOR,
            )).start(execution)
            accepted = await drive_ready_valid(clock, valid, ready, lambda: data.Set(9))
            await ClockCycles(clock, 1)
            await monitor.aclose()
            async with execution.paused():
                restart_tick = backend.tick
                try:
                    monitor.start(execution)
                except RuntimeError as error:
                    result["restart_error"] = type(error).__name__
                    result["buffered_after_close"] = monitor._queue.qsize()
                else:
                    observation = await monitor.recv()
                    result["buffered_observation_after_restart"] = {
                        "acceptance_tick": accepted.tick,
                        "restart_tick": restart_tick,
                        "returned_tick": observation.event.tick,
                        "value": observation.value.data.as_int(),
                    }
                await monitor.aclose()
    finally:
        backend.close()
    result["decoder_failure"] = await monitor_failure_probe()
    return result


async def monitor_failure_probe():
    clock = object()
    valid, ready, data = Signal(), Signal(1), Signal()
    backend = MemoryBackend(clock)

    def decode(value):
        raise ValueError("decoder failed")

    monitor = ReadyValidMonitor(ReadyValid(
        clock, valid, ready, Bundle(data=data), role=Role.MONITOR,
    ), decoder=decode)
    result = {}
    try:
        async with asyncio.timeout(2), Execution(backend) as execution:
            monitor.start(execution)
            waiting = asyncio.create_task(monitor.recv())
            drive = asyncio.create_task(
                drive_ready_valid(clock, valid, ready, lambda: data.Set(7)),
            )
            try:
                await asyncio.wait(
                    (waiting, execution._pump_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                result["recv_done"] = waiting.done()
                result["pump_done"] = execution._pump_task.done()
                if waiting.done():
                    error = waiting.exception()
                    result["recv_error"] = type(error).__name__
                    result["recv_message"] = str(error)
                if execution._pump_task.done():
                    result["pump_error"] = type(execution._pump_task.exception()).__name__
            finally:
                waiting.cancel()
                drive.cancel()
                await asyncio.gather(waiting, drive, return_exceptions=True)
                await monitor.aclose()
    except ValueError as error:
        result["context_exit_error"] = str(error)
    finally:
        backend.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    result = {"monitor": asyncio.run(monitor_probes())}
    (root / "results.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
