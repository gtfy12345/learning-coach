# 自校正 Hybrid RAG 单元测试计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-14

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 1 测试目标

验证 Embedding、BM25、Dense、RRF、重排、质量判断和查询改写的正常、边界与失败路径，并确认 LCEL、Middleware、Graph、Web 和旧检索接口兼容。所有 Provider 测试注入 fake Embeddings，不访问网络或真实模型。

## 2 测试策略

- 本地 Embedding 使用固定中英文输入验证维度、归一化、稳定性和空文本边界。
- Provider 工厂注入 fake initializer，验证配置传递、缓存和初始化错误。
- BM25、Dense、RRF 和重排使用小型确定性语料，分别断言候选、原始分、归一化分和稳定 tie-break。
- 自校正测试记录调用次数，覆盖无需改写、改写成功、改写后仍不足和 Embedding 降级。
- 集成测试使用 fake Chat Model 与 fake Embeddings，验证 Prompt、来源、State、SSE 和 Web 安全投影。

## 3 分阶段测试

### Phase 1: Embedding、配置与 Schema 测试

#### 1.1 本地 Embedding 与缓存

覆盖同输入稳定、不同输入可区分、向量归一化、批量顺序、缓存命中和最大项淘汰。

#### 1.2 Provider 配置

覆盖默认值、显式模型 ID、非法空值、initializer 调用和异常归一化。

#### 1.3 Schema

覆盖合法报告、分数上下界、尝试次数、可选兼容字段和敏感内容拒绝。

### Phase 2: 召回、融合与重排测试

#### 2.1 BM25

覆盖中英文、代码标识符、文档频率、长度归一化、无命中和稳定排序。

#### 2.2 Dense 与降级

覆盖余弦相似度、负分过滤、维度错误、非有限值和后端异常。

#### 2.3 RRF 与重排

覆盖单路、双路、重复候选、权重、归一化、查询覆盖、短语命中和 top_k。

### Phase 3: 自校正闭环测试

#### 3.1 质量判断

覆盖 `sufficient`、`insufficient`、`empty` 及来源多样性边界。

#### 3.2 查询改写

覆盖教学上下文字段、去重、空值、长度上限和改写无变化。

#### 3.3 终止与最佳结果

覆盖首轮通过、第二轮提升、两轮不足、空资料和严格最多两次。

### Phase 4: 教学与 Web 集成测试

#### 4.1 LCEL 与 Middleware

覆盖共享 Retriever 注入、Agent 工具输出、Prompt 上下文和 Embedding 降级。

#### 4.2 State、SSE 与 Web

覆盖报告写回、序列化、流式完成事件和浏览器安全展示。

#### 4.3 文档与配置

验证 README、`.env.example`、项目结构、默认模式和隐私边界一致。

### Phase 5: 完整回归与文章验证

#### 5.1 完整验证

运行完整 pytest、compileall、pip check、前端语法、context validator、INDEX 和差异检查。

#### 5.2 生命周期与复盘

验证 checklist 全部完成、Header/INDEX 无漂移、复盘报告已索引。

#### 5.3 文章验证

渲染第 06 篇 DOCX，逐页检查标题、流程图、代码、GitHub 地址、表格、页眉页脚和不可见溢出。

## 4 通过标准

- 新增逻辑的正常、失败、降级和循环终止路径都有行为断言。
- 测试不需要 `.env`、真实 API Key、网络、Embedding Provider 或真实 Chat Model。
- 所有分数与排序确定，报告不包含向量、未选中正文或敏感异常。
- 完整回归通过，代码、README、计划和文章使用相同边界表述。

## 5 关联文档

- [设计文档](../../spec/self-corrective-hybrid-rag-design.md)
- [实施计划](./implementation.md)
- [测试 Checklist](./unit-test-plan-checklist.md)
