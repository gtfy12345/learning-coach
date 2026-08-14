# 自校正 Hybrid RAG 交付复盘报告

> **日期**: 2026-08-14
> **审查人**: Codex

**关联计划**: [自校正 Hybrid RAG 实施计划](../plan/self-corrective-hybrid-rag/implementation.md)

## 1 复盘范围与成功证据

本次交付覆盖本地与 Provider Embedding、BM25、Dense 召回、RRF 融合、确定性重排、证据质量判断、上下文感知查询改写、最多两次检索，以及 LCEL、Middleware、LangGraph State、JSON/SSE 和 Web 展示集成。

- `PYTHONPATH=src .venv/bin/pytest`：181 项测试通过。
- `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`：通过。
- `.venv/bin/python -m pip check`：无损坏依赖。
- `node --check src/learning_coach/static/app.js`：通过。
- `.venv/bin/python .agent-skills/implement/shared/scripts/validate_context.py ...`：计划上下文通过。
- `git diff --check`：通过。

## 2 会话中的主要阻点/痛点

### 2.1 新旧检索来源标识不同

- **证据**：结构化 Chunk 使用 SHA-256 `chunk_id`，旧 `study_material` API 公开的是 `material-1#chunk-N`；直接替换会破坏已有断言和客户端预期。
- **影响**：需要在兼容适配层保存内部稳定 ID，同时把最终来源投影回旧公开 ID、空来源名称和空位置。

### 2.2 分支命名策略与本地检测脚本不一致

- **证据**：工作分支遵循 Codex 的 `codex/` 前缀要求，但现有 `detect_session_branch.py` 只识别 `feat/`、`fix/`、`opt/` 和 `docs/`。
- **影响**：自动检测会产生假阴性，需以 `context.yaml` 和当前实际分支人工确认。

### 2.3 校验脚本依赖调用解释器

- **证据**：系统 `python3` 运行计划上下文校验时报 `PyYAML is not installed`，同一命令改用项目 `.venv/bin/python` 后通过。
- **影响**：第一次校验产生一次无效环境失败，但没有影响产品实现或测试结果。

## 3 根因归类

- 旧公开来源 ID 与新内部 Chunk ID 语义不同，属于 **spec-plan / 兼容性约束**；通过边界适配解决，不应删除旧字段。
- 分支前缀检测器与宿主规则不一致，属于 **skill**；不是产品代码问题。
- 校验脚本没有自动复用项目虚拟环境，属于 **skill / 环境约定**；仓库依赖本身完整。

## 4 对流程资产的改进建议

- 在检索设计模板中显式列出“内部稳定 ID”和“旧公开 ID”的投影策略。
  - **落点**：spec-plan
  - **优先级**：medium
- 让分支检测脚本支持可配置前缀或把 `codex/` 纳入合法前缀。
  - **落点**：implement skill
  - **优先级**：medium
- 校验命令优先使用当前激活解释器，并在缺依赖时显示建议的项目虚拟环境命令。
  - **落点**：implement / sync-doc-index skill
  - **优先级**：low

## 5 建议优先级与后续动作

本次交付没有阻断项。下一阶段最值得优先处理的是 GraphRAG 概念与前置关系的数据契约，并继续复用本阶段的有界检索报告。分支检测和校验解释器问题可在不影响产品功能的情况下延后修复。
