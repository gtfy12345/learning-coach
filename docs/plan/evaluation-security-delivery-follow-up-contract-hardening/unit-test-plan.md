# 收官审计契约加固 Follow-up 单元测试计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-16

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 1 测试原则

- 每个问题先保留可复现的 Red，再做最小 Green 修复。
- 使用 fake/stub 模型与本地确定性 Retriever，不调用真实模型、Provider Embedding 或网络。
- 测试公开行为与安全输出，不依赖内部异常正文或时间抖动。

## Phase 1: 兼容性、缓存与测试入口

- Python 3.10 对源码逐文件编译通过，Web deadline helper 的成功与超时路径可直接运行。
- URL 相同命中缓存、URL 不同隔离缓存；既有 base64 行为保持。
- venv console-script 与 `python -m pytest` 都能收集完整套件。

## Phase 2: 安全扫描、资料定界与轨迹评价

- 101 个同类 PII 不抛异常且计数饱和为 100。
- Agent 资料工具返回定界符、加固声明和原资料内容。
- 合法两轮补救报告通过；同轮重复事件仍失败。

## Phase 3: Web 摄取与 JSON API 运行边界

- 纯粘贴文本产生兼容字段、Chunk 和摄取报告。
- JSON 创建与回答覆盖超时、模型失败脱敏、输入校验和未知会话；并发回答、锁等待、取消、空流和创建失败验证单飞与资源清理。

## Phase 4: Tool 检索复用与模型能力降级

- Spy Retriever 证明每次工具调用只检索一次；invoke/stream 与多查询的来源、单数报告来自同一结果。
- 不兼容高级模型未被调用，直接 middleware 和封装路径的主模型 Agent/LCEL 分支及 `model_tier` 均正确。

## Phase 5: 公开文档与完整验证

- README 契约测试覆盖稳定测试命令与 Python 版本。
- 全量 pytest、evaluate、编译、前端和差异检查通过。
