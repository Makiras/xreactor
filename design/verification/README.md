# 调研与验证记录

本目录保存设计评审、代码审计、实施检查和研究结果，按主题提供阅读入口。各文档中的状态和测试数字对应记录时点；判断当前可用能力请查阅[当前实现说明](../current-implementation.md)，安排后续工作请查阅[路线图](../delivery/roadmap.md)。

这些记录保留设计选择的依据。已经撤销的方案和早期缺口仍可出现在历史分析中，不能据此判断当前框架还需要实现同一功能。运行报告和测量数据按仓库约定保留为本地产物。

## 框架评审与文档检查

- [框架评审](framework-review-2026-09.md)与[易用性评审](usability-review-2026-09.md)：检查框架能力和用户编程成本。
- [验证流程审计](verification-flow-progress-2026-09.md)、[缺口修复记录](verification-flow-fixes-2026-09.md)、[实施记录](../delivery/verification-flow-next.md)：从早期问题追踪到后续交付。
- [功能文档与回归检查](feature-docs-regression-2026-09.md)、[递进入门教程检查](beginner-quickstart-2026-09.md)：文档、示例和测试之间的对应关系。

## Driver 与 Agent

- [Driver 提交入口](driver-submission-2026-09.md)、[Driver 交接](driver-handoff-2026-09.md)、[协议 Driver 范围](protocol-driver-scope-2026-09.md)：提交方式、任务交接和公开类型的收敛。
- [Agent 与参考模型接入](agent-reference-model-2026-09.md)：组件组合、响应检查、模型所有权与生命周期。
- [asyncio 观察器检查](asyncio-observer-2026-09.md)：调度观察方案的实现、回归和测量。

## 功能覆盖

- [覆盖标准评审](coverage-standards-review-2026-09.md)：行业语义与框架设计的比较。
- [移除测试标签后的覆盖模型](coverage-without-test-tags-2026-09.md)：用实际场景命中组织跨用例覆盖。
- [native 覆盖采集验证](native-coverage-2026-09.md)：原生计数、宽信号、诊断和有界并发的交付证据。
- [有状态覆盖实施计划](../delivery/stateful-coverage-plan-2026-09.md)：已交付范围及剩余扩展。

## 真实 DUT 验证

- [RTL 功能验证计划](rtl-feature-plan-2026-09.md)：e203 与 Cache 的验证组织方式。
- [e203 功能点整理](e203-functional-points-2026-09.md)、[Cache 功能点整理](cache-functional-points-2026-09.md)：设计要求、激活条件和观察位置的分析。
- 实际构建和运行请查阅 [e203 示例](../../examples/integration/e203/README.md)与 [Cache 示例](../../examples/integration/cache/README.md)；项目内的验证计划和检查代码记录具体义务。

## 随机化与搜索

- [持续随机化调研](continuous-randomization-research-2026-09.md)：运行中生成合法事务，结合状态、检查器和覆盖反馈发现问题。
- [Hypothesis 扩展调研](hypothesis-stateful-randomization-research-2026-10.md)：在线生成、动作历史搜索、失败简化与相关库的实测边界。

SystemRDL 的后续方案已整理为[寄存器模型设计](../architecture/systemrdl-register-model.md)和[支持计划](../delivery/systemrdl-support.md)，分别说明架构取舍与实施 TODO。
