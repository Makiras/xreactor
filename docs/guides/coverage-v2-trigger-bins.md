# Coverage v2：每个 bin 直接使用 xtrigger

这是 coverage v2 草稿。当前适配 picker/xcomm 的 `xreactor-coverage-v2` 分支；原生 ABI 为 3，coverage 描述协议为 4。精确提交与本地构建方式见下文。

这轮接通了完整执行路径：**一个 bin 引用一个现有 xtrigger 定义，C++ 持续推进并计数**。现有 Bundle、表达式 IR、Sequence/FSM 推进函数、coverage 计数存储、快照和报告继续复用。

## 定义与使用

可运行的完整示例见 [trigger_bins.py](https://github.com/Makiras/xreactor/blob/draft/coverage-v2/examples/coverage/trigger_bins.py)，引脚组和 DUT 替身直接复用 [declarative_protocol.py](https://github.com/Makiras/xreactor/blob/draft/coverage-v2/examples/coverage/declarative_protocol.py)。

```python
@xtrigger(sample=RisingEdge("clock"))
def roundtrip(pins: ProtocolBundle, *, tag: int = 1, maximum: int = 4):
    return Sequence(
        Wait(signal_expr(pins.request.valid) & signal_expr(pins.request.ready)
             & (signal_expr(pins.request.tag) == tag)),
        Within(1, maximum,
               signal_expr(pins.response.valid) & signal_expr(pins.response.ready)
               & (signal_expr(pins.response.tag) == tag)),
    )


class Completions(TemporalCoverPoint[ProtocolBundle]):
    tag_one = roundtrip
    tag_one_fast = Bin.pattern(roundtrip.with_args(maximum=2))


@covergroup(schema_id="protocol.completions", contract="protocol.completions/v1")
class ProtocolCoverage(SignalCoverGroup[ProtocolBundle]):
    completions = Completions()


coverage = ProtocolCoverage(instance="dut.protocol")
coverage.bind(pins=pins, sample=RisingEdge(pins.clock), strategy="native")
async with Execution(backend, coverage=[coverage.runtime]):
    await ClockCycles(pins.clock, 12)

count = coverage.completions.count(Completions.tag_one)
```

`ProtocolBundle` 是项目的普通 Bundle 子类；叶子仍是原始 XData。函数参数、字段和类属性可用于补全、跳转和重命名。报告名称取自类属性，查询直接使用声明对象。`clock`、schema/instance 标识和 FSM 状态名继续采用现有接口的字符串形式。

`TemporalCoverPoint` 和 `SignalCoverGroup` 是现有声明层的子类：前者组织过程完成事件，后者绑定 live 根对象。它们仍使用一个 CoreCoverGroup 存储计数。快照与已完成事务继续使用既有 `CoverGroup[Snapshot]`，例如 `TransactionCoverage.sample(completed)`；两种输入的职责可从类定义看出。

## bin 与 trigger 如何复用

`@xtrigger` 现在返回不可变的 `TriggerDefinition` 元数据对象。它保存原函数、sample 和 mode，声明函数仍构造既有 XExpr/SequenceSpec/FsmSpec。

- `roundtrip(pins, maximum=3)` 返回现有 `CompiledTrigger`，可以正常 await。
- `roundtrip.with_args(maximum=3)` 检查原函数的参数签名，冻结参数，返回同一种未绑定定义对象。
- `fixed.bind(pins, sample=...)` 绑定冻结后的定义；显式阶段必须与定义声明的阶段一致。
- 直接放进 point 的定义使用默认参数；存在必需参数时要先调用 `with_args`。
- 参数冻结目前接受 bool、int、str、None 及这些值组成的 tuple，拒绝可变容器。
- `Bin.pattern(...)` 增加阈值、normal/ignore/illegal、FSM 终态选择及有界重叠策略。

`PatternBin[P]` 只是 `TriggerDefinition[P, ...] | BinRule[P]` 的类型别名，方便继承时替换配置；没有独立 matcher/trigger 层。相同定义可用于不同 points，运行历史独立。同一个 point 下重复使用同一对象会导致查询歧义，要求分别创建 `Bin.pattern(...)` 配置。

完整示例同时包含逐拍握手表达式、两个不同窗口的 Sequence、Wait/Within/Hold 组合，以及选择 `OK`/`BAD_DATA` 的 FSM。多终态 FSM 必须指定 `terminals=(...)` 或 `all_terminals=True`；到达未选择的终态也结束该次匹配。ENTER/EACH_SAMPLE/CHANGE 直接沿用普通 trigger 的事件语义。

## 同一次观察，多个结果 bins

同一个 point 中，多个 bins 可以引用相同的完整程序，分别选择它的不同终态：

```python
class Completions(TemporalCoverPoint[ProtocolBundle]):
    correct_data = Bin.pattern(checked_tag_one, terminals=("OK",))
    bad_data = Bin.illegal(Bin.pattern(checked_tag_one, terminals=("BAD_DATA",)))
```

这两个 bins 共用一次 FSM 推进，C++ 根据结束结果分别增加计数。到达未选择的终态也会结束这次匹配；终态选择不改变过程本身。normal/illegal 属性、覆盖阈值和计数仍各自独立。

编译器按照现有 IR 的规范化内容识别相同过程，忽略终态选择、kind 和阈值。共享限定在同一个 point、同一绑定和采样生命周期内，mode、overlap、max_active 必须一致。两个不同窗口的 Sequence 分别执行；不同 points 的运行历史保持独立。

重叠请求仍各自有匹配状态。一拍内可以有 FAST 一次、SLOW 两次；引擎保留各终态的完成数量，分别分发给选择对应结果的 bins。Expr 和 Sequence 也可以共享同一观察结果，保留原事件模式和步骤语义。

声明写法沿用现有 Bin.pattern，不增加用户必须定义的中间层级。CompiledGroup.explain() 会显示例如 `execution 0 (checked_tag_one): bad_data, correct_data` 的关系。目标引擎的 CoverageState 使用 trigger 模块的 PatternMatcher，底层继续复用 AdvanceFsm/AdvanceSequence；原生 group 仍只占一份采样注册。

`CoverageExecutionCount(handle)` 是检查独立 pattern 执行数量的原生查询，排除 group 采样源和值 bins。协议示例的六个 bins 对应五份执行；两个终态 bins 共享一个 FSM。每个 bin 的诊断和 progress 继续显示该 bin 消费的观察过程，不能把这些视图相加当成实际资源数量。

该优化使用 coverage 描述协议 4，保持 schema version 3 和报告契约不变。配套原生库使用 ABI 3；两个版本号分别描述参数协议和 C++ 二进制兼容性。长 Execution 内节点回收、沿途 emit 事件及动态关联仍未实现。

## 编译与计数

```text
类声明与继承
  -> 现有 CompiledGroup：冻结参数、IR 序列化、schema、explain/diff
  -> 现有 backend lowering：绑定真实信号、编译表达式和步骤
  -> xcomm coverage 描述协议 4：共享的过程执行与各 bin 的结果选择
  -> trigger PatternMatcher / AdvanceSequence / AdvanceFsm / 表达式求值
  -> 原生累计计数与 CoverageSnapshot
  -> 同一个 CoreCoverGroup 的报告与 CoverageDatabase
```

pattern point 不需要虚构一个数值信号。每个 bin 的 matcher 保留完整程序，schema version 3 包含程序、参数、mode、终态和容量；更改窗口会改变 schema digest，报告不会误合并。普通值覆盖仍接受描述协议 3/4，trigger bins 的严格 native 路径要求协议 4；auto 路径遇到旧协议明示回退原因。

默认不重叠，`max_active=1`。重叠模式必须显式提供容量，例如 `Bin.pattern(roundtrip, overlap=True, max_active=8)`。同拍三次完成按三次计数。容量不足标记采集不完整并报错。reset、clear_history、abort 沿用现有执行生命周期；普通等待的取消不会清空 coverage 的历史。

ignore/illegal 在 pattern point 中修饰各自的过程事件，不取消同 point 下其他程序的完成计数。pattern point 的 samples 记录启用的采样次数，unmatched 表示该次没有任何程序完成；未知条件沿用现有 trigger 语义，普通值 point 的 unknown 统计不被借作过程诊断。

跨 temporal points 的 Cross 被明确拒绝；跨过程完成的关联上下文尚未定义。值 points、已完成事务记录的 Cross 继续使用既有实现。声明层 live 输入目前先支持 temporal points；typed gate 选择器仍面向快照字段，底层现有 Iff 的过程门控已经对照验证。

## 运行实验

在实验根目录运行：

```bash
python -m examples.coverage.trigger_bins --engine xcomm --strategy native
python -m examples.coverage.trigger_bins --engine memory --strategy python
```

示例发送 tag 1、2、3，响应顺序是 2、1、3。预期计数：

| point.bin | 次数 | 原因 |
| --- | ---: | --- |
| requests.handshake | 3 | 三笔请求握手，连续握手逐拍计数 |
| completions.tag_one | 1 | tag 1 三拍后返回，落入四拍窗口 |
| completions.tag_one_fast | 0 | 同一次响应不满足两拍窗口 |
| completions.tag_two_ready | 1 | tag 2 响应后，再连续保持 ready 两拍 |
| completions.correct_data | 1 | tag 1 响应数据为 10，FSM 到 OK |
| completions.bad_data | 0 | 没有错误数据 |

Python memory、xcomm Python 和 xcomm native 使用同一输入，对比计数。测试还覆盖同拍多个完成、FSM 未选终态、gate/abort/reset、普通 waiter 取消、容量失败、报告序列化，以及 native 不调用 Python sample、不因每次命中唤醒 Python。类型测试直接导入真实实现，检查参数名/类型、输入根类型和 bin 引用。

## picker/xcomm 分支适配

适配基线为 xreactor `11f7e89`，配套 picker `60ca8e8`、xcomm `83ab5b2c466ad5ebfb0275b84830a41f9c06bb5e`。picker 和 xcomm 均来自 `xreactor-coverage-v2` 分支；picker 的 `.build-config.yml` 固定了同一份 xcomm。

| 版本 | 值 | 检查方式 |
| --- | --- | --- |
| xspcomm 包版本 | `0.3.0.dev0` | `importlib.metadata.version("xspcomm")`、`xspcomm.version()` |
| 原生 C++ ABI | `3` | `xspcomm.abi_version()`，对应 `libxspcomm.so.3` |
| coverage 描述协议 | `4` | `XTriggerEngine.CoverageVersion()` |
| pattern schema | `3` | 报告中的 schema version |

CI 从 `.github/native-dependencies.json` 获取精确提交与这三个原生依赖版本，构建明确标识为 `0.3.0.dev0` 的预览包并分别校验。现有 Python lowering 使用的 ArmSample、AttachCoverage、CoverageSnapshot、CoverageExecutionCount 接口保持一致，类声明和 schema 不需要改变。

在独立工作目录中取得上述 xcomm 提交后，使用独立 Python 环境构建：

```bash
SETUPTOOLS_SCM_PRETEND_VERSION_FOR_XSPCOMM=0.3.0.dev0 \
BUILD_XSPCOMM_SWIG=python XSPCOMM_BUILD_WHEEL=1 \
python -m pip install /path/to/xcomm
python -m pip install -e '.[native,test]'
python -m pytest -q --require-xspcomm
python -m examples.coverage.trigger_bins --engine xcomm --strategy native
```

原生 ABI 变化后，picker 和生成的 DUT 扩展必须使用匹配的头文件与运行库重新构建。纯 Python MemoryBackend 仍不需要安装 xspcomm。真实 Adder DUT 的覆盖率示例见 `examples/coverage/picker_adder.py`：使用普通 Bundle 绑定生成的 XData，覆盖 128 位信号、跨采样 Sequence 和共享多终态 FSM。

取得使用配套 picker 重新生成的 Adder 包后，运行：

```bash
python -m examples.coverage.picker_adder \
  --dut-path /path/to/generated \
  --report /tmp/picker-adder-coverage.json
```

`--dut-path` 指向包含 Adder 包的目录。若构建时使用 `VERBOSE=ON` 保留了中间目录，再加 `--dut-module Adder.UT_Adder`。示例将每组输入保持两个采样，然后插入一个空闲采样；Adder RTL 本身是组合逻辑，Sequence/FSM 描述这里的观察窗口。7 个 bins 共用 3 份原生过程执行和一个采样注册，预期 carry 2 次、no_carry 2 次、完整溢出 Sequence 1 次、高半区结果 2 次。`repeated` bins 保留独立阈值，完整溢出的阈值 2 此时尚未达到。

## 尚未完成

长 Execution 内程序节点和缓存的细粒度回收仍待做；当前继续使用 Execution 结束时的既有清理路径。完整的 Bool/Bits、signed、宽运算、cast 和未知位类型规则也未实现。本轮复用现有表达式能力，不承诺新的表达式语义或完整 UCIS 兼容。

动态 tag 捕获/关联、完成上下文及 temporal Cross 保留为后续讨论。当前示例按固定 tag 编译匹配；现有 Python TransactionCollector 仍处理动态事务关联。没有新增信号容器、事务引擎、时序 VM 或报告系统。
