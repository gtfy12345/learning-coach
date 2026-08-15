# 多 Agent 与任务编排单元测试计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-15

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 测试原则

- 全部使用 fake/stub 模型与本地离线检索，不调用真实模型 API。
- worker 数量、修订次数与教师调用次数必须可数，断言聚焦行为契约。
- 覆盖成功、失败（审查未通过）、终止（预算耗尽）三类边界。

## Phase 1: Agent 契约与编排计划

- TeachingPlan Schema：焦点/维度上限、revision_budget 边界、未知字段拒绝。
- build_teaching_plan：无资料跳过研究；焦点来自诊断重点与最近错误并去重；维度随掌握度带变化。
- 审查规则：grounding 有/无证据、clarity 长度边界、alignment 有/无缺口；轮次标记正确。
- Reducer：teaching_reviews 上限 9、agent_handoffs 上限 20。

## Phase 2: 教学 Swarm 子图

- 无资料主题：跳过研究 worker，handoffs 直接 orchestrator→teach。
- 有资料主题：worker 数等于焦点数，证据去重合并 ≤ 3 来源，教师任务输入包含 prepared_retrieval。
- 审查未通过：审查意见进入反馈，教师被再次调用；第二轮通过后接受。
- 持续未通过：教师恰好调用 2 次后带意见接受，子图终止。
- 事件流：teaching started/completed 与 token 事件仍从子图内部发出。

## Phase 3: 主图接入

- 完整会话：诊断/练习 interrupt 不变，补救循环重入 swarm，父图 learning_events 无重复。
- 代码实践与零预算路径保持。
- swarm 节点挂接瞬态重试策略。

## Phase 4: Web 集成

- SessionView 返回 teaching_plan、teaching_reviews、agent_handoffs 与研究摘要。
- 页面渲染 Agent 轨迹文本（安全 DOM API）。

## Phase 5: 公开文档与回归

- README 契约关键词。
- 全量测试套件通过。
