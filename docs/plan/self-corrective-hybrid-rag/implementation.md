# 自校正 Hybrid RAG 实施计划

> **版本**: 1.0
> **状态**: active
> **更新日期**: 2026-08-14

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

在现有会话级多模态 Chunk 之上实现本地默认、Provider 可选的 Embedding，结合 BM25、Dense 召回、RRF 融合、确定性重排、质量判断和一次查询改写，形成可追溯且必然终止的教学检索闭环。

## 2 背景

第 5 阶段已经统一了 Loader、Splitter、Metadata、Hash 和增量索引，但检索仍依赖词面重叠。术语精确时效果稳定，表达改写或问题过短时容易漏召回，也无法解释检索是否足够、为什么重试。本阶段在不引入持久化数据库和默认外部费用的前提下补齐 Hybrid RAG。

## 3 实施步骤

### Phase 1: Embedding、配置与公共契约

#### 1.1 定义 RAG Settings、Embedding 接口和本地哈希实现

增加有界配置、本地确定性 Embedding、向量校验和文档向量缓存。

#### 1.2 接入可选 LangChain Provider Embedding

支持显式 `EMBEDDING_MODEL_ID=provider:model`，默认 `local:hash-v1`，初始化配置错误明确失败。

#### 1.3 定义检索分数、尝试与报告 Schema

扩展 `StudySource` 和 `GroundedTeaching` 的可选追溯字段，保持原接口兼容。

### Phase 2: 关键词、向量、融合与重排

#### 2.1 实现 BM25 关键词召回

基于现有中英文词元规则计算语料级 IDF、长度归一化和稳定排名。

#### 2.2 实现 Dense 召回与失败降级

批量缓存文档向量、计算查询余弦相似度，并在后端失败时保留关键词路径。

#### 2.3 实现 RRF 融合与确定性二阶段重排

融合两个排名，使用覆盖、短语、通道一致性和来源信息重排有界候选。

### Phase 3: 质量判断与查询改写闭环

#### 3.1 实现证据质量判断

根据最高重排分、查询覆盖、候选和来源数量输出 `sufficient|insufficient|empty`。

#### 3.2 实现上下文感知查询改写

组合主题、诊断重点、反馈、知识缺口和最近错误，去重并限制长度。

#### 3.3 实现最多两次的自校正检索编排

首轮不足时只改写一次，第二轮选择更优结果并无条件终止。

### Phase 4: LCEL、Middleware、State 与 Web 集成

#### 4.1 接入教学 Runnable 与 Agent 工具

让 LCEL 和 Middleware 共用可注入 Hybrid Retriever，并把最终报告写入教学结果。

#### 4.2 接入 LangGraph State、SSE 与 Web 展示

保存并展示检索模式、质量、查询改写和尝试次数，不展示向量或未选中正文。

#### 4.3 同步 README、环境变量与兼容边界

说明本地/Provider Embedding、降级、循环上限、隐私和使用示例。

### Phase 5: 完整验证、复盘与公众号文章

#### 5.1 完成完整回归和静态验证

运行完整 pytest、compileall、pip check、前端语法、计划上下文、索引和差异检查。

#### 5.2 完成交付复盘与生命周期同步

记录实际阻点，将 spec、plan、checklist 和 INDEX 收口为 completed。

#### 5.3 生成并视觉检查第 06 篇公众号文章

在 `person` 目录生成 Word 文章，包含 GitHub 地址、闭环架构、关键实现、边界和下一阶段，并逐页渲染检查。

## 4 验收标准

- 默认无 API Key 可运行完整 Hybrid 检索，可选 Provider Embedding 仅在显式配置时调用。
- BM25、Dense、RRF、重排的分数和排序均稳定、有界、可测试。
- 证据不足最多触发一次查询改写，任何输入最多两次检索。
- Embedding 失败可安全降级到关键词结果，报告不泄漏异常正文或密钥。
- LCEL、Agent、State、SSE 和 Web 使用相同最终来源与检索报告。
- 原 `retrieve_study_sources`、`study_material` 和 `study_chunks` 路径保持兼容。
- 完整测试通过，第 06 篇文章与最终实现一致。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 本地哈希向量被误解为神经语义模型 | README、Web 和文章明确标记 local hash，Provider 才提供模型语义 |
| 两路分数不可直接比较 | 使用基于排名的 RRF，再统一归一化 |
| 自校正形成无限循环 | `max_attempts=2` 为服务端常量，第二轮无条件终止 |
| Provider Embedding 故障中断教学 | 通道级捕获并降级 BM25，报告安全错误码 |
| 向量和报告放大 State | 向量只在进程缓存，State 只保存有界报告和最终来源 |
| LCEL 与 Agent 策略漂移 | 两条路径注入同一个 Hybrid Retriever |
| 新 Schema 破坏旧客户端 | 新增字段全部可选，保留原字段和 JSON/SSE 结构 |

## 6 关联文档

- [设计文档](../../spec/self-corrective-hybrid-rag-design.md)
- [实施 Checklist](./implementation-checklist.md)
- [单元测试计划](./unit-test-plan.md)
- [上一阶段实施计划](../multimodal-material-ingestion/implementation.md)
