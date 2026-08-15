# 记忆、暂停恢复与 Time Travel 单元测试计划

> **版本**: 1.0
> **状态**: draft
> **更新日期**: 2026-08-15

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 测试原则

- 全部使用 fake 模型与临时 SQLite 文件，不调用真实模型 API。
- 幂等、恢复与分叉行为必须有可数的断言（写入次数、线程状态、原线程不变）。
- 覆盖成功、拒绝/失败、崩溃重放三类边界。

## Phase 1: 持久化与记忆基础设施

- 环境解析：三种 env 的默认值、合法值与非法值。
- SqliteSaver/SqliteStore 构造与关闭行为。
- 记忆写入幂等：同一 thread 重放不产生重复条目；聚合画像正确。
- 召回摘要与 context_summary 注入行。

## Phase 2: 审批闸门与图接入

- 非代码路径不触发审批；零预算文本路径不变。
- 代码路径在审批中断暂停；批准后测试执行且报告正常。
- 拒绝后零执行：报告 status=rejected、passed=0、无进程输出，闭环继续。
- recall/remember 节点在无 Store 时为空操作。

## Phase 3: Time Travel

- 里程碑列表有界、脱敏且标签正确。
- 从练习作答前分叉：原线程状态不变；新线程重新等待作答；完成后状态可比较。
- compare_learning_states 输出安全字段差异。

## Phase 4: CLI 与 Web 集成

- CLI --thread-id 持久恢复（新进程继续 pending 中断）。
- Web 审批端点与审批流；历史/分叉端点返回结构；页面渲染。

## Phase 5: 公开文档与回归

- README 契约关键词。
- 全量测试套件通过。
