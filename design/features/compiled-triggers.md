# 编译式 Trigger

## 目标

`@xtrigger` 为用户提供 Python 声明语法，但不让声明函数进入逐 phase 热路径。它是严格编译器，不是自动 polling 装饰器。

```python
@xtrigger(sample=RisingEdge("clk"))
def handshake(dut):
    return dut.valid & dut.ready & ~dut.flush
```

## 编译流程

```text
调用 handshake(dut)
  -> 用 symbolic DUT proxy 执行声明函数一次
  -> 冻结参数和 signal path
  -> 得到 XExpr 或 XFsmSpec
  -> 生成 ExprIR/FsmIR
  -> 按 DUT schema、IR、sample、参数建立 cache key
  -> XTriggerEngine Arm
```

之后每个 sampling phase 只在 C++ 求值。

## 表达式语法

第一版支持：

- DUT signal attribute；
- 整数和布尔常量；
- `== != < <= > >=`；
- `& | ~` 和明确支持的位运算；
- 括号；
- 少量可直接转换为 IR 的白名单函数。

`Expr.__bool__` 必须抛错并提示使用 `& | ~`，从而拒绝：

- `and/or/not`；
- 链式比较；
- 隐式 truth test；
- 依赖 Python 短路副作用的表达式。

## 严格失败

以下声明不能静默变成 pytrigger：

```python
@xtrigger(sample=RisingEdge("clk"))
def invalid(dut):
    return reference_model.accept(dut.data.value)
```

注册时应报告无法编译的节点、源码位置、原因及建议替代 API。用户明确改写为 `@pytrigger` 才进入 Python sampling。

## pytrigger

```python
@pytrigger(sample=RisingEdge("clk"))
def model_ready(dut):
    return reference_model.accept(dut.data.value)
```

pytrigger 仍返回 XTrigger，使用相同 XReactor、XEvent、取消、超时和组合逻辑。区别是每次 sampling phase 必须回到 Python 调用同步 predicate，因此它会限制 RunUntil batch。

外部异步等待不使用 async pytrigger。应使用 AsyncioEventTrigger、QueueTrigger 或 TaskComplete。

## 缓存

可缓存：

- symbolic trace 结果；
- ExprIR/FsmIR；
- backend 编译程序；
- 无状态 evaluator 的公共节点。

不可跨不兼容上下文共享：

- 不同 DUT schema；
- 不同 signal binding；
- 不同 sample/domain；
- 不同冻结参数；
- 不同起始 phase 的 FSM 运行状态。

缓存必须有引用计数或明确生命周期，避免当前 ExprEngine 动态节点只增不减。
