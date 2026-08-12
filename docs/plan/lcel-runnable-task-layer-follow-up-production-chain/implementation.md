# LCEL 生产级组合 Follow-up 实施计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-12

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

在已完成的 LCEL Runnable 任务层上实现高级组合、确定性内存 RAG、完整 Runnable 执行接口、Web SSE 流式体验、取消与超时、可选追踪和 Runnable 图导出，并保持现有 LangGraph 学习协议和 JSON API 兼容。

## 2 背景

原计划已经完成 Prompt、模型、解析器和有限回退的五类任务链，但尚未覆盖并行/透传/赋值组合、真实检索上下文、流式产品接口、取消超时与追踪。用户确认以本地内存方案补齐两篇 LCEL 文章涉及的技术点，代码完成后同步更新第 03 篇公众号文章。

## 3 实施步骤

### Phase 1: 高级组合与内存 RAG

#### 1.1 定义资料切块、检索与来源契约

新增确定性纯文本切块与词法 Retriever，限制资料长度、片段数量和返回 top-k；增加 `StudySource`、`GroundedTeaching` 以及对应 State/SessionView 字段。

#### 1.2 组合真实教学 RAG Runnable

使用 `RunnableParallel`、`RunnablePassthrough`、`RunnableLambda`、`RunnableAssign` 和显式 `RunnableSequence` 组装教学输入与完整任务回退；节点把文本和来源写回局部 State。

### Phase 2: 执行接口与图流式事件

#### 2.1 补齐异步、批处理、流式和图导出契约

确保标准模型与 CLI 适配器均可通过 `invoke`、`ainvoke`、`batch` 和 `stream` 使用；增加按任务名查找和 Mermaid 图导出，并传递稳定 RunnableConfig。

#### 2.2 让文本节点发出可聚合 token 事件

教学、出题和总结节点消费 Runnable stream，通过 LangGraph custom stream 发出阶段、token 和来源事件，完成后再写入完整 State；普通 invoke 路径保持可用。

### Phase 3: Web SSE、取消与超时

#### 3.1 增加兼容的 SSE 服务接口

新增流式创建会话和恢复回答接口、SSE 编码、服务端超时及取消传播；保留原 JSON 接口，错误响应不泄露敏感内容。

#### 3.2 接入浏览器流式交互和学习资料输入

页面增加可选资料文本框，使用 Fetch 流解析 SSE、增量展示讲解/练习/总结，并提供取消按钮；旧浏览器错误路径仍可清晰恢复。

### Phase 4: 可观测性、公开说明与完整验证

#### 4.1 增加安全追踪配置与配置展示

补充 LangSmith project、任务标签和安全 metadata，增加 Web 超时环境配置与脱敏公开配置测试。

#### 4.2 同步 README、文章并完成回归验证

先完成实现、离线完整测试、编译和差异检查，再更新 `/Users/ray/Desktop/person/03-Runnable与LCEL：把一次模型调用组合成可复用任务.docx`，执行 DOCX 渲染与布局验证。

## 4 验收标准

- 真实教学路径使用五种高级 Runnable 组合并返回可追踪来源。
- 无学习资料时现有流程、评分、循环和暂停恢复行为不变。
- 四种 Runnable 执行入口均由离线测试验证。
- Web SSE 支持有序事件、浏览器取消和服务端超时，原 JSON API 保持兼容。
- LangSmith 默认关闭，显式 metadata 不含资料、回答、Prompt、输出和密钥。
- Mermaid 图可以导出且不包含运行时敏感输入。
- 完整测试、编译和 `git diff --check` 通过；公众号文章与最终实现一致并完成视觉校验。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| RunnableLambda 阻断原生 token stream | 把阻塞适配器放在模型之前，文本解析器保持可 transform；用多块 fake 模型验证增量结果 |
| 取消后 checkpointer 留下不完整数据 | 节点先聚合完整结果再返回局部 State，取消异常不被 fallback 吞掉 |
| SSE 与 JSON 路径行为漂移 | 两套接口共用同一 SessionService 校验、线程 ID 和 SessionView 投影 |
| 资料正文进入追踪或错误消息 | RunnableConfig 只传布尔值、计数和随机会话 ID；错误事件使用稳定公开消息 |
| 词法检索对中文分词较弱 | 同时使用规范化词元和连续字符片段，保持确定性并公开其边界 |
| 公众号文档先于代码而失真 | 文章更新固定在全部实现与验证通过之后执行 |

## 6 关联文档

- [设计文档](../../spec/lcel-production-chain-design.md)
- [实施 Checklist](./implementation-checklist.md)
- [单元测试计划](./unit-test-plan.md)
- [原实施计划](../lcel-runnable-task-layer/implementation.md)
- [原设计文档](../../spec/lcel-runnable-task-layer-design.md)
- [原交付复盘](../../reports/2026-08-12-lcel-runnable-task-layer-assessment.md)

## 7 完成验证

- `PYTHONPATH=src .venv/bin/pytest -q`：73 项离线测试通过。
- `.venv/bin/python -m compileall -q src tests`：通过。
- `node --check src/learning_coach/static/app.js`：通过。
- `git diff --check`：通过。
- 第 03 篇公众号 DOCX 已更新；内容提取、压缩包完整性、标题结构、表格几何、无障碍审计和 macOS 系统预览均通过。
- 内置 LibreOfficeDev 渲染器存在中文字体替换问题；已确认这是渲染环境差异，文档在 macOS Quick Look 中中文、表格和分页显示正常。
