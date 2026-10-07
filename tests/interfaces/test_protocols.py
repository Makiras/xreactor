import asyncio
import unittest

from xreactor import (
    Bundle,
    ClockCycles,
    FallingEdge,
    MemoryBackend,
    Execution,
    XPhase,
    drive_ready_valid,
)


class Signal:
    def __init__(self, value=0):
        self.value = value


class RiseSignal:
    """Model a picker input whose Set is deferred until an explicit commit."""

    def __init__(self):
        self.value = 0
        self.pending = 0

    def Set(self, value):
        self.pending = value

    def IsRiseWrite(self):
        return True

    def WriteOnRise(self):
        self.value = self.pending

    def ImmSet(self, value):
        self.pending = self.value = value


class ProtocolHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_rise_write_valid_is_committed_and_withdrawn_at_acceptance(self):
        clock = object()
        valid = RiseSignal()
        payload = RiseSignal()
        gate = {"open": False}

        class Ready:
            @property
            def value(self):
                return int(gate["open"] and valid.value and payload.value == 0xA5)

        ready = Ready()
        rising_samples = []

        def on_phase(phase, tick):
            if phase is XPhase.FALLING_STABLE and tick == 5:
                gate["open"] = True
            if phase is XPhase.RISING_STABLE:
                rising_samples.append((tick, valid.value, ready.value, payload.value))

        backend = MemoryBackend(clock, on_phase=on_phase)

        def drive_payload():
            payload.Set(0xA5)

        async with Execution(backend):
            accepted = await drive_ready_valid(
                clock, valid, ready, drive_payload, bits=Bundle(data=payload)
            )
            await ClockCycles(clock, 2)

        self.assertEqual(accepted.tick, 6)
        self.assertEqual(rising_samples[:3], [
            (2, 1, 0, 0xA5),
            (4, 1, 0, 0xA5),
            (6, 1, 1, 0xA5),
        ])
        self.assertEqual(rising_samples[3:], [
            (8, 0, 0, 0xA5),
            (10, 0, 0, 0xA5),
        ])

    async def test_drive_from_current_falling_crosses_one_rising(self):
        clock = object()
        valid = Signal()
        ready = Signal(1)
        payload = Signal()
        rising_samples = []
        backend = MemoryBackend(
            clock,
            on_phase=lambda phase, tick: rising_samples.append(
                (tick, valid.value, ready.value, payload.value)
            )
            if phase is XPhase.RISING_STABLE
            else None,
        )

        async with Execution(backend):
            falling = await FallingEdge(clock)
            accepted = await drive_ready_valid(
                clock,
                valid,
                ready,
                lambda: setattr(payload, "value", 0x55),
            )

        self.assertEqual(falling.tick, 1)
        self.assertEqual(accepted.tick, 2)
        self.assertEqual(rising_samples, [(2, 1, 1, 0x55)])
        self.assertEqual(valid.value, 0)

    async def test_drive_holds_payload_across_backpressure(self):
        clock = object()
        valid = Signal()
        ready = Signal()
        payload = Signal()
        rising_samples = []

        def on_phase(phase, tick):
            if phase is XPhase.FALLING_STABLE and tick == 3:
                ready.value = 1
            if phase is XPhase.RISING_STABLE:
                rising_samples.append(
                    (tick, valid.value, ready.value, payload.value)
                )

        backend = MemoryBackend(clock, on_phase=on_phase)
        async with Execution(backend):
            accepted = await drive_ready_valid(
                clock,
                valid,
                ready,
                lambda: setattr(payload, "value", 0xA5),
            )

        self.assertEqual(accepted.tick, 4)
        self.assertEqual(
            rising_samples,
            [(2, 1, 0, 0xA5), (4, 1, 1, 0xA5)],
        )
        self.assertEqual(valid.value, 0)

    async def test_drive_requires_active_execution(self):
        with self.assertRaisesRegex(RuntimeError, "active Execution"):
            await drive_ready_valid(
                object(), Signal(), Signal(1), lambda: None
            )

    async def test_cancel_withdraws_valid(self):
        clock = object()
        valid = Signal()
        ready = Signal()
        backend = MemoryBackend(clock)
        async with Execution(backend):
            task = asyncio.create_task(
                drive_ready_valid(clock, valid, ready, lambda: None)
            )
            await FallingEdge(clock)
            await asyncio.sleep(0)
            self.assertEqual(valid.value, 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(valid.value, 0)

    async def test_cancel_withdraws_rise_written_valid(self):
        clock = object()
        valid = RiseSignal()
        ready = Signal(0)
        rising_samples = []
        backend = MemoryBackend(
            clock,
            on_phase=lambda phase, tick: rising_samples.append(valid.value)
            if phase is XPhase.RISING_STABLE else None,
        )
        async with Execution(backend):
            task = asyncio.create_task(
                drive_ready_valid(clock, valid, ready, lambda: None)
            )
            await FallingEdge(clock)
            await asyncio.sleep(0)
            self.assertEqual(valid.value, 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(valid.value, 0)
            await ClockCycles(clock, 2)
        self.assertEqual(rising_samples, [0, 0])

    async def test_async_drive_callback_is_rejected(self):
        clock = object()
        backend = MemoryBackend(clock)

        async def invalid_drive():
            return None

        async with Execution(backend):
            with self.assertRaisesRegex(TypeError, "must be synchronous"):
                await drive_ready_valid(
                    clock, Signal(), Signal(1), invalid_drive
                )


if __name__ == "__main__":
    unittest.main()
