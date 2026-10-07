# Hypothesis、有状态持续生成与 XReactor 接入调研

调研与实测日期：2026-10-01。本文接续[持续随机化调研](continuous-randomization-research-2026-09.md)，重点是**同一次仿真中，依据已确认的状态持续生成合法事务**，并扩展到失败搜索、简化和长期探索。库的机制引用官方资料；接入判断来自当前源码和本文探针；实施建议尚未成为框架公共 API。

**建议把 Hypothesis 的 `st.data()` 在线生成作为有状态正确性测试的首选验证路线。** 它可以在 `await` 返回后，根据新状态继续抽样，同时保留失败简化能力。需要指定流量比例或长期压力时，另设 CRV/stress 模式；需要持续保留探索 corpus 时，再加入 HypoFuzz。标准库 RNG 仍适合这些模式的辅助随机流，但不再承担全部搜索与失败简化工作。

本次已经跑通 Hypothesis → XReactor Agent → 异步执行 → 独立参考模型 → 检查响应的闭环，且找到并重放了三笔事务的历史依赖故障。**这些实验使用 MemoryBackend，并未执行真实 RTL。** HypoFuzz 试跑还发现了当前版本组合的异步入口边界：直接异步测试失败，同步测试内部运行完整异步场景可用。

## 从 random 到性质和动作序列搜索

`random.Random` 回答“下一次抽什么”；Hypothesis 还负责组织多次候选执行、寻找违反性质的输入、简化失败并保存重跑线索。测试必须提供合法输入域和可信性质；库不会替我们写硬件规格或参考模型。[Hypothesis 自定义策略](https://hypothesis.readthedocs.io/en/latest/tutorial/custom-strategies.html)、[失败重放](https://hypothesis.readthedocs.io/en/latest/tutorial/replaying-failures.html)。

| 层次 | 在硬件验证中表达什么 | 本文核实的入口 |
| --- | --- | --- |
| 字段策略 | 位宽、opcode、对齐、burst 长度和依赖字段 | `integers`、`sampled_from`、`composite` |
| 在线事务生成 | 等待检查反馈后，按新状态决定下一笔域 | `st.data()` 的 `draw` 与项目协程 |
| 动作语法 | 哪些历史允许提交、完成、撤销或复用资源 | `RuleBasedStateMachine`、前置条件、Bundle |
| 搜索目标 | 倾向探索某个可重复的数值指标 | `target` |
| 持续探索 | 保留行为 corpus，并反复运行性质测试 | HypoFuzz；功能覆盖可通过 `event` 接入 |

Hypothesis 让用户定义允许的域，具体分布由搜索机制决定；它不保证均匀抽样，也不保证业务流量比例。[输入域与分布](https://hypothesis.readthedocs.io/en/latest/explanation/domain.html)。因此“读写各 50%”“长期平均占用 80%”应由独立的压力配方定义和测量。把这种要求交给 `sampled_from`，再因结果比例不符而判定 Hypothesis 错误，会混淆探索目标与统计目标。

## 字段约束：优先构造合法域

Hypothesis 的策略可以组合和依赖此前生成的值。对 burst，先选择长度，再缩小合法起始地址域，比从全空间生成后不断拒绝更直接。[策略组合](https://hypothesis.readthedocs.io/en/latest/reference/strategies.html)、[策略调整](https://hypothesis.readthedocs.io/en/latest/tutorial/adapting-strategies.html)。下面摘录[实测探针](hypothesis_randomization_probe.py)的生成器；`MemoryRequest` 是普通 frozen dataclass。

```python
@st.composite
def burst_requests(draw):
    beats = draw(st.sampled_from((1, 2, 4, 8, 16)))
    page = draw(st.integers(0, 15))
    word = draw(st.integers(0, 512 - beats))
    op = draw(st.sampled_from(("read", "write")))
    data = draw(st.integers(0, (1 << 64) - 1)) if op == "write" else 0
    return MemoryRequest(op, 0x10000 + page * 4096 + word * 8, beats, data)
```

地址对齐、64 KiB 区域和不跨 4 KiB 页在构造时成立；性质测试独立检查这些关系，本次检查了 300 个样例。这一生成器只验证内存请求结构，未驱动真实内存接口。

`filter` 和 `assume` 适合少量剩余条件。若合法区域极稀疏，大量拒绝会浪费预算，甚至触发健康检查；应先改造策略或使用适合的约束求解器。Python 类型注解也不能替代位宽、地址窗口、溢出和协议状态约束。

不要把策略当作普通 RNG，在场景中不断调用 `.example()`：该方法用于交互探索，本次也验证了在 `@given` 测试中调用会被拒绝。正式场景使用 `@given` 参数或当前案例的 `data.draw`；这样选择才参与搜索、记录和简化。[策略 API](https://hypothesis.readthedocs.io/en/latest/reference/strategies.html)。

## st.data 可以在仿真运行中继续生成

`st.data()` 的用途就是把生成与测试代码交错，而非要求先生成完整列表。[交互式生成](https://hypothesis.readthedocs.io/en/latest/reference/strategies.html)。在 pytest-asyncio 下，本次实测异步 `@given` 可在一个 `await` 后继续 `draw`；插件的更新记录也明确包含 Hypothesis 集成。[pytest-asyncio 更新记录](https://pytest-asyncio.readthedocs.io/en/stable/reference/changelog.html)。

下面是探针 `execute_online` 的循环摘录。每个案例在进入此循环前新建 DUT、model、Agent 和 Execution；外围还包含超时、finish 与 finally 清理。tag 合法域和数值关系是这个累加器实验的定义。

```python
for index in range(steps):
    before = model.total
    limit = 1 + before % 16
    tag = data.draw(st.sampled_from((1, 3, 2)), label=f"tag-{index}")
    operand = data.draw(st.integers(0, limit), label=f"operand-{index}")
    gap = data.draw(st.integers(0, 2), label=f"gap-{index}")
    rows.append({"tag": tag, "operand": operand, "gap_cycles": gap,
                 "model_before": before, "operand_limit": limit})
    if gap:
        await ClockCycles(dut.clock, gap)
    transfer = agent.submit(Command(tag, operand))
    assert model.total == before
    response = await transfer
    assert response.total == before + operand
    assert model.total == sum(row["operand"] for row in rows)
```

完整可运行实现见探针。这里下一笔 `operand` 的上限确实取决于上一笔已检查后更新的 `model.total`。本次异步入口执行 40 个案例、386 笔检查请求，上限实际增长到了 16。

选择**已检查响应**作为反馈点是当前实验的保守接法：`Agent.submit` 不推进模型；`wait_processing` 的接受 Future 返回，也不保证另一个模型消费者已处理完接受通知。累加器探针在响应检查完成后验证模型已更新，下一次才读取它。其他项目可在 `drain` 后取快照；若要在响应前持续生成，则需要明确的“模型已应用接受事件”接口和资源预留状态，不能靠 `sleep(0)` 推测。[Agent 源码](../../src/xreactor/agent.py)、[XTransfer 源码](../../src/xreactor/transfers.py)。

这个探针每次只有一笔 outstanding。它证明在线状态依赖的可用性，不证明满窗口吞吐量。滑动窗口测试还须区分已提交、已接受、已完成状态，并依据空闲 tag、Driver capacity 和模型一致性决定合法动作；容量满时 `submit` 会报错。

抽样集中在场景任务内。Monitor、Driver 和仿真 pump 继续承担观察与驱动；从已检查 transfer 取得响应，不再增加第二个响应流消费者。后台任务不持有逃出案例生命周期的 `DataObject`，也不根据宿主线程时序决定抽样顺序。

## RuleBasedStateMachine 适合表达历史和资源语法

有状态测试可以定义 `reserve`、`complete`、`cancel_pending` 等规则；`precondition` 按实例状态启用规则，Bundle 保存规则产物，`consumes` 让后续动作消费已有资源，invariant 检查每一步的全局关系。Hypothesis 能搜索并简化整条动作历史。[有状态测试](https://hypothesis.readthedocs.io/en/latest/stateful.html)。

本次纯 Python 探针限制最多三个预留资源，完成或取消必须消费已存在的 tag；执行中 reserve、complete、cancel 均出现，实际最大占用为 3。**这验证了动作语法和 Bundle 使用，未把该状态机接到 RTL 或 Agent。**

当前安装的 Hypothesis 6.168.3 的 stateful 执行器直接同步调用规则函数，没有 await 规则返回值。因此不能把 `@rule` 方法改成 `async def` 就宣称已经适配 XReactor。本文建议：

1. 首先使用已跑通的 `st.data()` 协程闭环表达在线动作及字段选择，配合普通 Python 状态判断。
2. 纯模型、资源管理器和协议动作合法性使用 `RuleBasedStateMachine`，获得历史搜索与简化。
3. 若真实项目需要 stateful 规则直接驱动仿真，再设计整个案例共用的同步到异步网关，并验证 loop ownership、取消和清理。不要每条规则调用一次 `asyncio.run`，却跨 loop 复用 Agent、Future 和 DUT。

`stateful_step_count` 限制规则步数，不等于 RTL 周期；`max_examples` 也不是全部执行次数的硬上限。数据库重跑、拒绝、目标搜索或简化都可能增加执行。本次配置 `max_examples=40` 的纯状态机探针实际创建了 59 个实例，正说明统计口径必须独立记录。[案例次数说明](https://hypothesis.readthedocs.io/en/latest/explanation/test-case-count.html)。

## 失败搜索、简化和项目重放

探针注入一个历史依赖故障：至少已有两笔输入被接受后，tag=2 的响应把累加结果多加 1。Hypothesis 搜索在线选择，找到并简化到下面的失败前缀；独立模型仍计算正常结果。

| 顺序 | tag | operand | gap 周期 | 检查结果 |
| --- | --- | --- | --- | --- |
| 1 | 1 | 0 | 0 | total=0，通过 |
| 2 | 1 | 0 | 0 | total=0，通过 |
| 3 | 2 | 0 | 0 | 期望 total=0，实际 total=1 |

搜索和简化过程中记录了 119 次失败执行；最后的三笔 trace 经 JSON 往返后，在新故障 DUT 上再次触发 `ScoreboardMismatch`，在新正确 DUT 上通过。这证明简化结果可脱离 Hypothesis 重新驱动当前场景。记录中最大的失败前缀也只有三笔，故本次证据**不支持“从十二笔失败 trace 缩成三笔”**；十二是案例允许的最大步数。简化结果也不等于全空间全局最小的证明。

每个候选都必须重新建立同一初始状态。否则“删除前面的事务”可能只是继承上次 DUT 状态，或者把原来数据错误变成超时错误。长期回归要保存可读动作、字段、延迟、reset 与环境决策、版本和因果锚点；检查预期继续来自规格模型。

Hypothesis 的数据库和 failure blob 对快速重跑很有用，但不能代替长期项目 trace：数据库不是永久回归保证，blob 有版本约束；显式 `@example` 可以保留案例，但本身不再自动简化。[失败重放指南](https://hypothesis.readthedocs.io/en/latest/tutorial/replaying-failures.html)。在线策略改变、RTL 修复或 reset 行为调整后，也必须重新核对 trace 兼容性。

## 每个案例的环境、确定性和预算

pytest 的 function-scoped fixture 在一次测试调用中建立，不会为每个 `@given` 候选重建。Hypothesis 对这种情况有专门健康检查。[API 与健康检查](https://hypothesis.readthedocs.io/en/latest/reference/api.html)。建议每个案例在测试体或场景工厂中创建 DUT 和新组件；需要复用昂贵的 native DUT 时，先验证 reset 能恢复所有 RTL、参考模型、Driver、Scoreboard、覆盖和资源状态，不能只禁用警告。

探针为每个案例建立新环境，退出后关闭 DUT，并检查没有遗留 asyncio task。实际 RTL 的可靠 reset 和进程隔离成本仍待测量。纯 Python fixture 能重新建立，不意味着 Verilator 或其他 backend 的内部状态已获得同样保证。

给定相同选择，动作、观测与失败应可重复。未受控的全局随机数、后台时间竞赛、外部设备和残留状态都可能导致 flaky failure，使简化无法稳定工作。[不稳定失败](https://hypothesis.readthedocs.io/en/latest/tutorial/flaky.html)。参数化时序使用仿真周期；宿主墙钟只控制超时，不成为硬件激励值。

| 预算 | 应限制什么 | 本次设置 |
| --- | --- | --- |
| 案例规模 | 一次新环境中的动作数 | 在线案例 1～12 步 |
| 仿真等待 | 协议无进展、响应和排空 | 响应 5 周期，finish 30 周期 |
| 单案例墙钟 | 初始化或执行挂起 | `asyncio.timeout(2)` |
| 普通搜索 | 有限 CI 探索 | 在线测试 `max_examples=40` |
| 长期探索 | 整个 fuzz 进程和 corpus 存储 | 本次 HypoFuzz 每次试跑 12 秒 |

`deadline=None` 适合成本不稳定的仿真案例，但只是关闭 Hypothesis 的执行时长检查；不能代替以上超时。库设置中的案例数也不限制简化的总宿主成本，实际 RTL 应另设进程预算并保留中断状态。

## 覆盖反馈：target、event 与 HypoFuzz

普通 Hypothesis 的 `target` 用可比较的有限数值鼓励探索，每个案例同一 label 只能调用一次。[target API](https://hypothesis.readthedocs.io/en/latest/reference/api.html#hypothesis.target)。可选指标包括峰值 outstanding、已完成历史长度或案例内达到的功能点数量；应在案例结束时汇总。探针使用已接受的总和验证接线，不能据此推导已经优化 Cache 覆盖。

普通 `event` 可以记录测试统计。**HypoFuzz 进一步把 event 当作虚拟分支反馈**，让来自领域观测的类别参与 corpus 探索。[HypoFuzz 行为反馈](https://hypofuzz.com/docs/manual/behavior.html)。这比只能观察 Python 分支更符合 native RTL 验证需要：Python 驱动执行同一条路径，RTL 仍可能达到不同内部状态。

推荐在案例或确定的批次边界读取实际覆盖，转换为有限、稳定的标签，例如 `functional/v1/cache.dirty_evict/way0`。标签应描述经过采集契约确认的 group/bin；不要加入 run_id、seed、逐 tick 数值等无限增长项。下面是实测入口的核心片段，`execute_online` 返回本案例新建 CoverGroup 的实际响应命中：

```python
@ONLINE_SETTINGS
@given(data=st.data(), steps=st.integers(1, 12))
def test_sync_executor_for_continuous_fuzzing(data, steps):
    result = asyncio.run(execute_online(data, steps))
    target(result["total"], label="accepted-total")
    for name in result["reached_response_bins"]:
        event(f"functional/v1/response.tag/{name}")
```

探针在 `await transfer` 成功后按实际 response.tag 调用 `coverage.sample`，随后从 report 计数读取命中；没有把生成时选中的 tag 直接计作已执行覆盖。它验证的是响应可观测功能点到反馈的桥接，尚未证明 RTL 内部 transition 的采集和优化。

XReactor `CoverGroup.report()` 会同步 native 计数，后续可在批次边界采集内部 bin，但仍须保留 at_least、goal、ignore、illegal、excluded 和采集完整性语义。事件首次出现不等于已达到计数阈值，HypoFuzz 行为数也不等于 RTL 功能覆盖率。[覆盖实现](../../src/xreactor/coverage.py)。

不要把“相对所有历史运行新增的 bin 数”直接作为同一输入的 target：该分数会随测试运行顺序变化。可以使用案例内命中集合、固定参考目标或确定性阈值等级；跨案例 novelty 交给 fuzzer corpus 管理。完整覆盖报告继续单独保存。

### 持续 fuzzing 和异步入口的实测边界

HypoFuzz 可以持续探索已写好的 Hypothesis 性质测试，其 CLI 默认一直运行直到停止，适合外部预算管理。[CLI](https://hypofuzz.com/docs/manual/cli.html)。这里有两个持续性：**一个案例内**根据新状态在线生成；**多个案例之间**由 fuzzer 持续搜索，每个案例仍回到可重复的初始状态。这不是让同一个永不 reset 的 DUT 承担所有简化重跑。

本次组合为 HypoFuzz 25.11.1、Hypothesis 6.168.3、pytest 9.1.1、pytest-asyncio 1.4.0：

| 试跑入口 | 实测结果 | 接入决定 |
| --- | --- | --- |
| 使用确定性 CI 设置 | `derandomize=True` 导致未收集，原因 `sets_derandomize` | 为 fuzz 单独设置 profile，使用共享默认数据库 |
| 直接异步 `@given` 测试 | 返回未 await 的 coroutine，触发 `FailedHealthCheck`，有效案例为 0 | 此版本组合不能沿用该入口；正常 pytest-asyncio 运行仍可通过 |
| 同步 `@given` 内 `asyncio.run` | 持续执行有效案例，并保存实际功能事件 | 采用本文已验证的同步 executor 入口 |

同步 executor 在最末保存快照中有 14 个 VALID、745 个 behaviors 和 6 个 fingerprints；保存的观测含 response.tag 的三个功能事件。14 是已持久化快照中的数，不是停止时完整总量；745 还包括 Python 路径反馈，不能称作 745 个 RTL bin。12 秒预算终止使 supervisor 退出 124，表示预算到期，不是完整 campaign 的通过结论。试跑结果 JSON（本地产物：`hypofuzz-randomization-probe-results-2026-10-01.json`）。

`asyncio.run` 在这里成立，是因为同步测试没有正在运行的外层 asyncio loop，并为整个案例创建一个 loop。异步测试内部不得嵌套调用它。HypoFuzz 与 Hypothesis 内部接口关系紧密，后续工程应固定并验证兼容版本，而非只声明一个宽松下限。[兼容性说明](https://hypofuzz.com/docs/compatibility.html)。

## 类似库与组合方式

下表的接入判断针对 XReactor；“未实测”意味着只核对官方机制，没有安装运行或比较性能。

| 工具 | 与本问题的关系 | 建议用途 | 本次证据 |
| --- | --- | --- | --- |
| Hypothesis | 合法域生成、性质搜索、历史与失败简化 | 有状态正确性测试首选；字段简单时 composite 足够 | 在线 Agent、纯动作语法和故障重放均运行 |
| HypoFuzz | 持续搜索 corpus，Python 分支及 event 反馈 | 在已有 Hypothesis 场景上扩展长时间探索 | 有界同步入口及功能事件桥接运行 |
| constrainedrandom | Python 字段域、函数约束和临时约束搜索 | 复杂字段 CRV，或需要显式抽样控制的配方 | 100 笔动态约束，两次同 seed 一致 |
| PyVSC | SV 风格随机类型、约束块、dist 和 solve_order | 已有复杂 SV 事务模型的 Python 迁移 | 官方约束接口调研，未实测 |
| Atheris | 对字节输入做覆盖引导 fuzzing；支持 Python 和已插桩 native 代码 | 编解码、接口解析、桥接库的输入健壮性 | 官方接口调研，未实测 |
| CrossHair | 用符号执行探索 Python 契约，也能生成路径输入 | 纯函数规格、约束 helper 和模型的补充检查 | 官方契约与限制调研，未实测 |

### constrainedrandom / PyVSC：字段求解与序列搜索分工

constrainedrandom 的 `RandObj` 可以注入 `random.Random`，定义变量域和多字段约束，并在每次 `randomize(with_constraints=...)` 加临时限制。[使用指南](https://constrainedrandom.readthedocs.io/en/latest/howto.html)。探针将 `word + beats <= 512` 设为基础约束，并随已生成历史调整 `beats <= limit`；两轮各 100 笔结果逐项相同。另一个已知无解的小有限域触发 `RandomizationError`；一般搜索报这个错误，仍不能直接推导数学无解。

PyVSC 的优势是已有 SV 风格约束、soft、分布和求解顺序的建模方式。[约束文档](https://pyvsc.readthedocs.io/en/latest/constraints.html)。这些字段求解接口不承担本文的 DUT 生命周期、动作合法性、参考检查和整条执行历史简化；仍要由场景配方组织，输出普通 immutable 请求后交给 Agent。

简单对齐和依赖范围优先用 Hypothesis composite。复杂求解器也可由 Hypothesis 生成一个 seed 后调用，但此时自动简化的主要对象是 seed，不意味着求解后的地址、数据和动作会按硬件语义变小。若混用，必须保存求解结果、配置和版本，并设计独立字段/trace reducer。本文更建议先分别建立正确性搜索与 CRV 压力模式，共享执行和检查接口。

研究环境还出现一个真实依赖冲突：constrainedrandom 所需的 python-constraint 1.4.0 安装了顶层 `examples` 包，遮住仓库同名 namespace。探针显式按路径载入现有累加器示例后运行通过，未改仓库包结构。这一现象说明可选依赖应先隔离验证；也不是 XReactor 核心需要新增第三方依赖的理由。

### Atheris：覆盖引导的字节输入

Atheris 面向字节输入，能追踪 Python 执行；native 扩展的覆盖需要相应插桩，装上 wheel 不会自动让未插桩 Verilator 库进入反馈。[Atheris 官方说明](https://github.com/google/atheris)。Hypothesis 提供 `fuzz_one_input` 与外部 fuzzer 集成，但该路径不会照搬普通 `@given` 的 max_examples、deadline 等运行设置。[外部 fuzzer 接入](https://hypothesis.readthedocs.io/en/latest/how-to/external-fuzzers.html)。

因此它更适合查 bridge 参数解码、序列化和 parser 健壮性。若用于硬件场景，需要自行设计字节到合法历史的编码、资源依赖修复、初始化和检查；本文已有领域事务与异步场景时，先选 Hypothesis/HypoFuzz 的接入成本更低。这是架构判断，不是性能排名。

### CrossHair：纯 Python 规格的符号探索

CrossHair 从契约生成反例，`cover` 还能为函数生成路径输入。[契约种类](https://crosshair.readthedocs.io/en/latest/kinds_of_contracts.html)、[cover](https://crosshair.readthedocs.io/en/latest/cover.html)。它要求被分析的执行满足确定性等限制，未找到反例不构成普遍正确性证明。[限制](https://crosshair.readthedocs.io/en/latest/limitations.html)。

可先评估 `is_legal`、地址映射、模型算术等纯函数。它不会把任意 XReactor asyncio 场景和 native DUT 自动变成可符号求解对象；本文不建议作为在线仿真的首个生成入口。

## XReactor 的引入方案和验收

保留现有 Agent、Driver、Monitor、Scoreboard 与 Execution，把策略和搜索 executor 放在它们上层。事务仍是普通 Python 对象；检查模型独立；场景入口同时接受 Hypothesis draw 或项目 trace replay。开始迁移时不需要新增公共基类或改核心依赖。

| 模式 | 生成与搜索 | 运行与检查 | 保存内容 |
| --- | --- | --- | --- |
| 有状态正确性 | Hypothesis `st.data`，必要时纯模型 stateful | 每案例新环境，有限动作，真实接受和检查反馈 | 搜索配置、失败前缀、简化 trace、版本基线 |
| CRV / stress | 独立 RNG 或约束求解器，明确权重与窗口 | 同一有预算场景，检查不断运行 | seed、请求及环境决策、实际流量统计 |
| 持续探索 | HypoFuzz 同步 executor、稳定功能事件 | 案例内在线，案例间复位；外部进程预算 | corpus、功能报告、失败 trace 和中断状态 |

实施顺序建议调整为以下四步；与初次文档相比，Hypothesis 提前进入第一步。

1. **验证真实项目在线路径。** e203 将基于上一已确认 PC 的合法域和 gap 移到 `data.draw`；Cache 先从逐笔写读、同 set 历史开始。复用已有 reset、环境和检查，先等待响应或 drain 后更新策略。
2. **形成可重跑案例工厂和 trace。** 实测真实 DUT reset、任务清理、异常传播与三个预算；为 native 场景注入可控故障，验证发现、简化、同故障重放和修复后通过。将兼容第三方版本固定在可选验证环境中，核心依赖继续为空。
3. **接入实际功能反馈和长期 corpus。** 定义版本化 group/bin 到 event 的有限映射，使用内部机制采集证据；分别运行固定 corpus CI 与有预算 fuzz profile。扩大窗口前补足接受快照、tag 预留和响应乱序语义。
4. **按复杂度引入求解器和压力配方。** 只有简单策略难以表达的字段关系才接 CRV adapter；同一规格下比较定向、普通 random、Hypothesis 和 HypoFuzz，不预设排名。

真实 RTL 对比应固定 build、初始化、定向前缀和墙钟预算，统计检查事务数、实际功能 bin/transition、找到故障的时间、重放成功率、简化重跑次数及成本、峰值 outstanding 和内存。Hypothesis 分布不同，案例数不能直接充当公平工作量；还应补充固定 trace 的性能比较。本次探针没有证明功能覆盖收益或真实 RTL 吞吐提升。

## 实测产物与复查

代码：[hypothesis_randomization_probe.py](hypothesis_randomization_probe.py)。普通测试结果：Hypothesis / constrainedrandom JSON（本地产物：`hypothesis-randomization-probe-results-2026-10-01.json`）。持续试跑结果：HypoFuzz JSON（本地产物：`hypofuzz-randomization-probe-results-2026-10-01.json`）。

普通测试在 Python 3.12.3 上为 **7 passed in 4.79s**。各项证据分别对应 composite 合法域、纯状态机、异步在线生成、同步 executor、故障搜索与重放、`.example()` 防误用和 constrainedrandom。预期的故障由测试捕获并验证，不是整个 suite 意外通过了错误 DUT。结果 JSON 是案例证据，pytest 退出状态才是这次 suite 的通过依据。

本次第三方库只安装在临时 venv `/tmp/xreactor-hypothesis-research-20260930`，没有改 pyproject 或默认测试依赖。仓库根目录下可使用一个装有所列版本的研究环境复查：

```bash
PYTHONPATH=src:. \
XREACTOR_HYPOTHESIS_RESULT=design/verification/hypothesis-randomization-probe-results-2026-10-01.json \
python -m pytest -q design/verification/hypothesis_randomization_probe.py
```

HypoFuzz 的预算试跑应在独立工作目录执行，使 corpus 与正常 CI 隔离。以下路径对应本次环境；`XREACTOR_HYPOFUZZ_PROBE=1` 启用非确定性且使用默认数据库的 fuzz 设置。

```bash
cd /tmp/xreactor-hypothesis-research-20260930
PYTHONPATH=/home/xyl/xreactor/src:/home/xyl/xreactor \
XREACTOR_HYPOFUZZ_PROBE=1 \
timeout --signal=INT --kill-after=3s 12s \
  /tmp/xreactor-hypothesis-research-20260930/bin/hypothesis fuzz \
  -n 1 --no-dashboard -- \
  /home/xyl/xreactor/design/verification/hypothesis_randomization_probe.py \
  -k sync_executor_for_continuous_fuzzing
```

试跑仅验证此组合能够执行并保存反馈，没有进行统计性能比较，也没有接入真实 RTL/native 覆盖。本文将可用在线路线、遇到的入口问题及未验证部分分别保留，作为下一步项目迁移的验收起点。
