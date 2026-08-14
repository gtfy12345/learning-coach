# 多模态学习资料摄取单元测试计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-14

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 1 测试目标

验证多格式 Loader、位置元数据、哈希与增量索引的正常、边界和失败路径，并确认 CLI/Web/Graph 与旧纯文本资料行为兼容。所有测试使用内存样本、fake HTTP 响应和 fake 视觉模型，不访问真实网络或模型。

## 2 测试策略

- Loader 测试使用运行时生成的小型 PDF、DOCX、PPTX、EPUB、HTML、文本、代码和图片样本。
- 网页测试注入 fetcher 与 DNS 解析结果，覆盖安全 URL、私网、重定向、类型和大小限制。
- 图片测试注入 fake vision model，断言标准 content block、单次调用和输出上限。
- Splitter/Hash/Index 使用确定性输入重复运行，断言顺序、哈希和增量统计。
- CLI/Web 测试注入摄取管线或 fake 模型，确保不产生外部费用。

## 3 分阶段测试

### Phase 1: Loader 与统一 Document 契约测试

#### 1.1 输入、Metadata 与 Registry

覆盖互斥输入、空输入、不支持格式、MIME/扩展名路由、大小/数量上限和安全元数据。

#### 1.2 文档、电子书、文本与代码

覆盖 PDF 页、DOCX 段落、PPTX 页、EPUB 章节、HTML 标题、纯文本和代码行位置；损坏或空文档给出稳定错误。

#### 1.3 网页与图片

覆盖网页正文清洗、URL 安全、响应限制、视觉能力协商、模型失败和有界视觉描述。

### Phase 2: Splitter、Hash 与增量索引测试

#### 2.1 Splitter 与哈希

覆盖短文档、长段落、中文句子、代码行、Chunk 重叠、位置偏移和重复执行哈希稳定性。

#### 2.2 增量索引

覆盖首次新增、完全重复、同来源更新、多来源追加、full 删除、Chunk 去重和稳定报告。

#### 2.3 Retriever 与 Schema

覆盖新 Chunk 检索排序、来源位置映射、旧纯文本适配、无命中、top_k 边界和 Pydantic 校验。

### Phase 3: CLI、Web 与流程集成测试

#### 3.1 CLI

覆盖重复 `--material`、本地文件/URL 分派、无资料兼容、错误退出和暂停恢复期间 Chunk 保留。

#### 3.2 Web 后端

覆盖多文件/URL JSON 与 SSE 创建、文件限制、图片能力错误、摄取报告、SessionView 和安全错误信息。

#### 3.3 浏览器协议

通过 DOM 文本和 JavaScript 语法检查验证多文件字段、URL 提交、来源位置与摄取统计渲染。

### Phase 4: 回归与交付验证

#### 4.1 文档与依赖

验证 requirements 可安装、README 与公开配置一致、计划上下文和 INDEX 无漂移。

#### 4.2 完整回归

运行完整 pytest、compileall、前端语法检查、`git diff --check`，确认没有真实网络或模型调用。

#### 4.3 文章验证

渲染第 05 篇 DOCX，逐页检查标题、代码块、表格、GitHub 地址、分页、页眉页脚和不可见溢出。

## 4 通过标准

- 所有新增聚焦测试和原有回归测试通过。
- 正常、失败、限制和增量终止路径均有行为断言。
- 测试过程不依赖 `.env`、真实 API Key、网络或外部模型。
- 代码、README、计划、测试和公众号文章对支持格式与边界表述一致。

## 5 关联文档

- [设计文档](../../spec/multimodal-material-ingestion-design.md)
- [实施计划](./implementation.md)
- [测试 Checklist](./unit-test-plan-checklist.md)
