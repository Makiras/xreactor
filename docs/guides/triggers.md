# Trigger

Trigger 描述一个等待条件。`await trigger` 返回对应的 `XEvent`。

## 时钟

```python
await FallingEdge(dut.clock)
await RisingEdge(dut.clock)
await DriveStable(dut.clock)
await ClockCycles(dut.clock, 10)
```

`FallingEdge` 和 `RisingEdge` 在稳定的 half-step 返回。常见驱动方式是在下降沿写入，
随后等待上升沿采样：

```python
await FallingEdge(dut.clock)
dut.valid.Set(1)
dut.data.Set(payload)
await RisingEdge(dut.clock)
```

## 信号条件

```python
await Value(dut.ready, 1, sample=RisingEdge(dut.clock))
await ValueChange(dut.response, sample=RisingEdge(dut.clock))
```

省略 `sample=` 时使用 `Execution(default_sample=...)`。条件从注册后的下一个采样点开始
求值。

`Value` 支持三种命中模式：

| `mode` | 命中条件 |
| --- | --- |
| `"enter"` | 条件由 false 变为 true，默认值 |
| `"each_sample"` | 条件为 true 的每个采样点 |
| `"change"` | 条件的布尔结果发生变化 |

`Value` 和比较表达式支持任意位宽无符号 XData。`ValueChange` 比较完整的 aval/bval。

## 超时

```python
await SimTimeout(100, clock=dut.clock)
await WallTimeout(0.5)
```

`SimTimeout` 按仿真周期计时；`WallTimeout` 按秒计时。

## asyncio 事件

```python
await AsyncioEventTrigger(stop_event)
item = (await QueueTrigger(queue)).value
result = (await TaskComplete(task)).value
```

## 组合

```python
event = await AnyOf(
    Value(dut.done, 1, sample=RisingEdge(dut.clock)),
    AsyncioEventTrigger(stop_event),
    WallTimeout(1.0),
)

event = await AllOf(
    ClockCycles(dut.clock, 10),
    TaskComplete(reference_task),
)
```

`AnyOf` 返回最先完成的事件，并取消其余等待。`AllOf` 等待全部事件，子事件保存在
`event.causes` 中。
