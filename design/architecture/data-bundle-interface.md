# XData、Bundle 与 Interface 设计

> 状态日期：2026-09-15
> 状态：核心端口抽象和自动层次视图已实现并经真实 Cache 验证；协议专用结构交由 agent 组织，native 批量快照待实现。

## 结论

新框架只把 `XData` 作为叶子信号句柄。旧 Python `XPin` 只是
`XData + shared event` 的动态代理，没有形成独立的硬件、调度或协议语义；本次允许
breaking change，因此已删除 `XPin` 和 `XData.xdata`，不再保留迁移期代理。

上层数据模型参考 Chisel，但不机械复制 Chisel 的 elaboration 模型：

```text
XData                         native-bound 叶子信号
  └── Bundle                  具名、可嵌套的活信号视图
      └── Interface           Bundle + 协议字段/角色/时序约束
          ├── ReadyValid
          ├── Valid
          └── 后续 AXI/TileLink/SimpleBus 等具体接口

Bundle.sample()
  └── BundleValue             某个明确 sampling phase 的不可变四态快照

Interface
  ├── Driver                  主动产生 transaction
  └── Monitor                 被动观察 transfer，输出 transaction/Transfer
```

推荐公共命名使用 Chisel 用户熟悉的名词：`Bundle`、`Vec`、`ReadyValid`、
`Decoupled`、`Flipped`/role、`DataView`/view；但每个名字必须服从验证框架的运行时
语义，不能暗示尚未实现的 Chisel elaboration 或连接检查能力。

## 1. 旧 XPin 到底做了什么

删除前的实现基本等价于：

```python
class XPin:
    def __init__(self, xdata, event):
        self.xdata = xdata
        self.event = event

    def __getattribute__(self, name):
        return getattr(self.xdata, name)

    def __setattr__(self, name, value):
        setattr(self.xdata, name, value)
```

逐项核对后，真正的能力归属如下：

| 能力 | 实际持有者 | XPin 是否增加语义 |
| --- | --- | :---: |
| 位宽、IO 类型、名称 | `XData` | 否 |
| 0/1/X/Z 值 | `XData` | 否 |
| DPI/VPI/memory-direct/Expr 绑定 | `XData` | 否 |
| immediate/rise/fall 写入模式 | `XData` | 否 |
| `OnChange` | `XData` | 否 |
| native trigger 采样 | `XTriggerEngine` 持有 `XData` | 否 |
| 时钟 pin 身份 | `XClock.HasClockPin(XData&)` | 否 |
| `.value` 写法 | `XData.value` 已是自身引用 | 否 |
| asyncio event | `XClock.getEvent()` 的共享 event | 没有 pin 特异性 |
| 防止 `dut.port = ...` 覆盖成员 | 生成 DUT 的 `__setattr__` | 否 |

所有生成的 `XPin` 都拿到同一个 `dut.event`。所以它表达的不是“这根 pin 发生了事件”，
只是旧 `XClock.ANext/AStep` 路径的共享周期通知。XReactor 已经以 Registration、
phase 和 typed `XEvent` 取代这条路径，不应再把共享 event 复制到每根信号上。

`XPin.__eq__` 还会造成实际问题：它只允许 `XPin == XPin`，遮蔽 `XData` 的数值比较；
同时定义 equality 而没有稳定 identity/hash 约定，不适合被 Bundle、trigger cache 或
ownership registry 当作 key。

因此，`XPin` 曾经有的是**兼容作用**，不是**模型作用**；在明确接受 breaking change
以后，这个兼容成本没有继续存在的理由。

## 2. 为什么保留 XData，而不是一起替换

`XData` 不是单纯的 Python 数值包装，它是 xcomm 的跨语言 native signal handle：

- 保存宽度、方向、四态 shadow value；
- 绑定 Verilator memory、DPI、VPI、常量或 Expr；
- 执行读写、边沿写回和 refresh；
- 被 XClock、XPort、XTriggerEngine 和 ComUse 系列直接使用；
- 在 C++、Python、Java、Scala 等前端拥有共同 ABI 概念。

删除 `XData` 会迫使新框架重新实现整个 simulator binding 层；删除 `XPin` 则只需要
把 Python 便利和旧 event 迁到正确的对象上。两者不应混为一谈。

新边界应为：

```text
Python user API       Bundle / Interface / Trigger
                              |
normalization                 v
                         XData identity
                              |
C++ hot path       XClock / XPort / XTriggerEngine
```

## 3. Chisel 中的对应模型

Chisel 的主要术语是：

| Chisel | 含义 | XReactor 对应建议 |
| --- | --- | --- |
| `Data` | 所有硬件数据的基类 | `XData` 作为 bound leaf handle |
| `UInt/SInt/Bool/Clock` | 叶子类型 | 首版仍由 `XData` 宽度/元数据表达 |
| `Aggregate` | 聚合数据 | Bundle/Vec 的共同结构概念 |
| `Bundle` | 具名字段聚合 | `Bundle` |
| `Vec[T]` | 同类型定长序列 | `Vec`，首版也可接受 tuple/list |
| `Record` | 动态 key/data 聚合 | 动态 `Bundle` 或内部 schema map |
| `IO(...)` | 把 Data 绑定为模块端口 | Picker 生成/绑定阶段 |
| `Input/Output/Flipped` | 递归方向 | DUT-relative direction + TB role view |
| `ReadyValidIO[T]` | ready/valid/bits 基类 | `ReadyValid[T]` |
| `DecoupledIO[T]` | 无额外时序保证的 ready-valid | `Decoupled[T]` 或 ReadyValid 默认 contract |
| `IrrevocableIO[T]` | valid 后 bits 稳定、不能撤回 | 后续 `Irrevocable[T]` + checker |
| `DataView` | 同一底层数据的另一结构视图 | `view_as()`/binding schema |
| `Connectable` | 结构化连接规则 | 验证侧 bind/compatibility check |

值得借鉴的不是 Scala 类层次本身，而是三条原则：

1. 叶子和聚合使用同一套可递归数据模型；
2. 协议接口是带约束的 Bundle，而不是若干无关 signal 参数；
3. 方向需要递归解释，并且 producer/consumer 两侧看到的是相反视角。

但 XReactor 是测试平台，不是 HDL elaborator。它不应复制 Chisel 的硬件构造、
FIRRTL 类型推导或 bulk-connect 规则。特别是，验证侧的 `Flipped` 只能生成相反 role
的**视图**，不能调用 `XData.FlipIOType()` 修改 DUT 原始元数据。

Chisel 术语和语义以官方文档为准：

- [Interfaces and Connections](https://www.chisel-lang.org/docs/explanations/interfaces-and-connections)
- [Bundle API](https://www.chisel-lang.org/api/latest/chisel3/Bundle.html)
- [DecoupledIO API](https://www.chisel-lang.org/api/latest/chisel3/util/DecoupledIO.html)
- [Connectable Operators](https://www.chisel-lang.org/docs/explanations/connectable)
- [ChiselTest DecoupledDriver](https://www.chisel-lang.org/api/latest/chiseltest/DecoupledDriver.html)

## 4. 公共对象模型

### 4.1 XData：唯一叶子实体

新生成的 Python DUT 应直接暴露：

```python
dut.clock            # XData
dut.reset             # XData
dut.io_req_valid      # XData
dut.io_req_ready      # XData
```

最低要求：

- 对象 identity 在 DUT 生命周期内稳定；
- 可以取得 `width`、DUT-relative direction、backend kind 和四态值；
- `await RisingEdge(dut.clock)` 与 `Value(dut.io_req_ready, 1)` 直接接受它；
- 信号所属 simulation domain 由 backend/DUT binding registry 判断，不由 signal 上的
  asyncio event 判断；
- 不要求 `XData` 自身 awaitable。

建议逐步补充更 Python 化但薄的属性，例如 `width`、`direction`、`logic_value`，这些
属性直接映射 native 状态，不能复制一份脱离 native identity 的 Python shadow。

### 4.2 Bundle：活信号的结构化视图

`Bundle` 保存字段到 leaf/nested Bundle/Vec 的绑定关系。它不拥有 simulator storage，
也不自己推进时间。

第一版可以采用运行时构造：

```python
req_bits = Bundle(
    addr=dut.io_in_req_bits_addr,
    data=dut.io_in_req_bits_data,
    mask=dut.io_in_req_bits_mask,
    cmd=dut.io_in_req_bits_cmd,
    user=dut.io_in_req_bits_user,
)
```

进一步可支持声明式 schema：

```python
class CacheRequest(Bundle):
    addr: UInt[32]
    data: UInt[64]
    mask: UInt[8]
    cmd: UInt[3]
    user: UInt[64]

req_bits = CacheRequest.bind(dut, prefix="io_in_req_bits_")
```

声明式语法属于生成器/类型检查增强，不阻塞第一版。第一版最重要的是递归结构、稳定
字段顺序、宽度校验和快照正确性。

`Bundle` 应提供：

- 属性和 key 两种字段访问；
- `leaves()`/`items()` 的确定性递归遍历；
- schema/shape/width 检查；
- `sample()` 生成不可变 `BundleValue`；
- `drive(mapping_or_value)`，但只允许驱动 role 授权的叶子；
- `view_as(schema)` 或显式 field mapping；
- 清晰的 path，例如 `req.bits.addr`，用于错误和 trace。

`Bundle` 不应提供：

- 隐式 clock；
- 隐式等待或自动推进仿真；
- 自己的 asyncio queue/event；
- 协议专用 handshake；
- 将全部叶子的 native IO type 就地翻转。

### 4.3 PackedArray/PackedView：单根 packed bus 的递归视图

Picker 已能把 Verilog 展平生成的 `lanes_0/lanes_1` 还原成序列；另一类输入是只有
一根 `N*W` 位 XData、但协议上表示 N 个 W 位 lane。两者不能混为一谈。后一类使用
显式视图：

```python
lanes = PackedArray(dut.packed_lanes, element_width=32, count=4)
# 等价便捷入口：split_packed(dut.packed_lanes, 32, 4)
lanes[0].Set(0x11223344)  # 默认 lane 0 对应最低 32 位
```

`PackedArray` 基于 `XData.SubDataRef`，不复制 simulator storage；每个元素仍是可用于
Value/@xtrigger/Bundle 的 XData。它强持有父 XData，防止 native slice 的非 owning
parent 指针悬空。默认 `lsb_first=True`，可显式设为 false；总位宽必须严格等于
`element_width * count`，避免遗漏高位或静默截断。

当一根总线包含多维数组、数组元素 Struct 或自定义 padding 时，使用递归布局：

```python
entry = PackedLayout.struct({
    "valid": PackedLayout.bits(1),
    "tag": PackedLayout.bits(7),
    "data": PackedLayout.array(2, PackedLayout.bits(32)),
})

entries = PackedView(
    dut.packed_entries,
    PackedLayout.array(4, entry),
    name="entries",
)

entries[2].valid.Set(1)
entries[2].data[1].Set(0x1234_5678)
```

每层 array 可以独立设置 `lsb_first`，所以多维 packed array 不需要共享同一种下标
方向。`stride` 可以描述元素间 padding。Struct 默认按声明顺序从低位向高位自动布局；
`lsb_first=False` 改为从高位向低位。自定义协议编码使用显式 offset：

```python
packet_layout = PackedLayout.struct({
    "opcode":  PackedLayout.bits(6, offset=0),
    "tag":     PackedLayout.bits(8, offset=8),
    "payload": PackedLayout.bits(64, offset=32),
}, width=128)
```

同一 Struct 不混用自动与显式 field offset，避免 padding 后字段位置产生歧义。字段
默认禁止重叠；`allow_overlap=True` 只适合 union/alias 视图，此时禁止 whole-view
`drive()`，调用者必须明确驱动某个 leaf。

布局在构造时一次性编译成绝对 bit offset。所有 leaf 都直接执行根 XData 的
`SubDataRef(abs_offset, width)`，不是逐层 slice-of-slice，因此嵌套深度不会增加 native
读写回调层数。每个中间 PackedView 都强持有根 XData，单独保存深层 view 也不会悬空。
PackedView 支持递归 `sample()`、`drive()`、`leaves()`，也可以直接放进 Bundle。

切片写回的是根 XData 的共享 backing。切片本身不单独加入 XClock/XPort；如果父信号
采用 Rise/Fall 写入模式，其最终 simulator commit 仍由父信号所在 XPort 的边沿提交
控制。

### 4.4 BundleValue：稳定、不可变的采样结果

活 `Bundle` 和采样值必须分开。否则 Monitor 把信号句柄放入队列后，消费者看到的会是
未来时刻的值，而不是 transfer 当时的数据。

```python
value = req_bits.sample()

assert value.addr == 0x8000_1000
assert value.data.width == 64
assert value.data.x_mask == 0
```

`BundleValue` 应满足：

- immutable；
- 保留嵌套结构和字段顺序；
- 每个 leaf 保留 value、X/Z mask、width，不能默认压成 Python `int`；
- 记录 sampling phase/tick 的职责由外层 `Transfer` 承担，避免同一 payload 被多个
  protocol event 包装时重复时间信息；
- 支持显式 `as_int(strict=True)`，遇到 X/Z 默认报错。

### 4.5 Vec

Chisel 使用 `Vec[T]` 表达同 shape 的定长序列。XReactor 首版不必为了名称对齐立即
实现复杂泛型容器：tuple/list of `XData | Bundle` 已足够表达结构。

只有当以下需求出现时再公开 `Vec`：

- 绑定时统一校验 length/element shape；
- 嵌套路径需要稳定表示 `ports[3].bits`；
- 批量 snapshot/drive 需要 native lowering；
- 静态类型工具能从 `Vec[T, N]` 获益。

内部 schema 可以先预留 sequence node，避免将来格式不兼容。

## 5. Interface：Bundle 加协议语义

`Interface` 不是任意 XData 的另一层无条件包装。只有当一组字段存在共同协议语义时，
才应该成为 Interface。

Ready-valid 建议直接采用 Chisel 用户熟悉的字段：

```text
valid   producer -> consumer
ready   consumer -> producer
bits    producer -> consumer
```

而不是同时支持 `payload/data/bits` 三套核心命名。不同 RTL 命名在 bind 时映射，绑定后
统一叫 `bits`。

```python
req = ReadyValid(
    clock=dut.clock,
    valid=dut.io_in_req_valid,
    ready=dut.io_in_req_ready,
    bits=req_bits,
    role=Role.PRODUCER,
)
```

这里的 role 是**验证组件相对接口的角色**：

- `PRODUCER`：可驱动 `valid/bits`，采样 `ready`；
- `CONSUMER`：可驱动 `ready`，采样 `valid/bits`；
- `MONITOR`：所有字段只读；
- 可选 `PASSIVE` 作为 `MONITOR` 别名，不再引入第四种语义。

role 不能只从 `XData.IsInIO/IsOutIO()` 推导。XData 方向是相对 DUT 的，而同一接口可能
被 DUT driver、外部 memory responder 或纯 monitor 以不同角色使用。bind 时可以结合
DUT direction 验证 role 是否合理，但 role 必须显式存在。

建议提供不修改底层 XData 的视图操作：

```python
producer = req.as_role(Role.PRODUCER)
consumer = req.flipped()       # 返回 consumer view
monitor = req.monitor_view()   # 返回只读 view
```

### ReadyValid 与 Decoupled 的命名

第一版建议把实现类命名为 `ReadyValid`，因为这准确描述结构与 fire 条件：

```python
req.fire   # symbolic valid & ready，按协议 sample phase 使用
```

如果公开 `Decoupled`，它应是 `ReadyValid` 的 contract 名称或薄子类，并明确与 Chisel
一致：它本身不保证 ready/valid 的额外稳定性。需要“valid 拉高后不得撤销且 bits 稳定”
时使用独立的 `Irrevocable` contract/checker，不能把这个保证悄悄塞进 Decoupled。

## 6. Driver、Monitor 与传输结果

协议对象只定义字段、角色和 transfer 规则；主动行为与被动观察分别进入 Driver 和
Monitor。

当前实现提供 `Driver[T]`、`Monitor[T]` 两个最薄抽象基类，以及
`ReadyValidDriver`、`ReadyValidMonitor`。基类只冻结主动发送/被动接收和生命周期
边界，不提前引入 sequence、agent、factory 等 UVM 层次。

```text
ReadyValid
  ├── ReadyValidDriver
  │     send(transaction) -> XEvent/Transfer
  └── ReadyValidMonitor
        recv() / async for -> Transfer[BundleValue]
```

`XEvent` 表示“底层 occurrence 已经发生”，payload transaction 不是 XEvent 本身。
推荐统一结果：

```python
@dataclass(frozen=True)
class Transfer(Generic[T]):
    event: XEvent
    value: T
    accepted_tick: int
```

其中 `accepted_tick` 可从 event 派生时不必重复存储；字段最终形态以实现验证为准。

Driver：

- 独占自己负责的驱动叶子；
- 用 `asyncio.Lock` 串行化同一 channel 的 `send()`；
- 基于已实现的 `drive_ready_valid()` 保证 valid 不跨过两个 accepting edge；
- transaction encoder 只负责把值映射到 bits，不负责推进时间；
- cancel/exception 必须撤销 valid，并保持 ownership 状态可恢复。

Monitor：

- 永不驱动信号；
- 在协议定义的 sampling barrier 捕获 `valid && ready`；
- 同步取得 `BundleValue`，不能在 event loop 下一轮才读取 live XData；
- 支持连续每周期 transfer，不允许 coroutine re-arm 空窗漏 beat；
- 通过有界、默认 lossless 队列交付，overflow 明确失败；
- transaction decoder 在 snapshot 之后运行，可留在 Python。

Monitor 的“命中与快照原子性”是关键实现点。现有 `@on` 能保证 native watcher 在
handler 前 rearm，但 async handler 被调度后再读取 live signal，严格意义上仍依赖
SimulationPump 的 yield 顺序。正式实现应选择以下之一：

1. XReactor publish 阶段同步执行无 await 的 capture callback；
2. backend hit 携带声明好的 leaf snapshot；
3. 引入 phase barrier acknowledgment，在所有同步 observer capture 完成前不推进。

首版推荐 1，性能优化后演进到 2。不能仅凭“通常 asyncio 会先运行 handler”建立
Monitor 正确性。

当前实现采用方案 1，并补上明确的 `DRIVE_STABLE` barrier：subscription 的同步
`capture(XEvent)` 在 Reactor publish
barrier 内完成，capture 返回的不可变值才进入 async handler 队列；`async def`
capture 会在注册时被拒绝。`ReadyValidMonitor` 在 drive-stable 的 `fire` 命中时
快照 `bits`，并立即注册与之相邻的 accepting RisingEdge，连续 beat 不存在 Python
re-arm 空窗。

该 monitor 既能观察 falling 前已稳定的 DUT 输出，也能观察被本次 FallingEdge 唤醒的
Python driver 在下一次 await 前完成的同步写入。Pump 随后调用 native `RefreshComb()`，
并在**不推进 half-tick**的 `DRIVE_STABLE` phase 统一求值 `valid && ready`。这不是“等待
所有 asyncio task 静止”：driver 若在写到一半 await、从 HTTP callback 随机写信号，或
绕过协议 driver，就不属于该确定性契约。

## 7. XPort 的位置

现有 `XPort` 是一个 flat `name -> XData*` 集合，能力包括：

- 按前缀选择 sub-port；
- 批量 edge write/read refresh；
- 批量设置写入模式和 IO type；
- 按同名 leaf `Connect`。

它对 XClock backend 很有用，但不适合作为新的 Python Bundle：

- 结构本质是前缀过滤后的 flat map，不是真正嵌套 schema；
- 只保存裸 `XData*`，生命周期依赖外部；
- `NewSubPort/SelectPins` 以 `new` 创建并返回引用，所有权不清晰；
- `Connect` 对缺失字段警告后继续，不适合作为严格协议绑定；
- 没有 immutable snapshot、X/Z value tree 或 transaction 类型；
- `FlipIOType()` 会修改底层 leaf，而验证侧需要的是不改变 DUT 元数据的 role view；
- Python 属性访问和类型提示能力不足。

还有一个需要明确的 Python 边界：SWIG `XPort.__getitem__()` 可能为同一底层
`shared_ptr<XData>` 返回新的 Python proxy，因此 `port["addr"] is dut.addr` 不保证成立；
两者的 `CSelf()`/native identity 仍相同。生成层次视图和 Bundle 直接引用生成 DUT 上的
flat XData 属性，因而可以保证 Python `is` identity。ownership/cache 不应使用临时
XPort lookup proxy 的 Python `id()` 作为 key；当前 `signal_identity()` 对 native XData
使用 `CSelf()`，纯 Python signal 才回退到 `id()`，因此不同 SWIG proxy 仍能检测到同一
叶子的 driver ownership 冲突。

因此应保留双层：

```text
XPort       backend collection：XClock 批量 refresh/write 的实现细节
Bundle      user structure：字段、shape、snapshot、path、binding
```

Bundle 可以在构造时把 leaf 注册进 XPort，但不应继承 XPort，也不应把 XPort 的方向
修改 API 暴露为 Bundle 语义。后续如果 XPort 只剩内部用途，可考虑更准确地重命名为
`XDataSet`/`XSignalGroup`，但这不是当前迁移的必要条件。

## 8. 生成代码与命名规则

### 公共类型名

建议使用 PascalCase，并尽量复用已形成行业认知的 Chisel 名词：

```text
XData
Bundle
BundleValue
Vec                 可后置
Interface
ReadyValid
Decoupled           可作为 contract/薄子类
Irrevocable         后置
Role
Driver / Monitor
ReadyValidDriver / ReadyValidMonitor
Transfer
```

`XTrigger/XEvent/XReactor` 保持 X 前缀，因为它们是框架特有调度概念；`Bundle` 和
`ReadyValid` 不必强行命名为 `XBundle/XReadyValid`，模块命名空间
`xreactor.Bundle` 已经足以消除歧义，也更接近用户已有认知。

### 字段名

- 标准 ready-valid 固定使用 `valid/ready/bits`；
- Bundle schema 字段使用 Python `snake_case`；
- 原始 RTL 名称完整保存在 binding path/metadata 中；
- 不为了 Python 风格重命名 native XData 的 `mName`；
- `payload` 可以作为文档中的通用概念，但不作为 ReadyValid 的第二套字段名。

### 生成结果

理想的生成 DUT：

```python
dut.clock                 # XData
dut.reset                 # XData
dut.io.req                # ReadyValid[CacheRequest]
dut.io.req.valid          # XData
dut.io.req.ready          # XData
dut.io.req.bits.addr      # XData
```

当前生成器已经建立与 RTL signal tree 对应的只读结构视图。例如 Cache 可写成：

```python
dut.io.in_.req.bits.addr is dut.io_in_req_bits_addr
dut.io.out.mem.resp.valid is dut.io_out_mem_resp_valid
```

Python 关键字字段追加 `_`（如 RTL `in` -> `in_`），原始 key 仍可通过 `[...]` 访问；
连续数字子节点生成为 tuple。顶层聚合（例如 `dut.io`）仍是原有 XPort，以保留 backend
批量 API；其子层是只读结构视图。若顶层 RTL 字段名与 XPort 方法冲突，不覆盖方法，改从
`dut.io._hierarchy[field]` 访问。

为了兼容扁平 Verilog 端口，可同时保留只读别名：

```python
dut.io_in_req_bits_addr is dut.io.req.bits.addr
```

两条路径必须指向同一 `XData` identity，不能复制 XData。是否默认生成层次对象应由
Picker 的 signal tree/schema 决定，而不是在运行时猜字符串。

## 9. XPin breaking removal

### 已完成：内部去 XPin 化

- XTrigger backend、Bundle、Interface、Driver、Monitor 内部只保存 XData；
- `as_xdata(obj)` 不再解包 wrapper，只保留为跨 backend leaf normalization 扩展点；
- event source、ownership 和 cache 都以直接 signal/native identity 为准。

### 已完成：生成器直接暴露 XData

- Python codegen 从 `XPin(XData(...), event)` 改为 `XData(...)`；
- DUT `__setattr__` 继续防止用户用整数覆盖 signal member；
- `dut.event` 和 pin `.event` 不再是新调度 API；
- Cache mem-direct、DPI、VPI 和 internal signal 全部回归。

当前 Picker Python codegen 已默认直接暴露 XData：新生成顶层端口和 internal signal
直接返回 `XData`，`XPort` 登记同一对象，并把 signal tree metadata 嵌入 DUT。
`Bundle.bind_tree()` 可按该树递归绑定、校验位宽并保留 leaf identity；它只恢复结构，
不根据字段名猜测 ReadyValid 等协议。调用方可显式使用
`ReadyValid.bind_tree(dut, subtree, ...)` 声明协议类型；该入口严格要求子树恰好包含
`valid/ready/bits`，并递归校验方向和 identity。

### 已完成：删除兼容 API

- 删除 `xspcomm.XPin`；
- 删除 `XData.xdata` self-view；
- 旧生成包必须重新生成，旧源码把 `pin.xdata` 改为 `pin`；
- 依赖 `.event` 的代码改用 RisingEdge/ClockCycles/Value 等显式 trigger。

不建议用另一个 `XSignal` wrapper 替代 XPin。除非未来确实需要一个跨 backend 的稳定
Python protocol，否则这只会把同一层代理换名重做。需要统一类型时优先定义
`typing.Protocol`，backend 边界仍规范化到 native XData。

## 10. 必须验证的行为

### XData breaking removal

- Python 公共模块不存在 `XPin`，`XData` 不存在 `.xdata`；
- 新生成包所有叶子和 XPort 登记都直接使用 XData；
- mem-direct、DPI、VPI 三种 backend 至少各有 smoke；
- `await RisingEdge(XData clock)`、Value、Expr、FSM 均工作；
- 非本 domain 的 clock XData 仍被拒绝；
- 移除共享 pin event 后 asyncio/pytest/HTTP 共存不退化。

### Bundle

- nested Bundle 和 sequence path 稳定；
- 重名、缺字段、宽度不符在 bind 时失败；
- BundleValue 捕获后继续 step，历史值不变化；
- X/Z mask 不丢失；
- 两个 Bundle view 可安全引用同一 leaf，但驱动 ownership 能发现冲突。

### ReadyValid/Monitor

- ready 连续为高时每周期一个 transfer，不漏不重；
- backpressure 时 valid/bits 保持；
- falling capture 与 accepting rising 的对应关系明确；
- monitor 捕获后 DUT 下一周期改变 bits，不污染已入队 transaction；
- queue overflow、handler exception、cancel 都确定性失败/清理；
- Cache 的 request/response/memory/MMIO channel 全部改用同一抽象后，与当前参考模型
  和 direct probe 结果一致。

## 11. 推荐实施顺序

```text
D0 统一 as_xdata()，冻结 XData identity 规则
  -> D1 Bundle + BundleValue + nested path/XZ tests
  -> D2 ReadyValid + Role，只实现结构和 fire 规格
  -> D3 ReadyValidDriver，复用 drive_ready_valid()
  -> D4 原子 capture + ReadyValidMonitor + Transfer
  -> D5 用 Cache 四类 channel 做真实重构验证
  -> D6 Picker 生成层次 Bundle/Interface，默认直接暴露 XData
  -> D7 删除 XPin/XData.xdata，重新生成旧包
  -> D8 native batched snapshot/宽信号性能优化
```

截至 2026-09-15 的实际状态：

| 项 | 状态 | 证据/边界 |
| --- | --- | --- |
| D0 | 完成 | 直接 signal normalization，并以 `CSelf()` 固定在世 native identity |
| D1 | 完成 | nested Bundle/sequence、Field 宽度、exact-shape drive、四态不可变 BundleValue |
| D2 | 完成 | ReadyValid、Role、direction check、Flipped view、native-lowerable fire |
| D3 | 完成 | 串行 send、signal ownership、backpressure、cancel 清理 |
| D4 | 完成 | native DriveStable、同步 capture、同 falling Python drive、连续 beat、Transfer |
| D5 | 完成（当前 DUT 范围） | Cache 八个 ready-valid 子树均严格绑定；CPU/memory/MMIO 功能流量通过统一 Interface/Bundle 跑通，coherence 已绑定但 DUT 用例无流量 |
| D6 | 完成（核心边界） | 直接 XData、生成层次视图、signal tree、`Bundle.bind_tree()`、显式 `ReadyValid.bind_tree()` 已完成；协议专用 Interface 由 agent 生成，不进入 Picker 核心 codegen |
| D7 | 完成（breaking） | `XPin`、`XData.xdata` 和生成模板 wrapper 已删除；旧包必须重新生成 |
| D8 | 未开始 | snapshot 仍逐 leaf 进入 Python，尚无 native batched snapshot |

其中 D4 的原子快照和 D5 的真实 Cache 重构已经越过 API 定型门槛。AXI/TileLink 等
项目专用协议由 agent 读取 signal tree/metadata 后显式组织 Interface，并为具体协议生成
连续 beat、backpressure、X/Z 和真实 DUT 验证；核心 codegen 不承担复杂协议推断。

## 12. 最终判断

`XPin` 曾经为 Python 前端附加共享 event 和透明代理，因而有历史上的便利作用；但在
XReactor 已经拥有独立 trigger/event/reactor 模型之后，这些能力要么属于 XData，
要么属于 Execution domain，已经没有理由继续由每根 pin 包装一次。

因此最终模型应当是：

```text
XPin：已删除，不属于新公共模型
XData：稳定 native 叶子，必须保留
XPort：backend 批量集合，暂时保留但不公开成 Bundle
Bundle：新的结构化用户抽象
Interface：协议化 Bundle
BundleValue/Transfer：稳定采样与事务交付
```

这既与 Chisel 的 `Data -> Bundle -> ReadyValidIO/DecoupledIO` 心智模型对应，也保留了
Python 异步验证所需要的 live handle、immutable snapshot 和显式 scheduling 边界。
