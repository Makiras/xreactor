# 编译条件、Sequence、FSM 与订阅

## `@xtrigger`

`@xtrigger` 把受支持的表达式转换为 IR，并由 `XCommClockBackend` 降低到 C++ trigger
engine：

```python
from xreactor import RisingEdge, xtrigger


@xtrigger(sample=RisingEdge("clk"))
def handshake(dut):
    return dut.valid & dut.ready & ~dut.flush


event = await handshake(dut)
```

布尔组合必须使用 `&`、`|`、`~`，不能使用 Python `and`、`or`、`not`。支持信号、
无符号常量和比较表达式；位宽检查发生在 arm/lowering 阶段。

装饰器只声明规格，调用 `handshake(dut)` 才生成绑定 DUT 的 Trigger。`sample` 可以写
真实 phase trigger，也可以像上例一样使用 DUT 属性路径字符串。

## `@pytrigger`

`@pytrigger` 用于调用 Python predicate：

```python
@pytrigger(sample=RisingEdge("clk"))
def model_accepts(dut):
    return reference_model.accept(int(dut.data.U()))
```

predicate 是同步函数，并在指定的 sample phase 执行。异步数据源使用
`QueueTrigger`、`AsyncioEventTrigger` 或 `TaskComplete`。

## 非重叠 Sequence

```python
@xtrigger(sample=RisingEdge("clk"))
def request_then_ack(dut):
    return Sequence(
        Wait(dut.req & ~dut.flush),
        Within(1, 8, dut.ack),
        Hold(dut.valid, cycles=2),
    )
```

- `Wait(expr)`：等待条件；
- `Within(min, max, expr)`：在周期窗口中等待；
- `Hold(expr, cycles=N)`：要求连续保持 N 个 sample；
- 当前 Sequence 是非重叠匹配，一个 registration 维护一个活动状态。

## 显式 FSM

```python
@xtrigger(sample=RisingEdge("clk"))
def request_fsm(dut):
    return FSM(
        start="WAIT_REQ",
        states={
            "WAIT_REQ": State().when(dut.req).goto("WAIT_ACK"),
            "WAIT_ACK": State()
                .when(dut.flush).goto("WAIT_REQ")
                .when(dut.ack).trigger("ACK"),
        },
    )
```

同一 state 的分支按声明顺序判断。terminal trigger 产生 `FsmEvent`，terminal 名称位于
`event.terminal_state`。

## `@on` 持久订阅

```python
from xreactor import on


@on(handshake, delivery="lossless", capacity=64)
async def observe(event):
    scoreboard.push(event)


async with Execution(backend) as execution:
    subscription = execution.subscribe(observe.bind(dut))
    ...
```

`await trigger` 是 one-shot registration；`@on` 使用同一 Trigger 编译路径，但命中后
自动 rearm，并把结果送入 handler queue。

- `lossless`：队列满时显式失败；
- `latest`：队列满时丢弃旧项目，只保留新值；
- `capture=` 必须是同步函数，用于在命中 phase 立即制作不可变 snapshot；
- handler 必须是 `async def`。

Execution 退出时会取消并回收所有 subscription。
