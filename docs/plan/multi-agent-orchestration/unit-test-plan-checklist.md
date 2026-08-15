# 多 Agent 与任务编排单元测试 Checklist

> **版本**: 1.0
> **状态**: draft
> **更新日期**: 2026-08-15

**关联测试计划**: [unit-test-plan.md](./unit-test-plan.md)

## Phase 1: Agent 契约与编排计划

- [ ] 1.1 TeachingPlan/Handoff Schema 边界
- [ ] 1.2 build_teaching_plan 路由与焦点
- [ ] 1.3 三个审查维度规则
- [ ] 1.4 Reducer 上限

## Phase 2: 教学 Swarm 子图

- [ ] 2.1 无资料跳过研究
- [ ] 2.2 焦点 fan-out 与证据合并
- [ ] 2.3 修订一次后通过
- [ ] 2.4 持续未通过带意见接受
- [ ] 2.5 子图事件流

## Phase 3: 主图接入

- [ ] 3.1 完整会话与父图增量
- [ ] 3.2 代码实践与零预算路径
- [ ] 3.3 swarm 重试挂接

## Phase 4: Web 集成

- [ ] 4.1 SessionView 新字段
- [ ] 4.2 页面轨迹渲染

## Phase 5: 公开文档与回归

- [ ] 5.1 README 契约测试
- [ ] 5.2 全量回归通过
