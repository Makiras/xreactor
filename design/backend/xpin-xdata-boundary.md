# XData、native identity 与时钟源边界

## 结论

`XPin` 已从 Python 公共接口和 Picker 生成模板删除，本次变更明确允许 breaking
change。C++ trigger、xreactor 和生成 DUT 只持有并暴露 `XData`；`XData.xdata` 兼容
属性也一并删除，避免继续维持“外面还有一层 pin wrapper”的错误心智模型。

关于旧 `XPin` 的复核、Chisel 命名映射以及 Bundle/Interface 模型，见
[XData、Bundle 与 Interface 设计](../architecture/data-bundle-interface.md)。

```text
用户代码 / 生成 DUT / Bundle / Interface
                    |
                    v
  XData -- BindNativeData(address) --> simulator storage
    |
    v
XTriggerEngine                       C++ 热路径
```

## breaking change

Picker 的 Python 模板按端口声明生成 `XData(width, direction)`，在 mem_direct 模式
用 `BindNativeData(NativeSignalAddr(name))` 绑定到 Verilator 的真实存储，并直接把
同一对象暴露给用户和登记进 XPort。旧生成包必须重新生成；框架不再接受
`XPin(xdata, shared_event)`，也不再支持 `dut.pin.xdata`。机械迁移规则是：

```python
# old
dut.req.xdata.Set(value)
await dut.req.event.wait()

# new
dut.req.Set(value)
await RisingEdge(dut.clock)  # 或显式 Value/Condition/ClockCycles
```

继续接受 `XPin` 会引入以下问题：

- C++ 热路径依赖 Python wrapper 和 GIL；
- C++、Java、Scala 等前端没有统一的 XPin ABI；
- 生成包使用相对导入时，`pkg.xspcomm.XData` 与顶层 `xspcomm.XData` 可能具有不同
  的 Python 类身份；
- trigger 生命周期和旧 shared event 生命周期被不必要地耦合。

因此公共 trigger API 只接受直接 `XData`；返回的 `XEvent.source` 就是用户传入的
signal 对象。

## `CSelf()` 到底是什么

xcomm 的 `XData.CSelf()` 当前返回 C++ `this` 指针转换成的 `uint64_t`。它解决的是
SWIG proxy identity 问题：`XPort.__getitem__()` 可能为同一个 C++ `XData` 创建新的
Python proxy，因此两个对象的 `is`/`id()` 可以不同，而 `CSelf()` 相同。

xreactor 将 native identity 表示为 `("native", int(signal.CSelf()))`；纯 Python
backend signal 才使用 `("python", id(signal))`。它只用于一个进程、一次对象生命期内
的 driver ownership 和 trigger/program cache key，边界如下：

- 不是逻辑 signal ID，不能序列化、落盘或跨进程比较；
- 对象析构后地址可以复用，不能缓存到所属 Execution 生命周期之外；
- 持有 registration/Bundle/Driver 时必须同时持有 `XData` 强引用；
- 对外错误信息仍使用 signal path/name，不能让裸地址成为用户 API。

更长期的 backend ABI 可引入 `slot + generation` handle；在此之前，`CSelf()` 是识别
同一在世 native 对象的务实运行期键，不是用它替代 `XPin`。

## 时钟的两个对象

生成 DUT 同时存在：

- `dut.clock`：真实 HDL clock 端口，是 native-bound `XData`；
- `dut.GetXClock()`：负责 half-step、phase 和 simulator eval 的调度器。

用户可以直接写 `await FallingEdge(dut.clock)`，而 backend 又必须确认该端口确实属于
自己的调度域。仅凭“对象是 XData”不能安全判断，多时钟场景下会静默采错域。

xcomm 因而提供 `XClock.HasClockPin(XData&)`。xreactor 接受调度器本身或已注册到该
调度器的 clock XData；其他信号会在 arm 时被拒绝。这样既保留 cocotb 风格的
端口写法，也没有牺牲时钟域身份检查。

`@xtrigger(sample=RisingEdge("clock"))` 会把字符串解析到 `dut.clock`，然后经过同一
身份校验。native backend 还会从传入 XClock 的 Python 模块加载匹配的
`XTriggerEngine/XData` 类型，避免生成包相对导入导致错误的 `isinstance` 判断。

## memory-direct Cache 实证

验证使用 `example/CacheSignalCFG`，Picker 参数包含 `--rw mem_direct`。生成结果确认：

- 顶层 clock、reset、ready 等 Python 成员是直接 `XData`；
- 扁平成员、XPort 登记和通过内嵌 signal tree 绑定的 Bundle view 保持同一 XData identity；
- `GetBackendKind()` 为 `XDataBackendKind_MemDirect`；
- `await FallingEdge(dut.clock)`、`Value(dut.io_in_req_ready, ...)` 和读取同一 XData 的
  `@xtrigger` 均由 native engine 命中。

可运行示例见
[`examples/integration/cache/example_xreactor.py`](../../examples/integration/cache/example_xreactor.py)。

从 XReactor 项目根目录复现：

```bash
# 主构建必须导出当前 xcomm 的 Python SWIG API。
BUILD_XSPCOMM_SWIG=python cmake -S .. -B ../build -DCMAKE_BUILD_TYPE=Release
BUILD_XSPCOMM_SWIG=python cmake --build ../build --parallel 64

# release 脚本本身使用 --rw mem_direct；--lang python 同时选择 Python 示例。
OUT_ROOT=/tmp/xreactor-cache-run \
  ../example/CacheSignalCFG/release-verilator.sh --lang python

PYTHONPATH=/tmp/xreactor-cache-run:src \
  python3 examples/integration/cache/example_xreactor.py
```

本次实测 Cache 在复位后还会执行内部初始化，因此 `io_in_req_ready` 并非紧接着复位
释放就有效；`Value` 会持续留在 C++ sampling 热路径中，直到明确的 rising stable
phase 命中，而不是在 Python 当前时刻读取一次后返回。
