# 位宽、有符号与四态语义

## 当前 native 契约

标量 hit 的固定布局仍使用 `uint64_t`，但条件求值不再受它限制。宽信号直接使用
`XData` 的完整 `aval/bval` 存储在 C++ 热路径比较，命中后 Python 只在边界读取一次
完整值：

- scalar 按 1 位处理，vector 的 `Value`、`ValueChange` 以及直接比较支持任意 XData 位宽；
- `Value` 和 `@xtrigger` 比较采用无符号语义；
- Python 整数必须非负并适配目标信号位宽；
- 宽信号支持与整数常量或相同位宽信号进行 `== != < <= > >=` 直接比较；
- 宽信号比较可组合进 `& | ~`、Sequence 和 FSM；宽算术及把宽信号直接当布尔值
  仍会明确报错；
- 负常量和尚未定义的 signed cast 在注册/编译阶段报错；
- 不做静默截断、隐式符号扩展或 Python fallback。

未来的 signed API 应通过显式 IR 节点（例如 `Signed(expr, width=...)`）增加，不能
改变现有无符号表达式的含义。

## X/Z

xcomm 的四态编码与 SystemVerilog DPI 一致：`aval` 保存值位，`bval` 保存未知
掩码。每一位 `(aval, bval)` 分别表示 `0=(0,0)`、`1=(1,0)`、`Z=(0,1)`、
`X=(1,1)`。

- `Value(signal, expected)` 只在 signal 全部已知时比较；含 X/Z 不命中。
- 编译 Expr/Sequence/FSM 的某个条件依赖 X/Z 时，本 sample 的条件视为未知，
  不发射也不更新 enter/change 的上一次布尔状态。
- `ValueChange` 比较 `(aval, bval)`，所以进入 X/Z、X 与 Z 互换、离开未知态都
  是变化。
- 已知 ValueChange 的 `event.value` 是 `int`；含未知位时是
  `LogicValue(value=aval, x_mask=bval, width=...)`。
- 宽 ValueChange 在 C++ 比较完整 aval/bval byte vector，不会只比较低 64 位。

这个策略避免把未知态误当作整数 0/1，同时保留 monitor 诊断所需的精确信息。
