# Coverage v2 草稿：程序回收与表达式语义审查

2026-10-09，检查对象：临时 xreactor `draft/coverage-v2-xcomm`、xcomm
`xreactor-coverage-v2`（`83ab5b2`）、picker `xreactor-coverage-v2`
（`60ca8e8`）。本页区分实测现状和后续实现要求。

结论：每个 bin 的完整程序、point 内相同 FSM/Sequence 的共享推进已经实现；
**长 Execution 内程序回收和完整表达式类型仍未实现**。适配新原生分支本身没有补齐它们。
当前优先范围是程序回收与两态表达式的位宽、signed、cast；X/Z 处理暂缓。
本次交付是审查与复现实验，未修改运行时代码、C++ 匹配器或描述协议。

## 可重复实验

在仓库根目录、使用配套 xcomm Python 包运行：

```bash
python -m experiments.coverage_v2_engine_audit --output /tmp/coverage-v2-engine-audit.json
```

脚本复用现有 `ToyResponder`、`ProtocolCoverage`、`Execution` 和 `@xtrigger`。
移除 ToyResponder 的自动响应，使常驻 coverage FSM 保持在等待响应状态，然后连续
等待不同参数的短 trigger。最后送出响应，检查这个 FSM 仍能完成一次。

节点数量通过向当前只追加的表达式 arena 插入常量、比较返回的节点下标测得；
差值排除了探针自身。它不是 RSS 测量，也不是未来节点回收 API 的实现。
这些现状数字用于暴露缺口，不是后续实现应维持的正确性目标；引入回收后需要更新探针。

## 长 Execution：不是 watcher 数量问题

默认 2,000 次等待的实测结果：

| 已完成的不同参数等待 | 剩余 registrations | Python 程序缓存 | 本批新增 C++ 节点 |
| --- | --- | --- | --- |
| 500 | 1 | 500 | 1,500 |
| 1,000 | 1 | 1,000 | 1,500 |
| 1,500 | 1 | 1,500 | 1,500 |
| 2,000 | 1 | 2,000 | 1,500 |

唯一剩余 registration 是 coverage。短等待都已结束，但缓存和节点仍然保留；
本例每个 `signal == constant` 产生三个节点。不能把这个比例推广到宽比较或所有程序。
最后等待中的 coverage FSM 正常完成一次。退出整个 Execution 后，缓存和
registrations 都归零，下一次创建节点的下标是 0。因此问题是 **Execution 内缺少回收**，
不是 Execution 之间完全没有清理。

另外两个失败路径也需要处理：

| 实验 | 当前观察 |
| --- | --- |
| 同一已缓存程序重复等待 64 次 | 新增 0 个节点，现有完整程序缓存确实有效 |
| 部分降低后遇到负数，重复编译失败 64 次 | 缓存没有增加，但原生新增 256 个节点 |
| 容量为 1，保留一个 watcher，再 arm 64 个不同程序 | 全部 arm 失败，缓存仍增加 64 份，原生新增 192 个节点 |

当前路径是：`XCommClockBackend.arm()` 降低并写入 `_program_cache`，随后申请 watcher。
`disarm()` 释放注册及 coverage 状态，不淘汰缓存；`ExprEngine::New*()` 追加节点。
最后只有 `clear_execution_state()` / `close()` 清空 arena。

### 回收必须保留哪些东西

一个正在等待的 FSM 有状态；其编译条件则是可共享的程序。回收程序不能重建整个
engine，也不能为了清空缓存重置常驻 coverage 的 FSM、计数或 overlap attempts。

建议继续使用现有 ExprEngine/DAG 和 PatternMatcher，补生命周期管理，不另造表达式引擎。
需要明确保留的根包括：

- 所有仍 occupied 的 watcher 的表达式、Sequence steps、FSM transition roots。
  已命中但等待交付或 rearm 的 watcher 仍需保留，即使 `armed == false`。
- 所有已 Attach 的 coverage source、group/item gates、abort、普通 bin 条件和时序 bin 程序。
  普通 bin 的条件不在 Python 程序缓存里，仅扫描 `_program_cache` 会误删它们。
- 有界缓存中仍保留的可复用程序；C++ 直接调用者显式保留的表达式根。

对应的资源包括 DAG 节点、宽常量与 mask 的 XData 存储，以及程序持有的 steps/
transitions。DUT 自己的 XData 是借用的绑定，不应由程序回收释放。

### 对 xcomm 的具体要求

这是实现契约草案，下面的能力名称并非已经存在的 API：

1. **编译事务**：开始构造，成功提交，失败回滚。部分降低失败、容量不足和
   AttachCoverage 失败都不能留下无人持有的节点；回滚不能影响其他活动程序。
2. **保留与释放程序根**：watcher、coverage 和可复用缓存分别持有引用。释放一个
   观察者不能释放其他 bin/watcher 共用的程序。
3. **回收不可达表达式及其常量**：复用当前 DAG 的遍历能力。活节点不能因压缩改变
   root；若复用空槽，需要句柄生命周期或 generation 检查，避免旧 root 误指新程序。
   C++ 直接调用者持有的裸 root 也要有明确契约，不能在 Disarm 时悄悄失效。
4. **最小资源查询**：活动节点、已分配槽位、常量存储和已保留程序数，用于验证回收
   是否有效。这不是统一诊断系统，统计和执行热路径应分开。
5. **保留运行状态**：回收不推进/清空 PatternMatcher；不改变 FSM transition 优先级、
   完成计数、terminal 分发、gate/abort 或 overlap 行为。

Python 侧再把无界 dict 改成有界的可复用缓存。活动程序不会因 LRU 淘汰而失效；
不再活动且已被淘汰的程序才可回收。只删 Python 字典不能释放 C++ 节点，
只在 watcher 数量归零时全清也无法服务常驻 coverage。

回收应在编译事务结束后的安全边界、达到一定资源阈值时执行；不要每结束一个等待
就扫描整个 arena。这里不先固定缓存容量和扫描阈值，后续用长 Execution 实验确定。

验收要检查：大量不同参数的等待后资源趋于有界；热点程序仍命中缓存；常驻 FSM
跨回收继续完成；共享程序最后一个引用释放前不会回收；编译/Attach/容量失败不会积累；
反复 bind/unbind、rearm、abort 和 Execution 关闭不会引用失效节点。

## 表达式：目前是 predicate 子集

| 能力/例子 | 当前结果 | 结论 |
| --- | --- | --- |
| `signal == value`、`<` 等无符号比较 | 支持 | 已有能力 |
| 128 位信号直接比较 `1 << 127` | 正常命中 | 直接宽比较支持完整位宽 |
| `signal == -1` | 原生降低明确报错 | 尚无 signed literal / 类型规则 |
| `signal_expr(wide) + 1` | 构造 IR 时 TypeError | Python IR 没有算术，不是 C++ 已自动支持 |
| `a & b`，a=0xf0，b=0x0f | 条件为 true | 当前是逻辑与；并非位与后得到 0 |
| 直接使用 C++ scalar ADD：8 位 255 加 1 | 返回 256 | 当前运算没有 8 位结果截断规则 |
| 直接使用 C++ scalar SHL：1 左移 64 | 返回 1 | 当前移位量按 64 取模，不能直接当成硬件位向量规则 |

后两项是直接探测 ExprEngine 的结果；当前 xreactor IR 并不开放这两个运算，
不能描述成用户现有 coverage 已经通过 `+` 或 `<<` 算错。
同样，unsigned 的 0xff 不是 signed 的 -1：缺少 signed 解释方式属于能力缺失，
不能把现有无符号结果直接判为错误。

### 类型语义应该怎样落到既有 IR

建议规则如下；这是待实现的草案，不声称等同于完整 SystemVerilog 表达式规范。

1. 给现有 IR 补 `Bool` 与 `Bits(width, signed)` 类型。绑定 Bundle 的 XData 提供物理位宽；
   signedness 需要显式声明，不能从一个整数值猜测。无需引入 enum 或新的引脚容器。
2. 普通常量按上下文检查是否可表示；显式宽度常量记录宽度及 signedness。
   负数在有明确 signed 上下文时才可降低。混合 signed/unsigned、改变位宽通过显式
   cast/resize 处理，不静默猜测。
3. 区分重新解释符号、符号/零扩展和截断。例如 8 位 0xff 重新解释为 signed 后是 -1；
   再符号扩展到 16 位是 0xffff，零扩展则是 0x00ff。
4. 算术和位运算有明确结果宽度。例如明确为 8 位的 `255 + 1` 截断为 0；
   想保留进位先把操作数扩展到 9 位。移位量达到/超过宽度时采用已定义的规则，
   不继续复用当前 `amount & 63`。
5. 当前 `&`、`|`、`~` 表示逻辑组合。新位运算可先使用明确的方法入口，例如
   `.bit_and()` / `.bit_not()`，避免读者把已有逻辑组合误读成数据位运算。
   比较返回 Bool；输入数据仍是 Bits。
6. 本轮只定义两态数据运算；X/Z 的传播、有效性刷新与四态逻辑暂不处理，保留现有
   行为。类型和编译层不要把未来四态支持写死为不可扩展的结构，也不额外实现一套未知位系统。
7. 宽度、signedness、literal 类型和显式 cast 都进入 IR 序列化、执行共享 key 和编译缓存
   key。仅按原始整数值合并常量不再足够。

编译过程继续沿用现有入口：

```text
class / @xtrigger 声明
    → 现有 XExpr / SequenceSpec / FsmSpec
    → 绑定既有 Bundle/XData，推导并验证类型
    → 检查原生能力，构造 typed DAG（编译事务）
    → 现有 C++ PatternMatcher 推进，terminal 分发到 bin 计数
```

编译 point 的约束仍是所有 bin 可原生执行；不支持的表达式应在编译/绑定时准确报错，
不能靠 Python predicate 退回路径来宣称“全部 compiled”。Python 参考执行也应共享同一套
类型规则，用差分用例验证 C++。宽比较已存在，不应为了新类型层重写一份。

C++ 若增加存储布局，需要按实际变更调整 native ABI；若改变 coverage descriptor，
另行调整描述协议。当前 native ABI 3 和 coverage protocol 4 是两个独立的版本号。

## 下一轮实现顺序

先实现编译失败回滚和程序回收，保留现有 point 内共享执行；再补类型化 IR、cast、
signed 比较和确定的窄位宽运算，随后扩展宽运算。X/Z 不属于本轮实现范围。
每一步明确支持范围并运行 Python/C++ 差分用例，最后才能称为完整表达式类型语义。

当前本次审查交付：可运行复现实验、资源增长和类型能力审查、原生能力要求及验收条件。
程序回收、typed DAG、signed/cast 和宽算术仍属于后续实现；没有改动 X/Z 处理。
