# 协议 Driver 范围收敛

日期：2026-09-29。按用户要求，先移除独立 ReadyValidDriver；协议驱动应按提交方式
派生自 SyncDriver 或 AsyncDriver，复用通用并发、所有权和清理机制。

## 变更

- 删除仅包含 ReadyValidDriver 的 src/xreactor/drivers.py，移除顶层导入与导出；
  不保留旧入口，不增加替代公共协议类。
- 公共 Driver 类收敛为六个：Driver、SignalDriver、SyncDriver、AsyncDriver、
  SyncSingleCycleDriver、AsyncSingleCycleDriver。
- Cache 示例原有 CacheDriver 直接继承 SyncDriver，其 _drive_one 复用原来的
  drive_ready_valid 和 Bundle.drive。request 的发射调用改为 self.send，关闭时释放
  CacheDriver 自己持有的信号，不再创建内部独立协议 Driver。
- 原来依赖该类的单元与 native 集成测试改为测试内的 SyncDriver 协议子类，保留
  串行发送、ownership 冲突、native identity、Monitor 采样等既有检查。
- 用户指南、API 索引、架构和 roadmap 同步更新。历史真实 DUT 验证报告标明旧类
  已移除，保留原始测量日期与证据。

ReadyValid 结构、ReadyValidMonitor、底层 drive_ready_valid 函数均保留；该函数的
falling/rising 时序和取消处理未改变。资源锁接口和 Sync/Async 提交语义没有改动。

## 验证

```text
python3 -m pytest -q --require-xspcomm
311 passed in 1.23s

mkdocs build --strict
通过
```

全量回归包含 memory/native 协议、ownership 与监视器采样检查，没有删除旧用例来
规避被移除类的依赖。公共导出检查确认剩余六个 Driver 类，源码中没有旧类或导入。
git diff --check 通过。

另对 CacheDriver 实际迁移后的类执行 MemoryBackend 冒烟：两笔请求在 tick 2/4
各采样一次，接受事件正确，valid 撤销，Driver ownership 和 watcher 清理完成。
加载项目模块时仅为生成 DUT 的导入提供占位；未构造 RTL DUT，不将此检查称为真实
Cache 功能回归。本次未重新生成或运行 CacheSignalCFG RTL。
