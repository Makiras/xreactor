# 总体架构

## 目标

框架要同时满足三件事：

1. 用户可以自然编写 `await RisingEdge(clk)`、`await condition(dut)`。
2. Expr/FSM 每个 phase 的检查留在 C++，避免 Python polling。
3. pytest、HTTP 和其他 asyncio task 不被仿真框架接管。

## 组件图

```text
用户验证代码
  await / @on / AnyOf / pytest / HTTP
                  |
                  v
Python Trigger API
  XTrigger factories, decorators, composition
                  |
                  v
XReactor
  Registration, Future, subscription, cancellation
        |                         ^
        v                         |
Trigger compiler                  | XBackendHit[]
  XExpr -> ExprIR                 |
  Sequence/FSM -> FsmIR           |
        |                         |
        v                         |
xcomm XTriggerEngine <------------+
  edge/deadline/Cond/Expr/FSM evaluator
                  |
                  v
ClockDomain / XClock / simulator backend

SimulationPump 横向控制 RunUntil、phase barrier、batch 和 yield。
```

## 仓库边界

```text
xcomm
├── XClock / XData / backend adapter
├── XTriggerEngine
├── RawStepHalf / RunUntil
├── XBackendHit / XRunResult
└── 安全 registration handle

new verification framework
├── event.py
├── trigger.py
├── reactor.py
├── execution.py
├── compiler/
├── adapters/
└── methodology/（后续）

picker
├── RTL -> DUT code generation
├── DUT/xclock/signal protocol
└── 跨仓库示例和集成测试
```

依赖方向只能是新框架依赖 xspcomm，生成的 DUT 依赖 xspcomm，用户测试组合二者。xcomm 不依赖 asyncio 或 Python framework。

## 生命周期

`Execution.__aenter__`：

1. 校验 backend capability。
2. 创建 simulation-local XReactor。
3. 创建 XTriggerEngine bridge 和 SimulationPump task。
4. 绑定当前 Reactor 到 contextvars。
5. arm 已声明的 process 和 subscription。

`Execution.__aexit__`：

1. 停止接受新 Registration。
2. 标记并取消框架自己的 waiter/subscription。
3. Disarm backend handles。
4. 等待 Pump 停止。
5. 调用 `backend.clear_execution_state()` 清除本次运行的 trigger、hit 和编译缓存。
6. 恢复 contextvars，不取消外部 asyncio task，不关闭 loop。

`Execution` 不拥有外部传入的 backend，因此绝不调用 `backend.close()`。
backend 通常与 DUT/XClock 同生命周期，由创建它的 pytest fixture 或调用者在最终
退出时关闭。不同 pytest case 可以为同一个 backend 分别创建 `Execution`；每次
退出都会强制清理运行态，但不会复位 DUT，也不会把 XClock tick 归零。

```text
pytest session fixture: create backend
  test_a: Execution -> clear_execution_state
  test_b: Execution -> clear_execution_state
fixture finalizer: backend.close
```

## 依赖倒置

新框架不应硬编码 Picker 的某个生成类。DUT 只需提供最小协议：

- 枚举或解析 signal；
- 取得 clock/domain；
- 读写 signal value；
- 调用 backend RunUntil/Finish；
- 暴露 backend capability。

这样 mock backend、其他生成器和未来 simulator adapter 都能接入。
