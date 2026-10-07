# e203 IFU-to-ICB 验证报告

> 后续变更：人工 pytest 功能标签、对应插件和完成率报告已移除。本文相关数字和
> 插件行为仅保留为当时的审查记录，不代表当前功能覆盖。运行命令与当前使用方式见
> [移除记录](coverage-without-test-tags-2026-09.md)及各项目 README。

2026-10-01 更新：49 项内部要求已接入真实快照检查，增加流水交接、缓冲竞争、不同
ready、错误清除、非选中响应与三种在途复位场景；当前入口为 31 项项目测试。
逐项契约见[功能点明细](e203-functional-points-2026-09.md)，实测状态以该报告的新证据为准。
下文的日期、测试数与 NOT_RUN 是历史记录。

49 项内部属性的 133 个必需场景 bins 已实际命中，49 项符合本基线关闭条件。
默认 campaign 的 534 笔 fetch 均与独立模型比较通过。
完整运行和逐项来源见2026-10-01 证据（本地产物：`rtl-property-evidence-2026-10-01/results.json`）。

## 历史验证范围（2026-09-29）

目标 RTL 为 Picker 的 `example/e203_ifu_ift2icb/e203_ifu_ift2icb.v`。本轮使用当前
Picker/xspcomm 重新生成 memory-direct DUT；Python 3.12、Verilator 5.026，开启 coverage。
旧生成包缺少 `ClearExecutionState`，不能用于验证当前 Execution 清理契约。

[构建和运行说明](../../examples/integration/e203/README.md)与环境代码保持一致。
没有修改 RTL、通用调度器或协议驱动规则。

## 模型、采样和比较

`ByteMemory` 支持地址生成、全零、全一、交替位和 walking bit 数据；`IfuReferenceModel` 独立预测目标端口、lane 分类、
0/1/2 条命令的地址、指令拼接和两个错误的 OR。predict 不修改状态，accept 只在 DUT
输入实际接受后推进前一请求状态。输入通过 Bundle 驱动，输出在原有采样阶段取得快照。

Scoreboard 每笔比较 `{commands, instruction, error}`，CheckContext 包含请求编号和
实际接受、响应 XEvent。这样错误路由、重复/遗漏命令不会因指令值偶然相同而被忽略。
不可变 FetchTransaction 用于覆盖率和事务 JSON；coverage 不重新读取 live 引脚。

中心化 E203Harness 保留项目的 pin 时序规则，时钟推进仍由 Execution 完成。
它在最后一笔完成后继续检查 3 周期，不允许额外命令或 IFU 响应。

## 定向与随机场景

定向请求从 24 笔扩展为 34 笔，保留已有场景：

- ITCM/BIU 普通和跨 lane fetch；holding-data 下的 0/1-command 优化，nohold；
- 顺序 +2 和 +4，包括 +4 后的跨 lane、下一 lane 地址；
- 首命令背压、第二条拆分命令单独背压、响应延迟及输出背压；
- ITCM 和 BIU 上，首条、第二条、两条同时报错及无错误；
- ITCM→BIU、BIU→ITCM 的区域边界，以及 32 位地址回绕。

新增六笔连续 ITCM 输入，在 holding 复用、nohold 强制取数、拆分错误、后续复用和跳转之间
切换，实际命令数为 `[1, 0, 1, 2, 0, 1]`，只有第四笔报错，后续复用没有继承错误。
另四笔分别在 ITCM/BIU 上将两次响应延迟设为 `(0, 9)` 和 `(9, 0)`，同时施加命令和输出背压。
随机请求也独立选择第二响应延迟。未传 `second_response_delay` 时沿用首响应延迟。

四个数据模式用例分别重跑全部 34 笔定向输入。周期边界用例覆盖 ITCM/BIU 普通和跨 lane
四条路径：先测量实际延迟，reset 后用恰好相等的预算完成，再用少一周期的预算确定超时；
reset 后下一笔仍可成功。没有把某个猜测的 RTL 延迟写死为通用规则。
原漏响应用例继续以 5 周期预算触发 TimeoutError，随后 reset 并成功完成下一笔。

## 检查器与清理回归

所有测试集中在原有 `test_e203_xreactor.py`，共 23 项：主 campaign、原超时恢复各一项，
数据模式四项、周期边界四项、故障注入十项、外部取消三项。

故障注入在真实 DUT 运行时修改观察快照或命令记录，检查以下错误一定被拒绝：

- 指令值、错误位、命令地址错误以及命令遗漏；
- 响应遗漏，以及结束窗口内出现额外 IFU 响应或 ICB 命令；
- 输出受阻期间数据变化、valid 暂时撤回；
- 输入接受前出现响应。

先运行失败回归，确认旧检查器会漏掉“valid 撤回一拍后恢复”的情况：原实现只在 valid
为高时比较数据，新实现还要求受阻响应持续有效。接受前响应原本已经失败，但诊断是空的
AssertionError，现在明确报告 `IFU response arrived before request acceptance`。
这些检查只属于项目环境，没有修改通用 Driver 或时钟调度规则。

取消用例分别发生在输入接受前、等待 ICB 响应和 IFU 输出受阻时。正常/失败/取消路径均
核对没有遗留 asyncio 任务，关闭 backend 前 watcher 为零、Execution ownership 已释放，
测试环境驱动的三个 valid 均撤销。取消测试还保留一个宿主外部任务，确认它不受影响。
失败和取消不代表 DUT 内部事务完成；复用 DUT 需要显式 reset。

## 实测证据

使用 `/tmp/xreactor-dut-current/e203-dut` 中重新生成的 native DUT。
默认 seed 运行全部 23 项检查；另外三个 seed 只重复主 campaign，避免重复执行确定性的故障矩阵。
每个主 campaign 包含 34 笔定向 + 500 笔随机输入。

| seed | 完成 / Scoreboard 检查 | ICB command | half-tick | functional | pytest |
| --- | ---: | ---: | ---: | ---: | --- |
| `0xE203` | 534 / 534 | 721 | 9571 | 100% | 完整 23 passed |
| `1` | 534 / 534 | 704 | 9489 | 100% | 主 campaign 1 passed |
| `0x1234` | 534 / 534 | 739 | 9825 | 100% | 主 campaign 1 passed |
| `0xdeadbeef` | 534 / 534 | 698 | 9405 | 100% | 主 campaign 1 passed |

上轮完整运行按旧标签计为 11/11 功能点通过。第一版细化到 40 点，
当时 38 PASS、2 NOT_RUN；主 campaign 关联 16 个明确要求，其他实例各有独立 ID。
随后补充 49 个 RTL 内部义务，当前完整分母为 89，其中 38 PASS、51 NOT_RUN，见下文。
各组 15 个 coverpoint、4 个 cross 全部达标。默认组 RTL 行覆盖仍为 199/300（66.33%），
包含生成 wrapper；本轮增加了检查场景，没有提高这个行覆盖数字。
默认主 campaign 耗时约 1.40 秒（约 380 transactions/s），仅作本机记录。
`E203_RANDOM_COUNT=0` 的实际脚本入口也通过 23 项，并生成包含三种覆盖信息的多页 HTML
和 genhtml 源码页；其主 campaign 为 34 笔，其余独立用例照常运行。

完整运行命令（本机 Python 来自 `/tmp/xreactor-verification-venv`）：

```bash
E203_DUT_DIR=/tmp/xreactor-dut-current/e203-dut \
E203_ARTIFACT_DIR=/tmp/xreactor-dut-current/e203-expanded-final E203_RANDOM_COUNT=500 \
python3 -m pytest -q examples/integration/e203/test_e203_xreactor.py \
  --xreactor-feature-plan=examples/integration/e203/verification_plan.json \
  --xreactor-feature-report=/tmp/xreactor-dut-current/e203-expanded-final/features.json
```

另外三组在同一命令中设置 `E203_SEED`、独立产物目录，并将测试选择缩小为
`test_e203_xreactor.py::test_e203_reference_stress_and_coverage`。
没有为这个项目增量重跑框架全量测试。

## 功能点与产物

完整定义在 [verification_plan.json](../../examples/integration/e203/verification_plan.json)，
逐点说明条件、激励、断言、证据与范围。16 个主 campaign 要求区分普通/拆分路由、
区域切换、回绕、复用、+2/+4、nohold、错误 OR 真值表及各类背压/延迟；四种数据模式、
四种周期边界、十种观察故障和三个取消阶段分别按参数实例记录，另有超时恢复一点。
重叠输入、事务中途 reset 两点无自动化用例，保留 NOT_RUN，不能因正常场景通过而删除。

新增主 campaign 定向快照证据检查，要求对应事务确实出现，随机流量不能掩盖定向场景被删。
逐笔值仍由 Scoreboard 比较；16 点共享 pytest item，所以任何该测试失败都会使关联点失败。
第一版没有增加测试文件或仿真次数。按当时计划运行真实脚本（random_count=0）：
23 passed，38/40 完成，完成率 95%。该比例仅是较窄历史计划的结果。
详细功能点描述与 metadata 在单页 HTML 和多页站点均展示。

内部计划修订后，补充 49 个有源码位置、触发、观测、必需场景和关闭条件的点，覆盖
lane/FSM/上下文/leftover/响应 mux/命令准入/旁路缓冲/复位。所有新增点未绑定内部断言，
保持 NOT_RUN，不因现有端到端比较通过而关闭。当前真实入口仍为 23 passed，
报告为 38/89 PASS、51 NOT_RUN。具体要求与证据方法见
[RTL 功能点评审](rtl-feature-plan-2026-09.md)。

coverpoint 记录 target、alignment、sequential、holdup、command_count、命令背压、
输出背压、response、latency、seq_rv32、第二命令背压、error_pattern、route_switch，
新增 response_delay_order 和 itcm_nohold。
四个 cross 保留 target×alignment、target×response、holdup×command_count、双向背压；
不可能组合通过显式 include 排除。

campaign 保存事务、覆盖率和带 seed、数据模式的性能/状态 JSON，失败时也保存已有数据。
`commands.json` 包含未完成 fetch 已发出的命令；`performance.json` 的 `active_request`
记录 PC、请求序号、接受时刻、最后采样时刻及命令数，成功完成或显式 reset 时清空。
十项故障和三项取消回归均检查 failed 状态和原始异常，故障回归还检查覆盖及命令产物。
主 campaign 产物在 `E203_ARTIFACT_DIR`，独立用例使用各自 pytest 临时目录。
DUT Finish 前先创建输出目录，避免 coverage 数据写入不存在的目录导致 native abort。
正常、异常和取消时，先撤销环境驱动的请求/响应 valid，再关闭 backend，保留原始异常。
pytest session 结束后才把 features.json 加入报告，
避免读取尚未产生的功能点结果；只选择 timeout 测试时不合并上次 campaign 的旧产物。

## 保留的设计经验与边界

`ifu_req_last_pc` 并非整个事务期间不变的 payload：握手前是 previous pc_r，握手后
更新为已接受的 current PC。same-cross-holdup 在当拍使用旧值，第二 uop 后续使用新值。
Bundle 只提供数据组织，不从前缀推断稳定周期。此规则仍留在项目 harness 内。

这里只验证 IFU-to-ICB bridge，不覆盖 e203 的指令执行、流水线或整核软件运行。
未覆盖重叠接受多个 IFU 请求、任意非法输入、所有 reset 中断阶段、所有背压/错误/保持状态
的笛卡尔组合，也未运行第二种独立 RTL simulator。模型状态、accepted 时刻和 Scoreboard 直接比较已在
真实 DUT 上使用；通用 Agent、异步 submit、key 乱序和固定延迟则由协议无关示例覆盖，
不能强套到这个多命令接口。

早期 510 笔、9 个 point 的数据及 5.32% coverage A/B 开销属于旧流量基线。
`benchmark_coverage.py` 已改为按当前 directed_requests 的实际数量报告；本轮未重测
完整性能矩阵，不将旧性能数值称为当前结果。另以 34 笔定向、1 次 A/B 复查 benchmark
入口能运行且计数正确；该短跑只验证工具可用，不用于性能结论。
