# Tool Calling、ReAct 与代码实践实施 Checklist

> **版本**: 1.0
> **状态**: active
> **更新日期**: 2026-08-15

**关联计划**: [implementation.md](./implementation.md)

## Phase 1: 工具 Schema、练习契约与动态注册表

- [x] 1.1 定义代码练习、测试结果、错误、提示和工具轨迹 Schema
- [x] 1.2 实现确定性 Python 练习生成器
- [x] 1.3 实现 LangChain Tool 与阶段感知注册表

## Phase 2: 受限执行器与有界 ReAct

- [x] 2.1 实现 AST 策略与执行前校验
- [x] 2.2 实现临时目录子进程测试执行器
- [x] 2.3 实现有界 ReAct 控制器和调用轨迹

## Phase 3: 错误分类、评分与三级提示

- [x] 3.1 分类语法、策略、超时、资源、运行时和断言错误
- [x] 3.2 实现确定性评分与三级提示

## Phase 4: LangGraph、SSE 与 Web 集成

- [x] 4.1 把代码练习接入练习生成、interrupt 与评价节点
- [x] 4.2 接入 State、会话 API 和 SSE 事件
- [x] 4.3 实现 Web 代码输入和测试/提示展示

## Phase 5: 公开文档、完整验证与公众号文章

- [ ] 5.1 更新 README 与项目边界
- [ ] 5.2 完成全量回归、文档生命周期同步与交付复盘
- [ ] 5.3 生成并视觉检查第 08 篇公众号文章
