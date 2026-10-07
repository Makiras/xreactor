# asyncio 调度观察器：实现与使用

日期：2026-09-29。状态：已接入公共 Execution；Driver 专用交接机制已移除。

asyncio 是唯一执行 Python Task 和回调的调度器。Execution 观察宿主的即时回调，
只决定能否进行下一次时钟推进或 DriveStable 采样。原生 Task、Handle、Lock、Queue、
Event、Semaphore 和 TaskGroup 保留原有职责，没有另一套执行队列。

## 实现位置与职责

| 文件 | 职责 |
| --- | --- |
| [\_asyncio_observer.py](../../src/xreactor/_asyncio_observer.py) | 观察 call_soon、回调登记、取消记录清理、收敛检查、共享入口恢复 |
| [execution.py](../../src/xreactor/execution.py) | 绑定 context、管理 Pump、阶段屏障、external_task、退出清理 |
| [\_driver_runtime.py](../../src/xreactor/_driver_runtime.py) | 原生 Lock/Semaphore 与驱动返回事件校验 |
| [集成回归](../../tests/integration/test_asyncio_observer.py) | asyncio 组合、取消、外部隔离和 loop 接入边界 |

原来的 DriverPermit/HandoffBarrier 已删除。resource_lock 仍可按资源名复用锁，但
返回原生 asyncio.Lock；max_active 使用原生 Semaphore。具体协议、接受时序、idle
策略和响应关联没有改变。异步串行 worker 继续复用，避免逐事务分配任务。

## 阶段收敛契约

在 event-loop 线程内，已接纳到本 Execution 的即时回调，以及它们继续产生的即时
回调，都执行完毕或取消，才进入下一次推进/采样。任务在 pending Future 上挂起时，
本次运行结束；不等待整个任务退出。新 Task 的初次运行同样属于就绪工作。

跟踪对象是回调，而不只是 Task。gather/shield 等操作会通过完成回调继续唤醒父任务，
只观察任务退出会遗漏中间的回调链。归属来自回调将要运行的目标 context，而不是
唤醒者的 context；因此 Pump 唤醒用户任务时不会丢失用户任务的归属。

```text
时钟事件 -> A 恢复 -> 原生 Lock 唤醒 B -> 原生 Queue 唤醒 C
         -> C 完成写入并挂起 -> 当前阶段无剩余工作 -> 采样/推进
```

## 核心代码

以下是源码的机制摘录，省略共享安装和生命周期处理。内部域只保存登记状态，不是
公共 Scope 或调度器。真正的入队和执行始终由原来的 call_soon 完成。

```python
# current_domain 是 ContextVar；domain.pending 是未完成回调记录的集合。
domain = current_domain.get() if context is None else context.get(current_domain)
if domain is None or domain.closed or domain.observer is not self:
    return original(callback, *args, context=context)

call = _PendingCall(domain, callback)
domain.pending.add(call)
try:
    handle = original(call, *args, context=context)
except BaseException:
    domain.pending.discard(call)
    raise
call.handle = handle
return handle  # 原生 asyncio.Handle
```

_PendingCall 是由 asyncio 调用的普通 callable；它不自行执行另一个 Task：

```python
def __call__(self, *args):
    try:
        self.callback(*args)
    finally:
        self.domain.pending.discard(self)
        self.handle = None
```

若 A 在运行中唤醒 B，B 先登记，A 后结算，登记集合不会在两者之间出现假的空闲窗口。
取消的 Handle 不会执行上述 finally，所以推进检查会剔除 cancelled() 的原生 Handle。
这里只查看本 Execution 的记录，不查看 loop._ready 或 Task._fut_waiter。

```python
while self.pending and not self.closed:
    for call in tuple(self.pending):
        if call.handle is not None and call.handle.cancelled():
            self.pending.discard(call)
            call.handle = None
            call.callback = None
    if not self.pending:
        return
    check_settle_budget()
    await asyncio.sleep(0)
```

sleep(0) 只把执行权交回宿主；正确性取决于登记集合清空，不依赖固定让出次数。
空集合路径直接返回。源码还为常见的零参数和单参数回调保留直接调用路径，减少
包装层重新打包参数的成本；域外零参数任务恢复也使用这个快速路径。

Execution 在推进前等待显式暂停解除和阶段收敛：

```python
while not self._closing:
    await self._resume.wait()
    await self._domain.settle(self.backend)
    if not self._pause_depth:
        return
```

最后一次检查和实际 backend 调用之间不再 await。处理工作时用户可能进入 paused，
所以等待收敛后需要复查暂停状态。

## Pump、同步回调与外部任务

Pump 本身在中性 context 中创建，不能把等待屏障的自身回调计入屏障。
backend 执行与 Reactor.publish 则在保存的 Execution context 中同步调用；这样
native callback、subscription capture 创建的任务也正确继承仿真归属。

external_task 只在当前活跃的 Execution 内使用，返回原生 Task：

```python
context = copy_context()
context.run(current_domain.set, None)
context.run(bind_reactor, None)
return asyncio.create_task(coro, name=name, context=context)
```

它保留用户 ContextVar，清除观察归属和隐式 Reactor 绑定。外部操作及其正常继承
上下文创建的子任务不参与仿真屏障，也不能直接 await XTrigger。外部代码不应直接
访问 DUT；数据或命令应交回仿真任务，由后者安排采样与驱动。

普通 await task 保持 asyncio 取消传播；需要保护已有任务时可使用 TaskComplete。
外部库自行创建的后台任务仍由该库或调用方关闭。调度归属不授予生命周期所有权，
Execution 不会据此取消用户 TaskGroup 或域外任务。

## 用户使用方式

原有 Execution、Trigger 和 Driver 用法保持不变。无需额外的公共调度类或框架版锁。
下面的协议无关示例使用公共 API，可在已安装项目的环境直接运行：

```python
import asyncio
from xreactor import ClockCycles, Execution, FallingEdge, MemoryBackend


async def queue_example():
    clock = object()
    backend = MemoryBackend(clock)
    writes = []
    try:
        async with Execution(backend):
            queue = asyncio.Queue()

            async def producer():
                await FallingEdge(clock)
                queue.put_nowait(42)

            async def consumer():
                value = await queue.get()
                writes.append((backend.tick, value))

            async with asyncio.TaskGroup() as group:
                group.create_task(producer())
                group.create_task(consumer())
                await ClockCycles(clock, 10)
            assert writes == [(1, 42)]
    finally:
        backend.close()


asyncio.run(queue_example())
```

TaskGroup 是 Python 3.11 标准库提供的并发任务生命周期接口，不是新调度器，也不是
必须使用的 API。正常退出时等待同组任务完成，发生非取消异常时取消并等待其他任务，
通常通过 ExceptionGroup 报错。也可自行 create_task 并负责 await 和取消。

外部库使用示意如下；业务函数和 backend 由调用方提供：

```python
async with Execution(backend) as execution:
    task = execution.external_task(fetch_configuration(), name="configuration")
    configuration = await task
    await FallingEdge(clock)
    apply_configuration(configuration)
```

若配置完成前不能推进时钟，显式暂停：

```python
async with execution.paused():
    configuration = await execution.external_task(fetch_configuration())
```

## 外部边界与诊断

| 操作 | 处理 |
| --- | --- |
| 域内 Task/Lock/Queue/Event/Semaphore | 原生即时回调参与阶段收敛 |
| gather/shield/TaskGroup | 完成传播与取消清理仍由 asyncio 执行 |
| 域内 sleep(0) | 仍有当前阶段工作 |
| 等待未完成的外部 Future | 不阻止时钟 |
| 域外持续就绪任务 | 不计入本 Execution |
| Timer/I/O/call_soon_threadsafe | 宿主实际交付后，产生的域内即时回调才参与收敛 |

只包装 call_soon。call_later(0) 是 wall-clock timer，不等同于阶段内的 sleep(0)。
外部事件尚未交付时，不承诺它优先于当前仿真批次，也不把它映射到确定的仿真 tick。

max_settle_rounds 默认为 100,000，必须为正整数。它限制单次阶段收敛检查交回宿主的
轮数；超过后抛出 SimulationNotSettledError，附带 tick、phase、剩余回调与样例。
预算只能触发失败诊断，不能作为强行推进的依据。域内无限 sleep(0) 循环需要修复或
显式移到域外；纯同步无限循环仍会像普通 asyncio 代码一样阻塞宿主线程。

## 兼容与生命周期

当前适配 asyncio.BaseEventLoop，已验证 CPython 3.12 默认 loop；第三方 loop 需要
独立验证。不支持的 loop 在进入 Execution 时明确报错，不静默降低时序保证。

每个 loop 只安装一个共享观察器。多个 Execution 分别判断收敛，最后一个退出才
恢复原始入口。进入前已有的包装器保留；活跃期间更换 call_soon 会在推进检查时报错，
退出不覆盖宿主的新入口。若宿主新入口仍包含旧观察器，旧观察器关闭后保持透传。

原生 Task factory、exception handler、debug 下的 callback 参数校验保持原有语义。
回调异常仍通过宿主处理；组件的后台失败仍由现有组件传播。Pump 创建失败会恢复
context、观察器和 backend lease；外部取消也执行原有 watcher/ownership 清理。
已入队的用户回调在关闭后仍可运行，不因撤销观察器而被擅自取消。

## 验证与性能

[正式集成回归](../../tests/integration/test_asyncio_observer.py)在 MemoryBackend 和
native XClock 上覆盖原生同步原语、组合等待、同 tick 采样、启动、取消、异常、
外部库子任务隔离、多个 Execution、eager task factory、同步 capture 子任务归属、
入口替换与恢复。旧 Driver 交接回归保留，现使用原生锁和信号量。

历史隔离原型共 30 项通过；实验子类已由公共 Execution 和正式回归替代，避免保留
第二套实现。原型历史数据不代表当前性能；测量结果属于本地产物，不纳入 Git。

当前测量使用[观察器基准](../../benchmarks/benchmark_asyncio_observer.py)，覆盖逐周期
等待、长批次、域外纯让出循环，以及未安装观察器的宿主对照。原生 XClock 不执行
RTL；域外循环的相对开销不能直接解释为 HTTP 应用的减速比例。
正式行为由上述集成回归检查，性能数据通过基准脚本重新测量。
