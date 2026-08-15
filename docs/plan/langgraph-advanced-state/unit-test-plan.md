# LangGraph 状态图进阶单元测试计划

> **版本**: 1.0
> **状态**: draft
> **更新日期**: 2026-08-15

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 测试原则

- 全部使用 fake/stub 模型与注入的零间隔重试策略，不调用真实模型 API。
- 断言聚焦行为契约：并行事件存在性不依赖顺序，重试与缓存断言调用次数。
- 每个循环、重试与缓存能力都覆盖成功、失败与上限三类边界。

## Phase 1: Reducer、并行分支与 Command 导航

- `merge_recent_errors`：增量合并、去重、跳过"暂无"标记、保留最近 3 条。
- `append_learning_events`：并行拼接、超过 30 条时只保留最新。
- `LearningEvent` Schema：拒绝未知字段，字段有界。
- `prepare_practice`：代码主题生成练习与轨迹，文本主题只记录类型，零预算回退文本。
- `make_quiz`：优先使用已准备练习；未准备时直调仍可自生成；文本路径不变。
- 图级：诊断回答后两个分支并行执行且事件都进入 `learning_events`。
- `assess`：返回 `Command` 的 update 增量与 goto 方向；`route_after_assessment` 原断言不变。

## Phase 2: 节点级 Retry 与瞬态错误分类

- `is_transient_model_error`：超时/连接错误与白名单类名为瞬态；`ValueError` 与图冒泡异常不是。
- 瞬态错误第一次失败、第二次成功：节点重试后会话完成，调用次数为 2。
- 非瞬态错误：只尝试一次即上抛。
- 默认策略上限：持续瞬态失败时不超过 max_attempts 次尝试。

## Phase 3: 节点级 Cache

- 相同主题与题图的两个线程：诊断模型只调用一次，两次结果一致。
- 不同主题：各自调用。
- `enable_node_cache=False`：不再复用。
- 缓存键：包含主题与图片内容，图片变化时键不同。

## Phase 4: 循环终止验证与 Web 集成

- 三个循环边界：达到阈值、未达阈值且可重试、用完次数。
- 并行 fan-out 下的 interrupt 恢复：诊断与练习两次暂停、同一 thread_id 恢复。
- Web SessionView 返回 `learning_events` 与 `practice_kind`，隐藏测试仍不下发。

## Phase 5: 公开文档与回归

- README 契约关键词条目。
- 全量测试套件通过。
