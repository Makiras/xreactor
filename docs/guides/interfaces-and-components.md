# Bundle、Interface、Driver 与 Monitor

## XData

DUT 信号使用 XData。需要检查或取得底层对象时调用：

```python
from xreactor import as_xdata

signal = as_xdata(dut.data)
```

Signal identity、位宽、读写和 native trigger 均使用该 XData 对象。

## Bundle

`Bundle` 把多个 live signal 组织成结构化 interface payload：

```python
from xreactor import Bundle

payload = Bundle(
    opcode=dut.req_opcode,
    address=dut.req_address,
    data=Bundle(lo=dut.req_data_lo, hi=dut.req_data_hi),
)

snapshot = payload.sample()
payload.drive({
    "opcode": 1,
    "address": 0x8000,
    "data": {"lo": 0x1122, "hi": 0x3344},
})
```

`sample()` 返回不可变 `BundleValue`，可直接交给 scoreboard 和 coverage。

## PackedArray 与 PackedLayout

等宽一维总线：

```python
lanes = PackedArray(dut.lanes, element_width=32, count=4)
lanes[2].Set(0x1234)
```

嵌套结构和多维布局：

```python
entry = PackedLayout.struct({
    "valid": PackedLayout.bits(1),
    "tag": PackedLayout.bits(7),
    "payload": PackedLayout.array(2, PackedLayout.bits(32)),
})
entries = PackedView(dut.entries_bus, PackedLayout.array(4, entry))

entries[0].drive({
    "valid": 1,
    "tag": 3,
    "payload": [0x11223344, 0x55667788],
})
```

这些对象都是 live view，不复制 simulator storage，也不引入隐式 sampling phase。

## ReadyValid

```python
from xreactor import Bundle, ReadyValid, Role

producer = ReadyValid(
    clock=dut.clock,
    valid=dut.valid,
    ready=dut.ready,
    bits=Bundle(data=dut.data),
    role=Role.PRODUCER,
    name="request",
)
```

角色是 testbench 的视角：

- `PRODUCER` 驱动 valid/bits，观察 ready；
- `CONSUMER` 驱动 ready，观察 valid/bits；
- `MONITOR` 只观察。

`ReadyValid.fire` 是在 `DriveStable` 采样的 persistent-capable compiled trigger。

## Driver 和 Monitor

```python
async with Execution(backend) as execution:
    monitor = ReadyValidMonitor(producer.monitor_view()).start(execution)
    try:
        async with ReadyValidDriver(producer) as driver:
            accepted = await driver.send({"data": 0xBEEF})
            transfer = await monitor.recv()
            assert transfer.accepted_tick == accepted.tick
            assert transfer.value.data.as_int() == 0xBEEF
    finally:
        await monitor.aclose()
```

Driver 会声明所驱动 signal 的所有权，两个 active driver 驱动同一 signal 时显式报错。
Monitor 在协议接受 phase 捕获 payload，并交付不可变 `Transfer`。

Monitor queue 同样支持 `lossless` 和 `latest`。验证数据路径通常应使用 `lossless`；
`latest` 更适合 UI 和遥测。
