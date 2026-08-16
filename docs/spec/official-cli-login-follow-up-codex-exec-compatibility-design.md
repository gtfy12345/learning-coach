# Codex CLI Exec 兼容性修复设计

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-17

## 1 概述

Learning Coach 通过 `codex exec` 复用官方 Codex CLI 登录会话。Codex CLI 0.144.1 已不再接受 `--ask-for-approval never`，导致 Web 首次模型调用立即失败。本设计在不改变认证、模型 ID 或公开 API 的前提下恢复兼容。

## 2 设计目标

- 让 `codex_cli:` 模型可在 Codex CLI 0.144.1 上完成文本和结构化输出调用。
- 继续显式维持只读 sandbox、禁止交互审批和无会话持久化边界。
- 用离线命令契约测试覆盖已废弃参数，避免相同回归。

## 3 设计决策记录

### 3.1 使用内联配置表达审批策略

Codex 当前 `exec` 命令支持 `-c key=value`，正式配置键为 `approval_policy`。适配器改用 `-c 'approval_policy="never"'`，不依赖本机用户配置或非交互模式的隐式默认值。

### 3.2 保留独立的只读 sandbox 参数

继续传递 `--sandbox read-only`。审批策略只控制是否暂停，sandbox 仍负责限制模型生成命令的文件与网络权限，两者不合并。

### 3.3 不在自动化测试中调用真实模型

单元测试通过 fake runner 检查完整参数契约；真实登录会话仅用于交付时的人工冒烟验证，不进入可重复测试套件。

### 3.4 仅在 Codex 边界严格化输出 Schema

Codex Structured Outputs 要求所有对象节点显式设置 `additionalProperties: false`。适配器在写入临时 Schema 文件前递归补齐该约束，不修改 Pydantic 模型定义，也不改变 Claude Code 或 Gemini CLI 的 Schema。

## 4 命令契约

Codex 调用必须包含：

- `exec`、`--ephemeral` 和 `--skip-git-repo-check`
- `--sandbox read-only`
- `-c approval_policy="never"`
- `--color never` 与 `--output-last-message`
- 按需追加 `--model`、`--output-schema` 和 `--image`
- `--output-schema` 文件中的每个对象节点显式禁止额外属性

调用不得再包含 `--ask-for-approval`。

## 5 接口与兼容性

公开模型 ID 继续使用 `codex_cli:MODEL`；`codex_cli:default` 继续让官方 CLI 选择默认模型。`create_cli_chat_model()`、Web API、CLI 参数和认证命令均不变化。

## 6 错误处理

官方 CLI 非零退出仍由适配器转换为有界 `RuntimeError`，Web 继续返回脱敏的 `run_failed`，不得把账号、路径外的长日志或模型响应原文暴露给浏览器。

## 7 非目标

- 不新增 Web 登录页面。
- 不更改 `.env` 或 API Key 认证路径。
- 不调整 Claude Code、Gemini CLI 或模型选择策略。
- 不通过降级 sandbox 绕过兼容性问题。

## 8 验收标准

| ID | 场景 | Given | When | Then | Phase |
|----|------|-------|------|------|-------|
| C-1 | 普通 Codex 调用 | fake runner 模拟已登录 CLI | 调用 `codex_cli:` 模型 | 参数包含只读 sandbox 与 `approval_policy="never"`，且不含旧参数 | 1 |
| C-2 | 结构化输出 | 提供 Pydantic Schema | 生成诊断结果 | 保留 `--output-schema` 并通过 Schema 校验 | 1 |
| C-3 | 当前 CLI 冒烟 | 本机 Codex CLI 0.144.1 已登录 | 执行最小非交互请求 | CLI 正常产生最终消息，不出现参数解析错误 | 2 |
| C-4 | 回归验证 | 完成实现与测试 | 运行完整 pytest | 所有离线测试通过且不访问真实模型 | 2 |

## 9 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 未来 Codex 再次调整命令参数 | 在升级 CLI 时核对 `codex exec --help`，并由命令契约测试固定项目依赖的参数集合 |
| 用户配置覆盖安全策略 | 使用命令行 `-c` 内联覆盖审批策略，并显式保留只读 sandbox |
| 网络慢导致 Web 超时 | 兼容修复与超时配置分离；必要时由 `WEB_RUN_TIMEOUT_SECONDS` 调整总 deadline |

## 10 关联文档

- [官方 CLI 登录态交付复盘](../reports/2026-08-09-cli-login-authentication-assessment.md)
- [LCEL Runnable 任务层设计](./lcel-runnable-task-layer-design.md)
- [实施计划](../plan/official-cli-login-follow-up-codex-exec-compatibility/implementation.md)
