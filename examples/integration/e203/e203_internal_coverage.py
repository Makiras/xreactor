"""Observed e203 state, context, leftover and response-buffer properties."""
from __future__ import annotations

from collections import deque
import os

from examples.integration.rtl_checks import ClockObserver, Rule, ScenarioChecks

RULES = {
    'E203-INT-LANE-CLASSIFY': Rule('触发：ITCM64 遍历 PC[2:1]，BIU32 遍历 PC[1]。检查：起始、中间、跨界分类分别满足 8-byte/4-byte lane 定义；不能用统一 lane 宽度。', ('ITCM:00', 'ITCM:01', 'ITCM:10', 'ITCM:11', 'BIU:0', 'BIU:1')),
    'E203-INT-LANE-SAME-NONSEQ': Rule('触发：ifu_req_seq=0，独立变化 lane_begin 和上次 cross 标志。检查：lane_same 恒为 0，即使新旧 PC 数值相近也不能复用。', ('begin', 'middle', 'cross')),
    'E203-INT-LANE-SAME-BEGIN': Rule('触发：顺序取指且 lane_begin=1，上次请求 cross 为 0/1。检查：仅上次已跨 lane 预取时 lane_same=1。', ('previous_cross=0', 'previous_cross=1')),
    'E203-INT-LANE-SAME-MIDDLE': Rule('触发：顺序取指且 lane_begin=0。检查：lane_same=1；仍须另行满足 holdup 才能省略访问。', ('middle', 'cross')),
    'E203-INT-LANE-HOLD-GATE': Rule('触发：逐一撤掉 ITCM 目标、ifu2itcm_holdup、允许 hold 三个条件。检查：仅 ITCM 且 holdup 且 nohold=0 时允许 lane_holdup；BIU 不得复用。', ('enabled', 'nohold', 'holdup_low', 'BIU')),
    'E203-INT-LANE-UOP-ZERO': Rule('触发：same=1、cross=0、holdup=1，再逐一撤掉条件。检查：只在完整条件成立时 need_0uop=1；need_2uop 必为 0。', ('eligible', 'not_same', 'cross', 'not_held')),
    'E203-INT-LANE-UOP-TWO': Rule('触发：跨 lane：same&&!hold，或 !same；另测非跨界。检查：两类跨界各需两次访问，非跨界不置 need_2uop。', ('same_unheld', 'different_lane', 'not_cross')),
    'E203-INT-LANE-UOP-HELD-CROSS': Rule('触发：same、cross、hold 全为 1。检查：same_cross_holdup=1，need_0uop=need_2uop=0，只访问后一 lane。', ('held_cross',)),
    'E203-INT-FSM-IDLE-FIRST': Rule('触发：IDLE 中请求分别需要零/一/两 uop，输入实际接受。检查：下一拍为 1ST；即使零 uop 也不能停在 IDLE。', ('0uop', '1uop', '2uop')),
    'E203-INT-FSM-FIRST-WAIT': Rule('触发：1ST、need_2uop=1、首 ICB 响应接受、命令未 ready。检查：下一拍 WAIT2ND；此时不产生完整 IFU 响应。', ('ITCM', 'BIU')),
    'E203-INT-FSM-FIRST-SECOND': Rule('触发：1ST、need_2uop=1、首响应接受且命令 ready。检查：下一拍直接 2ND；第二命令本拍恰好接受一次，无 WAIT2ND 空拍。', ('same_target', 'region_switch')),
    'E203-INT-FSM-WAIT-HOLD': Rule('触发：第二命令持续未 ready 至少两拍。检查：状态保持 WAIT2ND，命令地址及 leftover/error 不变。', ('two_cycle_stall', 'long_stall')),
    'E203-INT-FSM-WAIT-SECOND': Rule('触发：WAIT2ND 中第二命令 ready。检查：该命令接受后进入 2ND；不得重新发首命令。', ('ITCM', 'BIU')),
    'E203-INT-FSM-FIRST-IDLE': Rule('触发：1ST 中零/一 uop 的内部 IFU 响应接受，无新请求。检查：下一拍 IDLE；比较的是 i_ifu_rsp_hsked，不能误用外部缓冲响应接受。', ('0uop', '1uop')),
    'E203-INT-FSM-FIRST-FIRST': Rule('触发：1ST 中零/一 uop 完成且新请求同拍接受。检查：保持 1ST，但上下文切换为新请求；旧响应无丢失或串号。', ('0_to_1', '1_to_2', 'target_change')),
    'E203-INT-FSM-SECOND-IDLE': Rule('触发：2ND 中内部 IFU 响应接受，无新请求。检查：下一拍 IDLE，leftover 不再影响下一非拆分指令。', ('ok', 'error')),
    'E203-INT-FSM-SECOND-FIRST': Rule('触发：第二响应完成且新请求同拍接受。检查：下一拍 1ST；旧 leftover 用于旧响应，新请求上下文同时正确锁存。', ('new_0uop', 'new_1uop', 'new_2uop')),
    'E203-INT-FSM-NO-EXIT': Rule('触发：IDLE 无请求，1ST/2ND 无所需响应，WAIT2ND 命令阻塞。检查：分别保持原状态，不能因仅 valid 或其他端口事件前进。', ('IDLE', '1ST', 'WAIT2ND', '2ND')),
    'E203-INT-FSM-EXIT-ONEHOT': Rule('触发：运行四种合法状态，含同拍旧响应/新请求。检查：四个 exit_ena 至多一个为真，state_nxt 只来自当前状态分支。', ('IDLE', '1ST', 'WAIT2ND', '2ND', 'handoff')),
    'E203-INT-CTX-REQ-LOAD': Rule('触发：在未接受请求期间改变候选 PC/seq/hold，然后接受。检查：四个 *_r 标志只在 ifu_req_hsked 更新为被接受请求，不能提前污染旧事务。', ('stalled_input', 'accepted_input', 'handoff')),
    'E203-INT-CTX-ROUTE-LATCH': Rule('触发：ITCM/BIU 命令切换及未接受候选地址变化。检查：icb_cmd2itcm_r/biu_r 只在命令接受更新；响应由该记录选择。', ('ITCM_to_BIU', 'BIU_to_ITCM', 'no_accept')),
    'E203-INT-CTX-OFFSET-ZERO': Rule('触发：holding 零 uop 请求接受，没有 ICB 命令接受。检查：icb_cmd_addr_2_1_r 仍更新，正确选择新 PC 的半字位置。', ('offset_0', 'offset_2', 'offset_4')),
    'E203-INT-CTX-OFFSET-HOLD': Rule('触发：请求和命令均未接受，外部候选 PC 变化。检查：偏移寄存器保持；不能被下一候选地址改变当前响应对齐。', ('waiting_response', 'stalled_command')),
    'E203-INT-CTX-LAST-PC-PHASE': Rule('触发：顺序跨 lane，握手前为 previous PC，握手后更新为 current PC。检查：held-cross 首命令用 previous PC；后续第二命令用 current PC，两个阶段的地址均正确。', ('+2', '+4', 'two_uop')),
    'E203-INT-LEFTOVER-HELD-LOAD': Rule('触发：held-cross 请求实际接受。检查：leftover 捕获被保持 lane 的最高 16 位；不能使用下一 lane 数据。', ('accepted', 'blocked')),
    'E203-INT-LEFTOVER-FIRST-LOAD': Rule('触发：两 uop 首 ICB 响应实际接受。检查：分别捕获 ITCM[63:48] 或 BIU[31:16]，不提前给出完整指令。', ('ITCM', 'BIU')),
    'E203-INT-LEFTOVER-DATA-HOLD': Rule('触发：两个装载事件均未发生，改变非当前响应数据。检查：leftover_r 不变；WAIT2ND 与等待第二响应期间均保持。', ('WAIT2ND', '2ND_no_response')),
    'E203-INT-LEFTOVER-ERROR-CAPTURE': Rule('触发：首响应错误 0/1，另一路错误独立变化。检查：只保存被选中首响应的错误位，与同笔 leftover 数据对应。', ('ITCM_ok', 'ITCM_error', 'BIU_ok', 'BIU_error')),
    'E203-INT-LEFTOVER-ERROR-CLEAR-HELD': Rule('触发：先产生有错 leftover，再合法接受 held-cross 请求。检查：holding 装载将 leftover_err_r 清零，不能继承上一事务错误。', ('error_to_held_ok',)),
    'E203-INT-LEFTOVER-ERROR-HOLD': Rule('触发：等待第二命令或第二响应，其他 err 信号变化。检查：leftover_err_r 直到装载或 reset 前保持。', ('stored_0', 'stored_1')),
    'E203-INT-DATAPATH-ALIGN-ITCM': Rule('触发：lane 各半字填不同值，偏移 0/2/4 分别响应。检查：输出分别为 rdata[31:0]/[47:16]/[63:32]；必须以实际锁存偏移选择。', ('offset_0', 'offset_2', 'offset_4')),
    'E203-INT-DATAPATH-LEFTOVER-SELECT': Rule('触发：1ST held-cross 或 2ND；另测普通 1ST。检查：前两类选择 {当前数据低16位,leftover}，普通取指走对齐数据，不得混入旧 leftover。', ('held_cross_1ST', 'split_2ND', 'ordinary_1ST')),
    'E203-INT-DATAPATH-UNSELECTED-RESPONSE': Rule('触发：等待当前端口响应时，让另一端口 data/err/valid 变化。检查：当前指令、错误及响应事件不受未选中端口影响；响应有效性按已接受命令路由。', ('ITCM_selected', 'BIU_selected')),
    'E203-INT-DATAPATH-ERROR-MUX': Rule('触发：leftover_err_r=1 后执行普通单 uop，当前响应 err=0/1。检查：非拼接只传播当前 err；拼接才对当前 err 与保存 err 做 OR。', ('ordinary_ok', 'ordinary_error', 'assembled')),
    'E203-INT-DATAPATH-FIRST-SUPPRESS': Rule('触发：1ST need_2uop=1，IFU 外部响应受阻。检查：首响应仍能接受到 leftover，i_ifu_rsp_valid 不因该首响应置位。', ('consumer_ready', 'consumer_stalled')),
    'E203-INT-DATAPATH-ZERO-RESPONSE': Rule('触发：1ST need_0uop=1，两个 ICB rsp_valid 都为 0。检查：仍生成一次正确内部 IFU 响应且不发 ICB 命令。', ('buffer_empty', 'buffer_full')),
    'E203-INT-ADDRESS-CURRENT': Rule('触发：新请求非 held-cross、不是第二命令。检查：命令地址等于当前请求 PC，不受 last_pc 无关值影响。', ('ordinary', 'split_first')),
    'E203-INT-ADDRESS-NEXT-OFFSET': Rule('触发：分别执行第二 uop、held-cross 顺序 +2、held-cross 顺序 +4。检查：相对 last_pc 的加数分别是 2/4/6，按 32 位回绕。', ('+2', '+4', '+6', 'overflow')),
    'E203-INT-ADDRESS-SECOND-CMD-ENABLE': Rule('触发：首拆分响应接受，或停在 WAIT2ND；另测首响应未接受。检查：只在首响应接受当拍或 WAIT2ND 发第二命令；不得提前或重复发送。', ('direct', 'WAIT2ND', 'first_response_absent')),
    'E203-INT-ADDRESS-NEW-ADMISSION': Rule('触发：遍历 IDLE、1ST 的最终/非最终响应、WAIT2ND、2ND 最终响应。检查：只在空闲或旧请求内部最终响应接受时开放，仍由目标命令 ready 限制。', ('IDLE', '1ST_final', '1ST_nonfinal', 'WAIT2ND', '2ND_final')),
    'E203-INT-ADDRESS-READY-ROUTE': Rule('触发：两路 ready 取相反值，目标 ITCM/BIU 各一次。检查：未选中端口 ready 不得放行或阻塞目标命令；零 uop 当前实现仍受目标 ready 限制。', ('ITCM_ready_only', 'BIU_ready_only', 'zero_uop_target_blocked')),
    'E203-INT-ADDRESS-DISPATCH-EXCLUSIVE': Rule('触发：普通与跨区域第二命令，改变 region 指示的合法配置。检查：有效命令只发往一个目标；ITCM 地址截取16位、BIU保留32位。', ('ITCM', 'BIU', 'region_cross')),
    'E203-INT-BUFFER-BYPASS': Rule('触发：FIFO 为空且输入 valid、输出 ready。检查：输入当拍直达输出，FIFO 不入队，不增加响应延迟。', ('ok', 'error')),
    'E203-INT-BUFFER-CAPTURE': Rule('触发：FIFO 空且输入 valid、输出不 ready。检查：内部响应可以接受一次，{err,instr} 一同入队，后续保持到取走。', ('one_cycle_stall', 'long_stall')),
    'E203-INT-BUFFER-PRIORITY': Rule('触发：FIFO 非空，同时出现另一内部响应。检查：输出保持旧 FIFO 数据，不能被新的直通输入覆盖。', ('distinct_data', 'different_err')),
    'E203-INT-BUFFER-FULL-CUT-READY': Rule('触发：DP=1、CUT_READY=1，FIFO 满且本拍输出将取走。检查：本拍 i_rdy 仍为低；新输入只能等 FIFO 清空后再接受，不能假设满时 pop/push 同拍。', ('full_stalled', 'full_popping')),
    'E203-INT-BUFFER-DRAIN': Rule('触发：已缓存响应在输出 ready 后被接受，内部无新响应。检查：下一拍缓冲为空且输出无效，只交付一次原有响应。', ('after_short_stall', 'after_long_stall')),
    'E203-INT-RESET-CONTROL': Rule('触发：rst_n 拉低并覆盖有效时钟边沿；释放后无新请求。检查：FSM=IDLE，请求标志、路由寄存器、leftover_err 和响应 FIFO valid 清零；无伪响应。', ('idle_reset', 'inflight_reset', 'buffered_reset')),
    'E203-INT-RESET-UNRESET-DATA': Rule('触发：复位后原 leftover/data/offset 内容不可假设为零。检查：首次可能选择这些寄存器的有效事务必须有正确装载历史；按字节模型检查首次结果。', ('first_plain', 'first_split', 'first_held_after_legal_fill')),
}


class E203InternalObserver(ClockObserver):
    """Compare the bridge against acceptance history and byte memory."""
    def __init__(self, dut, memory, *, seed=1, data_pattern="address"):
        external = {
            "rst": ("rst_n", 1), "pc": ("ifu_req_pc", 32),
            "seq": ("ifu_req_seq", 1), "rv32": ("ifu_req_seq_rv32", 1),
            "last_pc": ("ifu_req_last_pc", 32), "req_v": ("ifu_req_valid", 1),
            "req_r": ("ifu_req_ready", 1), "out_v": ("ifu_rsp_valid", 1),
            "out_r": ("ifu_rsp_ready", 1), "out_data": ("ifu_rsp_instr", 32),
            "out_err": ("ifu_rsp_err", 1), "holdup": ("ifu2itcm_holdup", 1),
            "nohold": ("itcm_nohold", 1), "region": ("itcm_region_indic", 32),
        }
        for target, width in (("itcm", 64), ("biu", 32)):
            for suffix, bits in (("cmd_valid", 1), ("cmd_ready", 1),
                                 ("cmd_addr", 16 if target == "itcm" else 32),
                                 ("rsp_valid", 1), ("rsp_ready", 1), ("rsp_err", 1),
                                 ("rsp_rdata", width)):
                external[f"{target}_{suffix}"] = (f"ifu2{target}_icb_{suffix}", bits)
        internal = {
            "state": ("icb_state_r", 2), "state_enable": ("icb_state_ena", 1),
            "begin": ("ifu_req_lane_begin", 1), "cross": ("ifu_req_lane_cross", 1),
            "same": ("ifu_req_lane_same", 1), "held": ("ifu_req_lane_holdup", 1),
            "cross_r": ("req_lane_cross_r", 1), "need0": ("req_need_0uop", 1),
            "need2": ("req_need_2uop", 1), "held_cross": ("req_same_cross_holdup", 1),
            "need0_r": ("req_need_0uop_r", 1), "need2_r": ("req_need_2uop_r", 1),
            "held_cross_r": ("req_same_cross_holdup_r", 1),
            "route_itcm": ("icb_cmd2itcm_r", 1), "route_biu": ("icb_cmd2biu_r", 1),
            "addr": ("ifu_icb_cmd_addr", 32), "cmd_v": ("ifu_icb_cmd_valid", 1),
            "cmd_r": ("ifu_icb_cmd_ready", 1), "rsp_v": ("ifu_icb_rsp_valid", 1),
            "rsp_r": ("ifu_icb_rsp_ready", 1), "rsp_err": ("ifu_icb_rsp_err", 1),
            "offset": ("icb_cmd_addr_2_1_r", 2), "offset_enable": ("icb_cmd_addr_2_1_ena", 1),
            "left": ("leftover_r", 16), "left_err": ("leftover_err_r", 1),
            "left_enable": ("leftover_ena", 1), "assembled": ("rsp_instr_sel_leftover", 1),
            "int_v": ("i_ifu_rsp_valid", 1), "int_r": ("i_ifu_rsp_ready", 1),
            "int_data": ("i_ifu_rsp_instr", 32), "int_err": ("i_ifu_rsp_err", 1),
            "to_left": ("ifu_icb_rsp2leftover", 1),
            "admission": ("ifu_req_ready_condi", 1),
            "fake": ("holdup_gen_fake_rsp_valid", 1),
            "fifo_full": ("u_e203_ifetch_rsp_bypbuf.fifo_o_vld", 1),
            "fifo_data": ("u_e203_ifetch_rsp_bypbuf.fifo_o_dat", 33),
            "fifo_ready": ("u_e203_ifetch_rsp_bypbuf.fifo_i_rdy", 1),
        }
        for label in ("idle", "1st", "wait2nd", "2nd"):
            internal[f"exit_{label}"] = (f"state_{label}_exit_ena", 1)
        external.update({name: ("e203_ifu_ift2icb." + path, width)
                         for name, (path, width) in internal.items()})
        super().__init__(dut, prefix="e203_ifu_ift2icb_top.", signals=external)
        self.memory = memory
        self.checks = ScenarioChecks(RULES, run_metadata={
            "test": os.environ.get("PYTEST_CURRENT_TEST", "e203-campaign"),
            "seed": seed, "data_pattern": data_pattern,
        }, contract="e203.internal-drive-stable-to-rising/v1")
        self.checks.implemented = set(RULES)
        self.previous_cross = False
        self.previous_pc = None
        self.current = None
        self.queue = deque()
        self.wait_streak = 0
        self.buffer_stall = 0
        self.drain_pending = None
        self.offset_written = False
        self.left_written = False
        self.last_running = None

    def observe(self, p, q, tick):
        context = {"state_before": p["state"], "state_after": q["state"],
                   "pc": p["pc"], "last_pc": p["last_pc"]}

        def check(name, scenario, actual, expected, **detail):
            self.checks.check("E203-INT-" + name, scenario, actual=actual,
                              expected=expected, tick=tick, context={**context, **detail})

        if not p["rst"]:
            previous = self.last_running or p
            scenario = ("buffered_reset" if previous["fifo_full"] else
                        "inflight_reset" if previous["state"] else "idle_reset")
            keys = ("state", "need0_r", "need2_r", "held_cross_r", "cross_r",
                    "route_itcm", "route_biu", "left_err", "fifo_full")
            check("RESET-CONTROL", scenario, tuple(q[k] for k in keys), (0,) * len(keys))
            self.previous_cross = False
            self.previous_pc = self.current = None
            self.queue.clear()
            self.wait_streak = self.buffer_stall = 0
            self.drain_pending = None
            self.offset_written = self.left_written = False
            self.last_running = None
            return

        request = bool(p["req_v"] and p["req_r"])
        command = bool(p["cmd_v"] and p["cmd_r"])
        response = bool(p["rsp_v"] and p["rsp_r"])
        internal = bool(p["int_v"] and p["int_r"])
        output = bool(p["out_v"] and p["out_r"])
        state = p["state"]
        state_names = ("IDLE", "1ST", "WAIT2ND", "2ND")
        exits = (request if state == 0 else response if state == 1 and p["need2_r"] else
                 internal if state in (1, 3) else bool(p["cmd_r"]))
        expected_state = state
        if exits:
            expected_state = (1 if state == 0 or (state in (1, 3) and request) else
                              (3 if p["cmd_r"] else 2) if state == 1 and p["need2_r"] else
                              3 if state == 2 else 0)
        actual_exit = tuple(p["exit_" + name] for name in ("idle", "1st", "wait2nd", "2nd"))
        check("FSM-EXIT-ONEHOT", state_names[state], actual_exit,
              tuple(int(exits and index == state) for index in range(4)))
        if request and internal:
            check("FSM-EXIT-ONEHOT", "handoff", (q["state"], p["state_enable"]), (1, 1))
        if not exits:
            check("FSM-NO-EXIT", state_names[state], (q["state"], p["state_enable"]), (state, 0))
        elif state == 0:
            kind = "0uop" if p["need0"] else "2uop" if p["need2"] else "1uop"
            check("FSM-IDLE-FIRST", kind, q["state"], 1)
        elif state == 1 and p["need2_r"]:
            if expected_state == 2:
                target = "ITCM" if p["route_itcm"] else "BIU"
                check("FSM-FIRST-WAIT", target, q["state"], 2)
            else:
                switched = bool(p["route_itcm"]) != bool((p["addr"] & 0xffff0000) == (p["region"] & 0xffff0000))
                check("FSM-FIRST-SECOND", "region_switch" if switched else "same_target", q["state"], 3)
        elif state == 1:
            if request:
                old = "0" if p["need0_r"] else "1"
                new = "0" if p["need0"] else "2" if p["need2"] else "1"
                if old + "_to_" + new in RULES["E203-INT-FSM-FIRST-FIRST"].scenarios:
                    check("FSM-FIRST-FIRST", old + "_to_" + new, q["state"], 1)
                if self.current and self.current["target"] != self._target(p["pc"], p["region"]):
                    check("FSM-FIRST-FIRST", "target_change", q["state"], 1)
            else:
                check("FSM-FIRST-IDLE", "0uop" if p["need0_r"] else "1uop", q["state"], 0)
        elif state == 2:
            check("FSM-WAIT-SECOND", self._target(p["addr"], p["region"]), q["state"], 3)
        else:
            if request:
                kind = "new_0uop" if p["need0"] else "new_2uop" if p["need2"] else "new_1uop"
                check("FSM-SECOND-FIRST", kind, q["state"], 1)
            else:
                check("FSM-SECOND-IDLE", "error" if p["int_err"] else "ok", q["state"], 0)

        if state == 2 and not p["cmd_r"]:
            self.wait_streak += 1
            held = tuple(q[k] for k in ("state", "left", "left_err", "offset", "need2_r"))
            expected = tuple(p[k] for k in ("state", "left", "left_err", "offset", "need2_r"))
            if self.wait_streak >= 2:
                check("FSM-WAIT-HOLD", "two_cycle_stall", held, expected)
            if self.wait_streak >= 3:
                check("FSM-WAIT-HOLD", "long_stall", held, expected)
        else:
            self.wait_streak = 0

        # Classify requests using lane byte positions and accepted fetch history.
        target = self._target(p["pc"], p["region"])
        lane_bytes = 8 if target == "ITCM" else 4
        offset = p["pc"] % lane_bytes
        begin, cross = offset == 0, offset == lane_bytes - 2
        same = bool(p["seq"]) and (self.previous_cross if begin else True)
        held = target == "ITCM" and bool(p["holdup"]) and not p["nohold"]
        mode = "held_cross" if cross and same and held else (
            "split" if cross else "zero" if same and held else "plain")
        flags = (int(mode == "zero"), int(mode == "split"), int(mode == "held_cross"), int(cross))
        if p["req_v"]:
            check("LANE-CLASSIFY", f'{target}:{offset // 2:02b}' if target == "ITCM" else f'BIU:{offset // 2}',
                  (p["begin"], p["cross"]), (int(begin), int(cross)))
            if not p["seq"]:
                check("LANE-SAME-NONSEQ", "begin" if begin else "cross" if cross else "middle", p["same"], 0)
            elif begin:
                check("LANE-SAME-BEGIN", f'previous_cross={int(self.previous_cross)}', p["same"], int(same))
            else:
                check("LANE-SAME-MIDDLE", "cross" if cross else "middle", p["same"], 1)
            gate = ("BIU" if target == "BIU" else "nohold" if p["nohold"] else
                    "holdup_low" if not p["holdup"] else "enabled")
            check("LANE-HOLD-GATE", gate, p["held"], int(held))
            zero_case = "not_same" if not same else "cross" if cross else "not_held" if not held else "eligible"
            check("LANE-UOP-ZERO", zero_case, p["need0"], flags[0])
            two_case = "not_cross" if not cross else "same_unheld" if same and not held else "different_lane" if not same else None
            if two_case:
                check("LANE-UOP-TWO", two_case, p["need2"], flags[1])
            if mode == "held_cross":
                check("LANE-UOP-HELD-CROSS", "held_cross", (p["held_cross"], p["need0"], p["need2"]), (1, 0, 0))
        keys = ("need0_r", "need2_r", "held_cross_r", "cross_r")
        if request or p["req_v"]:
            check("CTX-REQ-LOAD", "accepted_input" if request else "stalled_input",
                  tuple(q[k] for k in keys), flags if request else tuple(p[k] for k in keys))
        if request and internal:
            check("CTX-REQ-LOAD", "handoff", tuple(q[k] for k in keys), flags)

        # Admission follows transaction completion, independently of downstream
        # command readiness. The latter is verified as a separate route gate.
        admission = state == 0 or (state == 1 and not p["need2_r"] and internal) or (state == 3 and internal)
        admission_case = ("IDLE" if state == 0 else "WAIT2ND" if state == 2 else
                          "1ST_nonfinal" if state == 1 and p["need2_r"] else
                          "1ST_final" if state == 1 and internal else "2ND_final" if state == 3 and internal else None)
        if admission_case:
            check("ADDRESS-NEW-ADMISSION", admission_case, (p["admission"], p["req_r"]),
                  (int(admission), int(admission and p["cmd_r"])))
        selected = self._target(p["addr"], p["region"])
        ready = p[("itcm" if selected == "ITCM" else "biu") + "_cmd_ready"]
        if p["itcm_cmd_ready"] != p["biu_cmd_ready"]:
            check("ADDRESS-READY-ROUTE", "ITCM_ready_only" if p["itcm_cmd_ready"] else "BIU_ready_only", p["cmd_r"], ready)
        if p["req_v"] and mode == "zero" and not ready:
            check("ADDRESS-READY-ROUTE", "zero_uop_target_blocked", (p["req_r"], p["cmd_v"]), (0, 0))

        if p["cmd_v"]:
            second = state == 2 or (state == 1 and p["need2_r"])
            pc = self.current["pc"] if second and self.current else p["pc"]
            expected_address = (pc + (2 if second or mode == "held_cross" else 0)) & 0xffffffff
            if second or mode == "held_cross":
                delta = (expected_address - p["last_pc"]) & 0xffffffff
                if delta in (2, 4, 6):
                    check("ADDRESS-NEXT-OFFSET", f"+{delta}", p["addr"], expected_address)
                if expected_address < pc:
                    check("ADDRESS-NEXT-OFFSET", "overflow", p["addr"], expected_address)
            else:
                check("ADDRESS-CURRENT", "split_first" if mode == "split" else "ordinary", p["addr"], expected_address)
            dispatch_case = "region_cross" if second and self.current and selected != self.current["target"] else selected
            check("ADDRESS-DISPATCH-EXCLUSIVE", dispatch_case,
                  (p["itcm_cmd_valid"], p["biu_cmd_valid"], p["itcm_cmd_addr"] if selected == "ITCM" else p["biu_cmd_addr"]),
                  (int(selected == "ITCM"), int(selected == "BIU"), expected_address & (0xffff if selected == "ITCM" else 0xffffffff)))
        if state == 2 or state == 1 and p["need2_r"]:
            case = "WAIT2ND" if state == 2 else "direct" if response else "first_response_absent"
            check("ADDRESS-SECOND-CMD-ENABLE", case, p["cmd_v"], int(state == 2 or response))
        if command:
            route = (int(selected == "ITCM"), int(selected == "BIU"))
            old_route = (p["route_itcm"], p["route_biu"])
            if old_route == (1, 0) and route == (0, 1):
                check("CTX-ROUTE-LATCH", "ITCM_to_BIU", (q["route_itcm"], q["route_biu"]), route)
            elif old_route == (0, 1) and route == (1, 0):
                check("CTX-ROUTE-LATCH", "BIU_to_ITCM", (q["route_itcm"], q["route_biu"]), route)
        else:
            check("CTX-ROUTE-LATCH", "no_accept", (q["route_itcm"], q["route_biu"]), (p["route_itcm"], p["route_biu"]))
        if command or request:
            self.offset_written = True
            if request and mode == "zero":
                check("CTX-OFFSET-ZERO", f'offset_{p["pc"] & 6}', q["offset"], (p["pc"] >> 1) & 3)
        elif state in (1, 3) or p["cmd_v"]:
            check("CTX-OFFSET-HOLD", "stalled_command" if p["cmd_v"] else "waiting_response", q["offset"], p["offset"])
        if request and p["seq"] and self.previous_pc is not None:
            check("CTX-LAST-PC-PHASE", "+4" if p["rv32"] else "+2", p["last_pc"], self.previous_pc)
        if p["cmd_v"] and (state == 2 or state == 1 and p["need2_r"]) and self.current:
            check("CTX-LAST-PC-PHASE", "two_uop", p["last_pc"], self.current["pc"])

        held_load = request and mode == "held_cross"
        first_load = state == 1 and bool(p["need2_r"]) and response
        if held_load or first_load:
            self.left_written = True
            pc = p["pc"] if held_load else self.current["pc"]
            if held_load:
                check("LEFTOVER-HELD-LOAD", "accepted", q["left"], self.memory.read(pc, 2))
                if p["left_err"]:
                    check("LEFTOVER-ERROR-CLEAR-HELD", "error_to_held_ok", q["left_err"], 0,
                          old_error=p["left_err"], new_error=q["left_err"])
            else:
                route = "ITCM" if p["route_itcm"] else "BIU"
                check("LEFTOVER-FIRST-LOAD", route, q["left"], self.memory.read(pc, 2))
                check("LEFTOVER-ERROR-CAPTURE", route + ("_error" if p["rsp_err"] else "_ok"), q["left_err"], p["rsp_err"])
        else:
            if p["req_v"] and mode == "held_cross" and not request:
                check("LEFTOVER-HELD-LOAD", "blocked", (q["left"], q["left_err"]), (p["left"], p["left_err"]))
            if state == 2 or state == 3 and not response:
                check("LEFTOVER-DATA-HOLD", "WAIT2ND" if state == 2 else "2ND_no_response", q["left"], p["left"])
            check("LEFTOVER-ERROR-HOLD", f'stored_{p["left_err"]}', q["left_err"], p["left_err"])

        if first_load:
            check("DATAPATH-FIRST-SUPPRESS", "consumer_ready" if p["out_r"] else "consumer_stalled",
                  (p["to_left"], p["rsp_r"], p["int_v"]), (1, 1, 0))
        if p["int_v"] and self.current:
            expected_instruction = self.memory.instruction(self.current["pc"])
            path = "split_2ND" if state == 3 else "held_cross_1ST" if self.current["mode"] == "held_cross" else "ordinary_1ST"
            check("DATAPATH-LEFTOVER-SELECT", path, (p["assembled"], p["int_data"]),
                  (int(path != "ordinary_1ST"), expected_instruction))
            if p["route_itcm"] and not p["assembled"]:
                check("DATAPATH-ALIGN-ITCM", f'offset_{self.current["pc"] & 6}', p["int_data"], expected_instruction)
            expected_error = bool(p["rsp_err"] or (p["assembled"] and p["left_err"]))
            check("DATAPATH-ERROR-MUX", "assembled" if p["assembled"] else "ordinary_error" if p["rsp_err"] else "ordinary_ok", p["int_err"], int(expected_error))
            route = "ITCM_selected" if p["route_itcm"] else "BIU_selected"
            unselected = "biu" if p["route_itcm"] else "itcm"
            if p[unselected + "_rsp_valid"]:
                check("DATAPATH-UNSELECTED-RESPONSE", route,
                      p["rsp_v"], p["itcm_rsp_valid"] if p["route_itcm"] else p["biu_rsp_valid"])
            use = "first_split" if state == 3 else "first_held_after_legal_fill" if p["assembled"] else "first_plain"
            check("RESET-UNRESET-DATA", use, bool(self.offset_written and (self.left_written or not p["assembled"])), True)
            if p["need0_r"]:
                # A same-edge successor may issue its own command while the
                # old zero-uop fetch completes. Attribute it to the successor.
                successor_command = p["req_v"] and admission and mode != "zero"
                check("DATAPATH-ZERO-RESPONSE", "buffer_full" if p["fifo_full"] else "buffer_empty",
                      (p["fake"], p["cmd_v"]), (1, int(successor_command)))

        # Independent queue of internal accepts vs external deliveries.
        assert len(self.queue) == p["fifo_full"], "response occupancy differs from accepted-event ledger"
        old_data = self.queue[0] if self.queue else None
        incoming = (p["int_data"], p["int_err"])
        if p["fifo_full"]:
            check("BUFFER-FULL-CUT-READY", "full_popping" if output else "full_stalled", p["fifo_ready"], 0)
            if incoming[0] != old_data[0] and p["int_v"]:
                check("BUFFER-PRIORITY", "distinct_data", (p["out_data"], p["out_err"]), old_data)
            if incoming[1] != old_data[1] and p["int_v"]:
                check("BUFFER-PRIORITY", "different_err", (p["out_data"], p["out_err"]), old_data)
        elif p["int_v"] and p["out_r"]:
            check("BUFFER-BYPASS", "error" if p["int_err"] else "ok", (p["out_data"], p["out_err"]), incoming)
        if internal:
            self.queue.append(incoming)
            if not output:
                self.buffer_stall = 1
        if output:
            if not self.queue:
                raise AssertionError("IFU output has no corresponding internal acceptance")
            expected = self.queue.popleft()
            if old_data is not None:
                duration = self.buffer_stall
                check("BUFFER-CAPTURE", "long_stall" if duration > 1 else "one_cycle_stall", (p["out_data"], p["out_err"]), expected,
                      stalled_cycles=duration)
                self.drain_pending = "after_long_stall" if duration > 1 else "after_short_stall"
                self.buffer_stall = 0
        elif old_data is not None:
            self.buffer_stall += 1
        if self.drain_pending and not p["int_v"] and not p["out_v"]:
            check("BUFFER-DRAIN", self.drain_pending, q["fifo_full"], 0)
            self.drain_pending = None
        assert len(self.queue) == q["fifo_full"], "response buffer commit differs from accepted-event ledger"

        if request:
            self.current = {"pc": p["pc"], "mode": mode, "target": target}
            self.previous_pc = p["pc"]
            self.previous_cross = cross
        self.last_running = q

    @staticmethod
    def _target(pc, region):
        return "ITCM" if pc & 0xffff0000 == region & 0xffff0000 else "BIU"
