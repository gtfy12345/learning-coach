# LCEL Runnable 任务层交付复盘报告

> **日期**: 2026-08-12
> **审查人**: Codex

**关联计划**: [LCEL Runnable 任务层实施计划](../plan/lcel-runnable-task-layer/implementation.md)

## 1 复盘范围与成功证据

本次交付在既有模型套件与 LangGraph 节点之间增加 LCEL 任务层，将诊断、讲解、出题、评价和总结组合为五个可复用 Runnable，并增加教学角色与评价角色的可选完整任务回退。节点只保留 State 投影和局部更新，原有暂停恢复、条件路由、80 分阈值和最多两次评价协议保持不变。

成功证据：

- `PYTHONPATH=src .venv/bin/pytest -q`：57 项离线测试通过。
- `.venv/bin/python -m compileall -q src tests`：通过。
- `git diff --check`：通过。
- fallback 默认关闭、评价 fallback 继承与覆盖、相同模型 ID 复用、结构化能力独立协商均有测试。
- 主模型异常、主链 Pydantic 校验失败、主备均失败和 `batch` 顺序均有边界测试；主备均失败时主备各执行一次。
- CLI、Web 和 LangGraph 回归测试通过，Web 公开配置只暴露模型 ID 与图片能力。
- 第 03 篇公众号 DOCX 已完成 9 页逐页渲染检查；可访问性审计为 0 项，表格几何、标题层级、PAGE 字段、图片尺寸和压缩包完整性检查通过。

## 2 会话中的主要阻点/痛点

### 2.1 `with_fallbacks()` 的最终异常来源容易误判

- **证据**：主链与备用链均失败时，LangChain 实际重新抛出最初的主链异常，而不是最后一个备用链异常；实现过程中据此修订了测试预期，并在设计文档增加 D-5。
- **影响**：如果只按直觉断言“最后一次异常”，会产生错误测试和不一致的公开说明。

### 2.2 文档索引检查会把注释中的示例链接识别为孤儿

- **证据**：`sync-doc-index --check` 对 `INDEX.md` 的 HTML 注释示例产生 dangling/orphan 提示，而实际 Header 与索引投影没有漂移。
- **影响**：需要人工区分真实索引问题和示例注释造成的误报，降低收尾检查的确定性。

### 2.3 DOCX 对比脚本依赖 PATH 中存在 `python`

- **证据**：`render_and_diff.py` 首次执行时使用裸 `python` 启动渲染脚本，在当前 bundled runtime 环境中出现 `FileNotFoundError`；补充运行时 PATH 后成功完成参考模板与新文档对比。
- **影响**：增加一次环境诊断与重跑，但没有影响最终文档内容或验证结果。

## 3 根因归类

- `with_fallbacks()` 的异常语义属于上游 API 细节，根因落在 **spec/plan**：设计若不显式记录“主备均失败时保留哪个异常”，测试和文章容易各自推断。
- 索引误报属于 **skill**：检查脚本没有忽略 Markdown HTML 注释中的示例内容。
- DOCX 对比启动失败属于 **skill**：脚本通过环境中的裸 `python` 递归启动，而不是沿用当前解释器。
- LCEL 与 CLI 模型的 PromptValue/消息列表差异已由计划中的兼容风险覆盖，并通过 `_as_runnable` 与测试解决，当前无需修改 README 或 AGENTS.md。

## 4 对流程资产的改进建议

- 在后续所有 fallback 设计中明确记录“触发范围、最大尝试次数、主备均失败时的异常来源”。
  - **落点**：spec/plan
  - **优先级**：high
- 让索引同步脚本在解析链接前剔除 HTML 注释，避免把模板示例当成真实文档条目。
  - **落点**：skill（`sync-doc-index`）
  - **优先级**：medium
- 让 DOCX 对比脚本使用 `sys.executable` 调用渲染脚本，或显式接受 Python 解释器参数。
  - **落点**：skill（`documents`）
  - **优先级**：medium
- 保留 `_as_runnable` 的兼容边界测试，避免未来重构时让官方 CLI 适配器收到未转换的 PromptValue。
  - **落点**：spec/plan
  - **优先级**：medium

## 5 建议优先级与后续动作

最高价值的后续动作是把 fallback 的失败语义继续作为设计与测试模板中的必填项。本次设计文档 D-5、验收条件 C-6 和对应单元测试已经完成这一补强，后续实现应复用同一判断方式。

索引注释误报和 DOCX 解释器选择可以在维护相关本地 skill 时一并修复；它们不影响 Learning Coach 运行时，因此本次不创建新的产品 follow-up plan，也不扩大当前交付范围。
