# Functional coverage 性能与统一报告

## 1. “不影响性能”的准确含义

Functional coverage 不可能是零 CPU 成本。框架保证的是隔离和可量化，而不是声称免费：

- 只对 monitor/reference model 已完成的 immutable transaction 采样，不在每个 XClock
  half-step 或 native trigger evaluation 中采样；
- schema finalization 预编译 source path、exact-bin lookup 和 cross eligible set；
- `sample(..., details=False)` 不构造逐次 `CoverageSample` 诊断视图，但保留 counter、gate、
  illegal-bin 和原子提交语义；
- JSON、LCOV 解析和 HTML 渲染全部在仿真结束后执行；
- coverage 可以针对性能专项显式关闭，并通过相同 workload 的 on/off A/B 门槛防回退。

因此，coverage 不增加仿真空转或背压周期的 Python/C++ 往返，但完成一笔 transaction 时
仍会消耗 Python CPU。若项目要求小于 1% 的总开销，应根据 profile 将 matcher/counter
下沉到 native compiled evaluator；不能用异步队列隐藏总 CPU 成本。

## 2. 当前测量结果

环境为 Python 3.12.3、当前机器；数字用于本版本基线，不是跨机器常量。

`benchmark_coverage.py` 的 6 coverpoint、3 cross、5×50,000 transaction 中位数：

| 模式 | 每事务成本 | 吞吐 |
|---|---:|---:|
| transaction 字段访问基线 | 约 82 ns | 约 12.2 M/s |
| `details=False` | 约 35.3 μs | 约 28.3 K/s |
| 返回逐次 details | 约 37.1 μs | 约 27.0 K/s |

真实 e203 memory-direct A/B 使用相同 Verilator coverage instrumentation、相同 seed、每轮
510 transaction，并交替 on/off 顺序运行 9 轮：

| 模式 | elapsed 中位数 |
|---|---:|
| functional sampling 关闭 | 0.9853 s |
| functional sampling 开启 | 1.0377 s |
| slowdown | 5.32% |

运行与设置项目门槛：

```bash
PYTHONPATH=src \
  python3 benchmarks/benchmark_coverage.py \
  --iterations 100000 --repeats 5 --json --max-fast-ns 50000

PYTHONPATH=src:../build/dependence/xcomm/python:examples/integration/e203 \
  python3 examples/integration/e203/benchmark_coverage.py \
  --dut-dir ../output/xreactor_e203 --random-count 500 --repeats 9 \
  --max-slowdown-percent 10 --json
```

绝对纳秒门槛只适合固定 runner；真实 DUT 的相对 A/B 门槛更能抵抗机器差异。性能 benchmark
应报告所有原始样本和中位数，不应只保存最好一次。

## 3. 统一覆盖率数据边界

统一报告不直接解析各 simulator 的私有数据库。边界是：

```text
XReactor functional JSON ─┐
                          ├─ normalized report model ─ HTML template
simulator ─ LCOV trace ───┘
```

Verilator 使用 `verilator_coverage --write-info` 产生 LCOV。其他 simulator 或转换工具只要
输出合法 LCOV `SF/DA/LF/LH` 记录，就复用同一个 parser；一个报告可以重复传入多个带标签
的 LCOV 文件。这样 simulator adapter 只负责格式转换，HTML 不依赖 Verilator。

Functional coverage 与 RTL line coverage 在页面中并排显示，但不相加、不平均。二者分母和
验证含义不同，制造“统一总分”会掩盖未覆盖的功能 bin 或 RTL 行。

## 4. HTML 生成

推荐输出是多页静态站点：

```text
coverage-report/
├── index.html
├── functional/
│   ├── index.html
│   └── groups/<instance>/
│       ├── index.html
│       ├── points/<point>.html
│       └── crosses/<cross>.html
└── line/<provider>/
    ├── index.html
    └── <source directories>/<file>.gcov.html
```

Functional item 页提供 bin kind、hit count、`at_least`、covered 状态、matcher/cross
definition，以及 samples/gated/ignored/unmatched。Line provider 使用 LCOV `genhtml`
生成源目录、文件和逐行源码视图，支持行命中次数、命中着色以及首个/下一个未命中导航。
Covergroup、coverpoint 和 cross 的 `description` 会分别出现在目录表、group 概览和 item
详情页，使报告同时回答“覆盖了多少”和“为什么要覆盖这个场景”。描述按纯文本转义显示。

```bash
xreactor-coverage-report \
  --functional output/e203-verification/functional-coverage.json \
  --line-coverage Verilator=output/e203-verification/line-coverage.info \
  --site output/e203-verification/coverage-report \
  --title "e203 IFU-to-ICB Coverage"
```

多页模式需要 LCOV 的 `genhtml`。输出目录只能在为空，或带有 XReactor site marker 时写入；
这避免把用户的任意非空目录当成生成目录清空。

原有单文件模式继续保留。默认模板是
`src/xreactor/templates/unified_coverage.html`，输出为一个自包含文件：

- 无 CDN、JavaScript package 或运行时服务器依赖；
- covergroup、point、cross、bin count 和 illegal hit；
- 每个 LCOV provider 的总行覆盖率；
- 每个源文件的 hit/found 和压缩后的未覆盖行范围；
- 深色、窄屏和打印样式；
- JSON 中的 `<`/`>` 被转义，DOM 内容只通过 `textContent` 写入。

单文件命令行：

```bash
xreactor-coverage-report \
  --functional output/e203-verification/functional-coverage.json \
  --line-coverage Verilator=output/e203-verification/line-coverage.info \
  --output output/e203-verification/coverage-report.html \
  --title "e203 IFU-to-ICB Coverage"
```

未安装 console script 时可使用：

```bash
PYTHONPATH=src python3 -m xreactor.coverage_report ...
```

`--functional` 和 `--line-coverage` 都可重复；functional shard 按 schema digest/instance
合并，line coverage 按 provider 独立展示。也可通过
`generate_unified_coverage_site()`、`generate_unified_coverage_report()` 或
`render_unified_coverage_html()` 嵌入 pytest。`--output` 和 `--site` 可以在一次命令中同时使用。

## 5. e203 报告带来的解释改进

当前 e203 总 RTL line coverage 为 198/300（66.0%），但按文件展开后：

- 目标 RTL `e203_ifu_ift2icb.v`：106/110（96.36%）；
- 自动生成 top wrapper：29/127（22.83%）；
- 三个通用支持模块：全部命中。

所以 66% 不是目标 IFU 模块本身只有 66%。统一报告保留总览，同时让 wrapper 与目标 RTL
可区分；后续可在 normalized model 上增加 include/exclude policy，但原始数据不应丢失。
