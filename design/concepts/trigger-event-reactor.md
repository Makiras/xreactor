# XTrigger、XEvent 与 XReactor

## 对象职责

| 对象 | 含义 | 是否可复用 | 是否有运行状态 |
| --- | --- | --- | --- |
| XTrigger | 等待什么 | 是 | 否，尽量不可变 |
| Registration | 谁正在等待 | 否 | 是 |
| XBackendHit | C++ 命中了什么 | 单次记录 | 否 |
| XEvent | 已经发生了什么 | 只读结果 | 否 |
| XReactor | 注册和分发运行时 | 每 Execution 一个 | 是 |

## await 链路

```text
Task await XTrigger
  -> XReactor 创建 one-shot Registration
  -> 当前 loop.create_future()
  -> 编译或复用 XTriggerIR
  -> XTriggerEngine Arm
  -> BackendHit
  -> XReactor 创建 XEvent
  -> Future.set_result(XEvent)
  -> Task 恢复
```

概念基类：

```python
class XTrigger(Generic[E]):
    def __await__(self):
        return self._wait().__await__()

    async def _wait(self) -> E:
        reg = current_reactor().register(self, mode="oneshot")
        try:
            return await reg.future
        finally:
            reg.cancel()
```

同一个 XTrigger 被多个 task await 时，每次产生独立 Registration。取消其中一个不会修改 Trigger 或取消其他 waiter。

## XEvent

XEvent 至少包含：

- 单调 `event_id`；
- simulation tick、cycle、phase；
- source/domain；
- kind；
- value 或 terminal state；
- 组合事件的 causes；
- 可选 captures/debug metadata。

XEvent 不持有 Future、Registration token、裸 C++ 指针或 PyObject。

## XReactor

负责：

- Registration/Future/subscription 索引；
- Trigger IR 编译缓存；
- watcher 引用计数；
- BackendHit 去重和 XEvent 广播；
- AnyOf/AllOf winner、聚合和原子取消；
- asyncio source adapter；
- cancellation、backpressure、异常和 close。

不负责：

- simulator eval；
- 推进 clock/time；
- 关闭 asyncio loop；
- 扫描 asyncio 私有 task 状态；
- 作为进程全局 singleton。

## pytrigger 与 xtrigger

二者最终都产生 XTrigger，区别只是 evaluator：

```text
@xtrigger
  declaration 执行一次
  -> ExprIR/FsmIR
  -> C++ 每 phase 求值

@pytrigger
  -> PythonPredicateTrigger
  -> 每个指定 sampling phase 返回 Python 调用 predicate
```

`@pytrigger` 不应是自动 fallback。包含 reference model、任意 Python 对象、I/O 或动态副作用时由用户显式选择。

第一版建议只允许同步 `def` 作为 pytrigger predicate。外部异步完成条件使用 AsyncioEventTrigger、QueueTrigger 或 TaskComplete，避免混淆仿真 sampling phase 与 coroutine 自身的挂起点。
