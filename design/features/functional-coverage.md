# Functional coverage 设计

本文定义 XReactor 的 `CoverGroup / CoverPoint / Bin / Cross` 模型。目标不是照搬
SystemVerilog 语法，而是保留硬件验证中真正影响结果可信度的语义，并适配 Python、
pytest、XClock 和事务级 Monitor。

状态说明：本文记录静态 bins 首版设计。状态转移、复杂历史模式与 native 采集的下一轮
方案见[有状态覆盖实施计划](../delivery/stateful-coverage-plan-2026-09.md)。基础 Trigger IR 复用、转移 bins 和 native count sink 已实现；capture/key 仍待后续阶段。
当前使用方式见[覆盖指南](../../docs/guides/coverage.md)，它扩展了本文 V1 的事务采样边界。

## 1. Coverage 回答什么问题

代码覆盖率回答“RTL 的哪些结构执行过”，功能覆盖率回答“验证计划中的哪些行为组合
发生过”。两者不能互相替代：

- Verilator/VCS line、branch、toggle coverage 属于 DUT code coverage；
- CoverGroup/Point/Bin/Cross 属于 testbench functional coverage；
- scoreboard/reference model 的 pass/fail 属于 correctness，不能用 coverage 代替；
- coverage 到达目标只证明已定义的验证空间被采样，不证明验证计划完整。

因此 e203 环境必须同时产出 RTL line coverage、functional coverage，并让 reference
model 对每个已接受事务做正确性检查。

## 2. 三层模型

### 2.1 Schema（定义）

Schema 是不可变的验证计划：

```text
CoverageSchema
  CoverGroupDef
    CoverPointDef
      BinDef
    CrossDef
      CrossBinDef
```

每个节点具有稳定的层次路径和 ID。Schema 可规范化为 JSON，并计算 digest。任意动态
Python callable 都不能成为默认的可移植 schema；若允许自定义 extractor/matcher，必须
作为运行时 binding 与 schema 分离，并提供显式、稳定的名称和版本，否则数据库不得
跨进程合并。推荐由 Monitor 先把派生属性写入 transaction，再由 point 按字段名取值。

### 2.2 Instance（运行状态）

Instance 保存某个 covergroup 实例的：

- 每个 bin 的 hit count；
- group/point/cross 的 sample count；
- ignored、unmatched 和 gated-off 数量；
- illegal hit 记录；
- 第一次/最近一次命中的 test、seed、sim tick 等可选 provenance。

定义和计数分离后，同一种 agent 的多个实例既可单独报告，也可按 type merge。

### 2.3 Database（回归数据库）

Database 负责跨 pytest case、seed、进程或 CI shard 合并。合并前必须校验 schema
digest；同名但 bin 边界不同的数据必须报错，不能静默相加。计数使用整数相加，覆盖率
由合并后的计数重新计算，不能平均各次运行的百分比。

报告版本 2 保存独立采集 origin、run_id 和内容 snapshot_id。合并只允许不重叠的来源；
重复快照和累计链重叠在提交前拒绝。普通 bin 保存按来源组织的稀疏 count、first/last
metadata，native 当前没有逐次命中位置，first/last 为 null。手动事务采样可在 instantiate
中声明稳定的 contract；项目通过 run_metadata 保存测试名、seed、RTL 与配置基线。

## 3. 采样模型

### 3.1 默认采样单位是 transaction

XClock 已保证 half-step 返回的是稳定相位；functional coverage 不再发明另一套 HDL
phase。推荐数据流如下：

```text
XClock stable phase
  -> Monitor 判断 ready && valid
  -> 构造不可变 Transaction(snapshot + tick + metadata)
  -> Scoreboard/reference model 检查
  -> CoverGroup.sample(transaction)
```

Scoreboard 与 coverage 必须消费同一个 snapshot。不得让 coverage 再次读取 live XData，
否则 Python 调度后读到的可能已是另一个周期。

对于 reset、stall length、latency 等周期级属性，Monitor/collector 应先形成语义明确的
观测对象，再采样 coverage。框架可以提供把 collector 连接到 queue/subscription 的适配器，
但 `CoverGroup` 本身不推进仿真、不持有 XClock，也不隐式创建 asyncio task。

### 3.2 原子采样

一次 group sample 分为三步：

1. 从同一 snapshot 提取所有 point value，并计算 gate；
2. 解析 point bin 和 cross bin 命中；
3. 一次性提交计数，然后报告 illegal/error。

这样 extractor 或 matcher 异常不会留下“前半组已计数、后半组未计数”的状态。
同一次采样中的 cross 必须使用这次 point 的 bin hit 集，而不是重新读取 source。

### 3.3 Gate

Group、point、cross 均可有 `iff` gate。gate 为 false 时不计入 hit，单独累计 gated-off
次数以便诊断“未覆盖”究竟是 stimulus 缺失还是采样被关闭。reset 期间通常由 group gate
统一屏蔽。

## 4. Bin 语义

### 4.1 V1 必须支持的 bin

- exact：一个值或枚举值集合；
- range：一个或多个闭区间；
- wildcard：`value/mask`，用于 opcode、地址区域和协议字段；
- array bins：把一个值域确定性拆成 N 个 bin；
- default：捕获所有未进入显式 normal bin 的值，用于诊断，但不进入覆盖率分母；
- ignore：从 normal 和 cross 空间排除；
- illegal：记录后触发明确错误；
- `at_least`：bin 至少命中多少次才算 covered。

Transition bin 很有用，但需要定义 non-overlap、连续采样、gate 中断和 reset 清历史等细节，
放在 V2；首版可先由 FSM/collector 把序列归约成 transaction 属性后采样。

### 4.2 优先级与重叠

命中优先级固定为：

```text
illegal > ignore > normal > default/unmatched
```

- illegal 即使与 ignore 或 normal 重叠也必须报错；
- ignore 即使与 normal 重叠也不会增加 normal hit；
- normal bin 可以重叠，一次采样可命中多个 bin；
- schema finalize 时默认检测可静态判断的重叠并给出警告，`detect_overlap=True` 时升级为错误；
- predicate matcher 无法普遍做静态重叠分析，因此不应是 V1 的主要 bin 表达。

### 4.3 Coverage 计算

normal bin 的 covered 状态是离散的：

```text
covered(bin) = hits(bin) >= at_least(bin)
```

在达到 `at_least` 前不能按 `hits / at_least` 给部分分。Point coverage 是 covered normal
bins / eligible normal bins。ignore、illegal、default 和 disabled bins 不进入分母。
完全被 ignore/illegal 覆盖的普通 bin 也不进入分母和自动 cross；部分排除保留其剩余空间。
空 bin 的 schema 与排除原因仍留在报告中。区间/mask 联合排除采用符号分析，复杂度超限
时报 schema error。Transition 按完成时优先级解析静态完成值与相同模式的完全排除。

Group coverage 是 point/cross coverage 的加权平均：

```text
sum(item.coverage * item.weight) / sum(item.weight)
```

`goal` 只决定 pass threshold，不改变百分比；`weight=0` 可显式让某项只报告、不进入 group
分数。空分母必须在 finalize 阶段报错，不能返回虚假的 100%。

默认 covered/assert_coverage 同时要求组目标与所有正权重子项目标达成、采集完整且无
illegal hit；goal_met 单独表示组分数达到阈值。assert_coverage(per_item=False) 可显式选择
只检查组阈值，仍拒绝非法命中和不完整采集。覆盖验收不能代替 Scoreboard 正确性检查。

## 5. Cross coverage

Cross 的单位不是原始 value，而是同一次 sample 命中的 point bin ID 的笛卡尔积。
ignore、illegal 和 default point bins不参与自动 cross 空间。
Cross ID 使用维度数组的无歧义编码；显示标签不参与计数键。报告显式保存 tuple、kind
与阈值，避免名称中包含分隔符时合并不同组合。自动展开前先检查乘积大小；显式 include
只解析指定组合，不构造整个笛卡尔积。

自动 cross 很容易指数爆炸，因此需要：

- `max_auto_cross_bins` 上限，超限在 schema finalize 时失败；
- 允许只声明关心的 tuple；
- 允许按 point-bin selector 定义 ignore/illegal tuple；
- 计数采用稀疏存储，但 coverage 分母来自 schema 中的 eligible tuple；
- 重叠 point bins 产生多个 tuple hit，语义必须稳定且在报告中可见。

e203 的典型 cross 包括：

- target(itcm/biu) x alignment(0/2) x response(ok/error)；
- target x command_backpressure x response_backpressure；
- lane_cross x sequential x holdup；
- request class x observed command count(0/1/2)。

这些 cross 比单独统计每个字段更能发现遗漏路径。

## 6. Illegal bin 不是 assertion 的替代品

Illegal bin 用于验证计划中的非法输入/状态分类，并保留统计和 provenance；协议时序错误仍应由
monitor/assertion/scoreboard 检查。默认策略是在原子提交本次 coverage 后抛出
`IllegalBinError`，pytest 因此失败。压力测试也可配置为 record-and-continue，以一次收集多个
错误，但最终测试必须因存在 illegal hit 而失败。

## 7. 报告和 pytest

最低输出包含：

- 人类可读的层次摘要和未覆盖 bin 列表；
- 版本化 JSON（schema + counts + provenance）；
- pytest 结束时写出本 worker 数据；
- 回归结束合并并检查 group goal；
- 可选 UCIS exporter，作为后续互操作层，而不是首版内部数据模型。

项目级 pytest fixture 负责 DUT 生命周期、seed、artifact 目录、line coverage 文件和 functional
coverage database；它属于 e203 验证环境，不要求 XReactor 核心猜测协议或自动生成 fixture。

## 8. 性能边界

Coverage 是观测慢路径，不能进入 native trigger 热循环。优化顺序是：

1. Monitor 只在实际 transaction 时 sample；
2. schema finalize 后预编译 source path、exact-bin index 和 cross eligible set；
3. cross 使用整数 bin ID 和稀疏 counters；
4. 可批量提交 transaction snapshots；
5. profile 证明 Python matcher 成为瓶颈后，再考虑 native aggregation。

这能保证仿真空转、背压等待时不会为 coverage 每周期跨越 Python/C++ 边界。
若调用方不消费逐次命中详情，应使用 `sample(transaction, details=False)`；它只跳过
`CoverageSample` 结果构造，不改变计数和 illegal-bin 行为。实测成本、e203 on/off A/B
和统一 HTML 报告见 [coverage-performance-and-reporting.md](coverage-performance-and-reporting.md)。

## 9. 建议 API 形状

```python
fetch_cov = CoverGroupDef(
    "ifu_fetch",
    description="验证取指路由、对齐与返回状态的组合覆盖。",
    points=[
        CoverPointDef("target", bins={
            "itcm": Bin.values("itcm"),
            "biu": Bin.values("biu"),
        }, description="覆盖本地 ITCM 与外部 BIU 两条取指路径。"),
        CoverPointDef("alignment", source="alignment", bins={
            "word": Bin.values(0),
            "halfword": Bin.values(2),
            "illegal_odd": Bin.illegal(Bin.masked(1, 1)),
        }),
        CoverPointDef("response", bins={
            "ok": Bin.values("ok"),
            "error": Bin.values("error"),
        }),
    ],
    crosses=[CrossDef(
        "target_x_alignment_x_response",
        ...,
        description="验证路由、对齐和返回状态的重要组合。",
    )],
    iff=Iff.equals("in_reset", False),
)

coverage = fetch_cov.instantiate("core0.ifu")
coverage.sample(fetch_transaction)
```

`description` 是 schema 的纯文本元数据，适合回答“为什么覆盖这个点”；名称回答
“这个点是什么”。它随 JSON shard 和 HTML 报告传播，并参与 schema digest，但不会在
`sample()` 热路径中读取。空描述不写入 JSON，以保持旧的无描述 schema digest 稳定。

最终 API 可以提供声明式 class/decorator 糖，但底层必须先有上述显式 schema/instance 模型，
不能把 decorator 本身当成数据模型。

## 10. 实现阶段

### V1：结果可信且可用于 e203

- 不可变 schema、finalize、stable IDs/digest；
- exact/range/wildcard/default/ignore/illegal/array bins；
- point/group gate、weight、goal、at_least；
- automatic/explicit cross 与规模上限；
- 原子采样、illegal policy、unmatched diagnostics；
- instance/type merge、版本化 JSON、schema mismatch error；
- pytest 中生成 functional coverage artifact；
- e203 reference-model transaction 上的覆盖模型。

当前代码位于 `src/xreactor/coverage.py`，上述 V1 中除 UCIS 和 transition
bin 外的核心模型已经实现并用于 e203 回归。实现采用 `CoverGroupDef.instantiate()`
显式分离 schema 与 instance；`CoverageDatabase` 支持版本化 JSON、round-trip、同实例
回归合并和同 schema 多实例 type 汇总。独立语义测试覆盖优先级、原子性、gate、
cross、爆炸上限、schema digest 和 merge mismatch。

### V2：序列与生态互操作

- transition bins 和历史 reset 语义；
- threshold/bin callbacks 与 coverage-guided stimulus hook；
- UCIS import/export；
- profile 驱动的批量/native aggregation。

### 非目标

- 不从 RTL 名称自动推断验证计划；
- 不把 line coverage 混进 functional coverage 百分比；
- 不用 coverage 替代 reference model/scoreboard；
- 不因追求 SystemVerilog 语法兼容而引入 HDL scheduling region。

## 11. e203 对设计的验证价值

`e203_ifu_ift2icb` 会验证 coverage 设计是否真的可用，而非只有 API：

- reference model 根据 byte-addressable memory 预测 instruction 和 error；
- ICB memory agent 注入 command/response backpressure 和 error；
- monitor 记录目标、地址、命令次数、latency、holdup、lane crossing；
- coverage cross 驱动 directed + seeded random 序列补齐角落；
- pytest 对 scoreboard mismatch、timeout、非法协议、coverage goal 都产生确定性失败；
- Verilator coverage 数据单独转换为 line coverage 报告。

如果某个验证意图无法从 transaction snapshot 表达，优先改进 monitor/transaction 模型，
而不是让 CoverPoint 直接窥探 live DUT 信号。

### 已发现的 e203 接口约束

压力序列证明 `ifu_req_last_pc` 虽与 request 信号并列，却不是必须保持到 response 的普通
payload。same-cross-holdup 的 command 在请求握手当拍读取旧 `pc_r`；two-uop 的第二个
command 则在握手后读取已经更新成当前请求 PC 的 `pc_r`。验证环境因此必须在请求接受后
更新该输入，参考模型第二个 uop 地址为 `pc + 2`。若机械地把全部 request 输入一直保持到
response，会造成第二个 command 重复访问当前 lane。

这也是 transaction snapshot 与 live control state 必须区分的实例：coverage/scoreboard
仍消费请求握手时的不可变语义 transaction，但 agent 可按明确协议继续更新 live state。
