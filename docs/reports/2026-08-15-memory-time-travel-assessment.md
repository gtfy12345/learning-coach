# 记忆、暂停恢复与 Time Travel 交付复盘报告

> **日期**: 2026-08-15
> **审查人**: Codex

**关联计划**: [记忆、暂停恢复与 Time Travel 实施计划](../plan/memory-time-travel/implementation.md)

## 1 复盘范围与成功证据

本次交付为学习闭环补上时间维度：SQLite 检查点持久化与 CLI `--thread-id` 跨进程恢复、Store 长期记忆（幂等会话键 + 聚合画像召回注入确定性摘要）、代码执行审批中断（拒绝零执行）与 Time Travel（脱敏里程碑列表、快照分叉重入中断、安全状态比较）。默认进程内行为与 interrupt 协议保持不变。

交付通过以下验证：

- `PYTHONPATH=src .venv/bin/python -m pytest`：277 个测试全部通过（新增 test_memory 11 项与 Web 历史/分叉/记忆 2 项，既有代码路径测试补审批步骤）。
- `.venv/bin/python -m compileall -q src/learning_coach`、`python -m learning_coach --help`、`node --check` 全部通过。
- `validate_context.py`：计划上下文校验通过；`git diff --check` 无空白符错误。
- 第 11 篇 Word 文章 postcheck 0 错误，结构审计确认 12 个章节、GitHub 地址与无本机路径泄漏。

## 2 会话中的主要阻点/痛点

### 2.1 SqliteStore 连接事务与 autocommit

- **证据**：节点内 `store.put` 在默认隔离级别下报 "cannot start a transaction within a transaction"；连接改 `isolation_level=None` 后恢复。
- **影响**：设计前提修正；已在 memory 构造器中固定 autocommit 并留测试覆盖重开读取。

### 2.2 fork 语义两轮实验才收敛

- **证据**：跨线程 `update_state(checkpoint_id)` 不携带源值；最终配方为"快照 values + `as_node=前驱` 显式复制"。
- **影响**：与第 10 阶段子图"终值经父图 Reducer"同属一族语义坑；两次实验成本换来可复用结论并写入设计决策 D4。

### 2.3 审批默认开启放大既有测试改动

- **证据**：代码路径测试需补一步审批 resume；Web 测试新增 approval 断言；拒绝轮的补救重入会覆盖工具轨迹，断言改用持久化的报告字段。
- **影响**：一次性测试维护；同时暴露"每轮重入并行入口"对轨迹字段的覆盖语义，复盘记录。

### 2.4 文章生成脚本模板指向错误

- **证据**：生成脚本模板串仍指向第 09 篇，页眉系列号未替换；产物格式一致（同版式模板），修正页眉后验证通过，第 09/10 篇未受影响。
- **影响**：仅页眉一次返工；脚本拼接方式应校验模板路径。

## 3 根因归类

- SQLite/跨线程语义属于组件行为差异，先实验后定契约的做法有效。
  - **类别**：spec-plan
- 审批闸门改变代码路径步数，属预期内的兼容测试维护。
  - **类别**：test-design
- 生成脚本复用时模板路径未参数化。
  - **类别**：process

## 4 对流程资产的改进建议

- 涉及持久化组件的交付，把"连接模式、事务语义、跨线程复制行为"列为前置实验项。
  - **落点**：spec-plan
- 保留"重放幂等""原线程不变""事件无重复"三类回归作为耐久语义的常驻门禁。
  - **落点**：tests
- 文章生成脚本模板路径参数化并在生成后断言页眉与系列号。
  - **落点**：documents skill
- 若后续提供 Web 会话注册表恢复，应先设计线程列表的权限与脱敏投影。
  - **落点**：spec-plan
- **优先级**：以上均为 medium，第一项 high。

## 5 建议优先级与后续动作

1. 收官阶段先梳理评价数据面（掌握图谱、评估集），再决定长期记忆字段的扩展。
2. 面向公网部署前，为审批与分叉 API 补充操作审计日志。
3. 若引入 Postgres 级 Checkpointer，重复本阶段的"先实验后定契约"流程。
