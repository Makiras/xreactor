# 移除人工测试标签完成率（2026-09-29）

用户确认功能点应横跨 case，以实际命中并集评估覆盖；人工将 pytest 结果登记为功能点
PASS/NOT_RUN 对当前流程没有必要。本次移除这层机制，保留运行时覆盖与原生测试结果。

## 实现变化

- 删除 `feature_report.py`、`pytest_plugin.py`，移除 pytest entry point、marker、
  plan/report 命令行及 ini 配置，以及六个相关公开导出。不保留兼容空实现。
- 覆盖报告移除 `features` 数据字段、`feature_path` 参数、`--features` 输入和完成率页面；
  单页与多页 HTML 继续展示 functional bins 和 LCOV，各自保留度量意义。
- e203/Cache 测试不再加载计划或添加 marker。原数据、时序、故障与资源清理断言保留，
  参数化实例继续由 pytest 执行。e203 脚本直接返回 pytest 的退出状态，主 campaign
  自行生成已有的 functional/LCOV 报告，不再会话结束后追加标签报告。
- 两份 `verification_plan.json` 改用 `scope` 与 `requirements`，保留全部设计要求、
  RTL 基线、观察点及场景，不作为测试状态汇总输入。内部 49/77 项要求仍未测量，
  本次不假称新增了这些内部采样器。
- 删除两份专门验证标签聚合的测试文件；历史探针只保留组件生命周期检查。旧评审与
  JSON 测量保留历史结果，文档明确其标签统计已经失效。

普通用例不需要声明“自己覆盖哪些功能”。环境中的采样器记录实际事件，检查器验证行为，
每次运行保存覆盖文件和运行元数据。汇总时显式选择同一 RTL/配置的兼容覆盖文件合并。
CoverageDatabase 校验 schema，尚不自动校验 RTL 身份或去重重复文件。

## 跨 case 的可运行证据

`examples/transactions/test_pipeline_coverage.py` 的两个 case 共用 `pipeline.output`
模型，分别观测 tag 1/2 和 2/3，各自覆盖 2/3。组合回归在 MemoryBackend 和 native XClock
上验证：合并后覆盖 3/3，计数为 `{1: 1, 2: 2, 3: 1}`，重复命中不增加 bin 数量。
原有检查失败、取消、启动/关闭失败和导出失败的回归仍保留，验证已观察的数据和原异常
不会因报告变化而丢失。

报告命令回归用两份部分覆盖文件生成单页及多页 HTML，确认实际计数合并、达到 100%，
并且导航和输出目录中没有标签完成率页面。空输入明确报错，schema 不兼容的原有回归保留。
这次没有修改覆盖引擎的采样或合并算法，也没有新增运行管理抽象。

## 验证

Python 环境：`/tmp/xreactor-verification-venv`；本机生成 DUT 复用
`/tmp/xreactor-dut-current/e203-dut` 与 `/tmp/xreactor-dut-current/CacheSignalCFG`。
重新安装 editable 包并刷新本工作区的生成包元数据，确认 pytest 不再自动加载已移除插件。

| 检查 | 结果 |
| --- | --- |
| coverage、组合配方和两个示例 case | 44 passed |
| `python3 -m pytest -q --require-xspcomm` | 467 passed |
| e203 实际 `run_pytest.sh -q`，random_count=0 | 23 passed |
| Cache 实际 `test_cache_coherence.py` | 8 passed |
| `mkdocs build --strict`、`git diff --check` | 通过 |

e203 产物：`/tmp/xreactor-dut-current/e203-without-test-tags`；Cache 各 case 产物：
`/tmp/xreactor-cache-without-test-tags`。真实 DUT 入口没有加载功能点计划，也未产生标签报告。

用户指南：[功能点与跨用例覆盖](../../docs/guides/functional-points.md)、
[运行产物](../../docs/guides/verification-flow.md)。
