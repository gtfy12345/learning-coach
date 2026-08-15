# LangGraph 状态图进阶实施计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-15

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

用 Reducer、Command、节点级 Retry 与 Cache 升级现有 LangGraph 学习闭环，让讲解、练习准备、评价和补救在并行分支与瞬态失败场景下保持有界、可恢复且可测试，同时不改变任何阈值、预算和暂停恢复协议。

## 2 背景

当前图是严格串行的：诊断 → 收集 → 讲解 → 出题 → 收集 → 评价 → 补救或总结。出题节点内部同时完成"判定练习类型 + 生成练习 + 拼装问题"，讲解节点失败只能靠 LCEL 备用链兜底，节点本身没有重试；重复主题的重复诊断没有任何复用；并行写 State 字段会触发 LangGraph 默认覆盖语义的隐患。第 09 阶段需要在保持公开行为兼容的前提下补齐这些运行时能力。

## 3 实施步骤

### Phase 1: Reducer、并行分支与 Command 导航

#### 1.1 定义 State Reducer 与学习事件契约

为 `recent_errors` 定义增量合并 Reducer，新增 `learning_events` 有界追加 Reducer、`practice_kind` 字段和 `LearningEvent` Schema。

#### 1.2 拆分确定性练习准备节点

新增 `prepare_practice`：只依赖主题与工具预算判定练习类型，并对代码主题预生成确定性练习与工具轨迹。

#### 1.3 用 Command 实现 fan-out 与条件导航

`collect_diagnostic` 返回 `Command(goto=["teach", "prepare_practice"])`；`assess` 返回 `Command(goto=...)` 并只提交错误增量；`make_quiz` 改为 fan-in 汇合点并保留直调兼容。

### Phase 2: 节点级 Retry 与瞬态错误分类

#### 2.1 实现瞬态错误分类与默认重试策略

新增 `resilience.py`：瞬态异常判定（内置超时/连接错误 + Provider 类名白名单）、`default_model_retry_policy()`。

#### 2.2 为模型节点挂接 RetryPolicy

五个模型节点挂接可注入的重试策略；收集节点与确定性节点不重试；验证重试与 LCEL 备用链叠加仍有界。

### Phase 3: 节点级 Cache

#### 3.1 纯函数化诊断节点并定义缓存键

`make_diagnostic` 只返回诊断字段；`diagnostic_cache_key` 以主题与图片内容摘要生成稳定键。

#### 3.2 接入 CachePolicy 与 GRAPH_NODE_CACHE 开关

图编译挂接 `InMemoryCache`，环境变量默认开启、显式注入优先；验证命中不重复调用模型。

### Phase 4: 循环终止验证与 Web 集成

#### 4.1 端到端验证有界补救与暂停恢复

覆盖通过阈值、未通过阈值、次数上限三个边界，并验证并行 fan-out 下的 interrupt 恢复协议不变。

#### 4.2 接入 Web 会话视图与页面展示

SessionView 暴露 `learning_events` 与 `practice_kind`，页面显示并行准备轨迹与练习类型。

### Phase 5: 公开文档、完整验证与公众号文章

#### 5.1 更新 README 与 .env.example

说明 Reducer 语义、并行结构、重试分类、缓存行为、开关与新的边界条目。

#### 5.2 完成全量回归、文档生命周期同步与交付复盘

运行全量测试、编译、前端语法、计划上下文、索引和差异检查，并生成证据化复盘。

#### 5.3 生成并检查第 09 篇公众号文章

在 `person` 目录生成 Word 文章，包含 GitHub 完整地址、架构、关键实现、边界和下一阶段。

## 4 验收标准

- 并行 fan-out 的两个分支事件都进入 `learning_events`，断言不依赖分支顺序。
- 评价节点提交增量错误，State 中列表仍去重且最多 3 条；三个循环边界行为不变。
- 瞬态错误重试后成功，非瞬态错误一次失败；默认策略每节点最多 2 次尝试。
- 相同主题与题图复用诊断结果；关闭 `GRAPH_NODE_CACHE` 后每次重新调用。
- `interrupt()` payload、`thread_id` 恢复协议、非代码主题与零预算路径全部保持兼容。
- 完整测试通过，第 09 篇文章与实现一致并包含 `https://github.com/gtfy12345/learning-coach`。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 并行分支写同一字段被覆盖 | 共享写只保留 `learning_events`，并用 Annotated Reducer 显式合并 |
| 缓存回放携带错误上下文 | 诊断节点瘦身为纯函数，learning_goal 等入口字段由调用方显式传入 |
| 重试放大模型调用 | max_attempts=2、瞬态白名单、与备用链叠加的最坏调用数显式写进文档 |
| 类名启发式误判 | 白名单保持窄集合，未知异常一律不重试并按原语义上抛 |
| 影响原串行流程 | 阈值、尝试次数、interrupt 协议与字段结构全部不变，端到端回归覆盖 |
| 事件无界增长 | Reducer 保留最近 30 条，字段为纯展示用途 |

## 6 关联文档

- [设计文档](../../spec/langgraph-advanced-state-design.md)
- [实施 Checklist](./implementation-checklist.md)
- [单元测试计划](./unit-test-plan.md)
- [上一阶段实施计划](../tool-calling-react-code-practice/implementation.md)
