"""Functional verification for the generated Cache through xreactor.

This is intentionally more than a binding smoke test.  It supplies a backing
memory/MMIO model, checks architectural results against a byte-addressed
reference model, and exercises refill, hit, masked write, dirty eviction,
backpressure, MMIO bypass, and deterministic randomized traffic.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import random
from collections import deque
from dataclasses import dataclass

try:
    from UT_CacheSignalCFG import DUTCacheSignalCFG
except ImportError:
    try:
        from CacheSignalCFG import DUTCacheSignalCFG
    except ImportError:
        from __init__ import DUTCacheSignalCFG

from xreactor import (
    FallingEdge,
    ReadyValid,
    ReadyValidDriver,
    ReadyValidMonitor,
    RisingEdge,
    Role,
    Execution,
    Value,
    XCommClockBackend,
    as_xdata,
)


CMD_READ = 0x0
CMD_WRITE = 0x1
CMD_READ_BURST = 0x2
CMD_WRITE_BURST = 0x3
CMD_READ_RESP = 0x4
CMD_WRITE_RESP = 0x5
CMD_READ_LAST = 0x6
CMD_WRITE_LAST = 0x7

MASK64 = (1 << 64) - 1
LINE_BYTES = 64
WORDS_PER_LINE = 8
SAME_SET_STRIDE = 1 << 13
TRACE = os.environ.get("CACHE_TRACE") == "1"


def trace(message: str) -> None:
    if TRACE:
        print(message, flush=True)


def get(signal) -> int:
    return int(signal.value)


def set_(signal, value: int) -> None:
    signal.Set(int(value))


def merge_word(old: int, new: int, mask: int) -> int:
    result = old
    for byte in range(8):
        if mask & (1 << byte):
            result &= ~(0xFF << (8 * byte))
            result |= ((new >> (8 * byte)) & 0xFF) << (8 * byte)
    return result & MASK64


class ReferenceMemory:
    def __init__(self) -> None:
        self.words: dict[int, int] = {}

    @staticmethod
    def word_addr(addr: int) -> int:
        return addr & ~0x7

    def default(self, addr: int) -> int:
        addr = self.word_addr(addr)
        return (
            0xA500_0000_0000_0000
            ^ ((addr & 0xFFFF_FFFF) << 17)
            ^ (addr * 0x9E37_79B1)
        ) & MASK64

    def read(self, addr: int) -> int:
        addr = self.word_addr(addr)
        return self.words.get(addr, self.default(addr))

    def write(self, addr: int, value: int, mask: int = 0xFF) -> None:
        addr = self.word_addr(addr)
        self.words[addr] = merge_word(self.read(addr), value, mask)


@dataclass(frozen=True)
class BusRequest:
    tick: int
    addr: int
    cmd: int
    size: int
    wmask: int
    wdata: int


@dataclass(frozen=True)
class CacheInterfaces:
    cpu_request: ReadyValid
    cpu_response: ReadyValid
    memory_request: ReadyValid
    memory_response: ReadyValid
    mmio_request: ReadyValid
    mmio_response: ReadyValid
    coherence_request: ReadyValid
    coherence_response: ReadyValid


def bind_cache_interfaces(dut) -> CacheInterfaces:
    if not hasattr(dut, "signal_tree"):
        raise RuntimeError(
            "complete Cache interface binding requires generated signal_tree"
        )

    def bind(path, prefix: str, role: Role, name: str) -> ReadyValid:
        node = dut.signal_tree
        for part in path:
            node = node[part]
        return ReadyValid.bind_tree(
            dut,
            node,
            clock=dut.clock,
            source_prefix=prefix,
            role=role,
            name=name,
        )

    return CacheInterfaces(
        cpu_request=bind(
            ("io", "in", "req"), "io_in_req", Role.PRODUCER,
            "cache.cpu_request",
        ),
        cpu_response=bind(
            ("io", "in", "resp"), "io_in_resp", Role.CONSUMER,
            "cache.cpu_response",
        ),
        memory_request=bind(
            ("io", "out", "mem", "req"), "io_out_mem_req",
            Role.CONSUMER, "cache.memory_request",
        ),
        memory_response=bind(
            ("io", "out", "mem", "resp"), "io_out_mem_resp",
            Role.PRODUCER, "cache.memory_response",
        ),
        mmio_request=bind(
            ("io", "mmio", "req"), "io_mmio_req", Role.CONSUMER,
            "cache.mmio_request",
        ),
        mmio_response=bind(
            ("io", "mmio", "resp"), "io_mmio_resp", Role.PRODUCER,
            "cache.mmio_response",
        ),
        coherence_request=bind(
            ("io", "out", "coh", "req"), "io_out_coh_req",
            Role.PRODUCER, "cache.coherence_request",
        ),
        coherence_response=bind(
            ("io", "out", "coh", "resp"), "io_out_coh_resp",
            Role.CONSUMER, "cache.coherence_response",
        ),
    )


class MemoryModel:
    """SimpleBus-like model matching this Cache's wrap-refill protocol."""

    def __init__(
        self,
        dut,
        memory: ReferenceMemory,
        interfaces: CacheInterfaces,
        *,
        response_gap: int = 0,
    ):
        self.dut = dut
        self.memory = memory
        self.request = interfaces.memory_request
        self.response = interfaces.memory_response
        self.response_gap = response_gap
        self.requests: list[BusRequest] = []
        self.read_bursts: list[int] = []
        self.writebacks: list[int] = []
        self._responses: deque[tuple[int, int]] = deque()
        self._write_line: int | None = None
        self._write_words: list[int] = []
        self._cooldown = 0
        self._tick = 0

    def _accept_request(self) -> None:
        bits = self.request.bits.sample()
        req = BusRequest(
            tick=self._tick,
            addr=bits.addr.as_int(),
            cmd=bits.cmd.as_int(),
            size=bits.size.as_int(),
            wmask=bits.wmask.as_int(),
            wdata=bits.wdata.as_int(),
        )
        self.requests.append(req)
        trace(f"[{self._tick:05d}] mem request {req}")
        assert req.size == 3, f"memory request size is not 8 bytes: {req}"
        assert req.wmask == 0xFF, f"memory request mask is not full: {req}"

        if req.cmd == CMD_READ_BURST:
            assert req.addr & 0x7 == 0, f"unaligned refill request: {req}"
            self.read_bursts.append(req.addr)
            line = req.addr & ~(LINE_BYTES - 1)
            first = (req.addr >> 3) & 0x7
            for beat in range(WORDS_PER_LINE):
                index = (first + beat) & 0x7
                cmd = CMD_READ_LAST if beat == WORDS_PER_LINE - 1 else CMD_READ_RESP
                self._responses.append((cmd, self.memory.read(line + index * 8)))
            return

        if req.cmd in (CMD_WRITE_BURST, CMD_WRITE_LAST):
            line = req.addr & ~(LINE_BYTES - 1)
            if self._write_line is None:
                self._write_line = line
                self._write_words = []
            assert line == self._write_line, (
                f"writeback line changed mid-burst: {self._write_line:#x} -> {line:#x}"
            )
            expected_cmd = (
                CMD_WRITE_LAST
                if len(self._write_words) == WORDS_PER_LINE - 1
                else CMD_WRITE_BURST
            )
            assert req.cmd == expected_cmd, (
                f"writeback command/beat mismatch at beat {len(self._write_words)}: {req}"
            )
            self._write_words.append(req.wdata)
            if req.cmd == CMD_WRITE_LAST:
                assert len(self._write_words) == WORDS_PER_LINE
                for index, word in enumerate(self._write_words):
                    self.memory.write(line + index * 8, word)
                self.writebacks.append(line)
                self._write_line = None
                self._write_words = []
                self._responses.append((CMD_WRITE_RESP, 0))
            return

        raise AssertionError(f"unexpected memory command: {req}")

    async def run(self) -> None:
        response_active = False
        try:
            while True:
                edge = await FallingEdge(self.dut.clock)
                self._tick = edge.tick

                # Present already queued responses before observing a new
                # request.  A response created by this cycle's request must not
                # be consumed on the same rising edge: the Cache changes from
                # request to response state on that edge.
                if response_active:
                    # io_out_mem_resp_ready is hard-wired high in this DUT.
                    assert get(self.response.ready) == 1
                elif self._responses and self._cooldown == 0:
                    cmd, rdata = self._responses[0]
                    self.response.bits.drive({"cmd": cmd, "rdata": rdata})
                    set_(self.response.valid, 1)
                    response_active = True
                    trace(f"[{self._tick:05d}] mem response cmd={cmd:#x} data={rdata:#018x}")
                elif self._cooldown:
                    self._cooldown -= 1

                if (
                    get(self.request.valid)
                    and get(self.request.ready)
                ):
                    self._accept_request()

                await RisingEdge(self.dut.clock)

                if response_active:
                    self._responses.popleft()
                    set_(self.response.valid, 0)
                    response_active = False
                    self._cooldown = self.response_gap
        finally:
            set_(self.response.valid, 0)


class MmioModel:
    def __init__(self, dut, memory: ReferenceMemory, interfaces: CacheInterfaces):
        self.dut = dut
        self.memory = memory
        self.request = interfaces.mmio_request
        self.response = interfaces.mmio_response
        self.requests: list[BusRequest] = []
        self._pending: deque[int] = deque()

    async def run(self) -> None:
        response_active = False
        try:
            while True:
                edge = await FallingEdge(self.dut.clock)

                # As with memory, do not respond on the edge that accepts the
                # request because the Cache has not entered its wait state yet.
                if response_active:
                    assert get(self.response.ready) == 1
                elif self._pending:
                    self.response.bits.drive(
                        {"cmd": 0, "rdata": self._pending[0]}
                    )
                    set_(self.response.valid, 1)
                    response_active = True

                if get(self.request.valid) and get(self.request.ready):
                    bits = self.request.bits.sample()
                    req = BusRequest(
                        tick=edge.tick,
                        addr=bits.addr.as_int(),
                        cmd=bits.cmd.as_int(),
                        size=bits.size.as_int(),
                        wmask=bits.wmask.as_int(),
                        wdata=bits.wdata.as_int(),
                    )
                    self.requests.append(req)
                    trace(f"[{edge.tick:05d}] mmio request {req}")
                    if req.cmd == CMD_WRITE:
                        self.memory.write(req.addr, req.wdata, req.wmask)
                        self._pending.append(0)
                    elif req.cmd == CMD_READ:
                        self._pending.append(self.memory.read(req.addr))
                    else:
                        raise AssertionError(f"unexpected MMIO command: {req}")

                await RisingEdge(self.dut.clock)
                if response_active:
                    self._pending.popleft()
                    set_(self.response.valid, 0)
                    response_active = False
        finally:
            set_(self.response.valid, 0)


class CacheDriver:
    def __init__(self, dut, interfaces: CacheInterfaces):
        self.dut = dut
        self.user = 1
        self.transactions = 0
        self.request_interface = interfaces.cpu_request
        self.response_interface = interfaces.cpu_response
        self.request_bits = self.request_interface.bits
        self.request_driver = ReadyValidDriver(self.request_interface)

    async def request(
        self,
        addr: int,
        cmd: int,
        *,
        wdata: int = 0,
        wmask: int = 0xFF,
        size: int = 3,
        response_stall_cycles: int = 0,
        require_idle: bool = True,
    ) -> tuple[int, int, int]:
        user = self.user
        self.user = (self.user + 1) & 0xFFFF

        # Enter a falling-stable drive phase exactly once.  Waiting for another
        # FallingEdge after asserting valid would cross two rising edges and
        # duplicate the request.
        for _ in range(1000):
            await FallingEdge(self.dut.clock)
            if not require_idle or get(self.dut.io_empty):
                break
        else:
            raise AssertionError("Cache did not become empty before request")

        trace(
            f"send request addr={addr:#010x} cmd={cmd:#x} "
            f"data={wdata:#018x} mask={wmask:#04x} user={user:#x}"
        )

        accepted = await self.request_driver.send(
            {
                "addr": addr,
                "size": size,
                "cmd": cmd,
                "wmask": wmask,
                "wdata": wdata,
                "user": user,
            }
        )
        accepted_tick = accepted.tick
        trace(f"[{accepted_tick:05d}] request accepted user={user:#x}")

        response = None
        stable = None
        stalls = 0
        for _ in range(1000):
            edge = await FallingEdge(self.dut.clock)
            if not get(self.response_interface.valid):
                continue
            bits = self.response_interface.bits.sample()
            current = (
                bits.cmd.as_int(),
                bits.rdata.as_int(),
                bits.user.as_int(),
            )
            if stable is None:
                stable = current
                if response_stall_cycles:
                    # Keep the pipeline flowing until a response actually
                    # exists, then withdraw ready before its sampling edge.
                    set_(self.response_interface.ready, 0)
            else:
                assert current == stable, (
                    f"response changed under backpressure: {stable} -> {current}"
                )
            if stalls < response_stall_cycles:
                stalls += 1
                continue
            set_(self.response_interface.ready, 1)
            response = current
            trace(
                f"[{edge.tick:05d}] receive response cmd={current[0]:#x} "
                f"data={current[1]:#018x} "
                f"user={current[2]:#x} "
                f"state={get(self.dut._debug_state)} "
                f"after_first={get(self.dut._debug_after_first)} "
                f"already_out={get(self.dut._debug_already_out)} "
                f"s3_valid={get(self.dut._debug_s3_valid)}"
            )
            await RisingEdge(self.dut.clock)
            break
        assert response is not None, (
            f"response timeout for addr={addr:#x} cmd={cmd:#x}; "
            f"req_ready={get(self.dut.io_in_req_ready)} "
            f"resp_valid={get(self.dut.io_in_resp_valid)} "
            f"mem_req_valid={get(self.dut.io_out_mem_req_valid)} "
            f"mem_resp_valid={get(self.dut.io_out_mem_resp_valid)} "
            f"accepted_tick={accepted_tick}"
        )
        assert response[2] == user, (
            f"response user mismatch: sent={user:#x}, received={response[2]:#x}"
        )
        self.transactions += 1
        return response

    async def read(self, addr: int, **kwargs) -> int:
        cmd, data, _ = await self.request(addr, CMD_READ, **kwargs)
        assert cmd == CMD_READ_LAST, f"read response command is {cmd:#x}"
        return data

    async def write(self, addr: int, data: int, mask: int = 0xFF, **kwargs) -> None:
        cmd, _, _ = await self.request(
            addr, CMD_WRITE, wdata=data, wmask=mask, **kwargs
        )
        assert cmd == CMD_WRITE_RESP, f"write response command is {cmd:#x}"


def initialize_inputs(dut) -> None:
    for signal in vars(dut).values():
        xdata = as_xdata(signal)
        if hasattr(xdata, "IsInIO") and xdata.IsInIO():
            xdata.AsImmWrite()
            xdata.Set(0)
    set_(dut.io_in_resp_ready, 1)
    set_(dut.io_out_mem_req_ready, 1)
    set_(dut.io_out_coh_resp_ready, 1)
    set_(dut.io_mmio_req_ready, 1)


async def reset_and_wait_ready(dut) -> None:
    set_(dut.reset, 1)
    await RisingEdge(dut.clock)
    await RisingEdge(dut.clock)
    await FallingEdge(dut.clock)
    set_(dut.reset, 0)
    async with asyncio.timeout(10):
        await Value(dut.io_in_req_ready, 1, sample=FallingEdge(dut.clock))


async def verify_cache(
    dut, execution, *, seed: int, random_ops: int
) -> tuple[dict[str, int], list[str]]:
    backing = ReferenceMemory()
    mmio_space = ReferenceMemory()
    interfaces = bind_cache_interfaces(dut)
    memory = MemoryModel(dut, backing, interfaces, response_gap=1)
    mmio = MmioModel(dut, mmio_space, interfaces)
    driver = CacheDriver(dut, interfaces)
    memory_request_interface = interfaces.memory_request.monitor_view()
    memory_request_bits = memory_request_interface.bits
    memory_request_monitor = ReadyValidMonitor(
        memory_request_interface,
        capacity=1024,
    ).start(execution)
    monitored_memory_requests = []

    async def collect_memory_requests() -> None:
        while True:
            monitored_memory_requests.append(
                await memory_request_monitor.recv()
            )

    monitor_task = asyncio.create_task(
        collect_memory_requests(), name="cache-memory-request-monitor"
    )
    protocol_issues: list[str] = []

    memory_task = asyncio.create_task(memory.run(), name="cache-memory-model")
    mmio_task = asyncio.create_task(mmio.run(), name="cache-mmio-model")
    try:
        await reset_and_wait_ready(dut)

        # Probe the early-demand-response overlap from a fixed, clean state so
        # random replacement history cannot affect reproduction.  Reset again
        # afterwards to keep it from contaminating the functional sequences.
        overlap_line = 0x0028_04C0
        assert await driver.read(overlap_line + 40) == backing.read(overlap_line + 40)
        try:
            await driver.read(overlap_line + 8, require_idle=False)
        except AssertionError as error:
            protocol_issues.append(
                "request accepted after an early miss response produced no "
                f"response: {error}"
            )
        await reset_and_wait_ready(dut)

        # 1. Cold miss at a nonzero beat, then all-word hit checks.  This proves
        # wrap refill ordering as well as line installation.
        line_a = 0x0000_1040
        demand = line_a + 5 * 8
        before = len(memory.read_bursts)
        assert await driver.read(demand) == backing.read(demand)
        assert memory.read_bursts[before:] == [demand]
        for index in range(WORDS_PER_LINE):
            addr = line_a + index * 8
            reads = len(memory.read_bursts)
            assert await driver.read(
                addr, response_stall_cycles=3 if index == 0 else 0
            ) == backing.read(addr)
            assert len(memory.read_bursts) == reads, f"refilled word {index} missed"

        # 2. Masked write hit and read-after-write.  Backing memory must remain
        # stale until eviction because the cache is write-back.
        hit_addr = line_a + 2 * 8
        old = backing.read(hit_addr)
        patch = 0x1122_3344_5566_7788
        mask = 0b0011_1100
        expected = merge_word(old, patch, mask)
        await driver.write(hit_addr, patch, mask)
        assert await driver.read(hit_addr) == expected
        assert backing.read(hit_addr) == old, "write hit unexpectedly wrote through"

        # 3. Write-allocate miss with a partial mask.
        line_b = 0x0000_28C0
        write_miss_addr = line_b + 7 * 8
        old_b = backing.read(write_miss_addr)
        patch_b = 0xDEAD_BEEF_0123_4567
        mask_b = 0b1010_0101
        expected_b = merge_word(old_b, patch_b, mask_b)
        reads = len(memory.read_bursts)
        await driver.write(write_miss_addr, patch_b, mask_b)
        assert len(memory.read_bursts) == reads + 1
        assert await driver.read(write_miss_addr) == expected_b
        assert backing.read(write_miss_addr) == old_b

        # 3b. Downstream request backpressure: a refill request must remain
        # valid with stable payload until memory raises ready.
        pressure_addr = 0x0000_5548
        set_(dut.io_out_mem_req_ready, 0)
        pressure_read = asyncio.create_task(driver.read(pressure_addr))
        await Value(
            dut.io_out_mem_req_valid,
            1,
            sample=FallingEdge(dut.clock),
        )
        held_request = (
            get(dut.io_out_mem_req_bits_addr),
            get(dut.io_out_mem_req_bits_cmd),
            get(dut.io_out_mem_req_bits_size),
            get(dut.io_out_mem_req_bits_wmask),
        )
        for _ in range(3):
            await RisingEdge(dut.clock)
            await FallingEdge(dut.clock)
            assert get(dut.io_out_mem_req_valid) == 1
            assert (
                get(dut.io_out_mem_req_bits_addr),
                get(dut.io_out_mem_req_bits_cmd),
                get(dut.io_out_mem_req_bits_size),
                get(dut.io_out_mem_req_bits_wmask),
            ) == held_request
        # Raise ready immediately after a rising edge so the memory-model task
        # observes it at the following falling sample before the handshake.
        await RisingEdge(dut.clock)
        set_(dut.io_out_mem_req_ready, 1)
        assert await pressure_read == backing.read(pressure_addr)

        # 4. Fill one set, dirty every way, then introduce a fifth tag.  The
        # replacement choice is internal, so identify the victim by writeback
        # address and verify the entire evicted line in backing memory.
        set_base = 0x0000_0180
        same_set_lines = [set_base + i * SAME_SET_STRIDE for i in range(5)]
        expected_dirty: dict[int, tuple[int, int]] = {}
        for i, line in enumerate(same_set_lines[:4]):
            assert await driver.read(line + 8) == backing.read(line + 8)
            addr = line + (i + 2) * 8
            value = 0xD100_0000_0000_0000 | (i << 16) | i
            await driver.write(addr, value)
            expected_dirty[line] = (addr, value)

        writebacks = len(memory.writebacks)
        assert await driver.read(same_set_lines[4] + 24) == backing.read(
            same_set_lines[4] + 24
        )
        assert len(memory.writebacks) == writebacks + 1, "dirty replacement did not write back"
        victim = memory.writebacks[-1]
        assert victim in expected_dirty, f"unexpected victim line {victim:#x}"
        victim_addr, victim_value = expected_dirty[victim]
        assert backing.read(victim_addr) == victim_value, "dirty victim data was not preserved"

        # 5. MMIO bypass for both reads and writes.
        mmio_addr = 0x3000_0040
        mmio_space.write(mmio_addr, 0xCAFE_BABE_8765_4321)
        mem_reqs = len(memory.requests)
        mmio_reqs = len(mmio.requests)
        assert await driver.read(mmio_addr) == mmio_space.read(mmio_addr)
        await driver.write(mmio_addr + 8, 0x1234_5678_9ABC_DEF0, 0xF3)
        assert mmio_space.read(mmio_addr + 8) == merge_word(
            mmio_space.default(mmio_addr + 8), 0x1234_5678_9ABC_DEF0, 0xF3
        )
        assert len(memory.requests) == mem_reqs, "MMIO request leaked to memory bus"
        # A repeated request is emitted only after the first response has
        # retired, so observe several additional cycles before counting.
        for _ in range(12):
            await FallingEdge(dut.clock)
        observed_mmio = len(mmio.requests) - mmio_reqs
        if observed_mmio != 2:
            protocol_issues.append(
                "two upstream MMIO transactions produced "
                f"{observed_mmio} downstream request handshakes"
            )

        # 6. Architectural randomized traffic.  Keep a logical reference model
        # separate from backing memory because dirty cache lines are not yet
        # externally visible.
        rng = random.Random(seed)
        logical: dict[int, int] = {}
        # Concentrate traffic into three sets with ten tags per set so random
        # traffic also exercises replacement and dirty writeback.
        random_lines = [
            0x0001_0000 + set_index * LINE_BYTES + tag * SAME_SET_STRIDE
            for set_index in range(3)
            for tag in range(10)
        ]
        for _ in range(random_ops):
            line = rng.choice(random_lines)
            addr = line + rng.randrange(WORDS_PER_LINE) * 8
            expected_old = logical.get(addr, backing.read(addr))
            if rng.random() < 0.55:
                got = await driver.read(addr)
                assert got == expected_old, (
                    f"random read mismatch addr={addr:#x}: got={got:#x}, expected={expected_old:#x}"
                )
            else:
                value = rng.getrandbits(64)
                mask = rng.randrange(1, 256)
                await driver.write(addr, value, mask)
                logical[addr] = merge_word(expected_old, value, mask)
                assert await driver.read(addr) == logical[addr]

        # io_empty describes the request pipeline, not dirty state.
        for _ in range(20):
            await FallingEdge(dut.clock)
            if get(dut.io_empty):
                break
        assert get(dut.io_empty) == 1

        for _ in range(100):
            if len(monitored_memory_requests) == len(memory.requests):
                break
            await asyncio.sleep(0)
        assert len(monitored_memory_requests) == len(memory.requests), (
            "memory request monitor lost a transfer: "
            f"model={len(memory.requests)}, "
            f"monitored={len(monitored_memory_requests)}"
        )
        monitored_payloads = [
            {
                name: transfer.value[name].as_int()
                for name in memory_request_bits
            }
            for transfer in monitored_memory_requests
        ]
        model_payloads = [
            {
                "addr": request.addr,
                "cmd": request.cmd,
                "size": request.size,
                "wmask": request.wmask,
                "wdata": request.wdata,
            }
            for request in memory.requests
        ]
        assert monitored_payloads == model_payloads, (
            "memory request monitor snapshots differ from model observations"
        )

        summary = {
            "transactions": driver.transactions,
            "memory_requests": len(memory.requests),
            "read_bursts": len(memory.read_bursts),
            "writebacks": len(memory.writebacks),
            "mmio_requests": len(mmio.requests),
            "seed": seed,
        }
        return summary, protocol_issues
    finally:
        driver.request_driver.close()
        monitor_task.cancel()
        await memory_request_monitor.aclose()
        memory_task.cancel()
        mmio_task.cancel()
        await asyncio.gather(
            monitor_task,
            memory_task,
            mmio_task,
            return_exceptions=True,
        )


async def main(seed: int, random_ops: int, *, allow_known_bugs: bool) -> None:
    dut = DUTCacheSignalCFG()
    dut.InitClock("clock")
    initialize_inputs(dut)
    dut._debug_state = dut.GetInternalSignal("CacheSignalCFG_top.Cache.s3.state")
    dut._debug_after_first = dut.GetInternalSignal(
        "CacheSignalCFG_top.Cache.s3.afterFirstRead"
    )
    dut._debug_already_out = dut.GetInternalSignal(
        "CacheSignalCFG_top.Cache.s3.alreadyOutFire"
    )
    dut._debug_s3_valid = dut.GetInternalSignal(
        "CacheSignalCFG_top.Cache.valid_1"
    )
    assert all(
        signal is not None
        for signal in (
            dut._debug_state,
            dut._debug_after_first,
            dut._debug_already_out,
            dut._debug_s3_valid,
        )
    )

    clock = dut.GetXClock()
    xspcomm = importlib.import_module(type(clock).__module__)
    assert (
        as_xdata(dut.io_in_req_ready).GetBackendKind()
        == xspcomm.XDataBackendKind_MemDirect
    ), "verification must use memory-direct XData"

    try:
        backend = XCommClockBackend(clock)
        async with Execution(backend, max_batch_ticks=256) as execution:
            async with asyncio.timeout(60):
                summary, protocol_issues = await verify_cache(
                    dut,
                    execution,
                    seed=seed,
                    random_ops=random_ops,
                )
        print("Cache functional verification completed:", summary)
        if protocol_issues:
            print("Cache protocol defects detected:")
            for issue in protocol_issues:
                print(f"  - {issue}")
            if not allow_known_bugs:
                raise AssertionError(
                    f"detected {len(protocol_issues)} Cache protocol defect(s)"
                )
        else:
            print("No protocol defects detected")
    finally:
        dut.Finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=0xCACE)
    parser.add_argument("--random-ops", type=int, default=80)
    parser.add_argument(
        "--allow-known-bugs",
        action="store_true",
        help="report known DUT protocol failures without returning failure",
    )
    args = parser.parse_args()
    asyncio.run(
        main(args.seed, args.random_ops, allow_known_bugs=args.allow_known_bugs)
    )
