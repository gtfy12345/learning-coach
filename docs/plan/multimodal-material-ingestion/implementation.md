# 多模态学习资料摄取实施计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-14

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

为 Learning Coach 增加统一 Loader、位置感知 Splitter、标准 Metadata、SHA-256 内容寻址和会话级增量索引，使论文、书籍、课程文档、网页、图片与代码能够进入现有讲解检索路径并保留来源位置。

## 2 背景

第 3 阶段只支持用户粘贴最多 50,000 字纯文本，第 4 阶段虽然能按上下文动态选择资料工具，但工具仍只能检索这段文本。本阶段需要把资料来源从一个字符串升级为有类型、有位置、有版本的 Document/Chunk 集合，同时保持现有词法检索、LCEL、Agent、SSE 和旧接口兼容。

## 3 实施步骤

### Phase 1: Loader 与统一 Document 契约

#### 1.1 定义输入、元数据、限制与 Loader Registry

增加资料输入、来源元数据、摄取报告和 Loader 协议，锁定 MIME、扩展名、大小、数量与错误边界。

#### 1.2 实现文档、电子书、文本与代码 Loader

接入 PDF、DOCX、PPTX、EPUB、HTML、TXT、Markdown 和常见代码解析，按页、幻灯片、章节、段落或行号输出 LangChain Document。

#### 1.3 实现安全网页和视觉图片 Loader

网页 Loader 限定安全 http/https 响应并阻止私网目标；图片 Loader 复用视觉模型生成有界文字与图表描述，无视觉能力时明确失败。

### Phase 2: Splitter、Hash 与增量索引

#### 2.1 实现位置感知 Splitter 与稳定哈希

在 Loader 位置单元内完成段落/句子/行边界切分，生成来源、内容与 Chunk SHA-256，并保持稳定顺序和位置偏移。

#### 2.2 实现会话级增量索引

实现 new、updated、skipped、deleted 统计和 `incremental|full` 清理语义，确保变化来源的旧 Chunk 不再可检索。

#### 2.3 接入现有词法检索与来源 Schema

让 Retriever 优先读取新 Chunk，并把来源名、URI、类型、位置与哈希写入 `StudySource`；旧 `study_material` 自动适配且无资料路径不变。

### Phase 3: CLI、Web 与学习流程集成

#### 3.1 接入 CLI 多资料输入

增加可重复 `--material PATH_OR_URL`，在图执行前摄取资料并把序列化 Chunk 写入初始 State，保持 `--image` 诊断语义不变。

#### 3.2 接入 Web 多文件与 URL 摄取

扩展 JSON/SSE 会话创建服务，接收多个资料文件和换行 URL，调用同一摄取管线并返回安全摄取报告。

#### 3.3 更新浏览器资料选择与来源位置展示

页面支持多文件、网页地址和格式提示，展示来源位置、摄取统计与错误，不展示资料全文、服务器路径或图片 base64。

### Phase 4: 文档、验证与公众号文章

#### 4.1 同步依赖、README 与公开边界

更新运行依赖、安装说明、格式矩阵、CLI/Web 示例、限制、安全边界、项目结构与系列路线。

#### 4.2 完成全量验证与交付复盘

运行 Loader、检索、Graph、CLI、Web、完整测试、Python 编译、前端语法和差异检查，并形成交付复盘。

#### 4.3 生成并视觉检查第 05 篇公众号文章

在 `person` 目录生成第 05 篇 Word 文章，包含 GitHub 地址、架构主线、关键代码、边界与下一阶段衔接，并逐页渲染检查。

## 4 验收标准

- 支持的本地文档、网页、图片和代码都通过统一 Loader 输出 LangChain Document。
- 每种资料都能返回对应页码、幻灯片、章节、标题、文件名或代码行范围。
- 来源、内容与 Chunk 哈希稳定；重复、修改和删除的增量结果准确。
- Retriever 和讲解来源使用新 Metadata，旧 `study_material`、无资料路径和 SSE 协议保持兼容。
- CLI 与 Web 能实际提交多资料，图片只在视觉能力明确可用时摄取。
- 所有读取、解析、网络和模型调用均有上限，测试不访问真实网络和模型。
- 完整测试与静态检查通过，第 05 篇文章与最终实现一致。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 文档解析依赖过重或格式差异大 | 使用专用、可测试解析库和统一 Loader Registry，不引入完整 community 集成包 |
| 网页 URL 导致 SSRF | 解析并校验 URL、DNS 地址与重定向，阻止私网和非 HTTP 目标 |
| Office/EPUB 压缩炸弹 | 限制原始字节、成员数量、解压总量和提取字符数 |
| 图片摄取产生额外费用 | 只对明确的资料图片调用视觉模型，每张最多一次并限制数量 |
| 增量更新留下旧 Chunk | 以 source_key 建立反向映射，更新和 full cleanup 都验证删除结果 |
| Metadata 泄漏本地路径或正文 | 只保留安全名称/URL/位置，报告不包含正文、base64 和绝对路径 |
| 新接口破坏旧客户端 | 新字段全部可选，保留 study_material 和既有 JSON/SSE 路径测试 |

## 6 关联文档

- [设计文档](../../spec/multimodal-material-ingestion-design.md)
- [实施 Checklist](./implementation-checklist.md)
- [单元测试计划](./unit-test-plan.md)
- [上一阶段实施计划](../context-engineering-middleware/implementation.md)
