# 已冻结的设计决策

本页记录已经达成一致、实现时不应再次隐式改变的规则。未冻结事项保留在各专题文档的“待确认”小节。

## 分层

- `XTrigger` 是不可变、可复用的等待规格。
- `XEvent` 是一次已经发生的不可变结果，不是同步原语。
- `XReactor` 管 Registration、Future、订阅、组合和事件分发。
- `SimulationPump` 是 Execution 内部推进任务，不作为主要用户概念。
- `XTriggerEngine` 是 xcomm 中按 domain/phase 求值的 C++ 热路径。
- asyncio 是宿主；框架不拥有、停止或关闭宿主 event loop。
- asyncio 是唯一执行 Python Task/回调的调度器；不另建协程调度器，不要求用户替换
  原生 Task、Lock、Queue、Event 或 TaskGroup。Execution 的扩展只负责观察仿真工作
  并约束时钟推进。[观察器方案](architecture/asyncio-observer.md)已接入公共 Execution。

## asyncio 观察器决策（2026-09-29）

- 接受按宿主 loop 安装、按 Execution 目标 context 隔离的即时回调观察方案。记录
  入队、执行完成和取消，只用来判断下一次时钟推进或 DriveStable 采样是否可进行。
- 原生 asyncio 保留执行顺序与 Task/Handle/同步原语实现；不增设另一套执行队列。
- 外部异步库允许显式包装接入。域外任务不参与收敛判断，但共享调度入口的检查开销
  必须保留实测，不能把逻辑隔离表述为无性能影响。
- 调度归属不授予取消权。外部任务和用户 TaskGroup 的生命周期继续由原所有者管理；
  需要冻结仿真时使用显式 paused()。
- 公共入口为 Execution.external_task，收敛预算为 max_settle_rounds，超限抛出
  SimulationNotSettledError。不增加 ObservedExecution 公共类，不改变具体 Driver 的协议时序。
  原型已由正式实现与集成回归替代；第三方 loop 和完整性能矩阵仍需独立验证。

## 等待与传输

- 用户写 `event = await trigger`。
- asyncio 实际等待本次 Registration 持有的 `Future[XEvent]`。
- C++ 向 Python 传输固定布局 `XBackendHit`。
- XReactor 将 BackendHit 规范化为 typed XEvent。
- 同一个底层 occurrence 匹配多个 waiter 时，广播同一 event identity。

## phase 与 sampling

- XClock 拥有仿真推进顺序；每个 half-step 已完成 pin update、simulator eval、
  edge write、再次 eval 和 refresh，返回后即是框架定义的 stable phase。
- `RisingEdge` 和 `FallingEdge` 都是稳定 half-step 屏障。
- FallingEdge waiter 必须在下一 rising 推进前获得执行机会。
- Value/Condition 必须显式提供 `sample=`，或使用 Execution 中显式配置的 `default_sample`。
- 注册时已经为真的条件也要等到下一个指定 sampling phase；不在任意 Python 时刻立即返回。
- 一个稳定 phase 的全部命中必须作为完整批次返回。
- `XData.AsRiseWrite()/AsFallWrite()` 只设置写入模式；自动边沿提交要求该数据属于
  一个已由 `XClock.Add(xport)` 绑定的 `XPort`。生成 DUT 已完成这个绑定。
- `XClock.Add(xdata)` 只用于真实 clock pin，并会强制 immediate 模式；普通数据、
  PackedArray 元素和 SubDataRef 切片不得用它来建立 R/F 写入关系。
- standalone XData 若不在已绑定 XPort 中，不承诺 R/F 自动提交；需要立即写时使用
  `ImmSet`/immediate mode，需要边沿写时显式创建并绑定 XPort。
- HTTP、Queue 或其他外部 await 不隐式冻结仿真；暂停必须显式请求。
- 不提供 cocotb `ReadWrite`、`ReadOnly`、`NextTimeStep`，也不把它们列为未来
  capability。adapter 内部即使使用 simulator event-region callback，也必须收敛为
  XClock stable contract，不向 XReactor 用户泄漏。

## 核心框架与项目生成代码的边界

- 核心框架提供 XData、signal tree/metadata、Bundle、Driver/SignalDriver/Monitor/Agent、
  Trigger/Event/Reactor 和稳定采样机制，不要求通用 `Interface` 基类。
- 具体通道视图（例如 `ReadyValid`）可复用，但普通 Driver/Monitor 可直接绑定信号；
  驱动类按周期、脉冲、流水线等行为命名，不按 Bundle 形状命名。
- Picker 不通过复杂 RTL/命名解析自动推断 AXI、TileLink 或项目私有协议类型。
- 通用 Scoreboard、coverage 引擎及覆盖报告由框架提供；项目专用端口绑定、
  reference model、比较/采样规则及 fixture，由项目代码或编码助手根据 DUT 和规范组织。
- 公共 Agent 是接口实例，封装可选 Driver、具名 Monitor 和响应检查接线；connect(ref)
  连接独立模型，send/submit 保持底层驱动类型的执行方式，Execution 统一启停注册的
  Agent。模型的所有权与跨接口顺序属于环境。这里的 Agent 与编码助手不是同一概念。
- 这些项目专用产物不是核心框架的“未完成项”；核心层只保留生成它们所需的稳定、
  可组合 primitive。

## Trigger 前端

- `@xtrigger` 是统一的编译型入口。
- 返回 XExpr/XConditionSpec 时生成 ExprIR。
- 返回 XFsmSpec/XSequenceSpec 时生成 FsmIR。
- `@xsequence` 只能是可读性别名，不能形成另一套调度系统。
- 表达式使用可重载的 `& | ~`；不支持 `and/or/not` 的隐式转换。
- 不支持的 `@xtrigger` 内容在注册时明确报错，不得静默降级。
- `@pytrigger` 是显式 Python sampling predicate，只用于无法编译的最差路径。

## FSM

- 复杂状态条件优先下沉到 ComUseFsmTrigger，不因为“复杂”退回 Python。
- persistent FSM 第一版采用非重叠语义。
- 命中 phase 完整广播后 reset，从下一个 sampling phase 开始新一轮。
- 当前终态 phase 不同时作为下一轮起点。
- handler 是否完成不阻塞 FSM reset。
- 第一版不提供 overlapping FSM instance。

## 性能

- 未命中 phase 不创建 Python XEvent。
- 无 Python predicate/edge barrier 时允许 C++ 大 batch 推进。
- C++ 热路径不保存 PyObject/Future，不使用字符串 key，不逐 phase 分配。
- watcher 使用 `slot + generation`，拒绝取消后的迟到命中。
- 正常仿真吞吐优先，但 Pump 必须按 wall-clock quantum 有界 yield。

## M0 已冻结的补充契约

- XEvent 使用公共只读 dataclass 字段和少量 typed subclass；四态值使用
  `LogicValue`，不把同步状态塞回 Event。
- native 条件采用无符号、任意位宽语义；负常量以及超过目标 signal 位宽的常量在
  arm 阶段拒绝，不做隐式截断。条件依赖 X/Z 时该 sample 不匹配；ValueChange
  对窄值和宽值都比较完整 aval/bval，区分 0/1/X/Z。详见
  [数值语义](concepts/value-semantics.md)。
- Condition 默认发射模式为 `enter`，可显式选择 `each_sample` 或 `change`。
- `@on` 默认容量 64；lossless 溢出抛出 `SubscriptionOverflowError` 并使
  Execution 失败，latest 丢弃旧值必须显式配置。
- 一个 XCommClockBackend 当前代表一个 domain；命中停止该 backend。跨 domain
  的共同时间轴留到 M5。
- 同一 event loop 可运行使用不同 backend instance 的多个 Execution；同一个
  backend instance 不承诺共享推进。
- Python 最低版本为 3.11。

## 通用事务契约（2026-09-28）

- 通用 Scoreboard 属于框架；项目专用预期模型、reset/flush 和协议规则属于调用方。
- XTransfer.cancel 只撤销未接受输入；取消 waiter 不取消事务。
- Scoreboard 独占已绑定 Monitor 的消费与启停，跨批次保持运行，显式关闭时释放。
- 异步检查显式声明 clock 和 response timeout；drain/finish 要求仿真周期预算。
- 默认所有观察都是有效响应；只有固定延迟且显式 sampled 模式可以忽略窗口外样本。
- 不新增独立 scope、通用观察广播或回归管理层；沿用组件 context manager 与 pytest。

## Driver 提交与验证接口（2026-09-29）

- Driver 基类约定 send 返回 Awaitable[XEvent]，不强制返回 coroutine 或提供后台队列。
- AsyncDriver.send 调用时提交，返回接受时自动完成的 XTransfer；submit 返回待响应
  事务。保留 await send 的常用写法，不增加 submit_input 别名。
- SyncDriver、SingleCycle 具体驱动时序、协议 Driver 和响应关联规则保持各自契约；
  AsyncSingleCycleDriver 继承 AsyncDriver 的提交入口。
- 日常验证通过事务与组件生命周期表达输入重叠，不提供 parallel 接口，不把
  TaskGroup 或原生任务创建作为流水示例的用户编程要求。宿主集成仍兼容 asyncio。
- 资源适配仍在[讨论阶段](architecture/driver-resources.md)，不把原生锁的实现选择
  等同于最终用户接口，也不推断 ready/valid、缓冲容量或硬件仲裁规则。
- 移除独立 ReadyValidDriver 及其导出，暂不增加替代协议类。协议 Driver 应按提交
  方式派生自 SyncDriver/AsyncDriver，复用并发与清理；公共 Driver 类现为六个。
  ReadyValid 视图、Monitor 和既有协议 helper 保留，Cache 调用方由项目级 SyncDriver
  子类承接。
