# 多 Agent 与任务编排交付复盘报告

> **日期**: 2026-08-15
> **审查人**: Codex

**关联计划**: [多 Agent 与任务编排实施计划](../plan/multi-agent-orchestration/implementation.md)

## 1 复盘范围与成功证据

本次交付把讲解阶段升级为有界的多 Agent 子图：编排器 Router 制定教学计划（焦点 ≤ 3、维度 ≤ 3、修订 ≤ 1），研究 Agent 经 Send 按焦点并行取证并在证据汇合后构造 prepared_retrieval 移交教师，教师 Agent 复用 teach_stream 起草，审查 Agent 经 Send 按维度并行检查并通过有界 Handoff 触发至多一次修订。子图作为主图 teach 节点接入，诊断/练习/评价/总结与 interrupt 协议保持不变。

交付通过以下验证：

- `PYTHONPATH=src .venv/bin/python -m pytest`：263 个测试全部通过（新增 test_agents 13 项，其余为既有回归适配）。
- `.venv/bin/python -m compileall -q src`：Python 模块编译通过。
- `node --check src/learning_coach/static/app.js`：前端脚本语法检查通过。
- `validate_context.py --context docs/plan/multi-agent-orchestration/context.yaml`：计划上下文校验通过。
- `git diff --check`：未发现空白符错误。
- 第 10 篇 Word 文章复用第 09 篇模板生成，postcheck 0 错误；结构审计确认 12 个章节、GitHub 地址、页眉系列号与无本机路径泄漏。

## 2 会话中的主要阻点/痛点

### 2.1 子图流式事件默认不透出到父图

- **证据**：接入子图后，父图 stream 中丢失 teaching token/status 事件；实验证明子图自定义事件需要 astream/stream 传 subgraphs=True，且 values 部分带命名空间。
- **影响**：若未发现，浏览器讲解打字机效果会静默消失。修复为 subgraphs=True + 按空命名空间过滤父级 values，并保留回归测试。

### 2.2 子图共享通道终值经父图 Reducer 会重复累加

- **证据**：实验显示子图回传的是通道终值而非增量；预置事件会在父图 append 后重复出现。
- **影响**：这是本阶段最关键的设计约束；采用受限 input/output schema 只回传增量，并用"事件详情无重复"回归锁死。

### 2.3 文档 commit 先于 INDEX 更新执行

- **证据**：阶段一提交时两个 INDEX 因文件重读校验失败未随提交进入，事后 amend 补齐。
- **影响**：无远端影响；流程上应先完成全部文件编辑再统一提交。

### 2.4 既有 FakeChatModel 短草稿与 clarity 阈值擦边

- **证据**：clarity 下限最初考虑 30 字符，会误伤既有 fake 草稿（最短 14 字符）；调整为 12 并以独立短草稿用例覆盖失败分支。
- **影响**：一轮阈值校准；规则取向记录为"宁松勿严"。

## 3 根因归类

- 子图流式与状态合并语义属于 LangGraph 版本行为，仓库文档此前未覆盖。
  - **类别**：spec-plan（已在设计文档 D3/D4 固化）
- 提交流程先于编辑完成的时序问题。
  - **类别**：process
- 审查阈值属于规则参数选择，靠既有回归暴露。
  - **类别**：test-design

## 4 对流程资产的改进建议

- 引入子图/嵌套图时，先写最小语义实验（流式透出、通道合并）再定接口契约。
  - **落点**：spec-plan
  - **优先级**：high
- "事件详情无重复"与"subgraphs 事件透出"保留为固定回归，防止后续升级 langgraph 时静默破坏。
  - **落点**：tests
  - **优先级**：high
- 提交前以显式 `git status` 核对暂存集合，INDEX 与正文同批提交。
  - **落点**：implement
  - **优先级**：medium

## 5 建议优先级与后续动作

1. 下一阶段涉及持久化记忆与 Time Travel 时，继续沿用"先实验 checkpointer 语义、再定契约"的做法。
2. 若未来审查 Agent 升级为模型化评审，需先为其增加独立的模型预算与确定性终止理由。
3. 工具型教学 Agent 的证据注入路径暂保持现状；若要统一，需在中间件工具层增加 prepared evidence 读取。
