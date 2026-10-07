# 有状态功能覆盖与 native 采集计划

本计划始于 2026-09-30，基础采集与有界模式并发已经交付。后续工作集中在 capture、
按事务 key 关联、可配置 pause 和完整过程轨迹。这里的 capture 指时序匹配过程中保存
字段值，不是 Monitor 已有的同步 capture 回调。

目标是让功能覆盖表达状态转移和历史依赖，并将高频信号采样留在 xcomm 中执行。
Python 事务采样继续可用，生命周期沿用 asyncio、Execution 和 XClock。

## 实施状态与阅读方式

以下状态根据截至 2026-10-01 的实现记录整理。本文后续章节保留原阶段的设计和验收
要求，其中尚未交付的接口属于后续目标；当前可用接口请查阅[覆盖指南](../../docs/guides/coverage.md)
与[当前实现说明](../current-implementation.md)。

| 范围 | 状态 | 后续边界 |
| --- | --- | --- |
| 简单转移与共享时序 IR | 已交付 Bin.transition、Next 和现有 Sequence/FSM 的复用 | 继续沿用已有 Trigger 时序语义 |
| native 整组采集 | 已交付持续计数、cross、宽信号、快照及生命周期接入 | 用户通过 CoverGroup.bind 绑定，没有新增公共 Binding 类 |
| 有界并发与诊断 | 已交付 Sequence/FSM 有界 overlap、汇总诊断与按需进度查看 | 当前 coverage ABI 为 v3；模式并发尚不提供事务 key 配对 |
| e203 与 Cache 内部观测 | 后续已补充内部场景采样和属性检查 | 已知 RTL 缺陷及未关闭要求按项目验证记录保留 |
| capture 与事务上下文 | 尚未交付 | 需要明确字段保存、key 关联、隔离和完成记录的语义 |
| 可配置 pause 与完整轨迹 | 尚未交付 | 依据实际诊断需求确定范围 |

基础采集和诊断的证据见[native 覆盖验证](../verification/native-coverage-2026-09.md)。
项目观测的后续进展见[当前实现说明](../current-implementation.md)及项目验证计划。
UCIS 互操作另行评估，推进顺序由[路线图](roadmap.md)统一记录。

## 1. 设计原则

1. **Bin 支持转移，但复用 Trigger 的时序识别实现。** `Bin.transition` 是简单值序列
   的声明入口；复杂的分支、窗口、capture 和事务关联放在统一的时序程序中，由 Trigger
   与 coverage 共同使用。Bin 不维护另一套 FSM 算法。
2. **根据数据来源选择执行位置。** 已绑定信号的静态 bins、cross 和时序模式在 xcomm
   观察层执行；Python Monitor 生成的事务与 reference model 派生数据仍可直接 sample。
   不把 Python 对象强行移入 RTL simulator，也不为 coverage 新建时钟推进循环。
3. **匹配与命中处理分离。** 同一份不可变程序可以用于唤醒等待者或累计覆盖计数。
   两种用途各有独立运行状态；高频覆盖命中不创建 asyncio task，也不必让 RunUntil 返回。
4. **覆盖、正确性和运行结果保持独立。** 模式未完成不是自动的协议失败；checker 负责
   判断应该发生的行为。覆盖发生后检查失败仍保留观察证据。不会恢复 pytest 功能标签聚合。
5. **xcomm 提供匹配与覆盖计数能力，XReactor 组织测量。** Coverpoint 所需的静态分类、
   时序识别、同样本 cross 和累计计数进入同一 C++ 观察引擎；定义管理、DUT 绑定、
   组件生命周期、跨运行合并及报告由 XReactor 负责。不增加 XBin/PyBin 两套公共接口。

不追求完整 SVA 语法。首轮支持当前两个项目需要、能给出明确轨迹语义的集合；不增加
任意 Python 回调的 native 执行、多时钟时序关联、自动猜测 reset/flush/协议事件。

## 2. 实施前的基础与接入位置

下表记录制定计划时已有的基础和当时要补充的内容；完成状态见本文开头。

| 位置 | 现状 | 本计划要补的部分 |
| --- | --- | --- |
| `src/xreactor/coverage.py` | 值/范围/mask、gate、cross、原子采样、计数、schema/merge | 历史匹配、时序定义、绑定采样与 native 计数导入 |
| `src/xreactor/ir.py` | Expr、Wait/Within/Hold、Sequence、FSM | 可共享的时序程序表示、严格相邻步骤、capture、受限多实例 |
| `src/xreactor/backend.py` | Memory 与 native Sequence/FSM；有程序 cache | 两后端共用语义的覆盖观察注册、能力检查与快照 |
| `src/xreactor/reactor.py` / `execution.py` | 既有 phase 与 asyncio 收敛、生命周期 | 被动采集器所有权与收尾；不新增调度规则 |
| xcomm `xtrigger.h/.cpp` | ArmExpr/ArmSequence/ArmFsm、generation、RunUntil | 持久 count sink、组内原子采样、累计快照及容量诊断 |

本机 xcomm 源码在 `/home/xyl/picker/dependence/xcomm`，属于另一源码目录。实际实施需
同步提交其 C++/SWIG 改动、重建 binding，再更新 XReactor 适配与项目生成包。本次已修改该目录的 Trigger/Expr 头文件与实现、SWIG 接口和既有 Trigger/Expr 测试；
独立构建目录为 `/tmp/xreactor-coverage-native-build`。

原有通知路径的 `XTriggerEngine::AppendHit()` 将 watcher 置为未 armed，RunUntil 看到 hit 后返回；
subscription 再由 Python 调用 Rearm。新接入的 count 路径在 C++ 内更新覆盖组，保持注册，普通命中不进入通知 buffer。
仅把 Python `coverage.sample()` 接到 `@on` 后面，不能算完成 native 下沉。

普通 Sequence 通知仍为非重叠单实例；覆盖绑定可显式开启有界并发。每个 sample 最多推进一步，Within 窗口超时重启，Hold
中断只清零连续计数并继续等待该步骤。FSM 分支按声明顺序选择。需要保留这些已有契约，
不能悄悄把 Hold 改成严格序列失败，也不能把现有 Within(0, N) 解释成新增的同拍多步匹配。

## 3. 数据和执行架构

```text
静态 Bin / Bin.transition / Sequence / FSM
                  │
      可序列化定义 + 统一时序 IR
                  │
        绑定字段、时钟、phase、策略
                  │
     Python 参考执行器 / xcomm 执行器
                  │
        ┌─────────┴──────────┐
        │                    │
   通知等待者             原生累计覆盖
   XEvent/Trigger       bin/cross/capture
                             │
                       稳定边界快照
                             │
                    CoverageDatabase
                             │
                  跨 case 合并及报告
```

Python 保留定义、数据绑定、模型计算和报告；native 负责可编译表达式求值、历史状态、
定界上下文、bin/cross 匹配和计数。静态 bins 也不必全部 native：已经在 Python 中形成
的稀疏事务，直接 sample 可能更便宜；只有测量表明有收益时才增加批量 native 接口。

一组 point/cross 使用同一份逻辑快照，在同一执行路径原子提交。首版以整组为 native
编译或 Python 回退单位，避免某个 cross 的两端被不同时间的采样混合。

### 3.1 Trigger、Bin 与执行位置

| 维度 | 对象 | 职责 |
| --- | --- | --- |
| 用途 | Trigger | 描述触发条件，匹配后向等待者或订阅者交付事件 |
| 用途 | Bin/Coverpoint | 定义覆盖分类与目标，匹配后累计计数并参与 cross/报告 |
| 执行方式 | `@xtrigger` | 构造 Expr/Sequence/FSM IR；native backend 将其编译到 C++ |
| 执行方式 | `@pytrigger` | 在指定 sample phase 调用同步 Python predicate |

现有 `XTrigger` 是两类触发器的公共基类，并不表示只能在 C++ 执行。复用的是不可变
匹配定义及求值语义；Trigger 通知与 coverage 计数各自拥有注册状态、起始时刻和历史。
`Bin.transition` 降低到同一时序 IR；Bin 自身不再实现一套 Sequence/FSM 执行器。

匹配模式与结果用途必须分别声明：连续三个 BUSY sample 的静态状态 bin 计数为 3；
从非 BUSY 进入 BUSY 的 `enter` 条件计数为 1；连续保持三拍的模式在完成时计数为 1。
count 不隐式改写 `enter/each_sample/change`，也不把每次条件成立都当成时序完成。
以 Trigger 作为 group 采样源时，明确沿用该 Trigger 的模式；以 phase 作为采样源时，
普通静态 bins 按每个有效 sample 分类。

`@pytrigger` 可作为 Python 采集路径的条件来源，但任意 Python predicate 不能自动
编译到 native。`strategy="native"` 遇到此类依赖在启动前报错，`auto` 明示整组回退。
Python 闭包自行保存的历史不自动获得 reset、隔离或序列化能力；框架提供的历史匹配
使用共享 IR 和有明确生命周期的执行状态。

### 3.2 两个项目的实现边界

| 层 | 本次扩展 |
| --- | --- |
| xcomm Expr/时序执行器 | 复用现有表达式和 Sequence/FSM；补严格步骤、capture、受限 overlap/key；独立保存各注册的运行态 |
| xcomm Trigger 引擎中的覆盖注册 | 同阶段字段快照、bin 分类优先级、历史推进、同样本 cross、原子累计、容量及错误诊断 |
| xcomm C++/SWIG 接口 | 能力查询、批量注册、累计快照、历史/统计清理、注销；热路径使用数值 ID |
| XReactor IR/backend | 校验并降低定义，选择执行路径，将 native IDs 映射回覆盖项，维护 Python 参考语义 |
| XReactor Execution/coverage | 管理被动 collector 生命周期、核对快照、合并实际命中、计算覆盖率及生成报告 |

覆盖注册可以拆成 xcomm 内部独立的 coverage 模块，仍由现有 XTriggerEngine 的 phase
求值入口调用，并共用匹配实现；模块拆分不产生第二个时钟循环或调度器。
Python 对象、pytest case、报告模板和跨运行历史不进入 C++ 热路径。

## 4. 建议的用户接口

4.1/4.2 的基础接口已实现；4.3 的普通 Trigger 绑定已实现，capture/MatchRecord 仍为后续设计。

### 4.1 简单转移保持在 bins 声明中

```python
definition = CoverGroupDef("pipeline-state", (
    CoverPointDef("state", {
        "idle_to_busy": Bin.transition(IDLE, BUSY),
        "stall_then_exit": Bin.transition(BUSY, WAIT, WAIT, DONE),
        "busy": Bin.values(BUSY),
    }),
))
coverage = definition.instantiate("dut.pipeline")
```

相邻转移按相邻 sample 识别；手动 `sample()` 时是相邻调用，时钟绑定时才是相邻所选
phase。声明本身为不可变 schema，历史放在 CoverGroup 的运行实例里。

### 4.2 周期信号绑定

```python
coverage.bind(
    trigger=RisingEdge(dut.clock),
    fields={"state": dut.state},
    abort=dut.reset_active,
    contract="pipeline-state/v1",  # 标识额外 abort 条件的项目含义
    strategy="auto",        # auto / python / native
)

async with Execution(backend, agents=[agent], coverage=[coverage]):
    await run_case(agent)
```

绑定配置直接保存在 CoverGroup 实例上，由 Execution 统一启动和关闭；不新增公开 Binding
实体。用例不需要处理 TaskGroup、asyncio 锁或逐拍任务，每组只有一个生命周期所有者。
默认每次 Execution 重置统计；bind(accumulate=True) 保留累计计数。匹配历史始终隔离。

`abort` 是项目显式提供的布尔条件；框架不知道它对应 reset、flush 还是其他取消条件。
它清除该绑定的未完成匹配，不清掉已计数的覆盖。缺省不猜测任何引脚名。

`strategy="native"` 对不支持的类型或操作在启动前报错；`auto` 在报告中列出选择的路径
与回退原因。不能默默退回每周期 Python，也不能悄悄忽略某些 bin 来获得全 native。

### 4.3 复杂模式复用 Trigger

已有 `@xtrigger` 下的 Sequence/FSM 继续作为入口。增加严格下一 sample、连续重复、
capture/引用等必要操作后，复杂场景可绑定为采集触发器：

```python
scenario_coverage.bind(
    trigger=error_then_held_load(dut),
    fields={"route": dut.route},  # 此示例在完整模式结束的 phase 取值
    strategy="native",
)
```

该 Trigger 的内部程序可由普通 await 使用，也可作为 count sink 的输入；不为每个 bin
写一个 coroutine。开始阶段的字段必须显式 Capture，终点不能重新读取“当前字段”冒充
旧请求的上下文。完成时可以产生包含 start/end tick、终态、capture 的 MatchRecord，
再对其字段使用普通 bins/cross；native 可在内部直接消费记录，不必每次构造 Python 对象。

静态点与模式完成字段的 cross 以该完成记录为单位。两个独立模式分别在不同时间命中，
不自动构成 cross；需要相关性时，显式定义共同的时序模式或匹配 key。

## 5. 必须先冻结的时序语义

| 项目 | 建议契约 |
| --- | --- |
| 采样域 | 每个程序明确时钟/phase 或事务流。窗口以该域的 sample 数计；不推断多时钟关系 |
| 相邻转移 | `A,B` 只匹配相邻 sample；`A,X,B` 不匹配。事件压缩后的“下一次变化”需另行显式声明 |
| 转移重叠 | 简单转移使用滑动匹配；输入 `A,A,A` 对 `A,A` 命中两次。可显式选择非重叠 |
| 严格步骤 | 新的 Next/连续重复在规定 sample 失配时结束该 attempt；与现有 Hold 等待累计连续成功的语义分开 |
| 窗口 | 上下界包含，满足上界的完成优先于超时；首轮不增加零时间多步循环，同拍条件用一个组合表达式 |
| 非重叠 | 现有 Sequence 默认保留一个活动 attempt，终点 sample 不同时作为下一次起点 |
| 受限重叠 | 显式启用，每次起始条件实际匹配建立 attempt；每个 attempt 首次完成计数一次，多次同时完成可增加多次 |
| 容量 | overlap/key 必须有 max_active；溢出报错并标记采集不完整，不静默丢弃或驱逐旧上下文 |
| key | 比较键由项目提供，不把 ready/valid、地址、tag 或 FIFO 顺序硬编码进框架。重复活跃 key 默认报错 |
| 同拍旧结束/新开始 | 在显式允许复用的 overlap/key 模式中，先用旧 capture 完成旧 attempt，再建立新上下文；新 attempt 不消费旧请求的完成事件。非重叠模式仍从下一 sample 开始 |
| Capture | 明确起点或命名步骤、位宽/符号及 X/Z；运行态不放入共享程序，也不被其他 waiter/collector 继承 |
| gate | 静态 bin 保留现有 iff。时序 bin 默认在 gated sample 断开历史，防止跨被屏蔽周期拼接；显式 pause 才冻结状态与年龄 |
| ignore | 调整覆盖分类，不删除时间；`A,X,B` 即使 X 被 ignore，也不能成为相邻的 `A,B`。时序匹配的推进与命中计数的优先级分别处理 |
| abort | 优先于同 sample 的推进/完成；清历史、保留累计计数。对应条件由项目传入 |
| X/Z | 不转成普通 0；默认不满足依赖该未知值的转移并断开连续性，记录 unknown 样本。若要把 X/Z 当目标需显式建模 |
| 无触发/未完成 | 不计命中；提供 activation、expired、aborted、pending 等诊断。关闭时不把 pending 伪装成完整覆盖，也不自动当协议失败 |
| 计数与断言 | `at_least=N` 仍表示累计 N 次，不等于连续 N 拍；时序识别失败不自动等于断言失败 |

所有 gap/overlap/capture/abort/窗口策略进入可序列化定义。相同 bins 名但匹配规则不同的
运行不得合并；执行策略 python/native 不改变语义 digest。

手动采样和信号绑定最终都形成明确的采样契约；除 bins 定义外，还要校验采样域、字段
含义和模式语义。绑定后的契约摘要不包含对象地址或 native handle；无法稳定描述的
自定义派生逻辑需项目提供名称/版本，不能仅凭相同字段名就认定可以合并。

样例轨迹必须覆盖：`A,B`、`A,X,B`、`A,A,A`、门控中断、未知值、截止拍完成、一个新请求
在旧请求结束同拍出现、多个 attempt 同拍完成。先明确预期计数，再写执行器。

## 6. native 实现与生命周期

### 6.1 同一执行引擎，两种命中处理

为 xcomm 程序注册增加内部 sink 类型：notify 延续现有 XBackendHit；count 更新注册所
拥有的 counters，并按约定重新开始或保留其他活跃 attempt。普通计数不能触发
TriggerHit 返回，也不能自动生成 Python handler 任务。若同一 phase 还有普通 Trigger
命中，照常返回；不能为了 coverage 越过既有 phase barrier。

整组静态匹配编译为字段读取、exact/range/mask 索引、bin ID 与 cross tuple。一次 logical
sample 先准备命中与状态变更，再提交计数；错误不能留下半组结果。首批 native 支持已
声明位宽的 bool/整数/枚举；最初的 <=64-bit 字段限制已由 coverage ABI v2 移除。
宽值比较、范围、mask、转移、Iff、完整非法值快照和高位 X/Z 检查独立验收，禁止截断。

illegal bin 默认在提交本次统计后返回有界诊断并令 Python 抛错；可记录继续的模式也必须
有诊断容量与溢出处理。64-bit native 计数器溢出必须报错，不能回绕成未覆盖。

### 6.2 不改变采样 phase

RisingStable/FallingStable/DriveStable 使用现有定义。DriveStable 仍需等待 Python
驱动收敛并 RefreshComb；native count 不能取消这种必要往返。优化目标是消除由覆盖
命中额外造成的往返，不承诺本来需要 Python 驱动的仿真变成全 native。

接受事件的边沿前条件与寄存器更新后的值不能混读。e203/Cache 如需两阶段证据，由项目
指定前后采样点并关联成记录，或由同一个时序程序跨 phase 显式观察；首批通用时序
程序仍限制单一采样域，跨 phase 关联在项目观察器中完成。不能把事后读取的信号当作接受快照。

多次结算同一个 phase 不应重复增加计数。实现需要稳定的 sample identity，并明确
DriveStable 的一次最终采样边界；不能仅按一次 Python 函数调用就加一次。

### 6.3 被动所有权与快照

- 被动 collector 不独立推进时钟，也不使无用例活动的仿真无限运行。推进仍来自现有
  Execution 中的等待/用例预算；只存在 collector 时不制造新的 clock demand。
- collector 独占自身运行态和 native handle；不同注册可共享不可变程序，不共享历史。
- 活跃 native group 不允许同时手动 sample 到同一组 counters，避免重复计数。
- 稳定边界读取累计快照；Python 用 generation/epoch 更新该运行的镜像，不把每次
  checkpoint 当作新 shard 相加。反复 snapshot/export 不会改变最终计数。
- 退出时在 backend 仍有效且推进已停的边界停止采样、读取末次快照、释放 handle，随后
  才清 native execution state。正常、异常、外部取消及部分启动失败都走相同所有权链。
- 导出失败保留原验证异常；无人等待的计数器/上下文错误仍从 Execution 退出传播。
- `reset()` 作为显式清空全部运行统计的操作；新增清历史动作与清计数分开，项目 reset
  可以只 abort 未完成匹配。累积计数跨 case 合并，未完成历史永远不跨 case 合并。

### 6.4 C++/SWIG 接口契约

下表冻结操作职责；具体类型和函数名在 P0 确定。它们是 backend 接口，验证用户继续
使用 CoverGroup/Bin/Trigger 与 Execution。

| 操作 | 必须具备的契约 |
| --- | --- |
| 查询能力 | 返回覆盖接口版本、支持的字段/模式和容量限制；在编译与注册前核对，避免旧 binding 到运行中才失败 |
| 注册整组 | 接收已编译字段、匹配程序、bin/cross IDs、采样域及策略；全部校验和资源申请成功后才生效，失败不留部分 watcher |
| 读取快照 | 返回 handle generation、统计 epoch、截至的 sample identity、累计 counters 和有界诊断；读取不改变计数或历史 |
| 清除历史 | 仅清未完成 attempt、capture 及条件历史，按声明规则重新开始；保留已累计的覆盖计数 |
| 重置统计 | 原子清计数、诊断和匹配历史并切换 epoch；Python 镜像同步重置，避免旧快照被再次累加 |
| 注销 | 先由生命周期所有者在稳定边界取最终快照，再释放所有组内资源；generation 防止旧 handle 操作新注册 |

持久 count 注册不能经现有 AppendHit 的“停止 watcher → 返回 Python → Rearm”循环
累计普通命中。它在同一次 native phase 求值中推进匹配并提交计数，通知 watcher 仍保留
原行为；illegal/容量耗尽/计数溢出等错误才进入有界错误交付路径。

每个 covergroup 注册统筹自己的 sample：读取字段、准备各 point 的命中集合、形成该
sample 的 cross tuple，最后统一提交。不能给每个 bin 独立注册普通通知 watcher 后，
再把来自不同采样时刻的事件拼成 cross。多个模式同拍完成时，分别保留对应完成记录，
不得将不同 key/attempt 的字段混合成同一条记录。

资源占用与推进需求必须分别可查询。被动覆盖注册计入资源释放检查及
`ClearExecutionState` 的存活检查，但不构成新的 clock demand。仅有覆盖注册时，显式
调用有预算的 RunUntil 仍可采样；Execution 不因这些注册自行无限推进。任何 count 注册
都不能绕过既有 DriveStable 结算与错误边界。

## 7. 数据库和报告

新增时序 matcher 类型与版本，报告显示转移/模式定义、采样域、窗口、gap/overlap 策略、
执行路径及回退原因。保留 completed hit counts；activation、expired、abort、pending
为独立诊断，不混进正常 bin 分母。匹配完成后的有限首/末证据可选保存，不默认存完整轨迹。

已交付的范围为 `diagnostics="off"|"summary"`，默认关闭；汇总包含 started/completed/
failed/expired/aborted/cleared/peak_active/unfinished_at_close。`inspect()` 只在执行内
按需返回活跃实例的步骤、等待年龄和 FSM 状态，不写历史日志。事件计数合并相加，峰值取
最大值；报告标明收集和未收集诊断的运行数量。退出未完成不会自动当作协议失败。
`overlap=True` 要求显式 `max_active`；旧结束/新开始同拍先释放容量，超限报错并标记
采集不完整。多个完成可观察相同引脚条件，此能力不表示已实现按事务 key 配对。

当前报告只支持格式版本 2，其他版本明确拒绝；这一规则替代早期保留 v1 读取能力的
设想。same-instance 合并需检查定义与采样契约一致，原生指针及后端 handle 不能进入
可移植 schema。RTL/配置来源另存运行元数据，合并工具应能检查显式提供的兼容身份。

设计要求可以引用覆盖项和 checker 的实现位置作为评审依据，不映射 pytest PASS，也不
以测试标签构造功能点完成率。没有采样器的场景仍为未测量，不能以空计数假装完成建模。

## 8. 分阶段实施与退出条件

| 阶段 | 交付 | 可以进入下一阶段的证据 |
| --- | --- | --- |
| P0：契约与基线 | 冻结上述轨迹语义、C++/SWIG 能力与注册/快照契约、最小 Python API、样本身份；记录现有吞吐/往返/内存基线 | 手工可复核的正反轨迹、e203/Cache 首批目标及观察位置确认 |
| P1：简单转移与共享时序 IR | Bin.transition、严格步骤、Python 参考执行器；适配现有 Sequence/FSM | 旧 Trigger 行为保持；重叠、gap、unknown、schema 往返及跨 case 合并有确定预期 |
| P2：native 采集闭环 | xcomm count sink、静态 bins/cross 与转移 lowering、CoverGroup.bind、快照/清理 | 同一轨迹 Python/native 逐 bin 计数一致；重复快照不重计；纯计数不新增逐命中返回 |
| P3：复杂状态与并发上下文 | Capture、受限 overlap/key、多终态完成记录与字段 cross | 乱序、重复 key、容量耗尽、旧完成/新开始同拍、跨请求隔离和取消均有确定结果 |
| P4：真实项目扩展 | 先复用已有定向激励补观察，再增加缺失的重叠/竞争 case | 首批状态场景真实命中，端到端及内部检查均有证据；已知缺陷保留失败而非删点 |
| P5：性能与文档收尾 | A/B 基准、执行路径报告、使用教程、覆盖缺口清单 | scoped/native/项目回归、性能基线比较、严格文档构建完成 |

P1/P2 已交付端到端路径。P3 已交付共享进度实现及可选有界 overlap，capture/key 与
完整完成记录仍待需求明确。P4 的项目内部采样和属性检查在后续工作中已补充，具体关闭
情况以项目验证计划和运行证据为准；模式并发不表示完整多事务关联已经交付。

P2 内部顺序为：xcomm 原生整组采样/计数与 C++ 轨迹测试 → SWIG 接口及 binding 重建
→ XReactor backend 与 collector 接入 → Python/native 差分及生命周期回归。
P1 的 Python 参考实现用于明确语义，不能替代 P2 的 native 计数交付；P3 新增时序操作
也必须同时在通知与覆盖用途上验证，不形成覆盖专用的第二套匹配语义。

修改位置以既有 `ir.py`、`coverage.py`、`backend.py`、`execution.py` 和 xcomm
`xtrigger/xexpr` 为主。可把 matcher runtime/lowering 拆到私有模块；不按功能点新建
测试文件，不引入公共 scheduler、VerificationScope 或项目协议判断。

## 9. e203 与 Cache 的落实顺序

| 项目 | 首批复用现有激励并补观察 | 需要新增激励/上下文能力 |
| --- | --- | --- |
| e203 | 首响应→WAIT2ND→第二命令、等待自环；leftover 装载/错误保持；响应缓冲 capture/drain | 历史错误→held 装载清除；单/双命令完成与下一输入同拍；满缓冲竞争 |
| Cache | refill 起始/推进/回绕、末拍 metadata 提交；early response 一次交付；dirty writeback 等待确认 | refill 完成但 CPU 仍受阻；forwarding 保存/覆盖/清除；CPU/probe 及 SRAM 端口竞争 |

e203 需单独生成带内部信号导出的观察版本；Cache 现有 VPI 仅少量诊断信号可读，其他
层次路径与优化结果需核对。记录 RTL/config/导出信号版本；不可读时使用可证明等价的
观测点或模块级 harness，不猜测内部值。内部观察可以只读，不改 Driver 的协议时序。

随后逐条评审已有 49/77 项内部要求及其场景。当前 JSON 中分别有 130/209 条
required_scenarios 说明，但它们还不是已实现 bins，也不一定一条对应一个 bin。
最终规模由合法状态/转移、阻塞位置与长度、历史来源、数据选择、way/word、优先级和
跨事务依赖决定。需要给每项明确采样方式、检查方式和可达性，不以“凑够若干百点”验收。

Cache 的独立 early-response overlap 已知失败需要保留。当前配置禁止的 Stage3 flush
按独立负例处理；通用框架不内置该语义。CPU burst 等契约不明的项目项先补规格核对，
不把未证明的假设写成覆盖目标或用排除 bin 的方式获得 100%。

## 10. 验证与性能验收

语义测试复用现有 coverage、compiled patterns、subscription 和生命周期测试组：

- 静态优先级、ignore/illegal/default、gate、cross、多命中、at_least 与原子提交；
- 相邻/非相邻、连续/非连续、窗口首尾、重叠与非重叠、abort/gap/X/Z；
- capture 隔离、乱序 key、多完成、重复 key、容量上限和未完成退出；
- 同一原始轨迹对照 Python/native，既检查计数也检查完成 sample/捕获字段；
- count 与 notify 共存，不改变 Driver 接受顺序、连续提交时序或同 phase 回调顺序；
- 重复 snapshot、错误清理、外部取消、backend 复用、native 槽位/表达式缓存释放；
- 合并只联合完整命中，不能把两次运行的半段序列或单维 cross 拼成一次命中。

性能分别测：无 collector 基线、Python 逐拍采样、native 静态、native 时序、稀疏事件、
高命中率、多个活跃上下文，以及 e203/Cache 同 seed 同 RTL 的端到端 A/B。
记录 half-ticks/s、每样本成本、RunUntil 返回次数、Python 唤醒次数、内存峰值、注册/
导出耗时；交替运行并保存全部样本与中位数。P0 根据固定 runner 方差冻结数值门槛，
不预先承诺所有工作负载低于 1% 或固定倍数加速。

结构性硬门槛是：普通 native count 不因每次命中返回 Python；计数与参考路径完全一致；
活跃状态内存有界；无采集时不引入额外逐拍 Python 工作。已有事务采样继续允许 Python
路径，不能为了“全 native”让端到端更慢或改变采样意义。

每阶段先跑改动对应的测试；修改 native 时执行 xcomm 的 trigger/expr/clock 测试并
重建 binding。最后集中运行一次：

```bash
python3 -m pytest -q --require-xspcomm
examples/integration/e203/run_pytest.sh
python3 -m pytest -q examples/integration/cache/test_cache_coherence.py
mkdocs build --strict
```

交付必须同时包含代码、真实场景证据、未覆盖清单和两种执行路径的限制说明。仅增加
计划条目、仅接 Python handler 或仅显示更大的 bin 分母，都不满足本计划。
