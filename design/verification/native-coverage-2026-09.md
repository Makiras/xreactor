# Native 覆盖采集与 Execution 隔离评审（2026-09-30）

## 实现范围

本次交付实施计划的基础采集路径。复用已有 CoverGroup、Execution 和 XTriggerEngine，
没有新增公开 CoverageBinding 类、调度器或用户协程组合接口。

- `CoverGroup.bind(trigger=..., fields=..., strategy=..., accumulate=...)` 配置当前实例；
  `Execution(coverage=[group])` 负责启动和退出。
- 静态 bins、同样本 cross、相邻转移在 xcomm 计数。已有编译 Expr/Sequence/FSM 可作为
  采样源；`Next` 增加严格下一 sample 条件，原 Wait/Within/Hold 行为保留。
- 转移 bins 与普通 Sequence 共用推进实现；各注册、各组独立保存匹配历史。
- xcomm 的 `AttachCoverage` 给已有 handle 附加覆盖定义，普通命中直接累计并保持观察，
  不经 Python Rearm。描述符使用数值 ID；整组准备结果后提交计数。
- `CoverageVersion/CoverageSnapshot/ResetCoverage/Disarm` 提供版本检查、累计快照、
  历史/统计清理和注销；generation/epoch 校验可检测外部非法修改与旧 handle。
- 原生计数限定 64 位并检查溢出；非法诊断容量为 1024，耗尽会报错，不能无限增长。

新增 Python 内部模块 `_coverage_runtime.py` 集中处理编译、采样、同步和资源清理，
验证用户不需要创建或管理它。C++ 描述符是 SWIG/backend 数据接口，不承担报告、case
管理或 Python 模型职责。框架没有增加 ready/valid、reset/flush 的协议判断。

## 数据隔离与同步契约

默认每次 Execution 开始时清空统计；显式 `accumulate=True` 才保留已经完成的计数。
无论哪种模式，跨 Execution 都不会继承未完成转移、Sequence/FSM 进度及 native handle。
同一 schema 可以实例化多组，互不影响；同一实例禁止并发归属两个 Execution。

运行时 `sync()` 读取累计快照并减去上一快照，重复调用不会重复加计数。`report()`、
覆盖率查询与导出自动同步；直接读取 samples 等字段前应显式 sync。活跃统计禁止手动
sample/merge，native 同步限制在 Execution 所在线程。reset 同时重置 native epoch 与
Python 镜像；clear_history 保留完成计数。采样契约不同的报告禁止合并或继续累计。

退出顺序为：完成组件清理 → 停止推进 → 同步覆盖末次快照 → 注销覆盖 handle →
关闭 Reactor → 清理 native 程序与 context → 释放 backend。快照失败仍继续释放资源。
原验证异常与独立清理错误都保留，相同异常对象不重复报告。被动采集不独立产生时钟需求。

测试发现既有 SWIG Trigger 接口没有 C++ 异常转换：native illegal bin 会导致进程 abort。
本次在 Trigger 接口范围增加异常转换，让非法覆盖、容量错误及非法 handle 能回到 Python，
随后执行正常的失败传播和清理。原生非法 bin 同步已提交统计后转换为 IllegalBinError。

## 验证结果

使用本次构建的 `/tmp/xreactor-coverage-native-build/python`：

| 检查 | 结果 |
| --- | --- |
| `python3 -m pytest -q --require-xspcomm` | 491 passed，3.43 s |
| 最后报告调整后的 coverage/compiled-pattern 定向回归 | 59 passed |
| xcomm `test_xtrigger` | 21 cases，140 assertions passed |
| xcomm `test_xclock/test_xexpr/test_xfsm` | 通过；FSM 负例的 parse error 是预期输出 |
| e203 现有 RTL 用例 | 23 passed |
| Cache 现有 RTL 用例 | 8 passed |
| stateful 示例，Memory/native 两条路径 | 通过；累计运行也不拼接半段转移 |
| native 示例生成 HTML site | 通过 |
| `mkdocs build --strict` 与两仓库 `git diff --check` | 通过 |

新增测试放进现有 coverage 和 compiled-pattern 测试文件，没有按功能点拆新文件。
覆盖了重复快照、运行中 reset、跨执行默认隔离/显式累计、严格转移/重叠、ignore 不删除
时间、gate/abort、同样本 cross、X/Z、非法命中、被动时钟需求、启动失败、原异常保留、
外部取消、快照失败，以及后端复用后的 watcher/collector/owner 释放。宿主外部任务保持存活。

## 微基准

使用无 RTL 的真实 XClock，相同固定信号，10,000 周期、3 轮交替测量；包含 Execution
启动/关闭开销。原始数据见 JSON（本地产物：`native-coverage-measurements-2026-09-30.json`）。

| 路径 | 中位数 ns/cycle | 每轮 RunUntil 返回次数 |
| --- | ---: | ---: |
| 无覆盖 | 806 | 1 |
| Python 每拍采样 | 53,943 | 10,000 |
| native 静态覆盖 | 1,054 | 1 |
| native 静态 + 三拍转移 | 1,383 | 1 |

该基准证明 count 命中不增加逐命中返回；不能用它宣称 e203/Cache 有相同倍数的总体加速。
已有 Driver 仍需要的 Python 往返和 DriveStable 结算保持不变。

复现命令：

```bash
PYTHONPATH=/tmp/xreactor-coverage-native-build/python \
  python3 benchmarks/benchmark_coverage.py --native --iterations 10000 --repeats 3
XCOMM_PYTHON=/tmp/xreactor-coverage-native-build/python \
  python3 -m pytest -q --require-xspcomm
```

源码修改同时位于 XReactor 与 `/home/xyl/picker/dependence/xcomm`；应配套交付并重建
Python binding。旧 binding 下 `strategy="native"` 在启动时报告缺少能力，auto 路径
可回退；不能只交付 Python 改动并宣称 native 计数可用。

## 宽信号修复复核（同日后续）

此前 1～64 位限制来自 coverage adapter 的 source Expr 根与非法值标量快照，
并非 XData 或 Trigger 引擎不能观察宽数据。新增回归先复现 65 位 native group 启动
报错，再实施以下修复：

- coverage ABI 升至 v2，point 直接引用 XData；无新增 Python 公共类或采样调度机制。
- value/range/transition/Iff 复用已有宽比较；ExprEngine 增加带完整位宽常量 mask 的
  相等比较，热路径逐 native word 求值，不逐拍构造字节数组。
- illegal 值在命中时保存完整十六进制字符串，同步时恢复 Python int；普通命中仍只计数。
  后续引脚变化、重复同步、JSON 往返不丢失高位。计数器继续独立使用 uint64。
- 取值域以外的无符号常量不截断；范围与不同宽度 mask 保持 Python 整数匹配语义。
  常量折叠保留 Iff 的信号依赖，避免反向 gate 在 X/Z 时被误判为真。
- 任意位 X/Z 均跳过普通匹配、增加 unknown 并中断相邻历史。高位 abort 同样生效。
  组持有信号引用，native 引擎持有比较常量；退出清注册再清表达式，计数累计不继承历史。
- 旧 ABI 下 native 启动报错，auto 整组回退并注明原因；未增加旧 ABI 兼容层。

验证使用同一隔离构建目录。测试仍追加在现有文件：

| 检查 | 结果 |
| --- | --- |
| 宽信号与现有 coverage/compiled-pattern 定向回归 | 75 passed |
| 最终 `python3 -m pytest -q --require-xspcomm` | 507 passed，3.55 s |
| xcomm `test_xexpr` | 9 cases，42 assertions passed |
| xcomm `test_xtrigger` | 22 cases，147 assertions passed |
| 128 位示例 native/Python 两条路径及 JSON 产物比较 | 通过；除执行路径元数据外完全一致 |
| `mkdocs build --strict` 与两仓库 `git diff --check` | 通过 |

覆盖 65/128/257 位，0 位宽 XData 所代表的单 bit 标量，64/65 位边界、完整非法快照、
高位 X/Z、宽 Trigger/abort、默认/显式累计隔离、reset、非法失败清理与旧 ABI 检查。
现有 `functional_coverage.py --wide [--native]` 提供可运行的 128 位示例。
本次未改项目 RTL 或事务流程，不重复执行 e203/Cache 全量项目用例；上表仅报告本轮实跑结果。
有符号覆盖和任意宽算术表达式仍未扩展。

## 可选诊断与并发匹配（同日后续，讨论项 3/4）

先加入重叠 Sequence/FSM 回归，确认旧接口拒绝 overlap 参数，再完成 Python/native
两条路径。测试追加到既有文件；没有新建公共类、调度器或逐实例 asyncio task。

- `bind(overlap=True, max_active=N)` 为复杂模式启用有界重叠，默认仍单实例。
  每拍先推进旧匹配再启动新匹配，完成释放容量；同拍多个完成分别采样。
  Sequence 的重叠起点为 Wait；FSM 离开 start 或直接终态启动，自环不启动，回到
  start 且未触发终态结束为 failed。普通通知和覆盖共用步骤/FSM 推进函数。
- C++ 仅为各匹配保存私有 MatchState，共享程序。活跃表线性推进和原地压缩，
  不复制每份状态机程序、不因逐个 erase 形成平方级搬移。达到容量再有新起点会报错，
  保留已有证据并设置 collection_complete=False，覆盖断言不能将其视为达标。
- `diagnostics="summary"` 独立开关，默认 off。固定计数包含启动、完成、失配、
  过期、中止、清历史、峰值和退出未完成数；不开启时不分配 native 汇总数组。
  `inspect()` 在 Execution 内按需读取当前步骤、年龄、连续保持次数或 FSM 状态，
  不需要打开诊断，不记录完整过程日志。
- JSON 保存可选汇总，单页/多页 HTML 折叠展示；不改变覆盖分母。混合开关的运行标明
  collected/uncollected 数量，不能把未收集解释为零。事件累加、峰值取最大；
  merge/accumulate 都不带入活跃匹配。退出先统计 unfinished 再释放，不伪装成 abort。
- ABI 升至 v3，需配套重建 xcomm。旧 ABI 下 native 启动报错，auto 整组回退。

回归覆盖：默认行为、多个模式同时完成、旧结束/新开始同拍、FSM 分支独立、自环和
返回起点、截止周期命中与过期、abort 优先、clear/reset、跨 Execution 历史隔离、
混合诊断合并、容量错误、用例异常、外部取消和宿主任务不受影响。快照读取不推进状态，
普通 native 命中仍不增加 RunUntil 返回次数。

微基准使用同一 no-op native XClock，20,000 周期 × 5 次，包含 Execution 启动和清理。
Sequence 在稳态有 3 个活跃匹配，关闭/开启汇总只改变诊断开关：

| 模式 | 中位数 ns/周期 | 每次运行 RunUntil 返回次数 |
| --- | ---: | ---: |
| 原生重叠，诊断关闭 | 1217.15 | 1 |
| 原生重叠，summary | 1219.83 | 1 |

本次差异约 0.2%，接近测量噪声，不能据此承诺其他负载的开销，更不能推算 RTL 性能。
保留所有原始样本（本地产物：`pattern-coverage-measurements-2026-09-30.json`）。计数、未完成数量和
返回次数均由基准断言核对。可运行示例为 `functional_coverage.py --overlap [--native]`。

本轮最终验证：

| 检查 | 结果 |
| --- | --- |
| `python3 -m pytest -q --require-xspcomm` | 533 passed，3.61 s |
| xcomm `test_xtrigger` | 24 cases，168 assertions passed |
| xcomm `test_xexpr` / `test_xfsm` | 9 cases / 42 assertions；3 cases / 24 assertions passed |
| 并发示例 Python/native JSON 比较 | 除 sampling_backend 外完全一致 |
| `mkdocs build --strict` | 通过 |
| 两仓库 `git diff --check` | 通过 |

框架测试使用 `/tmp/xreactor-verification-venv/bin/python3`，并设置
`XCOMM_PYTHON=/tmp/xreactor-coverage-native-build/python`；示例与基准通过 PYTHONPATH
选择同一 ABI v3 binding。未覆盖安装旧的 picker binding；交付时需要配套 C++ 与 Python
适配，使用指南已注明版本要求。

## 尚未交付的后续阶段

capture、按 key 关联事务、可配置 pause、完整过程轨迹及 e203/Cache 内部观测扩展仍
未实现。有界模式并发不等于事务配对，同一个结束条件可以完成多个匹配；事务关联继续
使用 Monitor/Scoreboard。UCIS 留到下一步单独讨论。

本次未扩大两个 RTL 示例原有 54/43 个事务 bins 的功能范围；既有项目回归通过不代表
内部状态覆盖目标已经完成。未改项目 RTL 或协议时序，因此不重复执行两个项目的全量用例。
