# Cache 功能验证报告

> 验证日期：2026-09-15
> DUT：`example/CacheSignalCFG/Cache.v` 生成的 `DUTCacheSignalCFG`
> 接入：Picker `mem_direct` XData + XCommClockBackend + XReactor

## 结论

这次验证不是只检查 `await` 能否运行，而是把 Cache 当作 DUT，提供可执行的
backing-memory/MMIO responder 和参考模型，并运行确定性及冲突密集型随机序列。

目前确认 Cache 的主要数据功能可以工作：read miss/refill、read hit、masked write
hit、partial write-allocate、4 路替换、dirty writeback 和 MMIO 数据旁路均通过参考
模型核对。与此同时，发现一个状态/时序相关的协议问题：read miss 首 beat 提前响应
后，如果依据 `io_in_req_ready` 接受下一请求，下一请求会永久没有响应。该 probe 在
每次随机序列前从固定 clean-reset 状态运行，四个 seed 均稳定复现。

该问题曾在 XReactor verifier 中复现，并持续在完全绕过 asyncio/XReactor 的同步
`StepHalf` probe 中复现，因此可以排除 Python event-loop 和 XReactor phase barrier。
加入 passive monitor 后异步 task 排序变化，异步 verifier 不再稳定触发该重叠窗口；
这不代表 DUT 已修复，固定同步 probe 仍是该缺陷的权威回归。剩余定位范围是 Cache
设计/生成 RTL 及 Verilator wrapper；从外部端口看，它已经明确违反 ready/valid
接受后的 response liveness。

端口方法学回归同时显式绑定了 signal tree 中的八个 ready-valid 子树：CPU req/resp、
memory req/resp、MMIO req/resp、coherence req/resp。绑定入口严格验证
`valid/ready/bits` shape、方向和 XData identity；CPU/memory/MMIO 的实际读写已迁移到
这些 Interface/Bundle。当前 Cache 场景不产生 coherence 流量，因此 coherence 只有
结构/方向绑定覆盖，不能声称做过其协议功能验证。

## DUT 行为核对

从生成 RTL 得到的结构和协议如下：

| 项目 | 行为 |
| --- | --- |
| 容量 | 32 KiB |
| 组织 | 4 way × 128 set |
| cache line | 64 B，8 个 64-bit beat |
| 地址拆分 | tag `[31:13]`、set `[12:6]`、word `[5:3]` |
| 普通读/写命令 | `0x0` / `0x1` |
| refill 请求 | `cmd=0x2` |
| refill 响应 | 中间 `0x4`，最后 `0x6` |
| writeback | 前 7 beat `0x3`，最后 `0x7` |
| 上游响应 | read `0x6`，write `0x5` |
| replacement | 4 路内部选择；验证器不假设固定 victim |
| MMIO | `0x3xxxxxxx` 及 RTL 判定的另一段高地址区域旁路 Cache |

refill 不是从 line base 固定顺序返回，而是从请求 word 开始，8 beat 后在 line 内
wrap。验证器按这个实际协议生成响应。例如请求 word 5 时，beat 顺序为
`5, 6, 7, 0, 1, 2, 3, 4`。

## 验证器组成

可执行脚本是：

```text
examples/integration/cache/cache_functional_xreactor.py
```

它包含四部分：

- `CacheDriver`：保持 request valid/payload 到明确的 falling-stable sample，并在下一
  rising edge 完成握手；检查 response cmd、data、user 和 backpressure 稳定性。
- `MemoryModel`：响应 wrap refill，接收 8-beat writeback，在 write-last 后返回 write
  response，并记录所有下游事务。
- `MmioModel`：实现 read/write MMIO 空间并记录每次下游握手。
- `ReferenceMemory`：64-bit word 模型和逐 byte `wmask` 合并，用作 scoreboard。

新生成输入端口是直接 XData，并断言 backend kind 为
`XDataBackendKind_MemDirect`。因此这里没有使用 MemoryBackend 替代真实 DUT。

当前重构从生成 DUT 内嵌的 signal tree metadata 绑定上游 request `Bundle`，由
`ReadyValidDriver` 发送；同时把 DUT
产生的下游 memory request 组成 monitor-role `ReadyValid`，由
`ReadyValidMonitor` 原子快照并与既有 MemoryModel 逐笔核对。一次 80-operation 的
direct-XData 回归通过，记录 150 个上游 transaction、295 个 memory request、63 个
read burst、29 个 writeback 和 2 个 MMIO transaction。response、memory response
和 MMIO channel 尚未全部统一迁移到同一 Interface API，因此 D5 仍是部分完成。

## 确定性序列

| 序列 | 检查点 | 结果 |
| --- | --- | --- |
| cold read miss，起始 word=5 | 请求地址、wrap beat 顺序、首词数据、user | 通过 |
| refill 后读取整行 8 word | 全部 hit、无新增 memory read | 通过 |
| masked write hit | byte merge、read-after-write、backing memory 保持旧值 | 通过 |
| partial write miss | read allocate、首 beat mask merge、后续 hit | 通过 |
| 同 set 五个 tag | 4-way fill、dirty victim、8-beat writeback、victim 数据 | 通过 |
| memory request backpressure | valid、addr/cmd/size/mask 连续 3 周期稳定 | 通过 |
| MMIO read/write | 数据、mask、一次上游请求对应一次下游握手 | 通过 |
| response backpressure | valid 期间 cmd/data/user 稳定 | 通过 |
| early-response overlap | 第二请求 response liveness | 失败，可稳定复现 |

`io_empty` 仅表示请求 pipeline 为空，不表示没有 dirty line。基础数据序列在发起下一
事务前等待 `io_empty`，以免已知的 overlap 缺陷污染其他功能结论。overlap probe
在第一次 clean reset 后独立执行，随后再次 reset 才运行其余序列。

## 随机验证

随机地址集中在 3 个 set，每个 set 使用 10 个不同 tag，强制持续替换；读写比例约
55%/45%，写使用随机 64-bit 数据及非零随机 byte mask。每次写后立即读回，其他读
与独立逻辑内存比较；dirty line 被替换时，再由 backing-memory scoreboard 核对完整
writeback。

实测结果：

| seed | 随机操作 | 上游事务 | refill | dirty writeback | memory 请求 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | 300 | 456 | 200 | 94 | 952 |
| `0x1234` | 300 | 467 | 207 | 104 | 1039 |
| `0xdeadbeef` | 300 | 461 | 186 | 97 | 962 |

三组数据一致性全部通过。overlap probe 在独立于随机流量的固定 reset 状态执行，
因此三个 300-operation 回归都得到相同的 timeout 结论。

## 已排除的误报：MMIO 请求重复

早期版本的异步 driver 曾观察到：一个上游 MMIO read/write 产生两个下游请求。
纯同步 `XClock.StepHalf()` 差分只观察到一次请求和一次响应，随后定位到 testbench
driver 在 falling phase 拉高 valid 后又等待下一个 FallingEdge 才检查 ready，导致
valid 实际跨过两个 rising edge，同一请求被合法接收两次。

修正方式是在当前 falling-stable phase 驱动 valid/payload，执行一次组合刷新，在
同一 phase 检查 ready，然后只跨过一个 rising sampling edge。修正后两个上游 MMIO
事务稳定对应两个下游握手。

独立复现脚本：

```text
examples/integration/cache/cache_direct_protocol_probe.py
```

这个误报本身说明验证框架需要提供标准 Decoupled driver primitive：如果每个 testbench
都手写 phase 循环，很容易制造跨两个采样沿的重复事务。

## 缺陷：early miss response 后续请求可能丢失

Cache 会在 refill 第一 beat 后提前向上游返回 demand word，这个优化本身符合 RTL
意图。问题出现在上游收到该响应后继续遵守 `io_in_req_ready` 发下一笔：第二笔已经
完成 ready/valid 接受，但在失败状态下之后没有任何 response，也没有新的 memory
request，最终 timeout。例如：

```text
response timeout for addr=0x2804c8 cmd=0x0;
req_ready=1 resp_valid=0 mem_req_valid=0 mem_resp_valid=0;
accepted_tick=276
```

纯同步 probe 给出相同结论：第一笔 `user=0x101` 在 half-tick 377 响应，第二笔在
half-tick 380 以 ready/valid 接受，之后 120 个同步周期内只记录到第一笔响应，没有
`user=0x102`。这说明问题不是 asyncio task 恢复顺序造成的。

等待 `io_empty` 后再发请求可绕开问题，但这不是上游按 Decoupled 接口应承担的隐含
约束。若 Cache 不允许 refill 未完成时接受后续请求，它必须保持
`io_in_req_ready=0`；若允许接受，则必须保证每笔请求只产生一次、且按正确 user
对应的响应。

## 运行方式

默认模式把已知协议缺陷视为失败：

```bash
PYTHONPATH=/tmp/xreactor-cache-standard:$PWD/src \
  python examples/integration/cache/cache_functional_xreactor.py \
  --seed 0x1234 --random-ops 300
```

为了继续收集完整覆盖数据，同时报告但不因已知缺陷返回非零：

```bash
PYTHONPATH=/tmp/xreactor-cache-standard:$PWD/src \
  python examples/integration/cache/cache_functional_xreactor.py \
  --seed 0x1234 --random-ops 300 --allow-known-bugs
```

设置 `CACHE_TRACE=1` 可打印每次 upstream response、memory request/response 和 MMIO
request，便于保留最小复现。

绕过 XReactor 的同步差分命令如下；它会在确认 overlap request 丢失时以 assertion
失败：

```bash
PYTHONPATH=/tmp/xreactor-cache-standard:$PWD/../example/CacheSignalCFG:$PWD/src \
  python examples/integration/cache/cache_direct_protocol_probe.py
```

## 尚未覆盖

- coherence probe/release；
- `flush[0]` pipeline kill 的精确事务语义；
- `flush[1]`，因为当前生成 RTL 明确带有“only allow to flush icache” fatal assertion；
- 非 8-byte size、非对齐地址及非法命令的接口契约；
- 更长、更随机的 memory request backpressure/response latency 组合；
- 独立 simulator 差分和 waveform，用于把剩余缺陷进一步定位到 Cache RTL 还是
  Verilator wrapper。

下一步优先级应是打开 waveform 定位这个 overlap 协议问题，再扩展 coherence、
flush 和非法输入测试。修复后，当前 probe 应从“已知缺陷检测”转为普通 hard
assertion。
