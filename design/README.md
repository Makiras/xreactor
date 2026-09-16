# XReactor 内部设计与验证记录

本目录保存 XReactor 的实现设计、历史决策、验证记录和交付记录，主要面向维护者。使用框架时请从[用户文档](../docs/index.md)开始。

Toffee 只作为需求和方法学参考；新框架不承担 Toffee API 兼容。Picker 继续生成 DUT 和稳定接入协议，xcomm 提供高性能 backend，新框架负责 Python API、生命周期和 asyncio 集成。

## 一句话模型

```text
XTrigger：等待规格
    -> XReactor：注册、组合、分发
    -> XTriggerEngine：C++ phase 求值
    -> XBackendHit：底层命中记录
    -> XEvent：交付给 await/@on 的结果

SimulationPump：控制 RunUntil、half-step 和 asyncio yield
```

## 阅读顺序

1. [当前实现说明（代码审计版）](current-implementation.md)
2. [已冻结的设计决策](decisions.md)
3. [总体架构](architecture/overview.md)
4. [调度、sampling phase 与 half-step](architecture/scheduling-and-phase.md)
5. [XTrigger、XEvent 与 XReactor](concepts/trigger-event-reactor.md)
6. [用户 API 草案](concepts/public-api.md)
7. [位宽、有符号与四态语义](concepts/value-semantics.md)
8. [编译式 Trigger](features/compiled-triggers.md)
9. [FSM 与 Sequence](features/fsm-and-sequence.md)
10. [@on 与持久订阅](features/subscriptions.md)
11. [xcomm 现状核对](backend/xcomm-audit.md)
12. [C++ XTriggerEngine](backend/trigger-engine.md)
13. [XData、native identity 与时钟源边界](backend/xpin-xdata-boundary.md)
14. [XData、Bundle 与 Interface 设计](architecture/data-bundle-interface.md)
15. [Ready/Valid 驱动](features/ready-valid.md)
16. [Functional coverage 设计](features/functional-coverage.md)
17. [Functional coverage 性能与统一报告](features/coverage-performance-and-reporting.md)
18. [asyncio、pytest、HTTP 与线程](integration/asyncio.md)
19. [实施 Roadmap](delivery/roadmap.md)
20. [测试与性能门槛](delivery/testing.md)
21. [Cache 功能验证报告](verification/cache-functional.md)
22. [e203 IFU-to-ICB 验证报告](verification/e203-functional.md)

## 核心 MVP

M0～M3 构成核心 MVP：

- 冻结对象、phase、位宽和生命周期契约；
- 提供 C++ half-step、XTriggerEngine、BackendHit/RunResult；
- 跑通 `await RisingEdge/FallingEdge`；
- 跑通编译到 C++ 的 Expr/FSM Trigger。

M4 再加入 `@on`、组合触发器和外部 asyncio adapter。XClock stable contract 已经是
完整公共时序边界，不规划 cocotb event-region API；多时钟按真实用例扩展，项目专用
方法学由 agent 基于基础抽象生成。

## 文档状态

- [当前实现说明](current-implementation.md)：以代码为事实来源，记录当前可用
  API、已验证语义和未实现边界；判断当前能力时优先阅读。
- 本目录：正式、模块化设计，后续修改应优先落在这里。
- [原始综合分析](history/asyncio-simulation-kernel.zh.md)：保留源码核对过程、历史讨论和完整背景。
- [用户文档](../docs/index.md)：安装、入门、使用指南和 API 参考。
- [XReactor 项目入口](../README.md)：代码、测试、样例和开发约定。
