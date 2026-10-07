# 调度、Sampling Phase 与 Half-step

当前 Execution 通过 [asyncio 调度观察器](asyncio-observer.md)判断本阶段的即时
回调是否处理完。asyncio 保持唯一的 Python 调度器；Driver 使用原生锁和信号量。

## 稳定采样点

XClock 的每个 half 内已经包含 pin 更新、simulator eval、port write、第二次 eval 和
refresh。TriggerEngine 在 `StepHalf()` 返回后求值，因此 stable phase 是 XClock 已有的
执行保证，不是 xreactor 以后还要模拟的 HDL event region：

```text
更新 clock pin
  -> simulator eval
  -> 写入该 edge 的 ports
  -> simulator eval
  -> refresh XData/XPort
  -> XTriggerEngine::Evaluate(phase, tick)
  -> 收集完整 BackendHit 批次
```

这里的“稳定”是该逻辑 phase 内读到统一的已刷新值，不要求复制整个 DUT snapshot。

## Half-step 屏障

`Step(1)` 连续执行 falling 和 rising，Python 不能在中间介入；当前实现已经通过
`StepHalf`/`RunUntil` 提供边沿间屏障。

```text
RunUntil 停在 FALLING_STABLE
  -> XReactor 广播全部事件
  -> resolve Future
  -> SimulationPump yield
  -> 被 falling 唤醒的 task 及其级联唤醒处理完，直到阻塞或结束
  -> XClock::RefreshComb()
  -> XTriggerEngine::SamplePhase(DRIVE_STABLE)，不推进 half-tick
  -> XReactor 同步 capture 并广播完整 hit batch
  -> SimulationPump 再次 yield
  -> 才允许推进 RISING_STABLE
```

因此：

```python
await FallingEdge(clk)
dut.req.value = 1
await RisingEdge(clk)
```

中间的同步写入必须发生在下一 rising 之前。

`DRIVE_STABLE` 是 xreactor 为 testbench drive/observe 建立的明确屏障，不冒充某个
simulator 标准 region。只有存在 `DriveStable` watcher 时才执行，因此普通 edge/condition
流程不增加这次 refresh 和 Python 往返。一个 falling waiter 恢复后、在**下一次 await
之前**完成的写入属于本次 drive window；框架不等待任意 coroutine 达到全局静止，也不把
HTTP 等外部 await 纳入这个窗口。

Execution 通过 call_soon 观察域内即时回调。回调及其级联唤醒执行完或取消后，
才允许下一次 RunUntil 或 DriveStable 采样；Task/Lock/Queue/Event 以及组合等待
都保留 asyncio 实现。新 Task 的启动也在屏障内，不需要特定次数的 sleep(0)。

等待 pending Future 不阻止时钟。外部服务使用 external_task 在域外运行；外部 I/O、
Timer 和跨线程通知由宿主实际交付后才进入仿真工作。框架不扫描宿主的私有就绪队列，
不创建第二套调度器，也不取得用户任务的取消权。

```python
await FallingEdge(clk)
dut.valid.value = 1
dut.bits.value = payload
event = await DriveStable(clk)  # 同一 half-tick，组合逻辑已刷新
```

`DriveStable` watcher 在 C++ 中作为完整 phase batch 求值。多个同 clock waiter 共享同一
event occurrence；在这个 barrier 内的 subscription capture 是同步的，因此读到的是统一
快照，而不是 async handler 之后的 live signal。

框架刻意不提供 cocotb `ReadWrite`、`ReadOnly`、`NextTimeStep`。这些 API 用于 Python
被动嵌入自由运行的事件调度器；本框架由 XClock 主动拥有推进顺序。即使某个 simulator
adapter 内部使用相应 callback，也必须将它们收敛为上述 XClock stable contract，而不是
泄漏为公共调度语义。

## Condition 采样

```python
await Value(dut.ready, 1, sample=RisingEdge(dut.clk))
```

即使 `ready` 在注册时已经为 1，也等待下一个 RISING_STABLE 再判断。这样避免在一个尚未冻结的任意 Python 时刻观察到瞬态。

TriggerEngine 可把 edge source 与 condition 融合为同一 C++ watcher；不必每周期先创建 RisingEdge XEvent，再回 Python 检查。

## SimulationPump

Pump 根据 active Registration 计算 RunLimit：

| Registration | 最大安全推进 |
| --- | --- |
| ClockCycles | 不越过目标 tick |
| C++ Expr/FSM | 大 batch，由命中提前停止 |
| pytrigger | 不越过下一 sampling phase |
| Rising/Falling | 精确目标 half-step |
| DriveStable | 停在 falling，经本阶段即时回调收敛后同 tick 采样 |
| simulation timeout | 不越过 deadline |
| 无仿真 waiter | IDLE |

Pump 返回 asyncio 的条件：

- Trigger 命中；
- edge barrier；
- wall-clock quantum 到期；
- pause/close/cancel；
- callback 或 backend error。

默认 foreground quantum 建议 5～10 ms。HTTP 等外部任务只影响公平性，不自动暂停仿真。

## 多线程边界

第一版允许 Pump 和 simulator facade 在 event-loop 线程运行短批次。若 backend 单次调用无法满足响应延迟，再增加 simulator owner thread。

即使 simulator 内部多线程，对外也必须表现为：

- eval/refresh 是原子 phase barrier；
- 同一 DUT 的 Step、signal access、waveform、Finish 遵守统一所有权；
- worker thread 不直接操作 asyncio Future；
- 命中通过线程安全通道回送 event-loop 线程。
