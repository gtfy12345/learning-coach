# 收官审计契约加固 Follow-up 交付复盘报告

> **日期**: 2026-08-16
> **审查人**: Codex

**关联计划**: [收官审计契约加固 Follow-up](../plan/evaluation-security-delivery-follow-up-contract-hardening/implementation.md)
**关联 Bug**: [BUG-0001](../bugs/BUG-0001.md)

## 1 复盘范围与成功证据

本次交付修复全项目收官审计确认的七组契约漂移：Python 3.10 与测试入口、诊断图片缓存、安全扫描与资料定界、多轮轨迹、Web 摄取与 JSON/SSE 运行边界、Tool 检索复用，以及高级模型能力降级。复核过程中发现的重复 `assess`、同会话并发、锁等待超时、失败资源清理、直接 middleware 路径、多查询投影和 Python 3.10 运行期 API 兼容也已纳入同一 owner 并闭环。

- `PYTHONPATH=src .venv/bin/python -m pytest` 与 console-script `.venv/bin/pytest` 均为 316 项通过。
- Python 3.10 与当前虚拟环境对 `src/`、`tests/` 的完整编译通过；删除 `asyncio.timeout` 的图运行回归通过，Python 3.10 直接执行 deadline helper 的成功/超时路径通过。
- 离线评估集 8 条查询全部命中，hit@3 1.00、MRR 1.00，零模型调用。
- Web 32 项、中间件 15 项、评价 15 项测试通过；三路独立只读复核最终均无 P0–P2 遗留。
- 前端 JavaScript 语法、依赖完整性、计划上下文和 `git diff --check` 通过；文档 Header/INDEX 为 0 violation、0 drift。

## 2 会话中的主要阻点/痛点

### 2.1 编译通过不能代表最低版本运行兼容

- **证据**：嵌套 f-string 首先被 Python 3.10 编译发现；后续复核又发现 `asyncio.timeout()` 只在 Python 3.11+ 存在，而 `compileall` 无法发现运行期属性缺失。
- **影响**：第一轮“Python 3.10 编译通过”之后仍需新增运行级 Red/Green，最终测试从 300 项基线增加到 316 项。

### 2.2 相同语义存在两套执行路径

- **证据**：JSON API 原先直接 `graph.invoke`，SSE 使用 `_graph_events`；资料 Tool 已执行一次检索，`_agent_result` 又执行一次。回归分别复现了 JSON 超时无效/异常正文泄露和一次 Tool 调用两次检索。
- **影响**：超时、安全错误、取消、证据来源和报告可能随入口不同而漂移，且重复 Provider Embedding 会增加成本并产生不一致证据。

### 2.3 初始验收缺少反例组合

- **证据**：首轮修复通过后，独立复核仍依次发现连续重复 `assess`、同会话并发回答、锁等待位于超时外、失败创建遗留 lock、直接 middleware 绕过能力过滤，以及多查询合并来源却只报告最后查询。
- **影响**：正常单轮、单请求、单 Tool 路径均为绿色，但 reducer 重放、并发、取消和多调用组合仍需要返工。

### 2.4 历史索引悬空项降低收口信噪比

- **证据**：`sync-doc-index --check` 对本轮文档给出 0 violation、0 drift，但仍报告 10 个历史 dangling 条目与 4 个不存在文件警告。
- **影响**：本轮交付不受阻，但“索引检查通过”仍需额外区分新增漂移与历史模板债务。

## 3 根因归类

- 最低版本只做语法编译、没有运行 smoke gate。
  - **类别**：AGENTS.md
- spec/plan 的验收场景覆盖了成功、失败和次数上限，但没有系统要求“连续边界重放、并发排队、取消清理、多 Tool 查询、能力不兼容”等反例矩阵。
  - **类别**：spec/plan
- Plan/TDD 审查可以确认文档结构与逐项 Red/Green，却未强制检查“同一语义是否有多个实现”以及“单数报告如何投影多次副作用”。
  - **类别**：skill
- 历史 INDEX 示例条目指向不存在文件，且同步 Skill 按规则只报告、不删除。
  - **类别**：spec/plan

## 4 对流程资产的改进建议

- 在项目交付门禁中增加“最低 Python 运行 smoke”，至少执行 Web 超时 helper、两种 pytest 入口和关键模块导入；不能只运行 `compileall`。
  - **落点**：AGENTS.md
  - **优先级**：high
- 在计划评审与 TDD 模板中增加反例组合表：重复边界事件、同资源并发、锁等待、取消后资源计数、超过 Schema 上限、多次 Tool 调用、直接/封装调用路径和模型能力不匹配。
  - **落点**：plan-review / tdd skill
  - **优先级**：high
- 对所有有副作用的工具规定“执行结果是后续投影的唯一对象”；若公开 Schema 只有单数报告，spec 必须明确多调用时选最后一次、聚合或拒绝，不能隐式混合。
  - **落点**：spec/plan
  - **优先级**：medium
- 单独建立文档卫生任务确认历史 dangling INDEX 条目的 owner；在未确认前继续遵守同步 Skill 的“不自动删除”约束。
  - **落点**：spec/plan
  - **优先级**：low

## 5 建议优先级与后续动作

1. 下一轮最高价值动作是在 AGENTS/CI 交付矩阵加入 Python 3.10 运行 smoke，并让它和当前解释器全量测试同时执行。
2. 随后更新 plan-review/TDD 的反例检查提示，优先覆盖并发、取消、轮次边界和多调用投影；这些正是本轮独立复核实际捕获的问题。
3. 中优先级是为未来 side-effecting Tool 的多调用报告语义写入对应 spec，避免再次出现“来源来自多次、报告只来自一次”。
4. 历史 10 个 dangling INDEX 项保持原样，待独立文档治理任务确认后再处理，不与本次代码交付混合。
