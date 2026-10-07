# 验证框架能力审查与调整建议

> 后续变更：人工 pytest 功能标签、对应插件和完成率报告已移除。本文相关数字和
> 插件行为仅保留为当时的审查记录，不代表当前功能覆盖。运行命令与当前使用方式见
> [移除记录](coverage-without-test-tags-2026-09.md)及各项目 README。

评审日期：2026-09-28。基线：`HEAD 2be994d` **加当前工作树全部修改**，包括尚未提交的
Sync/AsyncDriver、XTransfer、Scoreboard、feature report 与 pytest plugin。
第 1～8 节保留评审时的提案与证据；用户随后收窄了实施范围。
实际已完成的改动、验证与未采纳部分见第 9 节，不应把整份提案视为已实现。

建议优先把现有组件组织成可靠的验证闭环：**驱动、观察、预测、匹配、检查、结束判定**。
目前基础能力已经相当完整，最紧迫的问题是边界语义与职责交叉；继续增加类和 DSL
不能替代这些工作。Python 可以减少框架仪式，但不能省略事务、时间和资源的明确契约。

## 1. 对照范围与判断方法

UVM 对照采用 Accellera 的 [UVM 1.2 User’s Guide](https://www.accellera.org/images/downloads/standards/uvm/uvm_users_guide_1.2.pdf)
中的稳定方法学：agent/driver/monitor/sequence、analysis 通信、end-of-test、配置、
checking/coverage 和 register layer（第 1～5 章）。这不是最新版本符合性认证；当前版本入口是
[Accellera UVM 下载页](https://accellera.org/downloads/standards/uvm)。
UVM 为这些需求提供约定和基础设施，具体协议、预测器与正确性判据仍由验证环境实现。
约束随机、covergroup、SVA 还涉及 SystemVerilog 语言及工具，不能都算成 UVM 类库功能。

以下能力和优先级来自本仓库代码审查；Python 替代方案是本次设计建议。
证据分为：代码已存在、本次回归通过、本次定向复现、历史真实 DUT 报告。
后者不等于当前版本已重新跑过 DUT。

## 2. 已有能力与仍缺的验证能力

| 验证需求 | 当前证据 | 剩余缺口与建议归属 |
| --- | --- | --- |
| 确定采样、仿真推进、异步共存 | `execution.py`、`reactor.py`、`backend.py`；stable phase、batch、取消、backend lease、HTTP 共存已有测试 | 保留核心；统一方法学组件的任务归属和失败传播。多个独立 Execution 不等于多时钟共同时间轴 |
| 端口绑定与数据快照 | `data.py`：Bundle、PackedArray、PackedView、BundleValue；任意位宽无符号与 X/Z 有 native 测试 | 已有，不必再加通用 Interface 基类；signed/cast、原生批量快照按需求扩展 |
| Driver / Monitor / agent | `components.py`、三类 driver 模块、`monitors.py`；信号 ownership、并发上限、资源锁、ready/valid capture | agent/env 用普通组合对象；收敛重复驱动行为，补生命周期及被动监视模式；consumer/responder 可先留协议包 |
| 场景编排与输入仲裁 | 普通 coroutine、SyncDriver/AsyncDriver 的 semaphore/lock | async 函数组合场景；优先级、公平性、独占 burst 等仅在用例需要时加策略，不预建完整 sequencer |
| 事务对象与响应关联 | `interfaces.Transfer` 是观察值；`transfers.XTransfer` 是待完成句柄；Scoreboard 有 FIFO、固定延迟、key 匹配 | 明确取消/flush/reset、超时、迟到、额外输出和重复输出；多 beat、多输出归并先由协议层实现 |
| 预测与数据核对 | Scoreboard 直接/异步模式、结构差异、accepted 时调用 expected source；e203 有独立参考模型 | 匹配/预测/比较与组件启停解耦；协议特定 reference model 继续在项目层 |
| 事务广播 | Reactor 对 trigger 广播，Monitor 用单个 `asyncio.Queue.recv()` 输出 | Queue 多消费者会分流，不是广播；缺复用同一不可变 observation 给 scoreboard、coverage、trace 的通路 |
| 结束判定 | Scoreboard `drain()`、`aclose()` 能传播部分失败并检查未完成请求 | 缺统一 finish 边界：额外输出、后台异常、未结束检查、drain deadline、最后响应后的观察窗口 |
| Reset / flush | e203 Harness 手动清空响应及 model 状态；XTransfer 可 cancel | 缺跨 driver/monitor/scoreboard 的 epoch 和事务处置契约；物理 reset 时序仍由 DUT 环境定义 |
| 协议与时序检查 | Expr、Sequence、FSM、Within、Hold；已有 ready/valid primitive | trigger 命中不等于 assertion；缺义务失败、未完成义务、reset disable、重叠请求及诊断的统一封装 |
| 随机与复现 | Cache/e203 用 `random.Random(seed)`，已有随机流量 | 缺统一 seed 派生、配置/版本/事务记录和回放约定；复杂约束求解使用可选适配，普通随机先用 Python |
| 功能覆盖 | `coverage.py` 已有 bins/cross、illegal/ignore/default、阈值、schema digest、merge、uncovered | 不应重新造覆盖库；时序覆盖可从事件流采样，跨运行元数据和定向补洞尚缺 |
| 功能点与回归报告 | FeatureTracker、pytest marker/plugin、HTML 与 LCOV 整合 | 已有计划映射；还缺 run/seed/版本身份、分片/重跑聚合、collection/中断有效性及 CI gate 契约 |
| 寄存器访问 | Bundle 是端口视图，无 register map/mirror/predictor API | CSR 密集 DUT 出现时做可选寄存器层：访问属性、reset 值、frontdoor、预测/镜像；不塞进调度核心 |
| 可复用验证资产 | Cache/e203 示例、native backend CI | 需要模板和跨 DUT 复用验证；VIP 互操作不是仅靠 Python 类型系统就自动获得的能力 |

代码路径均相对 `src/xreactor/`；测试位于 `tests/runtime`、`tests/interfaces`、
`tests/coverage`、`tests/integration`。真实环境位于 `examples/integration`。

## 3. Python 能省什么，不能省什么

| 可以省掉的框架形式 | 推荐写法 | 仍需保留的语义 |
| --- | --- | --- |
| factory、字段注册宏、复杂继承注册 | 构造器注入 class/callable，dataclass、Protocol | 替换实现显式可追踪；同一配置能复现 |
| config_db / resource_db 的全局路径查找 | typed config + 显式构造参数 + pytest fixture | 配置验证、作用域、默认值及 artifact 记录 |
| sequence / virtual sequencer 类层次 | async 函数、async iterator、TaskGroup；把多个 driver 作为参数 | 资源仲裁、输入接受与响应完成的区别、取消和错误传播 |
| 大量 build/connect/run/check/report phase 继承 | 构造、async context manager、显式 reset/run/finish | 启停顺序、drain 和 verdict；`TaskGroup` 本身不会终止永远运行的 monitor |
| objection 计数机制 | 提交截止点、显式 drain + bounded finish | 仿真不能过早结束；monitor 常驻也不能让测试永不结束 |
| TLM port/export/imp 包装层 | callable/Protocol 做同步通知，有界通道做异步消费 | 广播与竞争消费不同；快照、顺序、overflow、关闭仍需定义 |
| transaction 基类和字段宏 | frozen dataclass、tuple、普通 codec 函数 | 深层数据不可变；`frozen=True` 不会冻结内层 dict/list |

不要因为 Python 动态语言就删除 `XTransfer`：它表达接受和完成两个不同时间点，
是有效抽象。应当删除重复的状态拥有者，而不是删除有用的状态。
同样，已有 `Sequence` 表示**被观察的时序模式**，不应再让它承担激励场景执行器的职责。

## 4. 最优先的正确性问题

### 4.1 结束判定可能漏掉额外响应（已复现，P0）

`scoreboard.py:associate/_reconcile` 把无法匹配的 observation 留在 `_observations`。
`drain()` 只看提交时 watermark 前的 transfer 是否终止；`aclose()` 检查未完成 transfer，
没有将残余 observation 判失败。`_finish_pair()` 在最后一个请求完成后还会自动关闭 monitor。

定向实验：key=1 的请求被接受，先收到 key=99 的额外响应，再收到正确的 key=1 响应。
结果为 `checked=1, unmatched_observations=1`，`drain()` 和 `aclose()` 都成功。
这是当前实现不能直接承担严格事务守恒检查的证据。

建议保持 `drain()` 的 watermark 含义，另定义严格结束检查；无须让 drain 隐式等无限未来。
有效响应流上的 unexpected/duplicate 应失败；每周期采样流上的空闲值则应有显式 filter/window
策略。环境在最后输入之后选择有限观察窗口，再检查未匹配输入、输出及活跃义务。
Scoreboard 不应因自身暂时空闲而擅自停止被多个消费者使用的 monitor。

### 4.2 已接受事务的 cancel 只终止句柄，未完成关联清理（已复现，P0）

`XTransfer.cancel()` 触发 done callback；driver 会 retire，Scoreboard 的
`_on_transfer_done()` 只 set `_changed`，不移除 `_pending`。
实验中 PROCESSING 事务 cancel 后 `drain()` 成功，`unmatched_requests=1`，monitor 仍运行。
这不说明所有取消都坏了，但说明“句柄取消”等同于“协议 flush”尚未成立。

应区分取消等待者、撤销尚未接受输入、丢弃已接受结果和物理 reset。
为后两者定义 epoch/tombstone：旧响应允许丢弃还是应报错由协议策略决定；不能误配到
复用同一 tag 的新事务。仅有 Python epoch 也不能识别线上相同 tag 的迟到响应，协议必须
保证 reset 清空、等待旧事务排空或提供可区分标识。

### 4.3 匹配窗口不是事务 deadline（已复现，P0）

固定延迟关联只判断 `observed.tick - accepted.tick == latency_cycles * 2`。
迟到的响应留在缓存；漏响应不会自动触发失败。实验中 latency=1，accepted tick=2，
response tick=6，`drain()` 需外部 wall timeout 才结束；随后 close 报 incomplete。

应分别定义 admission deadline、response deadline 和整个用例 wall watchdog。
固定延迟错过应有明确诊断；变延迟采用协议预算。deadline 必须由 simulation registration
推进并触发，不能等下一个 response 才检查，否则完全漏响应仍挂住。
`tick * 2` 规则应集中到单时钟时间换算边界，未来 domain 扩展不能散落修改 matcher。

### 4.4 生命周期和后台异常尚未统一（静态证据，P0）

`Execution.__aexit__()` 管 pump/reactor/backend execution state；
AsyncDriver 和 Scoreboard 各自创建 task，各自 close；SignalDriver 则同步释放 ownership。
Scoreboard 的异常能从 await/drain/aclose 到达测试，但前提是调用方确实走这些边界。
不能把“Execution 已退出”当成“所有方法学任务都完成且已检查”。

建议先以 fixture + `AsyncExitStack` 落地唯一生命周期拥有者，统一登记后台 task、
close 和 finish。默认顺序：停止提交 → 等待已接受工作（带预算）→ 完成观察窗口 →
检查 → 关闭观察/驱动任务 → 退出 Execution。异常路径跳过 drain，仍清理全部资源并
保留原始失败及清理失败。采用 TaskGroup 时需显式停掉无限 worker；不得取消宿主外部 task。
若两个真实环境都证明这层通用，再收成小型可选 scope；不要创造第二个调度内核。

## 5. 让已有实现更简洁

### 5.1 驱动的两个维度应正交

`SyncDriver` 和 `AsyncDriver` 都有 semaphore、resource_lock、`_drive_one()`；
Sync/AsyncSingleCycleDriver 又重复绑定、编码、写入、等待周期和 idle。
ReadyValidDriver 另用 Lock 和副作用式 encoder，而 SingleCycle 的 encoder 返回值。
这些不是三个独立的硬件协议维度。

建议收敛为“一份协议驱动行为 + 可选提交队列/响应跟踪适配器”：
`await send(request)` 仍表示输入完成；排队提交返回 handle。保持现有入口作薄适配，
先统一内部实现，再评估是否需要公共重命名。`Sync` 当前仍是 async def，文档应突出
它表示调用方等待输入完成，避免被理解为阻塞 event loop。

不能机械合并：AsyncSingleCycle 的 idle 可以依赖上次 request，并在启动/quiesce 写 idle；
SyncSingleCycle 当前不同。先明确这些策略，再提取复用。保留 AsyncDriver 串行 worker
复用协程的优化；代码注释已指出逐事务 task 切换可能错过写相位。

验收比较同一 traffic 在两种提交方式下的接受顺序、payload、backpressure、cancel idle、
吞吐；不能仅用最终数值相同证明时序等价。异步驱动应可供响应 collector 使用，不要求
必须经过 Scoreboard 才能回收 capacity。

### 5.2 Scoreboard 承担了过多独立职责

当前一个类负责 submit、task 管理、monitor 启停、预测、匹配、结构比较、history、
异常去重、quiesce 和 drain。它还与 driver 共同管理 retire，与 XTransfer 共同管理失败观察。
建议保留简单的 `check()` 用户入口，内部拆分职责：

- 比较器：只返回差异或抛断言，不拥有 task；默认 mismatch 路径目前会算两次结构差异，
  可以复用第一次结果，自定义 compare 仍保留其异常 cause。
- 关联策略：FIFO、固定延迟、key；拥有 pending/deadline/epoch，默认一对一。
- 预测器：接受不可变 request observation，返回 expected，不控制 driver 生命周期。
- scope/连接层：唯一管理源的启停、广播和 finish；项目环境显式组装。

优先做私有模块拆分，不要立刻公开更多 ABC。`AcceptedDriver` 的 submit+retire+quiesce
契约当前适合主动请求闭环，但被动验证应能只接入 request/response observations。
对第三方 master、多个源或 DUT 主动发起事务，driver 报告的 accepted 也不应是唯一真相。

### 5.3 复用队列策略，而不是再套一层 event bus

Reactor subscription 与 ReadyValidMonitor 各实现了一次 bounded queue、latest/lossless
和 overflow；Scoreboard `_events` 却是无界 Queue，`_observations` 也是无界列表。
Driver 的 capacity 因此并不是全链路内存上限。

先统一私有队列策略和关闭契约，再提供必要的 observation fanout：同步、不可 await 的
capture 只做一次，短同步 sink 可直接调用；异步消费者各有独立有界队列，保持顺序。
scoreboard/checker 默认 lossless 且溢出失败；latest 仅用于明确允许丢样的显示/统计。
两个消费者不应直接各自调用同一个 `recv()`，否则各拿到一部分数据。

ReadyValid 的双阶段 capture 有实际时序目的，不能为了减少队列层数就删掉：
它在 DriveStable 保存 payload，在下一 RisingStable 形成接受事件。
`drive_ready_valid()` 仍在 falling/refresh 后判断 ready；应补齐多个 Python writer 的
注册顺序、组合 ready、背靠背、取消等 native 差分测试，证明 driver/monitor 接受判据一致。
这是待扩充验证，不是本次已经证实的握手错误。

### 5.4 对象与历史记录边界

`Transfer` 与 `XTransfer` 名称容易混淆，但语义不重复：前者是 observation，后者是
有生命周期的 handle。可先在文档使用 Observation / TransferHandle 角色名，不必立即改 API。
XTransfer 直接保存 request 引用，任意 decoder 也可返回可变对象；应要求提交对象不可变，
或允许显式 snapshot hook，避免排队后被调用方修改。不要默认无条件 deepcopy 一切对象。

Scoreboard `_transfers` 持有全部历史 request/expected/response handle；status 每次遍历，
drain 复制历史前缀。建议累计计数 + 活跃表 + 可选有界历史/流式 trace，仍用提交序号保持
watermark 语义。key 关联可以用索引替代反复遍历；先测负载再优化一般 matcher。

MemoryBackend 与 native backend 的两套语义实现有测试价值，不应为了行数去掉；
应共享输入契约和差分用例。coverage 定义/实例/报告也有不同职责，不应合成一个大对象。

## 6. 还需要补齐，但不应扩大核心的能力

**时序检查。** `MemoryBackend._advance_sequence()` 中 Within 超限会重启匹配，
Hold 失配会重置计数；它们是模式识别语义，不能直接声称“协议违例已检查”。
增加小型 checker/expect 封装：明确 start、deadline、failure、reset disable 和 finish
时 outstanding obligations；继续复用 Trigger/FSM。多个重叠请求需要每请求义务或 ID
关联，当前非重叠 persistent FSM 无法代替完整重叠 assertion 语义。

**Reset。** 提供共享 epoch 和取消原因约定，让环境函数协调各组件；不要求增加一整套
runtime phase hierarchy。reset 是否清 coverage、镜像、参考模型是显式策略，不能总是
清空所有数据。验收必须包含背压中、等待响应中、tag 重用和旧响应到达后的 reset。

**可复现激励。** 先规范根 seed、按稳定名字派生的独立 RNG、有效配置、框架/RTL/backend
版本和 request trace。不能用进程随机化的 Python `hash()` 派生 seed。激励和背压用
不同随机流，增加 monitor 不应改变 traffic。seed 不能保证外部 I/O 时序或修改后的随机
算法一致，因此失败保存输入序列与相关外部控制事件。缩减失败序列时重新初始化 DUT/model。

**报告可信度。** 保留 pytest verdict、功能点完成率、functional coverage、RTL coverage
四者的独立含义；合法覆盖命中不等于功能检查通过。现有 FeatureTracker 按 nodeid 存结果，
plugin 走进程内 makereport；尚不能据此承诺 xdist/跨 seed 聚合。
引入 run_id/seed/config/schema/version 和会话完整性字段；对 collection error、提前中断、
fixture teardown error、重跑、分片重复与缺失先定义合并规则，再加 CI gate。
已有 CoverageDatabase 的 schema 校验和 merge 应复用，HTML 只渲染，不承担 verdict 推导。

**寄存器与 VIP。** 有 CSR 用例再建立可选 register adapter，支持字段访问属性、reset、
W1C 等副作用和按总线观察更新镜像；任意 RTL backdoor 取决于生成 DUT/backend 能力。
协议绑定、reference model、复杂多 beat 对应关系留在项目或协议包。框架提供可组合
primitive 和测试模板，使生成代码不再复制队列、取消、错误处理。

**性能与多时钟。** 单时钟语义已成立，多 domain 时间、signed IR、zero-copy、GIL release、
owner thread 均按需求进入。当前 `clear_execution_state()` 已调用 native
`ClearExecutionState()` 并清 program cache，不能再说只能 backend.close 时清理。
单次长 Execution 中唯一 IR 的增长仍值得量化；与 Python history/queue 增长一起测量，
分别报告高水位和 live state。先基于测量选择缓存上限、arena 或引用回收。

## 7. 建议的落地顺序与验收

以下按依赖顺序分成可审查变更，不是工期承诺。先修验证结果可靠性，再做结构收敛，
最后扩功能。每个实现切片都按 CONTRIBUTING 补对应测试、文档和必要的真实用例。

| 阶段 | 具体交付与主要落点 | 完成门槛 |
| --- | --- | --- |
| A：校准契约与文档 | current-implementation、decisions、roadmap 区分通用方法学与项目专用代码；记录接受/完成、drain/finish、cancel/reset、源所有权 | 新增 Scoreboard/plugin 不再被写成不存在；Python 最低版本与 pyproject 的 3.11 一致；历史结果标日期 |
| B：严格结束和事务守恒（P0） | scoreboard/transfers：unexpected/duplicate 策略、取消清理、response deadline、finish；所有容器有容量或保留策略 | 本文三个复现转成回归；漏响应、晚响应、额外响应、tag 冲突、cancel 后新请求均有确定 verdict；失败上下文含 request/tag、accepted/observed tick |
| C：统一生命周期（P0，基于 B） | 先在 fixture/env 用 AsyncExitStack/TaskGroup 组织 stop/drain/check/close；必要时提取小型 scope；统一 monitor 的源所有权 | 无 await handle 的后台异常仍使测试失败；成功、mismatch、timeout、外部取消后 task/watcher/ownership 均归零；宿主 HTTP task 存活；原始失败不被清理错误覆盖 |
| D：收敛驱动与观察流（P1） | drivers 私有复用、value encoder、observation fanout；Scoreboard 被动接入；活跃表和有限 history | send/submit 共用协议实现；多个 sink 看到相同接受序列；慢消费者显式溢出；native 时序差分通过；每事务 task 数和吞吐不明显退化 |
| E：Reset、checker 与复现（P1） | epoch/取消原因、expect/checker、RNG/运行 manifest/trace、feature aggregation/gate | reset 中断和 tag 重用无串扰；义务超时/结束未完成可诊断；固定输入可回放；分片/中断不会误报完整通过 |
| F：真实环境验收与资源门槛 | 将 Cache/e203 中一条完整请求流迁到共同契约；运行 native 回归、真实 DUT 随机与背压、长运行/HTTP benchmark | 相同输入下请求/响应/模型 verdict 与迁移前一致；已知 RTL 缺陷仍可复现；常规完成事务不使 live Python 状态线性增长；唯一 IR 增长单独测量并处理 |
| G：需求触发的扩展 | CSR adapter、复杂仲裁、多时钟、signed/cast、native snapshot/zero-copy | 必须有真实 DUT/性能证据、明确能力声明和独立验收，不阻塞前六步 |

F 的小型真实用例应在 B～E 每步随行运行，最终再做整体长测，避免纯替身测试掩盖调度问题。
对于性能，保留原有 coverage A/B 方法；新的阈值应由同机器、同 DUT、同波形与 coverage
设置的基线决定，不从 no-op backend 推导真实吞吐承诺。

推荐最终职责关系：

```text
pytest / typed config / scenarios / reference model
                   |
       环境 scope：启动、reset、finish、artifact
                   |
driver -> DUT -> observation -> predictor / matcher / checker / coverage / trace
                   |
       Bundle / Trigger / Reactor / Execution
                   |
           xcomm stable phase + native engine
```

scope 管资源，Reactor 管事件，matcher 管事务对应，model 管功能预期。
这四种所有权分清后，新增协议应主要写“如何驱动、何时接受、如何预测”，而非复制调度代码。

## 8. 本次验证记录及限制

运行：`PYTHONPATH=src python3 -m pytest -q --require-xspcomm`。
结果：**144 passed in 0.68s**，native binding 由现有本地构建提供。
这证明现有测试基线通过，不能证明下面新发现的边界已经正确。
本次未重新构建 DUT，未重跑 Cache/e203 完整 campaign，也未重新量测性能。

三项定向实验复用了 `tests/runtime/test_scoreboard.py` 中 FakeDriver/FakeMonitor。
以下保留改动前草案 API 的历史复现脚本；当前 API 已要求显式时间预算，
请运行第 9 节所列回归。历史脚本验证方法学层行为，不验证硬件时序：

```python
import asyncio
import runpy

n = runpy.run_path("tests/runtime/test_scoreboard.py")
Scoreboard, Driver, Monitor, Request, Response = (
    n[k] for k in ("Scoreboard", "FakeDriver", "FakeMonitor", "Request", "Response")
)

async def probe():
    for case in ("extra", "cancel", "late"):
        d, m = Driver(), Monitor()
        options = ({"request_key": lambda r: r.tag,
                    "response_key": lambda r: r.tag} if case == "extra"
                   else {"latency_cycles": 1} if case == "late" else {})
        sb = Scoreboard(case).bind(object(), driver=d, monitor=m, **options)
        t = sb.submit(Request(1, 10), expected=Response(1, 10))
        d.accept(t, 2)
        if case == "extra":
            m.observe(4, Response(99, 99))
            m.observe(6, Response(1, 10))
        elif case == "cancel":
            for _ in range(5):
                await asyncio.sleep(0)
            t.cancel()
        else:
            m.observe(6, Response(1, 10))
        try:
            status = await asyncio.wait_for(sb.drain(), 0.2)
            print(case, "drain passed", status.unmatched_requests,
                  status.unmatched_observations, "monitor", m.started)
        except TimeoutError:
            print(case, "external timeout", t.state.value)
        try:
            await sb.aclose()
            print(case, "close passed")
        except Exception as error:
            print(case, type(error).__name__)

asyncio.run(probe())
```

本次实测：extra drain/close 均通过但剩 1 个 observation；cancel drain 通过但剩 1 个
pending request 且 monitor 仍启动；late 需外部超时，close 报 ScoreboardIncompleteError。

已核对的文档漂移：`current-implementation.md` 仍保留 99/99 历史数字、旧 program
生命周期说明和将通用 Scoreboard 排除出核心的表述；`delivery/roadmap.md` 也未纳入新增
方法学闭环；`decisions.md` 最低 Python 版本仍为 3.10。先保留历史与冻结决策，后续 A
阶段明确更新范围，避免把本次提案误当成已批准和已实现的新架构。


## 9. 事务机制实施记录

2026-09-28，按用户批准的收窄范围实现。未新增 VerificationScope、ObservationStream、
seed/回放/campaign 等回归管理设施；没有修改 ready/valid、reset/flush 或具体协议时序。

完成项：

- XTransfer 只允许取消 PENDING；取消 waiter 不影响事务或确认其失败。
- Scoreboard.bind 显式接收 clock、response_timeout_cycles；drain 和 finish 显式接收
  timeout_cycles。固定延迟错过目标 rising phase 后主动失败；下一个 falling barrier
  暂停推进、处理就绪的 source 通知，再检查 deadline，避免误伤同周期响应。
- 默认所有 observation 都是有效响应；残余输出在 finish/aclose 报错。固定延迟的
  sampled=True 明确忽略窗口外样本。finish 封闭提交、排空并完成有预算的观察窗口。
- Monitor 跨批次保持启动，由 Scoreboard 独占消费并在关闭时释放。context manager
  保留原始失败及独立清理失败；Driver 生命周期由外层管理。
- Scoreboard 的 active table 与累计统计替代全部历史列表；默认 capacity=64 限制
  在途请求和未匹配输出。删除中转事件队列及 coordinator task，两个 source pump
  同步更新匹配状态，关联逻辑单独放在私有模块。默认差异只计算一次。
- Sync/AsyncDriver 共用私有并发控制、resource_lock 和返回事件校验。串行 worker
  继续复用，取消单个未接受输入不会丢失后续工作。send 只跟踪接受，不留下响应容量；
  submit 的句柄由调用方/Scoreboard 完成。关闭时遗漏已接受响应报 DriverIncompleteError。
- 更新指南、公共导出、现状与路线图；新增协议无关的可运行事务示例。

验证：

```bash
# 当前工作树本地安装在临时 venv，使用现有 native xspcomm 构建。
PATH=/tmp/xreactor-verification-venv/bin:$PATH python3 -m pytest -q --require-xspcomm
PATH=/tmp/xreactor-verification-venv/bin:$PATH mkdocs build --strict
/tmp/xreactor-verification-venv/bin/python3 examples/transactions/scoreboard.py
```

- 完整回归：**180 passed in 0.80s**；评审时基线为 144 项。
- 文档：严格模式构建通过。
- 示例：checked=8, passed=8, completed=8。
- tests/runtime/test_scoreboard.py 覆盖额外/重复、乱序、先观察后接受通知、漏响应、迟到、
  drain watermark、结束观察窗口、启动失败、外部取消及 200 笔完成请求的对象释放。
- tests/interfaces/test_async_driver.py 覆盖串行/重叠输入、接受时序、worker 启动前及
  驱动中的取消、输入清理失败，以及无需响应 collector 的 send。
- tests/integration/test_transaction_lifecycle_native.py 新增 7 项 native XClock 用例，
  覆盖 0/1/3 周期延迟、两种注册顺序、同 phase 延迟交付与漏响应资源清理。
- 原有协议、采样、coverage、HTTP 等回归均通过；本轮未重新构建 RTL 或重跑完整
  Cache/e203 campaign，也未宣称真实 DUT 吞吐改善。

实现限制：异步 Scoreboard 当前使用单 XClock 的 rising-stable 接受/观察时间戳；
Monitor 必须及时交付采样记录，不支持先等外部 I/O 或任意未来仿真事件再回送旧时间戳。
时钟检查当前每 falling phase 返回 Python；它确保没有响应时仍能超时，但实际长运行
吞吐仍需专门测量，不把这次正确性回归当作性能基线。
