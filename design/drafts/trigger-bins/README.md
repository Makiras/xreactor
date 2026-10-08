# 临时 coverage-v2 分支的下一步

状态：接口与实施草稿，2026-10-08。只修改 `/tmp/xreactor-coverage-v2-ob2uhbua/xreactor`，运行示例仍见[已实现指南](../../../docs/guides/coverage-v2.md)。本文细化[共享时序设计](../coverage-v2-patterns.md)，不表示新引擎已经实现。

**把 xtrigger 定义直接当成 bin 的匹配定义。Point 管 bins，Group 管 points；C++ 继续匹配和计数。** 下一轮用一个短协议示例贯穿接口、类型检查、原生编译和资源释放，先完成这条闭环。

## 用户最终写什么

[example.py](example.py) 是完整的候选接口例子，核心部分如下：

```python
@xtrigger()
def roundtrip(pins: ProtocolPins, *, maximum: int = 4) -> SequenceSpec:
    return Sequence(
        Wait(pins.request.valid & pins.request.ready),
        Within(1, maximum, pins.response.valid & pins.response.ready),
    )


class RoundTripPoint(TemporalCoverPoint[ProtocolPins]):
    within_four_cycles = roundtrip
    repeated = Bin.pattern(roundtrip, at_least=10)
    within_eight_cycles = roundtrip.with_args(maximum=8)


@covergroup(schema_id="protocol.patterns")
class ProtocolCoverage(SignalCoverGroup[ProtocolPins]):
    roundtrip = RoundTripPoint()


coverage = ProtocolCoverage(instance="dut.protocol")
coverage.bind(pins=pins, sample=RisingEdge(pins.clock), strategy="native")
count = coverage.roundtrip.count(RoundTripPoint.within_four_cycles)
```

类属性名就是报告里的 point/bin 名称。内部引用使用对象、函数参数和引脚属性路径；`schema_id`、`instance` 等外部标识仍用字符串。无需 Enum，也不新增一套 Sequence 或循环 await 代码。

这个 roundtrip 只适合最多一笔未完成请求；并发请求的身份关联仍单独讨论。当前示例的 typed signal leaves 是待实现的引脚视图，不等于现有只提供 W/U/Set 的 Pin 协议。

候选接线方式是在搭建引脚组时一次性包装真实信号，例如 `BoolSignal(dut.req_valid)`、`UIntSignal(dut.req_opcode)`；视图同时保留原生句柄和表达式类型，不在每拍创建。绑定检查 Bool 的物理宽度为 1、UInt 的真实位宽和原生来源。优先从后端元数据取得稳定端口身份，缺失时提供 source_id 或显式 observer contract，不能用逻辑字段路径冒充真实接线身份。这些外部标识与已实现绑定遵循相同原则。

## 把容易含糊的规则先确定

| 问题 | 本轮建议 |
| --- | --- |
| `roundtrip` 是什么 | 不可变的 `TriggerDefinition[P, Args]`，保存声明函数、输入根类型、参数签名和显式策略；不 arm |
| `roundtrip(pins, maximum=8)` | 返回已有语义的绑定 trigger；await 时才注册。静态返回类型是 CompiledTrigger，而非 SequenceSpec |
| `roundtrip.with_args(maximum=8)` | 检查并冻结所有非引脚参数，返回尚未绑定引脚的 TriggerPattern[P]；不会创建运行状态 |
| 直接引用带参数的定义 | 仅当所需参数都有默认值时合法；编译时冻结默认值。缺少必需参数就报错，要求先 with_args |
| `Bin.pattern(...)` | 创建独立、不可变的覆盖配置，保留原 matcher；附加阈值、kind、终态选择和有界重叠配置 |
| Python 类自动绑定函数 | TriggerDefinition 是可调用对象，不实现普通函数的 `__get__`；读 Point.read 不注入 self |
| 引脚组采样 | 由 coverage.bind 的实际时钟/phase 指定。定义已指定 sample 时，解析后必须与其一致，否则绑定失败 |
| 其他采样入口 | TriggerPattern.bind 可以显式指定 sample；普通 await 路径继续按现有规则使用 Execution 的默认 sample |
| 表达式事件模式 | EACH_SAMPLE/ENTER/CHANGE 保留原定义；read_accepted 宜显式 EACH_SAMPLE，连续握手每拍都算一次 |
| 时序观察模式 | 默认 non-overlap、max_active=1；overlap 要显式提供有界容量，沿用现有重新启动顺序 |
| 计数单位 | 一个完成匹配加 1，同拍两个完成加 2；观察采样次数单列 observations |
| Cross | 初版拒绝任何包含 TemporalCoverPoint 的 Cross；值 sample/已完成事务的 Cross 沿用现有路径 |

`with_args` 的参数仍由 ParamSpec 保留名称和类型；最大窗口不是字符串配置。传参范围、容量和终态归属由编译器进一步检查。列表、字典等可变参数先拒绝，接受可稳定序列化的不可变参数。声明函数在定义编译时生成并冻结 IR，绑定阶段不能因外部变量变化重新执行出另一份程序。

Bin.pattern 的 max_active 未传时保留为 None：non-overlap 在编译时解析为 1，overlap 则报缺少显式容量，避免默认值掩盖漏配。

采样来源按解析后的原生时钟身份和 phase 比较，而不是比较 Python wrapper 对象地址。首版一个 SignalCoverGroup 使用一个采样域；不同域拆成不同 group。不把 group 的 trigger 完成事件当作所有 bins 的默认多周期起点。

## 复用和继承怎样保持可查询

同一个定义可以出现在不同 points 或 coverage 实例中，计数、历史、取消互相独立。共享定义不写 owner 或 bin 名称；bin 身份由冻结的 group 槽位、point 和属性名确定。

同一个 point 内以下声明必须拒绝：

```python
class AmbiguousPoint(TemporalCoverPoint[ProtocolPins]):
    a = roundtrip
    b = roundtrip
```

因为 `AmbiguousPoint.a is AmbiguousPoint.b`，count(Point.a) 无法知道想查哪一个。需要两份计数时采用不同配置对象：

```python
class ExplicitPoint(TemporalCoverPoint[ProtocolPins]):
    once = roundtrip
    ten = Bin.pattern(roundtrip, at_least=10)
```

同一个 Bin.pattern 返回对象在一个 point 内同样不能重复命名。不要为了绕开歧义改写共享 trigger，或用元类把类属性偷偷变成另一种静态类型。

Point 子类继续增加或覆盖同名 bin，Group 子类继续以 Point 子类替换槽位，沿用当前 MRO、冻结和冲突检查。覆盖结果不修改基类。若子类把直接 trigger 改成 Bin.pattern，Python 静态工具会认为属性类型发生变化；在可替换槽位标一次公共类型即可：

```python
class BasePoint(TemporalCoverPoint[ProtocolPins]):
    done: PatternBin[ProtocolPins] = roundtrip


class RepeatedPoint(BasePoint):
    done: PatternBin[ProtocolPins] = Bin.pattern(roundtrip, at_least=10)
```

普通新增 bins 不需要这层注解。完整继承正例已列入类型草稿。类体内放错输入根类型、多个父类冲突、重复引用等仍需要定义编译检查；Python 的普通泛型基类无法自动约束所有子类属性，不能只靠类型检查器承诺全部安全。

## FSM 的 bin 如何选终态

终态使用具名对象引用，不要求 Enum：

```python
class RequestResult:
    success = Terminal()
    timeout = Terminal()


# FSM 状态中的 .trigger(RequestResult.success) 引用同一对象。
class ResultPoint(TemporalCoverPoint[ProtocolPins]):
    success = Bin.pattern(request_fsm, terminals=(RequestResult.success,))
    timeout = Bin.pattern(request_fsm, terminals=(RequestResult.timeout,))
```

需要扩展现有 FsmTransitionSpec/State.trigger，让 Terminal 对象可以降低为稳定 ID。编译器检查终态确实存在于该程序；两个 bins 各自观察完整 FSM，并仅累计所选终态。终态过滤不改变 FSM 运行：到达未选终态也结束本次匹配。

只有一个终态的 FSM 可以直接作为 bin；多个终态必须显式选择，或传 `terminals=ALL_TERMINALS`。Expr/Sequence 禁止终态选项。现有 FSM 状态字符串接口暂时保留，本轮先解决 bin 的完整程序与终态选择。

## 编译分两步，运行仍在 C++

```text
Python 类、继承、直接 trigger 引用
  -> 声明编译：冻结参数、规范化 Expr/Sequence/FSM、bin 元数据、稳定 schema
  -> 引脚绑定：解析实际信号、宽度/符号、采样域、能力和原生程序
  -> Execution 启动：注册每个 bin 的独立匹配状态和 C++ 计数器
  -> C++ 采样：推进程序 -> 完成数量/终态 -> 覆盖策略 -> 提交计数
  -> sync/退出：批量快照、保留报告、释放状态及最后一份程序引用
```

`compile()` 展示尚未绑定的逻辑定义；实际位宽来自引脚或显式类型，只有 bind 成功才算原生可执行计划。宽度未确定时不能提前声称类型正确或 native 可执行。引擎能力缺失时严格 native 在注册前失败；批量注册中途失败需要回滚已经创建的资源。

一个 pattern point 是事件集合，不携带伪造的 bool XData。XCoverageItem 需要显式 value/pattern 类别；XCoverageBin 需要完整程序种类、观察选项、终态选择及私有状态。normal pattern bins 独立计数；ignore/illegal 只作用于本 bin 的完成，不能抑制另一个独立 pattern。值分类点原有的 ignore/illegal/default 规则保持在值采样路径，pattern 点不支持含糊的 default bin。

C++ 继续复用 AdvanceSequence/AdvanceFsm；Expr 的事件模式也统一处理。每次完成数量参与计数提交，不能用 `completions != 0` 压成一次。计数溢出、illegal 策略及快照一致性仍由引擎保证。coverage 命中不产生普通通知，不逐次返回 Python；Python fallback 也消费相同规范化程序。

## 资源回收只做必要的改动

当前 ExprEngine 节点和 backend._program_cache 主要在 Execution 结束才清理。下一步采用程序所有权/lease：一个原生程序拥有其表达式节点和描述符，watcher/bin 引用它。开始先以整份程序为回收单位；不要求跨不同程序合并任意子表达式，也不要求全面重写公开的 Observer API。

- 相同程序、相同绑定可以复用；不同 watcher/bin 的 MatchState 独立。取消 A 后 B 继续运行，最后一个使用者释放时回收程序。
- Python 编译缓存不能无限强持有原生程序；原生程序失去最后使用者时移除对应缓存项。逻辑 IR/schema 不持有原生信号或 arena。
- clear_history/reset 只清相应状态或计数，继续持有仍在运行的程序。关闭时先取最终快照，再释放 native 资源；报告不依赖存活程序。
- 编译失败、中途注册失败和取消都释放临时资源。句柄带引擎归属及代际检查，旧 root/handle 不得指向复用槽位的新程序。

长 Execution 验证反复创建和释放上万份不同参数程序后的 live nodes/programs/cache 数量，而不只看 ActiveCount 或进程 RSS。保留一个共享程序的长期 coverage，同时创建/取消普通等待，确认它的窗口和累计计数不受影响。必要的资源数量测试接口属于回收验收，不扩展成统一诊断项目。

## 表达式类型先立规则，再降低

引脚视图提供补全，IR 负责真实类型。类型至少包含 bool/bits、width、signed 和未知位表示；规范化和 Python/native 执行都读取同一类型。建议本轮避免隐式模拟整套 SystemVerilog 上下文推导：

| 场景 | 拟议规则与审核例子 |
| --- | --- |
| Bool 与 Bits | Bool 的 &/\|/~ 表示逻辑；Bits 表示按位。Wait/Within/Hold 接收 Bool，整数条件须显式比较或转为非零判断 |
| 常量 | 在已确定的对端位宽/符号中检查是否可表示；裸负数不默认为 uint64。没有可推导类型的常量要求显式类型 |
| 两个 Bits 运算 | 位宽或 signed 不同就要求显式转换，不悄悄按 Python int 或 uint64 处理 |
| 加减乘 | 同类型结果保持位宽并截断；UInt4(15)+UInt4(1)=0。需要进位先扩展到 5 位 |
| signed 比较 | SInt8(-1)<SInt8(1) 为真，UInt8(255)<UInt8(1) 为假 |
| 转换 | 分开表达 reinterpret signed/unsigned、零扩展、符号扩展和截断；零扩展 0xff 到 16 位是 255，符号扩展 SInt8(-1) 得 -1 |
| 除法和余数 | signed 除法向零截断，余数与被除数同号；不能直接复用 Python // 的向下取整 |
| 移位及非法运算 | 规定逻辑/算术右移、超位宽移位、负移位和除零，定义阶段或运行阶段明确处理 |
| 未知位 | 转换保留未知位；按位运算按逐位真值表，算术/比较在输入未知时保守返回未知。typed IR 的已知性读取运算结果，不能一律按所有原始输入是否已知判断 |

这是类型规则提案，不是已实现保证。具体 cast/扩展函数名、除零和移位边界需要在类型实现提交中冻结。当前 Sequence 对未知条件的步骤行为继续保留；typed 表达式自身能够消去未知位的情况，例如按位 0 & X，需用 Python/native 对照用例明确新增结果语义。

支持任意声明位宽应落到原生多字表示或明确的能力检查，不能在 native 模式偷偷回 Python 计算。先完成本轮声明的运算集合、边界和对照测试，再开放对应运算；不把已有宽信号直接比较能力说成完整宽位运算。

## 按可验收的提交改临时分支

| 批次 | 修改位置 | 必须看到的结果 |
| --- | --- | --- |
| 1. 声明与类型闭环 | decorators.py、triggers.py、类型化引脚视图、declarative 的 declarations/compiler；新增明确的 pattern IR/计划 | @xtrigger 返回真实定义对象；直接 bins/with_args/继承编译和 explain 可审核；尚未具备原生能力时 bind 明确拒绝 |
| 2. 原生资源生命周期 | 隔离 xcomm 的 xexpr/xtrigger 头文件及实现、SWIG；backend 程序缓存 | 长 Execution 资源回落；共享观察不受取消影响；非法/陈旧 root 和 handle 拒绝；失败路径无泄漏 |
| 3. 类型规则与公共降低 | ir.py 或拆出的类型模块、backend、隔离 xcomm 的表达式实现 | 冻结类型规则；宽度、符号、转换、未知值的 Python/native 边界结果一致；trigger 和 coverage 走同一个 lowering |
| 4. 每 bin 完整程序 | coverage schema、_coverage_runtime.py、声明 runtime；隔离 xcomm 的 coverage 描述符与计数路径 | 每个 bin 支持 Expr/完整 Sequence/FSM 终态，C++ 持续计数，无虚构 signal、无循环 await |
| 5. 协议实例验收 | examples/coverage、tests/coverage、tests/typing 和打包检查 | 一个 group 同时展示逐拍握手 bin、Wait/Within/Hold bin、FSM 成功/超时 bins；计数、完成拍和生命周期可核对 |

这是三项能力的施工顺序，批次不是互不相关的新框架。先让新声明可编译但不执行，随后通过资源、类型和完整 bin 执行闭环；不能把“能接受语法”称为时序覆盖完成。当前原仓库和 `/home/xyl/picker/dependence/xcomm` 都保持只读；C++ 开工前在 `/tmp` 建独立副本，构建也使用新目录，不能复用指向原源码的构建目录进行修改。

验收重点：窗口两端、Hold 连续性、FSM 未选终态、重复完成、ENTER 与 EACH_SAMPLE 的区别、同拍多个完成、non-overlap 重新启动、gate/abort、reset、illegal、容量与溢出、失败回滚、Python/native 相同输出。测试需要一个不满足窗口的反例，确认不会为了凑覆盖而误计数。

## 草稿验证范围

[api.pyi](api.pyi) 与 [example.py](example.py) 用于检查参数补全、返回类型、输入根类型和继承是否能用 Python 类型系统表达；[negative.py](negative.py) 标出必须拒绝的误用。它们没有 api.py 实现，不能运行，不验证 native 或真实编辑器体验，也不验证表达式位宽语义。

类型配置仅对刻意缺少实现的 stub 模块关闭 reportMissingModuleSource；参数、继承和返回类型仍按 strict 检查。

在本目录执行：

```bash
node /tmp/xreactor-class-coverage-tools/node_modules/pyright/index.js --project pyrightconfig.json
node /tmp/xreactor-class-coverage-tools/node_modules/pyright/index.js --project pyrightconfig.json negative.py --outputjson
```

第二条应失败，并在每个 EXPECT_ERROR 行报告错误。没有标记的错误也要修正，不能只统计错误总数。

2026-10-08 使用 Pyright 1.1.414 验证：正例及 stub 共两个文件零错误、零警告；12 个标记负例全部拒绝，且没有非预期诊断。验证记录位于 `/tmp/xreactor-coverage-v2-ob2uhbua/trigger-bins-verification.json`。这些结果仅支持接口的静态可表达性，不代替未来实现测试。
