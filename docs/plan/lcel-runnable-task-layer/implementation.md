# LCEL Runnable 任务层实施计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-12

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

把现有五类模型任务改造成可复用 LCEL Runnable，增加可选的角色级备用模型配置，并在不改变 LangGraph 学习流程协议的前提下让 CLI 和 Web 自动使用完整任务回退。

## 2 背景

当前节点同时负责 Prompt、模型调用、结果解析和 State 映射，单次任务难以独立批量调用或复用。第二阶段已经解决 Provider、图片和结构化输出差异，本阶段在其上建立统一任务组合层。

## 3 实施步骤

### Phase 1: 备用模型与能力契约

#### 1.1 扩展模型配置

为 `ModelSettings` 增加教学和评价 fallback 模型 ID。保持空值兼容，并让评价 fallback 在未单独指定时继承教学 fallback。

#### 1.2 扩展模型套件

让 `LearningCoachModels` 持有可选的文本、诊断和评价备用模型；备用结构化模型独立协商输出方法，并复用相同模型 ID 的实例。

### Phase 2: LCEL Runnable 组合

#### 2.1 建立 Prompt 与解析器任务链

新增 `runnables.py`，为诊断、讲解、出题、评价和总结定义输入契约、Prompt、模型适配与输出解析。文本输出使用 `StrOutputParser`，结构化输出执行 Pydantic 二次验证。

#### 2.2 包装完整任务回退与批处理

把主任务与同契约备用任务通过 `with_fallbacks()` 组合，确保模型异常和解析异常都能触发一次回退，并验证 Runnable 的 `batch` 行为。

### Phase 3: 图接入与公开说明

#### 3.1 让节点委托 Runnable

保持节点方法和局部 State 更新不变，只把 Prompt、调用和解析职责迁移到 `LearningCoachRunnables`。验证图片诊断、两次暂停恢复和有限补救循环不回归。

#### 3.2 同步配置、README 与完整验证

更新 `.env.example`、README、Web 脱敏配置响应和项目结构说明；运行完整离线测试、编译检查和 `git diff --check`。

## 4 验收标准

- 五类模型任务均由独立 Runnable 表达并可直接 `invoke`。
- 文本和结构化输出类型稳定，解析失败可触发完整链回退。
- 两个 fallback 环境变量可选，未配置时行为不变。
- CLI、Web 和 LangGraph 共用同一模型套件与 Runnable 套件。
- 现有学习流程、暂停恢复、评分阈值和次数上限不变。
- 所有测试离线运行，不访问真实模型和网络。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 自定义 CLI 模型不是 LangChain `Runnable` | 用最小适配器包装 `invoke`，同时保留标准模型原生 Runnable 能力 |
| 只回退模型导致解析错误无法降级 | 在完整 `Prompt | Model | Parser` 外包装 `with_fallbacks()` |
| fallback 输出契约与主链不一致 | 主链和备用链复用同一 Prompt 与解析器构造函数 |
| 图片备用模型不支持视觉 | 原样传递图片并让异常显式上抛，不静默丢图 |
| 配置增加破坏现有部署 | 新环境变量全部可选，保留 `MODEL_ID` 和现有默认行为 |

## 6 关联文档

- [设计文档](../../spec/lcel-runnable-task-layer-design.md)
- [实施 Checklist](./implementation-checklist.md)
- [单元测试计划](./unit-test-plan.md)

## 7 完成验证

- `PYTHONPATH=src .venv/bin/pytest -q`：57 项测试通过。
- `.venv/bin/python -m compileall -q src tests`：通过。
- `git diff --check`：通过。
- 第 03 篇公众号 DOCX 已完成 9 页逐页渲染检查；表格几何、可访问性、标题层级、图片尺寸、PAGE 字段和压缩包完整性检查通过。

## 后续修复 / Follow-ups

- 2026-08-12: [LCEL 生产级组合 Follow-up](../lcel-runnable-task-layer-follow-up-production-chain/implementation.md) - 增加高级 Runnable 组合、内存 RAG、SSE 流式、取消超时、追踪与图导出。
