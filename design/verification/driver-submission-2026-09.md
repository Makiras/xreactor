# Driver 提交接口评审与验证

日期：2026-09-29。目标是让日常流水输入由 Driver 管理，测试无需创建并发任务。

## 最终接口

AsyncDriver 保留两个提交入口：

| 入口 | 调用时 | 完成条件 | await 结果 |
| --- | --- | --- | --- |
| send(transaction) | 立即提交输入，返回 XTransfer | _drive_one 返回接受事件 | 接受事件 XEvent |
| submit(request) | 立即提交请求，返回 XTransfer | 响应关联方显式完成 | 响应值 |

send 句柄在接受时自动完成并释放容量，不进入 recv_accepted 流；不需要伪造响应。
可以继续 await driver.send(request)，也可以先保存多个 send 返回的句柄，再分别等待。
相同句柄重复 await 不会再次发射。取消等待者不取消输入；显式 cancel 只撤销未接受输入。
正常退出 Driver 不隐式排空，取消未接受输入并回收任务；未被观察的后台失败从退出传播。

内部复用原有 accept_only 路径、容量表和串行 worker。send/submit 共用并发限制与资源锁，
具体驱动函数、接受点、单周期 idle 和响应关联规则不变。没有 parallel 接口或公共任务组。

## 各类 Driver 的边界与迁移

Driver 基类的签名明确为 send -> Awaitable[XEvent]，允许具体实现返回 coroutine
或已提交句柄，不添加后台队列要求。SyncDriver 的 send 仍是原先的 async 函数。
SignalDriver 仍负责 ownership；具体协议 Driver 保持自身实现与完成条件。
AsyncSingleCycleDriver 继承新的提交入口，单周期驱动与 idle 策略保持原样。

AsyncDriver.send 由 async def 改为返回句柄的 def，这是实际的调用语义变化：

- 只调用而不 await，现在也会提交；需要延后发送时先保存 request。
- Driver 未启动、已失败、容量不足在调用处立即报错。
- 返回对象是 XTransfer，不能交给要求 coroutine 的 create_task/TaskGroup.create_task；
  保存句柄并按需要 await 即可，不再为输入启动用户任务。
- 其他 Driver 不能仅凭同名 send 推断为调用即提交，必须遵循具体类型的契约。

日常流水示例移除用户 TaskGroup，改为 Driver.send 批量提交；原 direct-overlap CLI
改为逐笔 await send 的对照场景。SyncDriver 的直接并发调用只保留在底层兼容回归中，
避免删除已有能力而漏掉调度退化。资源锁的公共接口尚未调整，分析见
[资源占用讨论稿](../architecture/driver-resources.md)。

## 回归证据

在公共非阻塞输入入口尚不存在时，先增加接受即完成与容量复用用例，memory/native
共六项失败。最终 send 接口覆盖相同场景，并增加调用即提交和多种退出方式的验证。
相对观察器完成后的 267 项基线，本次增加 44 项，memory/native 各 22 项：

- 串行与阶段重叠的实际信号采样，逐笔 await 与先提交后等待的对照。
- 接受即完成、接受事件与完成事件同一对象、不产生待响应残留。
- 多批次复用、容量即时报错和接受后释放，连续接受没有额外空拍。
- send 与 submit 混用时，响应接受流只包含 submit 的请求。
- 提交前后取消、锁与队列清理；取消等待者仍可随后等待输入完成。
- 无人等待的驱动失败通过 context 报告；已观察的同一失败不重复报告。
- 无等待者也会发射、重复等待不重发，覆盖串行、重叠和 SingleCycle 模板。
- 正常、异常和外部取消退出均释放任务、信号 ownership、资源锁及 backend watcher。

最终在本地验证环境运行：

```text
python3 -m pytest -q --require-xspcomm
311 passed in 1.21s

mkdocs build --strict
通过
```

两种 backend 的六个成功 CLI 场景通过，独立 Scoreboard 示例 checked=8、passed=8、
completed=8。原有协议、SyncDriver、SingleCycle 和 asyncio 集成测试均包含在全量回归中。
git diff --check 通过。

| 场景 | 接受 tick |
| --- | --- |
| 单周期连续输入 | 2、4、6 |
| 两阶段，max_active=1，先提交后等待 | 8、16、24 |
| 两阶段，max_active=2，先提交后等待 | 8、14、20 |
| 两阶段，max_active=2，逐笔 await send | 8、16、24 |

环境为 Python 3.12.3，native 使用本地 xspcomm 无 RTL XClock。测试证明提交与采样
语义，不据此推导真实 DUT 吞吐；本次没有重新测量调度器性能。
