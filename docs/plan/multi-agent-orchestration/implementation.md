# 多 Agent 与任务编排实施计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-15

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

把讲解阶段升级为有界的多 Agent 编排子图，落地 Router、Send、Orchestrator-Worker、Subgraph 与 Handoff 五个模式，同时保持外层学习闭环、暂停恢复协议、预算语义与练习 Agent 行为完全不变。

## 2 背景

第 09 阶段让图可以在并行与失败下稳定运行，但"teach"节点内部仍然是一个单体育节点：检索、教学、质检混在同一个节点里，讲解质量没有独立把关，资料检索也只有一条固定查询。第 10 阶段把这一段拆成编排器加研究、教师、审查三个分工 Agent：研究按薄弱点并行取证，教师基于证据起草，审查按维度把关并最多触发一次修订。

## 3 实施步骤

### Phase 1: Agent 契约与编排计划

#### 1.1 定义计划、焦点、审查结论与交接 Schema

TeachingPlan、ResearchFocus、ReviewFinding、AgentHandoff、ResearchEvidence，全部 extra="forbid" 且有界。

#### 1.2 实现确定性编排计划与 Router

按资料、掌握度带、最近错误与知识缺口生成焦点与审查维度；无资料主题跳过研究。

#### 1.3 实现确定性审查规则

grounding / clarity / alignment 三个维度的离线检查与轮次标记。

### Phase 2: 教学 Swarm 子图

#### 2.1 实现 research_worker 与证据汇合

按 Send 焦点运行现有检索器，合并去重来源并构造 prepared_retrieval 移交教师。

#### 2.2 实现 teach_agent 与证据注入

复用 teach_stream；runnables 检索函数优先返回 prepared_retrieval，未注入时行为不变。

#### 2.3 实现 review fan-out 与有界修订 Handoff

按维度 Send 并行审查；revise_or_approve 只看当前轮结论，最多修订一次。

### Phase 3: 主图接入与端到端验证

#### 3.1 子图作为 teach 节点接入主图

受限 input/output schema、瞬态重试挂接、状态 teaching started/completed 事件保持。

#### 3.2 练习 Agent 交接与父图增量验证

prepare_practice 补记交接；验证父图事件通道无重复累加，interrupt 恢复与补救循环不变。

### Phase 4: Web 集成

#### 4.1 SessionView 暴露编排结果

teaching_plan、teaching_reviews、agent_handoffs 与研究证据摘要。

#### 4.2 页面展示 Agent 轨迹

在动态上下文面板显示焦点数、审查结论与交接次数，保持安全 DOM API。

### Phase 5: 公开文档、完整验证与公众号文章

#### 5.1 更新 README 与边界

新增多 Agent 章节、能力清单与边界条目；说明 worker 模型调用与终止保证。

#### 5.2 完成全量回归、文档生命周期同步与交付复盘

全量测试、编译、前端语法、计划上下文、索引与差异检查，并生成证据化复盘。

#### 5.3 生成并检查第 10 篇公众号文章

在 person 目录生成 Word 文章，包含 GitHub 完整地址、架构、关键实现、边界和下一阶段。

## 4 验收标准

- 编排计划随上下文变化且全程有界（焦点 ≤ 3、维度 ≤ 3、修订 ≤ 1）。
- Send fan-out 的 worker 数量由计划决定；并行写全部经 Reducer 合并且父图无重复。
- 首次审查未通过恰好修订一次；持续未通过在预算耗尽后接受，教师调用 ≤ 2 次。
- 完整会话、代码实践、零预算与非代码主题路径全部保持；全量测试通过。
- 第 10 篇文章与实现一致并包含 `https://github.com/gtfy12345/learning-coach`。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 子图终值经父图 Reducer 重复累加 | 受限 input/output schema 只回传增量，并用回归断言无重复 |
| 审查规则误判引发多余修订 | 规则宽松取向、修订预算 1，且修订后必定接受 |
| 证据注入破坏原教学行为 | prepared_retrieval 仅作为检索短路；未注入路径回归全覆盖 |
| worker 并行写冲突 | 共享写只保留 reviews/handoffs/events 三个 Reducer 通道 |
| 规模失控 | 不引入新依赖；Agent 均为现有组件的显式分工 |

## 6 关联文档

- [设计文档](../../spec/multi-agent-orchestration-design.md)
- [实施 Checklist](./implementation-checklist.md)
- [单元测试计划](./unit-test-plan.md)
- [上一阶段实施计划](../langgraph-advanced-state/implementation.md)
