# LCEL Runnable 任务层单元测试计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-12

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 1 目标

用 fake/stub 模型验证 fallback 配置、能力协商、LCEL 组合、输出契约、批处理、异常终止以及现有 LangGraph 行为，测试不得访问真实 Provider 或官方 CLI。

## 2 测试策略

- 在 `tests/test_model.py` 覆盖设置解析、默认继承和备用结构化模型协商。
- 新增 `tests/test_runnables.py` 覆盖五类 Runnable 的 Prompt、解析、回退和批处理。
- 在 `tests/test_graph.py`、`tests/test_web.py` 覆盖节点迁移后的流程兼容和脱敏公开配置。
- 每项实现先增加失败测试，再完成最小实现和相邻回归验证。

## 3 测试阶段

### Phase 1: 备用模型与能力契约测试

#### 1.1 配置默认与继承

验证未设置 fallback 时为 `None`，只设置教学 fallback 时评价 fallback 继承，单独设置评价 fallback 时可覆盖。

#### 1.2 角色能力协商

验证教学、诊断和评价备用模型各自绑定正确实例，结构化输出方法独立选择。

### Phase 2: Runnable 组合测试

#### 2.1 Prompt 与输出契约

验证五类任务输入进入正确 Prompt；文本结果为 `str`，诊断和评价结果为 Pydantic 对象，图片 content block 原样进入诊断消息。

#### 2.2 回退、批处理与失败终止

验证主模型异常、主链结构校验失败时切换备用链；验证 `batch` 返回有序结果；主备均失败时异常向上传播且调用次数有界。

### Phase 3: 图与公开配置回归测试

#### 3.1 图协议兼容

验证两个 interrupt、`Command(resume=...)`、条件路由、补救次数上限和最终总结保持不变。

#### 3.2 配置与完整回归

验证 Web 配置只暴露主/备用模型 ID 和图片能力，不暴露密钥；运行完整测试、`compileall` 和差异格式检查。

## 4 通过标准

- 正常路径、解析失败路径、主备均失败路径和循环终止边界均有断言。
- 测试响应顺序固定，不使用真实密钥、网络或模型费用。
- 完整测试套件通过，且 `git diff --check` 无错误。

## 5 关联文档

- [设计文档](../../spec/lcel-runnable-task-layer-design.md)
- [实施计划](./implementation.md)

## 6 验证结果

- 模型配置、五类 Runnable、完整任务回退、批处理、节点委托、图协议和 Web 脱敏配置均有离线测试覆盖。
- 完整测试结果为 57 项通过；未访问真实 Provider、官方 CLI 或网络服务。
