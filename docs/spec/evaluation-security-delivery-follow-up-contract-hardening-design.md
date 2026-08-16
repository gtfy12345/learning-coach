# 收官审计契约加固设计文档

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-16

## 1 概述

本 Follow-up 修复收官审计发现的实现漂移：Python 3.10 兼容、诊断图片缓存隔离、安全扫描与资料定界、补救轨迹评价、Web JSON API 超时与错误脱敏、粘贴资料统一摄取、Tool Calling 检索复用与高级模型能力降级，以及公开测试入口。既有学习流程、80 分阈值、最多两次评价、状态持久化语义和公开响应字段保持兼容。

## 2 设计目标

- 保持 README 声明的 Python 3.10+ 语法兼容，并提供可复现的测试入口。
- 诊断缓存键覆盖本地图片内容与 URL 图片标识，不跨不同题图复用结果。
- 安全扫描对有界输入永不抛出，LCEL 与 Tool Calling 两条资料路径统一定界加固。
- 合法多轮补救事件可重复出现，但同一评价轮次内的 reducer 重放仍能被识别。
- Web JSON 与 SSE API 共享同一有界图运行、超时和安全错误投影。
- 粘贴文本始终进入统一 Loader、Splitter 与会话索引管线，同时保留旧 `study_material` 字段。
- 一次资料工具调用只执行一次检索，报告反映实际模型层级与工具使用。

## 3 架构与真理源

### 3.1 兼容与缓存

Python 最低版本继续以 README 的 3.10 为真理源，不提高版本门槛。诊断缓存仍只在进程内存在；缓存键由主题和标准图片 block 的稳定序列化摘要组成，包含 `type`、`base64`、`url` 与 `mime_type` 等实际字段，不保存原始图片数据或 URL 到持久化状态。

### 3.2 安全与轨迹

`PIIFinding.count` 的 Schema 上限 100 保持不变，检测器在构造 Schema 前饱和到该上限。资料正文不改写，但进入模型上下文前统一经过 `hardened_study_context`。轨迹的“无重复”按评价轮次分段：`assess` 事件结束当前轮次；不同轮次可以有相同教学事件，同一轮次内的完全相同事件仍视为 reducer 重放。

### 3.3 Web 运行协议

SSE 的 `_graph_events` 是图运行、超时、取消与安全错误投影的唯一实现。两个 JSON API 消费同一事件流并只返回最终 `state`；同一会话的 JSON/SSE 运行共用单飞锁，Python 3.10 兼容的绝对 deadline 同时约束锁等待与图事件消费。资料摄取在线程中准备，创建失败、超时、取消或空流会清理未注册 runtime 与 lock。`run_timeout` 映射为 504，其他运行失败映射为 503，响应仅包含稳定错误码和安全消息。输入校验与未知会话仍保留现有 422/404 用户可操作信息。

### 3.4 摄取与 Tool Calling

粘贴文本在有无其他资料时都包装为 `pasted-text.txt` 并进入摄取管线，同时继续写入兼容字段 `study_material`。Tool Calling 的检索结果保存在单次 `TeachingAgentRuntime` 的临时映射中，供工具返回正文和最终结果投影共同读取；该映射不写入 LangGraph State、checkpoint、API 或长期记忆。若模型执行多个不同资料查询，单数 `sources`、`retrieval_report` 与 `graph_report` 共同投影最后一次查询结果，避免混合不同证据集合。

高级模型只有在选中且具备 Tool Calling 能力时才标记为 `advanced`。若其能力不兼容，则回到主模型：主模型支持工具时继续 Agent 路径，否则进入主模型 LCEL 路径，报告始终描述实际执行层级。

## 4 兼容边界

- 不新增或删除公开 API 路由、环境变量、State 字段或响应字段。
- 不改变诊断、教学、练习、评价、补救、审批与总结的节点顺序。
- 不改变 PII 类型、计数 Schema 上限或“只标记不阻断”的策略。
- 不持久化 Tool 检索临时结果，不把资料正文写入 Context Report。
- JSON API 的模型运行错误由不稳定异常正文收紧为稳定安全错误；这是已有公开安全契约的修复。

## 5 验收标准

| ID | 场景 | Given | When | Then | Phase |
|----|------|-------|------|------|-------|
| C-1 | Python 3.10 | 全部源码与 Web deadline helper | 使用 Python 3.10 编译并运行 helper 成功/超时路径 | 无语法或运行期兼容错误 | 1 |
| C-2 | URL 图片缓存 | 相同主题、不同 URL 图片 | 生成缓存键 | 缓存键不同 | 1 |
| C-3 | 测试入口 | 已激活项目虚拟环境 | 执行 README 测试命令 | 完整收集并通过 | 1 |
| C-4 | 高频 PII | 同类匹配超过 100 次 | 执行安全扫描 | 不抛异常且计数为 100 | 2 |
| C-5 | Agent 资料加固 | 工具检索命中含注入文字的资料 | ToolMessage 返回模型 | 含定界符与角色加固声明 | 2 |
| C-6 | 多轮轨迹 | 合法执行两次评价 | 生成阶段报告 | 轨迹检查全部通过 | 2 |
| C-7 | 粘贴资料 | 仅提交纯文本资料 | 创建 Web 会话 | 同时生成 chunks 与 ingestion report | 3 |
| C-8 | JSON API 超时/失败 | 慢模型、并发回答、空流或模型异常 | 调用 JSON/SSE 创建/回答接口 | 锁等待与执行有界、无资源残留且不泄露异常正文 | 3 |
| C-9 | Tool 检索 | 模型调用一次或多次资料工具 | 生成讲解与来源报告 | 每个 Tool 只检索一次且单数投影来自同一结果 | 4 |
| C-10 | 高级模型降级 | 高级模型不支持工具 | 低掌握度执行讲解 | 使用主模型路径且报告 primary | 4 |
| C-11 | 全量回归 | 修复全部完成 | 执行项目验证矩阵 | 测试、评估、编译与静态检查通过 | 5 |

## 6 设计决策记录

| ID | 决策 | 结论 | 理由 |
|----|------|------|------|
| D1 | Python 兼容 | 改写单处语法，不提高最低版本 | 保持公开安装契约 |
| D2 | PII 计数 | 检测器饱和到 Schema 上限 | 保持结构稳定且扫描不抛出 |
| D3 | 轨迹唯一性 | 按 `assess` 分段检查 | 区分合法补救与同轮 reducer 重放 |
| D4 | JSON 运行 | 复用 SSE 图事件实现 | 避免两套超时、取消和错误语义继续漂移 |
| D5 | Tool 结果 | 单次 runtime 临时缓存 | 避免重复 Provider Embedding 与证据漂移 |
| D6 | 高级模型能力 | 不兼容时回到主模型 | 报告实际执行路径并保留可用工具 |

## 7 非目标

- 不新增公网认证、持久化向量库或强隔离执行环境。
- 不改变模型 Provider、评分标准、预算上限或重试次数。
- 不扩展 PII/注入规则种类，不调整检索算法质量阈值。
- 不处理本轮七点之外的低优先级 CLI 帮助或文件签名增强。

## 8 关联文档

- [Follow-up 实施计划](../plan/evaluation-security-delivery-follow-up-contract-hardening/implementation.md)
- [原评价与安全设计](./evaluation-security-delivery-design.md)
- [Context Engineering 设计](./context-engineering-middleware-design.md)
- [多模态摄取设计](./multimodal-material-ingestion-design.md)
- [LangGraph 进阶设计](./langgraph-advanced-state-design.md)
- [LCEL 生产链设计](./lcel-production-chain-design.md)
