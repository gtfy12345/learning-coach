# GraphRAG 与知识前置图实施 Checklist

> **版本**: 1.0
> **状态**: active
> **更新日期**: 2026-08-15

**关联计划**: [implementation.md](./implementation.md)

## Phase 1: 图 Schema、实体关系抽取与消歧

- [x] 1.1 定义概念图、关系、路径和 GraphRAG 报告 Schema
- [x] 1.2 实现确定性实体与关系抽取器
- [x] 1.3 实现实体规范化、别名消歧与可注入模型增强

## Phase 2: 概念图构建与有界前置遍历

- [x] 2.1 构建稳定、去重、有界的会话级概念图
- [x] 2.2 实现查询种子识别与多级图遍历
- [x] 2.3 生成前置知识解释与证据链

## Phase 3: 图与 Hybrid RAG 融合

- [ ] 3.1 实现图证据排名和图/Hybrid RRF
- [ ] 3.2 实现 GraphStudyRetriever 与安全降级
- [ ] 3.3 接入兼容检索适配器和公共工厂

## Phase 4: LCEL、Middleware、State 与 Web 集成

- [ ] 4.1 把前置路径加入 LCEL 与 Agent 教学上下文
- [ ] 4.2 接入 LangGraph State、事件和 Web API
- [ ] 4.3 实现 Web 概念图与前置解释展示

## Phase 5: 文档、完整验证与公众号文章

- [ ] 5.1 更新 README 与公开能力边界
- [ ] 5.2 完成完整回归、静态验证、生命周期同步与复盘
- [ ] 5.3 生成并视觉检查第 07 篇公众号文章
