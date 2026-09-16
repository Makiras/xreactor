# 行为与限制

## 采样

- `RisingEdge` 和 `FallingEdge` 在稳定的 half-step 返回；
- `Value`、`ValueChange` 和编译条件只在指定的 sample phase 求值；
- 条件从注册后的下一个 sample phase 开始求值；
- 同一 phase 命中的事件由 Backend 批量返回。

## 生命周期

- `await trigger` 创建 one-shot registration；
- 取消等待会注销对应 watcher；
- subscription 在关闭或退出 `Execution` 时注销；
- `Execution` 清理当前测试的 trigger 和编译状态；
- Backend、DUT 状态和仿真时间由调用方管理。

## 数据

- native 条件支持任意位宽无符号 XData；
- 常量必须能由目标信号位宽表示；
- `ValueChange` 比较四态值的 aval/bval；
- 编译表达式暂不提供 signed 运算。

## 当前限制

- 一个 `XCommClockBackend` 对应一个 clock domain；
- Sequence 采用非重叠匹配；
- `@pytrigger` 在每个 sample phase 执行 Python predicate；
- Backend 不能同时用于多个 active `Execution`；
- Backend、XClock 和 DUT signal 不支持跨线程并发访问；
- Interface 需要显式构造或通过 signal tree 绑定；
- coverage JSON 使用 XReactor schema，不是 UCIS。
