# asyncio 调度观察器实施记录

日期：2026-09-29。基于当前工作树，执行已接受的[观察器设计](../architecture/asyncio-observer.md)。

## 修复范围

原来的 Driver 专用交接只覆盖 resource_lock/max_active，不能覆盖普通 Queue、Event、
新任务启动和 gather/shield 完成传播。现由 Execution 观察原生即时回调，阶段工作
处理完才推进时钟或采样。asyncio 仍是唯一 Python 调度器，没有另一套就绪执行队列。

先将三个反例移为正式回归，旧实现在 memory/native 共六项失败：

- 八级锁/Queue 加组合等待的记录落到 tick 3/5/7/9/13，未保持 tick 1。
- 新任务执行 32 次 sleep(0) 后才开始，仿真已经到 tick 200，而不是 tick 0。
- 32 层原生回调链在长时钟等待结束时仍未交付最后一项。

接入后这些反例通过。DriverPermit/HandoffBarrier 已移除，资源锁恢复原生 Lock，
并发名额使用原生 Semaphore；异步串行 worker 仍复用。未调整具体 Driver 的
ready/valid、reset/flush、接受周期、idle 或 Scoreboard 响应关联。

## 接入细节

- 共享 loop 观察器按目标 context 识别 Execution，返回原生 Handle；不替换 Task factory。
- 回调取消通过登记表中的 Handle.cancelled() 清理；执行异常仍归宿主 exception handler。
- Pump 自身不计入屏障。backend 同步回调和 capture 在 Execution context 中运行，
  因此它们创建的子任务也能在当前阶段执行。
- external_task 返回用户负责清理的原生 Task，清除域标记和 Reactor 绑定，保留用户 ContextVar。
- max_settle_rounds 默认 100,000；不收敛时报 SimulationNotSettledError，附 tick/phase/回调信息。
- 最后一个 Execution 退出时恢复入口；进入失败、取消和正常退出均释放 context 与 backend lease。
- 活跃期间若宿主替换 call_soon，推进检查明确失败，退出不覆盖宿主的新入口。
- 实验子类已删除，文档和示例使用公共 Execution；TaskGroup 只是可选的标准库生命周期接口。

## 验证

新增正式集成回归 46 项，memory/native 各 23 项。覆盖原生锁/Queue、组合等待、
DriveStable 采样、新任务启动、取消及 finally、外部任务及子任务隔离、多个 Execution、
已有包装器、入口替换、Task factory 创建失败、eager factory、debug 参数校验、
原生 exception handler、同步 capture 子任务，以及 TaskGroup 异常清理。

```text
python3 -m pytest -q --require-xspcomm
267 passed in 1.14s

python3 -m pytest -q examples/getting_started/test_first.py
1 passed in 0.01s
```

memory/native 的流水示例六个成功入口均通过：连续接受 tick 2/4/6，重叠输入接受
8/14/20，串行输入 8/16/24，乱序响应顺序 3/2/1。独立 Scoreboard 示例完成八项检查。
文档公共 Queue 示例也直接执行通过；`mkdocs build --strict` 和 `git diff --check`
均通过。native binding 自检与独立 subscription 示例通过。

当前实测环境是 Python 3.12.3 的默认 event loop。CI 保留 Python 3.11/3.12 矩阵，
本地没有据此声称已运行其他版本或任意第三方 loop。

## 性能与实际限制

[基准脚本](../../benchmarks/benchmark_asyncio_observer.py)使用 native 无 RTL XClock，
各项预热后测量七次，正反顺序交替。域外任务用 public external_task 创建；宿主对照
没有安装 Execution 观察器。全部样本（本地产物：`asyncio-observer-measurements-2026-09-29.json`）。

| 场景 | 最终实现中位数 |
| --- | --- |
| 10,000 次逐周期等待 | 648.083 ms |
| 一次等待 100,000 周期 | 80.721 ms |
| 域外 100,000 次 sleep(0)，有 Execution | 313.619 ms |
| 同样宿主任务，没有 Execution | 254.493 ms |

域外纯让出循环的额外耗时为 23.2%，每次约 0.59 µs。直接转发常见零参数回调，并
优化域内零/单参数转发后，较本次初版测得的约 34.7% 开销有所降低。两组原始数据
均保留；该比例是调度密集微基准，不代表 HTTP 应用或真实 RTL 的吞吐变化。

历史原型记录的旧 Execution 逐周期基线为 589.288 ms，与当前测量不是同轮交替
对照，不将二者差值作为严格版本性能结论。当前数据可作为后续同配置回归基线。

观察器对共享调度入口有真实成本。当前支持 BaseEventLoop 接入；跨线程/Timer 的
事件以宿主实际交付为界，不提供固定仿真 tick 映射，也不拦截尚未交付的外部通知。
