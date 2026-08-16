# Codex CLI Exec 兼容性 Follow-up 实施计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-17

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

修复 Codex CLI 0.144.1 移除 `--ask-for-approval` 后导致的模型调用失败，同时保持只读、无审批和无会话持久化的既有安全边界。

## 2 背景

官方 CLI 登录功能由历史交付直接实现，没有独立 plan/spec，当前仅有交付复盘。真实调用已复现旧参数导致退出码 2；移除旧参数后登录会话能够产生结果。本 Follow-up 作为兼容性修复的执行 owner。

## 3 实施步骤

### Phase 1: 命令契约回归

#### 1.1 增加当前 Codex exec 参数测试

先让测试要求 `-c approval_policy="never"`、`--sandbox read-only`，并明确拒绝 `--ask-for-approval`。

#### 1.2 更新 Codex CLI 适配器

用当前支持的内联配置替换已删除的命令参数，并在 Codex 临时输出 Schema 中递归禁止额外属性；不改变模型定义、图片或输出文件处理。

### Phase 2: 验证与交付收口

#### 2.1 运行离线回归与完整测试

运行 CLI 模型定向测试、完整 pytest 和 `git diff --check`，确保 fake/stub 测试不访问真实模型。

#### 2.2 执行真实 CLI 与 Web 冒烟验证

使用本机已登录 Codex CLI 做一次最小非交互调用，并在重启服务后验证 Web 能越过模型参数解析阶段。

#### 2.3 同步计划生命周期与交付记录

完成 checklist、文档索引、Bug 记录评估和交付复盘评估。

## 4 验收标准

- 设计 C-1 至 C-4 均有测试或实际命令证据。
- `codex exec` 参数不再包含 `--ask-for-approval`。
- 适配器仍显式使用 `approval_policy="never"` 与只读 sandbox。
- 完整自动化测试通过且不调用网络或真实模型。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 只删除旧参数导致安全策略依赖默认值 | 显式传递 `-c approval_policy="never"` |
| 真机网络回退掩盖参数修复 | 先用离线命令契约测试确认参数，再单独记录真实冒烟结果 |
| Web 仍受 120 秒总超时影响 | 将超时视为独立运行配置，不在本兼容修复中改变默认值 |

## 6 关联文档

- [兼容性设计](../../spec/official-cli-login-follow-up-codex-exec-compatibility-design.md)
- [实施 Checklist](./implementation-checklist.md)
- [单元测试计划](./unit-test-plan.md)
- [原 CLI 登录态交付复盘](../../reports/2026-08-09-cli-login-authentication-assessment.md)
