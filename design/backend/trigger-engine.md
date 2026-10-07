# C++ XTriggerEngine

状态说明：本文的接口代码为架构示意，现有 C++ 接口以 `xcomm/include/xspcomm/xtrigger.h`
为准。覆盖采集扩展的架构方向已确认，详见[有状态覆盖计划](../delivery/stateful-coverage-plan-2026-09.md)；
其中的基础 native 覆盖注册、持续计数及快照接口已实现；复杂 capture/key 上下文仍待后续阶段。

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

## 覆盖采集扩展

同一 phase 求值入口执行通知注册与被动覆盖注册，共用 Expr/Sequence/FSM
匹配实现。通知命中沿用 XBackendHit；普通覆盖命中在 C++ 内累计，持续观察，不因
每次命中返回 Python。采样、分类、同样本 cross 和原子提交以 covergroup 为单位。

`CoverageVersion/AttachCoverage/CoverageSnapshot/ResetCoverage/Disarm` 支持能力查询、
整组注册、累计快照、清历史、重置统计及注销。注册状态与
不可变程序分离，快照包含 generation/epoch 防止重复累计。覆盖注册占用的资源纳入
清理检查，但不产生独立时钟推进需求。`enter/each_sample/change`、时序完成、gap
及重叠策略继续明确区分；计数用途本身不改变匹配语义。

覆盖名称、目标管理、跨运行合并与报告保留在 XReactor。C++ 只保存执行所需的数值
索引、匹配状态、计数和有界诊断。具体接口与测试边界按上述实施计划冻结。

coverage ABI v2 的 point 描述符直接引用 XData，不再用 uint64 Expr 根传送观测值。
宽值/范围/转移复用已有 XData 比较；mask 在 ExprEngine 中逐 native word 比较，
采样热路径不分配字节数组。非法命中时保存完整十六进制值，Python 同步恢复为任意精度
整数；普通命中只更新计数。X/Z 检查覆盖全部位，计数器继续单独使用 uint64。
Mask 常量由 ExprEngine 持有，Execution 注销全部观察者后清理，不跨执行继承。

当前 ABI v3 扩展注册参数 `overlap/max_active/diagnostics`。复杂 Sequence/FSM 的活跃
实例使用私有 `MatchState`，共享 Watcher 的不可变步骤和状态表；普通通知与覆盖计数
共用 `AdvanceSequence/AdvanceFsm`。同 phase 先推进旧实例，以线性压缩移除终结状态，
再判定新开始，避免每实例复制程序或建立独立任务。容量耗尽保留证据并标记不完整。

诊断关闭时不分配汇总数组；开启时只累计固定数量的计数器。普通快照不复制匹配进度；
`CoverageSnapshot(handle, true)` 才返回数值状态行，由 Python 映射名称。
退出前读取未完成数，随后注销，累计和合并不保留活跃状态。多个匹配同拍完成分别采样，
采样字段取完成时的引脚值；没有隐含 capture 或 key 事务配对。

## MVP 迁移

1. 复用 CondCheck、ExprEngine 和 FsmTrigger 的求值算法。
2. 增加 half-step 和 post-refresh hook。
3. 用统一 slot/BackendHit 包装现有 evaluator。
4. 修复 ExprCheck 首命中 break。
5. 再逐步消除多个 callback、字符串 program 和裸 CSelf。

这样是 ComUse-first，而不是重写现有表达式和 FSM。
