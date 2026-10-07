# Driver：输入驱动与提交

`Driver` 和 `Monitor` 是独立的组件契约，不要求共同的 `Interface` 基类。
`SignalDriver` 为不同驱动方式提供信号所有权、方向检查和生命周期管理，
但不决定一个 transaction 应如何发射。具体 driver 可以实现单次周期驱动、
脉冲驱动、流水线排队或带反压的驱动；这些名称应描述行为，而非它使用的
`Bundle` 形状。`ReadyValid` 是一个可选的具体通道视图，不是组件必经层。

以下 Sync/Async 模板的传输形态有两个独立维度。这里的“异步”指提交立即返回
`XTransfer`，而不是 Python 函数是否写成 `async def`；“多周期”指一次输入事务
的发射或握手可能占用多个时钟周期，而不是 DUT 的响应延迟。

| 提交方式 | 单周期输入发射 | 多周期输入发射 |
| --- | --- | --- |
| 等待接受：`await send()` | `SyncSingleCycleDriver` | `SyncMultiCycleDriver`；非固定时序继承 `SyncDriver` |
| 立即提交：`send()` 或 `submit()` | `AsyncSingleCycleDriver` | `AsyncMultiCycleDriver`；非固定时序继承 `AsyncDriver` |

四种能力都由 XReactor 提供，且不依赖某个 DUT 或具体握手协议。这里的
`SyncDriver` 是等待输入接受，不是阻塞 Python event loop。
Driver 基类只约定 send 返回可等待的完成事件以及 close，SignalDriver 增加信号 ownership；
它们不要求后台队列、响应事务或阶段锁。协议 Driver 应按提交方式继承 SyncDriver
或 AsyncDriver，在 `_drive_one()` 中实现具体输入时序，复用模板的并发和清理机制。
当前框架不提供独立的 ReadyValidDriver。

当前通用 Driver 类关系如下。`DriveStage` 是多周期模板的静态阶段描述，
不是信号 Bundle，也不是另一个活动组件：

```text
Driver
└── SignalDriver
    ├── SyncDriver
    │   ├── SyncSingleCycleDriver
    │   └── SyncMultiCycleDriver
    └── AsyncDriver
        ├── AsyncSingleCycleDriver
        └── AsyncMultiCycleDriver
```
`AsyncDriver` 是与端口协议、数据形状和事务周期数无关的异步提交模板，统一管理
容量、`XTransfer` 生命周期、accepted stream、取消与失败传播。它不要求使用
显式队列；提交返回事务句柄是这里“异步”的定义。具体实现可以用它覆盖
异步行的任一列，而不需要为两列分别建立空基类。
`SyncDriver` 和 `AsyncDriver` 的 `max_active=1` 让整个输入事务独占通道；
异步串行提交复用同一个发射协程，连续请求不会因任务切换插入空拍。
更大的值允许不同事务在多周期流水线中重叠。重叠并不意味着允许两个
事务同时写同一端口：具体 Driver 应按实际协议使用 `resource_lock(stage)` 仲裁
共享阶段，并在取消或异常时恢复它驱动的信号。输入阶段是否重叠，与已接受
请求的响应是否尚未完成是不同问题。
两个 MultiCycle 模板已经实现固定时长的阶段遍历和逐阶段互斥，调用方仅声明
`DriveStage(name, bits, idle, encode, cycles)`；不同阶段必须绑定互不重叠的输入信号。
`max_active=1` 禁止事务间的输入重叠，较大的值允许前后事务占用不同阶段，
但不会让同一阶段并行写入。阶段时长可以不同；输入接受点是最后阶段的最后一拍。
如果阶段会因握手/背压动态延长、共享一个端口，或有非线性的阶段转移，
应继承 `SyncDriver`/`AsyncDriver`，在协议 Driver 中明确接受条件与资源占用。
`XTransfer` 只有在完整输入被接受时才进入 `PROCESSING`。
`AsyncDriver.send()` 返回接受时自动完成的句柄，`await` 得到接受事件；
调用 send 就提交，随后是否立即 await 由调用方决定。接受后释放容量，不要求响应 collector。
`submit()` 的句柄则由响应检查方完成。`cancel()` 只允许撤销尚未接受的请求。
关闭时仍未完成的已接受请求会进入 FAILED，并通过 `DriverIncompleteError` 报告。
Sync/Async 模板共享私有并发控制与返回事件校验，具体时序仍由 `_drive_one()` 决定。

| 调用 | SyncDriver | AsyncDriver |
| --- | --- | --- |
| `driver.send(request)` | 返回尚未运行的协程 | 立即提交，返回输入句柄 |
| `await driver.send(request)` | 执行驱动并等待接受 | 提交并等待接受 |
| `driver.submit(request)` | 未提供 | 立即提交，返回待响应的事务句柄 |

AsyncSingleCycleDriver 继承相同的提交语义，SyncSingleCycleDriver 继承等待调用的语义；
两者具体单周期时序和 idle 行为不变。其他协议 Driver 的调用时机以各自契约为准。

具体模板的 `resource_lock()` 按当前 Driver 内的资源名复用互斥锁，使用
`async with self.resource_lock(name)` 表达占用范围。不同 Driver 中的相同名字不共享
资源；资源锁也不改变信号 ownership。底层使用原生 asyncio.Lock，测试作者无需
创建锁。Execution 统一处理时钟推进前的就绪工作，阶段代码无需插入 sleep(0)。
锁不推断流水级、占用周期、缓冲深度或硬件仲裁；这些时序仍由具体 Driver 定义。

活动中的异步 Driver 应使用 `await driver.aclose()` 收尾；同步 `close()` 不会在
输入仍被驱动时提前释放信号所有权。

```python
from xreactor import AsyncSingleCycleDriver, Bundle, Execution

async with Execution(backend):
    async with AsyncSingleCycleDriver(
        dut.clock, Bundle(data=dut.data), idle={"data": 0},
    ) as driver:
        inputs = [driver.send({"data": value}) for value in (1, 2, 3)]
        accepted = [await item for item in inputs]
```


具体采样时间表及完整多阶段实现见[流水输入示例](pipeline-examples.md)。
用例通过 [Agent](agents-and-reference-models.md) 封装这些 Driver；上面的独立 context
用法适合组件开发与单独驱动验证。

## 实现自己的多周期输入

固定阶段输入可直接使用框架模板，测试只需要提交业务请求：

```python
from xreactor import AsyncMultiCycleDriver, DriveStage

driver = AsyncMultiCycleDriver(
    clock,
    (
        DriveStage("address", address, 0, lambda request: request.address),
        DriveStage("payload", payload, 0, lambda request: request.payload, cycles=2),
    ),
    max_active=2,  # 两笔请求可以占用不同阶段；同一阶段始终互斥
)
```

`SyncMultiCycleDriver` 接受同一组阶段定义，但调用方用 `await send()` 等待输入接受。
`AsyncMultiCycleDriver` 的 `send()` 立即提交、接受即完成；`submit()` 立即提交，
接受后由 Monitor/Scoreboard 完成响应关联。启动时模板写入各阶段 idle，
取消或异常时恢复当前阶段 idle。`max_active` 限制同时进行的输入发射过程，
与已接受但尚未观察到响应的事务数无关。

当阶段持续时间不能预先写成固定周期，由具体 Driver 明确写出时序；以下 0 空闲值
只属于这个示例接口：

```python
from xreactor import ClockCycles, SyncDriver

class ThreeCycleInput(SyncDriver[int]):
    def __init__(self, clock, data):
        self.clock, self.data = clock, data
        super().__init__((data,), name="three-cycle")

    async def _drive_one(self, value):
        self.data.Set(value)
        try:
            return await ClockCycles(self.clock, 3)
        finally:
            self.data.Set(0)
```

`_drive_one()` 返回输入实际接受的 XEvent，不能返回响应值或 None。
固定阶段需要后台提交时可直接使用 AsyncMultiCycleDriver；动态握手的后台提交
继承 AsyncDriver，并声明 capacity/max_active；无需另造 pipeline 基类。
并发占用同一组信号时，在具体时序中使用 resource_lock，完整实现见流水输入示例。

## 单周期模板的参数

两类 SingleCycleDriver 都接受 clock、标量/Bundle/packed/序列数据节点、idle，以及
可选 `encoder(request)`。encoder 必须同步返回符合驱动节点形状的值。
SyncSingleCycleDriver 使用显式 idle 值，在驱动结束或取消时恢复；AsyncSingleCycleDriver
还允许 `idle(last_request)`，启动时传 None，并在每次接受后恢复计算出的 idle。
callable idle 必须同时处理 None 和已接受请求。关闭只清理工作并释放 ownership，
不自动覆盖已经计算出的 idle。需要回到初始 idle 时，在所有输入接受后、退出前显式
调用 `driver.quiesce()`，此时 callable idle 再次接收 None。

```python
driver = AsyncSingleCycleDriver(
    clock, data, idle=lambda previous: 0 if previous is None else previous,
    encoder=lambda request: request, capacity=8,
)
```

这个例子在接受后保持上一笔输入；只有项目协议允许这种 idle 策略时才使用。
若要核对输出，不要直接 driver.submit 后无人接管响应：通过
[Agent](agents-and-reference-models.md) 或 [Scoreboard](scoreboard.md) 完成响应关联。
