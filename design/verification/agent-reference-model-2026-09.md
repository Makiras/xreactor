# Agent 实例与参考模型实施评审

日期：2026-09-29。当前实现以实例封装与环境统一管理为边界，取代此前要求使用
Agent.bind/async context、由用例拆组件连接检查器的草案。旧接口不保留兼容层。

## 当前接口

```python
model = AccumulatorModel()
agent = AccumulatorAgent(dut, response_timeout_cycles=5)
agent.connect(model)
async with Execution(dut.backend, agents=[agent]):
    transfers = [agent.submit(command) for command in commands]
    await agent.finish(timeout_cycles=30, observe_cycles=1)
    results = [await transfer for transfer in transfers]
```

项目 Agent 构造 Driver、Monitor 并声明响应源、clock、预算、FIFO/key/固定延迟规则。
普通用例直接使用 Agent。Execution 可以放进项目环境或 fixture；模型由环境持有，
可连接多个 Agent，Agent 不管理模型 reset/close。

实现入口：[agent.py](../../src/xreactor/agent.py)、
[execution.py](../../src/xreactor/execution.py)。

## 为什么这样实现

1. **把组件封装与运行作用域分开。** Agent 在环境构造时就是实例，connect 只接线。
   Execution 接收 agents，按序启动、逆序检查和清理；Agent 没有公共 bind/context/close。
   同一组件对象不能被多个 Agent 重复注册。
2. **保留 Driver 的执行契约。** SyncDriver.send 仍由调用方 await 驱动，接受事件交给
   私有适配层后继续检查响应，不提供 submit，也不创建驱动 worker。AsyncDriver 继续
   使用现有 worker；submit 返回响应 XTransfer，checked send 提供同一事务的接受视图。
   SingleCycle 驱动时序和 idle 策略无改动。
3. **模型推进与 expected 选择分离。** 私有接受适配层先调用同步 ref.accept(request)，
   再决定使用预测值还是本笔 expected 覆盖值。这样显式 expected 不会跳过状态更新，
   后续请求的预测不会因此错位。未接受撤销不调用模型；乱序响应按独立期望关联。
4. **finish 与关闭分离。** finish 具有预算、封口并检查，不关闭观察生命周期。多个批次
   用 drain 串接；Monitor 始终接收，Execution 退出会继续检查未匹配响应和后台失败。
5. **先完成检查，再释放运行资源。** Agent 先关闭内部 Scoreboard，再关闭 Driver、
   Monitor。Execution 在停止 pump、释放 reactor 和 lease 之前完成组件清理。启动失败
   回收部分组件及此前 Agent；所有退出路径保留原始错误与独立清理错误，避免重复报告。

Scoreboard 的比较、匹配和周期预算实现复用原有机制。manage_monitor=False 由 Agent
内部设置，普通用例不再操作这项接线细节。独立 Scoreboard(expected=...) 仍保留原来的
条件式预测回调语义；Agent 模型连接不再依赖这个回调。

## 验证范围

- Agent 单元测试 9 项：组件顺序、部分启动失败、组合异常、外部取消、宿主任务隔离、
  重复注册/共享组件拒绝、禁止重启、启动中断及错误嵌套不会关闭原实例。
- MemoryBackend/native XClock Agent 集成 34 项：Sync/Async 输入契约、唯一监视生命周期、
  多批次与 finish 后封口、响应独占消费、被动失败、checked send 和未接受撤销、取消
  等待不撤销异步事务、无人等待失败、模型异常去重、expected 覆盖不跳过状态推进、
  同步 send 无新增 worker、同步调用取消、共享模型、同步模型入口校验及绑定失败清理。
- 参考模型示例 7 项：模型独立单测，以及两种 backend 下的状态累加、未接受取消和
  故意错误响应。期望 3/8/15，响应顺序 tag 2/1/3。
- 覆盖率/运行产物组合 13 项：两种 backend 的正常、检查失败、body 异常、外部取消、
  启动/清理失败及导出失败保留原始异常，验证产物与资源释放。
- 原有 Driver、Scoreboard、Monitor、执行调度和协议回归全部运行。

环境：`/tmp/xreactor-verification-venv`；native 模块来自
`/home/xyl/picker/build/dependence/xcomm/python`。

```text
python3 -m pytest -q --require-xspcomm
433 passed in 5.62s

mkdocs build --strict
Documentation built in 0.18 seconds

python3 -m pytest -q examples/transactions/test_pipeline_coverage.py
1 passed; functional point PASS=1

python3 -m examples.transactions.reference_model
python3 -m examples.transactions.reference_model --backend native
两者均返回总和 [3, 8, 15]、响应顺序 [2, 1, 3]、模型终态 15
```

## 明确的边界

- 自动连接仍是可信 Driver 接受事件到单响应；纯被动输入、零/多响应需项目定义关联。
- 共享模型的跨接口同 tick 顺序由规格决定，框架不把 asyncio 顺序解释为硬件仲裁。
- 同步模型返回独立预期快照；异步远程模型、reset/flush 和退休语义由项目适配。
- 并发调用 SyncDriver.send 的任务归调用方，退出环境前必须结束这些调用；未 await 的
  Sync send 不会启动输入。Async 输入由原 Driver 管理。
- checked send 只缩短调用方等待点，响应仍占用 outstanding 容量直到结束；它的接受
  视图只承诺 await/cancel。完整响应状态使用 submit 返回的 XTransfer。
- 不新增调度器、parallel、公开 TaskGroup、广播流或回归管理层。

使用文档：[Agent 与 reference model](../../docs/guides/agents-and-reference-models.md)。
可运行组合：[reference_model.py](../../examples/transactions/reference_model.py)、
[verification_flow.py](../../examples/transactions/verification_flow.py)。
