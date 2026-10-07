# asyncio、pytest、HTTP 与线程

Execution 已接入 [asyncio 调度观察器](../architecture/asyncio-observer.md)：保留
宿主 asyncio 调度，通过观察本 Execution 的即时回调约束时钟推进。该页包含核心
代码、external_task 外部库包装示例及性能测量边界。

## asyncio 是宿主

核心规则：

- 使用 `asyncio.get_running_loop()`；
- Future 由当前 loop 的 `loop.create_future()` 创建；
- 核心 API 不调用 `asyncio.run()`；
- 不调用 loop.stop/close；
- 不覆盖全局 exception handler；
- 不扫描、识别或取消外部 Task；
- 只关闭框架自己创建的 Pump、handler 和 adapter task；
- 当前 Execution/XReactor 通过 contextvars 绑定。

同步 `run()` 只能作为“当前没有 running loop”时的便利入口；检测到已有 loop 时要求用户 `await`。

## pytest-asyncio

```python
@pytest_asyncio.fixture
async def dut():
    instance = DUTTop()
    async with Execution(instance) as sim:
        yield sim.dut

@pytest.mark.asyncio
async def test_request(dut):
    await ClockCycles(dut.xclock, 10)
```

Execution 退出不能关闭 pytest 创建的 loop，也不能取消 fixture/test 创建的其他 task。

## HTTP

HTTP 与 SimulationPump 可以共享一个 event loop：

```python
await asyncio.gather(
    run_driver(dut),
    serve_http(),
)
```

默认只要存在 active simulation Registration，仿真就继续推进。等待 HTTP 响应不隐式冻结 DUT。

需要冻结时显式写：

```python
async with sim.paused():
    response = await client.post("/configure")
```

Pump 用 wall-clock quantum 给 HTTP、公平取消和信号处理提供上界。不同策略可选择 foreground/cooperative，但都不能无限占用 loop。

当前回归测试使用真实 `asyncio.start_server`、HTTP 请求/延迟响应和并行
ClockCycles waiter，已验证等待响应不会冻结仿真，`sim.paused()` 才会冻结。
pytest-asyncio/aiohttp/FastAPI 的完整矩阵需要在安装这些依赖的 CI 环境继续跑；
当前开发环境没有这些可用发行包，因此不宣称已经覆盖。

## 外部异步源

外部 source 通过 adapter 变成 XTrigger：

- `AsyncioEventTrigger(event)`；
- `QueueTrigger(queue)`；
- `TaskComplete(task)`；
- 后续可扩展 stream/channel adapter。

```python
event = await AnyOf(
    handshake(dut),
    QueueTrigger(command_queue),
)
```

这些 trigger 在 asyncio 侧 arm，不进入 C++ evaluator。混合 AnyOf 由 XReactor 统一 winner 和 loser cancellation。

普通 asyncio.Event 只表示 occurrence，不携带 payload；需要数据时使用 Queue/channel。

## pytrigger 不是外部 I/O adapter

pytrigger 是在指定仿真 sampling phase 执行的同步 Python predicate。异步 HTTP/Queue 等待不应塞进 async pytrigger，否则无法明确它属于哪个仿真 phase。

## 多线程

多线程不是 asyncio 兼容的前提，而是 backend 调用过长时的优化：

```text
asyncio thread
  -> command queue
  -> simulator owner thread
  -> result queue / call_soon_threadsafe
  -> XReactor
```

规则：

- 同一 DUT facade 只有一个 owner；
- worker 不直接 set asyncio Future；
- signal access 与 Step/Finish 遵守同一线程协议；
- simulator kernel 内部可以多线程，但对外 phase barrier 必须原子；
- Python callback 不进入 backend worker 的热路径；
- close/cancel 必须能唤醒双方，不能互相等待形成死锁。

只有 profiling 证明单次 RunUntil 无法满足响应目标时，才引入 owner thread。

## 多 Execution

每个 Execution 有独立 XReactor、Pump、registry 和 context。首版允许同一 loop
中的多个 Execution 使用不同 backend instance；不承诺两个 Execution 共享同一
backend instance。`BackendCapabilities` 当前显式声明 half_step、stable_sample、
drive_stable、thread_safe、reentrant 和 multiple_instances；ReadWrite/ReadOnly/
NextTimeStep 不属于框架能力模型。Execution 启动时至少要求 half-step stable sampling，并通过 backend lease
主动拒绝共享同一 instance。
