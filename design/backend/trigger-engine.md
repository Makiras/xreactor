# C++ XTriggerEngine

## 目标

XTriggerEngine 把现有分散的 edge、Cond、Expr 和 FSM callback 收敛为每个 clock domain/phase 的统一求值器。

```text
XClock post-refresh hook
  -> XTriggerEngine::Evaluate(phase, tick)
      -> edge/deadline slots
      -> flat conditions
      -> Expr roots
      -> FSM instances
      -> append XBackendHit
  -> 扫描完整 phase 后决定 stop
```

## 数据接口

```cpp
struct XRegistrationHandle {
    uint32_t slot;
    uint32_t generation;
};

struct XBackendHit {
    uint64_t event_id;
    uint64_t tick;
    uint64_t source_id;
    uint64_t value;
    uint64_t x_mask;
    uint32_t slot;
    uint32_t generation;
    XHitKind kind;
    XPhase phase;
    uint16_t flags;
};

struct XRunResult {
    uint64_t advanced_ticks;
    XPhase stopped_phase;
    XStopReason stop_reason;
    std::span<const XBackendHit> hits;
};

XRegistrationHandle Arm(const XTriggerIR&);
bool Disarm(XRegistrationHandle);
XRunResult RunUntil(const XRunLimit&);
```

SWIG 若无法直接暴露 span，可提供只在下一次 RunUntil 前有效的只读 view，或一次批量复制到 Python buffer；不能按 hit 多次跨语言调用。

## 热路径要求

- 每个 domain/phase 尽量只有一个 engine callback；
- slot 存放紧凑 watcher，generation 防 ABA；
- 命中 buffer 预分配；
- 正常未命中 phase 不分配；
- 不保存 PyObject、Future、Python callable；
- 不使用字符串进行热路径索引；
- arm/disarm 只在推进批次之间生效；
- phase 内先扫描全部 watcher，再统一 stop；
- edge occurrence 只生成一个 hit，由 Reactor 广播；
- FSM program 与 instance state 分离。

## StopReason

至少区分：

- EDGE_BARRIER；
- TRIGGER_HIT；
- RUN_LIMIT；
- USER_PAUSE；
- SIMULATION_CLOSE；
- BACKEND_STOP；
- CALLBACK_ERROR；
- BACKEND_ERROR。

实现还包含 `QUANTUM_EXPIRED` 和仅在 Python bridge 使用的 `PYTHON_SAMPLE`。
Edge watcher 命中返回 `EDGE_BARRIER`；普通 Value/Expr/FSM 命中返回
`TRIGGER_HIT`。pause/close 在当前无 owner-thread 实现中发生在两次 RunUntil
之间，枚举值仍保留为跨 backend 的统一契约。

## Condition mode

Value 和无状态 Expr watcher 保存一个布尔前值并支持：

- `enter`：false 到 true，默认；新 registration 的初值为 false；
- `each_sample`：每个为 true 的采样点；
- `change`：false/true 双向变化，hit value 是新布尔值。

命中后的 persistent rearm 保留前值，因此默认 `@on` 不会把持续高电平重复
投递。X/Z sample 不发射，也不更新此前状态。

Pump 不能看到 clock disabled 就无条件 Enable；必须确认本次停止原因及所有权。

## RunUntil

RunLimit 可同时包含：

- 最大 tick/half-step；
- wall-clock/batch budget；
- 最近 edge barrier；
- simulation deadline；
- pause/cancel flag。

纯 C++ Expr/FSM 可以跨越多个 phase 批量推进。只有命中、屏障、预算或错误才返回 Python。

## MVP 迁移

1. 复用 CondCheck、ExprEngine 和 FsmTrigger 的求值算法。
2. 增加 half-step 和 post-refresh hook。
3. 用统一 slot/BackendHit 包装现有 evaluator。
4. 修复 ExprCheck 首命中 break。
5. 再逐步消除多个 callback、字符串 program 和裸 CSelf。

这样是 ComUse-first，而不是重写现有表达式和 FSM。
