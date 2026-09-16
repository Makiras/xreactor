# xcomm 现状核对

本页只记录从当前源码确认的能力和缺口，避免新框架重复实现已有机制。

## XClock

相关文件：

- `dependence/xcomm/include/xspcomm/xclock.h`
- `dependence/xcomm/src/xclock.cpp`
- `dependence/xcomm/swig/python/xcomm.py`

已确认：

- `Step(s)` 每个完整 cycle 连续执行 falling/rising 两个 half；
- 每个 half 包含 pin、eval、port、第二次 eval、refresh；
- StepRis/StepFal callback 点位于 refresh 之后；
- Disable 在下一轮完整 cycle 入口被检查，两个 half 之间不会再次检查；
- Python `RawStep` 是原始 C++ Step 的别名；
- Python 包装 `Step` 逐 cycle 设置/清除 `_step_event`；
- RawStep 不会触发该 Python event 路径。

结论：精确 FallingEdge 屏障需要公开 half-step/next-phase，不能只靠 callback 后 Disable。

## ComUseCondCheck

已确认：

- 支持 EQ/NE/GT/GE/LT/LE；
- 支持 XData/XData、地址比较及 valid gating；
- 能记录多个命名条件；
- Call 会扫描同 phase 全部条件；
- 命中后 Disable 绑定 clocks；
- 构造时绑定 clock 不等于安装 callback。

它适合成为简单 Cond evaluator 的实现来源。

## ComUseExprCheck

已确认：

- 有 ExprEngine、多个 root、字符串表达式和 cycle 状态；
- 命中后 Disable 绑定 clocks；
- 原实现 `Call()` 在第一个命中后 `break`，M1 切片已移除该提前退出并增加
  同 phase 多表达式回归测试；
- `RemoveExpr` 不等价于回收所有已创建 ExprEngine 节点。

动态 arm/disarm 仍需建立 Expr program 缓存或节点回收策略。

## ComUseFsmTrigger

已确认：

- state/start state；
- 条件转移、goto、trigger；
- flag/counter action；
- ExprEngine 条件；
- Reset/Clear；
- IsTriggered、当前状态和终态查询；
- trigger 后 Disable 绑定 clocks。

复杂状态条件可以直接利用它，不应退回 Python。

## XData::OnChange

已存在 on-change callback 和 X/Z 信息，可用于 ValueChange。其 callback phase 和安全 attach/detach 仍需统一到 post-refresh TriggerEngine hook。

## 生命周期风险

当前 callback 使用裸 `void*/CSelf()`。销毁 checker/FSM 前必须 detach。新 ABI 应使用 `slot + generation` handle，不把裸指针或字符串 key 暴露到 Python。
