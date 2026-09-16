# 快速开始

下面的测试在下降沿驱动请求，并在上升沿等待 `ready`：

```python
from xreactor import Execution, FallingEdge, RisingEdge, Value


async def test_request(backend, dut):
    async with Execution(
        backend,
        default_sample=RisingEdge(dut.clock),
    ):
        await FallingEdge(dut.clock)
        dut.req.Set(1)

        event = await Value(dut.ready, 1)
        assert event.source is dut.ready
```

`Execution` 启动仿真调度。`default_sample` 指定未显式填写 `sample=` 的条件在哪个
phase 采样。

## 创建 Backend

真实 DUT 使用 `XCommClockBackend`：

```python
from xreactor import XCommClockBackend

backend = XCommClockBackend(dut.GetXClock())
try:
    await test_request(backend, dut)
finally:
    backend.close()
```

Backend 可以由 pytest fixture 创建并在多个测试之间复用。每个测试使用独立的
`Execution`。

## 纯 Python 示例

仓库中的 [basic_execution.py](https://github.com/Makiras/xreactor/blob/main/examples/triggers/basic_execution.py) 使用
`MemoryBackend` 演示 edge、`Value` 和 `@xtrigger`：

```bash
PYTHONPATH=src python3 examples/triggers/basic_execution.py
```

接下来可阅读 [Trigger](../guides/triggers.md) 和
[Execution 与 Backend](../guides/execution-and-backend.md)。
