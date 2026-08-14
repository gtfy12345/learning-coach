# 自校正 Hybrid RAG 单元测试 Checklist

> **版本**: 1.0
> **状态**: active
> **更新日期**: 2026-08-14

**关联计划**: [unit-test-plan.md](./unit-test-plan.md)

## Phase 1: Embedding、配置与 Schema 测试

- [x] 1.1 本地 Embedding、缓存和资源边界测试
- [x] 1.2 Provider 配置、初始化和失败测试
- [x] 1.3 报告、分数与兼容 Schema 测试

## Phase 2: 召回、融合与重排测试

- [x] 2.1 BM25 中英文、IDF、无命中和排序测试
- [x] 2.2 Dense 相似度、维度、非有限值与降级测试
- [x] 2.3 RRF、重排、top_k 和稳定 tie-break 测试

## Phase 3: 自校正闭环测试

- [x] 3.1 证据质量正常与边界测试
- [x] 3.2 查询改写上下文、去重和长度测试
- [x] 3.3 首轮通过、二轮提升、二轮不足和终止测试

## Phase 4: 教学与 Web 集成测试

- [x] 4.1 LCEL、Middleware 与共享 Retriever 测试
- [x] 4.2 State、SSE、Web 报告和安全展示测试
- [x] 4.3 README、环境变量与公开边界测试

## Phase 5: 完整回归与文章验证

- [ ] 5.1 完整测试、编译、依赖、前端和差异检查
- [ ] 5.2 Checklist、Header/INDEX 和复盘验证
- [ ] 5.3 第 06 篇文章渲染与逐页视觉检查
