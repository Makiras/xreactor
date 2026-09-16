# 公共 API 索引

所有常用对象都从 `xreactor` 顶层导出。

## 执行与 Backend

| API | 用途 |
| --- | --- |
| `Execution` | 一个测试的异步运行作用域 |
| `SimulationBackend` | Backend 协议 |
| `XCommClockBackend` | XClock/C++ trigger engine adapter |
| `MemoryBackend` | 纯 Python 语义测试 Backend |
| `BackendCapabilities` | Backend phase/capability 声明 |
| `RunLimit`, `RunResult`, `StopReason` | Backend 批量推进接口 |

## Trigger 与 Event

| API | 用途 |
| --- | --- |
| `RisingEdge`, `FallingEdge`, `DriveStable` | stable phase trigger |
| `ClockCycles` | rising cycle 计数 |
| `Value`, `ValueChange` | 指定 phase 的值条件和变化 |
| `SimTimeout`, `WallTimeout` | 仿真时间和墙钟时间超时 |
| `AnyOf`, `AllOf` | 组合等待 |
| `AsyncioEventTrigger`, `QueueTrigger`, `TaskComplete` | asyncio source adapter |
| `XEvent`, `EdgeEvent`, `ConditionEvent`, `FsmEvent` | await 返回结果 |
| `XPhase`, `XEventKind`, `LogicValue` | phase、事件类型和四态值 |

## 编译和订阅

| API | 用途 |
| --- | --- |
| `@xtrigger` | 编译到 native IR 的条件/Sequence/FSM |
| `@pytrigger` | 明确的 Python predicate fallback |
| `Sequence`, `Wait`, `Within`, `Hold` | 非重叠时序序列 |
| `FSM`, `State` | 显式分支状态机 |
| `@on` | persistent subscription 声明 |
| `Execution.subscribe` | 启动绑定后的 subscription |

## 数据与协议

| API | 用途 |
| --- | --- |
| `as_xdata` | 取得/校验 native XData |
| `Bundle`, `BundleValue` | 结构化 live view 和不可变 snapshot |
| `PackedArray`, `split_packed` | 等宽 packed bus 拆分 |
| `PackedLayout`, `PackedView` | 嵌套、自定义 packed 布局 |
| `ReadyValid`, `Decoupled`, `Role` | ready/valid interface |
| `ReadyValidDriver`, `ReadyValidMonitor` | active/passive protocol component |
| `Transfer` | Monitor 交付的事务和接受事件 |

## Functional coverage

| API | 用途 |
| --- | --- |
| `Bin`, `BinSpec`, `BinKind` | bin 定义 |
| `CoverPointDef`, `CrossDef`, `CoverGroupDef` | 可序列化 coverage schema |
| `CoverGroup` | 一个运行实例及 counters |
| `CoverageDatabase` | 多实例保存、读取和合并 |
| `Iff` | group/point/cross gate |
| `IllegalPolicy`, `OverlapPolicy` | illegal 和 overlap 策略 |
| `generate_unified_coverage_site` | 多页 functional + LCOV 报告 |
| `generate_unified_coverage_report` | 单文件统一报告 |

参数与示例见对应的使用指南。
