# asyncio 与 pytest

XReactor 使用当前正在运行的 asyncio event loop，可以和 HTTP client/server、Queue、
Timer 以及其他异步任务同时运行。

## pytest

```python
import pytest

from xreactor import Execution, RisingEdge


@pytest.mark.asyncio
async def test_counter(backend, dut):
    async with Execution(backend):
        await RisingEdge(dut.clock)
        assert int(dut.count.U()) == 1
```

pytest-asyncio 已经创建 event loop，测试中直接使用 `await` 即可。

## 等待外部任务

普通 coroutine 可以直接等待：

```python
response = await http_client.get(url)
await RisingEdge(dut.clock)
```

需要同时等待 DUT 和外部事件时使用 `AnyOf`：

```python
event = await AnyOf(
    Value(dut.done, 1, sample=RisingEdge(dut.clock)),
    QueueTrigger(control_queue),
    WallTimeout(2.0),
)
```

仿真在存在 DUT Trigger 或 subscription 时推进。只等待 HTTP、Queue 或普通 Task 时，
仿真时间保持不变。

## 后台任务

```python
import asyncio
import contextlib

task = asyncio.create_task(run_reference_server())
try:
    async with Execution(backend):
        ...
finally:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
```

`Execution` 只管理自己创建的调度和 subscription task。测试创建的后台任务仍由测试
负责结束。

## 工作线程

阻塞函数可通过 `asyncio.to_thread()` 调用。Backend、XClock 和 DUT 信号应由运行
`Execution` 的线程访问；工作线程的结果可通过 asyncio Queue 或 Event 返回。
