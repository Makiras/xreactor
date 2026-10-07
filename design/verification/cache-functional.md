# Cache 功能验证报告

> 后续变更：人工 pytest 功能标签、对应插件和完成率报告已移除。本文相关数字和
> 插件行为仅保留为当时的审查记录，不代表当前功能覆盖。运行命令与当前使用方式见
> [移除记录](coverage-without-test-tags-2026-09.md)及各项目 README。

2026-10-01 更新：77 项内部要求已接入全 Cache 及 Stage1/2/3 检查，新增并发仲裁、
流水交接、初始化全 set、forwarding、beat 计数、在途复位与 RTL assertion 负例。
CPU/probe 并发还发现并修正了通用 Driver 过早读取 ready 的缺陷。读 burst 后续数据
重复 demand word 的 RTL 反例单独保存；触发覆盖不表示该行为正确。
逐项契约及实测状态见[功能点明细](cache-functional-points-2026-09.md)。下文保留历史记录。

最终回归为 27 passed，合并 394 个内部场景 bins 激活 100%，76/77 项符合本基线关闭条件。
旧 overlap “丢响应”结论已更正：同步探针在同拍 refill 输入更新前登记了 ready。
修正后第二请求实际接受于 half-tick 382、响应于 410；异步重叠回归及 300 笔随机压力也通过。
该旧记录不能作为 RTL 缺陷证据。当前未关闭的设计属性是 CPU read burst 后续数据错误。
完整结果见2026-10-01 证据（本地产物：`rtl-property-evidence-2026-10-01/results.json`）。

## 历史重构验证（2026-09-29）

本轮使用当前 Picker/xspcomm 重新生成带 signal_tree、VPI 和 coverage 的 memory-direct
DUT。可复现构建和运行命令见[Cache 示例说明](../../examples/integration/cache/README.md)。
以下历史记录保留当时的定位过程；当前功能与数值以上方 2026-10-01 更新为准。

CacheDriver 继承 SyncDriver，保留项目已有时序；八组接口均已完成 Bundle/Interface
绑定。经用户明确授权，coherence 增加项目内 probe/release 流量；框架层未增加协议假设。

新增零 mask、8 个独立 byte mask、全 mask，全部 refill 起始 word 及整行 hit 验证，
干净行替换不写回、脏 victim 全部 8 word 数据核对。已有 write allocate、背压、MMIO
和三 set 冲突随机流量保留。Scoreboard 核对读数据和 Monitor 请求快照，附真实接受与
响应事件；新增 4 个 coverpoint（operation/path/word/mask）及 operation×path cross。

| seed | 随机操作 | 上游事务 | checked reads | refill | writeback | memory 请求 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 定向，无随机 | 0 | 129 | 111 | 18 | 1 | 26 |
| `1` | 300 | 558 | 411 | 196 | 86 | 884 |
| `0x1234` | 300 | 570 | 411 | 205 | 100 | 1005 |
| `0xdeadbeef` | 300 | 564 | 411 | 201 | 94 | 953 |

以上 campaign 均通过，CPU 与 coherence 覆盖组均为 100%，每组 2 笔 MMIO。
每组另有 18 次 coherence probe、146 个响应 beat，不计入表中的 CPU 事务数。
新增定向流量改变了内部替换状态，因此随机 refill/writeback 数量不同于先前基线。
写响应 cmd/user 和写后读另有检查，checked reads 只统计读数据比较，不伪称每笔写都
返回了可比较的数据。后台异常在退出传播；即使检查失败，也继续关闭 task、Monitor、
Driver、backend 并保存 run.json、功能覆盖及 HTML。故意损坏返回数据的实验产生
ScoreboardMismatch，保留 failed 产物，退出后无残留 asyncio 任务。

overlap 记录只捕获特定响应超时；第二笔读的数据错误不会被归为已知缺陷，
即使打开 allow-known-bugs 也实际传播 ScoreboardMismatch。随机读的期望来自独立逻辑
状态与初始内存值，不从可能被错误 writeback 污染的 backing memory 推导。

**已知 overlap 缺陷仍未解决。** 当前异步 campaign 不一定能命中它；同步 StepHalf
探针依旧观测到第一响应 half-tick 377、第二请求接受 380，但之后没有第二响应。
脚本按预期断言失败。正常 campaign 的通过不能替代该探针，不能得出 DUT 已无缺陷。

未验证 CPU/coherence 并发仲裁、flush 的精确语义、非 8-byte size、非对齐/非法请求。
100% 仅对应上述定义的 bin，不代表全部 Cache 功能或 RTL 行覆盖。

## Coherence 项目增量

读取现有 CacheStage3 RTL 后，按其实际协议加入 CoherenceAgent：

| 请求 / 响应 | 项目规则 |
| --- | --- |
| probe 请求 | cmd=8，size=3，地址选择起始 word |
| miss | 仅一个 cmd=8 响应头；不产生 refill 或 MMIO 访问 |
| hit | cmd=C 响应头，随后 8 个 release beat；前七拍 cmd=0，末拍接受时 cmd=6 |
| 顺序 | 从请求 word 开始，在 64-byte line 内回绕 |
| 状态 | probe 不 invalidate、不向 backing memory 写回；脏数据应直接出现在 release 中 |

ProbeDriver 继承 SyncDriver，声明请求信号和响应 ready 的 ownership；具名
ReadyValidMonitor 采集不可变响应快照。CoherenceAgent 实例注册给 Execution，项目
probe 方法组装一个响应头及可选整行数据，并用独立期望 line 做直接 Scoreboard 比较。
没有把多拍接口硬套入通用 Agent 的单响应检查连接，没有修改通用组件或调度器。

两次 miss 分别无背压/头部背压；8 次 clean、8 次 dirty 分别覆盖全部起始 word，
其间停住 header、首个数据、中间数据和最后数据 beat。dirty 场景使用 byte mask
合并后的独立 line 作为期望。每次 probe 检查没有新增 memory/MMIO 流量；最后重新
读取全行，确认仍然 hit 且 backing memory 保持旧数据。

输入接受和完整响应各有 100 周期预算，结束观察 3 周期；拒绝输入接受前的旧响应和
观察窗口内额外响应。末拍 cmd 依赖 ready 是当前 RTL 的实际行为：检查 ready 持续为低
时的稳定性、接受时的最终序列，不宣称 ready 翻转前后 cmd 不变，也不推广这条规则。

一个项目回归文件 test_cache_coherence.py 运行正常 campaign、六种 Monitor 边界故障
（header/data/last 错误、missing、duplicate、stale），以及外部取消。故障注入改变
验证端观测，不修改 RTL；只有确实触发预期错误才算通过。退出后检查 native watcher=0、
backend lease 释放、Monitor 关闭、driver ownership 释放、请求 valid/响应 ready 归零，
无新遗留任务；外部取消不影响宿主任务。

coherence-transactions.json 保存接受 tick 和各响应 beat 的 tick/cmd/data，失败时保留
部分记录及原始错误。功能覆盖增加 state/start_word/stalled 和 state×stalled。
原 pytest 三个标签仅区分正常行为、故障检测和取消清理，当时为 **8 passed、3/3 PASS**；
另完成上表三组各 300 次随机操作。后续按明确验收条件细化，完整定义见
[verification_plan.json](../../examples/integration/cache/verification_plan.json)。

第一版 33 点中有 22 个正常要求：11 个 CPU 数据、替换、旁路和观察要求，以及 11 个 coherence
状态、回绕、分拍背压、隔离和保留行要求。六类故障各自一个点，取消一点。正常要求共用
现有 campaign，并检查 probe 拍数、起始 word 和背压位置的实际证据；故障按参数实例关联。
现有测试仍为 8 项，没有为增加标签而重复仿真。

当时四个 NOT_RUN 分别为 CPU valid 连续性、CPU overlap 缺陷、CPU/probe 并发及 flush。
逐条核对时发现 CPU response 循环仅在 valid 为高时比较数据，尚不能检查短暂撤回 valid，
所以没有将这一要求归入已完成的响应快照稳定性。独立 overlap 探针的已知失败在计划中明确
注明，尚未绑定本 pytest 报告的测试证据；NOT_RUN 不能解释成 DUT 没有该缺陷。
按当时计划运行结果为 **8 passed、29/33 PASS、4 NOT_RUN，计划完成率 87.88%**。
完整命令及按场景查看报告的方法见上述 Cache 示例 README。

随后按实际 RTL 补充 77 个内部机制义务，完整计划现为 110 点，当前真实回归仍为
8 passed、29/110 PASS、81 NOT_RUN。新增点覆盖流水控制、lookup/replacement、forwarding、
主/子 FSM、数组初始化及仲裁、refill/writeback、提前响应和 burst；没有绑定内部断言的点
全部保留 NOT_RUN。原 flush 定义同时纠正：当前写型配置的 Stage3 明确禁止 flush，应验证
启用 RTL assertion 后的非法操作诊断，不能作为普通清空缓存场景。源码基线和逐类要求见
[RTL 功能点评审](rtl-feature-plan-2026-09.md)。

## 历史验证与定位过程


> 验证日期：2026-09-15
> DUT：`example/CacheSignalCFG/Cache.v` 生成的 `DUTCacheSignalCFG`
> 接入：Picker `mem_direct` XData + XCommClockBackend + XReactor

> 2026-09-29 代码调整：文中历史使用的 ReadyValidDriver 已移除，当前 CacheDriver
> 继承 SyncDriver 并复用相同握手 helper。以下真实 DUT 测量仍保留原验证日期。

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
这些 Interface/Bundle。当时 Cache 场景不产生 coherence 流量，只有结构/方向绑定覆盖；
本轮新增的协议功能验证见开头的 Coherence 项目增量。

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
当时的 `ReadyValidDriver` 发送（现已改为项目 CacheDriver/SyncDriver）；同时把 DUT
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

旧生成包和早期命令已由[当前示例 README](../../examples/integration/cache/README.md)
中的构建、campaign 与独立探针命令替代。调试可用 CACHE_TRACE=1。

## 当时尚未覆盖（现状见开头）

- coherence probe/release（本轮已增加定向验证）；
- `flush[0]` pipeline kill 的精确事务语义；
- `flush[1]`，因为当前生成 RTL 明确带有“only allow to flush icache” fatal assertion；
- 非 8-byte size、非对齐地址及非法命令的接口契约；
- 更长、更随机的 memory request backpressure/response latency 组合；
- 独立 simulator 差分和 waveform，用于把剩余缺陷进一步定位到 Cache RTL 还是
  Verilator wrapper。

当时建议的下一步优先级是打开 waveform 定位这个 overlap 协议问题，再扩展 coherence、
flush 和非法输入测试。修复后，当前 probe 应从“已知缺陷检测”转为普通 hard
assertion。
