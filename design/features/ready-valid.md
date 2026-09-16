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

结构化 API 在这个 primitive 之上：

```python
from xreactor import Bundle, ReadyValid, ReadyValidDriver, Role

request = ReadyValid(
    clock=dut.clock,
    valid=dut.io_in_req_valid,
    ready=dut.io_in_req_ready,
    bits=Bundle(addr=dut.io_in_req_bits_addr, data=dut.io_in_req_bits_data),
    role=Role.PRODUCER,
)
driver = ReadyValidDriver(request)
accepted = await driver.send({"addr": 0x8000_0000, "data": 0x1234})
driver.close()
```

`ReadyValid.fire` 是由 bound XData 构成并在 C++ lowering 的 `valid & ready`
CompiledTrigger。Driver 串行化并发 send，Reactor 对 valid/bits 做单 driver ownership
检查；Monitor 用同步 capture 生成不可变 `BundleValue` 和 `Transfer`。

`drive_ready_valid()` 保证：

- payload 和 valid 只在 falling-stable phase 驱动；
- 如果调用时已经处于 falling-stable phase，直接复用当前 phase，不多等一周期；
- XCommClockBackend 会调用 `RefreshComb()`，再读取当前 phase 的 ready；
- 存在 monitor/fire watcher 时，写入后在同一 half-tick 进入 `DRIVE_STABLE`，刷新组合
  逻辑并统一判断 `valid && ready`；
- ready 为低时，valid/payload 跨 rising 保持不变；
- ready 为低期间使用 native `Value(..., sample=FallingEdge)` 等待，不逐周期恢复
  Python；
- ready 为高时，只跨过一个 accepting rising edge，随后立即撤销 valid；
- 返回值是该 accepting rising 的 `XEvent`；
- task 被取消或发生异常时，`finally` 仍撤销 valid；
- payload callback 必须同步执行且返回 `None`，async callback 会被明确拒绝。

## 为什么不用 `await (valid & ready)`

当前 XReactor 的 RisingEdge/Condition 语义是 rising-stable，即时序逻辑完成后的稳定
采样。Decoupled handshake 判断的却是 rising edge 之前的 valid/ready。如果 ready
因为该 edge 的状态更新而改变，post-edge condition 不能可靠重建 pre-edge fire。

因此 driver 在 falling-stable phase 观察 ready，再跨过紧邻的 rising edge。
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

当前已有 ReadyValid 方法学首版。以下内容刻意留给上层代码或 agent，不作为核心框架
待办：

- 多 producer 仲裁；同一 driven leaf 的 ownership 冲突已明确拒绝；
- 项目专用层次协议类型和 scoreboard；
- timeout 参数；当前可由 `asyncio.timeout` 或组合 Trigger 在上层实现；
- AXI/TileLink/SimpleBus 等多 channel 协议对象。

当前 passive monitor 在 DriveStable sample 内原子捕获 DUT 输出和本次合法 drive
window 的 Python 写入。合法窗口只包括 FallingEdge 恢复后到该 coroutine 下一次 await
之前的同步写操作；它不承诺等待任意外部 asyncio task，也不允许 async encoder/drive
callback 把一次 transaction 拆跨多个调度轮次。

下一步应在这个 primitive 上构建通用 transaction driver/monitor，而不是把具体 Cache
字段命名写入 XReactor 核心。
