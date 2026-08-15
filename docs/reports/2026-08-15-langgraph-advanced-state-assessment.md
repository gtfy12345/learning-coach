# LangGraph 状态图进阶交付复盘报告

> **日期**: 2026-08-15
> **审查人**: Codex

**关联计划**: [LangGraph 状态图进阶实施计划](../plan/langgraph-advanced-state/implementation.md)

## 1 复盘范围与成功证据

本次交付覆盖 State Reducer（错误增量合并与并行事件追加）、Command 导航（诊断后双分支并行 fan-out 与评价后条件跳转）、可与讲解并行的确定性练习准备节点、五个模型节点的瞬态错误重试、纯函数化诊断节点的结果缓存，以及 Web 会话视图与页面的并行轨迹展示。分数阈值、尝试次数、interrupt 恢复协议与非代码路径保持不变。

交付通过以下验证：

- `PYTHONPATH=src .venv/bin/python -m pytest`：250 个测试全部通过（历史各阶段 commit 实测 238 / 249 / 250）。
- `.venv/bin/python -m compileall -q src`：Python 模块编译通过。
- `PYTHONPATH=src .venv/bin/python -m learning_coach --help`：模块启动入口可用。
- `node --check src/learning_coach/static/app.js`：前端脚本语法检查通过。
- `validate_context.py --context docs/plan/langgraph-advanced-state/context.yaml`：计划上下文校验通过。
- `git diff --check`：未发现空白符错误。
- 第 09 篇 Word 文章复用第 08 篇模板生成，postcheck 0 错误；结构审计确认 12 个章节、GitHub 地址、页眉系列号与无本机路径泄漏。

## 2 会话中的主要阻点/痛点

### 2.1 工作日志中的测试计数一度凭记忆填写

- **证据**：阶段一、阶段二日志分别写为 242 / 253 项；通过 git worktree 实测历史 commit 为 238 / 249 项，已修正为实测值。
- **影响**：日志证据精度受损；无代码影响。

### 2.2 双失败补救流的 interrupt 次数最初判断错误

- **证据**：新增"两次失败后终止"图测试时先按两次暂停编写，实际并行补救每轮都会产生新的练习暂停，完整流程为三次 interrupt、四次 invoke；修正后通过。
- **影响**：一次测试迭代，同时暴露了"每轮重入并行入口"这一行为需要在文档中显式说明。

### 2.3 本环境缺少 LibreOffice，无法做逐页视觉检查

- **证据**：第 08 篇交付时通过 PDF 渲染逐页检查；本环境 `soffice` 不存在，改为模板复用 + document.xml 结构审计 + postcheck 脚本验证。
- **影响**：文章版式证据弱于上一阶段，但生成方式与 08 完全同源（同模板、同字体、同色板），风险有限。

### 2.4 resilience.py 提前进入阶段一提交

- **证据**：使用 `git add -A` 时把尚属阶段二的 resilience 模块文件带入了"reducer 合并与并行练习准备"提交；该文件当时未被引用，无功能影响。
- **影响**：提交粒度叙事有小瑕疵。

## 3 根因归类

- 测试计数凭印象写入日志，没有从 pytest 汇总行复制。
  - **类别**：process
- 并行补救流的循环形状（每轮都重新出题并暂停）在测试设计前未先枚举 superstep。
  - **类别**：test-design
- 渲染器缺失属于当前环境差异，模板复用与结构审计已提供替代证据。
  - **类别**：无需仓库改动
- `git add -A` 混入下一阶段文件属于提交流程纪律问题。
  - **类别**：process

## 4 对流程资产的改进建议

- 工作日志中的数字证据一律从命令汇总行复制，不凭记忆回填。
  - **落点**：work-journal
  - **优先级**：high
- 分阶段提交时按显式路径 `git add`，避免整目录暂存带入未接线文件。
  - **落点**：implement
  - **优先级**：medium
- 为"每轮补救重入并行入口"保留端到端回归；若未来把练习准备移出每轮重入，需同步更新 README 与文章描述。
  - **落点**：spec-plan
  - **优先级**：medium
- 在需要逐页视觉检查的交付环境中预装 LibreOffice；否则在计划中把"结构审计 + postcheck"定义为可接受证据。
  - **落点**：documents skill
  - **优先级**：medium

## 5 建议优先级与后续动作

1. 保留三次 interrupt 恢复与两次失败终止的图级回归，作为并行补救循环的形状契约。
2. 下一阶段多 Agent 编排继续沿用"预算上限 + 确定性终止 + 显式合并语义"三重约束。
3. 若引入跨进程缓存或 Send 动态 fan-out，先扩展 resilience 模块边界测试，再接入图装配。
