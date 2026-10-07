# 验证流程缺口逐项修复与评审

> 后续变更：人工 pytest 功能标签、对应插件和完成率报告已移除。本文相关数字和
> 插件行为仅保留为当时的审查记录，不代表当前功能覆盖。运行命令与当前使用方式见
> [移除记录](coverage-without-test-tags-2026-09.md)及各项目 README。

日期：2026-09-29。依据[修复前审计](verification-flow-progress-2026-09.md)与
[工作包](../delivery/verification-flow-next.md)。用户确认关闭后新建 Monitor 实例、
增加显式 trigger/capture 通用模板，并暂不增加 Agent 基类。

本文保留该轮的 379 项验收。用户随后确认增加接口组件 Agent，模型/Scoreboard 外置；
当前实施见[Agent 与参考模型评审](agent-reference-model-2026-09.md)。

## 逐层处置

| 层次 | 本次结果 | 保留的讨论边界 |
| --- | --- | --- |
| Driver | 保持六个类、send/submit、并发与现有时序；全量防回归通过 | 用户确认资源声明/作用域/诊断范围，已细化契约；尚未修改 resource_lock |
| Monitor | 修复终止与失败通知；新增 SamplingMonitor，共用私有生命周期 | capture 返回不可变快照由项目显式定义，不自动推断协议 |
| Agent | 项目 context/fixture 配方明确唯一所有者和反向清理 | 用户确认暂不增加公共基类；active/passive 公共配置未加入 |
| Scoreboard | 原关联实现保持；实测 Monitor 失败到 transfer 的传播 | 继续独占 Monitor，finish 使用显式预算 |
| 覆盖率 | 单消费者适配器在检查前采样，同一 Transfer 交给 Scoreboard；失败也保存 | 当前为项目配方，不是自动订阅/通用 fixture；LCOV 项目负责 |
| pytest | 已收集实例均留记录，未完成不误判 PASS；修正 XPASS/XFAIL；保护退出码 | xdist 与 rerun 聚合尚不支持 |
| 运行管理 | 配方记录 seed/nodeid/backend/预算/状态；验证启动失败、取消及反向清理 | 不新增 SimulationManager，多时钟共同时间轴另立范围 |

## Monitor 为什么这样修

原 recv 只等待 Queue.get；关闭订阅或订阅失败都不会通知这个队列。仅等待 recv 的
调用者无法前进到 context 退出，Execution pump 上已有错误也不能使它醒来。

现在接收方等待的是“有数据或已经终止”的通知，每次唤醒先检查错误和终止，再取数据。
关闭不需要往有界队列塞 sentinel，所以队列已满和多个等待者都能确定结束。
取消一个接收等待者不改变组件；关闭丢弃缓冲、唤醒所有接收者并回收候选 watcher。

Subscription 的私有 _on_stop 把终止原因交给所属组件。普通 @on 没有这个所有者，
仍向 Execution 报告失败。这样组件错误有一个负责报告的边界，不会在 recv 已处理后
又被全局 pump 重复抛出。处理器已经失败但 done callback 尚未执行的关闭竞态也检查
task.exception；取消清理中新产生的独立错误继续保留。

两个内置 Monitor 共享 _SubscriptionMonitor，未新增公开 ABC 或调度器。
SamplingMonitor 直接保存触发事件和同步 capture 的快照；ReadyValidMonitor 保留原先
DriveStable 捕获与随后 rising 接受的具体规则。协议相关候选清理留在具体类内。
Standalone Scoreboard 示例改用 SamplingMonitor 的逐周期采样，显式 sampled=True，
不再自行实现 Queue Monitor。

生命周期契约：正常 recv 关闭抛 MonitorClosedError；async for 正常结束；失败向 recv
传播原始异常，经接收观察后 aclose 不再报告同一个错误。无人等待时，aclose/context
退出报告错误。普通关闭和重复关闭均有界；不隐式排空，不替代 Scoreboard.finish。
用户应关闭自己启动的 Monitor，或使用组件 context；绑定时由 Scoreboard 负责。

## pytest 为什么这样修

聚合分母来自已收集的映射实例，而不是仅有运行报告的实例。收集时建立 NOT_RUN
占位；开始执行后缺少完整阶段报告记 INCOMPLETE。失败仍保留，不用“未完成”覆盖
已经发生的 FAIL/ERROR。setup/call/teardown 的中断均有真实 pytest 子进程回归。

pytest 的 strict XPASS 是 failed call，longrepr 以 [XPASS(strict)] 开头且没有 wasxfail；
分类依照实际报告处理。普通 XPASS 的 wasxfail 可以是空字符串，所以检查属性存在，
不能用其布尔值。setup 阶段的 XFAIL 也独立识别。

报告输出错误明确打印。原先成功的会话改为失败；已经失败或被中断的退出码保持原值。
这不会把功能点状态强行等同于 pytest verdict，也不承诺 worker/rerun 合并。

## 组合、覆盖率与运行配方

[verification_flow.py](../../examples/transactions/verification_flow.py) 在一个 context 中
拥有 DUT 替身、Execution、Driver、Scoreboard。Scoreboard 拥有 CoveredMonitor，后者
只代理源 Monitor，按接收顺序采样一次再原样转交 Transfer；没有第二个消费任务。
观察后比较失败仍计覆盖率，故障后未交付的响应不计入；这是明确的采样范围。

[pytest 示例](../../examples/transactions/test_pipeline_coverage.py) 只操作 submit/finish。
fixture 按 test item、seed、运行序号分目录；局部 Random(seed) 生成顺序。响应周期、
finish 预算/观察窗口、墙钟时限、阶段收敛预算分别控制，不混用。

配方在清理后保存 functional.json、coverage.html、run.json。保存失败与验证异常一起
报告，其他可保存产物仍尝试写出。run.json 描述该仿真 context，不代替整个 pytest
会话或其他 fixture 的最终状态。项目示例未实现通用框架产物插件或真实 DUT 初始化。

## 回归与证据

先将原有挂起与完成度误报转为红色回归，再实施修复。新增正式回归 68 项：

- Monitor 生命周期 26 项：关闭唤醒多个等待者、缓存、禁止重启、capture/decoder 错误、
  未观察错误、lossless/latest、取消、组合异常、Scoreboard 传播及 disarm 清理异常。
- SamplingMonitor 18 项：falling/rising/DriveStable 原事件、不可变快照、多批次、关闭、
  失败、容量及拒绝异步 capture。
- pytest 生命周期 11 项：-x/maxfail、三个阶段中断、参数化、collect-only、deselection、
  collection error、setup/teardown、strict/空理由 XPASS、setup XFAIL、输出失败。
- 组合配方 13 项：两种 backend 的正常/失败/启动/取消/清理路径，以及导出失败证据保留。

```text
python3 -m pytest -q --require-xspcomm
379 passed in 5.54s

python3 -m pytest -q tests/integration/test_verification_flow.py examples/transactions/test_pipeline_coverage.py
14 passed

python3 examples/transactions/scoreboard.py
checked=8, passed=8, completed=8

mkdocs build --strict
Documentation built successfully
```

环境为 Python 3.12.3 与本地 native xspcomm。新增 CI 示例入口；本地未运行 Python 3.11
矩阵，也未构建或执行真实 RTL。原 311 项防回归均包含在全量结果中。

原探针结果（本地产物：`verification-flow-probe-results-2026-09-29.json`）保留为历史证据；
修复后结果（本地产物：`verification-flow-fix-results-2026-09-29.json`）显示：关闭接收者完成、缓存归零、
重启拒绝、decoder 原异常由 recv 收到而 pump 不重复失败，failfast 完成率从 100% 降到
0%，strict XPASS 分类为 XPASS 且 pytest 仍以 1 退出。
