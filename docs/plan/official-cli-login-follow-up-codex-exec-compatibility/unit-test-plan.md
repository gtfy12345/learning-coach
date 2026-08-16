# Codex CLI Exec 兼容性 Follow-up 单元测试计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-17

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 1 测试目标

用完全离线的 fake runner 固化 Codex CLI 参数、安全边界与结构化输出契约，并通过完整测试确认其他 Provider 未回归。

## 2 测试范围

### Phase 1: 命令契约回归

#### 1.1 普通调用参数

断言 Codex 调用包含 `--sandbox read-only`、`-c approval_policy="never"`、`--ephemeral` 和最终消息文件，且不包含已删除参数。

#### 1.2 结构化输出保持兼容

确认诊断 Schema 仍通过 `--output-schema` 传递，根对象与嵌套对象均显式禁止额外属性，返回值继续经过 Pydantic 校验。

### Phase 2: 验证与交付收口

#### 2.1 定向与完整回归

运行 `tests/test_cli_models.py` 和完整 pytest；测试不得调用真实 CLI、网络或模型。

#### 2.2 差异质量检查

运行 `git diff --check`，检查无格式错误或无关改动。

## 3 通过标准

- 新命令契约测试能在旧实现上失败、修复后通过。
- CLI 模型测试和完整测试全部通过。
- 所有测试继续使用 fake/stub runner。

## 4 关联文档

- [实施计划](./implementation.md)
- [兼容性设计](../../spec/official-cli-login-follow-up-codex-exec-compatibility-design.md)
