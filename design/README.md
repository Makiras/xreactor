# XReactor 设计与计划

本目录面向维护者，说明框架如何工作、后续准备做什么，以及设计选择的依据。学习和使用框架请从[用户文档](../docs/index.md)开始。

判断当前能力时，优先阅读[当前实现说明](current-implementation.md)和[已冻结的设计决策](decisions.md)。专题设计解释职责和契约，实施计划记录未来工作，验证记录保留特定版本的检查证据；计划中的接口和历史测试结果不能直接视为当前能力。

## 从哪里开始阅读

- 了解当前框架：先读[当前实现说明](current-implementation.md)，再读[总体架构](architecture/overview.md)。
- 修改已有行为：先查[冻结决策](decisions.md)，再阅读对应的专题设计和用户指南。
- 选择下一项工作：从[实施路线与后续计划](delivery/roadmap.md)进入，查看具体计划的范围和验收要求。
- 查找分析依据：使用[调研与验证记录索引](verification/README.md)，按主题查阅审计、回归和研究文档。

## 核心架构与运行语义

XTrigger 描述等待条件，XReactor 管理注册与事件交付，xcomm 的 XTriggerEngine 在 C++ 中求值。SimulationPump 在 Execution 内控制仿真推进，与宿主 asyncio 协同工作。

- [总体架构](architecture/overview.md)：组件职责、仓库边界与生命周期。
- [调度与采样阶段](architecture/scheduling-and-phase.md)、[asyncio 调度观察器](architecture/asyncio-observer.md)：时钟何时推进，Python 工作如何在推进前完成。
- [Trigger 与 Event](concepts/trigger-event-reactor.md)、[API 设计](concepts/public-api.md)、[数值语义](concepts/value-semantics.md)：公共对象、位宽、有符号数与四态值。
- [编译式 Trigger](features/compiled-triggers.md)、[FSM 与 Sequence](features/fsm-and-sequence.md)、[持久订阅](features/subscriptions.md)：表达式和时序匹配如何执行。
- [C++ TriggerEngine](backend/trigger-engine.md)、[信号与时钟边界](backend/xpin-xdata-boundary.md)：原生执行和数据接入的契约。
- [外部 asyncio 集成](integration/asyncio.md)：pytest、HTTP、线程和宿主任务的接入方式。

## 数据与验证组件

- [结构化数据与绑定](architecture/data-bundle-interface.md)、[ReadyValid 设计](features/ready-valid.md)：信号如何组织，通道如何驱动和采样。
- [功能覆盖设计](features/functional-coverage.md)、[覆盖性能与报告](features/coverage-performance-and-reporting.md)：覆盖定义、采样、合并与报告。
- [Driver 资源占用讨论](architecture/driver-resources.md)：资源声明与占用的候选接口，尚未形成新的公共资源类。
- [寄存器模型与 SystemRDL 接入设计](architecture/systemrdl-register-model.md)：后续寄存器支持的分层，以及构建时生成和运行时构建的取舍。

Driver、Monitor、Agent、参考模型与 Scoreboard 的当前用法见[验证组件指南](../docs/guides/agents-and-reference-models.md)；实施依据保存在[验证记录](verification/README.md)中。

## 后续工作与验收

[路线图](delivery/roadmap.md)统一组织后续工作的推进顺序。具体计划只描述各自的交付范围和验收条件，避免在多处维护不同的优先级。

- [SystemRDL 支持计划](delivery/systemrdl-support.md)：TODO，先打通生成访问包和总线 Agent 接入。
- [有状态覆盖实施计划](delivery/stateful-coverage-plan-2026-09.md)：基础采集已交付，保留 capture、事务 key 关联等后续目标。
- [测试与性能要求](delivery/testing.md)：检查范围和性能验收方法。

## 实施记录与研究

- [验证流程实施记录](delivery/verification-flow-next.md)：Monitor 终止、Agent 接入、覆盖产物和运行配方的交付范围。
- [持续随机化调研](verification/continuous-randomization-research-2026-09.md)、[Hypothesis 扩展调研](verification/hypothesis-stateful-randomization-research-2026-10.md)：状态依赖的激励、覆盖反馈、失败简化和探针结果。
- [xcomm 初期审计](backend/xcomm-audit.md)、[性能基线](delivery/baseline.md)、[原始综合分析](history/asyncio-simulation-kernel.zh.md)：早期分析与测量背景。
- [其他调研与验证记录](verification/README.md)：按框架、组件、覆盖率和真实 DUT 分类查阅。

## 文档维护约定

已有功能的职责和契约写入对应专题设计；未来工作写入实施计划并从路线图链接；测试结果和调研过程写入验证记录。新计划应在开头说明是否已经实现，并区分推荐方案与已冻结接口。历史结果保留原日期、测试范围和限制，后续结论通过链接关联。

运行报告、覆盖数据库、日志和测量数据是本地产物，由 `.gitignore` 排除。正式设计、用户文档、验证计划和检查代码保留在仓库。

Picker 负责 DUT 生成和稳定接入协议，xcomm 提供原生 backend，XReactor 负责 Python API、组件生命周期和 asyncio 集成。Toffee 作为需求和方法学参考，项目不承担其 API 兼容。
