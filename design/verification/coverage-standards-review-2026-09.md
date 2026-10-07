# XReactor functional coverage 标准对照评审

评审日期：2026-09-30。初次评审对象是修复前工作树，包括尚未提交的实现；相关源码 SHA-256
保存在探针结果（本地产物：`coverage-standards-probe-results-2026-09-30.json`）中。

**结论：现有模型适合继续作为 Python 硬件验证框架的 functional coverage 基础。
核心架构无需推倒重做，修复前存在影响覆盖率数值和达标判断的边界问题；当前也没有
UCIS 数据交换实现，不能宣称 UCIS compatible 或 SystemVerilog 全语义兼容。**

下文的六项问题和 101 项基线测试记录保留初次评审结果。随后按用户要求完成实现修复，
修复后的源码摘要与实际结果见修复探针 JSON（本地产物：`coverage-standards-fix-results-2026-09-30.json`）。

**修复状态（2026-09-30）**

| 问题 | 已实现行为 | 对照结果 |
| --- | --- | --- |
| 完全排除的普通 bin | 移出分母、uncovered 和自动 cross；保留排除原因；部分排除保留 | 合法空间命中后 point/cross 从 50% 修正为 100% |
| cross 名称碰撞 | 无歧义数组编码 ID 与结构化 tuple；显示 label 单独保存 | 四组合保留四计数器，首次命中为 25% |
| 子项目标不参与验收 | 默认检查所有正权重子项；per_item=False 可显式只检查组阈值 | 组分数 33.33% 达到组目标 30%，子项缺口仍使默认断言失败 |
| 非法命中与 covered 矛盾 | 独立 goal_met、items_goal_met、has_illegal、collection_complete；covered 结合验收条件 | 普通空间仍为 100%，有非法命中时 covered=false |
| 重复/累计快照相加 | 自动采集来源、可选 run_id、snapshot_id；合并前拒绝来源重叠 | 单次命中 at_least=2 的 bin，重复导入被拒绝，仍为 0% |
| 普通命中缺少证据 | 按 bin/来源保存 count 和 first/last metadata；origins 保存运行上下文 | 合并后可定位 test/seed；native 仅保存运行关联，实际命中位置为 null |

报告 JSON 使用版本 2，按开发阶段约定仅接受当前格式，不保留旧格式转换。
手动事务采样新增稳定 contract，运行配方自动保存 nodeid、seed 和产物目录。
详见[公开 API 与报告说明](../../docs/guides/coverage.md)。

验证：定向 coverage、native pattern、运行配方与跨用例测试 **144 passed**；最终完整套件
**559 passed**（`XCOMM_PYTHON=/tmp/xreactor-coverage-native-build/python PYTHONPATH=src
python3 -m pytest -q --require-xspcomm`）。六项探针及 JSON 往返检查通过；报告 JavaScript
通过 `node --check`。新增测试还覆盖联合区间/mask 排除、部分排除、128 位值域、名称碰撞、
当前格式校验、累计快照与数据库合并的原子性。

这些修复没有引入 UCIS import/export 或完整 SV transition 语义；RTL/config 的兼容集合
仍由项目决定。coverage 验收达标不表示 Scoreboard 或整个测试通过。

2026-10-01 实施验证：完整框架 native 必需回归为 **560 passed**；真实 e203/Cache
项目回归分别 **31 passed / 27 passed**。内部属性的真实激活、比较失败与关闭状态独立
保存，Cache burst 反例没有因 bins 命中而被关闭。运行摘要及源码哈希见
RTL 验证证据（本地产物：`rtl-property-evidence-2026-10-01/results.json`）。

**应该对照哪些标准**

不同资料解决不同层的问题，不能仅凭输出格式判断功能覆盖是否合理。

| 资料 | 性质与范围 | 对 xreactor 的用途 |
| --- | --- | --- |
| [UCIS 1.0](https://www.accellera.org/images/downloads/standards/ucis/UCIS_Version_1.0_Final_June-2012.pdf)，2012 | 覆盖数据库模型、C API 与 XML 交换；包括实例、计数和运行历史 | 评估数据库能否互操作，规划 exporter；重点是 §8、§9 |
| [IEEE 1800-2023](https://standards.ieee.org/ieee/1800/7743/) | SystemVerilog 的语言语法和语义，含 functional coverage | 决定哪些采样/bin/cross 行为值得保留；官方 GET 提供正文入口 |
| [IEEE 1800-2017 原始标准](https://fpga.mit.edu/6205/_static/F25/documentation/1800-2017.pdf) | 本次可检索核对的 functional coverage 原始条文 | §19.5.5、§19.5.6 核对 ignore/illegal 值排除；§19.7、§19.11 是选项与计算的复核入口 |
| [PSS 3.0](https://www.accellera.org/images/downloads/standards/pss/Portable_Test_Stimulus_Standard_v3.0.pdf)，2024 | §18 data coverage；§19 behavioral coverage；Annex F 行为形式语义 | 对照事务级覆盖，以及未来跨事件场景、属性关联的表达能力 |
| [ISO/IEC/IEEE 29119-4:2021](https://www.iso.org/standard/79430.html) | 软件测试设计技术标准 | 用于设计测试空间的方法论；ISO 页面没有给出可用于本次互操作验收的 coverage 数据格式 |
| [LCOV tracefile](https://raw.githubusercontent.com/linux-test-project/lcov/master/docs/man/geninfo.rst)、[LLVM coverage mapping](https://llvm.org/docs/CoverageMappingFormat.html) | 软件 code coverage 的实际工具格式与实现契约 | 对照代码覆盖导入、结构标识、原始计数和格式版本；不能代替功能 bins |

版本边界：Accellera 的[UCIS 发布页](https://media.eda.org/downloads/standards/ucis)仍列出
1.0。IEEE 官网确认 1800-2023 为 active，本次未取得其完整正文，因此具体排除规则
引用可核对的 2017 原始条文，并以 PSS 3.0 §18.3.5/§18.3.6 交叉核对。
这不是对 2023 全部语言条款的符合性认证。

**可参考的开源实现**

| 实现 | 已核对的一手资料 | 对 xreactor 的启发 |
| --- | --- | --- |
| cocotb-coverage | [官方介绍](https://cocotb-coverage.readthedocs.io/en/latest/introduction.html)：CoverPoint、CoverCross、可自定义匹配关系、多 bin 命中、转换函数表达转移 | Python 实现无需照搬 HDL 语法；xreactor 的可序列化 schema 更便于判断合并兼容性 |
| PyVSC / PyUCIS | [PyVSC coverage 文档](https://pyvsc.readthedocs.io/en/latest/coverage.html#saving-coverage-data)：通过 PyUCIS 写 UCIS XML 或调用 UCIS C API | exporter 可放在内部模型外；可作为独立读取器候选，仍需针对实际输出做验证 |
| OSVVM | [CoveragePkg 源码](https://github.com/OSVVM/OSVVM/blob/main/CoveragePkg.vhd)：Count、AtLeast、Weight，COUNT_FIRST/COUNT_ALL 等显式模式 | 不同框架可以有不同计数策略；应把多命中、阈值和采样规则作为公开契约 |
| coverage.py | [measurement contexts](https://coverage.readthedocs.io/en/latest/contexts.html)：可关联“哪个测试执行了哪些行” | test/run → bin 的证据关联有实际价值，且可以由环境自动记录，无需给 case 声明功能标签 |

这些是实现参考，不是标准符合性的证明。尤其不可把第三方文档中“和 SV 一样”的概括
直接当作所有分桶、排除和采样细节的规范。

**已经合理的部分**

以下判断来自当前源码及已有测试，不是仅凭 API 名称得出。

| 能力 | 当前行为 | 评价 |
| --- | --- | --- |
| 定义与实例分离 | CoverGroupDef/CoverPointDef/CrossDef 保存定义，CoverGroup 保存计数；JSON 带 schema digest | 合适，能够阻止相同实例名下不同定义被静默相加 |
| bin 达标 | `count >= at_least` 才计为已覆盖，达到阈值前不按比例给部分分 | 合适；可明确表达重复命中要求 |
| 特殊 bin | default 不计入分母、不参与自动 cross；illegal 优先，原子提交后报告异常 | 基本合适；被完全排除的普通 bin 另有问题，见下文 |
| 同样本 cross | 使用本次 point 命中的 bin 集做笛卡尔积；重叠普通 bins 可多命中 | 合适；不是对不同运行各自命中的单维集合重新做笛卡尔积 |
| 采样边界 | 支持事务 `sample()` 与稳定相位绑定；Execution 拥有采样器，绑定组禁止手动混采 | 合适，有助于保持观测单位一致 |
| 转移与运行隔离 | 相邻 sample 转移、显式 overlap、gate/X/Z 打断历史；运行结束清历史 | 规则清楚；是 xreactor 自己的契约，不能自动视为全部 SV transition 语义 |
| 合并 | 同一实例的兼容统计整数相加，再由计数重算覆盖率；不合并未完成转移状态 | 合适；保留同一次运行内实际观察到的完整模式 |
| 后端一致性 | native 快照同步不重复计数；报告保留实际后端及 fallback；采集不完整阻止验收 | 合适；此次也运行了已有 memory/native 对照用例 |
| 指标区分 | 统一报告分别保存 functional 与 line coverage，没有把两者平均成总分 | 合适，避免不同测量空间相互掩盖缺口 |

主要实现见 [coverage.py](../../src/xreactor/coverage.py)、
[_coverage_runtime.py](../../src/xreactor/_coverage_runtime.py) 和
[coverage_report.py](../../src/xreactor/coverage_report.py)。

**已复现的计数问题：应先修正**

1. **P1：ignore/illegal 完全遮蔽的普通 bin 仍进入分母。**

   `CoverPointDef._normal_bins` 仅按 BinKind 分类；`point_coverage()` 使用其长度作分母，
   `_resolve_cross()` 也从这一集合构造 cross。采样时 `_plan_point()` 会先处理
   illegal/ignore，因而被完全遮蔽的普通 bin 永远无法命中。

   探针定义普通 bins `zero={0}`、`one={1}`，再定义 `ignore={1}`。合法空间中的 0
   已出现，当前 point 和 cross 仍都是 50%，并把 `one` 留在 `uncovered()`。
   换成 illegal 同样如此，非法命中应另行决定测试失败。

   IEEE 1800-2017 §19.5.5/§19.5.6 的排除规则要求去掉普通 bin 中被排除的值；
   排除后空 bin 不参与覆盖计算。[原始条文](https://fpga.mit.edu/6205/_static/F25/documentation/1800-2017.pdf)。
   PSS 3.0 §18.3.5/§18.3.6 也明确了同一规则。
   [PSS 正文](https://www.accellera.org/images/downloads/standards/pss/Portable_Test_Stimulus_Standard_v3.0.pdf)。

   建议在 schema finalize 时解析 effective normal bins，计算分母和 cross 时剔除空 bin，
   保留 excluded reason。部分排除不能把整个 bin 删除：例如 `{0,1}` 排除 1 后仍须由 0
   命中。transition、mask 等不能可靠静态解析的情形，应明确限制或拒绝含糊定义；
   不能静默留下必然不可达的覆盖目标。

2. **P1：cross 的显示字符串同时承担 ID，存在计数器碰撞。**

   `_tuple_key()` 使用 `" × ".join(tuple)`。名称校验允许任意非空字符串，因此
   `("a", "b × c")` 与 `("a × b", "c")` 都得到 `a × b × c`。
   两个 point 各两个 bins，应该有四个计数器，实际只有三个。
   命中第一个 tuple 后 `cross_coverage()` 对两个 tuple 读取同一计数，返回 **50%**；
   正确值为 **25%**。

   建议内部使用 tuple 或独立稳定 ID；JSON 使用结构化维度列表，显示文本只用于展示。
   不要靠限制 Unicode 名称来弥补 ID 设计；名称本来就可能来自项目描述或生成器。

**达标与合并契约：需要明确或补齐**

3. **P1：point/cross 的 goal 当前只是报告信息。**

   `covered` 和 `assert_coverage()` 检查组的加权分数与 group goal；
   point/cross 的 goal 不参与这一验收判断。
   探针中 a=100%、b=0%、cross=0%，三个权重相同，group goal=30%，当前组达标，
   `assert_coverage()` 通过，尽管 b 与 cross 各自声明 goal=100%。

   这并不能单凭结果认定违反 SV：组目标和子项目目标如何形成项目验收策略，应由
   xreactor 公开定义。问题是当前设计文档称 goal 决定 pass threshold，API 又允许逐项
   设置 goal，实际仅组目标生效，用户容易把它理解为逐项约束。

   建议保留当前 raw coverage 百分比，额外输出逐项 `goal_met`；增加显式的逐项验收
   策略，或清楚规定 `assert_coverage()` 仅检查 group。不要未经验证便引入“按 goal
   归一化成百分比”的公式，使历史数值发生隐式变化。

4. **P1：coverage 达标状态和检查通过状态需要区分。**

   `illegal_policy="record"` 时，普通空间达到 100% 后再出现非法值，报告的
   `covered` 仍为 true；但 `assert_coverage()` 抛 IllegalBinError。这一行为可以合理
   表示“覆盖目标已达成，同时检测到错误”，却不适合作为单一回归通过标志。

   建议报告分别给出覆盖目标、采集完整性和非法命中状态，验收结果明确结合三者。
   不能把有错误的运行直接标成验证通过，也无需抹掉它已经实际观察到的 coverage。

5. **P1（用于自动回归验收前）：缺少数据库级运行身份与去重。**

   `merge()` 校验定义和 sampling contract，但没有 run_id、DUT/配置基线及输入快照
   身份。探针对 `at_least=2` 的 bin 只实际采样一次，重复导入同一报告后从 0% 变成
   100%。这是已在[跨用例指南](../../docs/guides/functional-points.md)公开的边界，
   不是未披露的“违反 UCIS 自动去重要求”；UCIS 并不能替调用方决定回归集合。

   建议在回归层增加 run_id、snapshot_id、独立运行/累计快照声明，以及 RTL build、
   配置、环境和 coverage 语义版本。拒绝重复 snapshot 和同一累计链的重叠导入。
   手动采样目前均为 `sampling_contract=None`，schema 相同但采样位置不同的事务统计
   也能合并，宜由环境提供稳定的 transaction contract。

6. **P2：普通命中缺少 test/run → bin 证据索引。**

   `sample(metadata=...)` 只把 metadata 保存到 illegal hit。正常命中传入
   `test="case-a"`、seed、tick 后，JSON 中找不到该测试名。
   项目运行配方的独立运行产物仍可定位证据，这不等于系统完全没有 provenance；
   但合并后的 CoverageDatabase 单独不能回答哪个 case/seed 覆盖了某个 bin。

   建议先在环境/数据库层记录稀疏 run → hit-bin 关联，再按需保存 first/last hit，
   避免在采样热路径保存全量事务。测试归属可自动采集，无需功能标签。

**可以保留但应声明的差异**

- `goal` 不改变 raw percentage 是现有明确设计选择；无需只为类似 SV 就改统计口径。
  `CoverageDatabase.coverage` 是实例均值，而 `type_reports()` 是按兼容定义累加计数；
  二者回答不同问题。不要把实例平均和按类型合并展示成可互换的验收指标。
- xreactor 要求显式 bins、支持 bool/int/str/None，并按 Python 整数匹配；它不实现完整
  SV 的自动 bins、定宽类型转换、四态 wildcard 和所有 transition 运算符。这可以是
  合理的框架范围，但 exporter 不能暗中宣称这些行为全等。
- `Bin.array(0..7, count=3)` 的实现把余数优先分到前面的 bin，得到 0..2、3..5、6..7。
  PSS 3.0 §18.3.4 的自动分桶例子将剩余项放在最后一个 bin，得到 0..1、2..3、4..7。
  两者并非同一个 API；需要记录分桶规则，不能根据 count 相同推断模型相同。
  [PSS 正文](https://www.accellera.org/images/downloads/standards/pss/Portable_Test_Stimulus_Standard_v3.0.pdf)。
- gate=false 清空 transition 历史是清楚的 xreactor 契约。历史上的 SV 委员会曾讨论
  “跳过 sample”与“终止转移”的歧义，因此不能把这一点标成已经证明完全相同，或
  没核对新版条文便认定 xreactor 错误。
  [Accellera 委员会讨论](https://accellera.org/images/eda/sv-ec/8493.html)。
- 当前 Sequence/FSM、完成事件采样适合简单时序场景；若要表达“发出的请求地址等于
  若干拍后完成的响应地址”，还需要 capture/key 或项目事务观察器。PSS 的 action
  handles 和属性约束可作为设计参考，不必为了语法兼容把整个 PSS 引进核心。
  [PSS 3.0 §19.4](https://www.accellera.org/images/downloads/standards/pss/Portable_Test_Stimulus_Standard_v3.0.pdf)。

**UCIS 互操作建议**

保留内部 JSON 和采样实现，在持久化边界增加版本化 adapter。候选映射如下：

| xreactor 数据 | UCIS 目标 |
| --- | --- |
| CoverGroupDef / 实例 | COVERGROUP / COVERINSTANCE |
| CoverPointDef / CrossDef | COVERPOINT / CROSS |
| 普通、ignore、illegal、default bins | 对应 coveritem 类型与独立稳定 ID |
| count、at_least、weight | 原始计数、命中阈值和权重 |
| run 与 bin 关联 | history node 与 test association |
| sampling contract、schema digest、后端诊断 | 带命名空间的 user attributes |

注意 C API 的 `ucisCoverDataT.goal` 表示 bin 命中阈值，不能直接填 xreactor 的百分比
goal；scope 百分比目标是另一个属性。类型、实例、bin 与历史的详细接口见
[UCIS 1.0 §8.3、§8.5、§8.17、§9.8 及示例章 §10](https://www.accellera.org/images/downloads/standards/ucis/UCIS_Version_1.0_Final_June-2012.pdf)。

字符串/None 分类、mask、逐 bin 不同阈值和自定义时序契约应先列入 exporter 支持矩阵。
只导出 counts 的 interchange 能帮助报告交换，但不代表外部工具可以重新采样同一模型。
无法无损表示的属性保存在扩展中，并明确报告限制。

实施验收应包含 XML schema 校验，以及独立读取器回读，逐 bin 对照 count、类型、阈值、
cross 维度、实例和运行关联。PyUCIS 可作为候选读取器，目标 EDA 工具还需单独验证。
本次未安装 PyUCIS，也未验证任何商业工具读取结果。

软件格式建议仍走独立通道。当前 `parse_lcov()` 只读取 SF/DA/LF/LH，丢弃 branch、
function 等记录，准确名称是 **LCOV line coverage 子集**。LCOV 本身能容纳更多记录；
未来扩展 branch 时需显式增加模型字段，不能把未知指标当成 0%。
[LCOV 格式说明](https://raw.githubusercontent.com/linux-test-project/lcov/master/docs/man/geninfo.rst)。
LLVM 将 region、branch 和 decision 等覆盖结构分别建模，也支持独立 MC/DC 视图；
functional cross 命中不能替代这些结构覆盖证明。
[LLVM mapping](https://llvm.org/docs/CoverageMappingFormat.html)、
[Clang coverage](https://clang.llvm.org/docs/SourceBasedCodeCoverage.html)。

**验证证据与后续顺序**

修复前基线运行：

```bash
PYTHONPATH=src python3 -m pytest tests/coverage -q
# 34 passed

XCOMM_PYTHON=/tmp/xreactor-coverage-native-build/python PYTHONPATH=src \
  python3 -m pytest tests/integration/test_compiled_patterns.py -q --require-xspcomm
# 67 passed，包含 memory/native 对照和现有编译模式测试

PYTHONPATH=src python3 design/verification/coverage_standards_probe.py
```

已有测试共 **101 passed**，说明已有契约与回归用例通过，不代表标准符合性已完成。
最小探针见 [coverage_standards_probe.py](coverage_standards_probe.py)，
实际输出见 JSON（本地产物：`coverage-standards-probe-results-2026-09-30.json`）。
本次对问题的实际复现使用手动 Python 采样；native 定向回归验证的是已有后端契约，
不是逐项用 SV 仿真器做差分认证。

原评审建议按以下顺序推进；前三项及自动展开前的容量检查现已落实：

1. 修正 effective bins 与 cross ID，添加真正验证分母和 tuple 身份的回归；确保
   部分排除、多重排除、ignore/illegal overlap 及 Python/native 两条路径一致。
2. 明确逐项 goal、group goal、非法命中和采集完整性的验收关系，保持 raw coverage
   数值含义稳定，并让报告与检查 API 使用相同的公开状态。
3. 在回归层补齐运行身份、去重及稀疏证据索引；为手动事务采样提供语义契约。
4. 再增加 UCIS exporter，以标准 XSD 和独立回读作为验收；保留内部 JSON。
5. 按项目实际需要扩展行为关联与代码覆盖指标，避免为了覆盖完整标准而扩大核心。

原评审另有两项 P2 工程问题：`_resolve_cross()` 在检查 `max_auto_bins` 前就构造完整
笛卡尔积，显式 include 也先展开全集；这一项已一起修复。digest 仍包括 description，
纯文字修改也阻止合并，区分语义身份和文档身份仍可后续排期。

项目级可信度还依赖验证计划是否落实。现有[功能点指南](../../docs/guides/functional-points.md)
已明确把缺少采样器的 RTL 要求标成未测量；这一点应保留。框架能正确统计已定义 bins，
并不意味着这些 bins 已覆盖全部设计要求，或命中的行为已通过正确性检查。
