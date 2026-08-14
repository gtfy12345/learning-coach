# 多模态学习资料摄取交付复盘报告

> **日期**: 2026-08-14
> **审查人**: Codex

**关联计划**: [多模态学习资料摄取实施计划](../plan/multimodal-material-ingestion/implementation.md)

## 1 复盘范围与成功证据

本次交付覆盖 PDF、DOCX、PPTX、EPUB、HTML、文本、Markdown、代码、网页与图片资料的统一 Loader，位置感知切分，SHA-256 哈希，会话级内存增量索引，以及 CLI、Web、检索、LCEL 和 Middleware 集成。旧 `study_material` 路径继续兼容，公开行为与 README 已同步。

成功证据：

- `PYTHONPATH=src .venv/bin/pytest -q`：148 项测试全部通过。
- `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`：通过。
- `.venv/bin/python -m pip check`：无依赖冲突。
- `node --check src/learning_coach/static/app.js`：通过。
- `validate_context.py --target backend`：计划上下文校验通过。
- `git diff --check`：通过。

本次创建的 spec、plan 和 checklist 已进入 owner 执行并具有验证支持的完成进度，不存在未启动的 follow-up 文档。

## 2 会话中的主要阻点/痛点

### 2.1 新状态字段存在跨消费者遗漏风险

- **证据**：`study_chunks` 已接入 State、Retriever、CLI 和 Web 后，动态 Context 最初仍只依据旧 `study_material` 判断是否开放资料检索工具；相邻集成测试发现并补齐了该消费者。
- **影响**：如果只验证摄取管线，Web 能显示摄取成功，但教学 Agent 可能拿不到资料检索能力，形成“数据已进入、运行时不可用”的半集成状态。

### 2.2 网页大小限制最初发生在完整缓冲之后

- **证据**：交付审计发现 `SafeWebFetcher` 使用 `client.get()` 后才检查正文长度。新增自定义流测试后，确认旧实现会读完四个数据块；修正后在超过 2 MiB 的第三块立即停止。
- **影响**：原实现能拒绝超限网页，却不能限制下载过程的内存峰值，与“有界摄取”的设计目标不完全一致。

### 2.3 Manifest 目标名需要以声明文件为准

- **证据**：验证时先尝试了不存在的 `implementation` 目标，脚本明确返回唯一可用目标 `backend`；使用 `backend` 重跑后通过。
- **影响**：产生一次无效命令，但未引起代码返工或交付风险。

## 3 根因归类

- 跨消费者遗漏属于 **spec/plan**：计划描述了接入范围，但 checklist 未显式列出“新增状态字段的所有读取者”核对表。
- 完整缓冲问题属于 **spec/plan**：大小上限写清了数值，但没有把“传输中止”作为可验收的资源边界。
- 目标名误用属于 **无需仓库改动**：manifest 与校验器已经给出明确答案，是一次执行层参数误判。

## 4 对流程资产的改进建议

- 在后续状态 Schema 变更的 checklist 中增加“生产者—状态—消费者”核对项，至少覆盖 CLI、Web、Graph、Context、Middleware、Retriever 和序列化边界。
  - **落点**：spec/plan
  - **优先级**：high
- 对网络和文件资源限制采用可观察的验收表达，例如“不超过 N 字节时返回、超过 N 字节后立即终止读取”，并要求测试验证未继续消费剩余流。
  - **落点**：spec/plan
  - **优先级**：high
- 后续执行验证命令时直接从 `context.yaml` 的 `defaultTarget` 读取目标，不凭工作阶段名称推断。
  - **落点**：无需仓库改动
  - **优先级**：low

## 5 建议优先级与后续动作

下一轮开发最值得优先落实前两项：先为跨模块状态新增消费者矩阵，再把资源上限写成“拒绝 + 提前终止”的双重契约。它们能直接降低后续 Hybrid RAG、持久化索引和后台任务接入时的半集成与资源放大风险。

目标名误用不需要增加新的治理文档；保持按 manifest 执行即可。
