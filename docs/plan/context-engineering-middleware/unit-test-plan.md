# Context Engineering 与 Middleware 单元测试计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-13

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 1 目标

使用离线 fake/stub 模型验证 Runtime Context、动态教学上下文、Middleware 工具与模型选择、摘要、调用预算、CLI 降级、LangGraph 状态更新和 Web 展示，不调用真实模型或网络。

## 2 测试策略

- 新增 `tests/test_context.py` 验证配置、掌握度、最近错误、摘要和上下文裁剪。
- 新增 `tests/test_middleware.py` 验证动态 Prompt、工具筛选、模型切换和调用上限。
- 扩展 Runnable 与节点测试，验证 Agent 路径与无工具 LCEL 降级输出一致。
- 扩展 Graph、CLI、Web 测试，验证 Runtime Context 传递、暂停恢复、新字段和旧接口兼容。
- 所有测试使用确定性 fake/stub，不读取 `.env`、不访问 Provider 和 LangSmith。

## 3 测试阶段

### Phase 1: Runtime Context 与学习状态测试

#### 1.1 配置和状态边界

验证默认值、上下限、非法环境变量、目标规范化以及 Runtime Context 不被写回预算字段。

#### 1.2 上下文和摘要

验证不同掌握度、错误去重与截断、反馈、资料来源和 600 字摘要边界。

### Phase 2: Middleware 与 Agent 测试

#### 2.1 动态 Prompt、工具与模型

验证系统提示随目标和状态变化；资料工具和进度工具按条件开放；低掌握度时选择高级模型。

#### 2.2 Agent、预算和 CLI 降级

验证工具调用返回、模型/工具预算超限、主模型无工具能力时的 LCEL 降级，以及统一输出报告。

### Phase 3: LangGraph、Web 与 CLI 测试

#### 3.1 图与 CLI

验证图 context schema、节点读取运行目标、评价后 mastery/errors/summary 更新和 CLI 参数兼容。

#### 3.2 Web 与 SSE

验证表单目标输入、SessionView 新字段、SSE 最终状态、公开配置脱敏和原 JSON 路径回归。

### Phase 4: 文档与完整回归

#### 4.1 文档和配置

验证 README 与 `.env.example` 包含新配置、边界和启动说明。

#### 4.2 完整验证

运行完整 pytest、compileall、前端 JavaScript 语法与 `git diff --check`；文章生成后检查内容、链接、DOCX 包和逐页渲染。

## 4 通过标准

- 正常、无资料、无工具能力、动态模型未配置、预算超限和补救轮次均有断言。
- 新字段不破坏旧接口和旧调用方。
- 测试不调用真实模型、工具网络、数据库或外部服务。
- 文档与最终行为、配置默认值和安全边界一致。

## 5 关联文档

- [设计文档](../../spec/context-engineering-middleware-design.md)
- [实施计划](./implementation.md)
