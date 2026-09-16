# 基于 xcomm 的 XTrigger / XEvent / XReactor 异步仿真框架设计

> 本文保留完整源码核对、讨论背景和历史推导。正式的模块化设计文档已经迁移到 [XReactor 异步仿真框架文档目录](xreactor-framework/README.md)，后续设计更新优先修改新目录。

## 1. 文档目的

本文分析如何在 Picker/xcomm 现有能力上实现一套 Python 原生、兼容 asyncio、具有 cocotb 风格编程体验的仿真运行时，例如：

```python
await RisingEdge(dut.clk)
await ClockCycles(dut.clk, 10)
await Value(dut.ready, 1, sample=RisingEdge(dut.clk))

@xtrigger(sample=RisingEdge("clk"))
def ready(dut):
    return dut.valid & dut.ready

event = await ready(dut)
```

设计目标不是把 cocotb 或 Toffee 的调度器原样复制进来，而是：

1. 复用 xcomm 已有的时钟、条件表达式和 FSM 快速触发能力；
2. 使用调用者已有的 asyncio event loop，与 pytest-asyncio、aiohttp、FastAPI 等库共存；
3. 正常仿真时允许内核占据主要 CPU 时间，以仿真吞吐优先；
4. Trigger 命中、达到调度时间片或收到取消请求时，及时把控制权交还 asyncio；
5. 不扫描、修改或取消外部库创建的 asyncio Task；
6. 以 XClock 的 half-step stable contract 为唯一仿真 phase 边界，不复制 cocotb event-region API。

框架形态建议调整为：以 xcomm/ComUse 作为底层执行引擎，另建一个全新的 Python 验证框架仓库。Toffee 只作为需求和经验参考，不设 API 或行为兼容目标；Picker 只负责生成 DUT 和接入协议，不承载完整验证框架。

本文基于当前仓库中的实际代码核对，不假设 xcomm 尚未具备 Condition/FSM 能力。

## 2. 结论摘要

当前 xcomm 已经具备实现高性能 Trigger 的大部分底层能力：

- `XClock` 支持完整周期推进、上下沿 callback、Disable/Enable 和 C++ coroutine 调度；
- `ComUseCondCheck` 支持多条件比较、valid gating，并能在命中后停止绑定时钟；
- `ComUseExprCheck` 支持信号表达式树和字符串表达式，并能在命中后停止绑定时钟；
- `ComUseFsmTrigger` 支持跨周期 FSM、flag、counter 和 trigger；
- 上述类已经通过 SWIG 暴露给 Python；
- `XData::OnChange` 已具备值变化 callback 基础；
- Picker 生成的 DUT 已经暴露 `xclock`、`event`、`AStep()` 和 `ACondition()`。

第一阶段不需要重写 C++ Trigger/FSM，也不需要自定义 Python coroutine scheduler。主要工作是增加：

1. asyncio `Future` 与 xcomm fast-stop trigger 之间的桥接；
2. 一个不接管外部 asyncio Task 的 `XReactor`，以及内部 SimulationPump；
3. 可返回 typed XEvent 的 Python awaitable XTrigger；
4. fast path 与 Python predicate slow path 的统一注册、取消和超时机制；
5. 少量 C++ 语义修正和更安全的挂载接口。

实现原则应为 **ComUse-first**：结构化 Condition、表达式和跨周期序列优先映射到 `ComUseCondCheck`、`ComUseExprCheck` 和 `ComUseFsmTrigger`，Python lambda polling 只作为无法结构化表达时的兼容慢路径。

XEvent/XTrigger/XReactor 属于新 Python 框架；xcomm 负责统一 C++ XTriggerEngine、half-step、固定大小 BackendHit 和 RunResult，把 ComUse 当前的“记录命中状态 + Disable clock”收敛为“收集完整 phase hit set + 按原因停止推进”。

当前实现已经支持 Rising/Falling 半周期调度屏障，并能在边沿之间返回 Python。
`ReadWrite`/`ReadOnly`/delta-cycle 是 cocotb 被动适配自由运行 simulator 的概念；
XClock 已主动固定 pin update、eval、edge write、eval、refresh 顺序，因此不作为后续 capability。

## 3. 当前已有能力核对

### 3.1 XClock 的推进和 callback

相关代码：

- `dependence/xcomm/include/xspcomm/xclock.h`
- `dependence/xcomm/src/xclock.cpp`
- `dependence/xcomm/swig/python/xcomm.py`

C++ `XClock::Step(s)` 的实际流程是：

```text
for each cycle:
    检查 IsDisable()
    clk += 1
    执行一个下降沿和一个上升沿（顺序由 stop_on_rise 决定）
    调度 C++ coroutine awaiter
```

每个半周期内部包含：

```text
更新 clock pin
写入绑定 port
调用 simulator step/eval
刷新 port
执行 StepRis/StepFal callback
```

当前 callback 位于端口刷新之后。因此 `StepRis`/`StepFal` 更接近“边沿已经执行且相应端口已经刷新”，并不等价于 cocotb 中“边沿刚发生、下游 HDL 尚未完成求值”的严格语义。

需要澄清：这里的疑问不是 XClock 能否生成或识别 Rising/Falling edge。XClock 本身已经负责切换 clock pin，并通过 `_ris_ports()`/`_fal_ports()` 按 XData write mode 控制 Rise/Fall 写入时序；`StepRis`/`StepFal` 也已经提供明确 callback 点。真正的边界问题是：Python waiter 是否必须在下降沿完成后、同一个完整周期的上升沿执行前恢复。当前 `Step(1)` 连续执行两个半周期，且两个半周期之间不再次检查 `is_disable`，所以 falling callback 即使 Disable clock，本周期后续 rising half 仍会执行。

本文现在确定采用严格的调度屏障语义：`await FallingEdge(clk)` 恢复后，Python coroutine 必须能在下一上升沿推进前执行并驱动信号。因此仅报告 callback 不够，需要把 XClock 的半周期推进变成可暂停/恢复的稳定接口。Trigger 本身不负责写信号，它只定义 Python 恢复的调度边界；实际写入仍由用户代码、XData 和 Rise/Fall write mode 完成。

`XClock::Disable()` 会使当前 `Step(s)` 在下一轮循环入口提前返回。它是现有 fast-stop 机制的关键。

### 3.2 C++ coroutine 与 Python asyncio 是两套机制

相关代码：

- `dependence/xcomm/include/xspcomm/xcoroutine.h`
- `dependence/xcomm/src/xcoroutine.cpp`
- `dependence/xcomm/src/xclock.cpp`

C++ 中存在：

```cpp
XStep XClock::AStep(int i);
XCondition XClock::ACondition(std::function<bool(void)> checker);
XNext XClock::ANext(int n);
```

这些对象服务于 C++20 coroutine，由 `XClock::_shchedule_await()` 在每个完整周期末尾调度。

Python 中同名方法在 `swig/python/xcomm.py` 中被覆盖为 asyncio coroutine：

```python
async def XClock_AStep(self, cycle): ...
async def XClock_ACondition(self, condition): ...
async def XClock_ANext(self): ...
```

因此不能把 C++ `XCondition` 直接视作 Python asyncio Trigger。新的设计需要明确区分：

- C++ coroutine awaiter；
- C++ fast-stop checker/FSM；
- Python asyncio awaitable Trigger。

三者可以共享底层时钟，但生命周期和唤醒协议不同。

### 3.3 ComUseCondCheck

相关代码：

- `dependence/xcomm/include/xspcomm/xcomuse_base.h`
- `dependence/xcomm/src/xcomuse_base.cpp`

已有能力：

- `EQ/NE/GT/GE/LT/LE`；
- `XData` 对 `XData` 比较；
- 原始内存地址比较；
- valid/value gating；
- 多个命名条件；
- `GetTriggeredConditionKeys()`；
- 命中任一条件后 Disable 所有绑定 clock。

它不是自动绑定到 XClock 的。下面两步含义不同：

```cpp
ComUseCondCheck checker(&clk);  // 声明命中后需要停止 clk
clk.StepRis(checker.GetCb(), checker.CSelf(), "cond-check"); // 真正注册检查 callback
```

已用本地 Python 产物验证：两个条件在同一周期为真时，`ComUseCondCheck` 会返回两个 key。

适用场景：简单信号比较、valid/data 组合条件，以及可以结构化描述的高频检查。

### 3.4 ComUseExprCheck

相关代码：

- `dependence/xcomm/include/xspcomm/xexpr.h`
- `dependence/xcomm/src/xexpr_engine.cpp`
- `dependence/xcomm/src/xexpr_parser.cpp`

已有能力：

- 常量、信号、单目、双目和比较节点；
- signal/signal、signal/constant 快速比较；
- 逻辑短路顺序优化；
- 字符串表达式编译；
- 多个命名表达式；
- cycle 状态；
- 命中后 Disable 绑定 clock。

它非常适合承载 Python 侧的结构化 Condition：

```python
await Value(dut.ready, 1, sample=RisingEdge(dut.clk))
await Condition(
    (dut.valid == 1) & (dut.ready == 1),
    sample=RisingEdge(dut.clk),
)
```

但当前实现存在一个重要语义限制：`ComUseExprCheck::Call()` 在第一个表达式命中后立即 `break`。这意味着：

1. 同周期多个表达式为真时只报告第一个；
2. 如果第一个表达式持续为真而桥接层不先删除它，后面的表达式可能一直得不到报告；
3. 这不符合 asyncio/cocotb 中“同一事件唤醒所有匹配 waiter”的直觉语义。

已用本地 Python 产物验证：注册两个恒真的表达式时，每次只返回第一个 key。

建议在 asyncio bridge 落地前做一个很小的 C++ 修正：遍历并记录本周期全部命中表达式，只在第一次命中时执行 Disable/计数，但不要 `break`。

另一个生命周期问题是：`RemoveExpr()` 只移除表达式条目，不回收 `ExprEngine` 中已经创建的节点。大量动态创建/取消 Trigger 时可能导致节点长期增长。第一版至少应在 checker 没有 active expression 时 `ClearExpr()`；长期方案需要表达式节点所有权、缓存或回收策略。

### 3.5 ComUseFsmTrigger

相关代码：

- `dependence/xcomm/include/xspcomm/xfsm.h`
- `dependence/xcomm/src/xfsm_trigger.cpp`

已有能力：

- 命名 state 和 start state；
- `if`/`elif`/`else`；
- `goto` 和 `trigger`；
- `$flag*` 和 `$counter*`；
- 使用 ExprEngine 判断转移；
- trigger 状态保持；
- 命中后 Disable 绑定 clocks；
- `GetTriggeredState()` 和 `GetCurrentState()`。

它适合实现跨周期序列等待：

```python
await FSMTrigger("""
    state WAIT_VALID:
      if valid == 1 goto WAIT_READY

    state WAIT_READY:
      if ready == 1 trigger
""")
```

与 Cond/Expr checker 一样，构造时传入 clock 只表示“触发后停止哪些 clock”；还需要把 `GetCb()/CSelf()` 挂到相应边沿 callback。

FSM trigger 后保持 `triggered=True`，重用时需要：

1. `Reset()` FSM；
2. `Enable()` 被停止的 clocks；
3. 确保 callback 本身仍有效；
4. cancellation/销毁前从 XClock 移除 callback，避免 `CSelf()` 悬空。

### 3.6 XData::OnChange

相关代码：

- `dependence/xcomm/include/xspcomm/xdata.h`
- `dependence/xcomm/src/xdata.cpp`

`XData` 已经保存 on-change callback 列表，并在 shadow value 变化时调用 callback。回调可以区分当前值是否包含 X/Z，并得到当前数据。

这为 `ValueChange`、`RisingEdge` 和 `FallingEdge` 提供了底层基础，但当前仍有几个问题：

- Python 层没有与 `StepRis/StepFal` 同等易用的 OnChange callback 包装；
- callback 发生于 XData 刷新流程中，具体 phase 语义需要固定；
- callback 内不能直接执行异步 Python coroutine；
- 如果仿真在 worker 线程运行，callback 不能直接操作 asyncio Future，必须回送 event loop。

MVP 中 clock edge 由 XClock half-step phase source 提供；`XData::OnChange` 用于后续 `ValueChange`，并必须接入同一个 post-refresh sampling hook，不能用逐周期 Python snapshot 代替。

### 3.7 SWIG/Python 暴露情况

`dependence/xcomm/swig/xcomm.i` 已包含：

```text
xclock.h
xdata.h
xcomuse_base.h
xexpr.h
xfsm.h
```

当前构建产物已经能从 Python 访问：

```text
ComUseStepCb
ComUseCondCheck
ComUseExprCheck
ComUseFsmTrigger
ExprEngine
```

所以第一版 bridge 无需先补一套全新的 SWIG 类型系统。更需要的是面向 Python 的安全封装，隐藏 `GetCb()`、`CSelf()`、手工 desc 和裸对象生命周期。

## 4. 当前 Python asyncio 流程及问题

当前 `dependence/xcomm/swig/python/xcomm.py` 的主要流程为：

```text
RunStep(cycle)
    for every cycle:
        tick_clock_ready()
            扫描 asyncio.all_tasks()
            通过 Task repr 判断是否为 RunStep/wait_for
            等待“其他任务静止”
        Step(1)
            RawStep(1)
            _step_event.set()/clear()
        asyncio.sleep(0)
```

存在以下问题：

1. `asyncio.all_tasks()` 包含 pytest、HTTP server 和用户库的任务；
2. 通过 Task `repr` 和名字识别内部任务不稳定；
3. Toffee 使用的 `_fut_waiter` 类似做法也依赖 asyncio 私有实现；
4. `timestamp` 是模块全局变量，不适合多个 XClock/Execution；
5. `Event/Queue/sleep` 需要主动修改全局 timestamp 才能影响推进；
6. 框架无法区分仿真任务和无关外部任务；
7. 每个 ACondition 都会每周期唤醒一次 Python Task；
8. `RunStep(cycle)` 是有限循环，不适合作为由 active Trigger 驱动的长期 kernel；
9. 同步 `Step()` 和异步 `RunStep()` 可以同时推进同一 XClock，缺少单一 owner 约束。

另一个容易忽略的问题是 Python `XClock.Step(n)` 当前实现为：

```python
for _ in range(n):
    RawStep(1)
    _step_event.set()
    _step_event.clear()
```

如果 C++ checker 在第一个周期调用 `Disable()`：

- 后续 `RawStep(1)` 都会立即 no-op；
- Python 循环仍然继续执行剩余次数；
- `_step_event` 仍然会被重复 set/clear；
- `clk` 不再增长，但 Python waiter 可能收到假的“周期事件”；
- C++ fast-stop 的批量性能优势完全丢失。

因此当前高速原型必须调用一次 `RawStep(batch)`，由 C++ 循环在触发后提前退出，而不是调用 Python `Step(batch)`。正式接口再将它收敛为返回 RunResult 的 `RunUntil(limit)`。返回后统一检查 callback exception、实际 tick 增量和命中集合。

`RawStep()` 是 C++ 原始方法的 Python 别名，它不会执行 Python `Step()` 包装层中的 `_step_event.set()/clear()`。因此 SimulationPump 切换到统一 `RunUntil` 后，现有基于 `_step_event` 的 `AStep/ACondition/ANext` 不会自动被唤醒。兼容层必须改为向 XReactor 注册 waiter，并由 XReactor 根据 BackendHit 派发真实周期事件；不能同时保留旧 event 路径并假设它仍然有效。

此外，当前 `XClock_Check_Exceptions(self)` 是模块级 Python helper，并没有安装为 `XClock.CheckExceptions` 方法。新 runtime 应将其变成稳定方法或内部 API，确保每次 `RunUntil(limit)` 返回后都检查 callback exception。

## 5. 建议架构

### 5.1 分层

```text
用户验证代码
  await RisingEdge / Condition / FSMTrigger
  asyncio.gather / pytest / HTTP
                    │
Python Trigger API  │  不可变等待规格、组合与参数校验
                    │
XReactor            │  Registration、Future、分发、取消、订阅
                    │
SimulationPump      │  half-step、batch、quantum、协作式 yield
                    │
ClockDomain/XClock  │  phase source 与 backend 时钟控制
                    │
xcomm C++           │  XTriggerEngine、Expr/FSM、BackendHit、fast-stop
                    │
Simulator backend   │  Verilator / VCS / UVS / GSim
```

建议职责：

- `Execution` 聚合资源生命周期，但不拥有宿主 asyncio loop；
- `XReactor` 管 Registration、事件分发、组合触发器和订阅；
- 内部 `SimulationPump` 管仿真推进、公平性和多个 clock domain；
- xcomm C++ 的 `XTriggerEngine` 在单次 batch 内高速求值，并在命中或屏障处停止；
- Picker 生成的 DUT 只负责创建/暴露稳定的 runtime 入口，不内嵌复杂调度算法。

### 5.2 asyncio 是宿主调度器

不实现手工 `coroutine.send()` scheduler。所有 Python Task 仍由 asyncio 管理：

```text
pytest Task
HTTP Task
driver/monitor Task
SimulationPump Task
```

框架遵守以下规则：

- 使用 `asyncio.get_running_loop()`；
- 核心异步 API 不调用 `asyncio.run()`；
- 不调用 `loop.stop()` 或 `loop.close()`；
- 不覆盖全局 exception handler；
- 不向 event loop 对象写自定义属性；
- 不遍历、识别或取消外部 Task；
- 只保存并关闭自己创建的 task/future；
- 同步 `run()` 只能是“当前无 running loop”时的便利包装。

### 5.3 Trigger 是 Future-backed awaitable

建议基类：

```python
class XTrigger(Generic[E]):
    def __await__(self):
        return self._wait().__await__()

    async def _wait(self) -> E:
        registration = current_reactor().register(self, mode="oneshot")
        try:
            return await registration.future
        finally:
            registration.cancel()
```

XTrigger 不直接操作 clock；XReactor 创建 Future/Registration，并将可编译部分 arm 到对应 XTriggerEngine。

XTrigger 是可重用规格对象，每次 await 创建独立 one-shot Registration；Registration 本身不可重用。

### 5.4 两类 Condition

#### Fast path：结构化条件

```python
await Value(dut.ready, 1, sample=RisingEdge(dut.clk))
await Condition(
    (dut.valid == 1) & (dut.ready == 1),
    sample=RisingEdge(dut.clk),
)
await Sequence(program, sample=RisingEdge(dut.clk))
```

映射到：

- `ComUseCondCheck`；
- `ComUseExprCheck`；
- `ComUseFsmTrigger`。

这些条件在 C++ callback 中检查，能够配合 `RawStep(batch)` 提前停止。

#### Slow path：任意 Python predicate

```python
await Condition(
    lambda: reference_model.ready_for(dut.output.value),
    sample=RisingEdge(dut.clk),
)
```

任意 Python 逻辑无法安全下沉到 ExprEngine。SimulationPump 必须在每个指定采样点返回 Python 检查，因此 batch 通常被限制为一个采样周期。

不建议让 C++ simulator callback 每周期反向调用任意 Python lambda：这会增加 SWIG/GIL 开销，并在未来 worker-thread 模式下引入回调线程和死锁问题。

### 5.5 ComUse-first 的执行模型

新框架不应在 Python 中重复实现一套主要 Condition/FSM 引擎。建议把等待规格分为：

```text
Value/Compare/All/Any       -> ComUseCondCheck 或 ComUseExprCheck
字符串/结构化表达式          -> ComUseExprCheck
跨周期序列                  -> ComUseFsmTrigger
任意 Python callable        -> Python slow path
纯 asyncio Event/Queue      -> asyncio 自身，不进入 ComUse
```

正常高速路径为：

```text
Python 构造 XTrigger 规格
    -> XReactor 编译并注册到 XTriggerEngine
    -> SimulationPump 调用 RunUntil(limit)
    -> Cond/Expr/FSM evaluator 在 C++ sampling hook 中求值
    -> 命中后收集 BackendHit 并按 stop reason 返回
    -> XReactor 构造 XEvent 并完成 Future
```

这样 ComUse 是执行和优化中心，Python framework 是生命周期、组合 API 和 asyncio 适配层。

### 5.6 建议沉淀 XEvent/XTrigger

现有 ComUse 已有 trigger 的实质能力，但各类型通过不同查询接口暴露结果：

```text
ComUseCondCheck::GetTriggeredConditionKeys()
ComUseExprCheck::GetTriggeredExprKeys()
ComUseFsmTrigger::IsTriggered()/GetTriggeredState()
XData::OnChange callback
XClock StepRis/StepFal callback
```

这里需要区分四层对象：

```text
XTrigger          上层用户提交的等待规格：等待什么
Registration      XReactor 内部的一次等待/订阅：谁正在等、如何取消
BackendHit         xcomm/ComUse 输出的轻量命中记录
XEvent            上层已经发生的统一结果：何时、何处、发生了什么
```

`XTrigger` 是不可变、可复用的描述对象。每次执行 `await trigger` 都创建独立的一次性 Registration，因此同一个 Trigger 可以被多个 task 同时等待；取消其中一个 task 不会改变 Trigger，也不会取消其他订阅。ComUse checker/FSM 和 clock callback 是 Trigger 编译后的 backend watcher，不直接暴露为 Python Future。

`XEvent` 是上层统一结果，不是类似 `asyncio.Event` 的可等待同步原语。底层 ComUse、clock callback 和 ValueChange 先产生 BackendHit；XReactor 将其规范化为 XEvent，再把同一个事件广播给所有匹配的 Registration。关系如下：

```text
XTrigger --await--> Registration --compile--> ComUse/clock watcher
                                                |
                                                v
                                      BackendHit/phase stop
                                                |
                                                v
                                  normalize into XEvent
                                                |
                           +--------------------+--------------------+
                           v                    v                    v
                     waiter Future A      waiter Future B      monitor/subscriber
```

因此常规 API 是 `event = await trigger`。Trigger 决定匹配规则和推进策略，Event 只陈述一次事实；fast-stop 属于 Registration/SimulationPump 的执行策略，不属于 Event。

#### 5.6.1 await 实际等待什么

公开语法虽然是 `event = await trigger`，但 asyncio 实际等待的是本次 Registration 持有的 Future：

```python
class XTrigger(Generic[E]):
    def __await__(self):
        return self._wait().__await__()

    async def _wait(self) -> E:
        reg = current_reactor().register(self, mode="oneshot")
        try:
            return await reg.future
        finally:
            reg.cancel()
```

完整关系为：

```text
XEventSource/phase
    -> XTrigger matcher
    -> Registration
    -> asyncio.Future[XEvent]
    -> awaiting Task
```

因此：

- wait 的对象在用户层是 XTrigger，在 asyncio 内核层是 Future；
- 唤醒条件是 BackendHit 匹配 Registration；
- C++ 到 Python 传输 BackendHit；
- Future 的 result 和 `@on` handler 收到的对象都是 XEvent；
- XEvent 是已经发生的事实，本身不负责注册或等待。

Trigger 可以使用其他 Trigger 作为事件源。例如：

```python
Condition(expr, sample=RisingEdge(clk))
```

语义上是由 RisingEdge phase event 驱动的过滤器；C++ 编译器会将其融合为附着在对应 clock/phase 的 watcher，不需要每周期在 Python 创建中间 RisingEdge XEvent。只有最终 Condition 命中时才物化上层 XEvent。

外部异步源也可通过 adapter 转成 XTrigger：

```python
await AnyOf(
    RisingEdge(clk),
    AsyncioEventTrigger(stop_event),
)
```

`AsyncioEventTrigger` 由 asyncio 侧 Registration 驱动，不进入 C++ evaluator；混合 AnyOf 在 XReactor 中统一竞争、取消 loser。普通 asyncio.Event 不携带 payload，Queue/channel adapter 才负责传输外部数据。

#### 5.6.2 XReactor：注册与事件分发运行时

建议引入每个 Execution 独立的 `XReactor`，补足 Trigger 规格与 Event 结果之间的活跃运行时：

```text
XTrigger        等待/匹配规格，尽量不可变
XEvent          一次已发生的不可变结果
XReactor        arm、wait、publish、dispatch、cancel
XTriggerEngine  C++ phase 热路径求值
SimulationPump  仿真时间和 half-step 推进
```

调用链为：

```text
Task await XTrigger
    -> XReactor 创建 Registration/Future
    -> 编译并 arm 到 XTriggerEngine
    -> SimulationPump 调用 RunUntil
    -> XTriggerEngine 返回 BackendHit[]
    -> XReactor 规范化 XEvent 并广播
    -> Future/@on subscriber 恢复
```

XReactor 负责：

- `registration_id -> Future/subscriber`；
- Trigger 编译缓存与共享 watcher 引用计数；
- one-shot wait 和 persistent `@on`；
- AnyOf/AllOf 的 winner、聚合和原子取消；
- BackendHit 到 typed XEvent 的转换与同 phase 广播；
- asyncio Event/Queue/Task 等外部 source adapter；
- cancellation、exception、backpressure 和关闭清理。

XReactor 不负责：

- 不拥有、停止或关闭 asyncio loop；
- 不执行 simulator eval；
- 不在 C++ 每周期路径中运行 Python；
- 不自行推进 clock/time；
- 不成为进程全局 singleton。

SimulationPump 与 XReactor 应保持分离：Pump 决定“推进到哪里并何时 yield”，Reactor 决定“谁在等、命中了什么、把结果交给谁”。二者由 Execution 聚合，并通过 `contextvars` 暴露当前 Reactor，使 `await trigger` 不需要保存全局 loop。

MVP 直接在 xcomm 定义与 Python 无关的 C++ BackendHit record；现有各类 ComUse 可以先作为 `XTriggerEngine` 的实现来源，但不能让 Python 分别轮询它们。概念接口可以是：

```cpp
enum class XHitKind {
    ClockRise,
    ClockFall,
    ValueChange,
    Condition,
    Expression,
    Fsm,
    Timeout,
    BackendStop,
};

struct XBackendHit {
    uint64_t event_id;
    uint64_t tick;
    uint64_t source_id;
    uint64_t value;
    uint32_t slot;
    uint32_t generation;
    XHitKind kind;
    XPhase phase;
    uint16_t flags;
};

struct XRunResult {
    uint64_t advanced_cycles;
    bool stopped;
    std::vector<XBackendHit> hits;
};
```

由于下降沿和上升沿可能属于同一个完整 cycle，`cycle` 本身不足以排序，BackendHit 和 XEvent 的时间至少需要 `(cycle, phase)`，或者统一使用单调递增的 `half_step/tick`。公开 XEvent 可以额外包含组合事件的 `causes`，但不应泄露 ComUse checker 指针或 Registration token。

Python 侧：

```python
event = await trigger
assert event.kind is XEventKind.CONDITION
assert event.cycle == dut.xclock.clk
```

设计要求：

- Event 使用唯一、单调 id；Registration 使用独立 id 和 generation，避免取消后迟到命中被错误投递；
- 同一 phase 全部命中事件一次返回，满足广播语义；
- cancellation 使用 registration token，不暴露裸 `CSelf()`；
- XEvent 不持有 Python object 或 asyncio Future；
- XReactor 维护 `registration_id -> Future/subscriber` 和 watcher 到 Registration 的索引；
- fast-stop 是 Trigger/Registration 的推进策略，不应与事件本身绑定；
- 多个 waiter 匹配同一底层 occurrence 时收到相同 event identity，而不是竞争消费；
- `AnyOf` 返回首先命中的子事件，`AllOf` 返回包含全部子事件的组合 XEvent；
- 保留现有 Disable/query API，保证向后兼容；
- 最终可提供 `RawStepUntilEvent(max_cycles)` 或等价接口，减少 Python 对各类 ComUse 的分别查询。

第一版可不重写全部 ComUse 求值器，但必须先提供统一的 BackendHit/RunResult 和带 generation 的安全 registration handle；Python 只消费统一结果。

### 5.7 Python 装饰器：只负责声明和编译

已确认第一版使用可重载的 `& | ~` 构造符号表达式。装饰器不能把任意 Python 函数自动变成高速 C trigger，需要明确区分快速声明和慢速 predicate：

```python
@xtrigger(sample=RisingEdge("clk"))
def handshake(dut):
    return (dut.valid == 1) & (dut.ready == 1)

@pytrigger(sample=RisingEdge("clk"))
def reference_ready(dut):
    return reference_model.ready(dut)
```

`@xtrigger` 在首次 bind/arm 时用 symbolic DUT proxy 执行一次声明函数，生成与 Python 无关的 Trigger IR，随后编译到 Cond/Expr evaluator，并按 DUT schema、表达式结构、采样源和冻结参数缓存。逐 phase 求值不调用原 Python 函数。第一版只允许：

- DUT signal attribute；
- 整数/布尔常量和绑定时冻结的参数；
- `== != < <= > >=`；
- 可重载的 `& | ~` 和受限位运算；
- 括号及少量白名单函数。

`Expr.__bool__` 必须抛出带修复建议的异常，因此 Python `and/or/not`、链式比较和隐式 truth test 不会被错误编译。不支持的操作在注册时明确报错；需要 Python 控制流、任意函数或 reference model 时，用户显式选择 `@pytrigger` slow path，框架不得静默降级。

装饰器返回 Trigger factory/descriptor，而不是 coroutine：

```python
event = await handshake(dut)
```

`handshake(dut)` 只完成信号路径绑定、参数冻结和 XTrigger 构造；每次 await 再创建独立 Registration。装饰器 trace 和 IR 编译均不在逐 phase 热路径中。

建议装饰器分为：

```text
Trigger declaration:
    @xtrigger      统一入口；根据返回值编译 ExprIR 或 FsmIR
    @xsequence     可选可读性别名，仍返回 XTrigger
    @pytrigger     无法下沉时的显式 Python slow path

Task lifecycle:
    @process       随 Execution 启停的后台 coroutine
    @on(trigger)   持久消费 Trigger 命中
```

`@on(trigger)` 不建立新事件源。`await trigger` 创建 one-shot Registration；`@on(trigger)` 创建 `XSubscriptionSpec`，并在 Execution 启动时绑定为 persistent Registration。两者共享相同 XTrigger、编译缓存和底层 watcher。默认串行、lossless、有界队列；溢出时报错，UI/遥测消费者可显式选择 latest-only。

#### 5.7.1 `@xtrigger` 同时支持无状态表达式和有状态 FSM

`@xtrigger` 是统一的可编译 Trigger 入口，不等同于“只编译一个布尔表达式”。声明函数返回的符号对象决定编译目标：

```text
XExpr / XConditionSpec -> ExprIR -> Cond/Expr evaluator
XFsmSpec / XSequenceSpec -> FsmIR -> ComUseFsmTrigger evaluator
```

复杂跨周期协议仍使用 `@xtrigger`：

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

`Sequence/Wait/Within/Hold` 是声明期 builder，生成 FsmIR；不是逐周期运行的 Python coroutine。更复杂的分支、flag、counter 和显式状态可由 `FSM(...)` builder 表达。`@xsequence` 可以是强调时序意图的别名，但不能形成另一套 Trigger、Event 或调度系统。

现有 `ComUseFsmTrigger` 已具备 state、条件转移、trigger、flag、counter、`Reset()` 和 `Clear()`，并复用 ExprEngine。第一版可以先把 FsmIR 编译为现有 FSM program；状态转移始终留在 C++ sampling hook。

无状态表达式可以广泛共享 evaluator；状态型 Trigger 只能共享不可变编译程序。运行态 FSM instance 仅能由“同一启动 phase、同一 reset policy”的 Registration cohort 共享。启动时间不同的 await 必须有独立实例，不能继承已有状态。

第一版 persistent FSM 明确采用非重叠语义：每个 subscription/cohort 同时最多一个 active instance。终态命中后先完成当前 phase 的完整 BackendHit/XEvent 广播，再把该实例 reset；它从下一个 sampling phase 开始新一轮匹配，当前终态 phase 不会同时作为下一轮起点。底层 Registration/watcher 始终保持挂载，因此这是明确的匹配语义，不是 Python re-arm 空窗。handler 通过队列异步消费，是否处理完成不阻塞 FSM reset 和下一轮匹配。第一版不提供 overlapping instance。

所以 fast/slow 的边界是“能否编译为确定性的 ExprIR/FsmIR”，不是条件是否复杂。只有依赖任意 Python 对象、reference model、I/O、动态副作用或无法表达的控制流时，才使用 `@pytrigger`。

### 5.8 高效率 C++ TriggerEngine

长期形态建议在现有 ComUse 上增加一个按 clock domain/phase 集中的 `XTriggerEngine`，而不是为每个 Python waiter 安装一个 C++ callback：

```text
XClock phase callback
    -> XTriggerEngine::Evaluate(phase, tick)
        -> edge/deadline watcher
        -> flat condition slots
        -> ExprEngine roots
        -> FSM programs
        -> append POD BackendHit
        -> request phase stop
```

热路径要求：

- 一个 clock phase 尽量只有一个 engine callback；
- watcher 使用整数 `slot_id + generation`，字符串仅保留在 Python debug metadata；
- arm/disarm 只发生在两个仿真推进批次之间；
- active watcher 使用连续数组或可回收 slot，避免每周期 map 查找；
- 命中缓冲区预分配，正常周期不分配内存；
- C++ 不持有 PyObject、Future，也不反向调用 Python；
- XTriggerEngine 使用刷新后的逻辑冻结 sample，不允许 watcher 求值过程被其他 callback 写入打断；这里不复制整个 DUT，只在稳定 phase 内直接读取已刷新的 XData；
- 同 phase 扫描完全部 watcher、收集完整 hit set 后统一停止，保证广播语义；
- edge occurrence 只生成一个 BackendHit，由 Python 向多个 Registration 广播；
- ClockCycles 使用目标 tick/deadline 结构，不逐个 waiter 每周期轮询；
- ExprEngine 允许多个 root，共享表达式节点，并修复首个命中后 `break`；
- 只有实际命中时才在 Python 创建 XEvent，未命中的周期不跨语言传数据。

phase 标签、分支和 C++ 内部求值本身成本很低；当前 XClock 的完整周期本来就包含两个半周期及各自的 simulator eval，拆出 `RawStepHalf` 不应额外增加 eval。主要成本来自 Python 边界、Future 唤醒和 asyncio 调度。因此 SimulationPump 不应每个 phase 固定返回 Python：纯 C++ Cond/Expr/FSM 可以在 `RunUntil` 内跨多个 phase 批量推进，只有命中、存在对应 edge barrier、达到时间片或发生错误时才返回。

建议的底层接口轮廓：

```cpp
XRegistrationHandle Arm(const XTriggerIR&);
bool Disarm(XRegistrationHandle);

XRunResult RunUntil(const XRunLimit&);
// result: advanced ticks, stopped phase/reason, span<BackendHit>
```

验证性原型可以直接复用三个现有 ComUse 类；正式 MVP 则应提供统一 XTriggerEngine、整数 handle 和 POD hit buffer。XTriggerEngine 复用 ComUseCondCheck 的比较实现、ExprEngine 和 ComUseFsmTrigger 的 FSM 能力，不必重写算法，但不能把字符串 key、裸 `CSelf()`、多个 callback 和 Python 分别查询固化成新框架 ABI。

## 6. SimulationPump 推进算法

### 6.1 运行状态

```text
STOPPED
IDLE          没有 active simulation Registration
RUNNING       C++ 正在批量推进
DISPATCHING   当前稳定 phase 的事件正在交付
PAUSED        用户显式暂停
CLOSING
FAILED
```

状态属于每个 Execution，不是进程全局状态。XReactor 持有等待关系；SimulationPump 持有推进状态。

### 6.2 主循环

概念流程如下：

```python
async def run(self):
    while not self.closing:
        await self.reactor.work_available.wait()

        if self.paused:
            await self.resume_requested.wait()
            continue

        deadline = monotonic() + self.quantum_seconds

        while self.reactor.has_execution_work():
            limit = self.reactor.compute_run_limit(deadline)
            result = self.backend.run_until(limit)
            self.backend.check_exceptions()

            events = self.reactor.publish_hits(result.hits)

            if events or result.is_phase_barrier:
                self.reactor.resolve_waiters(events)
                await asyncio.sleep(0)
                deadline = monotonic() + self.quantum_seconds
            elif monotonic() >= deadline:
                await asyncio.sleep(0)
                deadline = monotonic() + self.quantum_seconds

            if result.stop_reason.is_error:
                raise self.backend.make_error(result)
```

真实实现还要处理 cancellation、backend stall 和 close，但不能退回 Python 分别轮询 Cond/Expr/FSM。`run_until()` 返回的是一个逻辑冻结 phase 的完整 BackendHit 批次。

### 6.3 phase 屏障与 asyncio 恢复

`Future.set_result()` 只把等待 Task 放入 asyncio ready queue，因此 Pump 不能在 set_result 后同步推进下一 half-step。边沿屏障流程是：

```text
RunUntil 停在 stable half-step
  -> XReactor 为完整 BackendHit 批次构造 XEvent
  -> resolve 所有匹配 Future / 投递 subscription
  -> SimulationPump yield 给 asyncio
  -> 已唤醒 task 执行，直到各自下一次挂起
  -> Pump 才能再次进入 RunUntil
```

框架应把所支持 asyncio loop 的 ready-callback FIFO 行为写入兼容契约并做回归测试；若某个 loop 无法满足该调度契约，就不能宣称提供严格 FallingEdge 屏障。这样 `await FallingEdge(clk)` 后的同步赋值才能保证发生在下一 rising 之前。

等待 HTTP、Queue 或其他外部 I/O 不会隐式冻结仿真。task 一旦再次挂起，Pump 即可继续；只有 `await sim.pause()` 或等价显式控制才暂停推进。

### 6.4 有界占用 asyncio

正常仿真可以占用主要 CPU，但不能永久不 yield。默认同时限制 wall-clock quantum 和最大 batch：

```text
foreground   默认，约 5～10 ms quantum，仿真优先
cooperative  约 0.5～2 ms，适合 Web UI 和交互调试
exclusive    更大 batch，但仍保留取消/信号 watchdog
```

立即返回 Python 的原因包括 Trigger 命中、已注册 edge barrier、时间片到期、暂停/关闭、callback 异常或 backend 错误。没有 active simulation Registration 时进入 IDLE，不空转。

### 6.5 安全推进上限

| Active Registration | RunLimit |
| --- | --- |
| `ClockCycles(clock, n)` | 不越过目标 tick |
| C++ Condition/Expr/FSM | 可用大 batch，由 TriggerEngine 命中停止 |
| `@pytrigger` 每次采样 | 不越过下一个 sampling phase |
| Rising/Falling waiter | 精确停在对应 half-step |
| simulation timeout | 不越过 deadline tick |
| 无仿真 waiter | IDLE |

phase 标签和 C++ 分支成本很低，拆出 `RawStepHalf` 也不应增加 simulator eval；真正需要避免的是逐 phase Python crossing、Future 创建和 heap allocation。

## 7. XTrigger 到 XEvent 的端到端流程

### 7.1 one-shot await

```text
Task 执行 await XTrigger
  -> current XReactor 创建 asyncio Future 和 one-shot Registration
  -> 编译/复用 XTriggerIR
  -> XTriggerEngine Arm，得到 slot + generation
  -> SimulationPump RunUntil
  -> C++ 返回完整 BackendHit[]
  -> XReactor 去重并构造 typed XEvent
  -> 同一 occurrence 广播给全部匹配 Registration
  -> Future.set_result(XEvent)
  -> Pump yield，Task 恢复
```

等待的是 XTrigger；传输的是 XEvent；Future 和 Registration 都是实现细节。

### 7.2 persistent `@on`

持久订阅只在启动时 arm 一次。每次命中由 XReactor 向订阅队列投递同一个 XEvent，不采用“handler 完成后重新 await”模式，因此没有 re-arm 空窗。handler 执行速度与触发速度不匹配时，按订阅的 lossless/latest-only 策略处理。

### 7.3 cancellation 与迟到命中

取消顺序为：先把 Registration 标记为 closing，再从 Reactor 索引移除，然后调用 `Disarm(slot, generation)`，最后取消 Future 或 handler task。C++ 即使返回已在途的旧 BackendHit，generation 校验也会将其丢弃，不能投递给复用该 slot 的新 Registration。

底层 callback 或 watcher 销毁前必须 detach；XReactor close 只清理自己创建的对象，不取消外部 asyncio task。

### 7.4 timeout

- simulation timeout 编译为 tick/deadline Trigger，由 SimulationPump 的 RunLimit 保证不越过；
- wall-clock timeout 使用宿主 asyncio timeout；
- `AnyOf(trigger, timeout)` 返回实际获胜的 typed XEvent，并原子取消 loser Registration。

## 8. asyncio 和外部库兼容边界

### 8.1 pytest-asyncio

框架核心不调用 `asyncio.run()`，而是提供异步上下文：

```python
@pytest_asyncio.fixture
async def dut():
    instance = DUTTop()
    async with Execution(instance) as sim:
        yield sim.dut
```

```python
@pytest.mark.asyncio
async def test_request(dut):
    await ClockCycles(dut.xclock, 10)
```

同步便利入口只在外部没有 running loop 时使用 `asyncio.run()`；检测到已有 loop 时应提示调用者改用 `await`，不能嵌套 loop 或使用 `nest_asyncio`。

### 8.2 HTTP server/client

HTTP 与 SimulationPump 可以共享同一个 event loop。默认语义建议为：

> 只要仍有 active simulation waiter，仿真继续推进；外部 I/O Task 不自动暂停仿真。

需要冻结 DUT 时显式使用：

```python
async with sim.paused():
    response = await client.post("/configure")
```

### 8.3 Task 所有权

Execution 只记录自己创建的 Pump/Reactor 辅助 tasks。关闭时只取消这些 task，不使用 `asyncio.all_tasks()`。

用户通过 `asyncio.create_task()` 或 `asyncio.gather()` 创建的任务仍可 await 仿真 Trigger，因为 Trigger 注册发生在 await 时，不要求 task 必须由框架创建。

### 8.4 多线程是可选优化

MVP 可在 event loop 线程直接执行有界的 `RunUntil(limit)`，通过 wall-clock quantum 控制占用。

如果单次 backend 调用太长，再引入 simulator owner thread：

```text
asyncio thread -> command/future -> simulator owner thread -> xcomm/backend
```

同一 DUT 的构造、Step、signal access、waveform 和 Finish 必须遵守线程所有权；simulator 内部可以自行多线程，但对外的 eval/Step 应表现为原子 barrier。

这属于性能/响应性扩展，不是 asyncio 正确集成的前置条件。

## 9. 与 Toffee/cocotb 的关系

### 9.1 将 Toffee 作为参考

值得参考但重新设计的能力：

- Bundle 和信号映射；
- Driver/monitor 基础抽象；
- Model/reference model；
- 由 agent 按项目生成的 reference model/scoreboard；
- functional coverage；
- 由 agent 按项目生成的 pytest fixture 和报告。

不建议直接继承的部分：

- 通过 asyncio 私有 Task 状态判断全局静止；
- 修改 event loop 对象保存全局仿真状态；
- 根据 task 名称区分时钟任务；
- 取消所有 asyncio tasks；
- 使用单一 `global_clock_event` 假设所有等待属于同一时钟。

### 9.2 cocotb 风格与严格 cocotb 时序

第一阶段可以提供相似 API：

```python
await ClockCycles(...)
await Condition(...)
await ValueChange(...)
```

这些 API 只借鉴用户侧的 await 形式，不以复刻 cocotb event-region scheduler 为目标。
当前 `StepHalf`/`RunUntil` 已允许 Python 在相邻边沿之间介入，并由 XClock 保证每个
stable phase 的完整执行顺序。因此：

- 完整周期 Condition/Expr/FSM：现有能力基本足够；
- `RisingEdge` 明确定义为上升沿 refresh 后；
- FallingEdge 后、下一 RisingEdge 前运行 Python：由 half-step barrier 保证；
- 组合 drive 后观测：使用同一 half-tick 的 `DriveStable`，不暴露 simulator region。

## 10. 建议仓库与代码组织

这一级别的调度内核和验证抽象适合放入独立 Python 框架仓库；xcomm 只提供与 Python 方法学无关的高性能机制，Picker 继续负责 DUT 生成和稳定接入点。

```text
xcomm repository
├── XClock / XData / backend adapter
├── XTriggerEngine
│   ├── Cond / Expr / FSM evaluator
│   ├── phase sampling hook
│   └── slot + generation registration
├── RawStepHalf / RunUntil
├── XBackendHit / XRunResult
└── SWIG 基础绑定与安全 attach/detach

new verification framework repository
├── event.py          XEvent 与 typed event
├── trigger.py        XTrigger、组合与 decorator
├── reactor.py        Registration、订阅与分发
├── execution.py     Execution 与内部 SimulationPump
├── adapters/         asyncio、pytest、HTTP 集成
├── methodology/      通用 Driver、Monitor；项目专用结构由 agent 组合
└── tests / examples / benchmarks

picker repository
├── RTL -> DUT code generation
├── 生成稳定的 DUT/xclock/signal protocol
└── 跨仓库集成测试与示例
```

依赖方向：

```text
new framework -> xspcomm
Picker generated DUT -> xspcomm
user test -> new framework + generated DUT
```

新框架采用独立包名和独立语义，不承担 Toffee 兼容。它依赖最小 DUT protocol，不硬编码 Picker 的具体生成类。`XTrigger/XEvent/XReactor` 属于新框架；`XTriggerEngine/XBackendHit/RunResult` 属于 xcomm；两者的 ABI/API 契约在 M0 固定。

## 11. 实施 Roadmap

实施顺序采用“纵向切片”：每个里程碑都必须形成一个可以运行、可以测量的闭环。M0～M3 构成核心 MVP；M4 以后是兼容性和工程化扩展。

### M0：冻结语义与性能基线

先不写大规模实现，固定以下不可轻易回退的契约：

- `XTrigger`、`XEvent`、`XReactor`、`Registration`、`XBackendHit` 的职责和生命周期；
- `await trigger` 是一次性等待，`@on(trigger)` 是持久订阅；
- `RisingEdge`、`FallingEdge` 都是半周期屏障；
- `Value/Condition` 必须显式指定 `sample=`，或由 `Execution` 提供显式默认值；
- 同一个稳定 phase 的全部命中必须作为一个批次返回；
- 表达式只支持 `& | ~`，禁止依赖 Python 的 `and/or/not`；
- 明确位宽、有符号数以及 X/Z 的比较语义。

同时记录当前 `RawStep`、`ComUseCondCheck`、`ComUseExprCheck`、FSM 的吞吐和跨 Python 次数，作为后续性能回归基线。

完成标志：形成一份接口 ADR、类型草图、phase 状态图和可重复运行的 benchmark。

### M1：C++ TriggerEngine 与半周期推进

这是后续 Python API 的地基：

- 增加稳定的 `RawStepHalf` 或等价 next-phase 接口；
- 在第二次 eval 和端口刷新之后增加专用 post-refresh sampling hook；
- 定义 `XPhase`、`StopReason`、`RunLimit`、`RunResult`；
- 使用整数 `slot + generation` 标识 watcher，避免悬空句柄；
- 使用固定布局 `XBackendHit` 和预分配命中缓冲区；
- 把 Condition、Expr、FSM 的检查统一接入 `XTriggerEngine`；
- 修复 `ComUseExprCheck` 首次命中后 `break` 的行为；
- 明确 attach、detach、cancel、stop、异常时的所有权和清理顺序。

验收门槛：

- `FallingEdge` 返回后，Python 写入发生在下一次 rising 之前；
- 同一 phase 的所有命中都能返回，Disable 一个 watcher 不会吞掉其他命中；
- 取消或销毁 Registration 后，旧的 slot 不可能误命中新对象；
- C++ 热路径没有字符串、Python 对象和逐 phase 堆分配。

### M2：XReactor 最小纵向闭环

建立独立 Python 框架仓库或包，并先打通最小链路：

- `event.py`：`XEvent`、`EdgeEvent`、`ClockEvent`；
- `trigger.py`：`XTrigger`、`RisingEdge`、`FallingEdge`、`ClockCycles`；
- `reactor.py`：Registration、Future、取消、命中分发；
- `execution.py`：Execution 生命周期和内部 `SimulationPump`；
- Future 必须由当前 loop 的 `loop.create_future()` 创建；
- 当前 Execution/XReactor 通过 `contextvars` 绑定；
- `SimulationPump` 支持 batch、quantum 和协作式 yield，不扫描 asyncio 私有状态。

第一个必须跑通的例子：

```python
async with Execution(dut) as sim:
    await FallingEdge(dut.clk)
    dut.req.value = 1
    event = await RisingEdge(dut.clk)
    assert event.phase is XPhase.RISING_STABLE
```

验收门槛：边沿写入顺序正确；pytest 已有 event loop 可以直接运行；仿真退出时不会取消或关闭不属于自己的外部 asyncio task。

### M3：编译式 Trigger——Expr 与 FSM

把易写性和 C++ 性能连接起来，并在核心 MVP 中覆盖复杂状态条件：

- 实现符号 Proxy、位宽传播、比较以及 `Expr.__bool__` 报错；
- 支持表达式中的 `& | ~` 和括号组合；
- `@xtrigger(sample=...)` 在注册时 trace 一次，根据返回对象生成 ExprIR 或 FsmIR；
- 简单谓词下沉为 Cond，组合谓词下沉为 Expr；
- `Sequence/Wait/Within/Hold/FSM` builder 下沉为 `ComUseFsmTrigger`；
- 缓存不可变编译程序；stateful Registration 按启动 phase 和 reset policy 隔离运行实例；
- XEvent 对 FSM 命中携带 terminal state、tick 和可选 captures；
- 提供显式 `@pytrigger` 最差情况路径，但禁止静默降级。

示例：

```python
@xtrigger(sample=RisingEdge("clk"))
def handshake(dut):
    return dut.valid & dut.ready & ~dut.flush

@xtrigger(sample=RisingEdge("clk"))
def request_then_ack(dut):
    return Sequence(
        Wait(dut.req),
        Within(1, 8, dut.ack),
    )

event = await request_then_ack(dut)
```

验收门槛：Expr 和 FSM 注册后均不逐 phase 回到 Python；FSM 的 reset、取消、超时和重用正确；不同启动 phase 的 waiter 不会错误共享状态；同 phase 的多个命中都能交付。

### M4：`@on`、组合触发器与外部 asyncio

在一次性等待可靠之后增加持久消费：

- `@on(trigger)` 生成 `XSubscriptionSpec`，由 XReactor 建立持久 Registration；stateful Trigger 默认非重叠，并在命中后的下一 sampling phase 重新开始；
- handler 默认串行执行；默认 lossless 有界队列，溢出必须报错；UI/遥测可显式选 latest-only；
- Trigger 决定 `enter`、`each_sample`、`change` 等发射语义；Subscription 决定交付策略；
- 实现 `AnyOf`、`AllOf` 及 winner/cancel 传播；
- 实现 `AsyncioEventTrigger`、`QueueTrigger`、`TaskComplete` 等 Python 侧适配器；
- 增加 pytest、aiohttp 或 FastAPI 共存测试。

验收门槛：持久订阅不存在重新 arm 的空窗；HTTP 请求在长仿真期间仍能获得可配置的响应延迟；默认模式不会静默丢事件。

### M5：更多事件、超时和多时钟

- 增加 `ValueChange`、更丰富的 Condition 发射策略，以及跨 clock-domain Sequence；
- 区分 simulation timeout 与 wall-clock timeout；
- 统一 global tick、clock domain、local cycle、phase 的时间模型；
- 支持分频、多时钟和跨 domain 的 `AnyOf`；
- 定义 clock pause、domain pause 和 backend pause 的区别。

验收门槛：相同输入产生稳定的事件排序；多时钟启停不会破坏 phase 或 watcher 所有权。

### M6：性能、可靠性与工程化

- 增加写缓冲和驱动冲突诊断；
- profiling 证明有收益时再实现 zero-copy、释放 GIL或独立仿真 owner thread；
- 自适应 batch/quantum，并暴露命中数、推进时间、Python 唤醒数等指标；
- 补齐错误上下文、事件 trace、文档、版本兼容矩阵和发布流程；
- 保留通用 Driver/Monitor；协议 Interface、Scoreboard、fixture/plugin 交由 agent 按项目生成。

验收门槛：后端能力被显式声明；无命中时吞吐接近直接 `RawStep`；存在外部 asyncio 工作负载时，事件循环延迟有明确上界。

### 最短可交付路径

```text
M0 语义冻结
  -> M1 C++ TriggerEngine + 半周期屏障
  -> M2 await RisingEdge/FallingEdge 的端到端闭环
  -> M3 await 编译式 Expr/FSM Trigger
  -> M4 @on 与 asyncio 适配
  -> M5 多时钟/超时/Sequence
  -> M6 严格 phase 与工程化
```

M3 完成后，框架已经具有最核心的差异化价值：用户可以 `await` 简单条件或复杂 FSM，而 Expr 求值和状态转移持续留在 C++；M4 解决与 HTTP、pytest 和其他 asyncio 库共存；M5、M6 不应阻塞第一个可用版本。

## 12. 兼容性和正确性风险

### 12.1 同周期广播

Expr checker 当前只返回第一个命中，必须修正或由 bridge 使用独立 checker，否则多个 waiter 的唤醒周期不同。

### 12.2 callback 生命周期

XClock callback 保存裸 `void*`/`CSelf()`。销毁 checker/FSM 前必须 detach callback。

### 12.3 Disable/Enable 所有权

用户也可能主动 Disable clock。SimulationPump 不能无条件 Enable 一个并非由 TriggerEngine 停止的 clock。建议增加停止原因或 token：

```text
USER_PAUSE
FAST_TRIGGER
SIMULATION_CLOSE
BACKEND_ERROR
```

短期至少在 SimulationPump 中记录它是否拥有本次 Disable。

### 12.4 callback exception

Python Step callback 当前把异常记录到 `XClock.exceptions`。`RunUntil(limit)` 返回后必须检查并传播；不能继续推进到下一个 batch。

### 12.5 假周期事件

不能在 clock 已 disabled、实际 cycle 未增加时继续发送 step/edge event。事件应依据 `before_clk/after_clk` 和 backend event，而不是依据 Python for-loop 次数。

### 12.6 多时钟

一个 checker 绑定多个 clock 时，命中会 Disable 全部 clocks。需要定义：

- 哪个 clock 负责采样；
- 其他 clock 为何停止；
- 恢复时由谁 Enable；
- 多个 SimulationPump/domain 是否共享同一个 simulator backend。

### 12.7 永久不满足条件

必须支持 simulation timeout、wall-clock watchdog 或用户取消。exclusive 模式也不能永久阻止 event loop 处理取消。

## 13. 测试计划

### 13.1 xcomm 正确性

- `ComUseCondCheck`、`ComUseExprCheck` 和 FSM 同 phase 多命中；
- `RunUntil` 在正确 half-step 停止并返回完整 BackendHit 批次；
- `slot + generation` 能拒绝取消后迟到的命中；
- callback exception 在 batch 返回后传播；
- attach/detach、Disable/Enable 和销毁顺序无悬空调用；
- 无 watcher 热路径没有逐 phase 分配。

### 13.2 XReactor 与 phase 语义

- `await RisingEdge/FallingEdge/ClockCycles`；
- `Value/Condition` 只在指定稳定 sampling phase 判断，包括注册时已经为真的情况；
- 同一 occurrence 的多个 waiter 收到相同 event identity；
- 同 phase 不同 occurrence 全部唤醒；
- XTrigger 可重复 await，Registration 不可重复使用；
- waiter cancellation、AnyOf loser 和 Execution close 都能清理底层 watcher；
- `@on` 不存在 Python re-arm 空窗；persistent FSM 必须验证非重叠和下一 sampling phase reset；
- 验证 lossless 溢出报错和 latest-only；
- Trigger 命中恢复的 Python task 在下一 half-step 推进之前获得执行机会。

### 13.3 asyncio 集成

- 在 pytest-asyncio 已有 loop 中启动和关闭 Execution；
- `asyncio.gather(driver, monitor, http_client)`；
- aiohttp/FastAPI server 与仿真共享 loop；
- 外部 Event、Queue、Task adapter 的命中、取消和异常传播；
- HTTP 请求持续进行时，SimulationPump 按 quantum 让出；
- 仿真关闭不取消外部 task，也不停止或关闭宿主 loop；
- 两个独立 Execution 在同一 loop 中的支持策略；
- Verilator、VCS、UVS、GSim capability 差异。

### 13.4 性能测试

至少比较：

```text
同步 RawStep(N)
当前 Python RunStep(N)
新 RunUntil 无 watcher
新 RunUntil C++ Condition/Expr
XReactor 命中与 Future 分发
显式 Python predicate slow path
不同 batch / quantum
```

重点指标为 cycles/s、每周期 Python/C++ 边界次数、命中到 Future 恢复的延迟、HTTP p50/p99 延迟、动态 Registration 的内存增长。

## 14. 建议的第一版 API

```python
@xtrigger(sample=RisingEdge("clk"))
def handshake(dut):
    return dut.valid & dut.ready & ~dut.flush

@pytrigger(sample=RisingEdge("clk"))
def reference_ready(dut):
    return reference_model.ready(dut)

@xtrigger(sample=RisingEdge("clk"))
def request_then_ack(dut):
    return Sequence(
        Wait(dut.req & ~dut.flush),
        Within(1, 8, dut.ack),
    )

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

    event = await handshake(dut)

    winner = await AnyOf(
        handshake(dut),
        AsyncioEventTrigger(stop_event),
        SimTimeout(100, clock=dut.clk),
    )
```

`default_sample` 只是显式的 Execution 配置，并非隐藏的当前时钟猜测。兼容入口如 `dut.AStep()`、`dut.ACondition()` 可以保留在适配层，但新 API 不依赖它们，也不把任意 Python lambda 静默当成 fast path。

## 15. 编码前仍需冻结的少量问题

已经确定：半周期屏障、显式 sampling、同 phase 完整事件集、`& | ~` 符号表达式、BackendHit/RunResult 下沉 xcomm、XReactor 不拥有 asyncio loop，以及 persistent FSM 第一版采用非重叠匹配。

真正还需在 M0 冻结的是：

1. `XEvent` 采用一个扁平 dataclass 加 kind，还是公开少量 typed subclass；
2. 位宽、有符号比较和 X/Z 的精确定义；
3. Condition 默认发射语义是 `enter` 还是 `each_sample`；
4. `@on` 默认队列容量，以及 overflow error 的异常类型；
5. 一个 clock-domain trigger 命中时，默认只暂停该 domain 还是整个共享 backend；
6. 第一版是否承诺同一 asyncio loop 中并行运行多个 Execution；
7. Python 最低版本和相应的 TaskGroup/timeout 兼容策略。

这些问题不改变总体分层，但会影响公开 API 或 ABI，应在 M1 编码前形成 ADR。HTTP await 本身不隐式暂停仿真；只有用户显式 await 仿真控制 Trigger，或调用 pause，才改变推进状态。

## 16. 推荐决策

- asyncio 是宿主；`XReactor` 只管理自己的 Registration、Future 和 task；
- `SimulationPump` 默认采用约 10 ms wall-clock quantum，并允许配置；
- 第一版即支持 half-step barrier、统一 BackendHit/RunResult 和完整同 phase 命中；
- `@xtrigger` 统一编译 ExprIR/FsmIR，使用 xcomm Cond/Expr/FSM evaluator，注册后不逐 phase 进入 Python；
- persistent FSM 第一版非重叠：命中后从下一 sampling phase reset，不等待 handler 完成；
- 任意 Python predicate 只能通过显式 `@pytrigger` slow path；
- 命中或边沿屏障后先向 asyncio yield，再允许 Pump 推进下一 phase；
- `Value/Condition` 必须有 `sample=` 或显式 `default_sample`；
- 新建独立验证框架；Toffee 只作概念参考，不构成兼容目标；
- XClock stable phase 是唯一公共仿真时序契约，不增加 `ReadWrite/ReadOnly/NextTimeStep`。

## 17. 参考

- xcomm API 文档：`dependence/xcomm/docs/APIs.cn.md`
- Toffee asynchronous：<https://github.com/XS-MLVP/toffee/blob/master/toffee/asynchronous.py>
- Toffee triggers：<https://github.com/XS-MLVP/toffee/blob/master/toffee/triggers.py>
- cocotb Trigger/Scheduler：<https://docs.cocotb.org/en/development/scheduler.html>
- cocotb Timing Model：<https://docs.cocotb.org/en/stable/timing_model.html>
