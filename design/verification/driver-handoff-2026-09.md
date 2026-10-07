# Driver 阶段交接修复

日期：2026-09-29。以下保留第一次 Driver 交接修复的历史记录。

该机制已由[通用 asyncio 调度观察器](asyncio-observer-2026-09.md)替代；
DriverPermit/HandoffBarrier 已删除，现有 Driver 使用原生锁和信号量。

## 根因与回归

asyncio.Lock.release 唤醒任务时，只把它加入 event loop 就绪队列。旧 Pump 在广播
事件后只 yield 一轮；本轮被唤醒的 Driver 再释放阶段锁时，下一位等待者可能排在 Pump
之后。Pump 随即执行长批次，导致等待者在更晚的仿真时间才开始驱动。

先删除示例的手动 yield，再运行已有 pipeline 采样回归：MemoryBackend/native，
SyncDriver/AsyncDriver 的 max_active=2 共四项失败，接受 tick 从期望 8/14/20 退化
为 8/16/24。max_active=1 的四项仍通过。

## 实现边界

- 私有 DriverPermit 管理 FIFO 资源锁与并发名额，未争用时直接取得，不创建 task/Future。
- 授予排队等待者之前登记 HandoffBarrier token；等待者 acquire 恢复时同步确认。
  其调用方随即执行到下一次实际挂起，期间 event loop 不切换。
- Pump 在 backend 推进及 DriveStable 采样前等待这些交接；级联交接继续登记 token，
  不靠固定增加 yield 次数，也不访问 asyncio 的私有 task/ready 队列。
- 取消未授予等待者只移除队列项；取消已授予者回收名额并交给下一位，再确认原 token。
  普通异常通过 context manager 释放。Execution 退出解除屏障，不接管宿主外部任务。
- 原生 asyncio.Lock、任意 create_task 和外部 await 不在保证范围。使用 resource_lock
  的直接 acquire/async with 路径可获得交接保证；额外包裹协程会引入独立调度边界。
- 修复 paused() 在进入阶段被取消时未回收 pause-depth 的清理路径。

没有修改具体 Driver 协议时序、idle 或 Scoreboard 匹配；没有新增公开调度类。
resource_lock 保留 acquire/release/locked/async with 接口，但返回仿真感知对象，
不再声明其类型为 asyncio.Lock。

## 验证

新增 `tests/integration/test_driver_handoffs.py`，同样使用 MemoryBackend/native XClock：
八级锁交接必须全部保持在 tick 1，且 DriveStable 第一次 capture 读到最终写入；
并发名额交接不能被独立的长时钟等待越过；排队和已授予时取消、公平性、持锁异常、
外部阻塞/持续就绪 task 与暂停进入取消均有检查。

已有 pipeline 回归在完全移除手动 yield 后保持原有实际采样和 8/14/20 接受 tick。
最终验证：

```text
python3 -m pytest -q tests/integration/test_driver_handoffs.py --require-xspcomm
18 passed in 0.05s

python3 -m pytest -q --require-xspcomm
221 passed in 0.91s

mkdocs build --strict
成功，无链接诊断
```

流水示例的六个成功入口分别在 memory/native 执行通过，连续输入仍在 tick 2/4/6
接受，阶段重叠仍在 tick 8/14/20 接受。改动与新增文件格式检查通过。

## 性能检查

同机、同 native binding、Python 3.12.3，修复前后分别运行：

```bash
python3 benchmarks/benchmark_runtime.py --ticks 20000 --repeats 7 --json
python3 benchmarks/benchmark_driver_handoffs.py --requests 256 --repeats 7
```

逐周期 await 的中位耗时从 559.326 ms 到 558.656 ms（-0.1%）；其他 runtime 子项
波动在约 -1.8%～+1.5%。本次微基准没有观察到明显回退，不把波动解释为性能提升。

新增 Driver 基准：无争用约 150.2 µs/request，含争用约 171.9 µs/request。两者工作
模式不同，不能将其比值当作本次修改开销；最终 tick 分别为 2048 和 1538，证明争用
模式确实发生阶段重叠。后续可用同一基准进行版本对比。

原始样本和参数保存在 测量记录（本地产物：`driver-handoff-measurements-2026-09-29.json`）。这是
无 RTL 的时钟微基准，不代表实际 DUT 吞吐。
