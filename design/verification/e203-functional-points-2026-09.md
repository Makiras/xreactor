# E203 功能点和验证契约

分析基线为 2026-09-30 本地 RTL，实施及证据核对更新于 2026-10-01。范围：`e203_ifu_ift2icb with ITCM64/BIU32/PC32 and response buffer DP=1`。
共 89 项要求：内部 49、外部 21、验证器自身 19。要求条数和 pytest PASS 不作为功能覆盖率分母。

内部 49 项均有真实 RTL 观察，共 133 个必需场景 bins；合并激活覆盖为 100%，49 项满足本基线的关闭条件。
逐项计数、来源和比较结果见实测检查（本地产物：`rtl-property-evidence-2026-10-01/e203-checks.json`），原始 schema/bin/origin 见合并覆盖数据库（本地产物：`rtl-property-evidence-2026-10-01/e203-internal-coverage.json`）。

关闭条件为实际激活、全部必需 bins 命中、属性比较通过且无观察器错误。该结论只针对已声明义务，不证明规格已经穷尽；模块级路径证据不自动证明完整系统集成。

## RTL 基线和观察能力

- `example/e203_ifu_ift2icb/e203_ifu_ift2icb.v`，SHA-256 `190cf49c17b8b7873b61eb5d0b833bd853d4d67a09cdfa9fb79abc17afb625e5`。
- `example/e203_ifu_ift2icb/sirv_gnrl_bufs.v`，SHA-256 `d46f8701f99a79b321cecd2e2b776caa2d7a76925e07b675bbd3952a47fb3ab2`。

当前导出 294 个排除 __V 覆盖计数后的 direct 信号，另枚举 271 个 VPI 信号；见观察清单（本地产物：`rtl-internal-observation-inventory-2026-09-30.json`）。观察器按显式路径和宽度绑定，缺失即失败。

普通时序属性在驱动稳定后读取边沿前条件，紧邻上升沿后比较提交结果。独立接受/响应账本、字节模型及已知 metadata/data 写账本作为 oracle；未初始化 SRAM 数据不假定为零。属性先记录真实激活再比较，失败仍保留实际证据。

## 需要特别区分的时序

零 uop 的旧响应完成时可以同时接受下一请求并发出下一请求的命令；不能将全局 cmd_valid=0 当成旧零 uop 的必要条件。响应端口隔离检查只在未选端口实际 valid 时触发；RTL 向两端广播 ready，因此不要求未选端口 ready=0。

连续输入检查逐笔命令归属和响应队列；三种在途复位分别保存中断前状态、复位后状态和恢复结果。leftover/offset 及 FIFO 数据不复位，只有有效使用时需要正确装载历史。

## 功能点明细

### 路由

**E203-ROUTE-ITCM ITCM 普通取指**

ITCM lane 起始和中部的非跨 lane 请求；命令目标为 ITCM、地址截取及 32 位指令与独立模型一致。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / ROUTE-ITCM；E203Harness.fetch 的 Scoreboard 比较。

**E203-ROUTE-BIU BIU 普通取指**

BIU lane 起始请求；命令目标为 BIU、32 位地址及指令与独立模型一致。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / ROUTE-BIU；E203Harness.fetch 的 Scoreboard 比较。

### 数据路径

**E203-SPLIT-ITCM ITCM 跨 lane 拼接**

PC 位于 8-byte lane 的末半字且没有 holding 复用；必须发两条命令，little-endian 拼接的四字节指令正确。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / SPLIT-ITCM；E203Harness.fetch 的 Scoreboard 比较。

**E203-SPLIT-BIU BIU 跨 lane 拼接**

PC 位于 4-byte lane 的末半字；必须发两条命令，little-endian 拼接的四字节指令正确。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / SPLIT-BIU；E203Harness.fetch 的 Scoreboard 比较。

### 路由

**E203-REGION-SWITCH 双向跨 ITCM 区域边界**

分别从 0x8000fffe 和 0x7ffffffe 取指；两条命令跨 ITCM/BIU，逐条比较目标、地址和最终指令。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / REGION-SWITCH；E203Harness.fetch 的 Scoreboard 比较。

**E203-ADDRESS-WRAP 32 位地址回绕**

PC=0xfffffffe；第二命令地址回绕到 0，完整指令仍按 32 位地址空间逐字节比较。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / ADDRESS-WRAP；E203Harness.fetch 的 Scoreboard 比较。

### 状态

**E203-HOLD-REUSE holding 零/单命令复用**

ITCM 顺序取指且 holding 可用；同 lane 发零条命令，跨 lane 只取缺失部分，完整指令正确。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / HOLD-REUSE；E203Harness.fetch 的 Scoreboard 比较。

**E203-SEQUENTIAL-2 顺序增加 2 字节**

sequential=true、seq_rv32=false 且 last_pc+2=pc；覆盖同 lane 和跨 lane，命令地址及指令正确。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / SEQUENTIAL-2；E203Harness.fetch 的 Scoreboard 比较。

**E203-SEQUENTIAL-4 顺序增加 4 字节**

0x80000502→0x80000506 顺序 +4；holding 跨 lane 时后续地址和拼接正确，下一请求仍可复用。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / SEQUENTIAL-4；E203Harness.fetch 的 Scoreboard 比较。

**E203-NOHOLD-TRANSITION nohold 切换、错误恢复和跳转**

连续六笔从复用切到强制取数、拆分错误、恢复复用及跳转；命令数须为 [1,0,1,2,0,1]，仅第四笔报错。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / NOHOLD-TRANSITION；E203Harness.fetch 的 Scoreboard 比较。

### 错误处理

**E203-ERROR-OR 拆分响应错误 OR 真值表**

ITCM 和 BIU 均执行无错误/首错/次错/双错四种拆分响应；最终错误等于两次实际响应错误的 OR。要求八种组合均出现。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / ERROR-OR；E203Harness.fetch 的 Scoreboard 比较。

### 时序

**E203-COMMAND-STALL 首命令受阻后完成**

首 ICB 命令 ready 延迟；valid 和请求字段在受阻期间保持，接受后只有模型预期的命令，最终结果正确。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / COMMAND-STALL；E203Harness.fetch 的 Scoreboard 比较。

**E203-SECOND-COMMAND-STALL 第二命令受阻后完成**

拆分取指首响应返回后单独阻塞第二命令；保持请求字段，离开 WAIT2ND 并正确完成。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / SECOND-COMMAND-STALL；E203Harness.fetch 的 Scoreboard 比较。

**E203-OUTPUT-STALL IFU 响应受阻后完成**

IFU response ready 延迟；输出 valid 持续有效、instruction/error 不变，最终接受一次正确响应。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / OUTPUT-STALL；E203Harness.fetch 的 Scoreboard 比较。

**E203-SPLIT-DELAY 两次响应延迟不对称**

ITCM/BIU 拆分取指均覆盖首响应较慢和次响应较慢，延迟 (9,0)/(0,9)；命令和输出背压共存，结果正确。

验证层：`design_external`。

检查入口：test_e203_reference_stress_and_coverage / SPLIT-DELAY；E203Harness.fetch 的 Scoreboard 比较。

### 产物

**E203-REPORTS 事务、功能覆盖与 RTL 报告**

主 campaign 全部事务经 Scoreboard 检查；15 个 point/4 个 cross 达标，LCOV 非空，HTML 及 genhtml 目标 RTL 源码页生成。功能 bin 命中不代替逐笔比较。

验证层：`testbench`。

检查入口：test_e203_reference_stress_and_coverage / 报告文件断言；E203Harness.fetch 的 Scoreboard 比较。

### 生命周期

**E203-TIMEOUT-RESET 漏响应超时后显式 reset 恢复**

将 ICB 响应延迟到预算外；5 周期内抛 TimeoutError，显式 reset 后下一笔正常完成，不把丢失请求记成成功。

验证层：`testbench`。

检查入口：test_e203_missing_response_times_out。

### 数据模式

**E203-DATA-ZERO 全零 数据拼接**

以 zero byte 模式执行全部 34 笔定向输入；0/1/2 命令路径均出现，所有指令、命令和错误比较通过。此点只代表该模式。

验证层：`design_external`。

检查入口：test_e203_data_patterns[zero]。

**E203-DATA-ONES 全一 数据拼接**

以 ones byte 模式执行全部 34 笔定向输入；0/1/2 命令路径均出现，所有指令、命令和错误比较通过。此点只代表该模式。

验证层：`design_external`。

检查入口：test_e203_data_patterns[ones]。

**E203-DATA-ALTERNATING 交替位 数据拼接**

以 alternating byte 模式执行全部 34 笔定向输入；0/1/2 命令路径均出现，所有指令、命令和错误比较通过。此点只代表该模式。

验证层：`design_external`。

检查入口：test_e203_data_patterns[alternating]。

**E203-DATA-WALKING walking bit 数据拼接**

以 walking byte 模式执行全部 34 笔定向输入；0/1/2 命令路径均出现，所有指令、命令和错误比较通过。此点只代表该模式。

验证层：`design_external`。

检查入口：test_e203_data_patterns[walking]。

### 周期预算

**E203-DEADLINE-ITCM ITCM 普通 截止周期**

PC=0x80000100，施加命令和输出背压；测量实际延迟后 reset，预算恰好等于延迟时成功，少一周期时已接受请求超时，再 reset 后可恢复。

验证层：`testbench`。

检查入口：test_e203_exact_response_budget[itcm]。

**E203-DEADLINE-ITCM-SPLIT ITCM 跨 lane 截止周期**

PC=0x80000106，施加命令和输出背压；测量实际延迟后 reset，预算恰好等于延迟时成功，少一周期时已接受请求超时，再 reset 后可恢复。

验证层：`testbench`。

检查入口：test_e203_exact_response_budget[itcm-split]。

**E203-DEADLINE-BIU BIU 普通 截止周期**

PC=0x100，施加命令和输出背压；测量实际延迟后 reset，预算恰好等于延迟时成功，少一周期时已接受请求超时，再 reset 后可恢复。

验证层：`testbench`。

检查入口：test_e203_exact_response_budget[biu]。

**E203-DEADLINE-BIU-SPLIT BIU 跨 lane 截止周期**

PC=0x102，施加命令和输出背压；测量实际延迟后 reset，预算恰好等于延迟时成功，少一周期时已接受请求超时，再 reset 后可恢复。

验证层：`testbench`。

检查入口：test_e203_exact_response_budget[biu-split]。

### 检查器

**E203-CHECK-INSTRUCTION 拒绝错误指令**

翻转观察指令一位，必须抛含 instruction 差异的 ScoreboardMismatch。 注入仅修改项目观察边界，不改 RTL；预期异常、失败状态和产物均核对。

验证层：`testbench`。

检查入口：test_e203_checker_rejects_faults[instruction]。

**E203-CHECK-ERROR 拒绝错误状态位**

翻转观察错误位，必须抛含 error 差异的 ScoreboardMismatch。 注入仅修改项目观察边界，不改 RTL；预期异常、失败状态和产物均核对。

验证层：`testbench`。

检查入口：test_e203_checker_rejects_faults[error]。

**E203-CHECK-COMMAND-ADDRESS 拒绝错误命令地址**

改写记录中的命令地址，必须抛含 commands 差异的 ScoreboardMismatch。 注入仅修改项目观察边界，不改 RTL；预期异常、失败状态和产物均核对。

验证层：`testbench`。

检查入口：test_e203_checker_rejects_faults[command_address]。

**E203-CHECK-MISSING-COMMAND 拒绝命令遗漏**

从观察轨迹删除命令，必须抛含 commands 差异的 ScoreboardMismatch。 注入仅修改项目观察边界，不改 RTL；预期异常、失败状态和产物均核对。

验证层：`testbench`。

检查入口：test_e203_checker_rejects_faults[missing_command]。

**E203-CHECK-MISSING-RESPONSE 拒绝漏响应**

屏蔽 IFU 响应快照，有限周期预算必须超时；失败产物保留已接受请求。 注入仅修改项目观察边界，不改 RTL；预期异常、失败状态和产物均核对。

验证层：`testbench`。

检查入口：test_e203_checker_rejects_faults[missing_response]。

**E203-CHECK-EXTRA-RESPONSE 拒绝额外 IFU 响应**

在最后事务后的三周期观察窗注入 IFU 响应，必须报告 extra IFU response。窗口之外不作保证。 注入仅修改项目观察边界，不改 RTL；预期异常、失败状态和产物均核对。

验证层：`testbench`。

检查入口：test_e203_checker_rejects_faults[extra_response]。

**E203-CHECK-EXTRA-COMMAND 拒绝额外 ICB 命令**

在最后事务后的三周期观察窗注入命令，必须报告 extra ICB command。窗口之外不作保证。 注入仅修改项目观察边界，不改 RTL；预期异常、失败状态和产物均核对。

验证层：`testbench`。

检查入口：test_e203_checker_rejects_faults[extra_command]。

**E203-CHECK-UNSTABLE 拒绝受阻响应改值**

输出已 valid 且 ready 为低后翻转指令，必须报告 changed under backpressure。 注入仅修改项目观察边界，不改 RTL；预期异常、失败状态和产物均核对。

验证层：`testbench`。

检查入口：test_e203_checker_rejects_faults[unstable]。

**E203-CHECK-WITHDRAWN 拒绝受阻响应撤回 valid**

输出受阻时撤回 valid 一拍，随后允许恢复；必须在撤回当拍报告 withdrawn under backpressure。 注入仅修改项目观察边界，不改 RTL；预期异常、失败状态和产物均核对。

验证层：`testbench`。

检查入口：test_e203_checker_rejects_faults[withdrawn]。

**E203-CHECK-EARLY 拒绝接受前响应**

输入尚未接受时注入响应，必须报告 before request acceptance。 注入仅修改项目观察边界，不改 RTL；预期异常、失败状态和产物均核对。

验证层：`testbench`。

检查入口：test_e203_checker_rejects_faults[early]。

### 生命周期

**E203-CANCEL-BEFORE-ACCEPT 输入接受前取消清理**

输入未握手时外部取消 campaign；CancelledError 传播，失败产物保留，任务/watcher/Execution ownership 释放，驱动 valid 撤销，宿主任务不受影响。

验证层：`testbench`。

检查入口：test_e203_external_cancellation[before_accept]。

**E203-CANCEL-WAITING-RESPONSE 等待 ICB 响应取消清理**

ICB 命令已接受、响应未到时外部取消 campaign；CancelledError 传播，失败产物保留，任务/watcher/Execution ownership 释放，驱动 valid 撤销，宿主任务不受影响。

验证层：`testbench`。

检查入口：test_e203_external_cancellation[waiting_response]。

**E203-CANCEL-OUTPUT-HELD IFU 输出受阻取消清理**

IFU 输出有效但消费者未接受时外部取消 campaign；CancelledError 传播，失败产物保留，任务/watcher/Execution ownership 释放，驱动 valid 撤销，宿主任务不受影响。

验证层：`testbench`。

检查入口：test_e203_external_cancellation[output_held]。

### 流水与连续取指

**E203-OVERLAPPED-INPUT 重叠接受 IFU 请求**

stream_fetches 连续呈现下一请求，在合法完成/交接边沿接受；独立队列逐笔比较 PC、目标、命令地址、指令和错误，覆盖 0→1、1→2、2→0/1/2 及 ITCM/BIU 切换。

验证层：`design_external`。

检查入口：test_e203_internal_scenarios / stream_fetches / stream-transactions.json。

### 复位

**E203-RESET-INFLIGHT 事务中途 reset**

分别在等待首响应、WAIT2ND 第二命令受阻、响应已入缓冲且 CPU 未接受时 reset；观察控制清零、丢弃外部旧响应队列，恢复后 split fetch 与独立字节模型一致。

验证层：`design_external`。

检查入口：test_e203_reset_discards_inflight_context[first_response/second_command/buffered_output] / reset-witness.json。

### 设计内部 / lane 分类与请求分解

**E203-INT-LANE-CLASSIFY 目标宽度决定 lane 分类**

触发：ITCM64 遍历 PC[2:1]，BIU32 遍历 PC[1]。检查：起始、中间、跨界分类分别满足 8-byte/4-byte lane 定义；不能用统一 lane 宽度。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:298`；module `e203_ifu_ift2icb`；符号 `ifu_req_lane_cross`。
实际观察：PC、ifu_req_pc2itcm、ifu_req_lane_begin/cross。
必需场景：`ITCM:00`；`ITCM:01`；`ITCM:10`；`ITCM:11`；`BIU:0`；`BIU:1`。

实测：82 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LANE-SAME-NONSEQ 非顺序请求禁止复用**

触发：ifu_req_seq=0，独立变化 lane_begin 和上次 cross 标志。检查：lane_same 恒为 0，即使新旧 PC 数值相近也不能复用。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:366`；module `e203_ifu_ift2icb`；符号 `ifu_req_lane_same`。
实际观察：ifu_req_lane_same、req_lane_cross_r。
必需场景：`begin`；`middle`；`cross`。

实测：61 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LANE-SAME-BEGIN lane 起始依赖上次跨界**

触发：顺序取指且 lane_begin=1，上次请求 cross 为 0/1。检查：仅上次已跨 lane 预取时 lane_same=1。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:366`；module `e203_ifu_ift2icb`；符号 `ifu_req_lane_same`。
实际观察：接受历史、req_lane_cross_r、ifu_req_lane_same。
必需场景：`previous_cross=0`；`previous_cross=1`。

实测：5 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LANE-SAME-MIDDLE 非 lane 起始的顺序复用资格**

触发：顺序取指且 lane_begin=0。检查：lane_same=1；仍须另行满足 holdup 才能省略访问。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:366`；module `e203_ifu_ift2icb`；符号 `ifu_req_lane_same`。
实际观察：ifu_req_lane_begin、ifu_req_lane_same。
必需场景：`middle`；`cross`。

实测：16 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LANE-HOLD-GATE holding 资格的三个独立条件**

触发：逐一撤掉 ITCM 目标、ifu2itcm_holdup、允许 hold 三个条件。检查：仅 ITCM 且 holdup 且 nohold=0 时允许 lane_holdup；BIU 不得复用。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:369`；module `e203_ifu_ift2icb`；符号 `ifu_req_lane_holdup`。
实际观察：ifu_req_pc2itcm、ifu_req_lane_holdup。
必需场景：`enabled`；`nohold`；`holdup_low`；`BIU`。

实测：82 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LANE-UOP-ZERO 零 uop 的判定及互斥**

触发：same=1、cross=0、holdup=1，再逐一撤掉条件。检查：只在完整条件成立时 need_0uop=1；need_2uop 必为 0。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:483`；module `e203_ifu_ift2icb`；符号 `req_need_0uop`。
实际观察：req_need_0uop/2uop、命令接受数。
必需场景：`eligible`；`not_same`；`cross`；`not_held`。

实测：82 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LANE-UOP-TWO 两 uop 的两个来源**

触发：跨 lane：same&&!hold，或 !same；另测非跨界。检查：两类跨界各需两次访问，非跨界不置 need_2uop。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:481`；module `e203_ifu_ift2icb`；符号 `req_need_2uop`。
实际观察：req_need_2uop、请求分类。
必需场景：`same_unheld`；`different_lane`；`not_cross`。

实测：77 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LANE-UOP-HELD-CROSS 持有数据的跨界单 uop**

触发：same、cross、hold 全为 1。检查：same_cross_holdup=1，need_0uop=need_2uop=0，只访问后一 lane。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:480`；module `e203_ifu_ift2icb`；符号 `req_same_cross_holdup`。
实际观察：三个请求标志及实际命令。
必需场景：`held_cross`。

实测：5 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / ICB 状态机

**E203-INT-FSM-IDLE-FIRST IDLE 接受请求进入 1ST**

触发：IDLE 中请求分别需要零/一/两 uop，输入实际接受。检查：下一拍为 1ST；即使零 uop 也不能停在 IDLE。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:422`；module `e203_ifu_ift2icb`；符号 `state_idle_exit_ena`。
实际观察：icb_state_r、ifu_req_hsked、请求模式。
必需场景：`0uop`；`1uop`；`2uop`。

实测：56 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-FSM-FIRST-WAIT 首响应完成但第二命令阻塞**

触发：1ST、need_2uop=1、首 ICB 响应接受、命令未 ready。检查：下一拍 WAIT2ND；此时不产生完整 IFU 响应。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:434`；module `e203_ifu_ift2icb`；符号 `ICB_STATE_WAIT2ND`。
实际观察：icb_state_r、首响应接受、i_ifu_rsp_valid。
必需场景：`ITCM`；`BIU`。

实测：15 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-FSM-FIRST-SECOND 首响应与第二命令同拍衔接**

触发：1ST、need_2uop=1、首响应接受且命令 ready。检查：下一拍直接 2ND；第二命令本拍恰好接受一次，无 WAIT2ND 空拍。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:437`；module `e203_ifu_ift2icb`；符号 `ICB_STATE_2ND`。
实际观察：状态前后值、命令和响应接受 tick。
必需场景：`same_target`；`region_switch`。

实测：14 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-FSM-WAIT-HOLD WAIT2ND 保持**

触发：第二命令持续未 ready 至少两拍。检查：状态保持 WAIT2ND，命令地址及 leftover/error 不变。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:448`；module `e203_ifu_ift2icb`；符号 `state_wait2nd_exit_ena`。
实际观察：icb_state_r、ifu_icb_cmd_addr、leftover_r/err_r。
必需场景：`two_cycle_stall`；`long_stall`。

实测：14 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-FSM-WAIT-SECOND WAIT2ND 接受第二命令**

触发：WAIT2ND 中第二命令 ready。检查：该命令接受后进入 2ND；不得重新发首命令。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:448`；module `e203_ifu_ift2icb`；符号 `state_wait2nd_exit_ena`。
实际观察：状态转移、命令序号与地址。
必需场景：`ITCM`；`BIU`。

实测：14 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-FSM-FIRST-IDLE 单次响应完成返回 IDLE**

触发：1ST 中零/一 uop 的内部 IFU 响应接受，无新请求。检查：下一拍 IDLE；比较的是 i_ifu_rsp_hsked，不能误用外部缓冲响应接受。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:442`；module `e203_ifu_ift2icb`；符号 `ifu_req_hsked`。
实际观察：icb_state_r、i_ifu_rsp_hsked、外部响应事件。
必需场景：`0uop`；`1uop`。

实测：28 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-FSM-FIRST-FIRST 1ST 同拍完成并接受下一请求**

触发：1ST 中零/一 uop 完成且新请求同拍接受。检查：保持 1ST，但上下文切换为新请求；旧响应无丢失或串号。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:442`；module `e203_ifu_ift2icb`；符号 `ifu_req_hsked`。
实际观察：状态、旧/新请求标志、两笔响应。
必需场景：`0_to_1`；`1_to_2`；`target_change`。

实测：6 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-FSM-SECOND-IDLE 第二响应完成返回 IDLE**

触发：2ND 中内部 IFU 响应接受，无新请求。检查：下一拍 IDLE，leftover 不再影响下一非拆分指令。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:453`；module `e203_ifu_ift2icb`；符号 `state_2nd_exit_ena`。
实际观察：状态及后续结果。
必需场景：`ok`；`error`。

实测：25 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-FSM-SECOND-FIRST 2ND 同拍完成并接受下一请求**

触发：第二响应完成且新请求同拍接受。检查：下一拍 1ST；旧 leftover 用于旧响应，新请求上下文同时正确锁存。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:457`；module `e203_ifu_ift2icb`；符号 `ifu_req_hsked`。
实际观察：状态、输入/输出同拍、请求标志。
必需场景：`new_0uop`；`new_1uop`；`new_2uop`。

实测：3 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-FSM-NO-EXIT 无退出事件时状态保持**

触发：IDLE 无请求，1ST/2ND 无所需响应，WAIT2ND 命令阻塞。检查：分别保持原状态，不能因仅 valid 或其他端口事件前进。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:463`；module `e203_ifu_ift2icb`；符号 `icb_state_ena`。
实际观察：四态前后值、各状态退出使能。
必需场景：`IDLE`；`1ST`；`WAIT2ND`；`2ND`。

实测：164 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-FSM-EXIT-ONEHOT 状态退出选择互斥**

触发：运行四种合法状态，含同拍旧响应/新请求。检查：四个 exit_ena 至多一个为真，state_nxt 只来自当前状态分支。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:463`；module `e203_ifu_ift2icb`；符号 `icb_state_ena`。
实际观察：state_*_exit_ena、icb_state_nxt。
必需场景：`IDLE`；`1ST`；`WAIT2ND`；`2ND`；`handoff`。

实测：336 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / 请求与命令上下文

**E203-INT-CTX-REQ-LOAD 请求标志只在接受时装载**

触发：在未接受请求期间改变候选 PC/seq/hold，然后接受。检查：四个 *_r 标志只在 ifu_req_hsked 更新为被接受请求，不能提前污染旧事务。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:485`；module `e203_ifu_ift2icb`；符号 `req_same_cross_holdup_dfflr`。
实际观察：req_same_cross_holdup_r、req_need_0uop_r/2uop_r、req_lane_cross_r。
必需场景：`stalled_input`；`accepted_input`；`handoff`。

实测：92 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-CTX-ROUTE-LATCH 响应路由跟随已接受的命令**

触发：ITCM/BIU 命令切换及未接受候选地址变化。检查：icb_cmd2itcm_r/biu_r 只在命令接受更新；响应由该记录选择。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:496`；module `e203_ifu_ift2icb`；符号 `icb2itcm_dfflr`。
实际观察：路由寄存器与命令事件。
必需场景：`ITCM_to_BIU`；`BIU_to_ITCM`；`no_accept`。

实测：260 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-CTX-OFFSET-ZERO 零命令取指也刷新偏移**

触发：holding 零 uop 请求接受，没有 ICB 命令接受。检查：icb_cmd_addr_2_1_r 仍更新，正确选择新 PC 的半字位置。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:503`；module `e203_ifu_ift2icb`；符号 `icb_cmd_addr_2_1_ena`。
实际观察：偏移寄存器、ifu_req_hsked、指令结果。
必需场景：`offset_0`；`offset_2`；`offset_4`。

实测：10 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-CTX-OFFSET-HOLD 无接受时偏移保持**

触发：请求和命令均未接受，外部候选 PC 变化。检查：偏移寄存器保持；不能被下一候选地址改变当前响应对齐。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:503`；module `e203_ifu_ift2icb`；符号 `icb_cmd_addr_2_1_ena`。
实际观察：icb_cmd_addr_2_1_r。
必需场景：`waiting_response`；`stalled_command`。

实测：179 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-CTX-LAST-PC-PHASE last_pc 的前后阶段含义**

触发：顺序跨 lane，握手前为 previous PC，握手后更新为 current PC。检查：held-cross 首命令用 previous PC；后续第二命令用 current PC，两个阶段的地址均正确。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:765`；module `e203_ifu_ift2icb`；符号 `icb_algn_nxt_lane_addr`。
实际观察：ifu_req_last_pc、命令采样 tick、地址选择。
必需场景：`+2`；`+4`；`two_uop`。

实测：85 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / leftover 数据及错误位

**E203-INT-LEFTOVER-HELD-LOAD holding 上半字装载**

触发：held-cross 请求实际接受。检查：leftover 捕获被保持 lane 的最高 16 位；不能使用下一 lane 数据。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:520`；module `e203_ifu_ift2icb`；符号 `holdup2leftover_ena`。
实际观察：leftover_ena/r、ITCM 当前 lane、接受前后快照。
必需场景：`accepted`；`blocked`。

实测：5 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LEFTOVER-FIRST-LOAD 首响应上半字装载**

触发：两 uop 首 ICB 响应实际接受。检查：分别捕获 ITCM[63:48] 或 BIU[31:16]，不提前给出完整指令。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:532`；module `e203_ifu_ift2icb`；符号 `uop1st2leftover_ena`。
实际观察：leftover_r、路由寄存器、ICB 数据。
必需场景：`ITCM`；`BIU`。

实测：29 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LEFTOVER-DATA-HOLD leftover 非写入周期保持**

触发：两个装载事件均未发生，改变非当前响应数据。检查：leftover_r 不变；WAIT2ND 与等待第二响应期间均保持。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:552`；module `e203_ifu_ift2icb`；符号 `leftover_ena`。
实际观察：leftover_ena、leftover_r 前后值。
必需场景：`WAIT2ND`；`2ND_no_response`。

实测：66 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LEFTOVER-ERROR-CAPTURE 首响应错误随数据保存**

触发：首响应错误 0/1，另一路错误独立变化。检查：只保存被选中首响应的错误位，与同笔 leftover 数据对应。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:543`；module `e203_ifu_ift2icb`；符号 `uop1st2leftover_err`。
实际观察：leftover_err_r、两路 err、接受事件。
必需场景：`ITCM_ok`；`ITCM_error`；`BIU_ok`；`BIU_error`。

实测：29 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LEFTOVER-ERROR-CLEAR-HELD holding 装载清除历史错误**

触发：先产生有错 leftover，再合法接受 held-cross 请求。检查：holding 装载将 leftover_err_r 清零，不能继承上一事务错误。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:561`；module `e203_ifu_ift2icb`；符号 `leftover_err_nxt`。
实际观察：leftover_err_r 的装载前后值及最终响应。
必需场景：`error_to_held_ok`。

实测：1 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-LEFTOVER-ERROR-HOLD 错误位非装载周期保持**

触发：等待第二命令或第二响应，其他 err 信号变化。检查：leftover_err_r 直到装载或 reset 前保持。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:567`；module `e203_ifu_ift2icb`；符号 `leftover_err_dfflr`。
实际观察：leftover_err_r、leftover_ena、rst_n。
必需场景：`stored_0`；`stored_1`。

实测：294 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / 响应数据选择

**E203-INT-DATAPATH-ALIGN-ITCM ITCM 三个非跨界截取位置**

触发：lane 各半字填不同值，偏移 0/2/4 分别响应。检查：输出分别为 rdata[31:0]/[47:16]/[63:32]；必须以实际锁存偏移选择。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:598`；module `e203_ifu_ift2icb`；符号 `ifu2itcm_icb_rsp_instr`。
实际观察：icb_cmd_addr_2_1_r、对齐 mux、独立 byte 模型。
必需场景：`offset_0`；`offset_2`；`offset_4`。

实测：37 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-DATAPATH-LEFTOVER-SELECT 两种 leftover 拼接选择**

触发：1ST held-cross 或 2ND；另测普通 1ST。检查：前两类选择 {当前数据低16位,leftover}，普通取指走对齐数据，不得混入旧 leftover。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:579`；module `e203_ifu_ift2icb`；符号 `rsp_instr_sel_leftover`。
实际观察：rsp_instr_sel_leftover、i_ifu_rsp_instr。
必需场景：`held_cross_1ST`；`split_2ND`；`ordinary_1ST`。

实测：74 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-DATAPATH-UNSELECTED-RESPONSE 未选中响应端口隔离**

触发：等待当前端口响应时，让另一端口 data/err/valid 变化。检查：当前指令、错误及响应事件不受未选中端口影响；响应有效性按已接受命令路由。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:633`；module `e203_ifu_ift2icb`；符号 `ifu_icb_rsp_instr`。
实际观察：icb_cmd2*_r、ifu_icb_rsp_valid/err/instr。
必需场景：`ITCM_selected`；`BIU_selected`。

实测：2 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-DATAPATH-ERROR-MUX 非拼接响应不受旧 leftover 错误影响**

触发：leftover_err_r=1 后执行普通单 uop，当前响应 err=0/1。检查：非拼接只传播当前 err；拼接才对当前 err 与保存 err 做 OR。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:654`；module `e203_ifu_ift2icb`；符号 `i_ifu_rsp_err`。
实际观察：rsp_instr_sel_leftover、i_ifu_rsp_err。
必需场景：`ordinary_ok`；`ordinary_error`；`assembled`。

实测：74 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-DATAPATH-FIRST-SUPPRESS 首拆分响应只进入 leftover**

触发：1ST need_2uop=1，IFU 外部响应受阻。检查：首响应仍能接受到 leftover，i_ifu_rsp_valid 不因该首响应置位。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:675`；module `e203_ifu_ift2icb`；符号 `ifu_icb_rsp2leftover`。
实际观察：ifu_icb_rsp2leftover、ICB ready、i_ifu_rsp_valid。
必需场景：`consumer_ready`；`consumer_stalled`。

实测：29 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-DATAPATH-ZERO-RESPONSE 零 uop 生成内部响应**

触发：1ST need_0uop=1，两个 ICB rsp_valid 都为 0。检查：仍生成一次正确内部 IFU 响应且不发 ICB 命令。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:669`；module `e203_ifu_ift2icb`；符号 `holdup_gen_fake_rsp_valid`。
实际观察：holdup_gen_fake_rsp_valid、i_ifu_rsp_hsked、命令轨迹。
必需场景：`buffer_empty`；`buffer_full`。

实测：21 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / 命令形成及准入

**E203-INT-ADDRESS-CURRENT 普通首命令使用当前 PC**

触发：新请求非 held-cross、不是第二命令。检查：命令地址等于当前请求 PC，不受 last_pc 无关值影响。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:758`；module `e203_ifu_ift2icb`；符号 `icb_addr_sel_cur`。
实际观察：地址选择三路、ifu_icb_cmd_addr。
必需场景：`ordinary`；`split_first`。

实测：62 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-ADDRESS-NEXT-OFFSET 下一 lane 地址的三种加数**

触发：分别执行第二 uop、held-cross 顺序 +2、held-cross 顺序 +4。检查：相对 last_pc 的加数分别是 2/4/6，按 32 位回绕。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:760`；module `e203_ifu_ift2icb`；符号 `nxtalgn_plus_offset`。
实际观察：nxtalgn_plus_offset、last_pc、ICB 地址。
必需场景：`+2`；`+4`；`+6`；`overflow`。

实测：75 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-ADDRESS-SECOND-CMD-ENABLE 第二命令的两种启动时刻**

触发：首拆分响应接受，或停在 WAIT2ND；另测首响应未接受。检查：只在首响应接受当拍或 WAIT2ND 发第二命令；不得提前或重复发送。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:724`；module `e203_ifu_ift2icb`；符号 `ifu_icb_cmd_valid`。
实际观察：state、req_need_2uop_r、ICB command valid/accept。
必需场景：`direct`；`WAIT2ND`；`first_response_absent`。

实测：87 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-ADDRESS-NEW-ADMISSION 新请求准入窗口**

触发：遍历 IDLE、1ST 的最终/非最终响应、WAIT2ND、2ND 最终响应。检查：只在空闲或旧请求内部最终响应接受时开放，仍由目标命令 ready 限制。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:778`；module `e203_ifu_ift2icb`；符号 `ifu_req_ready_condi`。
实际观察：ifu_req_ready_condi、ifu_req_ready、内部响应接受。
必需场景：`IDLE`；`1ST_final`；`1ST_nonfinal`；`WAIT2ND`；`2ND_final`。

实测：270 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-ADDRESS-READY-ROUTE 命令 ready 仅来自目标端口**

触发：两路 ready 取相反值，目标 ITCM/BIU 各一次。检查：未选中端口 ready 不得放行或阻塞目标命令；零 uop 当前实现仍受目标 ready 限制。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:816`；module `e203_ifu_ift2icb`；符号 `ifu_icb_cmd_ready`。
实际观察：两路 ready、ifu_icb_cmd_ready、请求接受。
必需场景：`ITCM_ready_only`；`BIU_ready_only`；`zero_uop_target_blocked`。

实测：8 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-ADDRESS-DISPATCH-EXCLUSIVE 单条命令目标互斥**

触发：普通与跨区域第二命令，改变 region 指示的合法配置。检查：有效命令只发往一个目标；ITCM 地址截取16位、BIU保留32位。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:794`；module `e203_ifu_ift2icb`；符号 `ifu_icb_cmd2itcm`。
实际观察：两路命令 valid/address、内部完整地址。
必需场景：`ITCM`；`BIU`；`region_cross`。

实测：136 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / 响应旁路缓冲

**E203-INT-BUFFER-BYPASS 空缓冲直接旁路**

触发：FIFO 为空且输入 valid、输出 ready。检查：输入当拍直达输出，FIFO 不入队，不增加响应延迟。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/sirv_gnrl_bufs.v:353`；module `sirv_gnrl_bypbuf`；符号 `wire byp`。
实际观察：byp、fifo_i_vld、fifo_o_vld、输入/输出数据。
必需场景：`ok`；`error`。

实测：53 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-BUFFER-CAPTURE 空缓冲在下游受阻时存入**

触发：FIFO 空且输入 valid、输出不 ready。检查：内部响应可以接受一次，{err,instr} 一同入队，后续保持到取走。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/sirv_gnrl_bufs.v:367`；module `sirv_gnrl_bypbuf`；符号 `fifo_i_vld`。
实际观察：fifo_i_vld/rdy、fifo_o_vld/dat、i_ifu_rsp_hsked。
必需场景：`one_cycle_stall`；`long_stall`。

实测：9 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-BUFFER-PRIORITY 已有缓冲数据优先**

触发：FIFO 非空，同时出现另一内部响应。检查：输出保持旧 FIFO 数据，不能被新的直通输入覆盖。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/sirv_gnrl_bufs.v:362`；module `sirv_gnrl_bypbuf`；符号 `assign o_dat`。
实际观察：fifo_o_dat、i_dat、o_dat 与事务顺序。
必需场景：`distinct_data`；`different_err`。

实测：22 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-BUFFER-FULL-CUT-READY 满缓冲不同时接收替换数据**

触发：DP=1、CUT_READY=1，FIFO 满且本拍输出将取走。检查：本拍 i_rdy 仍为低；新输入只能等 FIFO 清空后再接受，不能假设满时 pop/push 同拍。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/sirv_gnrl_bufs.v:334`；module `sirv_gnrl_bypbuf`；符号 `CUT_READY`。
实际观察：fifo_i_rdy、fifo_o_vld、输出接受及次拍输入接受。
必需场景：`full_stalled`；`full_popping`。

实测：39 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-BUFFER-DRAIN 缓冲排空后无重复响应**

触发：已缓存响应在输出 ready 后被接受，内部无新响应。检查：下一拍缓冲为空且输出无效，只交付一次原有响应。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/sirv_gnrl_bufs.v:356`；module `sirv_gnrl_bypbuf`；符号 `fifo_o_rdy`。
实际观察：FIFO occupancy、输出事件计数。
必需场景：`after_short_stall`；`after_long_stall`。

实测：9 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

### 设计内部 / 复位与可见状态

**E203-INT-RESET-CONTROL 复位控制状态**

触发：rst_n 拉低并覆盖有效时钟边沿；释放后无新请求。检查：FSM=IDLE，请求标志、路由寄存器、leftover_err 和响应 FIFO valid 清零；无伪响应。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:474`；module `e203_ifu_ift2icb`；符号 `icb_state_dfflr`。
实际观察：所有 resettable 控制寄存器和外部有效位。
必需场景：`idle_reset`；`inflight_reset`；`buffered_reset`。

实测：24 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

**E203-INT-RESET-UNRESET-DATA 未复位数据在使用前必须写入**

触发：复位后原 leftover/data/offset 内容不可假设为零。检查：首次可能选择这些寄存器的有效事务必须有正确装载历史；按字节模型检查首次结果。

验证层：`design_internal`。
RTL：`example/e203_ifu_ift2icb/e203_ifu_ift2icb.v:566`；module `e203_ifu_ift2icb`；符号 `leftover_dffl`。
实际观察：数据装载使能历史、响应选择、有效响应。
必需场景：`first_plain`；`first_split`；`first_held_after_legal_fill`。

实测：74 次比较，场景激活 100%，比较失败 0；`closed=true`。
检查实现：[e203_internal_coverage.py](../../examples/integration/e203/e203_internal_coverage.py)；关闭同时要求实际场景和比较通过。

## 根据实测缺口更新 case

主 campaign 保留 34 定向 + 500 随机 fetch。额外 case 针对此前不能证明的路径：前序 cross=0 的顺序 lane 起始、长 WAIT2ND、旧错误清除、未选端口实际响应、两端 ready 不同、同拍交接及旧 FIFO 数据优先。

流式输入覆盖 0→1、1→2、2→0/1/2 与目标切换。复位 case 分别在首响应等待、第二命令受阻、已缓冲输出受阻时中断；复位后重新取 split 指令并比较。四个错误快照反例验证属性检查的敏感性，另存 checker 证据，不合并入 DUT bins。

同一 RTL/配置和属性契约的独立最终快照才合并；运行 UUID 和 snapshot identity 防止重复计数。外部故障注入、检查器伪造快照和取消结果不纳入本次 DUT 证据集合。功能百分比、正确性及 pytest 结果分别报告。

完整回归与外部事务数量见结果汇总（本地产物：`rtl-property-evidence-2026-10-01/results.json`）。其他配置、未定义非法请求和物理存储器时序仍在范围之外。
