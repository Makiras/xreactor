"""Observed Cache pipeline, forwarding, arrays and state-machine properties."""
from __future__ import annotations

import os
from examples.integration.rtl_checks import ClockObserver, Rule, ScenarioChecks

RULES = {
    'CACHE-INT-PIPE-S1-JOINT-READY': Rule('触发：metadata/data ready 分别阻塞，再共同 ready。检查：只有两路 ready 且流水允许时请求向 Stage2 前进；单路完成不能丢请求。', ('meta_blocked', 'data_blocked', 'both_ready')),
    'CACHE-INT-PIPE-S1-INDEX': Rule('触发：跨 word、set、tag 边界的地址进入 Stage1。检查：metadata 索引为 addr[12:6]，data 索引为 {set,addr[5:3]}，改变 tag 不改变数组行索引。', ('word_boundary', 'set_boundary', 'tag_boundary')),
    'CACHE-INT-PIPE-S2-HOLD': Rule('触发：Stage1 接受新请求和 Stage2 受阻两种情况。检查：只在上游接受时更新寄存 payload，受阻时 addr/cmd/size/mask/data/user 保持。', ('load', 'stall', 'replace')),
    'CACHE-INT-PIPE-S3-HOLD': Rule('触发：Stage2 接受传给 Stage3；另施加 Stage3 受阻。检查：请求、hit/waymask/mmio、forwarding 及四路数据/metadata 同时锁存，受阻不部分更新。', ('load', 'stall', 'same_cycle_finish_new')),
    'CACHE-INT-PIPE-RETIRE': Rule('触发：read miss 提前交付 demanded word，后续 refill 尚未结束。检查：旧 Stage3 请求保持有效直到真正 finish；同拍新请求与 finish 时替换优先且无丢失。', ('early_response', 'final_refill', 'finish_and_new')),
    'CACHE-INT-PIPE-S2-CONSUME': Rule('触发：Stage2 被 Stage3 接受，分别有/无 Stage1 同拍补入。检查：flush 优先清空，否则无补入则清空，有补入则保持 valid 且 payload 对应新请求。', ('consume_only', 'consume_and_fill')),
    'CACHE-INT-PIPE-S2-FLUSH': Rule('触发：io_flush[0] 在空流水、Stage2 受阻或 Stage1 同拍接受时有效。检查：下一拍 Stage2 valid 清零，已进入 Stage3 的请求不被取消。', ('empty', 'held', 'accept_same_cycle')),
    'CACHE-INT-PIPE-EMPTY': Rule('触发：空流水、仅 Stage2、仅 Stage3、两级占用；另保留 dirty 行。检查：io_empty 仅当两级 valid 均低为高；dirty 行存在不影响它。', ('empty_clean', 'empty_dirty', 's2_only', 's3_only', 'both')),
    'CACHE-INT-LOOKUP-HIT-EACH-WAY': Rule('触发：每路分别安装目标 tag，同时改变其他路内容。检查：只选 valid 且 tag 相等的路；输出 hit/waymask 与独立 tag/valid 模型一致。', ('way0', 'way1', 'way2', 'way3')),
    'CACHE-INT-LOOKUP-INVALID-TAG': Rule('触发：某路 tag 等于请求但 valid=0。检查：该路 hitVec=0；不能因残余 tag 产生 hit。', ('way0', 'way1', 'way2', 'way3')),
    'CACHE-INT-LOOKUP-NO-INPUT': Rule('触发：io_in_valid=0，数组数据恰巧与请求地址相同。检查：hitVec/hit 必须为零，不能触发写回或命中副作用。', ('tag_equal', 'tag_unequal')),
    'CACHE-INT-LOOKUP-INVALID-FIRST': Rule('触发：miss 且至少一条 invalid，LFSR 候选指向 valid way。检查：分配 invalid way，不驱逐任何现存有效行。', ('one_invalid', 'multiple_invalid')),
    'CACHE-INT-LOOKUP-INVALID-PRIORITY': Rule('触发：遍历非零 invalidVec 组合。检查：选择最高编号的 invalid way；各组合的输出须为 one-hot。', tuple(f'invalidVec={mask}' for mask in range(1, 16))),
    'CACHE-INT-LOOKUP-ALL-VALID': Rule('触发：四路全部有效且均不命中。检查：waymask=1<<LFSR低2位；每路都能被选，且只替换一条。', ('candidate0', 'candidate1', 'candidate2', 'candidate3')),
    'CACHE-INT-LOOKUP-ONEHOT': Rule('触发：hit、存在 invalid 的 miss、全 valid miss。检查：合法请求 waymask 恰为一位；重复 tag 造成多命中应触发对应错误检查。', ('hit', 'invalid_miss', 'victim_miss', 'duplicate_tag_negative')),
    'CACHE-INT-LOOKUP-LFSR': Rule('触发：reset、普通推进、模块级注入全零状态。检查：种子为 0x1234567887654321；按当前多项式推进，零态下一拍回到1，不能锁死。', ('reset_seed', 'advance', 'zero_recovery')),
    'CACHE-INT-LOOKUP-MMIO-RANGES': Rule('触发：访问 0x3xxxxxxx 与 0x40000000..0x7fffffff 的边界内外。检查：仅定义范围判为 MMIO，附近可缓存地址不能误旁路；需扩展 responder 的当前单段识别。', ('0x2fffffff', '0x30000000', '0x3fffffff', '0x40000000', '0x7fffffff', '0x80000000')),
    'CACHE-INT-FORWARD-META-SAME-SET': Rule('触发：Stage2 查找与 metadata 写发生同拍，set 相同。检查：被写 way 的 tag/dirty/valid 使用最新写入值，其他 way 仍用数组响应。', ('way0', 'way1', 'way2', 'way3', 'hit_created', 'dirty_updated')),
    'CACHE-INT-FORWARD-META-DIFFERENT': Rule('触发：metadata 写入与 Stage2 请求 set 不同。检查：isForwardMeta=0，Stage2 命中结果不受该写影响。', ('adjacent_set', 'different_tag_same_word')),
    'CACHE-INT-FORWARD-META-HOLD': Rule('触发：Stage2 受阻期间发生同 set 写，下一拍写端空闲。检查：forwardMetaReg_* 保存该写，后续仍取新 metadata 而非旧 SRAM 响应。', ('single_update', 'multi_cycle_stall')),
    'CACHE-INT-FORWARD-META-NEWEST': Rule('触发：已有 pending forwarding，随后同 set 再写。检查：本拍优先当前写，寄存值同步更新，下一拍使用最新版本。', ('same_way_twice', 'different_way_followup')),
    'CACHE-INT-FORWARD-META-CLEAR': Rule('触发：Stage2 消费当前请求或出现空槽。检查：isForwardMetaReg 清零，下一请求不得继承上一请求的旁路资格。', ('consumed', 'bubble', 'reset')),
    'CACHE-INT-FORWARD-DATA-WORD': Rule('触发：同 set 同 word 写；同 set 不同 word；不同 set。检查：只在 set+word 都相等时触发 forwarding，不能仅按 line 匹配。', ('same_word', 'different_word', 'different_set')),
    'CACHE-INT-FORWARD-DATA-HOLD': Rule('触发：受阻请求命中写旁路后写端空闲，再消费或插入空槽。检查：等待期间保存 data/waymask；消费、空槽或 reset 清标志。', ('hold', 'consume', 'bubble', 'reset')),
    'CACHE-INT-FORWARD-DATA-NEWEST': Rule('触发：旧 forwarding 已保存，同 word 又写入新值。检查：Stage2 输出选择最新 data 和对应 waymask，不能跨版本配对。', ('same_way', 'way_changed')),
    'CACHE-INT-FORWARD-WAY-QUALIFY': Rule('触发：相同 set+word 的 forwarding 指向选中/未选中 way。检查：只有 forwarding waymask 等于当前 waymask 才使用旁路数据，否则使用所选 SRAM 路。', ('match', 'mismatch')),
    'CACHE-INT-FORWARD-MASKED-DEPENDENCY': Rule('触发：同 word 连续两个不同 byte mask 写，中间无空闲周期。检查：第二次合并使用第一次的新数据，未覆盖字节不能退回旧数组值。', ('disjoint_masks', 'overlap_masks')),
    'CACHE-INT-FSM-IDLE-CLEAN': Rule('触发：state=0，miss，非 MMIO/probe，victim clean，flush=0。检查：下一状态1；不能产生 writeback。', ('invalid_victim', 'valid_clean_victim')),
    'CACHE-INT-FSM-IDLE-DIRTY': Rule('触发：state=0、可缓存 miss、victim dirty。检查：下一状态3；写回完成确认前不得发新 refill。', tuple(f'way{way}' for way in range(4))),
    'CACHE-INT-FSM-IDLE-MMIO': Rule('触发：state=0 且 MMIO 请求有效。检查：下一状态5，无 cache 分配；不应出现 mmio&&hit。', ('read', 'write')),
    'CACHE-INT-FSM-READ-REQUEST': Rule('触发：state=1，memory ready 延迟后接受。检查：未接受保持1；接受后进入2，readBeatCnt 初始化为请求 word。', ('stalled', 'accepted')),
    'CACHE-INT-FSM-READ-END': Rule('触发：state=2，普通/末拍 response valid 和空拍交错。检查：普通拍/空拍保持2；接受 cmd=6 后进入7，不能只看总线上的末拍编码。', ('middle', 'gap', 'last_valid', 'last_without_valid')),
    'CACHE-INT-FSM-WB-END': Rule('触发：state=3，末拍命令受阻再接受。检查：阻塞保持3，只有末拍 cmd=7 接受后进入4。', ('last_stalled', 'last_accepted')),
    'CACHE-INT-FSM-WB-ACK': Rule('触发：state=4，无响应若干拍后确认到达。检查：无确认保持4，确认接受后进入1；请求与 victim 数据不被覆盖。', ('ack_delayed', 'ack_received')),
    'CACHE-INT-FSM-MMIO-REQUEST': Rule('触发：state=5，MMIO ready 为低再为高。检查：未接受保持5，接受后进入6，命令只计一次。', ('stalled', 'accepted')),
    'CACHE-INT-FSM-MMIO-RESPONSE': Rule('触发：state=6，响应 valid 延迟。检查：无响应保持6，接受后进入7并保留正确返回值。', ('gap', 'valid')),
    'CACHE-INT-FSM-COMPLETE': Rule('触发：state=7；响应尚未接受或早期响应已经接受。检查：普通响应未接受则保持7；最终接受或 alreadyOutFire=1 时返回0，不重复交付。', ('output_stalled', 'normal_accept', 'already_returned')),
    'CACHE-INT-FSM-PROBE': Rule('触发：state=0 的 probe header 分别 hit/miss，且有背压。检查：header 未接受保持0；miss 接受后仍0；hit 接受后进8。', ('miss', 'hit', 'header_stalled')),
    'CACHE-INT-FSM-RELEASE-END': Rule('触发：state=8，coherence release 的中间/末拍接受及阻塞。检查：非末拍/未接受保持8；只有第八数据接受后回0。', ('middle', 'last_stalled', 'last_accepted')),
    'CACHE-INT-ARRAY-META-SWEEP': Rule('触发：reset 释放后等待初始化，覆盖128个set。检查：resetSet 逐项扫描0..127、四路 tag/valid/dirty 清零，最后才退出 resetState。', tuple(f'set{index}' for index in range(128)) + ('all_ways',)),
    'CACHE-INT-ARRAY-RESET-BLOCK': Rule('触发：初始化扫描期间 CPU 连续请求。检查：metadata ready 为低，流水不得接受未初始化查找；扫描完成后放行。', ('during_sweep', 'first_ready')),
    'CACHE-INT-ARRAY-WAY-WRITE': Rule('触发：正常 metadata 写 one-hot waymask。检查：目标 set/way 更新为 tag、valid=1、dirty；其他way/set保留。', ('way0', 'way1', 'way2', 'way3')),
    'CACHE-INT-ARRAY-WRITE-PRIORITY': Rule('触发：同周期有 metadata 写和读请求。检查：读 ready 为低且读地址管线不装载；下一次实际读返回正确内容。', ('normal_write', 'reset_write')),
    'CACHE-INT-ARRAY-DATA-PORT': Rule('触发：Stage1 读和 Stage3 writeback/release 读同时有效。检查：当前 RTL 为端口0（Stage1）优先；Stage3 未授予时不推进读取子状态。', ('port0_only', 'port1_only', 'both')),
    'CACHE-INT-ARRAY-READ-RESPONSE': Rule('触发：两端口相邻周期轮流读取不同地址，另插空拍。检查：每个端口只在自身上次获准读取后更新返回副本，不能拿到另一端口数据。', ('0_then_1', '1_then_0', 'idle_hold')),
    'CACHE-INT-FORWARD-READ-ISSUE': Rule('触发：主状态3或8且 state2=0，data 端口延迟授予。检查：读未接受保持0；接受后state2=1，地址选择相应读/写计数器。', ('writeback', 'release', 'arbitration_stall')),
    'CACHE-INT-FORWARD-READ-CAPTURE': Rule('触发：state2=1。检查：四路 dataWay 在该阶段装载，下一拍state2=2；不能提前发送未返回的数据。', ('writeback', 'release')),
    'CACHE-INT-FORWARD-READ-HOLD': Rule('触发：state2=2，选定输出通道未接受。检查：state2 与 dataWay 保持，不发新的 SRAM 读、不跳过当前 word。', ('memory_stall', 'coherence_stall')),
    'CACHE-INT-FORWARD-READ-NEXT': Rule('触发：state2=2，当前 memory/coherence/CPU burst 数据接受。检查：下一拍 state2=0，再取下一word；每次接受只推动一次。', ('memory', 'coherence', 'CPU_burst')),
    'CACHE-INT-REFILL-COUNT-INIT': Rule('触发：读请求接受，start_word=0..7。检查：readBeatCnt 初始化为请求word；第一拍写正确word。', ('start0', 'start1', 'start2', 'start3', 'start4', 'start5', 'start6', 'start7')),
    'CACHE-INT-REFILL-COUNT-STEP': Rule('触发：响应中间插空拍，初始计数含7。检查：仅 response 接受递增，7→0按3位回绕；空拍保持。', ('increment', 'wrap', 'gap')),
    'CACHE-INT-REFILL-DATA-WRITE': Rule('触发：state=2，响应八拍且存在间隔。检查：每拍写当前set+readBeatCnt和选中way；未接受周期无写入。', ('beat0', 'beat1', 'beat2', 'beat3', 'beat4', 'beat5', 'beat6', 'beat7', 'gap_no_write')),
    'CACHE-INT-REFILL-WRITE-MERGE': Rule('触发：partial write miss，从非零word开始refill。检查：首响应按byte mask合并；其他七拍原样写入，不能对每拍重复合并。', ('partial_mask', 'zero_mask', 'first_vs_later')),
    'CACHE-INT-REFILL-META-LAST': Rule('触发：观察完整refill以及末拍前空隙。检查：只有末拍接受才写tag/valid，避免未填完整的line提前可命中。', ('before_last', 'last', 'last_gap')),
    'CACHE-INT-REFILL-META-DIRTY': Rule('触发：read miss 与 write miss 依次完成。检查：read分配clean，write分配dirty，tag来自请求而不是victim。', ('read_allocate', 'write_allocate')),
    'CACHE-INT-REFILL-FIRST-FLAG': Rule('触发：首refill响应、后续拍、返回IDLE、下一笔miss。检查：只在首响应接受后置位，后续保持；新事务在IDLE清零。', ('first', 'later', 'next_transaction')),
    'CACHE-INT-EARLY-DEMAND-CAPTURE': Rule('触发：read miss各拍数据不同，首拍为demand word。检查：inRdataRegDemand只由首个refill数据装载，后续拍不覆盖；最终响应等于独立期望。', ('first', 'later_different_data')),
    'CACHE-INT-EARLY-EARLY-ELIGIBLE': Rule('触发：普通read miss、write miss、MMIO分别运行。检查：read在首拍后允许提前返回；write/MMIO需完成状态，probe不得走CPU响应。', ('read_miss', 'write_miss', 'MMIO', 'probe')),
    'CACHE-INT-EARLY-RETURNED-FLAG': Rule('触发：早期响应受阻再接受，余下refill继续。检查：未接受不置位；接受后置位并保持到下一IDLE；不能因valid出现就记已交付。', ('stalled', 'accepted', 'next_idle')),
    'CACHE-INT-EARLY-NO-DUPLICATE': Rule('触发：demand word已接受，后续refill尚在进行。检查：后续拍不得再次交付CPU响应；最后refill完成仍能退休。', ('remaining_refill', 'finish')),
    'CACHE-INT-EARLY-FINAL-WHILE-STALLED': Rule('触发：CPU持续背压，完整refill先到末拍。检查：最终态保留需求数据，直到CPU接受后再退休；不丢请求上下文。', ('full_refill_before_CPU_accept',)),
    'CACHE-INT-WRITEBACK-VICTIM-ADDRESS': Rule('触发：新请求与victim同set不同tag。检查：写回基址由victim tag+当前set+零offset组成；不能使用新请求tag。', tuple(f'way{way}' for way in range(4)) + ('high_tag_bits',)),
    'CACHE-INT-WRITEBACK-COUNT': Rule('触发：八拍写回，首/中/末拍memory ready受阻。检查：writeBeatCnt在未接受时保持，每次接受加1，八拍回绕；数据地址与计数一致。', ('first_stall', 'middle_stall', 'last_stall', 'wrap')),
    'CACHE-INT-WRITEBACK-LAST-CMD': Rule('触发：writeBeatCnt从0到7。检查：前七拍cmd=3，第八拍cmd=7；末拍受阻不提前进入等待确认。', ('0_to_6', '7_stalled', '7_accepted')),
    'CACHE-INT-WRITEBACK-DIRTY-SET': Rule('触发：clean行首次写，包括零mask；随后再次写同一dirty行。检查：首次按该RTL置dirty，再写dirty不重复metadata更新；零mask不改变数据但仍属于write。', ('clean_partial', 'clean_zero_mask', 'already_dirty')),
    'CACHE-INT-WRITEBACK-BYTE-ENABLE': Rule('触发：one-hot/zero/full wmask以及read命令携带非零wmask。检查：write每一mask位控制对应8bit；read的wordMask为零，不能误写数据。', ('mask01', 'mask02', 'mask04', 'mask08', 'mask10', 'mask20', 'mask40', 'mask80', 'zero', 'full', 'read_with_mask')),
    'CACHE-INT-COHERENCE-COUNT-INIT': Rule('触发：hit/miss header接受和header受阻。检查：仅header接受时readBeatCnt装载addr_wordIndex；受阻不预先更新。', ('hit', 'miss', 'stalled')),
    'CACHE-INT-COHERENCE-COUNT-STEP': Rule('触发：不同start_word的八拍release，插入背压。检查：readBeatCnt跟随地址回绕；releaseLast_c_value从0计接受拍数，不因起始word改变结束位置。', ('start0', 'start1', 'start2', 'start3', 'start4', 'start5', 'start6', 'start7', 'gap', 'wrap')),
    'CACHE-INT-COHERENCE-LAST-QUALIFY': Rule('触发：release计数=7，ready从低到高。检查：只有实际接受末拍时releaseLast为真；不能将ready低时cmd值误当已完成。', ('last_blocked', 'last_fire')),
    'CACHE-INT-COHERENCE-REPEATED': Rule('触发：两个hit probe，中间插入miss probe。检查：每个完整hit八拍后计数回零，miss header不消耗release计数，后续hit仍八拍。', ('hit_hit', 'hit_miss_hit')),
    'CACHE-INT-COHERENCE-READ-SOURCE': Rule('触发：clean/dirty各way分别命中，其他way放不同数据。检查：release取当前选中way SRAM数据而非旧demand缓存或其他way。', ('way0_clean', 'way0_dirty', 'way1_clean', 'way1_dirty', 'way2_clean', 'way2_dirty', 'way3_clean', 'way3_dirty')),
    'CACHE-INT-ARBITRATION-PROBE-PRIORITY': Rule('触发：CPU与coherence同时valid，Stage1可接受。检查：coherence端口0优先、CPU不接受；payload取probe，CPU请求保留待后续接受。此RTL不是round-robin。', ('both', 'CPU_only', 'probe_only')),
    'CACHE-INT-ARBITRATION-DATA-PRIORITY': Rule('触发：Stage1读占用data端口，Stage3待writeback/release；之后停止Stage1请求。检查：无授予时Stage3不前进，端口可用后恢复并完成；不要求无限高优先级流量下公平。', ('writeback_wait', 'release_wait', 'priority_released')),
    'CACHE-INT-ARBITRATION-WRITE-EXCLUSION': Rule('触发：合法流水流量，使hit-write紧接refill结束。检查：两种写使能互斥；RTL断言开启且冲突负例能报错，不能让arbiter静默吞掉一方。', ('legal_handoff', 'negative_conflict')),
    'CACHE-INT-RESET-CONTROL': Rule('触发：空闲/进行中reset，随后重新完成metadata初始化。检查：顶层valid清零，Stage3 state/state2/计数/早期响应标志和Stage2 forwarding标志复位；没有旧响应泄漏。', ('idle', 'refill', 'writeback', 'release')),
    'CACHE-INT-RESET-UNRESET-DATA': Rule('触发：reset后metadata无效，data SRAM保留任意旧内容。检查：首次读取必须miss/refill，不能根据仿真器默认零值直接命中；填充后数据由独立模型验证。', ('old_nonzero_data', 'first_miss')),
    'CACHE-INT-BURST-READ-HIT': Rule('触发：已安装行收到cmd=2，从不同word开始并施加背压。检查：首字后进入state8，地址顺序回绕、累计八次交付后结束；需按SimpleBus契约独立审查cmd/数据，不能用probe结果代替。', ('start0', 'start7', 'stalled')),
    'CACHE-INT-BURST-WRITE-COUNT': Rule('触发：合法cmd=3序列后cmd=7，穿插输出背压。检查：writeL2BeatCnt只随对应写响应接受推进，burst写地址用该计数，普通写仍用请求word。', ('first', 'middle', 'last', 'stall', 'ordinary_after_burst')),
    'CACHE-INT-ERROR-ASSERTIONS': Rule('触发：真实 DUT 中重复 tag、MMIO 命中、metadata/data 写冲突或禁止 flush。检查：实际错误条件成立、指定 RTL assertion、SIGABRT 及该分支非零覆盖计数；模块与顶层分别留证。', (
        'stage2.duplicate_tag', 'stage3.mmio_hit', 'stage3.meta_conflict', 'stage3.write_conflict', 'stage3.flush',
        'cache.duplicate_tag', 'cache.mmio_hit', 'cache.meta_conflict', 'cache.write_conflict', 'cache.flush')),
    'CACHE-INT-ERROR-STATE-RESET': Rule('触发：完整 Cache 空闲时注入非法主状态15、读取子状态3或两者。检查：复位清除控制状态，重新初始化后访问发生 refill 且返回独立 memory 模型的数据；不要求未规定的自动恢复。', ('main_state', 'read_substate', 'both')),
    'CACHE-INT-ERROR-FLUSH-LATCH': Rule('触发：命中响应受阻时注入 needFlush=1。检查：受阻时保持，响应接受或复位清零，保留/取消响应与后续访问正确。依据当前 RTL 明确的清零逻辑，不将其解释为允许 writable flush。', ('accept', 'reset')),
}

SIGNALS = {
    'dataArray.io_w_req_valid': ('dataArray.io_w_req_valid', 1),
    's1.io_in_ready': ('s1.io_in_ready', 1),
    's1.io_in_valid': ('s1.io_in_valid', 1),
    's1.io_in_bits_addr': ('s1.io_in_bits_addr', 32),
    's1.io_in_bits_size': ('s1.io_in_bits_size', 3),
    's1.io_in_bits_cmd': ('s1.io_in_bits_cmd', 4),
    's1.io_in_bits_wmask': ('s1.io_in_bits_wmask', 8),
    's1.io_in_bits_wdata': ('s1.io_in_bits_wdata', 64),
    's1.io_in_bits_user': ('s1.io_in_bits_user', 16),
    's1.io_out_ready': ('s1.io_out_ready', 1),
    's1.io_out_valid': ('s1.io_out_valid', 1),
    's1.io_out_bits_req_addr': ('s1.io_out_bits_req_addr', 32),
    's1.io_out_bits_req_size': ('s1.io_out_bits_req_size', 3),
    's1.io_out_bits_req_cmd': ('s1.io_out_bits_req_cmd', 4),
    's1.io_out_bits_req_wmask': ('s1.io_out_bits_req_wmask', 8),
    's1.io_out_bits_req_wdata': ('s1.io_out_bits_req_wdata', 64),
    's1.io_out_bits_req_user': ('s1.io_out_bits_req_user', 16),
    's1.io_metaReadBus_req_ready': ('s1.io_metaReadBus_req_ready', 1),
    's1.io_metaReadBus_req_valid': ('s1.io_metaReadBus_req_valid', 1),
    's1.io_metaReadBus_req_bits_setIdx': ('s1.io_metaReadBus_req_bits_setIdx', 7),
    's1.io_metaReadBus_resp_data_0_tag': ('s1.io_metaReadBus_resp_data_0_tag', 19),
    's1.io_metaReadBus_resp_data_0_valid': ('s1.io_metaReadBus_resp_data_0_valid', 1),
    's1.io_metaReadBus_resp_data_0_dirty': ('s1.io_metaReadBus_resp_data_0_dirty', 1),
    's1.io_metaReadBus_resp_data_1_tag': ('s1.io_metaReadBus_resp_data_1_tag', 19),
    's1.io_metaReadBus_resp_data_1_valid': ('s1.io_metaReadBus_resp_data_1_valid', 1),
    's1.io_metaReadBus_resp_data_1_dirty': ('s1.io_metaReadBus_resp_data_1_dirty', 1),
    's1.io_metaReadBus_resp_data_2_tag': ('s1.io_metaReadBus_resp_data_2_tag', 19),
    's1.io_metaReadBus_resp_data_2_valid': ('s1.io_metaReadBus_resp_data_2_valid', 1),
    's1.io_metaReadBus_resp_data_2_dirty': ('s1.io_metaReadBus_resp_data_2_dirty', 1),
    's1.io_metaReadBus_resp_data_3_tag': ('s1.io_metaReadBus_resp_data_3_tag', 19),
    's1.io_metaReadBus_resp_data_3_valid': ('s1.io_metaReadBus_resp_data_3_valid', 1),
    's1.io_metaReadBus_resp_data_3_dirty': ('s1.io_metaReadBus_resp_data_3_dirty', 1),
    's1.io_dataReadBus_req_ready': ('s1.io_dataReadBus_req_ready', 1),
    's1.io_dataReadBus_req_valid': ('s1.io_dataReadBus_req_valid', 1),
    's1.io_dataReadBus_req_bits_setIdx': ('s1.io_dataReadBus_req_bits_setIdx', 10),
    's1.io_dataReadBus_resp_data_0_data': ('s1.io_dataReadBus_resp_data_0_data', 64),
    's1.io_dataReadBus_resp_data_1_data': ('s1.io_dataReadBus_resp_data_1_data', 64),
    's1.io_dataReadBus_resp_data_2_data': ('s1.io_dataReadBus_resp_data_2_data', 64),
    's1.io_dataReadBus_resp_data_3_data': ('s1.io_dataReadBus_resp_data_3_data', 64),
    's2.clock': ('s2.clock', 1),
    's2.reset': ('s2.reset', 1),
    's2.io_in_ready': ('s2.io_in_ready', 1),
    's2.io_in_valid': ('s2.io_in_valid', 1),
    's2.io_in_bits_req_addr': ('s2.io_in_bits_req_addr', 32),
    's2.io_in_bits_req_size': ('s2.io_in_bits_req_size', 3),
    's2.io_in_bits_req_cmd': ('s2.io_in_bits_req_cmd', 4),
    's2.io_in_bits_req_wmask': ('s2.io_in_bits_req_wmask', 8),
    's2.io_in_bits_req_wdata': ('s2.io_in_bits_req_wdata', 64),
    's2.io_in_bits_req_user': ('s2.io_in_bits_req_user', 16),
    's2.io_out_ready': ('s2.io_out_ready', 1),
    's2.io_out_valid': ('s2.io_out_valid', 1),
    's2.io_out_bits_req_addr': ('s2.io_out_bits_req_addr', 32),
    's2.io_out_bits_req_size': ('s2.io_out_bits_req_size', 3),
    's2.io_out_bits_req_cmd': ('s2.io_out_bits_req_cmd', 4),
    's2.io_out_bits_req_wmask': ('s2.io_out_bits_req_wmask', 8),
    's2.io_out_bits_req_wdata': ('s2.io_out_bits_req_wdata', 64),
    's2.io_out_bits_req_user': ('s2.io_out_bits_req_user', 16),
    's2.io_out_bits_metas_0_tag': ('s2.io_out_bits_metas_0_tag', 19),
    's2.io_out_bits_metas_0_dirty': ('s2.io_out_bits_metas_0_dirty', 1),
    's2.io_out_bits_metas_1_tag': ('s2.io_out_bits_metas_1_tag', 19),
    's2.io_out_bits_metas_1_dirty': ('s2.io_out_bits_metas_1_dirty', 1),
    's2.io_out_bits_metas_2_tag': ('s2.io_out_bits_metas_2_tag', 19),
    's2.io_out_bits_metas_2_dirty': ('s2.io_out_bits_metas_2_dirty', 1),
    's2.io_out_bits_metas_3_tag': ('s2.io_out_bits_metas_3_tag', 19),
    's2.io_out_bits_metas_3_dirty': ('s2.io_out_bits_metas_3_dirty', 1),
    's2.io_out_bits_datas_0_data': ('s2.io_out_bits_datas_0_data', 64),
    's2.io_out_bits_datas_1_data': ('s2.io_out_bits_datas_1_data', 64),
    's2.io_out_bits_datas_2_data': ('s2.io_out_bits_datas_2_data', 64),
    's2.io_out_bits_datas_3_data': ('s2.io_out_bits_datas_3_data', 64),
    's2.io_out_bits_hit': ('s2.io_out_bits_hit', 1),
    's2.io_out_bits_waymask': ('s2.io_out_bits_waymask', 4),
    's2.io_out_bits_mmio': ('s2.io_out_bits_mmio', 1),
    's2.io_out_bits_isForwardData': ('s2.io_out_bits_isForwardData', 1),
    's2.io_out_bits_forwardData_data_data': ('s2.io_out_bits_forwardData_data_data', 64),
    's2.io_out_bits_forwardData_waymask': ('s2.io_out_bits_forwardData_waymask', 4),
    's2.io_metaReadResp_0_tag': ('s2.io_metaReadResp_0_tag', 19),
    's2.io_metaReadResp_0_valid': ('s2.io_metaReadResp_0_valid', 1),
    's2.io_metaReadResp_0_dirty': ('s2.io_metaReadResp_0_dirty', 1),
    's2.io_metaReadResp_1_tag': ('s2.io_metaReadResp_1_tag', 19),
    's2.io_metaReadResp_1_valid': ('s2.io_metaReadResp_1_valid', 1),
    's2.io_metaReadResp_1_dirty': ('s2.io_metaReadResp_1_dirty', 1),
    's2.io_metaReadResp_2_tag': ('s2.io_metaReadResp_2_tag', 19),
    's2.io_metaReadResp_2_valid': ('s2.io_metaReadResp_2_valid', 1),
    's2.io_metaReadResp_2_dirty': ('s2.io_metaReadResp_2_dirty', 1),
    's2.io_metaReadResp_3_tag': ('s2.io_metaReadResp_3_tag', 19),
    's2.io_metaReadResp_3_valid': ('s2.io_metaReadResp_3_valid', 1),
    's2.io_metaReadResp_3_dirty': ('s2.io_metaReadResp_3_dirty', 1),
    's2.io_dataReadResp_0_data': ('s2.io_dataReadResp_0_data', 64),
    's2.io_dataReadResp_1_data': ('s2.io_dataReadResp_1_data', 64),
    's2.io_dataReadResp_2_data': ('s2.io_dataReadResp_2_data', 64),
    's2.io_dataReadResp_3_data': ('s2.io_dataReadResp_3_data', 64),
    's2.io_metaWriteBus_req_valid': ('s2.io_metaWriteBus_req_valid', 1),
    's2.io_metaWriteBus_req_bits_setIdx': ('s2.io_metaWriteBus_req_bits_setIdx', 7),
    's2.io_metaWriteBus_req_bits_data_tag': ('s2.io_metaWriteBus_req_bits_data_tag', 19),
    's2.io_metaWriteBus_req_bits_data_dirty': ('s2.io_metaWriteBus_req_bits_data_dirty', 1),
    's2.io_metaWriteBus_req_bits_waymask': ('s2.io_metaWriteBus_req_bits_waymask', 4),
    's2.io_dataWriteBus_req_valid': ('s2.io_dataWriteBus_req_valid', 1),
    's2.io_dataWriteBus_req_bits_setIdx': ('s2.io_dataWriteBus_req_bits_setIdx', 10),
    's2.io_dataWriteBus_req_bits_data_data': ('s2.io_dataWriteBus_req_bits_data_data', 64),
    's2.io_dataWriteBus_req_bits_waymask': ('s2.io_dataWriteBus_req_bits_waymask', 4),
    's2.addr_wordIndex': ('s2.addr_wordIndex', 3),
    's2.addr_index': ('s2.addr_index', 7),
    's2.addr_tag': ('s2.addr_tag', 19),
    's2.isForwardMeta': ('s2.isForwardMeta', 1),
    's2.isForwardMetaReg': ('s2.isForwardMetaReg', 1),
    's2.forwardMetaReg_data_tag': ('s2.forwardMetaReg_data_tag', 19),
    's2.forwardMetaReg_data_dirty': ('s2.forwardMetaReg_data_dirty', 1),
    's2.forwardMetaReg_waymask': ('s2.forwardMetaReg_waymask', 4),
    's2.pickForwardMeta': ('s2.pickForwardMeta', 1),
    's2.forwardWaymask_0': ('s2.forwardWaymask_0', 1),
    's2.forwardWaymask_1': ('s2.forwardWaymask_1', 1),
    's2.forwardWaymask_2': ('s2.forwardWaymask_2', 1),
    's2.forwardWaymask_3': ('s2.forwardWaymask_3', 1),
    's2.metaWay_0_tag': ('s2.metaWay_0_tag', 19),
    's2.metaWay_0_valid': ('s2.metaWay_0_valid', 1),
    's2.metaWay_1_tag': ('s2.metaWay_1_tag', 19),
    's2.metaWay_1_valid': ('s2.metaWay_1_valid', 1),
    's2.metaWay_2_tag': ('s2.metaWay_2_tag', 19),
    's2.metaWay_2_valid': ('s2.metaWay_2_valid', 1),
    's2.metaWay_3_tag': ('s2.metaWay_3_tag', 19),
    's2.metaWay_3_valid': ('s2.metaWay_3_valid', 1),
    's2.hitVec': ('s2.hitVec', 4),
    's2.victimWaymask_lfsr': ('s2.victimWaymask_lfsr', 64),
    's2.victimWaymask_xor': ('s2.victimWaymask_xor', 1),
    's2.victimWaymask': ('s2.victimWaymask', 4),
    's2.invalidVec': ('s2.invalidVec', 4),
    's2.hasInvalidWay': ('s2.hasInvalidWay', 1),
    's2.refillInvalidWaymask': ('s2.refillInvalidWaymask', 4),
    's2.waymask': ('s2.waymask', 4),
    's2.isForwardData': ('s2.isForwardData', 1),
    's2.isForwardDataReg': ('s2.isForwardDataReg', 1),
    's2.forwardDataReg_data_data': ('s2.forwardDataReg_data_data', 64),
    's2.forwardDataReg_waymask': ('s2.forwardDataReg_waymask', 4),
    's3.clock': ('s3.clock', 1),
    's3.reset': ('s3.reset', 1),
    's3.io_in_ready': ('s3.io_in_ready', 1),
    's3.io_in_valid': ('s3.io_in_valid', 1),
    's3.io_in_bits_req_addr': ('s3.io_in_bits_req_addr', 32),
    's3.io_in_bits_req_size': ('s3.io_in_bits_req_size', 3),
    's3.io_in_bits_req_cmd': ('s3.io_in_bits_req_cmd', 4),
    's3.io_in_bits_req_wmask': ('s3.io_in_bits_req_wmask', 8),
    's3.io_in_bits_req_wdata': ('s3.io_in_bits_req_wdata', 64),
    's3.io_in_bits_req_user': ('s3.io_in_bits_req_user', 16),
    's3.io_in_bits_metas_0_tag': ('s3.io_in_bits_metas_0_tag', 19),
    's3.io_in_bits_metas_0_dirty': ('s3.io_in_bits_metas_0_dirty', 1),
    's3.io_in_bits_metas_1_tag': ('s3.io_in_bits_metas_1_tag', 19),
    's3.io_in_bits_metas_1_dirty': ('s3.io_in_bits_metas_1_dirty', 1),
    's3.io_in_bits_metas_2_tag': ('s3.io_in_bits_metas_2_tag', 19),
    's3.io_in_bits_metas_2_dirty': ('s3.io_in_bits_metas_2_dirty', 1),
    's3.io_in_bits_metas_3_tag': ('s3.io_in_bits_metas_3_tag', 19),
    's3.io_in_bits_metas_3_dirty': ('s3.io_in_bits_metas_3_dirty', 1),
    's3.io_in_bits_datas_0_data': ('s3.io_in_bits_datas_0_data', 64),
    's3.io_in_bits_datas_1_data': ('s3.io_in_bits_datas_1_data', 64),
    's3.io_in_bits_datas_2_data': ('s3.io_in_bits_datas_2_data', 64),
    's3.io_in_bits_datas_3_data': ('s3.io_in_bits_datas_3_data', 64),
    's3.io_in_bits_hit': ('s3.io_in_bits_hit', 1),
    's3.io_in_bits_waymask': ('s3.io_in_bits_waymask', 4),
    's3.io_in_bits_mmio': ('s3.io_in_bits_mmio', 1),
    's3.io_in_bits_isForwardData': ('s3.io_in_bits_isForwardData', 1),
    's3.io_in_bits_forwardData_data_data': ('s3.io_in_bits_forwardData_data_data', 64),
    's3.io_in_bits_forwardData_waymask': ('s3.io_in_bits_forwardData_waymask', 4),
    's3.io_out_ready': ('s3.io_out_ready', 1),
    's3.io_out_valid': ('s3.io_out_valid', 1),
    's3.io_out_bits_cmd': ('s3.io_out_bits_cmd', 4),
    's3.io_out_bits_rdata': ('s3.io_out_bits_rdata', 64),
    's3.io_out_bits_user': ('s3.io_out_bits_user', 16),
    's3.io_isFinish': ('s3.io_isFinish', 1),
    's3.io_flush': ('s3.io_flush', 1),
    's3.io_dataReadBus_req_ready': ('s3.io_dataReadBus_req_ready', 1),
    's3.io_dataReadBus_req_valid': ('s3.io_dataReadBus_req_valid', 1),
    's3.io_dataReadBus_req_bits_setIdx': ('s3.io_dataReadBus_req_bits_setIdx', 10),
    's3.io_dataReadBus_resp_data_0_data': ('s3.io_dataReadBus_resp_data_0_data', 64),
    's3.io_dataReadBus_resp_data_1_data': ('s3.io_dataReadBus_resp_data_1_data', 64),
    's3.io_dataReadBus_resp_data_2_data': ('s3.io_dataReadBus_resp_data_2_data', 64),
    's3.io_dataReadBus_resp_data_3_data': ('s3.io_dataReadBus_resp_data_3_data', 64),
    's3.io_dataWriteBus_req_valid': ('s3.io_dataWriteBus_req_valid', 1),
    's3.io_dataWriteBus_req_bits_setIdx': ('s3.io_dataWriteBus_req_bits_setIdx', 10),
    's3.io_dataWriteBus_req_bits_data_data': ('s3.io_dataWriteBus_req_bits_data_data', 64),
    's3.io_dataWriteBus_req_bits_waymask': ('s3.io_dataWriteBus_req_bits_waymask', 4),
    's3.io_metaWriteBus_req_valid': ('s3.io_metaWriteBus_req_valid', 1),
    's3.io_metaWriteBus_req_bits_setIdx': ('s3.io_metaWriteBus_req_bits_setIdx', 7),
    's3.io_metaWriteBus_req_bits_data_tag': ('s3.io_metaWriteBus_req_bits_data_tag', 19),
    's3.io_metaWriteBus_req_bits_data_dirty': ('s3.io_metaWriteBus_req_bits_data_dirty', 1),
    's3.io_metaWriteBus_req_bits_waymask': ('s3.io_metaWriteBus_req_bits_waymask', 4),
    's3.io_mem_req_ready': ('s3.io_mem_req_ready', 1),
    's3.io_mem_req_valid': ('s3.io_mem_req_valid', 1),
    's3.io_mem_req_bits_addr': ('s3.io_mem_req_bits_addr', 32),
    's3.io_mem_req_bits_cmd': ('s3.io_mem_req_bits_cmd', 4),
    's3.io_mem_req_bits_wdata': ('s3.io_mem_req_bits_wdata', 64),
    's3.io_mem_resp_ready': ('s3.io_mem_resp_ready', 1),
    's3.io_mem_resp_valid': ('s3.io_mem_resp_valid', 1),
    's3.io_mem_resp_bits_cmd': ('s3.io_mem_resp_bits_cmd', 4),
    's3.io_mem_resp_bits_rdata': ('s3.io_mem_resp_bits_rdata', 64),
    's3.io_mmio_req_ready': ('s3.io_mmio_req_ready', 1),
    's3.io_mmio_req_valid': ('s3.io_mmio_req_valid', 1),
    's3.io_mmio_req_bits_addr': ('s3.io_mmio_req_bits_addr', 32),
    's3.io_mmio_req_bits_size': ('s3.io_mmio_req_bits_size', 3),
    's3.io_mmio_req_bits_cmd': ('s3.io_mmio_req_bits_cmd', 4),
    's3.io_mmio_req_bits_wmask': ('s3.io_mmio_req_bits_wmask', 8),
    's3.io_mmio_req_bits_wdata': ('s3.io_mmio_req_bits_wdata', 64),
    's3.io_mmio_resp_ready': ('s3.io_mmio_resp_ready', 1),
    's3.io_mmio_resp_valid': ('s3.io_mmio_resp_valid', 1),
    's3.io_mmio_resp_bits_rdata': ('s3.io_mmio_resp_bits_rdata', 64),
    's3.io_cohResp_ready': ('s3.io_cohResp_ready', 1),
    's3.io_cohResp_valid': ('s3.io_cohResp_valid', 1),
    's3.io_cohResp_bits_cmd': ('s3.io_cohResp_bits_cmd', 4),
    's3.io_cohResp_bits_rdata': ('s3.io_cohResp_bits_rdata', 64),
    's3.io_dataReadRespToL1': ('s3.io_dataReadRespToL1', 1),
    's3.metaWriteArb_io_in_0_valid': ('s3.metaWriteArb_io_in_0_valid', 1),
    's3.metaWriteArb_io_in_0_bits_setIdx': ('s3.metaWriteArb_io_in_0_bits_setIdx', 7),
    's3.metaWriteArb_io_in_0_bits_data_tag': ('s3.metaWriteArb_io_in_0_bits_data_tag', 19),
    's3.metaWriteArb_io_in_0_bits_waymask': ('s3.metaWriteArb_io_in_0_bits_waymask', 4),
    's3.metaWriteArb_io_in_1_valid': ('s3.metaWriteArb_io_in_1_valid', 1),
    's3.metaWriteArb_io_in_1_bits_setIdx': ('s3.metaWriteArb_io_in_1_bits_setIdx', 7),
    's3.metaWriteArb_io_in_1_bits_data_tag': ('s3.metaWriteArb_io_in_1_bits_data_tag', 19),
    's3.metaWriteArb_io_in_1_bits_data_dirty': ('s3.metaWriteArb_io_in_1_bits_data_dirty', 1),
    's3.metaWriteArb_io_in_1_bits_waymask': ('s3.metaWriteArb_io_in_1_bits_waymask', 4),
    's3.metaWriteArb_io_out_valid': ('s3.metaWriteArb_io_out_valid', 1),
    's3.metaWriteArb_io_out_bits_setIdx': ('s3.metaWriteArb_io_out_bits_setIdx', 7),
    's3.metaWriteArb_io_out_bits_data_tag': ('s3.metaWriteArb_io_out_bits_data_tag', 19),
    's3.metaWriteArb_io_out_bits_data_dirty': ('s3.metaWriteArb_io_out_bits_data_dirty', 1),
    's3.metaWriteArb_io_out_bits_waymask': ('s3.metaWriteArb_io_out_bits_waymask', 4),
    's3.dataWriteArb_io_in_0_valid': ('s3.dataWriteArb_io_in_0_valid', 1),
    's3.dataWriteArb_io_in_0_bits_setIdx': ('s3.dataWriteArb_io_in_0_bits_setIdx', 10),
    's3.dataWriteArb_io_in_0_bits_data_data': ('s3.dataWriteArb_io_in_0_bits_data_data', 64),
    's3.dataWriteArb_io_in_0_bits_waymask': ('s3.dataWriteArb_io_in_0_bits_waymask', 4),
    's3.dataWriteArb_io_in_1_valid': ('s3.dataWriteArb_io_in_1_valid', 1),
    's3.dataWriteArb_io_in_1_bits_setIdx': ('s3.dataWriteArb_io_in_1_bits_setIdx', 10),
    's3.dataWriteArb_io_in_1_bits_data_data': ('s3.dataWriteArb_io_in_1_bits_data_data', 64),
    's3.dataWriteArb_io_in_1_bits_waymask': ('s3.dataWriteArb_io_in_1_bits_waymask', 4),
    's3.dataWriteArb_io_out_valid': ('s3.dataWriteArb_io_out_valid', 1),
    's3.dataWriteArb_io_out_bits_setIdx': ('s3.dataWriteArb_io_out_bits_setIdx', 10),
    's3.dataWriteArb_io_out_bits_data_data': ('s3.dataWriteArb_io_out_bits_data_data', 64),
    's3.dataWriteArb_io_out_bits_waymask': ('s3.dataWriteArb_io_out_bits_waymask', 4),
    's3.addr_wordIndex': ('s3.addr_wordIndex', 3),
    's3.addr_index': ('s3.addr_index', 7),
    's3.mmio': ('s3.mmio', 1),
    's3.hit': ('s3.hit', 1),
    's3.miss': ('s3.miss', 1),
    's3.probe': ('s3.probe', 1),
    's3.hitReadBurst': ('s3.hitReadBurst', 1),
    's3.meta_dirty': ('s3.meta_dirty', 1),
    's3.meta_tag': ('s3.meta_tag', 19),
    's3.useForwardData': ('s3.useForwardData', 1),
    's3.dataRead': ('s3.dataRead', 64),
    's3.wordMask': ('s3.wordMask', 64),
    's3.writeL2BeatCnt_value': ('s3.writeL2BeatCnt_value', 3),
    's3.hitWrite': ('s3.hitWrite', 1),
    's3.metaHitWriteBus_x5': ('s3.metaHitWriteBus_x5', 1),
    's3.state': ('s3.state', 4),
    's3.needFlush': ('s3.needFlush', 1),
    's3.readBeatCnt_value': ('s3.readBeatCnt_value', 3),
    's3.writeBeatCnt_value': ('s3.writeBeatCnt_value', 3),
    's3.state2': ('s3.state2', 2),
    's3.dataWay_0_data': ('s3.dataWay_0_data', 64),
    's3.dataWay_1_data': ('s3.dataWay_1_data', 64),
    's3.dataWay_2_data': ('s3.dataWay_2_data', 64),
    's3.dataWay_3_data': ('s3.dataWay_3_data', 64),
    's3.raddr': ('s3.raddr', 32),
    's3.waddr': ('s3.waddr', 32),
    's3.cmd': ('s3.cmd', 3),
    's3.afterFirstRead': ('s3.afterFirstRead', 1),
    's3.alreadyOutFire': ('s3.alreadyOutFire', 1),
    's3.readingFirst': ('s3.readingFirst', 1),
    's3.inRdataRegDemand': ('s3.inRdataRegDemand', 64),
    's3.releaseLast_c_value': ('s3.releaseLast_c_value', 3),
    's3.releaseLast_wrap_wrap': ('s3.releaseLast_wrap_wrap', 1),
    's3.releaseLast': ('s3.releaseLast', 1),
    's3.respToL1Fire': ('s3.respToL1Fire', 1),
    's3.respToL1Last_c_value': ('s3.respToL1Last_c_value', 3),
    's3.respToL1Last_wrap_wrap': ('s3.respToL1Last_wrap_wrap', 1),
    's3.respToL1Last': ('s3.respToL1Last', 1),
    's3.dataRefillWriteBus_x9': ('s3.dataRefillWriteBus_x9', 1),
    's3.metaRefillWriteBus_req_valid': ('s3.metaRefillWriteBus_req_valid', 1),
    'reset': ('reset', 1),
    'valid': ('valid', 1),
    'valid_1': ('valid_1', 1),
    'io_empty': ('io_empty', 1),
    'io_flush': ('io_flush', 2),
    'metaArray.ram.resetState': ('metaArray.ram.resetState', 1),
    'metaArray.ram.resetSet': ('metaArray.ram.resetSet', 7),
    'metaArray.ram.wen': ('metaArray.ram.wen', 1),
    'metaArray.ram.io_r_req_ready': ('metaArray.ram.io_r_req_ready', 1),
    'metaArray.ram.io_r_req_valid': ('metaArray.ram.io_r_req_valid', 1),
    'metaArray.ram.array_0_rdata_MPORT_addr_pipe_0': ('metaArray.ram.array_0_rdata_MPORT_addr_pipe_0', 7),
    'metaArray.ram.array_0_rdata_MPORT_en_pipe_0': ('metaArray.ram.array_0_rdata_MPORT_en_pipe_0', 1),
    'metaArray.ram.array_0_MPORT_addr': ('metaArray.ram.array_0_MPORT_addr', 7),
    'metaArray.ram.array_0_MPORT_data': ('metaArray.ram.array_0_MPORT_data', 21),
    'metaArray.ram.array_0_MPORT_mask': ('metaArray.ram.array_0_MPORT_mask', 1),
    'metaArray.ram.array_0_MPORT_en': ('metaArray.ram.array_0_MPORT_en', 1),
    'metaArray.ram.array_0_rdata_MPORT_data': ('metaArray.ram.array_0_rdata_MPORT_data', 21),
    'metaArray.ram.array_1_MPORT_addr': ('metaArray.ram.array_1_MPORT_addr', 7),
    'metaArray.ram.array_1_MPORT_data': ('metaArray.ram.array_1_MPORT_data', 21),
    'metaArray.ram.array_1_MPORT_mask': ('metaArray.ram.array_1_MPORT_mask', 1),
    'metaArray.ram.array_1_MPORT_en': ('metaArray.ram.array_1_MPORT_en', 1),
    'metaArray.ram.array_1_rdata_MPORT_data': ('metaArray.ram.array_1_rdata_MPORT_data', 21),
    'metaArray.ram.array_2_MPORT_addr': ('metaArray.ram.array_2_MPORT_addr', 7),
    'metaArray.ram.array_2_MPORT_data': ('metaArray.ram.array_2_MPORT_data', 21),
    'metaArray.ram.array_2_MPORT_mask': ('metaArray.ram.array_2_MPORT_mask', 1),
    'metaArray.ram.array_2_MPORT_en': ('metaArray.ram.array_2_MPORT_en', 1),
    'metaArray.ram.array_2_rdata_MPORT_data': ('metaArray.ram.array_2_rdata_MPORT_data', 21),
    'metaArray.ram.array_3_MPORT_addr': ('metaArray.ram.array_3_MPORT_addr', 7),
    'metaArray.ram.array_3_MPORT_data': ('metaArray.ram.array_3_MPORT_data', 21),
    'metaArray.ram.array_3_MPORT_mask': ('metaArray.ram.array_3_MPORT_mask', 1),
    'metaArray.ram.array_3_MPORT_en': ('metaArray.ram.array_3_MPORT_en', 1),
    'metaArray.ram.array_3_rdata_MPORT_data': ('metaArray.ram.array_3_rdata_MPORT_data', 21),
    'dataArray.io_r_0_req_valid': ('dataArray.io_r_0_req_valid', 1),
    'dataArray.io_r_0_req_ready': ('dataArray.io_r_0_req_ready', 1),
    'dataArray.io_r_0_req_bits_setIdx': ('dataArray.io_r_0_req_bits_setIdx', 10),
    'dataArray.r___05F0_data': ('dataArray.r___05F0_data', 64),
    'dataArray.r___05F1_data': ('dataArray.r___05F1_data', 64),
    'dataArray.r___05F2_data': ('dataArray.r___05F2_data', 64),
    'dataArray.r___05F3_data': ('dataArray.r___05F3_data', 64),
    'dataArray.REG': ('dataArray.REG', 1),
    'dataArray.io_r_1_req_valid': ('dataArray.io_r_1_req_valid', 1),
    'dataArray.io_r_1_req_ready': ('dataArray.io_r_1_req_ready', 1),
    'dataArray.io_r_1_req_bits_setIdx': ('dataArray.io_r_1_req_bits_setIdx', 10),
    'dataArray.r_1_0_data': ('dataArray.r_1_0_data', 64),
    'dataArray.r_1_1_data': ('dataArray.r_1_1_data', 64),
    'dataArray.r_1_2_data': ('dataArray.r_1_2_data', 64),
    'dataArray.r_1_3_data': ('dataArray.r_1_3_data', 64),
    'dataArray.REG_1': ('dataArray.REG_1', 1),
    'dataArray.ram_io_r_resp_data_0_data': ('dataArray.ram_io_r_resp_data_0_data', 64),
    'dataArray.ram_io_r_resp_data_1_data': ('dataArray.ram_io_r_resp_data_1_data', 64),
    'dataArray.ram_io_r_resp_data_2_data': ('dataArray.ram_io_r_resp_data_2_data', 64),
    'dataArray.ram_io_r_resp_data_3_data': ('dataArray.ram_io_r_resp_data_3_data', 64),
    'arb.io_in_0_valid': ('arb.io_in_0_valid', 1),
    'arb.io_in_0_ready': ('arb.io_in_0_ready', 1),
    'arb.io_in_0_bits_addr': ('arb.io_in_0_bits_addr', 32),
    'arb.io_in_0_bits_size': ('arb.io_in_0_bits_size', 3),
    'arb.io_in_0_bits_cmd': ('arb.io_in_0_bits_cmd', 4),
    'arb.io_in_0_bits_wmask': ('arb.io_in_0_bits_wmask', 8),
    'arb.io_in_0_bits_wdata': ('arb.io_in_0_bits_wdata', 64),
    'arb.io_in_1_valid': ('arb.io_in_1_valid', 1),
    'arb.io_in_1_ready': ('arb.io_in_1_ready', 1),
    'arb.io_in_1_bits_addr': ('arb.io_in_1_bits_addr', 32),
    'arb.io_in_1_bits_size': ('arb.io_in_1_bits_size', 3),
    'arb.io_in_1_bits_cmd': ('arb.io_in_1_bits_cmd', 4),
    'arb.io_in_1_bits_wmask': ('arb.io_in_1_bits_wmask', 8),
    'arb.io_in_1_bits_wdata': ('arb.io_in_1_bits_wdata', 64),
}

MASK64 = (1 << 64) - 1
REQUEST_FIELDS = ("addr", "size", "cmd", "wmask", "wdata", "user")
S3_FIELDS = tuple("req_" + field for field in REQUEST_FIELDS) + tuple(
    f"metas_{way}_{field}" for way in range(4) for field in ("tag", "dirty")
) + tuple(f"datas_{way}_data" for way in range(4)) + (
    "hit", "waymask", "mmio", "isForwardData", "forwardData_data_data", "forwardData_waymask",
)


def byte_mask(mask):
    return sum(0xff << (8 * byte) for byte in range(8) if mask & (1 << byte))


def merge(old, new, mask):
    return ((old & ~mask) | (new & mask)) & MASK64


class CacheInternalObserver(ClockObserver):
    """Check settled conditions and committed state using accepted-event history."""
    def __init__(self, dut, *, seed=1):
        super().__init__(dut, prefix="CacheSignalCFG_top.Cache.", signals=SIGNALS)
        self.checks = ScenarioChecks(RULES, run_metadata={
            "test": os.environ.get("PYTEST_CURRENT_TEST", "cache-campaign"), "seed": seed,
        }, contract="cache.rtl-properties/v1")
        self.checks.implemented = set(RULES)
        # Directory/data retain arbitrary initial contents until observed writes.
        self.directory = {}
        self.data = {}
        self.last_running = None
        self.previous_s1_addr = None
        self.forward_meta_stall = 0
        self.refill_beats = 0
        self.release_start = 0
        self.arbitration_wait = None
        self.previous_data_port = None
        self.previous_meta_write = None
        self.was_sweeping = False
        self.last_hit_write = None
        self.prior_data = {}
        self.probe_history = []
        self.after_reset = False
        self.reset_retained_nonzero = False

    def observe(self, p, q, tick):
        self._tick = tick
        def check(name, scenario, actual, expected, **detail):
            self.checks.check("CACHE-INT-" + name, scenario, actual=actual, expected=expected,
                              tick=tick, context={"state": p["s3.state"],
                                                 "address": p["s3.io_in_bits_req_addr"], **detail})
        self._arrays(p, q, check)
        self._lookup(p, q, check)
        self._forwarding(p, q, check)
        if p["reset"]:
            old = self.last_running or p
            mode = {2: "refill", 3: "writeback", 8: "release"}.get(old["s3.state"], "idle")
            keys = ("valid", "valid_1", "s3.state", "s3.state2", "s3.readBeatCnt_value",
                    "s3.writeBeatCnt_value", "s3.writeL2BeatCnt_value", "s3.releaseLast_c_value",
                    "s3.respToL1Last_c_value", "s3.afterFirstRead", "s3.alreadyOutFire",
                    "s2.isForwardMetaReg", "s2.isForwardDataReg")
            check("RESET-CONTROL", mode, tuple(q[key] for key in keys), (0,) * len(keys))
            self.last_running = None
            self.forward_meta_stall = self.refill_beats = 0
            self.previous_s1_addr = self.previous_data_port = None
            self.arbitration_wait = None
            self.last_hit_write = None
            self.probe_history.clear()
            self.after_reset = True
            self.reset_retained_nonzero = any(self.data.values())
            return
        self._pipeline(p, q, check)
        self._forwarding_s3(p, q, check)
        self._stage3(p, q, check)
        self.last_running = q

    def _pipeline(self, p, q, c):
        s1 = bool(p["s1.io_out_valid"] and p["s1.io_out_ready"])
        s2 = bool(p["s2.io_out_valid"] and p["s2.io_out_ready"])
        flush2 = bool(p["io_flush"] & 1)
        meta, data = p["s1.io_metaReadBus_req_ready"], p["s1.io_dataReadBus_req_ready"]
        if p["s1.io_in_valid"]:
            case = "meta_blocked" if not meta else "data_blocked" if not data else "both_ready"
            allowed = bool(meta and data)
            c("PIPE-S1-JOINT-READY", case,
              (p["s1.io_out_valid"], p["s1.io_in_ready"]),
              (int(allowed), int(allowed and bool(p["s1.io_out_ready"]))))
        addr = p["s1.io_in_bits_addr"]
        if s1:
            if self.previous_s1_addr is not None:
                changed = self.previous_s1_addr ^ addr
                case = "tag_boundary" if changed >> 13 else "set_boundary" if changed >> 6 else "word_boundary"
                c("PIPE-S1-INDEX", case,
                  (p["s1.io_metaReadBus_req_bits_setIdx"], p["s1.io_dataReadBus_req_bits_setIdx"]),
                  ((addr >> 6) & 127, (addr >> 3) & 1023))
            self.previous_s1_addr = addr
        payload2 = tuple(q["s2.io_in_bits_req_" + field] for field in REQUEST_FIELDS)
        if s1 or (p["valid"] and not s2):
            c("PIPE-S2-HOLD", "replace" if s1 and p["valid"] else "load" if s1 else "stall",
              payload2, tuple(p[("s1.io_out_bits_req_" if s1 else "s2.io_in_bits_req_") + field]
                              for field in REQUEST_FIELDS))
        if s2:
            c("PIPE-S2-CONSUME", "consume_and_fill" if s1 else "consume_only", q["valid"], int(s1 and not flush2))
        if flush2:
            c("PIPE-S2-FLUSH", "accept_same_cycle" if s1 else "held" if p["valid"] and not s2 else "empty",
              q["valid"], 0)
        assert q["valid"] == int(not flush2 and (s1 or (p["valid"] and not s2))), "Stage2 occupancy mismatch"
        payload3 = tuple(q["s3.io_in_bits_" + field] for field in S3_FIELDS)
        if s2 or (p["valid_1"] and not p["s3.io_isFinish"]):
            case = "same_cycle_finish_new" if s2 and p["s3.io_isFinish"] else "load" if s2 else "stall"
            c("PIPE-S3-HOLD", case, payload3,
              tuple(p[("s2.io_out_bits_" if s2 else "s3.io_in_bits_") + field] for field in S3_FIELDS))
        expected3 = int(s2 or (p["valid_1"] and not p["s3.io_isFinish"]))
        assert q["valid_1"] == expected3, "Stage3 occupancy mismatch"
        cpu_fire = p["s3.io_out_valid"] and p["s3.io_out_ready"]
        if p["s3.state"] == 2 and cpu_fire:
            c("PIPE-RETIRE", "early_response", (p["s3.io_isFinish"], q["valid_1"]), (0, 1))
        if p["s3.state"] == 2 and p["s3.io_mem_resp_valid"] and p["s3.io_mem_resp_bits_cmd"] == 6:
            c("PIPE-RETIRE", "final_refill", q["valid_1"], 1)
        if s2 and p["s3.io_isFinish"]:
            c("PIPE-RETIRE", "finish_and_new", (q["valid_1"], payload3), (1, tuple(p["s2.io_out_bits_" + f] for f in S3_FIELDS)))
        if (p["s3.state"] == 7 and p["valid_1"] and not p["s3.alreadyOutFire"]
                and not cpu_fire and not (p["s3.io_in_bits_req_cmd"] & 1) and not p["s3.mmio"]):
            c("EARLY-FINAL-WHILE-STALLED", "full_refill_before_CPU_accept",
              (q["s3.inRdataRegDemand"], q["valid_1"], p["s3.io_isFinish"]), (p["s3.inRdataRegDemand"], 1, 0))
        occupancy = (p["valid"], p["valid_1"])
        dirty = any(meta[2] for meta in self.directory.values())
        case = {(1, 0): "s2_only", (0, 1): "s3_only", (1, 1): "both"}.get(
            occupancy, "empty_dirty" if dirty else "empty_clean")
        c("PIPE-EMPTY", case, p["io_empty"], int(not any(occupancy)))
        v0, v1 = p["arb.io_in_0_valid"], p["arb.io_in_1_valid"]
        if v0 or v1:
            case = "both" if v0 and v1 else "probe_only" if v0 else "CPU_only"
            selected = 0 if v0 else 1
            c("ARBITRATION-PROBE-PRIORITY", case,
              (p["arb.io_in_0_ready"], p["arb.io_in_1_ready"], p["s1.io_in_bits_addr"], p["s1.io_in_bits_cmd"]),
              (p["s1.io_in_ready"], int(not v0 and p["s1.io_in_ready"]),
               p[f"arb.io_in_{selected}_bits_addr"], p[f"arb.io_in_{selected}_bits_cmd"]))

    def _lookup(self, p, q, c):
        lfsr = p["s2.victimWaymask_lfsr"]
        nxt = 1 if lfsr == 0 else (lfsr >> 1) | (
            (((lfsr >> 0) ^ (lfsr >> 1) ^ (lfsr >> 3) ^ (lfsr >> 4)) & 1) << 63)
        c("LOOKUP-LFSR", "reset_seed" if p["reset"] else "zero_recovery" if not lfsr else "advance",
          q["s2.victimWaymask_lfsr"], 0x1234567887654321 if p["reset"] else nxt)
        if p["reset"]:
            return
        addr = p["s2.io_in_bits_req_addr"]
        metas = [(p[f"s2.metaWay_{w}_tag"], p[f"s2.metaWay_{w}_valid"]) for w in range(4)]
        hit = sum(1 << w for w, (tag, valid) in enumerate(metas)
                  if valid and tag == addr >> 13 and p["s2.io_in_valid"])
        invalid = sum(1 << w for w, (_, valid) in enumerate(metas) if not valid)
        candidate = 1 << (lfsr & 3)
        expected_way = hit or ((1 << (invalid.bit_length() - 1)) if invalid else candidate)
        if p["s2.io_in_valid"]:
            if hit and hit.bit_count() == 1:
                c("LOOKUP-HIT-EACH-WAY", f"way{hit.bit_length() - 1}",
                  (p["s2.hitVec"], p["s2.io_out_bits_hit"], p["s2.waymask"]), (hit, 1, hit))
            for way, (tag, valid) in enumerate(metas):
                if not valid and tag == addr >> 13:
                    c("LOOKUP-INVALID-TAG", f"way{way}", (p["s2.hitVec"] >> way) & 1, 0)
            if not hit and invalid:
                c("LOOKUP-INVALID-FIRST", "one_invalid" if invalid.bit_count() == 1 else "multiple_invalid",
                  p["s2.waymask"], expected_way)
                c("LOOKUP-INVALID-PRIORITY", f"invalidVec={invalid}",
                  (p["s2.invalidVec"], p["s2.refillInvalidWaymask"], p["s2.waymask"]),
                  (invalid, expected_way, expected_way))
            if not hit and not invalid:
                c("LOOKUP-ALL-VALID", f"candidate{lfsr & 3}", p["s2.waymask"], candidate)
            case = "duplicate_tag_negative" if hit.bit_count() > 1 else "hit" if hit else "invalid_miss" if invalid else "victim_miss"
            c("LOOKUP-ONEHOT", case, p["s2.waymask"].bit_count(), 1)
            if self.after_reset and not p["s2.io_out_bits_mmio"] and p["s2.io_in_bits_req_cmd"] != 8:
                c("RESET-UNRESET-DATA", "first_miss", p["s2.io_out_bits_hit"], 0)
                if self.reset_retained_nonzero:
                    c("RESET-UNRESET-DATA", "old_nonzero_data", p["s2.io_out_bits_hit"], 0)
                # Retain the obligation until the lookup is actually consumed.
                if p["s2.io_in_ready"]:
                    self.after_reset = False
            if hex(addr) in RULES["CACHE-INT-LOOKUP-MMIO-RANGES"].scenarios:
                c("LOOKUP-MMIO-RANGES", hex(addr), p["s2.io_out_bits_mmio"], int(0x30000000 <= addr < 0x80000000))
        else:
            equal = any(valid and tag == addr >> 13 for tag, valid in metas)
            c("LOOKUP-NO-INPUT", "tag_equal" if equal else "tag_unequal", (p["s2.hitVec"], p["s2.io_out_bits_hit"]), (0, 0))

    def _forwarding(self, p, q, c):
        valid = p["s2.io_in_valid"]
        consumed = valid and p["s2.io_in_ready"]
        clear = p["reset"] or consumed or not valid
        addr = p["s2.io_in_bits_req_addr"]
        meta_now = bool(valid and p["s2.io_metaWriteBus_req_valid"]
                        and p["s2.io_metaWriteBus_req_bits_setIdx"] == ((addr >> 6) & 127))
        data_now = bool(valid and p["s2.io_dataWriteBus_req_valid"]
                        and p["s2.io_dataWriteBus_req_bits_setIdx"] == ((addr >> 3) & 1023))
        expected_mflag = int(not clear and (meta_now or p["s2.isForwardMetaReg"]))
        expected_dflag = int(not clear and (data_now or p["s2.isForwardDataReg"]))
        clear_case = "reset" if p["reset"] else "consumed" if consumed else "bubble"
        if clear:
            c("FORWARD-META-CLEAR", clear_case, q["s2.isForwardMetaReg"], 0)
            c("FORWARD-DATA-HOLD", "reset" if p["reset"] else "consume" if consumed else "bubble", q["s2.isForwardDataReg"], 0)
        if p["reset"]:
            return
        if valid and p["s2.io_metaWriteBus_req_valid"] and not meta_now:
            delta = abs(p["s2.io_metaWriteBus_req_bits_setIdx"] - ((addr >> 6) & 127))
            case = "adjacent_set" if delta == 1 else "different_tag_same_word"
            c("FORWARD-META-DIFFERENT", case, p["s2.isForwardMeta"], 0)
        pick_meta = meta_now or p["s2.isForwardMetaReg"]
        source = "s2.io_metaWriteBus_req_bits_" if meta_now else "s2.forwardMetaReg_"
        waymask = p[source + "waymask"]
        expected_metas = []
        for way in range(4):
            selected = pick_meta and waymask & (1 << way)
            expected = ((p[source + "data_tag"], 1, p[source + "data_dirty"]) if selected else
                        tuple(p[f"s2.io_metaReadResp_{way}_{field}"] for field in ("tag", "valid", "dirty")))
            actual = (p[f"s2.metaWay_{way}_tag"], p[f"s2.metaWay_{way}_valid"], p[f"s2.io_out_bits_metas_{way}_dirty"])
            expected_metas.append(expected)
            if meta_now and selected:
                c("FORWARD-META-SAME-SET", f"way{way}", actual, expected)
                old = tuple(p[f"s2.io_metaReadResp_{way}_{field}"] for field in ("tag", "valid", "dirty"))
                if not old[1] and expected[0] == addr >> 13:
                    c("FORWARD-META-SAME-SET", "hit_created", actual, expected)
                if old[2] != expected[2]:
                    c("FORWARD-META-SAME-SET", "dirty_updated", actual, expected)
            if pick_meta:
                assert actual == expected, "metadata forwarding selected stale data"
        if meta_now and p["s2.isForwardMetaReg"]:
            c("FORWARD-META-NEWEST", "same_way_twice" if waymask == p["s2.forwardMetaReg_waymask"] else "different_way_followup",
              tuple(q["s2.forwardMetaReg_" + f] for f in ("data_tag", "data_dirty", "waymask")),
              tuple(p[source + f] for f in ("data_tag", "data_dirty", "waymask")))
        if valid and not consumed and pick_meta:
            self.forward_meta_stall += 1
            c("FORWARD-META-HOLD", "multi_cycle_stall" if self.forward_meta_stall >= 2 else "single_update",
              q["s2.isForwardMetaReg"], expected_mflag)
        else:
            self.forward_meta_stall = 0
        if valid and p["s2.io_dataWriteBus_req_valid"]:
            write_index = p["s2.io_dataWriteBus_req_bits_setIdx"]
            case = "same_word" if data_now else "different_word" if write_index >> 3 == ((addr >> 6) & 127) else "different_set"
            c("FORWARD-DATA-WORD", case, p["s2.isForwardData"], int(data_now))
        if valid and not consumed and (data_now or p["s2.isForwardDataReg"]):
            c("FORWARD-DATA-HOLD", "hold", q["s2.isForwardDataReg"], expected_dflag)
        data_source = "s2.io_dataWriteBus_req_bits_" if data_now else "s2.forwardDataReg_"
        if data_now or p["s2.isForwardDataReg"]:
            expected = tuple(p[data_source + f] for f in ("data_data", "waymask"))
            actual = (p["s2.io_out_bits_forwardData_data_data"], p["s2.io_out_bits_forwardData_waymask"])
            assert actual == expected, "data forwarding lost data/way pairing"
            if data_now and p["s2.isForwardDataReg"]:
                c("FORWARD-DATA-NEWEST", "same_way" if expected[1] == p["s2.forwardDataReg_waymask"] else "way_changed", actual, expected)
    def _forwarding_s3(self, p, q, c):
        if p["s3.io_in_valid"] and p["s3.io_in_bits_isForwardData"]:
            match = p["s3.io_in_bits_waymask"] == p["s3.io_in_bits_forwardData_waymask"]
            expected = p["s3.io_in_bits_forwardData_data_data"] if match else sum(
                p[f"s3.io_in_bits_datas_{way}_data"] for way in range(4) if p["s3.io_in_bits_waymask"] & (1 << way))
            c("FORWARD-WAY-QUALIFY", "match" if match else "mismatch", (p["s3.useForwardData"], p["s3.dataRead"]), (int(match), expected))

    def _stage3(self, p, q, c):
        state = p["s3.state"]
        valid = p["s3.io_in_valid"]
        addr, cmd = p["s3.io_in_bits_req_addr"], p["s3.io_in_bits_req_cmd"]
        index, word, tag = (addr >> 6) & 127, (addr >> 3) & 7, addr >> 13
        mem = bool(p["s3.io_mem_req_valid"] and p["s3.io_mem_req_ready"])
        rsp = bool(p["s3.io_mem_resp_valid"] and p["s3.io_mem_resp_ready"])
        cpu = bool(p["s3.io_out_valid"] and p["s3.io_out_ready"])
        coh = bool(p["s3.io_cohResp_valid"] and p["s3.io_cohResp_ready"])
        mmio_cmd = bool(p["s3.io_mmio_req_valid"] and p["s3.io_mmio_req_ready"])
        mmio_rsp = bool(p["s3.io_mmio_resp_valid"] and p["s3.io_mmio_resp_ready"])
        read = p["s3.readBeatCnt_value"]
        write = p["s3.writeBeatCnt_value"]
        after, returned = p["s3.afterFirstRead"], p["s3.alreadyOutFire"]
        first = bool(state == 2 and rsp and not after)
        last = bool(rsp and p["s3.io_mem_resp_bits_cmd"] == 6)
        is_write = bool(cmd & 1)
        hit, probe, mmio = p["s3.hit"], p["s3.probe"], p["s3.mmio"]
        if state == 0 and valid:
            if probe:
                case = "header_stalled" if not coh else "hit" if hit else "miss"
                c("FSM-PROBE", case, q["s3.state"], 8 if coh and hit else 0)
                c("COHERENCE-COUNT-INIT", "stalled" if not coh else "hit" if hit else "miss", q["s3.readBeatCnt_value"], word if coh else read)
                if coh and hit:
                    self.release_start = word
                if coh:
                    self.probe_history.append("hit" if hit else "miss")
                    if self.probe_history[-2:] == ["hit", "hit"]:
                        c("COHERENCE-REPEATED", "hit_hit", p["s3.releaseLast_c_value"], 0)
                    if self.probe_history[-3:] == ["hit", "miss", "hit"]:
                        c("COHERENCE-REPEATED", "hit_miss_hit", p["s3.releaseLast_c_value"], 0)
            elif mmio:
                c("FSM-IDLE-MMIO", "write" if is_write else "read", q["s3.state"], 5)
            elif p["s3.miss"]:
                if p["s3.meta_dirty"]:
                    way = p["s3.io_in_bits_waymask"].bit_length() - 1
                    c("FSM-IDLE-DIRTY", f"way{way}", q["s3.state"], 3)
                else:
                    way = p["s3.io_in_bits_waymask"].bit_length() - 1
                    victim = self.directory.get((index, way))
                    c("FSM-IDLE-CLEAN", "valid_clean_victim" if victim and victim[1] else "invalid_victim", q["s3.state"], 1)
        elif state == 1:
            c("FSM-READ-REQUEST", "accepted" if mem else "stalled", q["s3.state"], 2 if mem else 1)
            if mem:
                c("REFILL-COUNT-INIT", f"start{word}", q["s3.readBeatCnt_value"], word)
                self.refill_beats = 0
        elif state == 2:
            case = "last_valid" if last else "middle" if rsp else "last_without_valid" if p["s3.io_mem_resp_bits_cmd"] == 6 else "gap"
            c("FSM-READ-END", case, q["s3.state"], 7 if last else 2)
            c("REFILL-COUNT-STEP", "wrap" if rsp and read == 7 else "increment" if rsp else "gap", q["s3.readBeatCnt_value"], (read + int(rsp)) & 7)
            c("REFILL-DATA-WRITE", f"beat{self.refill_beats}" if rsp else "gap_no_write", p["s3.dataRefillWriteBus_x9"], int(rsp))
            if rsp:
                expected = merge(p["s3.io_mem_resp_bits_rdata"], p["s3.io_in_bits_req_wdata"], byte_mask(p["s3.io_in_bits_req_wmask"]) if first and is_write else 0)
                actual = (p["s3.dataWriteArb_io_in_1_bits_setIdx"], p["s3.dataWriteArb_io_in_1_bits_waymask"], p["s3.dataWriteArb_io_in_1_bits_data_data"])
                assert actual == ((index << 3) | read, p["s3.io_in_bits_waymask"], expected), "refill data/address/way mismatch"
                self.refill_beats += 1
                if is_write:
                    mask = p["s3.io_in_bits_req_wmask"]
                    case = "first_vs_later" if not first else "zero_mask" if mask == 0 else "partial_mask"
                    c("REFILL-WRITE-MERGE", case, actual[2], expected)
            c("REFILL-META-LAST", "last" if last else "last_gap" if not rsp and p["s3.io_mem_resp_bits_cmd"] == 6 else "before_last", p["s3.metaRefillWriteBus_req_valid"], int(last))
            if last:
                c("REFILL-META-DIRTY", "write_allocate" if is_write else "read_allocate",
                  (p["s3.metaWriteArb_io_in_1_bits_data_tag"], p["s3.metaWriteArb_io_in_1_bits_data_dirty"]), (tag, int(is_write)))
            c("REFILL-FIRST-FLAG", "first" if first else "later", (p["s3.readingFirst"], q["s3.afterFirstRead"]), (int(first), int(after or rsp)))
            if first:
                c("EARLY-DEMAND-CAPTURE", "first", q["s3.inRdataRegDemand"], p["s3.io_mem_resp_bits_rdata"])
            elif rsp and p["s3.io_mem_resp_bits_rdata"] != p["s3.inRdataRegDemand"]:
                c("EARLY-DEMAND-CAPTURE", "later_different_data", q["s3.inRdataRegDemand"], p["s3.inRdataRegDemand"])
            if returned:
                c("EARLY-NO-DUPLICATE", "remaining_refill", p["s3.io_out_valid"], 0)
        elif state == 3:
            if write == 7:
                c("FSM-WB-END", "last_accepted" if mem else "last_stalled", q["s3.state"], 4 if mem else 3)
            assert q["s3.writeBeatCnt_value"] == (write + int(mem)) & 7, "writeback count advanced without command acceptance"
            if mem and write == 7:
                c("WRITEBACK-COUNT", "wrap", q["s3.writeBeatCnt_value"], 0)
            elif p["s3.io_mem_req_valid"] and not mem:
                c("WRITEBACK-COUNT", "first_stall" if write == 0 else "last_stall" if write == 7 else "middle_stall",
                  q["s3.writeBeatCnt_value"], write)
            if p["s3.io_mem_req_valid"]:
                c("WRITEBACK-LAST-CMD", "7_accepted" if write == 7 and mem else "7_stalled" if write == 7 else "0_to_6", p["s3.io_mem_req_bits_cmd"], 7 if write == 7 else 3)
                way = p["s3.io_in_bits_waymask"].bit_length() - 1
                victim = self.directory.get((index, way))
                if victim is None or not victim[1]:
                    raise AssertionError("writeback has no valid victim in observed directory")
                expected_address = (victim[0] << 13) | (index << 6)
                c("WRITEBACK-VICTIM-ADDRESS", f"way{way}", p["s3.io_mem_req_bits_addr"], expected_address)
                if victim[0] >> 10:
                    c("WRITEBACK-VICTIM-ADDRESS", "high_tag_bits", p["s3.io_mem_req_bits_addr"], expected_address)
        elif state == 4:
            c("FSM-WB-ACK", "ack_received" if rsp else "ack_delayed", q["s3.state"], 1 if rsp else 4)
        elif state == 5:
            c("FSM-MMIO-REQUEST", "accepted" if mmio_cmd else "stalled", q["s3.state"], 6 if mmio_cmd else 5)
        elif state == 6:
            c("FSM-MMIO-RESPONSE", "valid" if mmio_rsp else "gap", q["s3.state"], 7 if mmio_rsp else 6)
            if mmio_rsp:
                assert q["s3.inRdataRegDemand"] == p["s3.io_mmio_resp_bits_rdata"], "MMIO response not captured"
        elif state == 7:
            c("FSM-COMPLETE", "already_returned" if returned else "normal_accept" if cpu else "output_stalled", q["s3.state"], 0 if returned or cpu else 7)
            if returned:
                c("EARLY-NO-DUPLICATE", "finish", p["s3.io_out_valid"], 0)
        elif state == 8 and probe:
            end = coh and p["s3.releaseLast_c_value"] == 7
            case = "last_accepted" if end else "last_stalled" if p["s3.releaseLast_c_value"] == 7 else "middle"
            c("FSM-RELEASE-END", case, q["s3.state"], 0 if end else 8)
            expected_count = (read + int(coh)) & 7
            c("COHERENCE-COUNT-STEP", f"start{self.release_start}" if coh else "gap", q["s3.readBeatCnt_value"], expected_count)
            if coh and read == 7:
                c("COHERENCE-COUNT-STEP", "wrap", q["s3.readBeatCnt_value"], 0)
            if p["s3.releaseLast_c_value"] == 7 and p["s3.io_cohResp_valid"]:
                c("COHERENCE-LAST-QUALIFY", "last_fire" if coh else "last_blocked", p["s3.releaseLast"], int(coh))
            assert q["s3.releaseLast_c_value"] == (p["s3.releaseLast_c_value"] + int(coh)) & 7, "release count advanced without delivery"
            if p["s3.io_cohResp_valid"]:
                way = p["s3.io_in_bits_waymask"].bit_length() - 1
                expected = self.data.get(((index << 3) | read, way))
                if expected is None:
                    raise AssertionError("release uses uninitialized data in observed ledger")
                c("COHERENCE-READ-SOURCE", f"way{way}_" + ("dirty" if p["s3.meta_dirty"] else "clean"), p["s3.io_cohResp_bits_rdata"], expected)

        if state == 0:
            c("REFILL-FIRST-FLAG", "next_transaction", q["s3.afterFirstRead"], 0)
            c("EARLY-RETURNED-FLAG", "next_idle", q["s3.alreadyOutFire"], 0)
        elif valid:
            c("EARLY-RETURNED-FLAG", "accepted" if cpu else "stalled", q["s3.alreadyOutFire"], int(returned or cpu))
        if valid and (p["s3.miss"] or mmio or probe):
            case = "probe" if probe else "MMIO" if mmio else "write_miss" if is_write else "read_miss"
            expected = False if probe else state == 7 if is_write or mmio else bool(after and not returned)
            c("EARLY-EARLY-ELIGIBLE", case, p["s3.io_out_valid"], int(expected))
        self._read_substate(p, q, c, mem=mem, coh=coh)
        if valid:
            mask = p["s3.io_in_bits_req_wmask"]
            expected_mask = byte_mask(mask) if is_write else 0
            case = "read_with_mask" if not is_write and mask else "zero" if mask == 0 else "full" if mask == 255 else f"mask{mask:02x}" if mask.bit_count() == 1 else None
            if case:
                c("WRITEBACK-BYTE-ENABLE", case, p["s3.wordMask"], expected_mask)
            if hit and is_write:
                case = "already_dirty" if p["s3.meta_dirty"] else "clean_zero_mask" if not mask else "clean_partial"
                c("WRITEBACK-DIRTY-SET", case, p["s3.metaHitWriteBus_x5"], int(not p["s3.meta_dirty"]))
                way = p["s3.io_in_bits_waymask"].bit_length() - 1
                key = (p["s3.dataWriteArb_io_in_0_bits_setIdx"], way)
                old = self.prior_data.get(key, self.data.get(key))
                if old is None:
                    raise AssertionError("hit write has no initialized word in observed ledger")
                expected = merge(old, p["s3.io_in_bits_req_wdata"], expected_mask)
                assert p["s3.dataWriteArb_io_in_0_bits_data_data"] == expected, "hit write lost preserved bytes"
                if self.last_hit_write is not None:
                    previous = self.last_hit_write
                    if previous["tick"] + 2 == self._tick and previous["key"] == key:
                        dependency = "overlap_masks" if previous["mask"] & mask else "disjoint_masks"
                        c("FORWARD-MASKED-DEPENDENCY", dependency,
                          p["s3.dataWriteArb_io_in_0_bits_data_data"], expected)
                if cpu:
                    self.last_hit_write = {"tick": self._tick, "key": key, "mask": mask}
            burst = cmd in (3, 7)
            case = "stall" if burst and not cpu else "last" if cmd == 7 else "first" if burst and p["s3.writeL2BeatCnt_value"] == 0 else "middle" if burst else "ordinary_after_burst"
            c("BURST-WRITE-COUNT", case, q["s3.writeL2BeatCnt_value"], (p["s3.writeL2BeatCnt_value"] + int(cpu and burst)) & 7)
            if burst and hit and is_write:
                assert p["s3.dataWriteArb_io_in_0_bits_setIdx"] == ((index << 3) | p["s3.writeL2BeatCnt_value"]), "write burst used request word instead of beat"
            if p["s3.hitReadBurst"]:
                case = "stalled" if not cpu else "start7" if word == 7 else "start0" if word == 0 else None
                if case and state == 0:
                    c("BURST-READ-HIT", case, (q["s3.state"], q["s3.readBeatCnt_value"]), (8, (word + 1) & 7) if cpu else (0, read))
                if case and state == 8 and p["s3.state2"] == 2 and cpu:
                    way = p["s3.io_in_bits_waymask"].bit_length() - 1
                    expected = self.data.get(((index << 3) | read, way))
                    if expected is None:
                        raise AssertionError("CPU burst uses uninitialized word in observed ledger")
                    c("BURST-READ-HIT", case, p["s3.io_out_bits_rdata"], expected,
                      demand_word=word, current_word=read, observation="burst_data")
        c("ARBITRATION-WRITE-EXCLUSION", "negative_conflict" if p["s3.hitWrite"] and p["s3.dataRefillWriteBus_x9"] else "legal_handoff",
          bool(p["s3.hitWrite"] and p["s3.dataRefillWriteBus_x9"]), False)

    def _read_substate(self, p, q, c, *, mem, coh):
        state, sub = p["s3.state"], p["s3.state2"]
        if state not in (3, 8):
            return
        mode = "writeback" if state == 3 else "release"
        read_fire = p["s3.io_dataReadBus_req_valid"] and p["s3.io_dataReadBus_req_ready"]
        if sub == 0:
            c("FORWARD-READ-ISSUE", mode if read_fire else "arbitration_stall", q["s3.state2"], int(read_fire))
            count = p["s3.writeBeatCnt_value"] if state == 3 else p["s3.readBeatCnt_value"]
            assert p["s3.io_dataReadBus_req_bits_setIdx"] == (((p["s3.io_in_bits_req_addr"] >> 6) & 127) << 3) | count, "SRAM read word mismatch"
            if not read_fire:
                self.arbitration_wait = mode
                c("ARBITRATION-DATA-PRIORITY", "writeback_wait" if state == 3 else "release_wait", q["s3.state2"], 0)
            elif self.arbitration_wait:
                c("ARBITRATION-DATA-PRIORITY", "priority_released", q["s3.state2"], 1)
                self.arbitration_wait = None
        elif sub == 1:
            c("FORWARD-READ-CAPTURE", mode, (q["s3.state2"], tuple(q[f"s3.dataWay_{w}_data"] for w in range(4))),
              (2, tuple(p[f"s3.io_dataReadBus_resp_data_{w}_data"] for w in range(4))))
        else:
            cpu_burst = p["s3.hitReadBurst"] and p["s3.io_out_ready"]
            if mem or coh or cpu_burst:
                c("FORWARD-READ-NEXT", "memory" if mem else "coherence" if coh else "CPU_burst", q["s3.state2"], 0)
            else:
                c("FORWARD-READ-HOLD", "memory_stall" if state == 3 else "coherence_stall",
                  (q["s3.state2"], tuple(q[f"s3.dataWay_{w}_data"] for w in range(4))),
                  (2, tuple(p[f"s3.dataWay_{w}_data"] for w in range(4))))

    def _arrays(self, p, q, c):
        self.prior_data = {}
        sweep = p["metaArray.ram.resetState"]
        reset_set = p["metaArray.ram.resetSet"]
        if sweep:
            case = f"set{reset_set}"
            actual = tuple((p[f"metaArray.ram.array_{w}_MPORT_en"], p[f"metaArray.ram.array_{w}_MPORT_addr"],
                            p[f"metaArray.ram.array_{w}_MPORT_mask"], p[f"metaArray.ram.array_{w}_MPORT_data"]) for w in range(4))
            expected = ((1, reset_set, 1, 0),) * 4
            c("ARRAY-META-SWEEP", case, actual, expected)
            c("ARRAY-META-SWEEP", "all_ways", actual, expected)
            if not p["reset"]:
                assert q["metaArray.ram.resetSet"] == (reset_set + 1) & 127, "metadata sweep skipped set"
                assert q["metaArray.ram.resetState"] == int(reset_set != 127), "metadata sweep ended early"
            c("ARRAY-RESET-BLOCK", "during_sweep", p["s1.io_metaReadBus_req_ready"], 0)
        elif self.was_sweeping:
            c("ARRAY-RESET-BLOCK", "first_ready", p["s1.io_metaReadBus_req_ready"], int(not p["metaArray.ram.wen"]))
        self.was_sweeping = bool(sweep)
        if p["metaArray.ram.wen"]:
            c("ARRAY-WRITE-PRIORITY", "reset_write" if sweep else "normal_write",
              (p["metaArray.ram.io_r_req_ready"], q["metaArray.ram.array_0_rdata_MPORT_addr_pipe_0"]),
              (0, p["metaArray.ram.array_0_rdata_MPORT_addr_pipe_0"]))
        for w in range(4):
            if p[f"metaArray.ram.array_{w}_MPORT_en"] and p[f"metaArray.ram.array_{w}_MPORT_mask"]:
                index = p[f"metaArray.ram.array_{w}_MPORT_addr"]
                value = p[f"metaArray.ram.array_{w}_MPORT_data"]
                self.directory[index, w] = (value >> 2, (value >> 1) & 1, value & 1)
                if not sweep:
                    c("ARRAY-WAY-WRITE", f"way{w}", (index, value),
                      (p["s3.io_metaWriteBus_req_bits_setIdx"],
                       (p["s3.io_metaWriteBus_req_bits_data_tag"] << 2) | 2 | p["s3.io_metaWriteBus_req_bits_data_dirty"]))
        read_index = q["metaArray.ram.array_0_rdata_MPORT_addr_pipe_0"]
        if q["metaArray.ram.array_0_rdata_MPORT_en_pipe_0"]:
            for w in range(4):
                known = self.directory.get((read_index, w))
                if known is not None:
                    expected = (known[0] << 2) | (known[1] << 1) | known[2]
                    assert q[f"metaArray.ram.array_{w}_rdata_MPORT_data"] == expected, "metadata SRAM contents differ from observed writes"
        if p["s3.io_dataWriteBus_req_valid"]:
            addr = p["s3.io_dataWriteBus_req_bits_setIdx"]
            waymask = p["s3.io_dataWriteBus_req_bits_waymask"]
            for w in range(4):
                if waymask & (1 << w):
                    self.prior_data[addr, w] = self.data.get((addr, w))
                    self.data[addr, w] = p["s3.io_dataWriteBus_req_bits_data_data"]
        v0, v1 = p["dataArray.io_r_0_req_valid"], p["dataArray.io_r_1_req_valid"]
        if v0 or v1:
            case = "both" if v0 and v1 else "port0_only" if v0 else "port1_only"
            ready = int(not p["dataArray.io_w_req_valid"])
            c("ARRAY-DATA-PORT", case,
              (p["dataArray.io_r_0_req_ready"], p["dataArray.io_r_1_req_ready"]), (ready, int(ready and not v0)))
        for port in (0, 1):
            reg = "dataArray.REG" if port == 0 else "dataArray.REG_1"
            keys = [f"dataArray.r_1_{w}_data" if port else f"dataArray.r___05F{w}_data" for w in range(4)]
            if not p["reset"]:
                actual = tuple(q[key] for key in keys)
                expected = tuple(p[f"dataArray.ram_io_r_resp_data_{w}_data"] if p[reg] else p[key] for w, key in enumerate(keys))
                case = f"{self.previous_data_port}_then_{port}" if p[reg] and self.previous_data_port is not None and self.previous_data_port != port else None
                if case:
                    c("ARRAY-READ-RESPONSE", case, actual, expected)
                if not p[reg] and not v0 and not v1:
                    c("ARRAY-READ-RESPONSE", "idle_hold", actual, expected)
                assert actual == expected, "SRAM response delivered to wrong port"
            if p[reg]:
                self.previous_data_port = port


class CacheStage2Observer(CacheInternalObserver):
    """Reuse the lookup/forwarding checker against independently driven Stage2."""
    def __init__(self, dut):
        signals = {key: (path.removeprefix("s2."), width) for key, (path, width) in SIGNALS.items()
                   if key.startswith("s2.")}
        signals["reset"] = ("reset", 1)
        ClockObserver.__init__(self, dut, prefix="CacheStage2_top.CacheStage2.", signals=signals)
        rules = {key: rule for key, rule in RULES.items()
                 if key.startswith("CACHE-INT-LOOKUP-") or key.startswith("CACHE-INT-FORWARD-META-")
                 or key in {"CACHE-INT-FORWARD-DATA-WORD", "CACHE-INT-FORWARD-DATA-HOLD", "CACHE-INT-FORWARD-DATA-NEWEST"}}
        self.checks = ScenarioChecks(rules, run_metadata={
            "test": os.environ.get("PYTEST_CURRENT_TEST", "cache-stage2"), "module": "CacheStage2",
        }, contract="cache.rtl-properties/v1")
        self.checks.implemented = set(rules)
        self.after_reset = False  # This isolated module contains no data SRAM.
        self.forward_meta_stall = 0

    def observe(self, p, q, tick):
        def check(name, scenario, actual, expected, **detail):
            self.checks.check("CACHE-INT-" + name, scenario, actual=actual, expected=expected,
                              tick=tick, context={"address": p["s2.io_in_bits_req_addr"], **detail})
        self._lookup(p, q, check)
        self._forwarding(p, q, check)


class CacheStage3Observer(CacheInternalObserver):
    """Stage3 checks with an explicit input-side SRAM oracle for the module."""
    def __init__(self, dut):
        signals = {key: (path.removeprefix("s3."), width) for key, (path, width) in SIGNALS.items()
                   if key.startswith("s3.")}
        ClockObserver.__init__(self, dut, prefix="CacheStage3_top.CacheStage3.", signals=signals)
        families = ("FSM-", "REFILL-", "EARLY-", "WRITEBACK-", "COHERENCE-", "FORWARD-READ-", "BURST-")
        excluded = {"CACHE-INT-FSM-IDLE-CLEAN", "CACHE-INT-EARLY-FINAL-WHILE-STALLED"}
        rules = {key: rule for key, rule in RULES.items() if key not in excluded and (
            key.removeprefix("CACHE-INT-").startswith(families) or key in {
                "CACHE-INT-FORWARD-WAY-QUALIFY", "CACHE-INT-FORWARD-MASKED-DEPENDENCY",
                "CACHE-INT-ARBITRATION-WRITE-EXCLUSION"})}
        self.checks = ScenarioChecks(rules, run_metadata={
            "test": os.environ.get("PYTEST_CURRENT_TEST", "cache-stage3"), "module": "CacheStage3",
        }, contract="cache.rtl-properties/v1")
        self.checks.implemented = set(rules)
        self.directory, self.data, self.prior_data = {}, {}, {}
        self.probe_history = []
        self.last_hit_write = None
        self.release_start = self.refill_beats = 0
        self.arbitration_wait = None

    def observe(self, p, q, tick):
        self._tick = tick
        def check(name, scenario, actual, expected, **detail):
            identifier = "CACHE-INT-" + name
            if identifier in self.checks.groups:
                self.checks.check(identifier, scenario, actual=actual, expected=expected,
                                  tick=tick, context={"state": p["s3.state"],
                                                     "address": p["s3.io_in_bits_req_addr"], **detail})
        if p["s3.reset"]:
            self.last_hit_write = None
            self.probe_history.clear()
            self.refill_beats = 0
            keys = ("state", "state2", "readBeatCnt_value", "writeBeatCnt_value", "writeL2BeatCnt_value",
                    "releaseLast_c_value", "respToL1Last_c_value", "afterFirstRead", "alreadyOutFire")
            assert tuple(q["s3." + key] for key in keys) == (0,) * len(keys), "Stage3 reset failed"
            return
        self._forwarding_s3(p, q, check)
        self._stage3(p, q, check)
        # Writes become part of the oracle only after comparisons. The source
        # words and victim directory are supplied independently by the case.
        if p["s3.io_dataWriteBus_req_valid"]:
            index, mask = p["s3.io_dataWriteBus_req_bits_setIdx"], p["s3.io_dataWriteBus_req_bits_waymask"]
            for way in range(4):
                if mask & (1 << way):
                    self.data[index, way] = p["s3.io_dataWriteBus_req_bits_data_data"]
