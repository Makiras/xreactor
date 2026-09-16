# XReactor 当前实现说明（代码审计版）

> 状态日期：2026-09-16
> 事实来源：`src/xreactor/` 与 `../dependence/xcomm/` 当前代码。
> 本文描述“已经能运行什么”，不把 Roadmap 中的规划当作现有能力。

## 结论

当前已经完成一个可运行的**单时钟、asyncio-native 核心 MVP**，但没有完成整个
M0～M6 Roadmap。

已形成端到端闭环的是：

```text
await XTrigger
  -> XReactor Registration + asyncio.Future
  -> XCommClockBackend
  -> C++ XTriggerEngine 在 stable phase 求值
  -> 一批 XBackendHit
  -> typed XEvent
  -> 恢复等待它的 asyncio Task
```

Expr、Sequence 和分支 FSM 已经能在 C++ 中逐 sampling phase 求值；普通 HTTP、
Queue 和其他 asyncio task 与 SimulationPump 共用宿主 event loop。尚未完成的主要
部分是多时钟共同时间模型、native program 回收、zero-copy hit、宽位/signed IR、
GIL release/owner thread 和完整第三方兼容矩阵。框架级 functional coverage 核心与
真实 e203 memory-direct 验证闭环也已经完成。

## 代码组成

| 层次 | 当前实现 | 职责 |
| --- | --- | --- |
| Python Trigger | `triggers.py`、`decorators.py` | awaitable 规格、`@xtrigger`、`@pytrigger` |
| Python IR | `ir.py` | Expr、Sequence、分支 FSM 的不可变描述 |
| Reactor | `reactor.py` | Registration、Future、广播、取消、订阅队列 |
| 调度 | `execution.py` | RunUntil batch、wall quantum、pause、asyncio yield |
| asyncio adapter | `external.py`、`combinators.py` | Event/Queue/Task/WallTimeout、AnyOf/AllOf |
| 协议 primitive | `protocols.py` | falling drive、ready backpressure、单 rising 接受 |
| 数据/接口 | `data.py`、`interfaces.py` | Bundle、四态快照、ReadyValid role/fire |
| 方法学组件 | `components.py`、`drivers.py`、`monitors.py` | Driver/Monitor 契约、ownership、原子 capture |
| 功能覆盖 | `coverage.py`、`coverage_report.py` | CoverGroup/Point/Bin/Cross、LCOV 与统一 HTML |
| 测试 backend | `MemoryBackend` | Python 语义模型，不代表 simulator 性能 |
| native bridge | `XCommClockBackend` | IR lowering、SWIG 批量转换、program cache |
| C++ 热路径 | `xspcomm/xtrigger.h`、`xtrigger.cpp` | watcher、phase 求值、FSM state、hit batch |
| 时钟基础 | `xclock.h`、`xclock.cpp` | StepHalf、half tick、stable phase |

`XTrigger` 是不可变等待规格；每次 await 创建独立 `Registration`。运行状态属于
Registration/C++ watcher，而不属于 Trigger。`XEvent` 是已经发生的结果，不是
可以再次 set/wait 的同步原语。

## 最小使用方式

```python
from xreactor import (
    FallingEdge,
    RisingEdge,
    Execution,
    Value,
    XCommClockBackend,
)


async def run(dut):
    # 新生成 DUT：clock 是直接 XData；GetXClock() 是其调度器。
    clock = dut.GetXClock()
    backend = XCommClockBackend(clock)
    async with Execution(
        backend,
        default_sample=RisingEdge(dut.clock),
        quantum_ms=10,
    ):
        await FallingEdge(dut.clock)
        dut.req.value = 1

        # 保证在下一 rising stable phase 判断，不在任意 Python 时刻判断。
        ready_event = await Value(dut.ready, 1)
        assert ready_event.phase.name == "RISING_STABLE"
```

`FallingEdge` 命中后，Pump 会先返回 asyncio，使同步写入有机会发生，再推进下一
个 Rising。`Value`、`ValueChange`、`@xtrigger` 和 `@pytrigger` 必须显式指定
`sample=`，或使用 Execution 的 `default_sample`；框架不猜测默认时钟。

## 已实现 Trigger

| Trigger/API | MemoryBackend | XCommClockBackend | 当前语义 |
| --- | :---: | :---: | --- |
| `RisingEdge` / `FallingEdge` | 是 | 是 | stable half-step barrier |
| `ClockCycles` | 是 | 是 | 只计算 rising stable phase |
| `Value` | 是 | 是 | 指定 sample 的无符号相等条件 |
| `ValueChange` | 是 | 是 | 以注册时值为 baseline |
| `SimTimeout` | 是 | 是 | simulation cycle，不是 wall time |
| `@xtrigger` Expr | 是 | 是，C++ 求值 | `&`、`\|`、`~`、六种比较 |
| `Sequence` | 是 | 是，C++ FSM | `Wait`、`Within`、`Hold` |
| 显式 `FSM` | 是 | 是，C++ FSM | 有序分支、goto、terminal trigger |
| `@pytrigger` | 是 | 是 | 每个指定 sample 回 Python 调同步 predicate |
| `WallTimeout` | asyncio | asyncio | 宿主 wall-clock timeout |
| `AsyncioEventTrigger` | asyncio | asyncio | 等待已有 asyncio.Event |
| `QueueTrigger` | asyncio | asyncio | event.value 携带取出的元素 |
| `TaskComplete` | asyncio | asyncio | shield 原 task，取消 waiter 不取消原 task |
| `AnyOf` / `AllOf` | asyncio | asyncio | 支持 simulation/external 混合等待 |

表达式的 `& | ~` 当前是逻辑组合，不是任意位运算表达式。Python 的
`and/or/not`、隐式 truth test 和链式比较会被拒绝，且不会自动降级成 pytrigger。

## Condition 发射模式

`Value`、Expr `@xtrigger` 和 `@pytrigger` 支持三种模式：

- `enter`：默认，只在 false 到 true 时发射；
- `each_sample`：每个为 true 的 sample 都发射；
- `change`：false/true 两个方向都发射，`event.value` 是变化后的布尔值。

新 Registration 的前值从 false 开始。因此条件注册时已经为 true，也会在下一个
明确 sample 发射一次，而不是在注册调用栈中立即返回。persistent subscription
rearm 时保留前值，所以持续高电平不会被默认 `enter` 每周期重复投递。

Sequence/FSM 本身只产生离散 terminal event，不接受非默认 Condition mode。

## FSM 与订阅

```python
from xreactor import FSM, RisingEdge, State, on, xtrigger


@xtrigger(sample=RisingEdge("clk"))
def request_ack(dut):
    return FSM(
        start="WAIT_REQ",
        states={
            "WAIT_REQ": State().when(dut.req).goto("WAIT_ACK"),
            "WAIT_ACK": (
                State()
                .when(dut.flush).goto("WAIT_REQ")
                .when(dut.ack).trigger("ACK")
            ),
        },
    )


@on(request_ack, delivery="lossless", capacity=64)
async def observe(event):
    scoreboard.push(event)


subscription = sim.subscribe(observe.bind(dut))
```

FSM 实例状态按 watcher 隔离。persistent FSM 采用非重叠语义：terminal phase
完成整批广播后 reset，从下一个 sampling phase 开始新一轮，不把 terminal phase
同时当成下一轮起点。

`@on` 不创造另一套 Trigger；它创建持久 Registration 和独立串行 handler task。
backend 在 handler 执行前 rearm，因此没有“handler 完成后才重新 await”的空窗。
可选同步 `capture(event)` 在 publish barrier 内取得不可变数据，再把结果交给 async
handler；capture 不允许 await。

- 默认 `lossless`，容量 64；
- 队列满抛 `SubscriptionOverflowError`，Execution 失败；
- `latest` 必须显式选择，满时替换旧事件；
- handler exception 默认使 Execution 失败；
- close 会 cancel 并 await 框架创建的 handler task，不取消外部 task。

## phase、batch 与 asyncio

当前有四个公开 phase：

- `FALLING_STABLE`；
- `DRIVE_STABLE`；
- `RISING_STABLE`；
- `EXTERNAL`。

每个 XClock half-step 内完成 clock pin、eval/write/eval/refresh 后才执行 TriggerEngine
求值。一个 phase 中所有 watcher 都扫描完，再整体返回 hit batch。

`DRIVE_STABLE` 是按需执行的同 half-tick barrier：FALLING_STABLE 广播后，Pump 让被
唤醒的 coroutine 执行到各自下一次 await；若此时存在 DriveStable watcher，则 backend
刷新组合逻辑并调用 native `SamplePhase(DRIVE_STABLE)`，同步 capture 完成后才推进
RISING_STABLE。它不等待 HTTP 或任意外部 task，也不冒充 ReadWrite/ReadOnly region。
backend 通过 `capabilities.drive_stable` 明确声明支持；不使用该 phase 的旧 backend
保持原有调用流程。

SimulationPump 默认：

- `max_batch_ticks=4096`；
- `quantum_ms=10`；
- `budget_check_interval=64`。

C++ RunUntil 在命中、edge barrier、run limit、backend stop 或 wall quantum 到期时
返回。每次返回后 Pump 都执行一次 `await asyncio.sleep(0)`，让 HTTP、pytest task、
取消和其他 coroutine 获得运行机会。

外部 await 不会自动暂停仿真。只有存在 simulation Registration/subscription 时
Pump 才推进；如果需要明确冻结，使用：

```python
async with sim.paused():
    response = await http_client.post("/configure")
```

框架使用当前 running loop，不调用 `loop.stop()`/`loop.close()`，也不取消不属于
框架的 task。当前实现不创建 simulator owner thread；RunUntil 在 event-loop 线程
执行，并用 wall quantum 控制最长占用时间。simulator kernel 内部可以多线程，但
其对外 StepHalf 必须仍表现为原子的 stable phase barrier。

## Event、Hit 和取消

C++ watcher handle 是 `slot + generation`。slot 可复用，generation 用于拒绝取消
之后到达的旧 hit。one-shot Future 被取消时，Reactor 会 disarm 对应 watcher。

同一个 native edge occurrence 的多个 waiter 共享 event id，Reactor 因而交付同一
Python Event 对象。条件 watcher 的 mode、baseline 和 FSM 状态属于各自 Registration，
因此各自产生 event id；框架只保证同 phase 完整返回所有 hit，不尝试把“相似条件”
猜测为同一个 occurrence。

`BackendHit` 当前通过一个 SWIG vector 批量返回，不进行逐 hit 跨语言 callback；
但 vector 到 Python tuple 仍会复制，因此还不是 zero-copy view。

## 数值和 X/Z

native 热路径支持任意位宽无符号值：

- 1～64 位使用标量 ABI，更宽信号使用 little-endian byte-vector ABI；
- 负常量和超过目标 signal 位宽的常量拒绝；
- 没有隐式截断和隐式 signed cast；
- Value/Expr 条件依赖 X/Z 时，该 sample 不命中；
- 未知 sample 不更新 `enter/change` 的布尔前值；
- ValueChange 对所有位宽比较完整 `(aval, bval)`，能区分 0、1、X、Z 的变化。

已知 ValueChange 的 `event.value` 是 int；含 X/Z 时返回
`LogicValue(value=aval, x_mask=bval, width=...)`。

## backend 与线程所有权

Execution 启动时要求 backend 声明 `BackendCapabilities`，并至少保证：

- half-step；
- stable sample。

当前 MemoryBackend 和 XCommClockBackend 均声明 `thread_safe=False`、
`reentrant=False`。同一个 backend instance 由 lease 限制为只能被一个 active
Execution 使用；不同 backend instance 可处于同一个 asyncio loop/context 中。

ReadWrite、ReadOnly、NextTimeStep 不属于框架 capability，也没有对应公开 Trigger。
它们解决的是 Python 被动嵌入事件驱动 simulator 时的 region 协调，而本框架由 XClock
主动执行 pin update、eval、edge write、再次 eval 和 refresh，并在完成后发布 stable
phase。各 simulator adapter 必须满足这个 XClock 契约，不向上层暴露内部 event region。

## 已验证内容

当前回归覆盖：

- falling 后写入早于下一 rising；
- 同 edge 广播、完整 phase hit、slot generation、cancel；
- Value/default sample/ValueChange/XZ；
- Condition enter/change、native false payload；
- Expr、Sequence、分支 FSM、program cache 和 state isolation；
- pytrigger sample/rearm；
- AnyOf/AllOf、Event/Queue/Task/WallTimeout；
- `@on` rearm、lossless overflow、latest、handler exception；
- 真实 `asyncio.start_server` HTTP 请求期间仿真继续；
- 显式 paused 冻结；
- backend instance 共享被拒绝；
- close 不接管宿主 event loop。
- covergroup/point/bin/cross、illegal/ignore/default、`at_least`、schema digest 与 merge；
- e203 IFU-to-ICB 参考模型、背压/错误注入、事务超时、functional 和 RTL line coverage。

验证命令：

```bash
cmake --build /tmp/xreactor-xcomm-engine-build --parallel 64
ctest --test-dir /tmp/xreactor-xcomm-engine-build/tests \
  --output-on-failure -j 64

PYTHONPATH=src:/tmp/xreactor-xcomm-engine-build/python \
python3 -m pytest -q

examples/integration/e203/build_xreactor.sh
python3 -m pip install -e '.[test]'
examples/integration/e203/run_pytest.sh
```

此外，`example/CacheSignalCFG` 已用 Picker `--rw mem_direct` 重新生成并实际运行：新生成
端口直接为 `XData`，并报告 `XDataBackendKind_MemDirect`；`FallingEdge(clock)`、
`Value(ready)`、Expr `@xtrigger` 和 ReadyValid `fire` 均在 native 路径工作。`XPin`
与 `XData.xdata` 已作为本次 breaking change 删除，生成 DUT 直接暴露 XData。生成 DUT
同时提供 `dut.io.in_.req.bits.addr` 一类只读结构视图，
并与扁平属性保持同一 XData identity；顶层 `dut.io` 仍是 XPort，以保留批量 backend
API。协议不从名字推断，而由调用方通过 `ReadyValid.bind_tree()` 显式声明。smoke 脚本为
`examples/integration/cache/example_xreactor.py`。

Cache 功能验证器 `examples/integration/cache/cache_functional_xreactor.py` 进一步提供真实
refill/writeback/MMIO responder 和参考模型，覆盖 read miss/hit、masked write、
write allocate、4-way dirty eviction、backpressure 及冲突密集随机序列。三个 seed、
每个 300 次随机操作的数据核对均通过，并发现 early miss response 后、依据 ready
接受的下一请求在固定 clean-reset probe 中永久无响应。MMIO 重复请求的早期现象经纯同步
StepHalf 差分后已确认是 testbench valid 跨过两个 rising edge，修正 driver 后消失；
early-response overlap 缺陷则在同一纯同步 probe 中仍然复现，已排除 XReactor 调度。详见
`verification/cache-functional.md`。XPin 删除决策、XData native identity 和时钟域校验见
`backend/xpin-xdata-boundary.md`。

Cache 验证期间发现手写 ready/valid driver 很容易让 valid 意外跨过两个 rising edge，
因此框架新增 `drive_ready_valid()`。它复用当前 falling-stable phase、调用 backend
组合刷新、在 backpressure 时保持 payload，并在首个 accepting rising 后撤销 valid；
取消也会清理 valid。语义和边界见 `features/ready-valid.md`。

e203 IFU-to-ICB 环境进一步使用独立参考模型核对 0/1/2 次 ICB command、路由、地址、
指令数据和 error OR；主 seed 的 510 个事务达到 100% functional coverage，RTL line
coverage 为 198/300（66.0%），重复完整运行约 480～495 transactions/s。8-seed 矩阵共
2080 个事务通过；另有真实延迟响应触发事务预算 `TimeoutError` 的 pytest。详见
`verification/e203-functional.md`。

functional sampling 采用预编译 source path/exact-bin/cross set 和 `details=False` 快路。
真实 e203 相同流量的 9 组 on/off A/B 中位 slowdown 为 5.32%，并提供可失败的 CI 门槛；
pytest 同时产生自包含 functional + LCOV line coverage HTML。详见
`features/coverage-performance-and-reporting.md`。

当前结果为仓库 CTest 24/24、native-backed Python 99/99、e203 pytest 2/2 通过。没有
native 模块时，MemoryBackend/asyncio 测试仍可运行，native 测试会 skip。

性能脚本位于 `benchmarks/benchmark_runtime.py`，覆盖 Raw Step、逐次
StepHalf、RunUntil 无 watcher/Value/Expr/FSM、pytrigger 和逐周期 Future 恢复；
`benchmark_coverage.py` 测量 point/cross 每事务成本，e203 另有真实 DUT A/B benchmark。

## 尚未完成

### P0：进入生产使用前应优先解决

1. **native program 生命周期**：相同 IR 有 cache，但大量唯一 Expr/FSM program
   的 ExprEngine node 目前只在 backend close 时统一清理，缺少 refcount/arena 回收。
2. **完整性能矩阵**：e203 memory-direct 已形成包含 DUT eval 和 Verilator coverage 的
   吞吐基线；waveform 开启后的代价、长期运行内存曲线和 HTTP latency p50/p99 尚缺。
3. **错误模型**：StopReason 类型已定义，但 callback/backend exception 主要通过
   Python exception 传播；USER_PAUSE/SIMULATION_CLOSE 等并非都由 RunResult 发出。

已完成的原 P0 位宽项：XData 本身的任意位宽读写已贯通到 native `Value`、
`ValueChange` 和直接 `@xtrigger` 比较；`PackedArray/split_packed` 可将单根 Verilog
packed bus 显式拆成等宽 XData lane，`PackedLayout/PackedView` 进一步支持多维数组、
数组/Struct 任意嵌套、每层位序、stride、显式 offset 和 padding。布局只在构造时编译，
leaf 都直接引用根 XData。宽 signed/cast 与宽算术仍是独立语言设计，不属于此次
无符号位宽修复。

### P1：按真实用例选择的扩展

1. 多时钟、分频 clock 的共同 global tick 和 deterministic ordering；
2. 跨 domain AnyOf/Sequence/FSM 和 domain/backend pause；
3. 写缓冲、同 phase 多 driver 冲突诊断；
4. 显式 signed/cast/width IR，以及确有需求时的宽算术；
5. overlapping FSM instance；当前只支持非重叠。

### P2：测量驱动的优化与生态验证

1. SWIG hit 的只读 zero-copy buffer/view；
2. GIL release，以及 profiling 证明需要时的 simulator owner thread；
3. adaptive batch/quantum；
4. pytest-asyncio、aiohttp、FastAPI 的安装后 CI 兼容矩阵与 latency p50/p99；
5. trace、结构化错误上下文、内存/长期 subscription 压测；
6. Bundle/ReadyValid 的 native batched snapshot。框架保留通用 Driver/Monitor 与显式
   Interface binding；协议类型组织、Scoreboard 和 pytest 工程脚手架由上层代码或 agent
   基于 signal tree/metadata 生成，不进入核心框架。Cache 的八个 ready-valid 子树均已
   绑定，CPU/memory/MMIO 功能流量已通过统一抽象；coherence 当前只有绑定验证。

## 推荐下一步

最短、风险最低的推进顺序是：

```text
program arena/refcount + 内存压力测试
  -> 补齐 waveform/HTTP/长期运行性能矩阵
  -> 按 profiling 决定 zero-copy hit / GIL / owner-thread
  -> pytest/HTTP 兼容矩阵
  -> 真实用例需要时再扩展多时钟 domain 模型
  -> native batched Bundle snapshot
```

因此，当前版本适合继续做单 XClock 调度域 DUT 的 API 验证、语义测试和性能迭代。
它不以复刻 cocotb event-region scheduler 为目标；多时钟是否扩展由真实用例决定。
