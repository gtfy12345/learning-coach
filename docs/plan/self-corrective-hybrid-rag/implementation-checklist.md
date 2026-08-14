# 自校正 Hybrid RAG 实施 Checklist

> **版本**: 1.0
> **状态**: active
> **更新日期**: 2026-08-14

**关联计划**: [implementation.md](./implementation.md)

## Phase 1: Embedding、配置与公共契约

- [x] 1.1 定义 RAG Settings、Embedding 接口和本地哈希实现
- [x] 1.2 接入可选 LangChain Provider Embedding
- [x] 1.3 定义检索分数、尝试与报告 Schema

## Phase 2: 关键词、向量、融合与重排

- [x] 2.1 实现 BM25 关键词召回
- [x] 2.2 实现 Dense 召回与失败降级
- [x] 2.3 实现 RRF 融合与确定性二阶段重排

## Phase 3: 质量判断与查询改写闭环

- [x] 3.1 实现证据质量判断
- [x] 3.2 实现上下文感知查询改写
- [x] 3.3 实现最多两次的自校正检索编排

## Phase 4: LCEL、Middleware、State 与 Web 集成

- [x] 4.1 接入教学 Runnable 与 Agent 工具
- [x] 4.2 接入 LangGraph State、SSE 与 Web 展示
- [x] 4.3 同步 README、环境变量与兼容边界

## Phase 5: 完整验证、复盘与公众号文章

- [ ] 5.1 完成完整回归和静态验证
- [ ] 5.2 完成交付复盘与生命周期同步
- [ ] 5.3 生成并视觉检查第 06 篇公众号文章
