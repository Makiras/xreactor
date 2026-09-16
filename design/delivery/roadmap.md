# 实施 Roadmap

实施采用纵向切片。每个里程碑必须形成可运行、可测试、可测量的闭环。

## 总览

```text
M0 冻结契约与基线
  -> M1 C++ TriggerEngine + half-step
  -> M2 await Rising/Falling 端到端
  -> M3 编译式 Expr/FSM Trigger
  -> M4 @on + asyncio adapter
  -> M5 多时钟/ValueChange/复杂时间
  -> M6 性能、可靠性与工程化
```

M0～M3 是核心 MVP。M3 完成后，简单条件和复杂 FSM 都能以 Python await 形式使用，而逐 phase 求值留在 C++。

## 当前实现状态（2026-09-15）

| 里程碑 | 状态 | 已形成的闭环 | 尚缺 |
| --- | --- | --- | --- |
| M0 | 完成 | 模块化契约、phase/所有权 ADR、数值/XZ ADR、源码审计、可重复 benchmark 与本机 baseline | 真实 DUT baseline 随 simulator adapter 补充 |
| M1 | 核心完成 | `StepHalf`、`XPhase`、slot+generation、完整 hit 批次、typed StopReason、Edge/Value/ValueChange/Expr/Sequence/FSM/Sample watcher | SWIG 零拷贝 hit view、unique program 回收 |
| M2 | 完成 | `await RisingEdge/FallingEdge/ClockCycles`、Future/cancel、contextvars、default_sample、显式 capability、wall-clock quantum | adaptive batch 属 M6 优化 |
| M3 | 核心完成 | symbolic `& | ~`、严格 `@xtrigger`、任意位宽无符号 Expr、非重叠 Sequence、分支 FSM、program cache/instance 隔离、显式 `@pytrigger` | signed IR 扩展 |
| M4 | 核心完成 | AnyOf/AllOf、Event/Queue/Task adapter、`@on` persistent native rearm、有界 lossless/latest、真实 asyncio HTTP 共存测试 | 安装完整依赖后的 pytest/aiohttp/FastAPI 矩阵、长期压力测试 |
| M5 | 部分完成 | ValueChange、Condition 三种 mode、simulation/wall timeout | 多时钟共同时间轴、跨 domain 组合、domain pause |
| M6 | 部分完成 | XClock stable contract、固定 quantum、DriveStable/pre-rising barrier 与 profiling baseline | 写冲突诊断、长期压力测试，以及由 profiling 决定的 zero-copy/GIL/owner thread 优化 |

当前项目入口是 `src/xreactor/`；原生执行器位于 `../dependence/xcomm/` 的
`include/xspcomm/xtrigger.h` 与 `src/xtrigger.cpp`。目前的“完成”只表示纵向
闭环可运行，并不表示 ABI 已稳定。

方法学纵向切片也已启动：`as_xdata`、Bundle/BundleValue、ReadyValid/Role、最薄
Driver/Monitor 基类、ReadyValidDriver、同步 capture ReadyValidMonitor 已实现；Picker
新 Python 端口默认直接暴露 XData，生成只读层次信号视图，并内嵌 signal tree 供
`Bundle.bind_tree()`/`ReadyValid.bind_tree()` 绑定。
Cache 八个 ready-valid 子树已统一绑定，CPU/memory/MMIO 功能流量已经迁移；尚缺带协议
类型的生成 schema 和自动 ReadyValid Interface 不属于核心框架目标；agent 可基于已有
signal tree 和显式 binding API 生成这些上层结构。核心层尚缺 native batched snapshot。详细状态见
[XData、Bundle 与 Interface 设计](../architecture/data-bundle-interface.md) 的 D0～D8 表。

## M0：冻结契约和性能基线

交付：

- XTrigger/XEvent/XReactor/Registration/BackendHit 类型草图；
- phase 状态图；
- ExprIR/FsmIR 轮廓；
- 生命周期和所有权 ADR；
- 位宽、有符号、X/Z 语义 ADR；
- 当前 RawStep、Cond、Expr、FSM benchmark。

验收：

- 本目录 decisions 不再存在互相矛盾的描述；
- benchmark 可重复运行；
- 公共 API 与 C++ ABI 的负责边界明确。

## M1：C++ TriggerEngine 与 half-step

交付：

- RawStepHalf 或等价 RunUntil phase 接口；
- post-refresh sampling hook；
- XPhase、StopReason、RunLimit、RunResult；
- slot + generation；
- 固定布局 BackendHit 和预分配 hit buffer；
- Cond/Expr/FSM 接入统一 engine；
- 修复 ExprCheck 首命中 break；
- 安全 attach/detach/cancel/close。

验收：

- Falling 停止后不会继续推进 Rising；
- 同 phase 全部命中返回；
- 取消后的旧 hit 不误投递；
- 热路径无字符串、PyObject 和逐 phase heap allocation。

## M2：XReactor 边沿闭环

交付：

- event.py、trigger.py、reactor.py、execution.py；
- RisingEdge、FallingEdge、ClockCycles；
- Future/Registration/cancellation；
- SimulationPump batch、quantum、yield；
- contextvars 绑定。

验收示例：

```python
async with Execution(dut):
    await FallingEdge(dut.clk)
    dut.req.value = 1
    await RisingEdge(dut.clk)
```

必须证明写入发生在下一 rising 之前，并能在 pytest 已有 loop 中运行。

## M3：编译式 Expr/FSM Trigger

交付：

- symbolic proxy 和严格表达式检查；
- `& | ~`；
- ExprIR/FsmIR；
- `@xtrigger` 统一入口；
- Sequence/Wait/Within/Hold/FSM builder；
- ComUse Cond/Expr/FSM 编译；
- program cache 和 state instance 隔离；
- 显式 `@pytrigger`。

验收：

- Expr/FSM 注册后不逐 phase 回 Python；
- 不同起始 phase 的 FSM waiter 不串状态；
- one-shot FSM 的 reset/cancel/timeout 正确；
- unsupported xtrigger 不静默降级。

## M4：订阅、组合和 asyncio adapter

交付：

- `@on` 和 XSubscriptionSpec；
- lossless 有界队列、overflow error、latest-only；
- persistent FSM 非重叠 reset；
- AnyOf/AllOf；
- AsyncioEventTrigger、QueueTrigger、TaskComplete；
- pytest/aiohttp/FastAPI 共存测试。

验收：

- 无 Python re-arm 空窗；
- persistent FSM 从命中后的下一 sample 开始新一轮；
- handler 落后时不静默丢事件；
- HTTP 延迟满足配置的 quantum 目标。

## M5：更多事件和多时钟

交付：

- ValueChange；
- Condition enter/each_sample/change；
- simulation timeout 与 wall-clock timeout；
- global tick/domain/local cycle/phase 时间模型；
- 分频、多时钟、跨 domain AnyOf/Sequence；
- domain/backend pause。

验收：同输入事件排序稳定，多时钟启停不破坏 watcher 所有权。

## M6：性能、可靠性和工程化

交付：

- 用真实负载决定是否实现 zero-copy hit、GIL release 或 owner thread；
- adaptive batch/quantum 和 profiling；
- trace、错误上下文、兼容矩阵、发布流程；
- 为已落地的 Bundle/Monitor 补齐 native batched snapshot。

XClock 已经以 `pin update -> eval -> edge write -> eval -> refresh` 保证 stable phase；
ReadWrite/ReadOnly/NextTimeStep 是 cocotb 适配外部事件调度器的 region API，不是本框架
交付项。协议专用 Interface、Scoreboard 和 pytest fixture/plugin 由用户代码或 agent
基于基础抽象生成，也不进入核心框架。

验收：

- capability 显式声明；
- 无命中吞吐接近直接 RawStep；
- 外部 asyncio workload 下 loop 延迟有明确上界。

## 从当前切片继续的最短路径

1. 用动态 program/registration 长期压力测试量化 Execution 内存增长，并给 native
   program cache 加引用计数、回收或 generation arena；
2. 建立真实 Cache 吞吐与 asyncio p50/p99 基线；profiling 证明有收益时，再做
   zero-copy hit、释放 GIL、owner thread 或 adaptive quantum；
3. 在装有 pytest-asyncio/aiohttp/FastAPI 的 CI 环境跑兼容矩阵；
4. 在真实跨 domain 用例出现时，再建立 global tick/domain/local cycle 模型；
5. profiling 证明 snapshot 成本显著时，为 Bundle/Monitor 增加 native batched snapshot。
   协议 schema、专用 Interface、
   Scoreboard 和 pytest 脚手架由 agent 处理；XPin 已按 breaking change 删除。

核心单 XClock 调度域已经闭环。后续先验证长期资源边界、真实性能和第三方 asyncio
兼容性；多时钟、zero-copy 和 native snapshot 均由实际用例或 profiling 决定，不再为了
追求表面上的“完整框架”预先扩张公共 API。
