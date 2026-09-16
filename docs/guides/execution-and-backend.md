# Execution 与 Backend

`Execution` 是一个测试的运行作用域，负责注册 Trigger、推进仿真和分发事件。

```python
async with Execution(
    backend,
    default_sample=RisingEdge(dut.clock),
):
    await RisingEdge(dut.clock)
```

退出 `Execution` 时，当前测试注册的 watcher、subscription 和编译缓存会被清理。
Backend 与 DUT 状态继续保留。

## Backend 的创建与关闭

```python
backend = XCommClockBackend(dut.GetXClock())
try:
    async with Execution(backend):
        ...
finally:
    backend.close()
```

`Execution` 不关闭 Backend。创建 Backend 的代码负责调用 `close()`。

## 在 pytest 中复用 Backend

```python
import pytest

from xreactor import Execution, XCommClockBackend


@pytest.fixture(scope="session")
def backend(dut):
    backend = XCommClockBackend(dut.GetXClock())
    yield backend
    backend.close()


@pytest.mark.asyncio
async def test_a(backend):
    async with Execution(backend):
        ...


@pytest.mark.asyncio
async def test_b(backend):
    async with Execution(backend):
        ...
```

在多个 case 之间复用 Backend 时，时钟和 DUT 状态不会自动复位。需要确定初态的测试
应在进入 `Execution` 后执行 reset sequence。

## 调度参数

```python
Execution(
    backend,
    default_sample=RisingEdge(dut.clock),
    max_batch_ticks=4096,
    quantum_ms=10.0,
    budget_check_interval=64,
)
```

| 参数 | 含义 |
| --- | --- |
| `default_sample` | `Value` 和编译条件的默认采样 Trigger |
| `max_batch_ticks` | 单次 Backend 调用最多推进的 half ticks |
| `quantum_ms` | 单次连续推进的 wall-clock 时间上限 |
| `budget_check_interval` | native 执行器检查时间预算的间隔 |

同一 Backend 同一时间只能属于一个 active `Execution`。
