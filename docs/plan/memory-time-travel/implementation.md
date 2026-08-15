# 记忆、暂停恢复与 Time Travel 实施计划

> **版本**: 1.0
> **状态**: draft
> **更新日期**: 2026-08-15

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

为学习闭环增加持久化 Checkpoint、跨会话长期记忆、代码执行审批中断和 Time Travel（里程碑列表、分叉重答、状态比较），同时保持默认运行行为、interrupt 协议与补救循环不变。

## 2 背景

第 10 阶段结束时，会话仍只活在单个进程内存里：服务重启任务即丢失；两个会话之间没有共享的学习画像；本地执行学习者代码是全系统唯一执行不可信输入的动作，却不需要任何确认；也没有手段回到某个历史节点换一种回答重来。第 11 阶段用 LangGraph 的 Checkpointer、Store 与 interrupt 原语补齐这四件事。

## 3 实施步骤

### Phase 1: 持久化与记忆基础设施

#### 1.1 定义检查点/记忆/审批设置与构造器

`CHECKPOINT_DB_PATH`、`MEMORY_DB_PATH`、`CODE_EXECUTION_APPROVAL` 解析；SqliteSaver/SqliteStore/InMemory 组件构造与依赖安装。

#### 1.2 实现记忆召回与写入

画像聚合、幂等会话键、召回摘要与 `context_summary` 注入行。

### Phase 2: 审批闸门与图接入

#### 2.1 实现 approve_execution 节点与拒绝评价路径

仅代码练习中断审批；批准正常运行执行器，拒绝构造 rejected 报告。

#### 2.2 接入 recall/remember/approve 节点并保持协议不变

START 前召回、总结后写入、练习收集后审批；更新受影响测试。

### Phase 3: Time Travel

#### 3.1 实现里程碑列表与快照 fork

get_state_history 脱敏投影；快照 values 复制到新线程并重新进入中断点。

#### 3.2 实现状态比较

安全字段 diff，用于分叉基线对比。

### Phase 4: CLI 与 Web 集成

#### 4.1 CLI 持久恢复与审批输入

`--thread-id` 跨进程恢复；审批 kind 的命令行交互。

#### 4.2 Web 历史/分叉 API 与页面

历史与分叉端点、审批卡片、时间旅行面板与分叉对比横幅。

### Phase 5: 公开文档、完整验证与公众号文章

#### 5.1 更新 README 与 .env.example

新能力、配置、边界与体验方式说明。

#### 5.2 完成全量回归、文档生命周期同步与交付复盘

#### 5.3 生成并检查第 11 篇公众号文章

## 4 验收标准

- 持久化开启后跨进程恢复；默认行为不变。
- 画像写入幂等；新会话摘要含长期记忆行。
- 代码练习必经审批；拒绝后零执行且继续闭环。
- 分叉不动原线程；里程碑与比较输出脱敏有界。
- 全量测试通过；第 11 篇文章与实现一致并包含仓库地址。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 新增审批打断既有代码路径测试 | 更新受影响测试并新增审批专项用例 |
| SQLite 连接线程/事务问题 | check_same_thread=False + Store autocommit，服务端单锁串行 |
| fork 语义与预期不符 | 采用实测的快照复制配方并锁定回归 |
| 记忆重复写入 | thread_id 幂等键 + 重复写入测试 |
| 里程碑泄露敏感数据 | 只投影白名单字段并加脱敏断言 |

## 6 关联文档

- [设计文档](../../spec/memory-time-travel-design.md)
- [实施 Checklist](./implementation-checklist.md)
- [单元测试计划](./unit-test-plan.md)
- [上一阶段实施计划](../multi-agent-orchestration/implementation.md)
