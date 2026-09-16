# @on 与持久订阅

## 关系

`@on` 不是 Trigger，也不建立新事件源：

```text
XTrigger               描述匹配什么
XSubscriptionSpec      描述如何长期消费
Registration           当前绑定和运行状态
XEvent                 每次交付的数据
```

`await trigger` 创建 one-shot Registration；`@on(trigger)` 在 Execution 启动时创建 persistent Registration。二者共享 Trigger IR、编译缓存和可共享的 backend watcher。

## 为什么需要队列

handler 是 async function，可能在处理期间 await。如果采用“handler 返回后重新 await trigger”，中间会出现 re-arm 空窗并丢失事件。

正确模型：

```text
backend hit
  -> XReactor 立即入 subscription queue
  -> FSM/Trigger 继续运行
  -> 独立 handler task 串行消费
```

## 默认交付策略

首版已冻结：

- handler 默认串行；
- 队列有界，默认容量 64；
- 默认 lossless；
- 队列满时抛出 `SubscriptionOverflowError` 并停止相关 Execution；
- UI/遥测可显式选择 latest-only；
- 不提供静默 drop-oldest/drop-newest 默认值。

Trigger 决定何时产生事件，例如 `enter`、`each_sample`、`change`；Subscription 决定事件如何交付。两者不能混在同一个参数中。

## FSM subscription

persistent FSM 默认非重叠。命中后不等待 handler：

```text
terminal hit
  -> enqueue FsmEvent
  -> 当前 phase 结束
  -> FSM reset
  -> 下一 sampling phase 再匹配
```

如果 handler 落后，事件保留在 lossless 队列中；这不会创建 overlapping FSM。

## 生命周期

- Execution start：bind descriptor，创建 queue/task，Arm Registration。
- normal close：停止新投递并立即 cancel 框架创建的 handler task，不隐式等待
  用户 handler drain；后续若增加 drain 必须是显式策略。
- overflow：保留诊断上下文，停止推进并传播异常。
- handler exception：默认使 subscription 和 Execution failed；可后续增加隔离策略。
- cancellation：Disarm 后再销毁 C++ 状态。

handler exception 首版使整个 Execution 失败，不做局部隔离。decorator 使用
`spec.bind(...)` 后再由 `sim.subscribe(spec)` 显式启动；实例方法和参数化 factory
沿用这一条路径，不提供隐藏的自动启动时机。
