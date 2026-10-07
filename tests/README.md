# 按功能维护回归

运行完整框架回归及用户 quick start：

```bash
python3 -m pytest -q --require-xspcomm
mkdocs build --strict
```

`--require-xspcomm` 保证 native 依赖缺失时失败，而不是跳过全部原生验证。普通 pytest
允许没有 native 的环境运行 MemoryBackend 部分。版本、导入路径与命令见安装指南。多页源码报告集成测试需要 genhtml，CI 安装 lcov，
本地未安装时仅跳过这组工具测试。

## 功能分组

| 目录 / 入口 | 覆盖内容 |
| --- | --- |
| runtime/test_runtime、test_subscriptions | 时钟/值/模式、组合等待、订阅、取消与运行作用域 |
| runtime/test_scoreboard、test_transfers | 直接比较、关联、预算、残余、状态与失败观察 |
| interfaces/test_*driver、test_signal_driver | 驱动模板、接受/并发、信号所有权和单周期时序 |
| interfaces/test_sampling_monitor、test_monitor_lifecycle | 快照、采样 phase、共享关闭和交付契约；特殊协议候选逻辑单独保留 |
| interfaces/test_agent | 注册、部分启动、反向清理、异常与宿主隔离 |
| interfaces/test_data_interfaces、test_protocols | 显式绑定、结构化数据及可选协议工具 |
| integration/test_xcomm_backend | native half-step、wide/XZ、packed、IR 与订阅 |
| integration/test_asyncio_*、test_driver_handoffs、test_http_integration | 阶段收敛、锁交接、外部 I/O 与任务边界 |
| integration/test_*examples、test_agent_native、test_transaction_lifecycle_native | 复用文档 Driver/DUT 替身，在两种后端核对接受/响应 tick、失败与清理 |
| integration/test_quickstart_tutorial | 主线各段与文档同步、故障练习退出码；native 示例由 CI 单独运行 |
| integration/test_verification_flow | 覆盖采样、失败产物、预算与完整退出路径 |
| coverage/ | bins、gates、cross、schema/merge、HTML/LCOV、跨 case 合并与报告命令 |
| examples/getting_started、examples/transactions/test_pipeline_coverage.py | 用户完整示例，也在默认 testpaths 中执行 |

[功能与回归索引](../docs/reference/feature-map.md)连接每类功能的用户指南、场景和回归。
递进示例、故障练习和 native 选读见[入门代码](../examples/getting_started/README.md)。
运行报告与覆盖数据保存在本地产物目录，不纳入 Git。

## 按未覆盖行补充用例

行覆盖收敛以完整框架回归为基础，包括 MemoryBackend 和 native XClock；这组命令
测量的是 `src/xreactor` 的 Python 代码，不包含 e203、Cache 等 DUT 的 RTL 行覆盖率。

```bash
python3 -m pytest -q --require-xspcomm \
  --cov=xreactor --cov-branch \
  --cov-report=json:output/python-coverage/coverage.json \
  --cov-report=html:output/python-coverage/html
```

打开 `output/python-coverage/html/index.html`，从未执行的行定位遗漏行为。新增用例应
验证正常结果、边界错误、失败后的资源释放或报告内容，再运行完整回归。开启分支覆盖时，
pytest 的综合百分比不能当作行覆盖率；行覆盖率应按 JSON 的
`totals.covered_lines / totals.num_statements` 计算，分支覆盖率单独计算。

2026-10-02 在 Python 3.12 和 native 覆盖 ABI v3 上的实测如下。数字是当次运行记录，
后续改动应重新生成报告。

| 指标 | 补充前 | 本轮补充后 |
| --- | --- | --- |
| 通过的用例 | 560 | 873 |
| Python 行覆盖率 | 5462 / 6021，90.72% | 6002 / 6024，99.63% |
| Python 分支覆盖率 | 1745 / 2208，79.03% | 2144 / 2210，97.01% |
| 未覆盖行 | 559 | 22 |

本轮新增 313 个参数展开后的用例，覆盖数据定义、signal-tree 和 packed 布局、覆盖模型
与快照校验、采样绑定与 native 回退、事务比较与接受流、组件生命周期和调度故障。
同时复现并修复 `pytrigger` 拒绝异步返回值时未关闭协程的问题，两种后端都有回归。
源码多出的 3 行来自这项清理修复；原有的 44 行覆盖排除未改动。

目标仍是 100%，当前没有刷满。剩余 22 行应继续按以下原因审查，不应为了数字直接
调用私有 helper、修改排除配置或删除保护条件：

| 剩余位置 | 后续检查方向 |
| --- | --- |
| `backend.py`、`_coverage_runtime.py`、`coverage.py`、`data.py` | 检查重复防御分支的可达性；例如 native 常量和 Sequence 类型错误已被前置校验拒绝，覆盖恢复也先验证来源与计数结构 |
| `_asyncio_observer.py`、`agent.py`、`async_drivers.py`、`execution.py` | 检查重复关闭、已结束事务和撤销时钟需求的调度路径 |
| `monitors.py`、`reactor.py` | 抽象采样实现，以及订阅停止后在取消期间出现第二个异常的处理 |
| `scoreboard.py` | `finish` 内部尾部超时保护的可达性：进入循环时已要求检查点不晚于尾部终点，而尾部终点不晚于总 deadline |

这些用例已在默认 pytest 收集范围内。HTML 和 JSON 报告保存在本地，不会自动上传。

## 精简与新增规则

复用 integration/conftest 的 make_toy 和 interfaces/conftest 的双后端时钟 fixture。
通用 Monitor 的关闭/容量/取消契约用同一个参数化场景检查两类 Monitor，协议特有的
候选采样不合并。通用 Driver 的 Sync/Async 及 SingleCycle 时序不同，分别保留回归。

新增测试应证明一个可观察行为或已复现问题：检查采样信号、事件 tick、结果/异常身份、
资源释放或产物内容。不要仅断言私有 helper 被调用，不为每个配置分支复制一份测试。
有真实子系统边界才放 integration；仅使用 asyncio 不足以将单元测试归为集成。

当前测试包含纯 Python 与 native XClock 替身，不包含构建外部 RTL 的耗时环境。e203 与
cache 的构建/执行命令在 examples/integration 对应 README，不能用 native 时钟通过
宣称这些 RTL 已重新验证。

框架回归结果使用 pytest 原生 verdict。覆盖示例让两个 case 贡献同一模型的部分场景，
合并实际采样计数；不从测试标签推算功能覆盖。
