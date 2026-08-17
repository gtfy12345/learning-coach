# 国产模型兼容接入与模型页面优化单元测试 Checklist

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-17

**关联计划**: [unit-test-plan.md](./unit-test-plan.md)

## Phase 1: OpenAI 兼容 Provider 契约测试

- [x] 1.1 覆盖 Provider 注册表、默认地址与 URL 拒绝边界
- [x] 1.2 覆盖兼容模型构建、角色分流与现有 Provider 回归
- [x] 1.3 覆盖 API 脱敏、测试票据与逻辑 Provider 摘要

## Phase 2: 首页与模型设置页体验测试

- [x] 2.1 覆盖 Provider 预设与动态凭据静态契约
- [x] 2.2 覆盖测试门禁、字段去重和状态反馈交互
- [x] 2.3 覆盖首页入口、可访问性与响应式浏览器检查

## Phase 3: 文档与交付验证测试

- [x] 3.1 覆盖 README 与 `.env.example` 公开说明
- [x] 3.2 完成聚焦测试、全量测试、语法和 diff 检查
