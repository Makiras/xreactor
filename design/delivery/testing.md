# 测试与性能门槛

## xcomm 正确性

- CondCheck 同 phase 多条件命中；
- ExprCheck 同 phase 多表达式命中；
- FSM state、flag、counter、trigger、Reset、Clear；
- RunUntil 精确停止在目标 half-step；
- BackendHit 批次完整且排序稳定；
- slot generation 拒绝迟到 hit；
- callback exception 在 batch 返回时传播；
- attach/detach 后无悬空调用；
- Disable/Enable 遵守 StopReason 所有权。

## phase 与 await

- RisingEdge/FallingEdge/ClockCycles；
- Falling 后同步写发生在下一 Rising 前；
- Value/Condition 只在指定稳定 sample 判断；
- 注册时已为真也等待下一 sample；
- 同一 occurrence 的 waiter 收到相同 event id；
- 同 phase 不同 occurrence 全部交付；
- 命中 task 在下一 half-step 前获得运行机会。

## Trigger 生命周期

- XTrigger 可被重复和并发 await；
- Registration 不可复用；
- one-shot cancel 清理 backend slot；
- AnyOf winner 原子取消 loser；
- AllOf 正确保存全部 causes；
- Execution close 不投递迟到结果；
- Expr cache/refcount 无增长泄漏。

## FSM

- Sequence 和显式 FSM 等价场景；
- 不同起始 phase 的实例状态隔离；
- one-shot 命中、reset、cancel、timeout；
- persistent FSM 非重叠；
- terminal phase 不作为下一轮 start；
- 下一 sampling phase 正确 reset；
- handler 落后不阻塞 FSM；
- 第一版拒绝 overlapping 配置。

## @on

- 启动时 arm 一次，无 Python re-arm 空窗；
- handler 串行；
- lossless 队列保持顺序；
- queue overflow 明确失败；
- latest-only 只在显式配置时丢旧值；
- handler exception 和 close 行为符合策略。

## asyncio 集成

- pytest-asyncio 已有 loop；
- asyncio.gather(driver, monitor, http_client)；
- aiohttp/FastAPI server/client；
- Event/Queue/Task adapter；
- HTTP 请求期间仿真继续；
- sim.paused 显式冻结；
- close 不取消外部 task；
- close 不 stop/close 宿主 loop；
- owner-thread 模式下 cancel/close 无死锁。

## ready/valid primitive

- 从当前 falling-stable 调用只跨一个 accepting rising；
- 从其他 phase 调用先进入下一 falling-stable；
- ready 为低时 valid/payload 稳定；
- backpressure 等待降低为 native Value，不逐周期唤醒 Python；
- backend 组合刷新后再判断 ready；
- accepting rising 后立即撤销 valid；
- cancel/exception 撤销 valid；
- callback 禁止 await；
- 真实 mem-direct DUT 不产生重复 request。

## backend capability

为 Verilator、VCS、UVS、GSim 分别记录：

- half-step；
- post-refresh stable sample；
- XClock 的 pin update/eval/edge write/eval/refresh stable contract；
- thread ownership；
- checkpoint/waveform/coverage；
- 多实例和可重入性。

不支持的 capability 应在启动时明确报错或降级到声明过的弱语义，不能假装完全等价。

## 性能矩阵

```text
同步 RawStep(N)
当前 Python RunStep(N)
新 RunUntil 无 watcher
RunUntil + Cond
RunUntil + Expr
RunUntil + FSM
XReactor BackendHit -> Future
pytrigger 每 sample
不同 batch / quantum
可选 owner thread
```

指标：

- cycles/s；
- Python/C++ crossing/phase；
- 未命中 phase allocation；
- hit 到 Future 恢复延迟；
- HTTP p50/p99；
- 大量动态 Registration 的内存；
- FSM program/instance 数量；
- cancel/close 延迟。

性能测试必须与 M0 baseline 使用相同 DUT、编译参数和 waveform/coverage 配置。
