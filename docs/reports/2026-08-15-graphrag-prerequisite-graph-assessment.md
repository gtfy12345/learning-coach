# GraphRAG 与知识前置图交付复盘报告

> **日期**: 2026-08-15
> **审查人**: Codex

**关联计划**: [GraphRAG 与知识前置图实施计划](../plan/graphrag-prerequisite-graph/implementation.md)

## 1 复盘范围与成功证据

本次交付覆盖默认离线实体关系抽取、显式可注入结构化模型增强、Unicode/标识符规范化、别名消歧、会话级概念图、有界前置 BFS、图证据排名、图与 Hybrid RRF、前置知识解释，以及 LCEL、Middleware、LangGraph State、JSON/SSE 和 Web 概念图集成。

- `PYTHONPATH=src .venv/bin/pytest -q`：208 项测试全部通过。
- `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`：通过。
- `.venv/bin/python -m pip check`：无损坏依赖。
- `node --check src/learning_coach/static/app.js`：通过。
- `validate_context.py --target backend`：计划上下文校验通过。
- `sync-doc-index.py --check`：Header 违规 0、INDEX drift 0；仅报告注释模板中的历史示例链接。
- `git diff --check`：通过。

本次计划已经进入 owner 执行，前四个实现阶段及对应测试清单全部完成，不存在未启动的 follow-up 文档。

## 2 会话中的主要阻点/痛点

### 2.1 GraphRAG 报告需要跨多层流式消费者传播

- **证据**：`HybridRetrievalResult` 增加 `graph_report` 后，需要同步更新 LCEL `RunnableParallel`、同步/异步 `GroundedTeachingParser`、Middleware Agent 汇总、Node 事件、LangGraph State、Web `SessionView` 和 SSE。聚焦测试在 Node 尚未发送 `knowledge_graph` 事件时明确失败，补齐后通过。
- **影响**：如果只实现 Retriever，代码可以算出概念图，但浏览器和暂停恢复状态看不到它，形成“后端完成、产品不可见”的半集成状态。

### 2.2 中英文句界和代码标识符共享文本空间

- **证据**：确定性抽取器首轮实现只按中文标点和换行切句，英文 `StateGraph requires TypedDict. Reducer ...` 被合并成一个错误关系；英文聚焦测试失败后，增加点号加空白的句界规则并重新验证。
- **影响**：如果缺少语言混合样本，实体和关系仍能通过 Schema 校验，却会产生错误端点。

### 2.3 文档索引检查会扫描注释模板链接

- **证据**：`sync-doc-index.py --check` 对真实 Header 和 INDEX 报告 0 drift，但仍把 `docs/spec/INDEX.md`、`docs/plan/INDEX.md` HTML 注释示例中的文件报告为 10 个 dangling orphan。
- **影响**：不会改变文件，也不阻塞交付，但需要人工区分真实 orphan 和模板噪声。

## 3 根因归类

- 图报告跨消费者传播属于 **spec/plan**：本次设计列出了消费者，结构契约 Gate 和集成测试成功阻止了遗漏进入交付。
- 混合语言句界属于 **无需仓库改动**：这是实现细节缺陷，已有 Red 测试和回归测试已经形成稳定防线。
- 注释模板 orphan 属于 **skill**：索引检查器没有忽略 Markdown HTML 注释区块，报告包含可预期噪声。

## 4 对流程资产的改进建议

- 后续新增运行时报告时，在 checklist 保留“生产者 → Runnable/Agent → State → Event/API → Web”消费者矩阵，并要求同步/异步流式路径各有断言。
  - **落点**：spec/plan
  - **优先级**：high
- 实体关系抽取测试继续使用中英文混排、缩写、代码标识符和连续句子，不把 Schema 合法误当作语义正确。
  - **落点**：spec/plan
  - **优先级**：medium
- `sync-doc-index` 在解析 INDEX 链接前忽略 HTML 注释内容，或把注释链接降级为单独的 template warning，不计入 orphan 数量。
  - **落点**：sync-doc-index skill
  - **优先级**：low

## 5 建议优先级与后续动作

下一阶段最值得保留的是第一项消费者矩阵，因为 Tool Calling 和代码实践会继续增加工具结果、执行报告和 Web 事件；沿用同一 Gate 可以避免半集成。

混合语言抽取样本已进入测试套件，无需额外治理文件。索引工具的注释过滤只影响审计噪声，可低优先级处理，不阻塞后续产品开发。
