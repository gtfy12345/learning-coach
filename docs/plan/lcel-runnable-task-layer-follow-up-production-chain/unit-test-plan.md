# LCEL 生产级组合 Follow-up 单元测试计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-12

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 1 目标

使用离线 fake/stub 模型验证高级 Runnable 组合、确定性内存检索、四种执行入口、LangGraph custom stream、Web SSE、取消超时、追踪元数据和原流程兼容，不调用真实 Provider、LangSmith 或网络。

## 2 测试策略

- 在 `tests/test_retrieval.py` 验证纯文本切块、中文/英文相关性、稳定排序、top-k、无命中和输入上限。
- 扩展 `tests/test_runnables.py` 验证组合图、来源输出、invoke/ainvoke/batch/stream、fallback 和安全配置。
- 扩展 `tests/test_graph.py` 验证来源 State、custom token 事件、取消前不写半截节点状态及既有中断路由。
- 扩展 `tests/test_web.py` 验证新旧接口、SSE 事件顺序、资料输入、超时错误、配置脱敏和页面控件。
- 每个 checklist item 先新增失败测试，再提交最小实现并运行相邻回归。

## 3 测试阶段

### Phase 1: 高级组合与内存 RAG 测试

#### 1.1 Retriever 边界测试

验证切块 ID 稳定、资料长度上限、中文/英文查询、无命中、相关度排序和 top-k 上限。

#### 1.2 教学组合与来源测试

验证教学 Prompt 只使用命中片段，返回 `GroundedTeaching`，Runnable 图包含预期组合节点，无资料时返回空来源。

### Phase 2: 执行接口与图流式测试

#### 2.1 Runnable 统一接口测试

验证 invoke 与 ainvoke 等价、batch 保序、stream 多块可聚合、CLI 型同步模型单块退化，以及未知图名错误。

#### 2.2 LangGraph custom stream 测试

验证 status、token、sources 和最终 values 的顺序，且取消或模型异常不会提交半截文本。

### Phase 3: Web SSE 与兼容测试

#### 3.1 SSE 服务与错误测试

验证创建和回答的 SSE content type、JSON data 编码、有序 done、未知会话、输入校验、超时和模型错误。

#### 3.2 浏览器与 JSON 回归测试

验证页面包含资料输入与取消控件；原 JSON 创建/回答、图片输入和补救循环继续通过。

### Phase 4: 可观测性与完整回归测试

#### 4.1 追踪配置和脱敏测试

验证 RunnableConfig 的 run name、tags、metadata 白名单和 Web 公开超时，确保不包含资料、回答、Prompt、输出或密钥。

#### 4.2 完整验证

运行完整 pytest、compileall、`git diff --check`，再对更新后的第 03 篇 DOCX 执行内容提取、逐页渲染和包完整性检查。

## 4 通过标准

- 正常、无命中、主链失败、主备失败、取消、超时和未知会话均有断言。
- fake 模型的响应顺序固定，不使用 `.env`、真实 API Key、LangSmith 或网络。
- 完整套件无回归，文章中的命令、接口、代码片段和限制与仓库一致。

## 5 关联文档

- [设计文档](../../spec/lcel-production-chain-design.md)
- [实施计划](./implementation.md)

## 6 验证结果

- 73 项离线测试全部通过，覆盖检索、Runnable 四类执行入口、custom stream、SSE、取消、超时、回退、追踪元数据和既有 JSON API。
- Python 编译、前端 JavaScript 语法检查与 `git diff --check` 通过。
- DOCX 必需内容与禁用小节检查通过，包完整性、表格几何和无障碍审计通过，macOS 系统预览显示正常。
