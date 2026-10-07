# 持续随机化在硬件验证中的作用与 XReactor 引入方案

首次调研日期：2026-09-30；生态和实施建议更新于 2026-10-01。本文面向 XReactor 维护者，说明随机化如何探索硬件状态和时序、Python 能提供什么，以及如何在当前验证组件之上引入可复现的持续随机激励。仓库事实来自当前工作树；外部机制来自文中链接的官方文档。**引入方式、接口和阶段安排是本文建议，尚未成为框架公共能力。**

建议将 Hypothesis 在线生成引入有状态正确性测试，同时建立有预算的案例工厂和显式激励重放；独立 RNG 和可选约束求解器用于需要指定分布的 CRV/stress 配方。事务生成位于 Agent 上方，参考模型仍按真实接受通知推进，Driver 保持协议时序，Execution 继续统一推进仿真。[Hypothesis 扩展调研](hypothesis-stateful-randomization-research-2026-10.md)已验证 await 后继续按状态生成、故障简化与重放，以及 HypoFuzz 的功能事件桥接；本文件保留首次标准库探针作为基线。两轮均未测量真实 RTL 上的成本或收益。

## 术语和研究范围

本文的研究重点是**运行中持续生成有约束、依赖状态的随机事务**。“持续随机化”在本文中指仿真期间反复产生新激励，并根据状态或观测决定后续动作。它与下面两个概念相关，但分别解决不同问题：

| 概念 | 决定什么 | 例子 |
| --- | --- | --- |
| 约束随机化 CRV | 一次生成哪些合法且有意义的值 | burst 长度、地址对齐、合法 opcode |
| 运行中的持续生成 | 何时生成下一笔以及如何利用历史 | 写后读、填满队列后制造反压、逐步建立 dirty eviction |
| 多 seed 持续回归 | 多次独立运行探索哪些路径 | 固定复现 seed 加 nightly 探索 seed |

方案围绕同一次 Execution 内的生成闭环展开：取得可信状态快照，构造合法候选，按策略抽样并提交，在明确反馈点更新下一轮决策，直到达到目标或预算。状态快照和资源预留决定下一笔允许做什么；随机策略决定在允许的动作中怎样探索。

一次测试开始前生成整张列表也能完成 CRV；运行中持续生成增加了反馈和状态依赖。约束随机化为这条主线提供生成方法，seed 回归与重放提供复现和探索管理。另一个不同问题是 DUT 上电状态、仿真器 X 初始化或 fault injection 的随机化，它们需要单独记录配置和 seed；Python 激励 seed 不会自动控制这些来源。

## 随机化在硬件验证中的作用

硬件问题常发生在状态、数据和时序共同满足条件时。定向测试适合建立已知场景，随机测试能组合更多路径；约束则把计算预算集中到协议允许或测试计划关注的区域。以下是针对本项目用例的分析，不是随机测试能证明正确性的承诺。

| 随机维度 | 可以探索的行为 | 必须保留的边界 |
| --- | --- | --- |
| 数据和字段 | 零值、最大值、mask、地址别名、不同指令长度 | 位宽、有符号语义、有效字段组合 |
| 请求间隔和响应延迟 | 空拍、背压、满队列、请求响应重叠 | 用仿真周期表达延迟，给等待设置上限 |
| 有历史的操作 | 重复读写、同 set 冲突、dirty writeback、顺序取指 | 约束依据已确定的模型状态和项目规格 |
| 多接口动作组合 | 仲裁、竞争、并发响应 | 项目定义同 tick 的顺序和资源占用 |
| reset 和错误注入 | pending 输入、在途响应与恢复路径 | 项目明确撤销、退休和检查器清理语义 |

激励、检查和覆盖缺一不可。随机事务让 DUT 经历行为，参考模型或断言判断行为是否正确，覆盖模型回答哪些计划中的行为实际发生。生成了某个请求，只能证明生成器做过选择；不能据此给 RTL 内部行为计一次命中。

假设每笔独立激励命中某事件的概率为 p，N 笔后至少命中一次的概率为 `1-(1-p)^N`。若 p 为百万分之一，10,000 笔的命中概率仅约 1%。这是简化模型；有状态硬件上的样本常有关联，实际情况还取决于是否建立了前置状态。因此，“持续增加随机量”不能代替构造前置状态、调整分布和补充定向测试。

对 Cache，应把“同 set 多 tag、产生脏行、引发替换”视为一个可生成的动作序列。对 e203，应把目标存储区、上一 PC、顺序关系、holding 和 stall 联合建模。只独立随机各字段容易产生无意义组合或长期避开关键机制。

## SystemVerilog 和 UVM 如何实现

SystemVerilog 提供随机字段与约束表达；UVM 把事务、sequence、driver、monitor 和检查组件组织起来。Accellera 的 UVM 1.2 指南展示了约束分层、控制参数以及创建、可选随机化、发送 sequence item 的流程。这里引用的是方法学参考，并不把 2015 年的 1.2 指南当作当前标准版本声明。[Accellera UVM 用户指南](https://www.accellera.org/images/downloads/standards/uvm/uvm_users_guide_1.2.pdf)，主要参见 3.1、3.10、3.12 和 4.10。

持续性来自 sequence 中的循环或动作编排：每次形成事务，通过约束得到合法字段，再交给 driver。随机字段不会在仿真时间推进时自动不断变化。工程上必须检查随机化失败，区分协议合法性约束与场景偏好，并记录用于复现的输入。

下面是本文编写的 SystemVerilog 示意片段：事务限制对齐、长度和跨页关系；循环每笔重新创建并随机化事务。class 放在定义区，循环放在 sequence 的 body 中；构造函数和环境接线省略。该片段用于解释实现方式，本次没有运行 SystemVerilog 编译。

```systemverilog
class BurstReq extends uvm_sequence_item;
  rand bit [31:0] addr;
  rand int unsigned beats;
  constraint legal {
    beats inside {[1:16]};
    addr[2:0] == 0;
    int'(addr[11:0]) + 8 * beats <= 4096;
  }
endclass

// sequence body 内
BurstReq req;
repeat (count) begin
  req = new();
  start_item(req);
  if (!req.randomize() with { beats inside {1, 2, 4, 8, 16}; })
    `uvm_fatal("RAND", "burst randomization failed")
  finish_item(req);
end
```

长度候选是这次场景的额外限制；基础 legal 约束保持生效。start_item 和 finish_item 负责 sequence 与 driver 的交互，具体引脚保持和握手仍由 driver 完成。

常见机制包括 `randomize() with` 的临时约束、`rand_mode()` 和 `constraint_mode()` 的开关，以及用于控制解分布的求解顺序。指南说明了前两类控制；PyVSC 官方文档也明确对照了 SystemVerilog 的 `solve a before b`。[UVM sequence 控制](https://www.accellera.org/images/downloads/standards/uvm/uvm_users_guide_1.2.pdf)，[PyVSC 求解顺序](https://pyvsc.readthedocs.io/en/latest/constraints.html#solve-order)。

对 XReactor 的启示是保留“合法性、生成策略、协议驱动、实际检查”的职责分离。具体语法、工厂和 phase 类层级不必成为 Python 用户使用随机化的前提。

## Python 中随机化提供什么

### 随机数与合法事务是两层能力

Python 标准库 `random` 提供伪随机抽样、独立 `Random` 实例和 `getstate`、`setstate`。它不自动求解硬件约束。官方复现说明还指出，多数抽样算法可能随 Python 版本变化；记录 seed 不构成跨版本、跨代码修改的完整重放保证。[Python random 文档](https://docs.python.org/3.11/library/random.html)。

下面是本文建议使用的生成方式分类：

| 方法 | 适用情况 | 代价和失败含义 |
| --- | --- | --- |
| 构造式抽样 | 对齐、范围、已知依赖关系 | 先选长度，再直接选合法地址；需要写清解分布 |
| 拒绝采样 | 合法集合不稀疏的简单谓词 | 若合法比例为 p，平均需要约 1/p 次尝试；设尝试上限 |
| 有限枚举后抽样 | 小域、少数合法动作 | 成本和内存随合法集合增长；候选顺序必须稳定 |
| CSP 或 SMT 等求解器 | 多字段耦合、复杂列表或算术关系 | 适配其类型、seed 和失败状态；测量实际求解时间 |

普通 Python 函数 `is_legal(request, state)` 很适合校验和拒绝采样，但不是自动可编译的符号约束。它可能调用任意代码、读取外部状态或依赖副作用。若未来需要声明式 DSL，应明确支持的表达式和整数语义；不能承诺把任意 lambda 转成求解器程序。

Python 的整数和容器适合参考模型、事务和策略，但硬件宽度需要明确处理。例如无符号 w 位值应位于 `0 <= value < 2**w`；有符号解释、溢出、移位和 mask 由项目定义。普通整数事务也不会自行获得 X/Z 语义，未知值测试应使用框架四态数据或明确的编码。

### 合法解与目标分布要分别定义

考虑自己构造的例子：a 为 1 bit，b 为 8 bit；a=0 时要求 b=0，a=1 时要求 b 在 1 到 255 之间。共有 256 个合法组合。若均匀选择合法组合，a=0 的概率是 1/256；若先等概率选择 a，再选择合法 b，a=0 的概率是 1/2。两种生成器都满足约束，但探索能力不同。

因此，协议硬约束描述允许集合，场景权重描述希望怎样探索。burst 长度先按权重选择，再选择合法起始地址，就明确采用“长度优先”的分布。求解器随机选一个模型也不应被直接称为均匀抽样。PyVSC 文档给出了 `dist` 和 `solve_order` 控制分布的接口；具体适配仍需统计验证。[PyVSC 分布约束](https://pyvsc.readthedocs.io/en/latest/constraints.html#dist)。

### 可选生态能力及适配取舍

下表中的机制来自官方文档；“建议用途”是针对 XReactor 的判断。首次调研未安装第三方库；后续已在隔离研究环境实测 Hypothesis、HypoFuzz 和 constrainedrandom，详见[扩展调研及结果](hypothesis-stateful-randomization-research-2026-10.md)。未进行性能排名。

| 能力 | 已核实的机制 | 建议用途及限制 |
| --- | --- | --- |
| 标准库 random 加 dataclass | 独立 RNG、普通对象、显式函数 | 压力配方和辅助随机流的基础，保持核心零第三方运行依赖 |
| Hypothesis | 策略与在线 draw、有状态动作、性质搜索、失败简化与重跑 | 有状态正确性测试优先路线；st.data 可 await 后生成，RTL 仍需逐案例初始化和执行预算 |
| HypoFuzz | 持续搜索 corpus、Python 分支及 event 虚拟分支反馈 | 在 Hypothesis 场景上接实际功能 bin；已测组合使用同步 executor 包裹完整异步执行 |
| constrainedrandom | `RandObj` 接受 `random.Random`；变量域、约束函数和搜索限制 | 用于需要声明式 Python 约束的项目适配；达到 effort limit 的失败不能直接解释为数学无解 |
| PyVSC | 随机类型、约束块、临时约束、soft、dist、solve_order | 用于需要 SV 风格建模的复杂事务；把其对象转换成项目普通事务后提交 |
| cocotb-coverage CRV | `Randomized`、随机域、函数约束、临时约束与前后处理 | 已采用该库的项目可评估接入；其权重和 soft 语义需逐项对照，不直接等同于其他求解器 |
| cocotb | Python 协程仿真环境，记录并设置随机 seed | 参考运行管理经验；seed 管理本身不承担字段约束求解 |

来源：[Hypothesis 有状态测试](https://hypothesis.readthedocs.io/en/latest/stateful.html)、[失败重放](https://hypothesis.readthedocs.io/en/latest/tutorial/replaying-failures.html)、[HypoFuzz 行为反馈](https://hypofuzz.com/docs/manual/behavior.html)；[constrainedrandom 使用和失败诊断](https://constrainedrandom.readthedocs.io/en/latest/howto.html)；[PyVSC 约束](https://pyvsc.readthedocs.io/en/latest/constraints.html)；[cocotb-coverage CRV 参考](https://cocotb-coverage.readthedocs.io/en/latest/reference.html#module-crv)；[cocotb seed 管理](https://docs.cocotb.org/en/stable/library_reference.html#cocotb.RANDOM_SEED)。

本文建议的求解器适配返回状态至少区分成功、已证明无解、预算耗尽和适配错误。搜索超限不能让框架悄悄放松硬约束。求解器耗时应受控制：一般事务保持同步短计算；昂贵求解应在项目明确的暂停或外部计算边界完成，再交回 immutable 请求。把求解丢入线程不会自动解决 seed、线程安全、状态快照和墙钟时序问题。

Hypothesis 可以生成有状态动作并简化失败序列，但复现要求案例状态可靠复位。外部状态和不能重复的行为会导致 flaky failure；失败数据库也不能替代永久回归样例。[Hypothesis 不稳定失败](https://hypothesis.readthedocs.io/en/latest/tutorial/flaky.html)，[重放与数据库边界](https://hypothesis.readthedocs.io/en/latest/tutorial/replaying-failures.html)。后续实测表明，st.data 支持 Execution 内 await 后继续 draw，不必预生成完整动作计划。普通 pytest-asyncio 可直接运行异步测试；本次 HypoFuzz 组合则需同步入口运行整个异步案例。不能在已运行的 asyncio loop 里嵌套 `asyncio.run()`；RuleBasedStateMachine 的同步规则也不能直接当异步规则使用，详见扩展调研。

## 当前仓库已有能力和缺口

下列结论按 2026-09-30 工作树源码核对，不以历史交付报告替代当前代码。

| 位置 | 当前事实 | 可复用能力或需要补充的部分 |
| --- | --- | --- |
| [e203_xreactor_env.py](../../examples/integration/e203/e203_xreactor_env.py) 的 random_requests 和 run_campaign | 用一个局部 Random 预生成列表，联合选择 PC、顺序关系、目标区、错误和 delay；随后逐笔 fetch | 已有合法关系建模；事务和延迟共用抽样流，尚未统一派生和重放 |
| [cache_functional_xreactor.py](../../examples/integration/cache/cache_functional_xreactor.py) 的随机段 | 在线选择同 set 多 tag 地址、读写和 mask；独立 logical 字典给出预期，并进行写后读 | 已有状态依赖和局部 RNG；不是通用随机化设施，也不代表所有 Cache 并发状态都已探索 |
| [verification_flow.py](../../examples/transactions/verification_flow.py) | 每次运行独立目录，保存 seed、Python 版本、预算、状态与覆盖报告，失败时仍导出 | 扩展 manifest 和 trace 的起点；没有自动 seed 矩阵或 stimulus replay |
| [agent.py](../../src/xreactor/agent.py) 与 [transfers.py](../../src/xreactor/transfers.py) | 接受通知推进模型，send 等接受，submit 返回待检查响应的 XTransfer；drain 和 finish 有周期预算 | 持续生成可直接调用；禁止以 submit 当作模型接受 |
| [async_drivers.py](../../src/xreactor/async_drivers.py) | 有 capacity 和 max_active；满容量提交报错，接受前可以取消 | 生成器须限制提交窗口；不能把 submit 当作自动等待容量的队列 |
| [coverage.py](../../src/xreactor/coverage.py) | CoverGroup 可 sample、sync、report，支持计数、阈值、排除和采集状态；report 会同步 native 计数 | 有反馈读出基础；尚无从缺口自动生成请求的通用算法 |
| [pyproject.toml](../../pyproject.toml) | 核心 dependencies 为空，Python 至少 3.11 | 简单随机化可只用标准库；第三方求解器适配按需加载 |

[既有框架评审](framework-review-2026-09.md)已提出独立 RNG、稳定 seed 派生和 request trace。这次将它们细化为生成、状态、反馈与回放契约；没有改动核心 API 或把这些建议标记为已实现。

## 软件原生的引入架构

“软件原生”在本方案中有具体含义：事务使用普通 Python 类型，合法性与策略使用函数或可选求解器，序列使用 generator 或 coroutine，运行组织使用 pytest 和项目配方。时钟推进、信号 ownership 和 phase 仍由已有框架处理。

```text
项目配置和根 seed
    -> 独立 RNG 与场景策略
    -> Python 事务生成器 或 可选求解器适配
    -> 有限窗口的协程 campaign
    -> Agent -> Driver -> DUT
                   接受通知 -> reference model -> Scoreboard
    DUT -> Monitor 或 native coverage -> 实际观测与覆盖计数
    批次边界的状态与覆盖快照 -> 场景策略

运行配方保存 manifest、激励决策、接受和完成记录以及覆盖报告
```

建议职责分配如下，名称代表设计角色而非新增的公共类：

| 层次 | 负责什么 | 首轮落点 |
| --- | --- | --- |
| 随机流管理 | 根 seed、具名派生、流缓存、状态快照 | 先作为项目可复用 helper 验证，再决定公共模块 |
| generator 和 policy | 合法候选、场景偏好、显式状态输入、普通事务输出 | 项目 Python 函数、dataclass 和 generator |
| campaign | 数量预算、提交窗口、反馈边界、停止和排空 | 项目协程，调用现有 Agent |
| run recipe | DUT 初始化、manifest、失败产物、seed 矩阵和进程隔离 | 复用环境和 pytest fixture，跨进程调度交给回归脚本 |

首轮不需要新增一套随机序列调度器。当前 Driver 已有资源互斥和并发模板，Execution 已有任务与仿真边界。若将来出现跨 generator 的共享资源、优先级或公平性需求，再提出具体仲裁契约和可验证用例。

## 状态和协议边界

### 生成时机及模型推进

生成器可以读取只读状态快照决定下一步，但不能修改连接到 Agent 的检查模型。建议将“已接受的功能状态”与“生成器保留的 tag、地址或资源”分开：资源在提交前预留，拒绝或未接受取消时释放，响应结束后才按项目规则允许复用。检查模型由现有接受链更新一次。

`XTransfer.wait_processing()` 等到 Driver 设置接受事件；当前 Agent 还通过另一个消费者处理接受流并调用模型。这意味着仅等待这个 Future 就立即读取模型，不能保证模型消费者已经处理完。第一阶段需要有状态反馈时，采用 `await agent.drain(timeout_cycles=...)` 后读取模型；后续要在响应之前推进复杂生成策略，须建立明确的“模型已应用接受通知”快照接口，而不是通过 `sleep(0)` 猜测时序。

依赖退休、响应或提交事件的功能模型，应使用项目规定的事件更新；不能因为框架默认按输入接受推进，就把所有微架构状态都放在同一个 accept 中。多个接口共享状态时，项目还须定义同 tick 仲裁顺序，不能使用 asyncio 回调顺序作为硬件规范。[当前模型契约](../../docs/guides/agents-and-reference-models.md)。

### 提交窗口及持续生成的停止条件

无状态流可以边生成边提交，窗口内保持有限数量的 XTransfer。有状态流可先采用分批生成、提交、drain、反馈的方式。滑动窗口则在窗口满时等某个完成或可用槽位，再生成下一笔；选择哪笔等待会影响激励时序，应纳入策略。窗口不得超过 Agent 检查器和 Driver 的容量，也要遵守项目 tag 数量。

数量、仿真周期和墙钟预算都应明确记录：请求数或覆盖目标限制探索；simulation budget 限制硬件无进展；wall budget 限制宿主或外部计算挂起。达到目标后停止产生新请求，排空已提交事务，完成观察窗口，调用 finish 并保留检查结论。当前 drain、finish、asyncio timeout 可组成配方；它们不是一个已经存在的统一 campaign budget API。

运行中的随机延迟用 `ClockCycles`、`SimTimeout` 或协议 Driver 的周期逻辑表达。`asyncio.sleep()` 的真实时间延迟会引入宿主负载依赖，不能默认当成硬件随机背压。

### 背压及 reset

可以随机选择事务间 gap 和 ready 模式，但 valid 已拉高、ready 未接受时，协议要求稳定的 payload 必须保持。随机化应发生在新事务或协议允许的状态转移处，不能每个未接受周期重新改请求。

reset 随机序列首先选择合法注入点。项目必须规定未接受请求、已接受请求、参考模型、Scoreboard 和在途响应如何结束；当前 Agent 不会自动推断 reset。需要取消已接受事务的测试应先补足对应协议契约，不能调用普通 `XTransfer.cancel()` 绕过限制。违规字段或异常波形测试作为有明确预期的负向场景，禁止为扩大随机范围而全局关闭合法性检查。

## 独立随机流和复现契约

建议保存根 seed，并使用显式名字派生子 seed：`port0/traffic`、`port0/timing`、`port0/backpressure`、`reset/scenario`、`policy/selection`。同一名字的 rng 调用返回同一推进中的对象，不重新初始化。多个生成协程不能竞争消费同一个流；同一流有明确的消费方。

探针采用如下建议算法，完整实现见 [continuous_randomization_probe.py](continuous_randomization_probe.py)。算法版本是 trace 契约的一部分，不是现有框架标准。

```python
encoded = json.dumps(
    ["xreactor.rng.v1", root_seed, list(path)],
    ensure_ascii=True, separators=(",", ":"),
).encode("utf-8")
child_seed = int.from_bytes(hashlib.sha256(encoded).digest(), "big")
rng = random.Random(child_seed)
```

根 seed 限定为非负整数，path 为非空字符串片段组成的有序列表。JSON 避免用分隔符拼接名称造成歧义；SHA256 避免依赖进程随机化的 Python `hash()`。同一项目保持名称、候选排序和算法版本稳定；set 枚举、地址 `id()`、创建顺序、进程号和墙钟时间不用于流名称或候选排序。

这种隔离能保证给 delay 流多抽样不直接改变 traffic 流的值。但更改 delay 仍可能改变实际接受顺序、模型或覆盖快照，进而改变有反馈的后续事务。隔离保证的是随机流相互独立，完整激励稳定还要求固定控制逻辑、快照与外部事件。

`getstate()` 可用于恢复 RNG 位置，不能单独恢复 DUT、模型、Driver 队列或 Scoreboard。首轮采用从确定 reset 和新组件开始重放完整激励。跨版本或生成算法修改后需要显式 trace；若外部输入和时序无法固定，应记录实际决策与事件，并报告复现范围。

## 接入现有 Agent 的最小方式

探针复用了仓库的 Accumulator Agent 和独立模型。该 DUT 替身仅定义 tag 1、2、3，所以每批排空后才复用 tag。下面是已运行路径的核心写法；RngStreams 只是调研 helper，不能从 xreactor 公共包导入。

```python
model = AccumulatorModel()
agent = AccumulatorAgent(dut, response_timeout_cycles=5)
agent.connect(model)
rng = RngStreams(seed).rng("accumulator", "traffic")

async with asyncio.timeout(5), Execution(dut.backend, agents=[agent]):
    for batch in range(8):
        before = model.total
        limit = 1 + before % 15
        transfers = [
            agent.submit(Command(tag, rng.randint(1, limit)))
            for tag in (1, 2, 3)
        ]
        assert model.total == before
        await agent.drain(timeout_cycles=30)
        results = [await transfer for transfer in transfers]
    await agent.finish(timeout_cycles=30, observe_cycles=1)
```

生成代码没有调用 `model.accept()`，也没有额外读取 DUT 输出来构造预期。limit 是示例生成策略，真实项目应替换成自己的约束。这种批次反馈可先形成完整流程；高吞吐和多个 outstanding 的持续窗口留给后续具有资源预留和模型快照契约的实现。

## 覆盖反馈如何引导下一轮激励

第一阶段在批次 drain 后读取 `group.report()`，根据项目覆盖定义和返回的 counts 找缺口。当前 report 会同步 native 计数，因此没有必要为了反馈而把每周期 native 采样搬到 Python。同步和策略计算放在显式批次边界，记录反馈观察点；其性能成本需要实际测量。

建议由项目定义“覆盖目标到场景构造器”的映射，例如 dirty eviction 对应“同 set 写入足够多不同 tag 再访问新 tag”。覆盖 bin 是目标判定，场景构造器是达到目标的方法。两者不能自动从名称推导，也不能把手动 coverage sample 当作 DUT 内部机制已经发生的证据。

策略可提高未达阈值场景的选择权重，同时保留探索其他场景的非零概率。固定批次长度和排序、版本化映射、记录被选场景及权重后，才能解释反馈怎样影响激励。若长期无进展，先判断可达性、约束冲突和采样器是否完整，再添加定向前置序列；不能无限循环或自动删除难命中的 bin。

缺口计算还须遵守现有 at_least、goal、ignore、illegal 和 excluded 语义，并把采集不完整与零命中分开。覆盖已达目标而检查失败，运行仍然失败；检查通过但有预算内未完成的目标，标记为覆盖未达成。代码覆盖用于补充观察，不能替代功能规格覆盖。

## 运行产物与激励重放

### manifest 建议字段

沿用已有 run.json 并版本化扩展，建议至少记录以下信息。当前配方只覆盖其中一部分，表中是交付目标。

| 信息 | 建议内容 |
| --- | --- |
| 独立运行身份 | run_id、pytest nodeid、根 seed、状态与失败原因；seed 不单独充当身份 |
| 版本基线 | XReactor 版本、Python、backend、simulator、RTL build、generator 与 policy 版本 |
| 工作树基线 | commit 加工作树差异或构建内容摘要；单独记录 HEAD 无法描述未提交修改 |
| 有效配置 | 实际使用的参数、初始化和 reset 方法、负向测试模式、覆盖 schema 和 contract |
| 随机来源 | 派生算法、stream path 与子 seed、求解器 seed、DUT 初始化 seed |
| 预算和结果 | 请求上限、窗口、仿真与墙钟限制，generated/submitted/accepted/checked 等计数 |
| 产物定位 | stimulus.jsonl、事件记录、functional.json、报告、失败最小样例、内容摘要 |

### trace 记录建议

提交前写下不可变请求、项目局部递增 seq、场景和环境决策；提交成功再记录 submitted，接受和完成分别附真实事件。Driver 或 checker 返回的接受/完成 event 可在等待或 drain 后读取，但若要保证故障发生前已有持久记录，须增加明确的生命周期记录接点。该记录接点仍是拟实现工作；首次探针只验证完整成功运行的请求重放，扩展探针新增了内存中的失败前缀记录、简化和 JSON 重放。

```json
{"schema":"stimulus/v1","seq":7,"kind":"request","port":"port0","epoch":0,"request":{"op":"read","addr":65536,"beats":4},"timing":{"after_seq":6,"gap_cycles":2},"scenario":"same_set"}
```

这是建议 schema 的示意记录。真实 schema 要描述整数宽度、枚举、bytes、四态值以及跨接口引用，并区分请求与环境决策。记录中的 seq 属于本次运行；不要把当前进程级 XTransfer.sequence_id 当作跨运行稳定身份。批量刷新、失败时 flush 和独立输出目录用于控制日志成本与保留证据；磁盘写入失败必须反映在运行状态中。

### seed 重跑与 trace 重放的区别

seed 重跑在固定代码、配置、初始化、随机消费顺序和外部事件下重新生成。trace 重放读取已保存请求及环境决策，绕过新随机选择，仍让当前 Driver、DUT 和检查模型执行。预期响应继续由独立规格计算，不能把上一轮实际 DUT 输出当成下一轮正确答案。

对于自适应 campaign，只保存最终请求不一定保留原有并发关系。重放还需要记录提交间隔、背压、reset、外部响应等决策及因果锚点。建议同时记录仿真 tick 作为核对证据；若 DUT 变化后无法在原 tick 接受，请求应按原因果规则继续执行并报告时序偏离，不能伪造旧接受事件。精确固定周期重放和协议弹性重放应明确区分。

跨版本、schema 或配置不兼容时拒绝隐式重解释，使用明确转换或重新生成。修复后行为变化可以使失败不再复现；重放的价值是保留原激励和正确检查，而非保证错误永远出现。

### 失败简化

Hypothesis 场景优先使用内建简化；已经独立保存的 trace 可做 delta debugging：缩短序列、移除无关请求、缩小数据和 delay。每个候选使用新 DUT 和相同初始化，保持必要的写后读、tag 和 reset 依赖，冻结环境决策，检查是否复现同一失败类型与关联事务。若候选因协议非法或前置状态缺失而失败，不能把它当作原 bug 的更小样例。

RTL 重跑成本高，需要总尝试预算。Hypothesis 可产生并简化纯模型动作计划，也可简化在线异步场景的选择；后者已在 MemoryBackend 的历史依赖故障上验证。其 failure blob 和数据库存在版本边界，长期回归应保存可读、带 schema 的项目 trace 或显式用例。[Hypothesis 重放 API](https://hypothesis.readthedocs.io/en/latest/reference/api.html#hypothesis.reproduce_failure)。

## 推荐实施顺序与验收

这些步骤是后续工程计划，本次交付是调研文档和研究探针。

| 阶段 | 具体工作 | 验收证据 |
| --- | --- | --- |
| 第一阶段 | Hypothesis st.data 在线场景与逐案例环境工厂；有预算执行；压力模式统一 RngStreams、manifest 和 traffic/timing 流 | 新状态改变合法域；逐案例初始状态一致；压力模式同 seed 可重复；检查和异常可靠传播 |
| 第二阶段 | 完成 stimulus schema、接受和完成记录接点、环境决策记录与 replay runner；迁移 Cache 和 e203 | 新环境重放同一激励与时序策略；故障时仍有完整前缀；检查失败继续传播 |
| 第三阶段 | 项目状态快照、资源预留、滑动窗口、显式 reset 场景，以及批次覆盖反馈 | 未接受取消不改模型；窗口满有界等待；乱序响应、同 tick 冲突和反馈决策可复现 |
| 第四阶段 | 由复杂用例决定求解器适配与独立 trace reducer；HypoFuzz 连接实际功能事件；扩展持续 corpus 和多 seed 回归 | 无解和超时明确区分；功能反馈来自观测；分片运行身份和覆盖合并有效 |

建议先迁移 e203 的 PC 关系和 delay 流，再迁移 Cache 的同 set 冲突与逻辑模型。在旧模式和新模式并存期间保留已有定向前缀及检查能力。分流后相同整数 seed 的新请求通常会变化，应记录 generator version 并保留旧 trace；“可复现”不是承诺迁移前后产生相同抽样序列。

若需要回归调度，快速 CI 运行固定 seed、已知失败 corpus 和有限随机量；nightly 使用预先保存的 seed 清单、较大预算和多个场景 profile。每个独立运行初始化 DUT 和新组件，按 RTL、配置、schema 和 contract 兼容条件合并覆盖；保留 collection error、skip、取消和中断状态，禁止用不完整合并结果宣布完成。

引入效果建议在相同 RTL build、定向前缀、墙钟预算和 seed 集合下比较：实际检查的事务数、功能 bin 与 transition 增量、稀有场景所需周期、故障复现成功率、生成和反馈耗时、峰值 outstanding、内存和日志量。反馈变化会改变激励，因此性能比较还需补充固定 trace 的 A/B，分清不同工作量与框架开销。

只有真实 DUT 测量才能决定批次大小或求解器选择。这次不以 Python 探针吞吐量推导 RTL 验证性能，也不预设第三方库谁更快。

## 首次验证证据与边界（2026-09-30）

执行入口和结果：[研究探针](continuous_randomization_probe.py)，实际结果 JSON（本地产物：`continuous-randomization-probe-results-2026-09-30.json`）。仓库根目录复查命令：

```bash
PYTHONPATH=src:. python3 design/verification/continuous_randomization_probe.py
```

本次环境为 Python 3.12.3，使用 MemoryBackend，结果为 passed：

| 检查 | 实际证据 |
| --- | --- |
| 构造式约束 | 10,000 笔请求满足 8 byte 对齐、64 bit 数据范围、允许的 burst 长度和不跨 4 KiB 页；这些内存请求仅验证生成器，未驱动真实总线 |
| seed 与流隔离 | 同 seed 请求逐项相同；增加 delay 与 debug 流抽样仍相同；seed 17 和 23 产生不同序列 |
| RNG 状态恢复 | getstate、setstate 恢复后 16 次抽样相同；只证明 RNG 恢复 |
| Agent 接入 | 4 次独立运行，各 8 批、24 笔，验证提交不立即改模型及 drain 后状态依赖 |
| 乱序检查 | 每批响应次序为 2、1、3，仍通过独立模型与现有 Scoreboard |
| 显式请求重放 | seed 17 的请求经 JSON 往返后，在 seed 999 的新环境执行，响应、最终模型和 tick 与原运行相同 |

种子 17 的 Agent 请求摘要为 `dc0b8f45ce93439f130b28fe5ff66ff7e30438e0ad0a4afcc6cab4700b432802`，最终模型 total 为 103，最后 half tick 为 99。摘要只对应当前探针和 Python 环境。

另外运行了本方案依赖的组件回归，结果为 **32 passed**：

```bash
PYTHONPATH=src:. python3 -m pytest -q \
  tests/interfaces/test_agent.py \
  tests/integration/test_reference_model_example.py \
  tests/integration/test_verification_flow.py
```

文档的本地引用、Python 和 JSON 示例语法，以及与探针 JSON 的关键结果一致性均已检查。当前环境未安装 MkDocs，本次未验证站点渲染；该研究文档通过 design 索引访问。

这些首次证据支持“标准库随机流与协程可以接入现有事务闭环”。它们未验证真实 RTL、native 求解性能、复杂 reset、跨接口仲裁、在线覆盖自适应、故障前 trace 持久化或自动失败简化。首次默认解释器未提供 xspcomm、Hypothesis、PyVSC 或 constrainedrandom。2026-10-01 的[扩展调研](hypothesis-stateful-randomization-research-2026-10.md)在临时 venv 新增第三方库实测，补足在线 Hypothesis、故障简化重放和 HypoFuzz 功能事件桥接；真实 RTL 与持久 trace 等边界仍未验证。
