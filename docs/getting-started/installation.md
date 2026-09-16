# 安装

XReactor 需要 Python 3.11 或更高版本。

## 安装 Python 包

从源码安装：

```bash
python3 -m pip install .
```

开发环境：

```bash
python3 -m pip install -e '.[test]'
python3 -m pytest -q
```

## xcomm

使用 `XCommClockBackend` 还需要安装 xcomm/xspcomm Python binding。该 binding 必须
提供以下接口：

- `XClock.StepHalf`；
- `XData`；
- `XTriggerEngine`。

如果 binding 没有安装到 Python 环境，可将其所在目录加入 `PYTHONPATH`：

```bash
export PYTHONPATH="/path/to/xspcomm/python:$PYTHONPATH"
```

## 检查安装

```bash
python3 -c 'import xreactor; print(xreactor.__name__)'
```

运行不依赖仿真器的示例：

```bash
PYTHONPATH=src python3 examples/triggers/basic_execution.py
```
