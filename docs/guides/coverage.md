# Functional coverage 与统一报告

Functional coverage 以 Monitor 产生的 transaction 为采样输入。

## 定义 covergroup

```python
from xreactor import Bin, CoverGroupDef, CoverPointDef, CrossDef

definition = CoverGroupDef(
    "fetch",
    (
        CoverPointDef(
            "target",
            {
                "local": Bin.values("local"),
                "external": Bin.values("external"),
            },
            description="Exercises both fetch routes.",
        ),
        CoverPointDef(
            "response",
            {
                "ok": Bin.values("ok"),
                "error": Bin.values("error"),
            },
            description="Exercises success and error responses.",
        ),
    ),
    (
        CrossDef(
            "target_x_response",
            ("target", "response"),
            description="Checks responses on every route.",
        ),
    ),
    description="End-to-end fetch coverage.",
)

coverage = definition.instantiate("core0.ifu")
coverage.sample(
    {"target": "local", "response": "ok"},
    metadata={"seed": 7, "tick": 42},
    details=False,
)
coverage.sample({"target": "local", "response": "error"})
coverage.sample({"target": "external", "response": "ok"})
coverage.sample({"target": "external", "response": "error"})
coverage.assert_coverage(100.0)
```

`details=False` 只更新计数器，不返回本次采样的 bin 命中明细。

## Bin 类型

```python
Bin.values(0, 1)
Bin.range(0, 15)
Bin.ranges((0, 3), (8, 11))
Bin.masked(value=0b1000, mask=0b1100, width=4)
Bin.array("bucket", 0, 255, count=16)
Bin.default()
Bin.ignore(Bin.values(7))
Bin.illegal(Bin.range(12, 15))
```

`at_least=N` 要求 bin 至少命中 N 次。`ignore` 不进入覆盖率分母；`illegal` 默认立即
抛出 `IllegalBinError`，也可以实例化时选择 record policy。定义中的 `description`
会进入 JSON 和 HTML 报告，不进入 sampling 热路径。

## 保存和合并

```python
from xreactor import CoverageDatabase

database = CoverageDatabase([coverage])
database.write_json("functional-coverage.json")

merged = CoverageDatabase.read_json("run-a.json")
merged.merge(CoverageDatabase.read_json("run-b.json"))
merged.write_json("merged.json")
```

只有兼容 schema digest 的同名实例才能安全合并。

## 统一 HTML 报告

Verilator coverage 先转换为 LCOV，其他能产生 LCOV 的 simulator 使用同一入口：

```bash
xreactor-coverage-report \
  --functional functional-coverage.json \
  --line-coverage Verilator=line-coverage.info \
  --site coverage-report
```

输出包含：

- functional covergroup/point/cross 分级页面；
- 每个 bin 的目标、命中次数和描述；
- genhtml 生成的逐文件、逐行 RTL coverage；
- functional 与 line coverage 的统一导航。

完整样例见
[functional_coverage.py](https://github.com/Makiras/xreactor/blob/main/examples/coverage/functional_coverage.py)。
