# LangGraph 状态图进阶单元测试 Checklist

> **版本**: 1.0
> **状态**: active
> **更新日期**: 2026-08-15

**关联测试计划**: [unit-test-plan.md](./unit-test-plan.md)

## Phase 1: Reducer、并行分支与 Command 导航

- [x] 1.1 merge_recent_errors 合并、去重、标记与上限
- [x] 1.2 append_learning_events 拼接与 30 条上限
- [x] 1.3 LearningEvent Schema 边界
- [x] 1.4 prepare_practice 三种路径
- [x] 1.5 make_quiz fan-in 与直调兼容
- [x] 1.6 图级并行事件合并
- [x] 1.7 assess Command 方向与增量

## Phase 2: 节点级 Retry 与瞬态错误分类

- [x] 2.1 瞬态分类单元断言
- [x] 2.2 瞬态错误重试后成功
- [x] 2.3 非瞬态错误快速失败
- [x] 2.4 持续失败不超过尝试上限

## Phase 3: 节点级 Cache

- [x] 3.1 相同输入命中缓存
- [x] 3.2 不同输入不命中
- [x] 3.3 开关关闭后不复用
- [x] 3.4 缓存键覆盖主题与图片

## Phase 4: 循环终止验证与 Web 集成

- [ ] 4.1 三个循环边界
- [ ] 4.2 并行 fan-out 下的暂停恢复
- [ ] 4.3 Web 会话视图新字段

## Phase 5: 公开文档与回归

- [ ] 5.1 README 契约测试
- [ ] 5.2 全量回归通过
