# XReactor examples

- `getting_started/`: a progressive accumulator tutorial, failure exercises and an optional native path;
- `triggers/`: execution, edges, sampled values, and compiled triggers;
- `coverage/`: covergroups, bins, crosses, and JSON output;
- `transactions/`: protocol-independent Driver/Scoreboard lifecycle and deadlines;
- `integration/`: DUT-specific verification environments.

Run the standalone examples from the project root:

```bash
PYTHONPATH=src python3 examples/triggers/basic_execution.py
PYTHONPATH=src python3 examples/coverage/functional_coverage.py
PYTHONPATH=src python3 examples/transactions/scoreboard.py
```

Integration environments list their own DUT and tool dependencies in their
README files.

真实 DUT 可从 [e203](integration/e203/README.md) 或 [Cache](integration/cache/README.md)
开始：两者都提供构建命令、定向场景、随机 seed 和产物说明。前者演示模型/Scoreboard、
pytest 执行结果与 RTL 行覆盖；后者演示项目 SyncDriver、Monitor、参考内存和读写/替换覆盖，
以及封装 probe/release 多拍接口的 CoherenceAgent。
Cache 独立 overlap 探针仍失败，不能把基础数据序列通过当成完整协议验证通过。

After installing `python3 -m pip install -e '.[test]'`, run the getting-started
test and subscription example:

```bash
python3 -m pytest -q examples/getting_started
python3 examples/triggers/subscription.py
```

With xspcomm importable, `python3 examples/getting_started/check_native.py`
prints the loaded binding path and advances a native clock without a DUT.
默认 pytest 命令包含完整入门教程及覆盖率运行配方；故意失败和 native 选读需显式执行。
入门文件顺序见 [getting_started/README](getting_started/README.md)，逐步解释见
[零基础教程](../docs/getting-started/index.md)。CI 另外执行文档中的 CLI 示例。

For continuous inputs, overlapping stages, and out-of-order responses:

```bash
python3 examples/transactions/pipeline.py
python3 examples/transactions/pipeline.py --backend native
python3 -m pytest -q tests/integration/test_pipeline_examples.py --require-xspcomm
```

The [pipeline guide](../docs/guides/pipeline-examples.md) explains each case and
its sampled timing. Native runs require xspcomm; default examples use MemoryBackend.
AsyncDriver `send()` immediately submits input and returns an acceptance handle;
`submit()` tracks a later response. The examples let the Driver own this work.
The `missing`, `late`, `wrong-fifo`, and `capacity` cases deliberately fail.

## Agent 与有状态 reference model

`transactions/reference_model.py` 定义 AccumulatorAgent 实例，封装输入 Driver、响应
Monitor 和检查接线，connect 独立累加器模型，由 Execution(agents=[agent]) 管理生命周期。
用例直接调用 agent.submit/finish；模型按接受顺序更新，响应按 tag 乱序匹配：

```bash
python3 -m examples.transactions.reference_model
python3 -m examples.transactions.reference_model --backend native
```

模型可独立单元测试，框架不推断初始化、reset 或跨接口状态顺序。

## 验证流程配方

`transactions/test_pipeline_coverage.py` 与 `transactions/verification_flow.py`
演示单消费者覆盖率接入、组件反向清理和失败时保存产物：

```bash
python3 -m pytest -q -s examples/transactions/test_pipeline_coverage.py
```

日常用例只操作 submit/finish；fixture 管 seed、输出目录及运行预算。
配方回归同时验证 MemoryBackend/native XClock，详见
[`tests/integration/test_verification_flow.py`](../tests/integration/test_verification_flow.py)。

按功能查找场景和回归入口：[功能索引](../docs/reference/feature-map.md)。
