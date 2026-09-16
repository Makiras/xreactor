# 示例

## Trigger

[basic_execution.py](https://github.com/Makiras/xreactor/blob/main/examples/triggers/basic_execution.py) 演示：

- `Execution`；
- `RisingEdge` 和 `FallingEdge`；
- `Value`；
- `@xtrigger`。

```bash
PYTHONPATH=src python3 examples/triggers/basic_execution.py
```

## Functional coverage

[functional_coverage.py](https://github.com/Makiras/xreactor/blob/main/examples/coverage/functional_coverage.py) 演示 coverpoint、bin、
cross、JSON 输出和覆盖率检查。

```bash
PYTHONPATH=src python3 examples/coverage/functional_coverage.py
```

`examples/integration/` 中保存真实 DUT 验证环境。每个环境的依赖和运行方式见其目录下
的 README。
