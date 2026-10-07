# 从设计机制定义功能点（2026-09-29）

## 当前适用方式

两份 JSON 现用 `scope` 与 `requirements` 保留设计要求和 case 设计依据，不再作为
pytest 输入。人工标签聚合及完成率报告已移除；覆盖由实际场景观察记录，再跨 case 合并。
2026-10-01 已落实 e203 49 项、Cache 77 项内部属性与 527 个必需场景 bins；激活均为
100%，e203 49 项、Cache 76 项满足本基线关闭条件，Cache 读 burst 数据属性未关闭。
详见[e203 明细](e203-functional-points-2026-09.md)、[Cache 明细](cache-functional-points-2026-09.md)
及实测结果（本地产物：`rtl-property-evidence-2026-10-01/results.json`）。后续尚未实现的要求应保持未测量。
末尾的标签统计及下方“仅完善定义”的文字都是当时的历史记录，
实现变更见[移除记录](coverage-without-test-tags-2026-09.md)。

## 定义扩展记录

上一版从现有测试倒推清单，细化到 e203 40 点、Cache 33 点，仍主要是接口事务和验证器自测。
这个清单不能表示设计内部验证完整度。本轮读取实际 RTL，补充**机制级验证义务**：
状态转移、寄存器装载/保持、数据选择、forwarding、仲裁、资源占用、计数器及配置约束。
测试文件数量和参数数量不再作为功能点数量的依据。

定义保存在原有两个文件：

- [e203 verification_plan.json](../../examples/integration/e203/verification_plan.json)：原 40 点加 49 个内部点，共 89 点。
- [Cache verification_plan.json](../../examples/integration/cache/verification_plan.json)：原 33 点加 77 个内部点，共 110 点。

这是依据当前 RTL 提取、待与设计意图共同评审的验证基线，不宣称已经穷尽规格。
本轮只完善定义和证据契约，没有为新增点安装内部采样器或断言，也没有把相关外部测试的
PASS 转记为内部点 PASS。新增 126 个内部要求尚未落实运行时采样与检查，无法判断现有 case 实际命中了哪些场景。

## 定义的来源和适用配置

来源是本机 Picker checkout 的 `example/e203_ifu_ift2icb` 与 `example/CacheSignalCFG/Cache.v`。
每个内部点的 metadata 记录源码文件、行号、所在 module 和对应符号；计划的 scope 保存
源文件 SHA-256，RTL 更新后需重新评审引用及语义，不能沿用过期结论。

e203 仅针对 IFU-to-ICB bridge：PC32、ITCM64、BIU32、响应缓冲 DP=1。不把整核译码、
预测、TLB 或其他宏配置中没有实例化的分支算进来。Cache 针对当前生成的四路、128 set、
每行八个 64-bit word 的可写配置，覆盖三个流水阶段和实际实例化的 SRAM/arbiter。

发现的配置约束：Cache.v 中 `io_flush[1]` 接到 Stage3，而 Stage3 保留
`only allow to flush icache` 断言。原 CACHE-FLUSH 改成“当前写型配置禁止 Stage3 flush”，
其关闭证据应是 assertions 确实启用时的独立非法操作负例。不能为了命中 needFlush 分支，
向正常 campaign 输入当前配置禁止的操作。其他配置的合法 flush 不属于这个分母。

## e203 内部清单的结构

| ID 中段 | 点数 | 具体要求 |
| --- | ---: | --- |
| LANE | 8 | 两种 lane 宽度分类；顺序/非顺序与上次 cross 的关系；hold/nohold 三条件；0/2/held-cross uop 判定 |
| FSM | 11 | IDLE→1ST、1ST→WAIT2ND/2ND/IDLE/1ST、WAIT2ND 保持/退出、2ND→IDLE/1ST、四态保持、退出选择互斥 |
| CTX | 5 | 请求标志按接受更新、命令路由锁存、零 uop 偏移刷新、无接受时保持、last_pc 的阶段含义 |
| LEFTOVER | 6 | holding 和首响应两种装载、数据保持、首响应错误保存、holding 装载清旧错误、错误位保持 |
| DATAPATH | 6 | ITCM 三种截取位置、两种 leftover 拼接、未选端口隔离、旧错误隔离、首响应抑制、零 uop 内部响应 |
| ADDRESS | 6 | 当前地址选择、+2/+4/+6、第二命令两种启动、下一请求准入、目标 ready 选择、目标互斥分发 |
| BUFFER | 5 | 空缓冲旁路、受阻时存入、旧数据优先、CUT_READY 满时限制、排空无重复 |
| RESET | 2 | 控制寄存器复位、未复位数据使用前装载，不能依赖初始零值 |

例如 `E203-INT-LEFTOVER-ERROR-CLEAR-HELD` 不是“错误测试通过”的别名：

1. 先使 `leftover_err_r=1`，证明存在非零旧状态。
2. 再合法接受 held-cross 请求，观察实际装载事件。
3. 在该边沿更新后断言 `leftover_err_r=0`，同时独立核对最终指令和 error。

只有最终 error=0，不能证明经历了这次内部清除；可能根本未装载过错误值。反过来，仅看到
错误位清零也不足以证明输出正确。内部属性检查和端到端模型需要共同提供证据。

响应缓冲也不能沿用“普通深度一 FIFO”的直觉：实例使用 CUT_READY=1，满缓冲即使当拍
即将 pop，也不能在同拍接受替换输入。`E203-INT-BUFFER-FULL-CUT-READY` 单独记录此条件。

## Cache 内部清单的结构

| ID 中段 | 点数 | 具体要求 |
| --- | ---: | --- |
| PIPE | 7 | 两 SRAM 共同许可、地址分解、两级 payload 保持、finish 退休、同拍消费补入、empty 的含义 |
| LOOKUP | 9 | 四路有效 tag 命中、无效旧 tag 排除、invalid 优先与高编号优先、LFSR 候选与推进、one-hot、两段 MMIO 边界 |
| FORWARD | 10 | metadata 同 set/异 set、延迟保存/当前写优先/清除；data 精确到 word、保存/更新、Stage3 way 匹配、连续 mask 写依赖 |
| FSM | 12 | clean/dirty/MMIO 初始分流、refill 与 writeback 各阶段、等待确认、完成态、probe header 与 release 退出 |
| ARRAY | 6 | metadata 128 set 扫描、初始化阻塞、逐 way 写、写优先、Stage1/3 读仲裁、读返回归属 |
| FORWARD-READ | 4 | Stage3 state2 的发起、同步数据捕获、受阻保持、接受后取下一 word |
| REFILL | 7 | 初始 word、接受递增与回绕、逐拍写入、仅首拍合并、末拍提交 tag/valid、dirty 初始化、afterFirstRead 生命周期 |
| EARLY | 5 | demand 缓存不被后续拍覆盖、允许提前响应的操作类别、alreadyOutFire 置位、无重复、refill 先完成但 CPU 受阻 |
| WRITEBACK | 5 | victim 地址来源、写回计数、末拍命令、clean→dirty、byte enable 与 read 不写入 |
| COHERENCE | 5 | header 接受装载起始 word、地址/完成计数分离、末拍接受资格、连续 probe 计数、选中 way 数据来源 |
| ARBITRATION | 3 | probe 优先于 CPU、Stage1 读释放后的 Stage3 进展、hit-write/refill-write 互斥 |
| RESET | 2 | 流水/控制复位、data SRAM 不复位时的首次读保护 |
| BURST | 2 | 当前事务示例未覆盖的 CPU read-burst 和 write-burst 控制路径，需独立核对 SimpleBus 契约 |

`CACHE-INT-FORWARD-META-HOLD` 要求先制造真实 Stage2 stall，再让同 set 的 metadata 写入
经过，撤掉写端后观察保存的 forwarding 是否仍有效。这与串行 write 后 read 返回正确完全
不同：串行场景很可能始终从已经更新的 SRAM 取数，根本没有触发 forwarding。

`CACHE-INT-REFILL-META-LAST` 则要求末拍之前 metadata 不可提前提交、末拍实际接受时
才提交。只检查 refill 后整行读回，不能证明中途没有错误的 valid 暴露窗口。

源码也明确了两个容易误写的要求：替换不是 LRU，当前候选来自 LFSR；同时存在多个 invalid
way 时选最高编号 invalid way。入口仲裁和 data SRAM 读仲裁也是固定优先级，不能凭习惯
要求 round-robin 或在无限高优先级流量下保证低优先级请求完成。

## 功能点、场景与证据的关系

一个点对应一个可独立失败的行为义务。相同规则在四个 way、八个起始 word 上的实例通常
放入该点的 `required_scenarios`，不把每一个 bit 翻转机械地扩成新功能点。只有因果条件或
错误后果不同，例如“forwarding 保持”和“forwarding 清除”，才拆成两个点。

每个新增点包含：

| 字段 | 用途 |
| --- | --- |
| description | 激活条件与明确的预期结果 |
| rtl / module / anchor | 回到这版设计的对应机制，不能代替规格判断 |
| observation | 需要同步取得的状态、数据、事件；是逻辑信号清单，不冒充已验证的 VPI 路径 |
| required_scenarios | 要全部触发的矩阵，例如四路、首/中/末、同拍完成补入、错误历史 |
| sampling | 接受边沿前的组合条件与边沿提交后的寄存器值分别采样 |
| closure | 激活发生、对应属性断言通过、所需场景全部命中，三者缺一不可 |
| verification_layer | design_external、design_internal 或 testbench，防止把环境自测计成 DUT 内部验证 |
| evidence | 已有观察/检查代码或待补证据的说明；不用于聚合测试结果 |

`required_scenarios` 目前只是计划要求，尚未实现为运行时 CoverPoint/Cross，不能把清单长度
称为已采样 bin 数。之后可用逐周期项目 Monitor/VPI 导出信号、RTL 内断言或模块级 harness
提供证据；只读内部观察不需要更改 Driver 的协议时序，也不需要另做调度器。

e203 当前构建脚本未开启 VPI，不能直接声称这些内部符号已经可读；需要先显式导出或构建
相应观察版本。Cache 已有少量 VPI 诊断信号，但诊断打印不等于周期属性验证，其他层次路径
也需逐项确认。对优化掉的信号应改选等价观测点或模块级检查，不能用猜测值填补。

检查器设计不能简单复制 RTL 方程再比较。应以独立 byte/line 模型、接受事件账本、状态的
允许转移和寄存器使能约束检查行为；分支覆盖和状态访问记录用于判断是否触发，不直接给 PASS。
尤其跨生命周期属性，检查窗口必须从前置状态建立一直延续到后置条件完成，避免空触发通过。

## 当前状态与实施顺序

内部要求尚无统一运行时采样；外部事务与验证器检查保留已有实现。要求条目数不是
覆盖率分母，运行时 bins 才定义已实现的采样模型；需同时说明模型未包含的计划场景。
验证器的故障、取消、报告测试只证明验证环境自身行为，不计入 DUT 内部机制覆盖率。

建议先落实能复用现有定向激励的被动内部观测：e203 FSM/leftover/buffer，Cache refill
计数器/metadata 提交/early-response。接着补串行 campaign 无法触发的 forwarding、同拍
退休补入和仲裁场景。最后做受控模块级边界/非法使用检查，包括 LFSR 零态和当前配置禁止的
flush；不把这些输入直接混进正常 DUT campaign。

本轮不要求新增 126 个测试函数。一个仿真可以同时检查多条属性，但各点需要记录自己的
激活与检查结果；某段事务跑完不能自动关闭其间所有尚未观测的内部义务。

## 从覆盖缺口反推 case

上一轮停在“列要求、保留 NOT_RUN”，没有完成从功能点推导 case 的工作。
下面依据现有 harness 和定向序列区分**缺少观测**与**缺少激励能力**。
“已有相关激励”只是静态审查发现，不代表已经测得内部命中。
表中的 bin 是应实现的采样契约，尚不是已有 CoverPoint；不增加计划点数。

### e203

| 功能点 / 机制 | 必须实际出现的场景 | case 设计及检查 | 当前缺口 |
| --- | --- | --- | --- |
| FSM-FIRST-WAIT / WAIT-HOLD / WAIT-SECOND | 两路由分别经历首响应接受、第二命令受阻、等待自环、解阻退出 | 跨 lane 请求；第二命令阻塞 3 拍，再放行。记录首响应与第二命令接受事件，检查状态序列和等待期间的上下文保持；最终指令与 byte 模型比较 | `directed_requests()` 已包含 `second_command_stall=3`；补内部采样后确认，不能以参数值代替状态命中 |
| FSM-FIRST-SECOND | 首响应接受与第二命令接受同拍 | 拆分请求且第二命令不阻塞，检查直接进入 2ND、没有额外首响应交付 | 已有不阻塞的拆分激励；缺少逐周期事件和状态证据 |
| FSM-FIRST-FIRST / SECOND-FIRST、ADDRESS-NEW-ADMISSION | 旧事务完成边沿同时接受新请求，分别覆盖单命令和拆分事务 | 在旧响应完成前呈现下一合法请求，以实际两个接受事件同拍为命中条件；按接受顺序保存各自 PC、路由和期望输出，检查无丢失/串线 | 当前 `fetch()` 等一笔完成后再发下一笔，需项目级连续输入序列；单纯增加随机数或减小 delay 无法保证触发 |
| LEFTOVER-ERROR-CLEAR-HELD | 旧错误位确为 1，随后 held 装载把它清为 0 | 第一段拆分取指在首响应注入错误；再建立合法 held-cross 请求，观察装载前后的错误位及数据，并检查新事务的最终 error | 现有错误/holding 序列不能替代这段有明确前置状态的检查；需补两阶段激励与内部观察 |
| BUFFER-BYPASS / CAPTURE / FULL-CUT-READY / DRAIN | 空时旁路、下游受阻存入、满时 pop 边沿不接收替换、排空 | 输出受阻后恢复；用输入/输出接受账本检查守恒和顺序。满时替换场景需保证缓冲非空且上游也有有效输入，观察 CUT_READY | 现有输出 stall 可复用来检查 capture/drain；满缓冲竞争条件没有证据，需定向序列或缓冲模块级 harness |
| CTX-OFFSET-ZERO、DATAPATH-ZERO-RESPONSE | 无 ICB 命令但接受了新 PC，偏移更新且仅交付一次 | 复用合法 sequential holding 的零命令请求；接受边沿记录新 PC，核对偏移与旧 lane 的选段、最终指令、输出次数 | 现有零命令事务可复用；缺内部寄存器观察和对应接受事件关联 |

e203 的观察前置工作是构建明确导出内部信号的版本；现有构建没有 VPI。不能为了让表中
条目变绿，直接用 `FetchRequest` 配置值推测寄存器状态。

### Cache

| 功能点 / 机制 | 必须实际出现的场景 | case 设计及检查 | 当前缺口 |
| --- | --- | --- | --- |
| REFILL-COUNT-INIT / COUNT-STEP / DATA-WRITE | 八种起始 word、接受推进、空拍保持、7→0 回绕 | 复用从各 word 发起的 miss 和 memory response gap；逐拍记录接受事件，以起始 word 加已接受拍数推导写地址，核对数据及计数 | 已有各起始 word 和 `response_gap=1`；缺内部计数/阵列写使能采样 |
| REFILL-META-LAST / META-DIRTY / WRITE-MERGE | 末拍之前不安装 metadata；末拍才安装；read/write 分支及首拍部分写合并 | read miss 与 partial write allocate；在末拍出现前插入响应空拍，逐拍检查 metadata 写使能与数据合并位置，再整行读回 | 已有相关 read/write miss 和 partial mask；尚无中间状态检查，整行读回不能证明提交时机 |
| EARLY-RETURNED-FLAG / NO-DUPLICATE / FINAL-WHILE-STALLED | CPU 在 refill 完成前交付，以及 refill 完成时 CPU 仍未接收，两种相反顺序 | 同一 read miss 分两组：CPU 立即接收；CPU 保持受阻直到观测到 refill 末拍已接受再放行。记录实际事件顺序，检查 demand 数据保持、一次交付及退休 | 现有 miss 提供第一组候选激励；受阻测试主要针对 hit，第二组需按事件控制的 miss 场景，固定等几拍不构成命中证据 |
| FORWARD-META/DATA-HOLD / NEWEST / WAY-QUALIFY | 同地址冲突、异地址排除、Stage2 受阻时保存、后来的写覆盖旧保存值、way 匹配/不匹配 | 让后一请求进入流水并受阻，再使前一请求写阵列；撤掉写端检验保持，再安排可合法到达的新写。使用不同数据区分 SRAM、旧 forwarding 和新 forwarding 来源 | 默认 CPU 请求先等 `io_empty`，串行 read-after-write 无法建立这种重叠；需项目级流水激励或 Stage2/3 模块级 harness，并先确认可达性 |
| ARBITRATION-PROBE-PRIORITY / DATA-PRIORITY | CPU/probe 同时请求；Stage1/3 同时请求 data SRAM；高优先级退出后低优先级进展 | 在同一采样窗口保持两个请求，确认真实竞争和 grant；保持各自 payload，解除高优先级后等待低优先级完成并核对数据 | 现有 CPU/probe 分段运行，缺少竞争激励；两个仲裁器分别建场景，不以其一命中代替另一个 |
| LOOKUP-INVALID-FIRST / INVALID-PRIORITY / ALL-VALID | 有多个 invalid way、仅一个 invalid way、全 valid 的 miss | 从 reset 后逐步填满同一 set，再触发替换；每次接受时记录 valid mask、所选 way 和 LFSR 候选，核对 invalid 优先及全 valid 分支 | 现有同 set 填充/替换可复用；缺 way 和 valid mask 观察。不能用被驱逐地址倒推所有选择条件都出现过 |

### 如何根据运行结果继续补 case

采样应先记录“前置条件确实发生”，再执行对应检查，失败也保存已观察的激活事件。
记录至少能追溯功能点、case/seed、事务或周期、场景名及失败条件；不要求保存全部历史波形。
一条属性从未触发却没有报错，不算验证完成；一个 bin 已命中但断言失败，也不能标记 PASS。

下一步应先给上述可复用的定向 case 加观察，得到真实缺口，再补缺少的重叠/竞争激励。
已知 overlap 探针失败需要保留为缺陷证据，不能被普通 campaign 的通过或未绑定的 NOT_RUN
遮住。受当前配置禁止或难以到达的场景应单独评审，不能通过删 bin 来制造 100%。
下面的运行结果保留当时记录；后续已移除标签聚合机制，但尚未新增这些内部采样器，
也不宣称内部点已覆盖。

## 历史复查证据（移除标签之前）

仅修改两份计划和相关文档，未修改通用框架、Driver 时序或 RTL。实际运行现有项目入口：

| 入口 | pytest | 完整计划报告 |
| --- | ---: | --- |
| e203 run_pytest.sh，E203_RANDOM_COUNT=0 | 23 passed | 38/89 PASS，51 NOT_RUN |
| Cache test_cache_coherence.py，显式加载计划 | 8 passed | 29/110 PASS，81 NOT_RUN |

e203 产物为 `/tmp/xreactor-dut-current/e203-internal-plan`，Cache 功能点报告为
`/tmp/xreactor-dut-current/cache-internal-plan/features.json`。这只证明现有测试和扩展计划
能正确接入报告，不提供新增内部属性的通过证据。

另核对 ID 唯一性、必需场景非空且无重复、所有内部源码行/符号与 SHA-256 基线一致、
FeatureTracker 能读取完整计划且未绑定点默认 NOT_RUN。严格 MkDocs 构建与 diff 检查通过。
没有因增加计划条目而重复全仓库测试。
