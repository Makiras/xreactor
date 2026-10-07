# Ready/Valid 驱动

## 为什么需要框架 helper

Cache 验证最初手写了如下时序：

```python
await FallingEdge(clock)
valid.value = 1
await FallingEdge(clock)  # 错误：valid 已经跨过一个 rising
if ready.value:
    await RisingEdge(clock)
valid.value = 0
```

当 `ready=1` 时，这会让同一 payload 跨过两个 accepting rising edge。MMIO 重复请求
的早期误报正是由此产生。这个错误只看 Python 控制流不明显，因此不能要求每个
testbench 重复实现握手循环。

## API

```python
from xreactor import drive_ready_valid


def drive_payload():
    dut.req_bits_addr.Set(addr)
    dut.req_bits_cmd.Set(cmd)


accepted = await drive_ready_valid(
    dut.clock,
    dut.req_valid,
    dut.req_ready,
    drive_payload,
)
print(accepted.tick)
```

2026-09-29 起，框架移除独立的 ReadyValidDriver，暂不提供替代协议类。协议驱动按
需要继承 SyncDriver 或 AsyncDriver，在 `_drive_one()` 内调用此 primitive，并显式
声明 valid/bits 的驱动信号。队列、并发和所有权由通用模板提供，协议函数只负责时序。
Cache 示例的项目级 CacheDriver 已直接继承 SyncDriver，保留原来的握手过程。

`ReadyValid.fire` 是由 bound XData 构成并在 C++ lowering 的 `valid & ready`
CompiledTrigger。通用 Driver 模板对声明的信号做单 driver ownership 检查；
ReadyValidMonitor 用同步 capture 生成不可变 `BundleValue` 和 `Transfer`。

`drive_ready_valid()` 保证：

- payload 和 valid 只在 falling-stable phase 驱动；
- 如果调用时已经处于 falling-stable phase，直接复用当前 phase，不多等一周期；
- 写入后在同一 half-tick 进入 `DRIVE_STABLE`，刷新组合
  逻辑并统一判断 `valid && ready`；
- ready 为低时，valid/payload 跨 rising 保持不变；
- 无论驱动瞬间 ready 是否为高，均用 native `Value(..., sample=DriveStable)` 等待
  所有同阶段驱动完成后的 ready；受阻期间不逐周期恢复
  Python；
- ready 为高时，只跨过一个 accepting rising edge，随后立即撤销 valid；
- picker 的 Rise-mode `valid.Set(1)` 在 DriveStable 前显式提交；接受后立即
  撤销，而不是等下一次上升沿才撤销，否则背靠背请求会错位或重复接受。
  如果 `ready` 依赖 Rise-mode payload，driver 可传 `bits=interface.bits`，由
  helper 在驱动回调返回后统一提交 payload；testcase 不必操作时钟相位或
  picker 写入细节；
- 返回值是该 accepting rising 的 `XEvent`；
- task 被取消或发生异常时，`finally` 仍撤销 valid；
- payload callback 必须同步执行且返回 `None`，async callback 会被明确拒绝。

## 为什么不用 `await (valid & ready)`

当前 XReactor 的 RisingEdge/Condition 语义是 rising-stable，即时序逻辑完成后的稳定
采样。Decoupled handshake 判断的却是 rising edge 之前的 valid/ready。如果 ready
因为该 edge 的状态更新而改变，post-edge condition 不能可靠重建 pre-edge fire。

因此 driver 在 DriveStable phase 观察 ready，再跨过紧邻的 rising edge。
驱动瞬间读取 ready 会遗漏同一 falling phase 中稍后出现的竞争请求。
`ReadyValid.fire` 明确采样于 `DriveStable(clock)`，不能用 post-rising condition
假装等价。未来严格 HDL scheduler region 可以提供更细粒度表达，但不改变这里
“写入完成后、accepting rising 前”的协议含义。

## backend 支持

`SimulationBackend` 提供 `refresh_comb()` 和可选的 `sample_drive_stable()` capability：

- MemoryBackend 是 no-op，因为信号是普通 Python 值；
- XCommClockBackend 调用 XClock `RefreshComb()`。

这只是当前稳定 phase 内的组合传播，不等价于 cocotb `ReadWrite`、`ReadOnly` 或
`NextTimeStep` region。backend 必须显式声明 `drive_stable=True` 才能注册相关 trigger；
未使用它的旧 backend 不会被 Pump 隐式调用。

## 已验证

- MemoryBackend：当前 falling 调用只产生一个 rising sample；
- MemoryBackend：ready 连续为低时 payload 保持；
- cancel：valid 被撤销；
- async drive callback：明确失败；
- 同一 falling 被唤醒的 Python driver 写入，可被 MemoryBackend 和 native backend 的
  ReadyValidMonitor 在 DriveStable 原子捕获；
- 真实 Cache mem-direct：所有普通请求改用该 helper 后，MMIO 一请求对应一次下游
  handshake；Cache early-refill overlap 缺陷仍可复现，说明 helper 没有掩盖 DUT bug。

## 当前边界

当前保留 ReadyValid 结构、Monitor 和底层协议 helper。以下内容留给上层代码或 agent，不作为核心框架
待办：

- 多 producer 仲裁；同一 driven leaf 的 ownership 冲突已明确拒绝；
- 项目专用层次协议类型和 scoreboard；
- timeout 参数；当前可由 `asyncio.timeout` 或组合 Trigger 在上层实现；
- AXI/TileLink/SimpleBus 等多 channel 协议对象。

当前 passive monitor 在 DriveStable sample 内原子捕获 DUT 输出和本次合法 drive
window 的 Python 写入。合法窗口只包括 FallingEdge 恢复后到该 coroutine 下一次 await
之前的同步写操作；它不承诺等待任意外部 asyncio task，也不允许 async encoder/drive
callback 把一次 transaction 拆跨多个调度轮次。

后续协议 Driver 应在通用 Sync/Async 模板之上实现，具体 Cache 字段命名留在项目中。
