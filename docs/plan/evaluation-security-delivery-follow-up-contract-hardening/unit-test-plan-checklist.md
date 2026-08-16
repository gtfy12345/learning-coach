# 收官审计契约加固 Follow-up 单元测试 Checklist

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-16

**关联测试计划**: [unit-test-plan.md](./unit-test-plan.md)

## Phase 1: 兼容性、缓存与测试入口

- [x] 1.1 Python 3.10 编译与 deadline 运行回归
- [x] 1.2 URL 与 base64 缓存键回归
- [x] 1.3 两种 pytest 入口回归

## Phase 2: 安全扫描、资料定界与轨迹评价

- [x] 2.1 高频 PII 饱和计数回归
- [x] 2.2 Agent ToolMessage 加固回归
- [x] 2.3 单轮重复失败与多轮重复通过回归

## Phase 3: Web 摄取与 JSON API 运行边界

- [x] 3.1 纯粘贴文本统一摄取回归
- [x] 3.2 JSON/SSE 超时、脱敏、并发单飞与资源清理回归

## Phase 4: Tool 检索复用与模型能力降级

- [x] 4.1 invoke/stream 单次 Tool 与多查询投影回归
- [x] 4.2 直接/封装路径高级模型能力降级与报告回归

## Phase 5: 公开文档与完整验证

- [x] 5.1 README 公开契约回归
- [x] 5.2 全量验证矩阵
