# XReactor 现状与易用性评审

日期：2026-09-28。基线：`HEAD 2be994d` 加当前工作树，包含事务机制收敛后的实现。
本文是代码、文档和定向运行检查得到的评审，不是用户测试或性能测量。
第 1～5 节保留提出建议时的状态；本次获准后的实施结果见第 6 节。
此前事务改动见[前次评审第 9 节](framework-review-2026-09.md#9-事务机制实施记录)。

## 1. 当前状态

当前已经可以组织完整的驱动、观察、预测、匹配和结束检查。下一步易用性工作的重点
应是让使用者更容易选对已有能力，并能从失败中快速定位原因。

| 层次 | 已有能力 | 使用与验证边界 |
| --- | --- | --- |
| 执行 | asyncio、Execution、MemoryBackend、native XClock、stable phase、外部任务 adapter | 单 backend 的资源归属清楚；不代表支持通用多时钟时间轴 |
| 等待与观察 | edge/value、编译条件、Sequence/FSM、持续订阅 | 模式命中、超时事件和断言失败是不同语义，需要显式区分 |
| 数据与组件 | Bundle/snapshot、packed view、信号 ownership、通用 Driver、Monitor 契约 | 已能用普通 Python 对象组合；驱动何时接受输入仍由具体设计决定 |
| 事务检查 | XTransfer、FIFO/key/固定延迟、周期 deadline、bounded drain/finish、后台失败传播 | 异步 Scoreboard 当前要求单 XClock 的 rising-stable 接受与观察记录；Monitor 必须及时交付 |
| 覆盖与报告 | 功能覆盖、功能点、pytest 集成、HTML/LCOV | 已有独立职责，无需为易用性再引入一套运行管理框架 |

本次重新执行强制 native 回归：**180 passed in 0.78s**。基础示例与协议无关事务示例
也运行通过。当前正确性证据比之前充分，但没有重新构建 RTL、重跑 Cache/e203 完整
验证或量测长时间吞吐。尤其 Scoreboard 的每 falling phase deadline 检查会返回 Python，
其性能影响仍需单独测量，不能从测试数量推出。

## 2. 最值得先解决的使用障碍

### 2.1 第一个测试还不是一条完整路径

[快速开始](../../docs/getting-started/first-test.md) 的入口是
`async def test_request(backend, dut)`，但没有给出 fixture 与 pytest asyncio 标记。
后面的 backend 片段和纯 Python 示例能补充理解，用户仍需跨页拼出一个可运行测试。
[安装检查](../../docs/getting-started/installation.md) 只验证 `import xreactor`，
不验证 native binding 是否具备当前 backend 所需能力。

建议先提供两条清楚的路径：

- **不接 RTL 的第一个测试**：一个完整 pytest 文件，包含 import、marker、替身和
  Execution，给出精确运行命令；示范等待、比较以及一次可理解的失败。
- **接入已有 DUT**：一个完整 fixture 配方，明确 DUT 构造位置、获取 XClock、backend
  创建与关闭责任；设计相关输入和时序由项目填入，不猜测信号名、协议或响应延迟。

将这些可运行文件作为文档示例的来源。少量关键入口在 CI 中执行，比只检查 Markdown
能否构建更能防止文档漂移。现有 `examples/triggers/basic_execution.py` 和
`examples/transactions/scoreboard.py` 可以复用，不需要先开发脚手架 CLI。

### 2.2 超时与取消的写法短，但容易理解错

实测 `await SimTimeout(...)` 和 `await WallTimeout(...)` 都返回
`XEventKind.TIMEOUT`，不会自动让测试失败。
[Trigger 指南](../../docs/guides/triggers.md) 的组合等待示例没有继续判断超时分支；
照着改成“等待结果或超时”后，使用者可能误以为已经建立了失败条件。

立即可用的写法应完整展示：

```python
event = await AnyOf(condition, SimTimeout(budget, clock=clock))
if event.kind is XEventKind.TIMEOUT:
    raise TimeoutError(f"condition was not observed within {budget} cycles")
```

这段只说明显式处理结果，不承诺同一周期边界的确定仲裁。当前 AnyOf 对**同一轮已完成**
来源按参数顺序选胜者；它本身不保证让整个采样 phase 的处理完成后再判超时。
Scoreboard 已有专门的 deadline barrier，不能把它的截止周期保证直接推广给 AnyOf。

另一个实测结果是：

| 等待方式 | 超时先完成后，原有 task 的状态 |
| --- | --- |
| `AnyOf(task, WallTimeout(...))` | 未完成的原 task 被取消 |
| `AnyOf(TaskComplete(task), WallTimeout(...))` | 原 task 继续运行 |

原因是组合器取消落败的等待，而 `TaskComplete` 用 shield 隔离外部任务。
这和“取消 XTransfer 的 waiter 不取消底层事务”同样需要在示例中讲清楚。
原 task 本身未必返回 XEvent，也应通过 adapter 统一返回类型。

**值得考虑的小接口**是“有预算地等待条件，超时抛异常”的便利函数。仅当多个实际测试
都在重复上述样板时再加入。它必须显式接收 clock 和周期预算，并先定义同周期命中优先、
外部取消及来源任务归属；不能只是随手包一层 AnyOf，也无需扩成通用 assertion 框架。

### 2.3 事务 API 需要一张按任务选择的表

`SyncDriver` 的 `send()` 同样是 async def；Sync/Async 表达的是调用方式，
不是阻塞与非阻塞 Python。`Transfer` 是观察记录，`XTransfer` 是事务句柄。
这些对象有各自用途，但名称本身不足以解释差异。

建议把下面这类表放到入门指南，并让示例分别使用恰当的最小路径：

| 我现在要做什么 | 使用什么 | 需要知道的结束条件 |
| --- | --- | --- |
| 已经拿到两个值，只做比较 | `Scoreboard.check(expected=..., actual=...)` 或普通断言 | 比较完成；无需 driver/monitor |
| 等待输入被接受 | `await driver.send(request)` | 不表示响应已完成 |
| 排队提交，并跟踪响应 | `scoreboard.submit(request)` 返回 XTransfer | Scoreboard 关联并检查响应；直接 driver.submit 时需要自行完成句柄 |
| 等待一个事务结果 | `await transfer` | 完成或失败；取消等待不撤销事务 |
| 等当前批次完成，后面还要发 | `await scoreboard.drain(timeout_cycles=...)` | 只等待调用前的提交，不代表严格结束 |
| 不再发请求，检查测试结束 | `await scoreboard.finish(timeout_cycles=..., observe_cycles=...)` | 封闭提交、排空、有限观察和残余检查 |
| 退出或异常清理 | context manager / `aclose()` | 检查当前状态并释放资源，不替代有预算的 finish |

还应把三种预算并列说明：单事务响应预算、drain/finish 总预算、外部 wall watchdog。
finish 的观察窗口计入其总预算。不要用猜测的默认周期数换取参数减少。

可先改善入口文字和类型说明，再决定是否改名。若以后修改草案名称，应一次性同步调用，
不必堆积兼容别名；目前没有足够收益支持单独进行大规模改名。

### 2.4 文档存在可以直接修复的断点

- [编译与订阅指南](../../docs/guides/compiled-triggers.md) 使用
  `scoreboard.push(event)`，既未定义该变量，当前 Scoreboard 也没有 push 方法。
  若想表达自定义 sink，应明确命名；若指公共 Scoreboard，应使用真实接口。
- README 和用户手册首页的指南列表未列出 Scoreboard 与功能点文档，但 MkDocs
  导航已经包含它们；`docs/examples.md` 也没有事务示例入口。
- API 索引混合展示普通用户与 backend 扩展者需要的对象。当前顶层共有 **122** 个
  `__all__` 导出；这不是要求删 API 的依据，但支持按“常用 / 扩展”组织阅读入口。
- `Sequence/Within/Hold` 是观察模式；用户应在其示例旁就看到“未命中不会自动报错”，
  而不必先读底层实现。激励场景继续用普通 async 函数组合。

这些改进主要是修正文档和组织入口，不需要新框架设施。

## 3. 少量接口便利性，如何选择

### 3.1 订阅可以评估直接绑定入口

当前简单回调也要经过 `@on`、`.bind()`、`execution.subscribe()`。
这个流程对可复用、待绑定 DUT 的定义有价值；对已经拿到 trigger 的局部检查稍显繁琐。
同步 handler 会明确报错：`@on handler must be async def`。

可以评估一个直接绑定的 subscribe 入口，内部生成现有 BoundSubscriptionSpec，
继续使用已有队列、容量和失败传播，不另建事件系统。只有在局部订阅用例反复出现时
才值得加这个入口。

同步 sink 是否可接入应单独决定。`capture` 必须在采样时同步取得快照，handler 则在
交付时处理快照；便利接口不得混淆这两个时间点。先把一次同步采样和一个 async handler
的正确配方讲清楚，不能为了少写 async 就让用户在延迟处理时重读 live signal。

### 3.2 生命周期样板优先用 Python 的组合方式解决

Execution、Driver、Scoreboard 的嵌套表达了不同资源归属。可以用 Python 支持的
多项 `async with` 减少缩进，重复环境放入项目自己的 pytest fixture 或
`asynccontextmanager`。测试体专注输入、检查和显式 finish。

这不需要 VerificationScope，也不应让一个 context 自动猜 drain 预算、reset 操作
或 DUT 合理延迟。backend 仍由创建者关闭；Scoreboard 独占消费并管理绑定 Monitor，
Driver 仍由外层管理。

### 3.3 诊断应减少换算和定位成本

Scoreboard mismatch 已包含 request、字段路径、期望/实际值及时间戳，是值得保留的
基础。超时异常主要用文本携带 deadline/current tick；调用参数则以 cycle 表示。
建议同时显示已等待周期、配置预算和原始 tick，并让关键字段可供程序读取。

例如期望诊断的信息形态是：“事务 17 在 tick 20 接受，预算 4 cycles，截止 tick 28，
当前 tick 29 尚无匹配响应”，同时指出是响应预算还是 finish 总预算耗尽。
仅保留首个失败及少量相关记录即可，不需要恢复全历史保存或引入 trace 服务。

binding 诊断则应展示实际加载的 xspcomm 模块路径与缺失 API，让“装错 binding”
和“测试断言失败”容易分开。先提供安装检查配方；是否做 doctor 命令可后置。
已有 backend 构造检查应复用，不建立另一份易漂移的能力清单。

### 3.4 数据和覆盖优先提供小例子，不急于增加 DSL

Bundle 是 live view，BundleValue 是 snapshot，LogicValue 保留 X/Z。
需要把“采样 → 明确转换 → model/coverage”这条路径讲透，例如显式
`snapshot.data.as_int()`；不能默认转 int、吞掉未知值来让代码显得简短。

coverage 的 definition、instance、database 分别负责结构、计数、保存合并，
没有证据需要合成一个大对象。先给只有一个 coverpoint 的完整最小示例，再渐进加入
cross 与报告。reference model 不用 context 时，`lambda request, _: model(request)`
足够简单，目前不值得为省去这个参数再加一套 callable 自动适配。

## 4. 优先级与完成标准

| 优先级 | 建议 | 完成标准 |
| --- | --- | --- |
| 先做 | 完整快速开始、补齐入口、修订失效订阅示例 | 安装后能按一页文档运行；关键示例有执行校验 |
| 先做 | 超时/任务取消示例、事务选择表、预算说明 | 使用者能区别接受/完成、超时事件/失败、drain/finish，且知道外部 task 是否会被取消 |
| 随后 | 统一易读诊断、binding 检查配方 | 失败输出能指向配置与事务；无需读内部容器或手动换算 half-tick |
| 有重复用例再做 | 抛异常的条件等待 helper、直接订阅入口 | 各消除真实重复代码；沿用当前调度、队列和生命周期，不增加新的所有者 |
| 暂不做 | 新 Scope、广播设施、回放/回归平台、全面重命名、新 coverage DSL | 当前易用性问题不要求这些设施；以后由独立需求决定 |

ready/valid、reset/flush、协议判断及具体 Driver 的时序不属于这些建议的调整范围。
明确的 clock、预算、接受语义和四态值检查应保留，它们提供必要的可预测性。

## 5. 本次检查记录

使用已经安装当前工作树的临时 venv 和现有 native xspcomm 构建：

```bash
PATH=/tmp/xreactor-verification-venv/bin:$PATH python3 -m pytest -q --require-xspcomm
/tmp/xreactor-verification-venv/bin/python3 examples/triggers/basic_execution.py
/tmp/xreactor-verification-venv/bin/python3 examples/transactions/scoreboard.py
PATH=/tmp/xreactor-verification-venv/bin:$PATH mkdocs build --strict
```

回归 180 项通过；基础示例输出 `ready at 2, handshake at 4`；事务示例输出
`checked=8, passed=8, completed=8`；严格文档构建通过。

额外定向检查验证了以下当前行为：

```text
WallTimeout: returned kind=TIMEOUT
SimTimeout: returned kind=TIMEOUT
AnyOf protected=False: source.cancelled=True
AnyOf protected=True: source.cancelled=False
sync handler: @on handler must be async def
public exports: 122
Scoreboard.push exists: False
```

其中 protected=True 指使用 TaskComplete 包装已有 task；probe 在外部任务未完成时
让 WallTimeout(0) 获胜，并在检查后自行清理任务。本次只新增评审记录和设计索引，
没有实施上面的 API 或运行时改动。

## 6. 易用性优化实施记录

2026-09-28，按用户要求落实当前收益明确的改进：

- 新增完整的 `examples/getting_started/test_first.py`，入门页给出可直接复制运行的
  fixture、测试和失败演示；真实 DUT 接入配方只要求替换项目构造/释放函数。
- 新增 `check_native.py`，输出实际 binding 路径，通过已有 backend 构造检查和
  native 时钟推进验证接入；新增 `examples/triggers/subscription.py` 示范同步
  capture 快照和异步消费。CI 执行这三个入口及现有事务示例。
- 修复不存在的 scoreboard.push 示例；完善超时、任务取消、采样快照、Sequence
  未命中语义；补全首页与示例导航。API 索引分离常用入口和扩展者协议。
- Scoreboard 指南增加任务选择表、三类预算和结构化超时属性说明。生命周期示例
  使用多项 async with，并显式关闭 backend；没有增加 Scope 或别名兼容层。
- ScoreboardTimeoutError 增加 operation、budget_cycles、elapsed_cycles、start_tick、
  deadline_tick、current_tick、context、status、reason。固定延迟以实际窗口报告，
  finish 排空阶段的超时标为 finish；提前发现观察窗口放不进预算时，不误报已经耗尽。
  这些改动不改变关联、截止判定、采样相位或具体 Driver 时序。

运行示例进一步验证了读取 live signal 的陷阱：Value 命中时 count=3，AnyOf 返回后
count 可能已经为 5。入门测试改为检查 event.value 和 event.tick。AnyOf 可能在恢复时
同时看到不同 tick 的已完成来源，并按参数顺序选胜者；缩短 SimTimeout 参数不保证
抢在排在前面的已完成条件之前获胜。因此失败演示使用每次加 2、永不命中 3 的计数器，
且文档明确事务精确 deadline 应使用已有 Scoreboard，不承诺通用组合等待具有此能力。

验证记录：

- `python3 -m pytest -q --require-xspcomm`：181 项通过，覆盖结构化响应/固定延迟/drain/
  finish 失败，以及原有截止周期正确响应和资源清理回归。
- 入门示例：1 项通过；文档直接提取的同一测试通过，修改计数步长后的预期 TimeoutError
  已验证。
- native 自检输出 `tick=2, phase=RISING_STABLE`；订阅输出三个正确计数快照；事务示例
  输出 `checked=8, passed=8, completed=8`。
- `mkdocs build --strict` 和改动格式检查通过。

未加入条件等待 helper、直接订阅重载或其他管理设施；这些仍等待重复实际用例。
本轮没有重新构建 RTL 或量测真实 DUT 性能。

## 7. 流水相关使用场景与验证

本节记录 2026-09-28 的初版。2026-09-29 已由框架管理阶段锁交接，删除示例的手动
sleep(0)；最新实现和验证见 [Driver 交接修复记录](driver-handoff-2026-09.md)。

2026-09-28，按用户要求将流水相关能力写成可运行示例和文档，并验证实际时序。

- 文档：`docs/guides/pipeline-examples.md`；代码：`examples/transactions/pipeline.py`；
  回归：`tests/integration/test_pipeline_examples.py`。
- 六种成功场景：连续输入并等待多笔响应、保序变延迟响应、串行输入阶段、重叠输入阶段、
  直接并发 send、倒序 key 响应；四种预期失败：漏响应、固定延迟迟到、错误选择 FIFO、
  提交超出容量。输入接受、响应与 idle 约定全部由替身明确提供，没有 ready/valid 策略。
- 示例直接继承现有通用 Driver，自行定义单拍或多阶段 `_drive_one()`；没有新增
  Pipeline 基类，也没有在本轮修改现有 API 名称或移除 SingleCycle 导出。
- 实测发现单纯检查协程执行记录不足以证明阶段在采样时重叠。示例在释放第一阶段锁后
  `await asyncio.sleep(0)`，让等待者先获取执行机会，再注册第二阶段的长时钟等待。
  两种 backend 均验证：max_active=2 时 tick 4 采到第一阶段请求 2、第二阶段请求 1，
  tick 10 采到第一阶段请求 3、第二阶段请求 2。接受 tick 从串行的 8/16/24 变为 8/14/20。
  这不把 sleep(0) 定义成一般采样屏障，也不改变框架时序语义。

验证结果：

```text
python3 -m pytest -q tests/integration/test_pipeline_examples.py --require-xspcomm
22 passed in 0.08s

python3 -m pytest -q --require-xspcomm
203 passed in 0.86s

mkdocs build --strict
成功，无链接诊断
```

使用现有临时 venv 和本地 native binding。另以 subprocess 验证 memory/native 各自的
默认成功入口退出码为 0，四个失败入口退出码为 1 且错误类型正确。测试检查实际引脚采样、
响应值、阶段独占、句柄完成顺序和资源清理；CI 加入两种 backend 的成功示例命令。
