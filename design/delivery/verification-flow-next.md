# 验证流程实施记录

本页保留 2026-09-29 验证流程改进的目标、交付范围和验收要求。Monitor 终止与错误传播、SamplingMonitor、Agent 接入，以及覆盖产物和运行配方均已交付；曾实施的 pytest 功能标签聚合后来撤销。

当前使用方式见[Agent 与参考模型指南](../../docs/guides/agents-and-reference-models.md)和[验证流程指南](../../docs/guides/verification-flow.md)。资源领域接口仍在讨论，其他后续工作统一记录在[路线图](roadmap.md)中。

## 目标与范围

优先保证“组件停止时等待者能结束、测试提前结束时报告不会假通过”，然后降低
Driver/Monitor/Scoreboard/覆盖率在项目中的组合成本。保持 asyncio 为唯一调度器。

实施沿用 Driver 的 send/submit 语义、六个公共类和具体时序。协议 Driver 派生自
Sync/Async 模板，Agent 组合现有组件并由 Execution 管理。资源锁没有新增公共类；
parallel、VerificationScope、ObservationStream、回放和回归管理设施不属于这次交付。

## Monitor 终止与失败传播

该项已实施。改动范围以 components.py、monitors.py 及私有交付状态为主，正式回归覆盖以下行为：

1. 多个 recv 等待者在关闭时全部获得确定结果，不残留等待任务。
2. capture/decoder/交付失败能到达 recv 和生命周期边界。
3. lossless 溢出后接收者不挂起；latest 仍只覆盖旧样本，不掩盖真正错误。
4. 异常退出和外部取消继续释放订阅、候选 rising watcher、队列及任务。

已确认并实施的终止契约：

- aclose 表示终止，不表示排空；正常采样结果通过关闭前的 recv/上层 finish 消费。
- 正常终止使用明确的关闭结果或异常，不能伪装成一条成功 Transfer。
- 失败优先传播原始异常；同一失败到达 context 时避免重复报告，并保留独立清理异常。
- 关闭后同实例不再 start；多批次使用同一次启动。关闭清空未读缓冲。
- 严格残余检查继续由 Scoreboard.finish 负责，不能用关闭代替。

正常关闭的公共异常为 MonitorClosedError；异步迭代正常结束，失败保留原始异常。
不得通过取消宿主全部任务来解决 recv 挂起，也不让调用者靠 asyncio.TaskGroup 回收等待。

验收：现有 memory/native 采样、连续 beat、快照一致性和 Scoreboard 绑定测试保持
通过；新回归证明关闭、失败和取消均有界完成。不会重复启动或关闭绑定 Monitor。

## 已撤销的 pytest 标签聚合

这项工作曾用于将测试结果登记到人工功能标签。后续确认功能覆盖应由各次运行的实际
场景命中合并，因此插件、状态 API 和完成率报告已移除。pytest 原生收集、参数化、
skip/xfail 和退出码保持使用；回归计划不再要求绑定测试标签。
当前契约见[跨用例功能覆盖指南](../../docs/guides/functional-points.md)。

## Monitor 模板与 Agent 组合

SamplingMonitor 已提供通用采样、同步 capture、不可变记录与接收队列，减少项目中
手写 asyncio.Queue 的需要。具体协议仍定义有效事件和接受时刻，通用层不推断
ready/valid、flush、reset 或延迟。

组合示例验证 Driver、Monitor、Scoreboard、参考模型和覆盖率的配合后，Agent 已成为
公共接口实例。环境创建 Agent 并连接独立模型，Execution 统一启停组件。

实现和回归需要满足以下组合要求：

- active 与 passive 是否都需要，组件是构造传入还是内部创建；
- 每个组件由谁启动、谁关闭，启动到一半失败如何反向清理；
- Scoreboard 已独占绑定 Monitor 时，组合层如何避免第二个 recv 消费者；
- finish 的周期预算与观察窗口由测试明确传入，不能从退出动作隐式推断；
- 失败如何保留原始原因、清理错误和组件身份。

验收：普通测试只发送请求、等待事件/结果、结束检查；不需要导入 asyncio 来启动
组件任务。组合示例覆盖正常、检查失败、启动失败和外部取消，不影响宿主外部任务。

Driver 资源适配单独依据[资源讨论稿](../architecture/driver-resources.md)讨论，优先
考虑声明与占用诊断；不把资源锁自动等同于流水级，也不把同名锁变成全局资源。

## 覆盖率采样与 pytest 产物

该项通过项目示例和回归交付，复用现有组件组合。完整用例验证以下要求：

- 同一份不可变观测能够用于检查和覆盖率，按约定恰好采样一次，不争抢 recv。
- 采样点显式选择输入接受、DUT 观察或核对完成；测试失败不必然表示先前覆盖率无效。
- 每个 test item 有隔离的产物目录，保存明确的 nodeid、seed 与运行参数。
- 正常、断言失败和 teardown 失败后都保留可用覆盖率；导出错误与原异常分别保留。
- pytest 执行结果、functional bins 和 simulator line coverage 分别保留。

交付使用 fixture、现有 CoverageDatabase 和报告函数；DUT-specific LCOV 导出由
项目工具负责，没有增加通用 pytest 产物插件。

验收：成功和故意失败的用例都能生成并读取 JSON/HTML；兼容 schema 可合并，
不兼容 schema 明确报错；无需新增观察广播或通用事件总线。

## 仿真运行配方与运行边界

该项通过项目示例和回归交付，沿用 Execution/Backend 与 fixture：

1. DUT/Backend 构造和销毁归创建者，组件在 Execution 内关闭。
2. 仿真周期预算、墙钟运行限制和阶段收敛预算分别明确。
3. 记录 seed、Backend/仿真器配置、开始/结束状态和产物路径。
4. 初始化失败、Backend 失败、测试取消时仍结束组件和保存诊断。

验收：相邻测试之间没有遗留 watcher、信号 ownership 或组件任务，宿主任务不受
影响。真实 DUT 复用时由项目显式初始化，不由框架推断 reset。

暂不新建 SimulationManager 或独立运行 scope。多时钟共同时间轴、第三方 loop、
长时间压力、seed 矩阵与回归调度按实际需求另立范围。

## 验收与检查

各项交付包含代码、正反例、用户文档和评审记录。pytest 标签聚合的撤销不改变
pytest 原生执行结果；功能覆盖继续依赖实际观察到的 bin 命中。

必要检查：

```bash
python3 -m pytest -q --require-xspcomm
mkdocs build --strict
```

新增用例优先使用协议无关替身和 native XClock，现有具体协议用例用于防回归。
真实 RTL 与性能测量单独记录，不能从无 RTL 的调度测试推导硬件吞吐。
