# 收官审计契约加固 Follow-up 实施计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-16

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

修复全项目收官审计确认的七组实现漂移，使公开兼容性、安全边界、运行超时、摄取和报告行为重新符合既有设计，并用回归测试覆盖此前盲区。

## 2 背景

原评价、安全、摄取、LangGraph、Context 与 LCEL 计划均已 completed，不能重开旧清单。本 Follow-up 作为本次跨模块修复的唯一 owner，保持既有公开 API、阈值和状态协议兼容。

## 3 实施步骤

### Phase 1: 兼容性、缓存与测试入口

#### 1.1 恢复 Python 3.10 语法兼容

先增加低版本编译验证，再改写嵌套 f-string，不提高最低 Python 版本。

#### 1.2 修复 URL 诊断图片缓存隔离

缓存指纹稳定覆盖标准图片 block 的本地内容与 URL 字段，并增加 URL 正反例。

#### 1.3 修复公开 pytest 入口

让仓库根目录在 console-script pytest 中可导入，并把 README 推荐命令固定为 `python -m pytest`。

### Phase 2: 安全扫描、资料定界与轨迹评价

#### 2.1 饱和 PII 计数并保持扫描不抛出

超过 Schema 上限的同类匹配按 100 报告，保留现有类型与字段。

#### 2.2 加固 Tool Calling 资料上下文

资料工具输出统一使用现有定界符和角色加固声明，不改写资料正文。

#### 2.3 修复多轮补救轨迹唯一性判定

按评价轮次检查事件重复，允许不同合法轮次产生相同 detail。

### Phase 3: Web 摄取与 JSON API 运行边界

#### 3.1 让纯粘贴文本进入统一摄取管线

无文件或 URL 时同样生成 `study_chunks` 和 `ingestion_report`，并保留 `study_material`。

#### 3.2 统一 JSON 与 SSE 的超时和安全错误协议

JSON 路由消费 `_graph_events`，复用超时、取消和安全错误事件；同会话共用单飞锁，锁等待与图执行受同一 Python 3.10 兼容 deadline 约束，摄取移出事件循环，失败创建清理临时资源。输入校验与未知会话错误保持现有状态码。

### Phase 4: Tool 检索复用与模型能力降级

#### 4.1 保证一次 Tool 调用只检索一次

在单次 runtime 中保存结构化检索结果，最终来源与报告复用同一对象；多查询时单数投影统一采用最后一次结果。

#### 4.2 让高级模型降级报告实际执行层级

高级模型不兼容 Tool Calling 时回到主模型，并根据主模型能力选择 Agent 或 LCEL；直接 middleware 与封装路径使用同一能力判断。

### Phase 5: 公开文档与完整验证

#### 5.1 同步 README 与公开契约测试

更新测试入口和必要的兼容说明，确保 README、实现与测试一致。

#### 5.2 执行全量交付验证

运行完整 pytest、Python 3.10 编译、离线 evaluate、前端语法、依赖、计划上下文、文档索引和差异检查。

## 4 验收标准

- Follow-up 设计 C-1 至 C-11 全部有自动化或确定性命令证据。
- 现有 300 项测试保持通过，新增回归不调用网络或真实模型。
- Python 3.10 与当前项目 Python 均可编译源码和测试。
- 两个 JSON API 不泄露模型异常正文，并在配置超时内返回稳定错误。
- 所有 checklist 完成后同步文档生命周期并执行 Bug 记录与交付复盘评估。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| JSON 与 SSE 复用改变错误形状 | 只收紧模型运行错误；保留输入校验和未知会话状态码测试 |
| Tool runtime 临时缓存泄露正文 | 不写 State/API/报告，只在单次对象内持有既有检索结果 |
| 轨迹检查放宽后漏掉 reducer 重放 | 仅在 `assess` 边界重置同轮集合，同轮重复仍失败 |
| 新 pytest 路径影响导入顺序 | 运行完整套件并检查无测试外网络/模型调用 |

## 6 关联文档

- [Follow-up 设计](../../spec/evaluation-security-delivery-follow-up-contract-hardening-design.md)
- [实施 Checklist](./implementation-checklist.md)
- [单元测试计划](./unit-test-plan.md)
- [原评价与安全计划](../evaluation-security-delivery/implementation.md)
- [原评价与安全设计](../../spec/evaluation-security-delivery-design.md)
- [原交付复盘](../../reports/2026-08-15-evaluation-security-delivery-assessment.md)
