# Context Engineering 与 Middleware 交付复盘报告

> **日期**: 2026-08-13
> **审查人**: Codex

**关联计划**: [Context Engineering 与 Middleware 实施计划](../plan/context-engineering-middleware/implementation.md)

## 1 复盘范围与成功证据

本次交付覆盖 Runtime Context、动态 Prompt / Tools / Model、确定性学习摘要、模型与工具预算、Context Report，以及 LangGraph、CLI、Web 和 SSE 的完整接入。外层教学流程继续由 LangGraph 确定性组织，Middleware 只负责一次讲解任务内部的上下文决策。

交付通过以下验证：

- `PYTHONPATH=src .venv/bin/pytest -q`：110 个测试全部通过。
- `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`：Python 模块编译通过。
- `node --check src/learning_coach/static/app.js`：前端脚本语法检查通过。
- `validate_context.py --context docs/plan/context-engineering-middleware/context.yaml`：计划上下文校验通过。
- `git diff --check`：未发现空白符错误。

## 2 会话中的主要阻点/痛点

### 2.1 Agent 接入曾使流式讲解退化为单块输出

- **证据**：初版 `ContextEngineeredTeaching.stream()` 在工具模型路径直接调用同步 `invoke()`；复查后改为消费 Agent 的 `messages` 与 `values` 流，并新增 Agent 和 LCEL 两条路径的流式测试。
- **影响**：如果未在交付前发现，Web SSE 协议虽然仍可返回结果，但用户会失去逐步看到讲解文本的体验。

### 2.2 新 Agent 路径需要显式继承既有模型回退语义

- **证据**：LCEL 路径原有 `with_fallbacks()`，但局部 Agent 初版没有复用备用聊天模型；复查后加入 `ModelFallbackMiddleware`，并新增主模型失败、备用模型成功的测试。
- **影响**：同一讲解任务会因是否进入 Agent 路径而出现不同的故障恢复行为。

### 2.3 Context Report 在流结束时才能完整生成

- **证据**：工具调用次数、使用过的工具与来源必须等 Agent 循环结束后统计；实现因此将正文作为增量块发送，并在最后一个空文本块携带来源和报告。
- **影响**：节点聚合逻辑需要同时处理正文块与收尾元数据块，不能假设首块包含全部字段。

## 3 根因归类

- Agent 与 LCEL 的流式一致性要求在设计中只描述为“保持 Web SSE”，没有明确到两条执行路径的 chunk 契约。
  - **类别**：spec-plan
- 回退策略的设计重点在模型选择和预算，没有把“新增执行路径必须继承既有 fallback 语义”写成验收项。
  - **类别**：spec-plan
- Context Report 采用收尾块是 Agent 流式执行的自然结果，当前测试和节点已覆盖，不需要额外治理变更。
  - **类别**：无需仓库改动

## 4 对流程资产的改进建议

- 在后续涉及 Agent / LCEL 双路径的计划中，增加“正文增量流、最终元数据、异常传播”三项跨模式契约。
  - **落点**：spec-plan
  - **优先级**：high
- 在新增模型执行路径的 checklist 中加入回退继承检查：主模型失败、备用成功、主备均失败且次数有界。
  - **落点**：spec-plan
  - **优先级**：high
- 在 README 的 SSE 说明中继续区分 token 事件与最终 state / Context Report，不把报告描述为逐 token 可用。
  - **落点**：README
  - **优先级**：medium

## 5 建议优先级与后续动作

下一阶段最值得优先保留的是双路径契约测试：无论后续接入文档摄取、RAG 还是更多工具，都要同时验证 Agent 与 LCEL 的流式、回退和预算边界。Context Report 的收尾块协议已经有测试保护，暂不需要增加新的抽象层。
