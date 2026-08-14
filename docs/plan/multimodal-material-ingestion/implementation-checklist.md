# 多模态学习资料摄取实施 Checklist

> **版本**: 1.0
> **状态**: active
> **更新日期**: 2026-08-14

**关联计划**: [implementation.md](./implementation.md)

## Phase 1: Loader 与统一 Document 契约

- [x] 1.1 定义输入、元数据、限制与 Loader Registry
- [x] 1.2 实现文档、电子书、文本与代码 Loader
- [x] 1.3 实现安全网页和视觉图片 Loader

## Phase 2: Splitter、Hash 与增量索引

- [x] 2.1 实现位置感知 Splitter 与稳定哈希
- [x] 2.2 实现会话级增量索引
- [x] 2.3 接入现有词法检索与来源 Schema

## Phase 3: CLI、Web 与学习流程集成

- [x] 3.1 接入 CLI 多资料输入
- [x] 3.2 接入 Web 多文件与 URL 摄取
- [x] 3.3 更新浏览器资料选择与来源位置展示

## Phase 4: 文档、验证与公众号文章

- [ ] 4.1 同步依赖、README 与公开边界
- [ ] 4.2 完成全量验证与交付复盘
- [ ] 4.3 生成并视觉检查第 05 篇公众号文章
