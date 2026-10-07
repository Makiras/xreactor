# Cache 功能点和验证契约

分析基线为 2026-09-30 本地 RTL，实施及证据核对更新于 2026-10-01。范围：`CacheSignalCFG generated write-capable Cache, 4 ways/128 sets/8 words per line`。
共 110 项要求：内部 77、外部 25、验证器自身 8。要求条数和 pytest PASS 不作为功能覆盖率分母。

内部 77 项均有真实 RTL 观察，共 394 个必需场景 bins；合并激活覆盖为 100%，76 项满足本基线的关闭条件。
逐项计数、来源和比较结果见实测检查（本地产物：`rtl-property-evidence-2026-10-01/cache-checks.json`），原始 schema/bin/origin 见合并覆盖数据库（本地产物：`rtl-property-evidence-2026-10-01/cache-internal-coverage.json`）。

关闭条件为实际激活、全部必需 bins 命中、属性比较通过且无观察器错误。该结论只针对已声明义务，不证明规格已经穷尽；模块级路径证据不自动证明完整系统集成。

## RTL 基线和观察能力

- `example/CacheSignalCFG/Cache.v`，SHA-256 `0ad44cce29d699db56b401d1c9fe87bb217a0a19bb6fb8dadc39e4fac04e9273`。

当前导出 1121 个排除 __V 覆盖计数后的 direct 信号，另枚举 1121 个 VPI 信号；见观察清单（本地产物：`rtl-internal-observation-inventory-2026-09-30.json`）。观察器按显式路径和宽度绑定，缺失即失败。

普通时序属性在驱动稳定后读取边沿前条件，紧邻上升沿后比较提交结果。独立接受/响应账本、字节模型及已知 metadata/data 写账本作为 oracle；未初始化 SRAM 数据不假定为零。属性先记录真实激活再比较，失败仍保留实际证据。

## 尚未关闭的 RTL 属性

`CACHE-INT-BURST-READ-HIT` 的 start0/start7/stalled 均实际触发，但两个起始位置的下一 CPU burst 数据重复 demand word，未返回对应 SRAM 下一 word。两个预期失败测试 PASS 仅说明反例可复现。该要求 `closed=false`，后续完整八拍结束行为也不能据此宣称正确。
数值及状态见RTL 反例（本地产物：`rtl-property-evidence-2026-10-01/rtl-defects.json`）。当前工作修改验证框架和 case；Picker 的外部 RTL 未修改。

旧 overlap 探针失败已定位为边沿前输入尚未全部稳定就登记 ready。修正同步探针和通用 Driver 后，第二请求真实接受于 half-tick 382、响应于 410；旧证据不能建立 overlap RTL 缺陷。
见同步独立证据（本地产物：`rtl-property-evidence-2026-10-01/direct-protocol-probe.json`）及 native `test_cpu_request_overlaps_remaining_refill`。

## 功能点明细

### CPU 数据路径

**CACHE-REFILL-WRAP 八种首 word 的 refill 回绕**

分别从一行的 8 个 word 发起 cold miss；下游首地址为请求地址，随后整行八个 word 读回正确，恰好一次 refill。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / first_word 循环。

**CACHE-READ-HIT refill 后整行命中**

安装 cache line 后读全部 8 个 word；逐笔数据正确且无额外下游 refill。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / line_a 和 first_word 循环。

**CACHE-WRITE-HIT 部分写命中及延迟写回**

已安装行用 mask=0x3c 写入；读回等于逐字节合并值，backing memory 在替换前保持旧值。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / hit_addr。

**CACHE-WRITE-ALLOCATE 部分写未命中分配**

未安装行用 mask=0xa5 写入；恰好一次 refill，读回合并值，backing memory 尚未改变。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / write_miss_addr。

**CACHE-BYTE-MASK 零、单字节及全字节写掩码**

对已安装行依次使用零 mask、8 个 one-hot mask 和全 mask；每次读回与独立合并值相符，backing 保持旧值。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / byte_mask 循环。

### CPU 替换

**CACHE-CLEAN-REPLACE 干净行替换不写回**

连续安装同一 set 的八个不同 clean tag，超过四路容量；全部读回正确且 writeback 数不增加。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / clean_writebacks。

**CACHE-DIRTY-REPLACE 四路脏行替换保全整行**

填满同一 set 四路并各写一个 word，再读第五 tag；恰好一次 writeback，victim 必须属于四行之一，其八个 word 均正确。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / expected_dirty 和 victim。

### CPU 时序

**CACHE-MEMORY-STALL 下游请求受阻保持**

memory request ready 拉低三个周期；valid 持续有效且 addr/cmd/size/wmask 不变，解除背压后数据正确。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / held_request。

**CACHE-CPU-RESPONSE-STALL CPU 读响应受阻保持**

已安装行 CPU response 背压三周期；valid 从首次出现持续到接受，data/cmd/user 全部保持稳定，最终与独立模型一致。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / CacheDriver.request。

### MMIO

**CACHE-MMIO-BYPASS MMIO 读写旁路**

一次读和 mask=0xf3 的写；读值及写后 MMIO 空间正确，memory bus 无新请求，观察十二周期后下游 MMIO 恰好两次请求。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / mmio_addr；main 的 protocol_issues 检查。

### 观察链路

**CACHE-MONITOR-SNAPSHOTS Monitor 与 responder 记录一致**

所有已接受 memory 请求逐笔比较 addr/cmd/size/wmask/wdata；数量、顺序和内容完全一致。

验证层：`testbench`。

检查入口：test_real_cache_coherence_campaign / verify_cache / cache.memory-snapshots Scoreboard。

### Coherence

**CACHE-COH-MISS probe miss 仅响应头**

未安装地址在无背压和头部背压两种情况下 probe；每笔仅一拍 miss header，不发数据。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / 两次 miss；CoherenceAgent.probe。

**CACHE-COH-CLEAN clean hit 的整行 release**

已完成 refill 的 clean line 被 probe；hit header 后恰好八个数据，逐 word 与独立 line 模型一致。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / clean_words；CoherenceAgent.probe。

**CACHE-COH-DIRTY dirty hit 包含修改字节**

对已安装行使用 mask=0x5a 写入后 probe；八个数据包含合并后的 dirty word，其他字节不变。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / dirty_words；CoherenceAgent.probe。

**CACHE-COH-WRAP release 从请求 word 回绕**

clean 和 dirty 两种状态分别覆盖 start_word=0..7；八拍按 (start_word+i)%8 返回，第八数据拍使用末拍命令。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / 两组 start_word；CoherenceAgent.probe 的序列比较。

### Coherence 时序

**CACHE-COH-STALL-HEADER 头部背压**

clean/dirty hit 的第 0 拍停两周期；ready 持续低时 valid/data 稳定，接受后的完整 cmd/data 序列正确。末拍 cmd 按 RTL 接受条件检查，不要求 ready 翻转前后 cmd 不变。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / stall_positions；CoherenceAgent._stall。

**CACHE-COH-STALL-FIRST 首数据拍背压**

clean/dirty hit 的第 1 拍停两周期；ready 持续低时 valid/data 稳定，接受后的完整 cmd/data 序列正确。末拍 cmd 按 RTL 接受条件检查，不要求 ready 翻转前后 cmd 不变。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / stall_positions；CoherenceAgent._stall。

**CACHE-COH-STALL-MIDDLE 中间数据拍背压**

clean/dirty hit 的第 4 拍停两周期；ready 持续低时 valid/data 稳定，接受后的完整 cmd/data 序列正确。末拍 cmd 按 RTL 接受条件检查，不要求 ready 翻转前后 cmd 不变。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / stall_positions；CoherenceAgent._stall。

**CACHE-COH-STALL-LAST 末数据拍背压**

clean/dirty hit 的第 8 拍停两周期；ready 持续低时 valid/data 稳定，接受后的完整 cmd/data 序列正确。末拍 cmd 按 RTL 接受条件检查，不要求 ready 翻转前后 cmd 不变。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / stall_positions；CoherenceAgent._stall。

### Coherence

**CACHE-COH-ISOLATION probe 不产生 CPU/memory/MMIO 事务**

18 笔 probe 前后比较 memory/MMIO 请求数不变，完成时 CPU response valid 为低；这是串行 probe 场景，不代表并发仲裁已验证。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / probe 辅助函数。

**CACHE-COH-RETAIN probe 后保留 cache line**

clean/dirty probe 后 CPU 读回全部八个 word；无新 refill，数据正确，backing memory 仍为旧的 clean 值。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / verify_cache / dirty_words 后续 CPU read。

**CACHE-COH-QUIET 每笔 probe 后有限静默检查**

每笔 probe 完成后观察三周期并在 campaign 末尾再次检查；不得出现额外 coherence 响应。窗口外不作无限保证。

验证层：`design_external`。

检查入口：test_real_cache_coherence_campaign / CoherenceAgent.check_quiet。

### 检查器

**CACHE-CHECK-HEADER 拒绝错误响应头**

翻转 header cmd，必须抛含 cmd 差异的 ScoreboardMismatch。 注入在 Monitor 交付边界；故障必须保留 failed 产物并清理组件，allow_known_bugs 不能屏蔽这些错误。

验证层：`testbench`。

检查入口：test_coherence_rejects_faulty_observations[header]。

**CACHE-CHECK-DATA 拒绝错误 release 数据**

翻转一个数据位，必须抛含 data 差异的 ScoreboardMismatch。 注入在 Monitor 交付边界；故障必须保留 failed 产物并清理组件，allow_known_bugs 不能屏蔽这些错误。

验证层：`testbench`。

检查入口：test_coherence_rejects_faulty_observations[data]。

**CACHE-CHECK-LAST 拒绝错误末拍命令**

翻转最后数据拍 cmd，必须抛含 cmd 差异的 ScoreboardMismatch。 注入在 Monitor 交付边界；故障必须保留 failed 产物并清理组件，allow_known_bugs 不能屏蔽这些错误。

验证层：`testbench`。

检查入口：test_coherence_rejects_faulty_observations[last]。

**CACHE-CHECK-MISSING 拒绝漏拍**

漏掉一个数据拍，在响应预算内不能收齐九拍，必须超时并报告 received 8/9 beats。 注入在 Monitor 交付边界；故障必须保留 failed 产物并清理组件，allow_known_bugs 不能屏蔽这些错误。

验证层：`testbench`。

检查入口：test_coherence_rejects_faulty_observations[missing]。

**CACHE-CHECK-DUPLICATE 拒绝重复拍**

重复交付一个观察快照，残留真实响应必须被静默窗口检查拒绝。 注入在 Monitor 交付边界；故障必须保留 failed 产物并清理组件，allow_known_bugs 不能屏蔽这些错误。

验证层：`testbench`。

检查入口：test_coherence_rejects_faulty_observations[duplicate]。

**CACHE-CHECK-STALE 拒绝旧响应**

把观察 tick 改为早于本次 probe 接受时刻，必须报告 precedes this probe。 注入在 Monitor 交付边界；故障必须保留 failed 产物并清理组件，allow_known_bugs 不能屏蔽这些错误。

验证层：`testbench`。

检查入口：test_coherence_rejects_faulty_observations[stale]。

### 生命周期

**CACHE-COH-CANCEL release 中途外部取消**

收到首个 release 数据时取消 campaign；CancelledError 传播，失败状态保留，任务/watcher/信号 ownership 释放，Agent/Monitor/Driver 关闭，宿主任务仍运行。

验证层：`testbench`。

检查入口：test_cancel_during_release。

### CPU 时序

**CACHE-CPU-VALID-HOLD CPU 受阻响应 valid 连续性**

CPU 受阻响应 valid 必须持续到接受；CacheDriver 当拍拒绝 valid 撤回，独立负例在观察边界撤回一拍并核对明确异常。故障不贡献 DUT bins。

验证层：`design_external`。

检查入口：test_cpu_checker_rejects_valid_withdrawal；正常 response stall 与 test_refill_finishes_while_cpu_response_is_stalled。

### 待验证缺陷

**CACHE-CPU-OVERLAP early-response 后重叠 CPU 请求**

独立同步探针已发现第二请求被接受后无响应；当前 pytest campaign 不能稳定复现，不能以其通过认定修复。需要将稳定复现的激励与检查落实为回归；普通 campaign 的通过不能关闭该缺陷。

验证层：`design_external`。

检查入口：cache_direct_protocol_probe.py（单独运行的已知失败）。

### 并发仲裁

**CACHE-COH-CPU-CONCURRENT CPU 与 coherence 并发仲裁**

CPU/probe 同时请求时固定 probe 优先；release 与 CPU 的 SRAM 读竞争时端口0优先并最终完成。另在 CPU refill/writeback 进行中提交 probe，核对两端完成、CPU 数据及八拍 release。

验证层：`design_external`。

检查入口：test_probe_competes_with_cpu_and_sram；test_probe_waits_for_cpu_memory_transaction[refill/writeback]。

### 设计配置约束

**CACHE-FLUSH 当前写型 Cache 禁止 Stage3 flush**

当前可写 RTL 禁止 Stage3 flush；开启 --assert 的独立进程驱动 io_flush，保存真实违例条件并核对 only allow to flush icache 断言。该负例不视为正常 cache 清空。

验证层：`design_external`。

检查入口：test_stage3_rtl_assertions[flush] / rtl-assertion.log。

### 设计内部 / 流水线准入与退休

**CACHE-INT-PIPE-S1-JOINT-READY Stage1 同时取得两路 SRAM 许可**

触发：metadata/data ready 分别阻塞，再共同 ready。检查：只有两路 ready 且流水允许时请求向 Stage2 前进；单路完成不能丢请求。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:42`；module `CacheStage1`；符号 `io_in_ready`。
实际观察：s1 两路 SRAM ready、s1 输入/输出接受。
必需场景：`meta_blocked`；`data_blocked`；`both_ready`。

实测：242 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-PIPE-S1-INDEX metadata/data 地址分解一致**

触发：跨 word、set、tag 边界的地址进入 Stage1。检查：metadata 索引为 addr[12:6]，data 索引为 {set,addr[5:3]}，改变 tag 不改变数组行索引。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:51`；module `CacheStage1`；符号 `io_metaReadBus_req_bits_setIdx`。
实际观察：s1 两路读地址与独立地址分解。
必需场景：`word_boundary`；`set_boundary`；`tag_boundary`。

实测：212 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-PIPE-S2-HOLD Stage1→2 payload 装载与保持**

触发：Stage1 接受新请求和 Stage2 受阻两种情况。检查：只在上游接受时更新寄存 payload，受阻时 addr/cmd/size/mask/data/user 保持。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:2833`；module `Cache`；符号 `always @(posedge clock)`。
实际观察：valid、s2_io_in_bits_r_*、s1 接受。
必需场景：`load`；`stall`；`replace`。

实测：398 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-PIPE-S3-HOLD Stage2→3 上下文原子装载**

触发：Stage2 接受传给 Stage3；另施加 Stage3 受阻。检查：请求、hit/waymask/mmio、forwarding 及四路数据/metadata 同时锁存，受阻不部分更新。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:2866`；module `Cache`；符号 `if (_T_4)`。
实际观察：valid_1、s3_io_in_bits_r_*、s2 接受。
必需场景：`load`；`stall`；`same_cycle_finish_new`。

实测：1627 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-PIPE-RETIRE 退休不能等同于早期响应**

触发：read miss 提前交付 demanded word，后续 refill 尚未结束。检查：旧 Stage3 请求保持有效直到真正 finish；同拍新请求与 finish 时替换优先且无丢失。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:2394`；module `Cache`；符号 `s3_io_isFinish`。
实际观察：valid_1、s3_io_isFinish、alreadyOutFire、输入/输出序号。
必需场景：`early_response`；`final_refill`；`finish_and_new`。

实测：113 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-PIPE-S2-CONSUME Stage2 valid 的消费与补入**

触发：Stage2 被 Stage3 接受，分别有/无 Stage1 同拍补入。检查：无补入则清空，有补入则保持 valid 且 payload 对应新请求。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:2383`；module `Cache`；符号 `valid`。
实际观察：顶层 valid、s1/s2 握手及 payload。
必需场景：`consume_only`；`consume_and_fill`。

实测：223 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-PIPE-EMPTY io_empty 只表达流水占用**

触发：空流水、仅 Stage2、仅 Stage3、两级占用；另保留 dirty 行。检查：io_empty 仅当两级 valid 均低为高；dirty 行存在不影响它。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:2696`；module `Cache`；符号 `assign io_empty`。
实际观察：valid/valid_1、io_empty、已知 dirty line。
必需场景：`empty_clean`；`empty_dirty`；`s2_only`；`s3_only`；`both`。

实测：4033 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / 命中、替换与地址属性

**CACHE-INT-LOOKUP-HIT-EACH-WAY 四路 valid 与 tag 命中**

触发：每路分别安装目标 tag，同时改变其他路内容。检查：只选 valid 且 tag 相等的路；输出 hit/waymask 与独立 tag/valid 模型一致。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:156`；module `CacheStage2`；符号 `_hitVec_T_2`。
实际观察：metaWay_*、hitVec、hit、waymask。
必需场景：`way0`；`way1`；`way2`；`way3`。

实测：334 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-LOOKUP-INVALID-TAG 无效行的旧 tag 不可命中**

触发：某路 tag 等于请求但 valid=0。检查：该路 hitVec=0；不能因残余 tag 产生 hit。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:149`；module `CacheStage2`；符号 `metaWay_0_valid`。
实际观察：有效位、tag、hitVec。
必需场景：`way0`；`way1`；`way2`；`way3`。

实测：298 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-LOOKUP-NO-INPUT 无输入时不产生有效命中**

触发：io_in_valid=0，数组数据恰巧与请求地址相同。检查：hitVec/hit 必须为零，不能触发写回或命中副作用。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:214`；module `CacheStage2`；符号 `io_out_bits_hit`。
实际观察：s2 输入 valid、hitVec、s3 副作用门控。
必需场景：`tag_equal`；`tag_unequal`。

实测：3639 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-LOOKUP-INVALID-FIRST 无效路优先于替换候选**

触发：miss 且至少一条 invalid，LFSR 候选指向 valid way。检查：分配 invalid way，不驱逐任何现存有效行。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:175`；module `CacheStage2`；符号 `_waymask_T`。
实际观察：invalidVec、victimWaymask、waymask。
必需场景：`one_invalid`；`multiple_invalid`。

实测：111 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-LOOKUP-INVALID-PRIORITY 多个 invalid way 的优先顺序**

触发：遍历非零 invalidVec 组合。检查：选择最高编号的 invalid way；各组合的输出须为 one-hot。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:172`；module `CacheStage2`；符号 `_refillInvalidWaymask_T_3`。
实际观察：invalidVec、refillInvalidWaymask。
必需场景：`invalidVec=1`；`invalidVec=2`；`invalidVec=3`；`invalidVec=4`；`invalidVec=5`；`invalidVec=6`；`invalidVec=7`；`invalidVec=8`；`invalidVec=9`；`invalidVec=10`；`invalidVec=11`；`invalidVec=12`；`invalidVec=13`；`invalidVec=14`；`invalidVec=15`。

实测：111 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-LOOKUP-ALL-VALID 全 valid miss 使用 LFSR 候选**

触发：四路全部有效且均不命中。检查：waymask=1<<LFSR低2位；每路都能被选，且只替换一条。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:165`；module `CacheStage2`；符号 `victimWaymask`。
实际观察：victimWaymask_lfsr、waymask。
必需场景：`candidate0`；`candidate1`；`candidate2`；`candidate3`。

实测：88 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-LOOKUP-ONEHOT waymask 的单路约束**

触发：hit、存在 invalid 的 miss、全 valid miss。检查：合法请求 waymask 恰为一位；重复 tag 造成多命中应触发对应错误检查。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:176`；module `CacheStage2`；符号 `waymask`。
实际观察：waymask、hitVec、RTL assertion 事件。
必需场景：`hit`；`invalid_miss`；`victim_miss`；`duplicate_tag_negative`。

实测：534 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-LOOKUP-LFSR 替换 LFSR 初始化、推进和零态恢复**

触发：reset、普通推进、模块级注入全零状态。检查：种子为 0x1234567887654321；按当前多项式推进，零态下一拍回到1，不能锁死。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:238`；module `CacheStage2`；符号 `if (reset)`。
实际观察：victimWaymask_lfsr 前后值；独立 LFSR 序列。
必需场景：`reset_seed`；`advance`；`zero_recovery`。

实测：4204 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-LOOKUP-MMIO-RANGES 两段 MMIO 范围及边界**

触发：访问 0x3xxxxxxx 与 0x40000000..0x7fffffff 的边界内外。检查：仅定义范围判为 MMIO，附近可缓存地址不能误旁路；边界在 Stage2 模块级输入检查，外部 MMIO responder 当前仅覆盖 0x3 段。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:182`；module `CacheStage2`；符号 `_io_out_bits_mmio_T`。
实际观察：s2 mmio、内存/MMIO 请求、独立范围判定。
必需场景：`0x2fffffff`；`0x30000000`；`0x3fffffff`；`0x40000000`；`0x7fffffff`；`0x80000000`。

实测：6 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / metadata 与 data forwarding

**CACHE-INT-FORWARD-META-SAME-SET 同 set metadata 写入旁路**

触发：Stage2 查找与 metadata 写发生同拍，set 相同。检查：被写 way 的 tag/dirty/valid 使用最新写入值，其他 way 仍用数组响应。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:131`；module `CacheStage2`；符号 `isForwardMeta`。
实际观察：isForwardMeta、forwardWaymask、metaWay_*。
必需场景：`way0`；`way1`；`way2`；`way3`；`hit_created`；`dirty_updated`。

实测：20 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-META-DIFFERENT 不同 set 不触发 metadata 旁路**

触发：metadata 写入与 Stage2 请求 set 不同。检查：isForwardMeta=0，Stage2 命中结果不受该写影响。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:131`；module `CacheStage2`；符号 `isForwardMeta`。
实际观察：set 索引、isForwardMeta、hitVec。
必需场景：`adjacent_set`；`different_tag_same_word`。

实测：5 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-META-HOLD 受阻请求保留 metadata forwarding**

触发：Stage2 受阻期间发生同 set 写，下一拍写端空闲。检查：forwardMetaReg_* 保存该写，后续仍取新 metadata 而非旧 SRAM 响应。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:223`；module `CacheStage2`；符号 `isForwardMetaReg`。
实际观察：isForwardMetaReg、forwardMetaReg_*、Stage2 stall。
必需场景：`single_update`；`multi_cycle_stall`。

实测：29 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-META-NEWEST 新 metadata 写覆盖旧保存值**

触发：已有 pending forwarding，随后同 set 再写。检查：本拍优先当前写，寄存值同步更新，下一拍使用最新版本。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:140`；module `CacheStage2`；符号 `_GEN_3`。
实际观察：当前写、保存副本、metaWay_*。
必需场景：`same_way_twice`；`different_way_followup`。

实测：7 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-META-CLEAR metadata forwarding 上下文清除**

触发：Stage2 消费当前请求或出现空槽。检查：isForwardMetaReg 清零，下一请求不得继承上一请求的旁路资格。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:224`；module `CacheStage2`；符号 `_T | ~io_in_valid`。
实际观察：forward flag、请求序号与接受历史。
必需场景：`consumed`；`bubble`；`reset`。

实测：4004 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-DATA-WORD data forwarding 精确到 set+word**

触发：同 set 同 word 写；同 set 不同 word；不同 set。检查：只在 set+word 都相等时触发 forwarding，不能仅按 line 匹配。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:187`；module `CacheStage2`；符号 `_isForwardData_T_10`。
实际观察：isForwardData、dataWriteBus setIdx、请求 word。
必需场景：`same_word`；`different_word`；`different_set`。

实测：41 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-DATA-HOLD data forwarding 保存和清除**

触发：受阻请求命中写旁路后写端空闲，再消费或插入空槽。检查：等待期间保存 data/waymask；消费、空槽或 reset 清标志。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:246`；module `CacheStage2`；符号 `isForwardDataReg`。
实际观察：isForwardDataReg、forwardDataReg_*。
必需场景：`hold`；`consume`；`bubble`；`reset`。

实测：4027 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-DATA-NEWEST 当前 data 写优先于已保存旁路**

触发：旧 forwarding 已保存，同 word 又写入新值。检查：Stage2 输出选择最新 data 和对应 waymask，不能跨版本配对。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:218`；module `CacheStage2`；符号 `io_out_bits_forwardData_data_data`。
实际观察：isForwardData、forwardDataReg_*、输出 forwarding。
必需场景：`same_way`；`way_changed`。

实测：3 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-WAY-QUALIFY Stage3 旁路还需匹配 way**

触发：相同 set+word 的 forwarding 指向选中/未选中 way。检查：只有 forwarding waymask 等于当前 waymask 才使用旁路数据，否则使用所选 SRAM 路。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:524`；module `CacheStage3`；符号 `useForwardData`。
实际观察：useForwardData、两种 waymask、dataRead。
必需场景：`match`；`mismatch`。

实测：6 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-MASKED-DEPENDENCY 连续部分写基于最新旁路值合并**

触发：同 word 连续两个不同 byte mask 写，中间无空闲周期。检查：第二次合并使用第一次的新数据，未覆盖字节不能退回旧数组值。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:552`；module `CacheStage3`；符号 `_dataHitWriteBus_x1_T`。
实际观察：dataRead、wordMask、dataWriteBus、独立逐字节模型。
必需场景：`disjoint_masks`；`overlap_masks`。

实测：2 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / Stage3 主状态机

**CACHE-INT-FSM-IDLE-CLEAN 空闲 clean miss 进入读请求**

触发：state=0，miss，非 MMIO/probe，victim clean，flush=0。检查：下一状态1；不能产生 writeback。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:615`；module `CacheStage3`；符号 `_state_T_3`。
实际观察：state、meta_dirty、mem cmd。
必需场景：`invalid_victim`；`valid_clean_victim`。

实测：44 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-IDLE-DIRTY 空闲 dirty miss 先进入写回**

触发：state=0、可缓存 miss、victim dirty。检查：下一状态3；写回完成确认前不得发新 refill。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:615`；module `CacheStage3`；符号 `_state_T_3`。
实际观察：state、writeback/refill 事件顺序。
必需场景：`way0`；`way1`；`way2`；`way3`。

实测：8 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-IDLE-MMIO MMIO 优先选择专用状态**

触发：state=0 且 MMIO 请求有效。检查：下一状态5，无 cache 分配；不应出现 mmio&&hit。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:616`；module `CacheStage3`；符号 `_state_T_4`。
实际观察：state、mmio、hit、两种下游总线。
必需场景：`read`；`write`。

实测：4 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-READ-REQUEST 读请求接受后进入 refill**

触发：state=1，memory ready 延迟后接受。检查：未接受保持1；接受后进入2，readBeatCnt 初始化为请求 word。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:624`；module `CacheStage3`；符号 `_GEN_29`。
实际观察：state、命令接受、readBeatCnt。
必需场景：`stalled`；`accepted`。

实测：79 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-READ-END refill 仅接受末拍才完成**

触发：state=2，普通/末拍 response valid 和空拍交错。检查：普通拍/空拍保持2；接受 cmd=6 后进入7，不能只看总线上的末拍编码。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:627`；module `CacheStage3`；符号 `_T_57`。
实际观察：state、memory response 接受、cmd。
必需场景：`middle`；`gap`；`last_valid`；`last_without_valid`。

实测：914 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-WB-END 写回最后接受拍进入等待确认**

触发：state=3，末拍命令受阻再接受。检查：阻塞保持3，只有末拍 cmd=7 接受后进入4。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:635`；module `CacheStage3`；符号 `_T_60`。
实际观察：state、writeBeatCnt、memory command 接受。
必需场景：`last_stalled`；`last_accepted`。

实测：33 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-WB-ACK 收到写回确认后才启动 refill**

触发：state=4，无响应若干拍后确认到达。检查：无确认保持4，确认接受后进入1；请求与 victim 数据不被覆盖。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:637`；module `CacheStage3`；符号 `_GEN_39`。
实际观察：state、memory response、后续 refill。
必需场景：`ack_delayed`；`ack_received`。

实测：15 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-MMIO-REQUEST MMIO 命令接受转等待响应**

触发：state=5，MMIO ready 为低再为高。检查：未接受保持5，接受后进入6，命令只计一次。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:776`；module `CacheStage3`；符号 `4'h5 == state`。
实际观察：state、MMIO 请求接受。
必需场景：`stalled`；`accepted`。

实测：6 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-MMIO-RESPONSE MMIO 响应接受转完成**

触发：state=6，响应 valid 延迟。检查：无响应保持6，接受后进入7并保留正确返回值。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:620`；module `CacheStage3`；符号 `_GEN_26`。
实际观察：state、MMIO response、inRdataRegDemand。
必需场景：`gap`；`valid`。

实测：8 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-COMPLETE 完成态退出的两种合法依据**

触发：state=7；响应尚未接受或早期响应已经接受。检查：普通响应未接受则保持7；最终接受或 alreadyOutFire=1 时返回0，不重复交付。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:638`；module `CacheStage3`；符号 `_GEN_40`。
实际观察：state、alreadyOutFire、CPU 接受事件。
必需场景：`output_stalled`；`normal_accept`；`already_returned`。

实测：88 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-PROBE probe header 决定是否进入 release**

触发：state=0 的 probe header 分别 hit/miss，且有背压。检查：header 未接受保持0；miss 接受后仍0；hit 接受后进8。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:611`；module `CacheStage3`；符号 `_state_T`。
实际观察：state、probe/hit、coh response 接受。
必需场景：`miss`；`hit`；`header_stalled`。

实测：75 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FSM-RELEASE-END release 末拍接受后退出**

触发：state=8，coherence release 的中间/末拍接受及阻塞。检查：非末拍/未接受保持8；只有第八数据接受后回0。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:623`；module `CacheStage3`；符号 `_GEN_28`。
实际观察：state、releaseLast_c_value、releaseLast、接受事件。
必需场景：`middle`；`last_stalled`；`last_accepted`。

实测：1377 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / SRAM 初始化、端口与读时序

**CACHE-INT-ARRAY-META-SWEEP metadata 全 set 初始化扫描**

触发：reset 释放后等待初始化，覆盖128个set。检查：resetSet 逐项扫描0..127、四路 tag/valid/dirty 清零，最后才退出 resetState。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:1125`；module `SRAMTemplate`；符号 `resetState`。
实际观察：metaArray.ram.resetState/resetSet、四路写掩码和地址。
必需场景：`set0`；`set1`；`set2`；`set3`；`set4`；`set5`；`set6`；`set7`；`set8`；`set9`；`set10`；`set11`；`set12`；`set13`；`set14`；`set15`；`set16`；`set17`；`set18`；`set19`；`set20`；`set21`；`set22`；`set23`；`set24`；`set25`；`set26`；`set27`；`set28`；`set29`；`set30`；`set31`；`set32`；`set33`；`set34`；`set35`；`set36`；`set37`；`set38`；`set39`；`set40`；`set41`；`set42`；`set43`；`set44`；`set45`；`set46`；`set47`；`set48`；`set49`；`set50`；`set51`；`set52`；`set53`；`set54`；`set55`；`set56`；`set57`；`set58`；`set59`；`set60`；`set61`；`set62`；`set63`；`set64`；`set65`；`set66`；`set67`；`set68`；`set69`；`set70`；`set71`；`set72`；`set73`；`set74`；`set75`；`set76`；`set77`；`set78`；`set79`；`set80`；`set81`；`set82`；`set83`；`set84`；`set85`；`set86`；`set87`；`set88`；`set89`；`set90`；`set91`；`set92`；`set93`；`set94`；`set95`；`set96`；`set97`；`set98`；`set99`；`set100`；`set101`；`set102`；`set103`；`set104`；`set105`；`set106`；`set107`；`set108`；`set109`；`set110`；`set111`；`set112`；`set113`；`set114`；`set115`；`set116`；`set117`；`set118`；`set119`；`set120`；`set121`；`set122`；`set123`；`set124`；`set125`；`set126`；`set127`；`all_ways`。

实测：3884 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-ARRAY-RESET-BLOCK 初始化期间禁止 metadata 读接受**

触发：初始化扫描期间 CPU 连续请求。检查：metadata ready 为低，流水不得接受未初始化查找；扫描完成后放行。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:1167`；module `SRAMTemplate`；符号 `io_r_req_ready`。
实际观察：resetState、SRAM ready、CPU 接受。
必需场景：`during_sweep`；`first_ready`。

实测：1957 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-ARRAY-WAY-WRITE metadata 写入只影响选中 way**

触发：正常 metadata 写 one-hot waymask。检查：目标 set/way 更新为 tag、valid=1、dirty；其他way/set保留。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:1144`；module `SRAMTemplate`；符号 `array_0_MPORT_mask`。
实际观察：数组写地址、waymask、读回 metadata。
必需场景：`way0`；`way1`；`way2`；`way3`。

实测：64 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-ARRAY-WRITE-PRIORITY 单端口 metadata 写优先于读**

触发：同周期有 metadata 写和读请求。检查：读 ready 为低且读地址管线不装载；下一次实际读返回正确内容。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:1131`；module `SRAMTemplate`；符号 `wen`。
实际观察：wen、io_r_req_ready、读地址使能。
必需场景：`normal_write`；`reset_write`。

实测：2006 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-ARRAY-DATA-PORT Stage1 与 Stage3 的 data SRAM 读仲裁**

触发：Stage1 读和 Stage3 writeback/release 读同时有效。检查：当前 RTL 为端口0（Stage1）优先；Stage3 未授予时不推进读取子状态。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:1795`；module `Arbiter_3`；符号 `grant_1`。
实际观察：readArb grants、两路 ready、s3.state2。
必需场景：`port0_only`；`port1_only`；`both`。

实测：412 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-ARRAY-READ-RESPONSE 共享 SRAM 返回值归属及保持**

触发：两端口相邻周期轮流读取不同地址，另插空拍。检查：每个端口只在自身上次获准读取后更新返回副本，不能拿到另一端口数据。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:1856`；module `SRAMTemplateWithArbiter_1`；符号 `reg  REG`。
实际观察：SRAMTemplateWithArbiter_1 REG/REG_1、两组 r_* 数据。
必需场景：`0_then_1`；`1_then_0`；`idle_hold`。

实测：6904 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / Stage3 读取子状态

**CACHE-INT-FORWARD-READ-ISSUE 写回/release 发起 SRAM 读取**

触发：主状态3或8且 state2=0，data 端口延迟授予。检查：读未接受保持0；接受后state2=1，地址选择相应读/写计数器。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:708`；module `CacheStage3`；符号 `io_dataReadBus_req_valid`。
实际观察：state2、读请求接受、data read 地址。
必需场景：`writeback`；`release`；`arbitration_stall`。

实测：621 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-READ-CAPTURE 同步 SRAM 数据装载**

触发：state2=1。检查：四路 dataWay 在该阶段装载，下一拍state2=2；不能提前发送未返回的数据。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:822`；module `CacheStage3`；符号 `2'h1 == state2`。
实际观察：state2、dataWay_0..3、SRAM response。
必需场景：`writeback`；`release`。

实测：402 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-READ-HOLD 已取数据受阻时保持**

触发：state2=2，选定输出通道未接受。检查：state2 与 dataWay 保持，不发新的 SRAM 读、不跳过当前 word。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:824`；module `CacheStage3`；符号 `2'h2 == state2`。
实际观察：state2、dataWay、mem/coh/CPU burst 接受。
必需场景：`memory_stall`；`coherence_stall`。

实测：184 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-FORWARD-READ-NEXT 数据接受后准备下一 word**

触发：state2=2，当前 memory/coherence/CPU burst 数据接受。检查：下一拍 state2=0，再取下一word；每次接受只推动一次。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:581`；module `CacheStage3`；符号 `_GEN_8`。
实际观察：state2、数据输出接受、下一读请求。
必需场景：`memory`；`coherence`；`CPU_burst`。

实测：402 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / refill 计数、数据与 metadata

**CACHE-INT-REFILL-COUNT-INIT refill 计数从 demand word 开始**

触发：读请求接受，start_word=0..7。检查：readBeatCnt 初始化为请求word；第一拍写正确word。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:625`；module `CacheStage3`；符号 `_GEN_30`。
实际观察：readBeatCnt、refill写地址。
必需场景：`start0`；`start1`；`start2`；`start3`；`start4`；`start5`；`start6`；`start7`。

实测：61 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-REFILL-COUNT-STEP refill 计数只随接受递增**

触发：响应中间插空拍，初始计数含7。检查：仅 response 接受递增，7→0按3位回绕；空拍保持。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:630`；module `CacheStage3`；符号 `_GEN_34`。
实际观察：readBeatCnt 前后值、memory response valid。
必需场景：`increment`；`wrap`；`gap`。

实测：914 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-REFILL-DATA-WRITE 每个已接受 refill word 恰好写一次**

触发：state=2，响应八拍且存在间隔。检查：每拍写当前set+readBeatCnt和选中way；未接受周期无写入。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:662`；module `CacheStage3`；符号 `dataRefillWriteBus_x9`。
实际观察：dataRefillWriteBus、dataArray write地址/waymask。
必需场景：`beat0`；`beat1`；`beat2`；`beat3`；`beat4`；`beat5`；`beat6`；`beat7`；`gap_no_write`。

实测：914 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-REFILL-WRITE-MERGE write allocate 只在首拍合并写数据**

触发：partial write miss，从非零word开始refill。检查：首响应按byte mask合并；其他七拍原样写入，不能对每拍重复合并。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:658`；module `CacheStage3`；符号 `_dataRefill_T`。
实际观察：readingFirst、wordMask、dataRefill、独立line模型。
必需场景：`partial_mask`；`zero_mask`；`first_vs_later`。

实测：24 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-REFILL-META-LAST 仅末响应提交新 tag/valid**

触发：观察完整refill以及末拍前空隙。检查：只有末拍接受才写tag/valid，避免未填完整的line提前可命中。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:663`；module `CacheStage3`；符号 `metaRefillWriteBus_req_valid`。
实际观察：metadata写事件、refill进度、同set查找。
必需场景：`before_last`；`last`；`last_gap`。

实测：914 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-REFILL-META-DIRTY refill dirty 根据请求类型初始化**

触发：read miss 与 write miss 依次完成。检查：read分配clean，write分配dirty，tag来自请求而不是victim。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:742`；module `CacheStage3`；符号 `metaWriteArb_io_in_1_bits_data_dirty`。
实际观察：metaRefill写data_tag/dirty、后续lookup。
必需场景：`read_allocate`；`write_allocate`。

实测：60 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-REFILL-FIRST-FLAG afterFirstRead 置位与清除**

触发：首refill响应、后续拍、返回IDLE、下一笔miss。检查：只在首响应接受后置位，后续保持；新事务在IDLE清零。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:840`；module `CacheStage3`；符号 `afterFirstRead`。
实际观察：afterFirstRead、readingFirst、state。
必需场景：`first`；`later`；`next_transaction`。

实测：3705 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / 提前响应与完成隔离

**CACHE-INT-EARLY-DEMAND-CAPTURE 需求字缓存不被后续refill覆盖**

触发：read miss各拍数据不同，首拍为demand word。检查：inRdataRegDemand只由首个refill数据装载，后续拍不覆盖；最终响应等于独立期望。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:855`；module `CacheStage3`；符号 `_inRdataRegDemand_T_2`。
实际观察：readingFirst、inRdataRegDemand、所有响应数据。
必需场景：`first`；`later_different_data`。

实测：480 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-EARLY-EARLY-ELIGIBLE 只有普通read miss可提前响应**

触发：普通read miss、write miss、MMIO分别运行。检查：read在首拍后允许提前返回；write/MMIO需完成状态，probe不得走CPU响应。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:668`；module `CacheStage3`；符号 `_io_out_valid_T_23`。
实际观察：state、afterFirstRead、io_out_valid、操作类型。
必需场景：`read_miss`；`write_miss`；`MMIO`；`probe`。

实测：2854 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-EARLY-RETURNED-FLAG alreadyOutFire 记录一次实际交付**

触发：早期响应受阻再接受，余下refill继续。检查：未接受不置位；接受后置位并保持到下一IDLE；不能因valid出现就记已交付。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:849`；module `CacheStage3`；符号 `alreadyOutFire`。
实际观察：alreadyOutFire、CPU接受、state。
必需场景：`stalled`；`accepted`；`next_idle`。

实测：5510 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-EARLY-NO-DUPLICATE 早期返回后不重复输出**

触发：demand word已接受，后续refill尚在进行。检查：后续拍不得再次交付CPU响应；最后refill完成仍能退休。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:668`；module `CacheStage3`；符号 `_io_out_valid_T_23`。
实际观察：alreadyOutFire、CPU响应事件、isFinish。
必需场景：`remaining_refill`；`finish`。

实测：728 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-EARLY-FINAL-WHILE-STALLED 首响应未取走时refill先结束**

触发：CPU持续背压，完整refill先到末拍。检查：最终态保留需求数据，直到CPU接受后再退休；不丢请求上下文。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:671`；module `CacheStage3`；符号 `_io_isFinish_T_13`。
实际观察：inRdataRegDemand、state=7、valid_1、isFinish。
必需场景：`full_refill_before_CPU_accept`。

实测：16 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / victim、写回及dirty更新

**CACHE-INT-WRITEBACK-VICTIM-ADDRESS 写回地址来自victim tag**

触发：新请求与victim同set不同tag。检查：写回基址由victim tag+当前set+零offset组成；不能使用新请求tag。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:583`；module `CacheStage3`；符号 `wire [31:0] waddr`。
实际观察：meta_tag、waymask、waddr与独立目录模型。
必需场景：`way0`；`way1`；`way2`；`way3`；`high_tag_bits`。

实测：136 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-WRITEBACK-COUNT 写回计数只随命令接受前进**

触发：八拍写回，首/中/末拍memory ready受阻。检查：writeBeatCnt在未接受时保持，每次接受加1，八拍回绕；数据地址与计数一致。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:633`；module `CacheStage3`；符号 `_value_T_11`。
实际观察：writeBeatCnt、data读地址、mem请求事件。
必需场景：`first_stall`；`middle_stall`；`last_stall`；`wrap`。

实测：31 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-WRITEBACK-LAST-CMD 第八写回数据使用末拍命令**

触发：writeBeatCnt从0到7。检查：前七拍cmd=3，第八拍cmd=7；末拍受阻不提前进入等待确认。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:585`；module `CacheStage3`；符号 `_cmd_T_2`。
实际观察：mem cmd、计数与state。
必需场景：`0_to_6`；`7_stalled`；`7_accepted`。

实测：80 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-WRITEBACK-DIRTY-SET clean write hit置dirty**

触发：clean行首次写，包括零mask；随后再次写同一dirty行。检查：首次按该RTL置dirty，再写dirty不重复metadata更新；零mask不改变数据但仍属于write。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:556`；module `CacheStage3`；符号 `metaHitWriteBus_x5`。
实际观察：meta_dirty、metaHitWriteBus、dataWriteBus。
必需场景：`clean_partial`；`clean_zero_mask`；`already_dirty`。

实测：49 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-WRITEBACK-BYTE-ENABLE byte enable 展开与未写字节保留**

触发：one-hot/zero/full wmask以及read命令携带非零wmask。检查：write每一mask位控制对应8bit；read的wordMask为零，不能误写数据。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:543`；module `CacheStage3`；符号 `wordMask`。
实际观察：wordMask、dataRead、新写数据、逐字节模型。
必需场景：`mask01`；`mask02`；`mask04`；`mask08`；`mask10`；`mask20`；`mask40`；`mask80`；`zero`；`full`；`read_with_mask`。

实测：2999 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / probe与release内部控制

**CACHE-INT-COHERENCE-COUNT-INIT probe header接受装载起始word**

触发：hit/miss header接受和header受阻。检查：仅header接受时readBeatCnt装载addr_wordIndex；受阻不预先更新。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:795`；module `CacheStage3`；符号 `if (probe)`。
实际观察：readBeatCnt、probe、coh接受。
必需场景：`hit`；`miss`；`stalled`。

实测：75 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-COHERENCE-COUNT-STEP release遍历计数与完成计数分离**

触发：不同start_word的八拍release，插入背压。检查：readBeatCnt跟随地址回绕；releaseLast_c_value从0计接受拍数，不因起始word改变结束位置。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:622`；module `CacheStage3`；符号 `_GEN_27`。
实际观察：两计数器、coh接受、数据地址。
必需场景：`start0`；`start1`；`start2`；`start3`；`start4`；`start5`；`start6`；`start7`；`gap`；`wrap`。

实测：1420 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-COHERENCE-LAST-QUALIFY releaseLast依赖接受**

触发：release计数=7，ready从低到高。检查：只有实际接受末拍时releaseLast为真；不能将ready低时cmd值误当已完成。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:602`；module `CacheStage3`；符号 `wire  releaseLast`。
实际观察：releaseLast_c_value、releaseLast、cmd、accept。
必需场景：`last_blocked`；`last_fire`。

实测：97 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-COHERENCE-REPEATED 连续probe之间计数复用**

触发：两个hit probe，中间插入miss probe。检查：每个完整hit八拍后计数回零，miss header不消耗release计数，后续hit仍八拍。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:863`；module `CacheStage3`；符号 `releaseLast_c_value`。
实际观察：releaseLast_c_value、probe序号和响应拍数。
必需场景：`hit_hit`；`hit_miss_hit`。

实测：38 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-COHERENCE-READ-SOURCE release使用被选中way的最新数组值**

触发：clean/dirty各way分别命中，其他way放不同数据。检查：release取当前选中way SRAM数据而非旧demand缓存或其他way。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:567`；module `CacheStage3`；符号 `dataWay_0_data`。
实际观察：dataWay_*、waymask、coh rdata、独立line模型。
必需场景：`way0_clean`；`way0_dirty`；`way1_clean`；`way1_dirty`；`way2_clean`；`way2_dirty`；`way3_clean`；`way3_dirty`。

实测：504 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / 多请求仲裁与副作用互斥

**CACHE-INT-ARBITRATION-PROBE-PRIORITY CPU/probe同时请求的固定优先级**

触发：CPU与coherence同时valid，Stage1可接受。检查：coherence端口0优先、CPU不接受；payload取probe，CPU请求保留待后续接受。此RTL不是round-robin。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:2819`；module `Cache`；符号 `arb_io_in_0_valid`。
实际观察：arb grants、两输入接受、输出payload。
必需场景：`both`；`CPU_only`；`probe_only`。

实测：226 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-ARBITRATION-DATA-PRIORITY 高优先级读释放后的Stage3进展**

触发：Stage1读占用data端口，Stage3待writeback/release；之后停止Stage1请求。检查：无授予时Stage3不前进，端口可用后恢复并完成；不要求无限高优先级流量下公平。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:2813`；module `Cache`；符号 `dataArray_io_r_1_req_valid`。
实际观察：dataArray仲裁、state2、完成事件。
必需场景：`writeback_wait`；`release_wait`；`priority_released`。

实测：6 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-ARBITRATION-WRITE-EXCLUSION hit-write与refill写不能同时发生**

触发：合法流水流量，使hit-write紧接refill结束。检查：两种写使能互斥；RTL断言开启且冲突负例能报错，不能让arbiter静默吞掉一方。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:937`；module `CacheStage3`；符号 `hitWrite & dataRefillWriteBus_x9`。
实际观察：s3 hitWrite、dataRefillWriteBus_x9、assertion日志。
必需场景：`legal_handoff`；`negative_conflict`。

实测：5509 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / 复位与不支持的操作

**CACHE-INT-RESET-CONTROL 复位清空流水和控制**

触发：空闲/进行中reset，随后重新完成metadata初始化。检查：顶层valid清零，Stage3 state/state2/计数/早期响应标志和Stage2 forwarding标志复位；没有旧响应泄漏。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:2834`；module `Cache`；符号 `if (reset)`。
实际观察：流水valid、s3控制、s2 forward、端口输出。
必需场景：`idle`；`refill`；`writeback`；`release`。

实测：30 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-RESET-UNRESET-DATA 数据SRAM未复位时不可当作已初始化**

触发：reset后metadata无效，data SRAM保留任意旧内容。检查：首次读取必须miss/refill，不能根据仿真器默认零值直接命中；填充后数据由独立模型验证。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:1576`；module `SRAMTemplate_1`；符号 `module SRAMTemplate_1`。
实际观察：metadata valid、hit、refill、数据结果。
必需场景：`old_nonzero_data`；`first_miss`。

实测：18 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / 普通读写之外的burst控制

**CACHE-INT-BURST-READ-HIT CPU read-burst命中控制路径**

触发：已安装行收到cmd=2，从不同word开始并施加背压。检查：首字后进入state8，地址顺序回绕、累计八次交付后结束；需按SimpleBus契约独立审查cmd/数据，不能用probe结果代替。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:513`；module `CacheStage3`；符号 `hitReadBurst`。
实际观察：hitReadBurst、respToL1Last_c_value、io_dataReadRespToL1、顶层响应。
必需场景：`start0`；`start7`；`stalled`。

实测：6 次比较，场景激活 100%，比较失败 2；`closed=false`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**CACHE-INT-BURST-WRITE-COUNT CPU write-burst内部word计数**

触发：合法cmd=3序列后cmd=7，穿插输出背压。检查：writeL2BeatCnt只随对应写响应接受推进，burst写地址用该计数，普通写仍用请求word。

验证层：`design_internal`。
RTL：`example/CacheSignalCFG/Cache.v:550`；module `CacheStage3`；符号 `_GEN_0`。
实际观察：writeL2BeatCnt、dataHitWriteBus地址、CPU响应。
必需场景：`first`；`middle`；`last`；`stall`；`ordinary_after_burst`。

实测：3045 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[cache_internal_coverage.py](../../examples/integration/cache/cache_internal_coverage.py)；关闭同时要求实际场景和比较通过。

## 根据实测缺口更新 case

正常 campaign 不能自然产生全部 invalid mask，Stage2 模块 case 直接覆盖 15 个非零 mask、四路 hit/invalid/LFSR 候选、零态恢复和 forwarding 当前/保存/清除三阶段。Stage1 组合真值表核对两 SRAM 共同许可与地址分解。

Stage3 使用独立四路 SRAM 输入数据，覆盖八种 refill/release 起始 word、四路 dirty victim、全部八位 byte enable、首/中/末写回阻塞、部分写合并和连续 mask 依赖。全 Cache 连续命中及真实背压覆盖两级保持、替换、同拍补入；实际 CPU/probe 与 SRAM 竞争、refill/writeback 中的 probe、三种在途复位补充集成证据。

重复 tag、写入冲突和禁止 flush 在 assertion 开启的独立进程运行；既核对真实违例条件，也核对指定 assertion，进程非零退出本身不算证据。Stage3 burst 反例保留为未关闭属性。

同一 RTL/配置和属性契约的独立最终快照才合并；运行 UUID 和 snapshot identity 防止重复计数。外部故障注入、检查器伪造快照和取消结果不纳入本次 DUT 证据集合。功能百分比、正确性及 pytest 结果分别报告。

完整回归与外部事务数量见结果汇总（本地产物：`rtl-property-evidence-2026-10-01/results.json`）。其他配置、未定义非法请求和物理存储器时序仍在范围之外。
