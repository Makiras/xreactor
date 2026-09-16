# FSM 与 Sequence

## 定位

复杂跨周期条件是 `@xtrigger` 的核心 fast path，而不是 pytrigger 的理由。

```python
@xtrigger(sample=RisingEdge("clk"))
def request_then_ack(dut):
    return Sequence(
        Wait(dut.req & ~dut.flush),
        Within(1, 8, dut.ack),
        Hold(dut.valid, cycles=2),
    )
```

Sequence builder 生成 FsmIR；运行时状态转移由 C++ ComUseFsmTrigger/XTriggerEngine 完成。

## 两种声明形式

线性协议使用 Sequence：

```python
Sequence(
    Wait(start),
    Within(1, 8, done),
    Hold(stable, cycles=2),
)
```

显式分支使用 FSM builder：

```python
FSM(
    start="WAIT_REQ",
    states={
        "WAIT_REQ": State().when(req).goto("WAIT_ACK"),
        "WAIT_ACK": State()
            .when(flush).goto("WAIT_REQ")
            .when(ack).trigger("MATCHED"),
    },
)
```

这些 builder 只描述状态、动作和转移，不在仿真期间执行 Python 控制流。

## 现有 xcomm 映射

ComUseFsmTrigger 已支持：

- 命名 state 和 start state；
- if/elif/else 条件转移；
- goto 和 trigger；
- flag/counter；
- ExprEngine 条件；
- Reset、Clear、当前状态和终态查询。

第一版可采用：

```text
Python builder -> FsmIR -> 现有 FSM program -> LoadProgram()
```

语义稳定后再提供直接的结构化 C++ `Arm(FsmIR)`，避免字符串成为长期 ABI。

## one-shot FSM

`await fsm_trigger` 创建一个运行实例。命中后产生 FsmEvent，至少包含：

- tick、cycle、phase；
- terminal state；
- 可选 captures、flags、counters；
- source trigger identity。

取消时先令 Registration closing，再 Disarm handle，最后销毁状态实例。generation 防止在途命中投递到新对象。

## persistent FSM：非重叠

第一版采用非重叠匹配：

```text
单一 active instance
  -> 到达 terminal state
  -> 当前 phase 完整事件广播
  -> reset
  -> 下一 sampling phase 开始下一轮
```

终态 phase 不同时作为下一轮起点。watcher 始终挂载，所以不存在 Python re-arm 空窗。handler 通过队列消费，处理速度不影响 FSM reset。

第一版不提供 overlapping instance。

## 状态共享

不可变编译程序可以共享；运行实例只允许在相同起始 phase、相同 reset policy 的 Registration cohort 中共享。

不同时间注册的 waiter 必须有独立实例：

```python
a = asyncio.create_task(sequence(dut)._wait())
await ClockCycles(clk, 3)
b = asyncio.create_task(sequence(dut)._wait())
```

`b` 不能继承 `a` 已经走过的状态。

## 超时与失败

Sequence 中的 Within 属于仿真时间约束，应在 C++ 通过 counter/deadline 判断。wall-clock timeout 属于 asyncio 侧。协议失败是否产生 FailureEvent 或仅保持等待，需要在具体 builder API 中明确，不能混同 backend error。
