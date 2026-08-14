# 多模态学习资料摄取单元测试 Checklist

> **版本**: 1.0
> **状态**: active
> **更新日期**: 2026-08-14

**关联计划**: [unit-test-plan.md](./unit-test-plan.md)

## Phase 1: Loader 与统一 Document 契约测试

- [x] 1.1 输入、Metadata、Registry、限制和错误测试
- [x] 1.2 PDF、DOCX、PPTX、EPUB、HTML、文本与代码 Loader 测试
- [x] 1.3 安全网页和视觉图片 Loader 测试

## Phase 2: Splitter、Hash 与增量索引测试

- [ ] 2.1 位置感知切分与哈希稳定性测试
- [ ] 2.2 新增、重复、更新与 full cleanup 测试
- [ ] 2.3 新旧 Retriever、来源 Schema 与排序测试

## Phase 3: CLI、Web 与流程集成测试

- [ ] 3.1 CLI 多资料、错误与暂停恢复测试
- [ ] 3.2 Web 多文件/URL、报告、限制与兼容测试
- [ ] 3.3 浏览器字段、提交和来源位置渲染测试

## Phase 4: 回归与交付验证

- [ ] 4.1 依赖、README、计划上下文和 INDEX 检查
- [ ] 4.2 pytest、compileall、前端语法和差异检查
- [ ] 4.3 第 05 篇文章渲染与逐页视觉检查
