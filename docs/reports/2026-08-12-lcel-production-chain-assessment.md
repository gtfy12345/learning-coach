# LCEL 生产级组合交付复盘报告

> **日期**: 2026-08-12
> **审查人**: Codex

**关联计划**: [LCEL 生产级组合 Follow-up 实施计划](../plan/lcel-runnable-task-layer-follow-up-production-chain/implementation.md)

## 1 复盘范围与成功证据

本次交付在既有五类 LCEL Runnable 任务层上补齐高级组合、确定性内存 RAG、同步/异步/批量/流式执行、LangGraph custom stream、Web SSE、浏览器取消、服务端超时、可选 LangSmith 追踪和 Runnable Mermaid 图导出。原 JSON API、人工暂停恢复、评分阈值和有界补救循环保持兼容；第 03 篇公众号文章已按最终实现更新。

成功证据：

- `PYTHONPATH=src .venv/bin/pytest -q`：73 项离线测试通过。
- `.venv/bin/python -m compileall -q src tests`：通过。
- `node --check src/learning_coach/static/app.js`：通过。
- `git diff --check`：通过。
- Retriever 的输入上限、稳定切块、中文/英文检索、top-k 与无命中均有测试。
- Runnable 的 `invoke`、`ainvoke`、`batch`、`stream`、`astream`，以及 graph custom event 和 Web SSE 顺序均有测试。
- 超时、取消、未知会话、主链失败、结构校验失败、主备均失败和元数据脱敏均有边界测试。
- 第 03 篇 DOCX 的必需内容与禁用小节检查通过；压缩包完整，标题结构、表格几何和无障碍审计通过，macOS 系统预览中文与布局正常。

## 2 会话中的主要阻点/痛点

### 2.1 Runnable 组合存在“看似 stream、实际缓冲”的风险

- **证据**：官方 RunnableSequence 语义要求链中组件实现 `transform` 才能保持增量流；`RunnableLambda` 默认不提供这一能力。教学链既要附带来源又要保留模型分块，因此最终增加了 `GroundedTeachingParser.transform/atransform`，并用多块 fake 模型验证聚合结果。
- **影响**：只验证最终文本会掩盖首块被推迟的问题，Web 页面虽然使用 SSE，也可能直到模型完成才看到内容。

### 2.2 DOCX 内置渲染环境无法正确替换中文字体

- **证据**：bundled LibreOfficeDev 渲染出的五页图片把中文替换为重复拉丁字符，而同一 DOCX 的 macOS Quick Look 预览能完整显示中文；内容提取、表格几何、无障碍和 ZIP 审计均通过。
- **影响**：需要增加系统预览交叉验证，才能区分文档本身损坏与渲染器字体环境问题，增加了文章收尾成本。

### 2.3 表格边界审计发现 10 DXA 的对齐偏差

- **证据**：首次 `table_geometry.py` 审计发现表格缩进 120 DXA，而首列单元格起始边距为 130 DXA；修正后复查为零问题。
- **影响**：发生一次小范围重生成，但没有影响正文、代码或最终交付。

## 3 根因归类

- 真流式取决于整条 Runnable 链的 `transform` 能力，而不只是模型支持 `stream`，根因属于 **spec/plan** 的执行契约细节；本次设计风险、解析器实现和测试已经覆盖。
- CJK 字体替换是 bundled LibreOfficeDev 的字体发现/回退问题，根因属于 **skill**（`documents`）运行环境，不属于 Learning Coach 或 DOCX 内容。
- 10 DXA 表格偏差是一次性文档生成参数不一致，属于 **无需仓库改动**；现有几何审计已经能准确拦截。

## 4 对流程资产的改进建议

- 后续涉及 LCEL 流式的 spec/plan 应把“首块可观测、所有中间组件的 transform 能力、完整结果可聚合”列为独立验收项。
  - **落点**：spec/plan
  - **优先级**：high
- 文档渲染工具应在缺少 CJK 字体或发生异常字形替换时给出明确诊断，并允许指定可用字体目录；macOS 环境可将 Quick Look 预览作为补充验证路径。
  - **落点**：skill（`documents`）
  - **优先级**：high
- 保留表格几何审计作为公众号 DOCX 的固定收尾步骤，不需要为本次 10 DXA 偏差增加新的项目规范。
  - **落点**：无需仓库改动
  - **优先级**：low

## 5 建议优先级与后续动作

下一轮最值得保留的是分层流式测试：Runnable 层验证多块输出，LangGraph 层验证 custom 事件，Web 层验证 SSE 顺序与取消；这样可以定位是哪一层发生缓冲或丢事件。

文档工具链的最高价值改进是增加 CJK 字体可用性诊断和显式字体目录支持。它不影响 Learning Coach 运行时，本次不创建新的产品 follow-up plan。表格微调已由现有审计闭环，无需进一步动作。
