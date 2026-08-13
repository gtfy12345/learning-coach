# Context Engineering 与 Middleware 实施计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-13

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

为 Learning Coach 增加 Runtime Context、动态 Prompt/Tools/Model、确定性学习摘要和有界调用预算，使讲解可以根据学习目标、掌握度与最近错误动态调整，同时保持现有 LangGraph 学习协议兼容。

## 2 背景

第 3 阶段已经把 Prompt、模型、解析器、RAG、流式与回退组合成可复用 Runnable，但上下文仍主要依赖固定字段，工具和模型也在任务构造期确定。第 4 阶段需要把“给模型什么、开放什么能力、使用哪个模型、允许花多少预算”变为显式、可测试且有界的运行策略。

## 3 实施步骤

### Phase 1: Runtime Context 与学习状态

#### 1.1 定义运行上下文、配置与状态契约

新增不可变 Runtime Context、环境配置校验和 State 字段；明确目标与预算不从运行结果反写，掌握度、错误和摘要由节点维护。

#### 1.2 实现确定性上下文组装与摘要

根据目标、掌握度、诊断、反馈、最近错误和资料检索结果生成有界教学上下文、动态提示材料与安全 Context Report。

### Phase 2: 动态 Middleware 讲解任务

#### 2.1 实现动态 Prompt、Tools 与 Model Middleware

接入 `dynamic_prompt`、`wrap_model_call`、`ModelCallLimitMiddleware` 和 `ToolCallLimitMiddleware`，按状态筛选只读工具并选择可选高级模型。

#### 2.2 集成有界讲解 Agent 与兼容降级

工具模型使用有界 Agent；无 Tool Calling 能力的 CLI Provider 复用同一上下文组装并走 LCEL 教学链。两条路径输出统一讲解、来源和报告。

### Phase 3: LangGraph、Web 与 CLI 集成

#### 3.1 更新节点、图与 CLI Runtime Context

让图声明 context schema，节点读取 Runtime Context，评价后更新掌握度、错误和摘要；CLI 增加可选学习目标参数并保留旧调用方式。

#### 3.2 更新 Web API、页面与 SSE 展示

Web 创建会话接受可选学习目标，SessionView 返回掌握度、最近错误、摘要和 Context Report，页面展示动态教学上下文信息。

### Phase 4: 文档、验证与交付

#### 4.1 同步配置、README 与公开边界

更新 `.env.example`、README 路线说明、启动示例、动态能力与安全边界，保持实现和公开描述一致。

#### 4.2 完成回归验证、Git 交付与公众号文章

运行全量测试、Python 编译、前端语法和差异检查；完成提交、推送、合并到 `main`，随后生成并视觉检查 `person` 目录第 04 篇公众号 Word 文章。

## 4 验收标准

- Runtime Context、State 与显式配置边界清楚并有测试。
- Prompt、工具和教学模型确实随目标、掌握度、最近错误和资料动态变化。
- 每次讲解的模型与工具调用均有硬上限，所有循环可终止。
- CLI 无工具模型有清晰兼容路径，不伪造 Tool Calling。
- Web 可输入学习目标并查看掌握度、错误、摘要和安全 Context Report。
- 现有评分阈值、补救次数、暂停恢复、SSE 和旧接口保持通过。
- 全量验证通过，代码已推送并合并到 `main`，第 04 篇文章与最终实现一致。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| Agent 工具循环失控 | 同时设置模型调用和工具调用硬上限，保留 LangGraph 外层终止条件 |
| CLI 模型无法绑定工具 | 按 profile 显式选择 LCEL 兼容路径，不伪造能力 |
| Runtime Context 与 State 混用 | 通过类型与测试锁定真理源和只读边界 |
| 动态模型引入额外必填配置 | 高级模型完全可选，未配置时使用主模型 |
| 摘要额外消耗预算 | 使用确定性摘要，不新增模型调用 |
| 页面暴露敏感上下文 | 只返回安全计数、名称和摘要，不返回资料全文、答案或密钥 |

## 6 关联文档

- [设计文档](../../spec/context-engineering-middleware-design.md)
- [实施 Checklist](./implementation-checklist.md)
- [单元测试计划](./unit-test-plan.md)
- [上一阶段计划](../lcel-runnable-task-layer-follow-up-production-chain/implementation.md)
