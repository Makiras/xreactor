# M0 调度性能基线

可重复脚本位于 `benchmarks/benchmark_runtime.py`。以下结果用于证明
benchmark 闭环可运行，不代表真实 DUT/simulator 吞吐。

环境：Linux 6.8 x86_64、Python 3.12.3、xcomm Release/LTO 构建、no-op XClock
callback、无 waveform/coverage；每项 20,000 half-step，重复 3 次取中位数。

| case | half-step/s |
| --- | ---: |
| raw Step 单次跨语言调用 | 1,078,875 |
| Python 逐次 StepHalf | 1,204,192 |
| RunUntil 无 watcher | 2,472,306 |
| RunUntil + Value | 2,380,834 |
| RunUntil + Expr | 2,209,464 |
| RunUntil + FSM | 2,194,889 |
| pytrigger 每 rising sample | 133,903 |
| 每周期 XReactor/Future/Task 恢复 | 37,646 |

比较 revision 时必须使用相同构建选项、host load、tick/repeat 参数和 DUT 配置，
并保存脚本 `--json` 输出中的全部原始样本。真实 simulator 接入后需另建包含 DUT
eval、waveform、coverage 和 HTTP p50/p99 的基线，不能与本表混用。

## Cache 验证后的 200k half-step 复测

加入 `drive_ready_valid()` 后，以同一 no-op XClock、200,000 half-step、重复 3 次取
中位数复测：

| case | half-step/s |
| --- | ---: |
| raw Step 单次跨语言调用 | 1,101,803 |
| Python 逐次 StepHalf | 1,241,001 |
| RunUntil 无 watcher | 2,594,670 |
| RunUntil + Value | 2,455,818 |
| RunUntil + Expr | 2,266,824 |
| RunUntil + FSM | 2,267,189 |
| pytrigger 每 rising sample | 128,210 |
| 每周期 XReactor/Future/Task 恢复 | 36,348 |

这组结果不是不同机器间的性能承诺，但能支持三个实现判断：

- native Value 相对无 watcher 开销约 5.4%，Expr/FSM 约 12.6%；
- pytrigger 每 sample 比 native Expr 慢约 17.7 倍；
- 每周期恢复 Python Future 比 native Expr 慢约 62 倍。

因此 `drive_ready_valid()` 在 ready 为低时使用 native
`Value(ready, 1, sample=DriveStable(clock))` 等待，只在 drive、ready 命中和最终
accept 边界恢复 Python。它不应退化成逐 Rising/Falling 的 Python polling loop。
