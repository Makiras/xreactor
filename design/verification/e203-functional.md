# e203 IFU-to-ICB 验证报告

## 范围

目标 RTL 是 `example/e203_ifu_ift2icb/e203_ifu_ift2icb.v`。它把 IFU fetch
转换成 ITCM 64-bit 或 BIU 32-bit ICB 访问，包含地址路由、跨 lane 拼接、0/1/2
command 优化、ITCM holding-data、三处背压、错误合并和 response bypass buffer。

验证环境位于 `examples/integration/e203/e203_xreactor_env.py`，使用 picker
memory-direct binding、真实 XClock 和 XReactor，不使用 MemoryBackend。

## 参考模型与 agent

`ByteMemory` 用地址确定性生成 byte；ICB agent 返回相应的 64-bit ITCM lane 或 32-bit
BIU lane。独立 `IfuReferenceModel` 预测：

- ITCM/BIU 目标；
- lane begin/middle/cross；
- 0/1/2 command 数量及地址；
- little-endian 32-bit instruction；
- 两个 uop 的 error OR。

DUT response 同时与 architectural data 和 command trace 比较，所以错误路由、重复访问、
漏访问，以及错误但碰巧返回相同数据都会失败。

测试平台采用中心化 cycle harness 驱动 IFU 和两个 ICB 接口，避免多个 asyncio agent 在
同一 falling-stable barrier 上争用组合输入；edge progression 仍全部由 XReactor 完成。

## 压力与错误路径

定向与 seeded random 序列覆盖：

- ITCM/BIU 普通和跨 lane fetch；
- ITCM 0-command、same-cross 1-command 和普通 2-command；
- `itcm_nohold`；
- command backpressure、response latency、IFU response backpressure；
- 第一个及第二个 uop error；
- output/ICB response 在背压下保持稳定；
- 慢响应和 wall timeout guard；
- 真实延迟 ICB response 触发事务级 simulation-cycle `TimeoutError`。

主 pytest 使用 `seed=0xE203` 和 500 个随机事务。额外运行了 8 个 seed、每个 250 个
随机事务的矩阵，共 2080 个事务，全部通过且每个 seed 都达到 100% functional coverage。

## Functional coverage

coverage 采样 reference model/scoreboard 使用的同一份不可变 `FetchTransaction`。9 个
point 和 4 个 cross 包含：

- target、alignment、sequential、holdup；
- command count 0/1/2；
- command/response backpressure；
- ok/error；
- fast/medium/slow latency；
- target×alignment、target×response、holdup×command count、双向背压组合。

不可能组合由显式 cross include 从分母排除，不要求随机测试覆盖不可达笛卡尔积。

## 实测结果

环境：Verilator 5.026、memory-direct、coverage enabled、Python 3.12。

| 指标 | 结果 |
|---|---:|
| pytest | 2 passed in 1.60s（含多页 HTML/genhtml 生成） |
| 总事务 | 510 |
| ICB command | 663 |
| half-tick | 7965 |
| functional coverage | 100% |
| RTL line coverage | 198 / 300 = 66.0% |
| throughput | 约 480～495 transactions/s |
| half-tick throughput | 约 7560～7730/s |

性能值是当前机器上包含 coverage 的基线，不是跨机器默认门槛。固定 CI 可通过
`E203_MIN_TRANSACTIONS_PER_SECOND` 设置阈值。

相同 seed、相同 Verilator instrumentation、每轮 510 transaction 的 functional
sampling on/off A/B 交替运行 9 轮：关闭中位数 0.9853s，开启中位数 1.0377s，slowdown
为 5.32%。`benchmark_coverage.py` 提供 `--max-slowdown-percent` CI 门槛。

pytest 输出 `functional-coverage.json`、`verilator-coverage.dat`、
`line-coverage.info/json`、`transactions.json`、`performance.json` 和自包含
`coverage-report.html`，以及推荐使用的多页 `coverage-report/index.html`。多页站点按
covergroup/point/cross 分页，并可从 Verilator 源码目录点击进入带逐行命中次数的 RTL。
报告按文件显示目标 RTL 106/110（96.36%），并揭示总计 66% 主要受到自动生成 top
wrapper 29/127 的影响。

## 参考模型带来的设计发现

初始压力测试在 sequential BIU crossing 中发现第二个 command 重复当前地址。原因是环境
把 `ifu_req_last_pc` 错当成直到 response 都保持不变的 request payload。真实契约是：

```text
request handshake 前：ifu_req_last_pc = previous pc_r
request handshake 后：ifu_req_last_pc = accepted current PC
```

same-cross-holdup command 在握手当拍消费旧值；two-uop 的第二个 command 随后消费新值。
修正 agent 和独立模型后，单 seed 与多 seed 压力均通过。

这说明 Bundle/Interface 不能仅因信号共享前缀就假设相同稳定周期。scoreboard/coverage
消费不可变 transaction snapshot；protocol agent 仍可能在事务中更新 live control state。

## 运行

```bash
examples/integration/e203/build_xreactor.sh
python3 -m pip install -e '.[test]'
examples/integration/e203/run_pytest.sh
```

构建默认 `BUILD_THREADS=0`，使用全部可用核心。
