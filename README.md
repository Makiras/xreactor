# XReactor

XReactor 是基于 `asyncio` 的 Python 硬件验证框架。测试协程可以直接等待时钟边沿、
信号条件、时序序列和外部异步事件。可编译的条件与状态机由 xcomm trigger engine
执行。

```python
from xreactor import Execution, FallingEdge, RisingEdge, Value


async def test_request(backend, dut):
    async with Execution(backend, default_sample=RisingEdge(dut.clock)):
        await FallingEdge(dut.clock)
        dut.req.Set(1)
        await Value(dut.ready, 1)
```

## 安装

```bash
python3 -m pip install -e .
```

开发与测试依赖：

```bash
python3 -m pip install -e '.[test]'
python3 -m pytest -q
```

真实 DUT 需要提供 xcomm/xspcomm 的 `XClock`、`XData` 和 `XTriggerEngine` Python
binding。纯 Python 示例使用 `MemoryBackend`，无需仿真器：

```bash
PYTHONPATH=src python3 examples/triggers/basic_execution.py
```

## 文档

- [安装](docs/getting-started/installation.md)
- [快速开始](docs/getting-started/first-test.md)
- [Trigger](docs/guides/triggers.md)
- [编译条件、Sequence 和 FSM](docs/guides/compiled-triggers.md)
- [Interface、Driver 和 Monitor](docs/guides/interfaces-and-components.md)
- [asyncio 与 pytest](docs/guides/asyncio-and-pytest.md)
- [Functional coverage](docs/guides/coverage.md)
- [API 索引](docs/reference/api.md)

完整目录见[用户手册](docs/index.md)。维护者设计记录位于 [design](design/README.md)。

本地预览文档：

```bash
python3 -m pip install -e '.[docs]'
mkdocs serve
```
