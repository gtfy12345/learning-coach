# 收官审计契约加固 Follow-up 实施 Checklist

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-16

**关联计划**: [implementation.md](./implementation.md)

## Phase 1: 兼容性、缓存与测试入口

- [x] 1.1 恢复 Python 3.10 语法兼容
- [x] 1.2 修复 URL 诊断图片缓存隔离
- [x] 1.3 修复公开 pytest 入口

## Phase 2: 安全扫描、资料定界与轨迹评价

- [x] 2.1 饱和 PII 计数并保持扫描不抛出
- [x] 2.2 加固 Tool Calling 资料上下文
- [x] 2.3 修复多轮补救轨迹唯一性判定

## Phase 3: Web 摄取与 JSON API 运行边界

- [x] 3.1 让纯粘贴文本进入统一摄取管线
- [x] 3.2 统一 JSON 与 SSE 的超时和安全错误协议

## Phase 4: Tool 检索复用与模型能力降级

- [x] 4.1 保证一次 Tool 调用只检索一次
- [x] 4.2 让高级模型降级报告实际执行层级

## Phase 5: 公开文档与完整验证

- [x] 5.1 同步 README 与公开契约测试
- [x] 5.2 执行全量交付验证
