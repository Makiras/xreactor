# 用户 API 草案

## 基本边沿与条件

```python
async with Execution(
    dut,
    default_sample=RisingEdge(dut.clk),
    quantum_ms=10,
) as sim:
    await ClockCycles(dut.clk, 10)

    await FallingEdge(dut.clk)
    dut.req.value = 1

    event = await Value(
        dut.ready,
        1,
        sample=RisingEdge(dut.clk),
    )

    # 使用 Execution 显式配置的 default_sample：
    event = await Value(dut.ready, 1)
```

`default_sample` 是显式配置，不允许框架猜测“当前时钟”。

Value、`@xtrigger` 与 `@pytrigger` 默认使用 `mode="enter"`。持久观察电平时可
显式使用 `mode="each_sample"`，同时观察进入/退出则使用 `mode="change"`。
即使注册时条件已经为真，初次命中也只发生在下一个指定 stable sample。

## 编译型表达式

```python
@xtrigger(sample=RisingEdge("clk"))
def handshake(dut):
    return dut.valid & dut.ready & ~dut.flush

event = await handshake(dut)
```

## Packed bus 结构视图

```python
entry = PackedLayout.struct({
    "valid": PackedLayout.bits(1),
    "tag": PackedLayout.bits(7),
    "payload": PackedLayout.array(2, PackedLayout.bits(32)),
})
entries = PackedView(dut.entries_bus, PackedLayout.array(4, entry))

entries[0].drive({
    "valid": 1,
    "tag": 3,
    "payload": [0x1122_3344, 0x5566_7788],
})
snapshot = entries[0].sample()
```

一维等宽场景继续使用更短的 `PackedArray(bus, element_width, count)`。两者都是 live
XData view，不复制 simulator storage，也不引入隐式采样 phase。

## 编译型 FSM

```python
@xtrigger(sample=RisingEdge("clk"))
def request_then_ack(dut):
    return Sequence(
        Wait(dut.req & ~dut.flush),
        Within(1, 8, dut.ack),
        Hold(dut.valid, cycles=2),
    )

event = await request_then_ack(dut)
assert event.terminal_state == "MATCHED"
```

## Python 最差路径

```python
@pytrigger(sample=RisingEdge("clk"))
def model_ready(dut):
    return reference_model.accept(dut.data.value)
```

它与 xtrigger 一样返回 XTrigger、接受取消并产生 XEvent，但每个 sampling phase 必须回到 Python。

## 组合与外部事件

```python
winner = await AnyOf(
    request_then_ack(dut),
    AsyncioEventTrigger(stop_event),
    SimTimeout(100, clock=dut.clk),
)
```

`AnyOf` 返回获胜子事件；`AllOf` 返回包含全部 causes 的组合事件。

## 持久订阅

```python
@on(request_then_ack, delivery="lossless")
async def observe(event: FsmEvent):
    scoreboard.push(event)

async with Execution(backend) as sim:
    subscription = sim.subscribe(observe.bind(dut))
```

当前孵化 API 使用显式 `bind(dut)` 和 `sim.subscribe(...)`，避免隐藏启动时机。
语义固定为：同一 Trigger 编译路径、persistent Registration、队列化 handler 和
显式 backpressure。

## Execution 与 Backend 生命周期

`Execution` 是一次测试的运行作用域，退出时总会调用
`backend.clear_execution_state()`；它不拥有也不会关闭传入的 backend。Backend 可以与
DUT/XClock 一起由 session fixture 复用，最终由其创建者显式关闭：

```python
@pytest.fixture(scope="session")
def backend(dut):
    instance = XCommClockBackend(dut.GetXClock())
    yield instance
    instance.close()


async def test_a(backend):
    async with Execution(backend):
        ...


async def test_b(backend):
    async with Execution(backend):
        ...
```

`clear_execution_state()` 只清除 trigger registration、未消费 hit、编译表达式缓存及其
native handle；它不执行 DUT functional reset，也不重置仿真时间。DUT 是否在
case 间复位由测试环境显式决定。
