# Codex CLI Exec 兼容性 Follow-up 交付复盘报告

> **日期**: 2026-08-17
> **审查人**: Codex

## 1 复盘范围与成功证据

- 本次交付修复 Codex CLI 0.144.1 的非交互参数与 Structured Outputs 契约漂移，保持原登录方式、模型 ID、只读 sandbox 和 Web 安全错误协议。
- `tests/test_cli_models.py` 10 项通过，完整 pytest 317 项通过；自动化测试均使用 fake/stub，不调用真实模型或网络。
- `compileall` 与 `git diff --check` 通过。
- 修复后的真实文本适配器调用返回 `OK`；重启 Web 后，创建会话返回 HTTP 201 并生成结构化诊断题。
- 本会话创建的 Follow-up 已进入 `implement`/`tdd` owner 流程，实施与验证均有 checklist 证据，不存在孤立计划风险。

## 2 会话中的主要阻点/痛点

### 2.1 上游 CLI 漂移包含两个连续契约变化

- **证据**：先遇到 `--ask-for-approval` 被删除；替换后又发现输出 Schema 缺少 `additionalProperties: false`。
- **影响**：仅修复首个参数错误仍会在真实 Web 结构化调用中返回相同的安全兜底文案，需要第二轮诊断与实现。

### 2.2 原离线测试没有固定安全关键参数和 Schema 严格性

- **证据**：原 Codex fake runner 只检查 `exec`、模型、ephemeral 和 prompt，没有断言审批策略、sandbox 完整组合或严格对象 Schema。
- **影响**：测试在官方 CLI 已不接受实际命令时仍保持通过。

### 2.3 安全错误截断隐藏了真正的末尾原因

- **证据**：CLI stderr 前部包含缓存与插件告警，`_safe_error` 只保留前 500 字符，真正的 `invalid_json_schema` 位于末尾。
- **影响**：Web 的脱敏行为符合安全边界，但开发诊断需要额外 runner 才能看到可操作错误。

### 2.4 真实 CLI 网络回退接近 Web 默认 deadline

- **证据**：本机多次出现 WebSocket 重试后回退 HTTPS，单次请求约需 100 秒；最终 Web 验证使用 300 秒 deadline。
- **影响**：即使命令契约正确，网络抖动时仍可能触发默认 120 秒超时，但这与本次兼容性根因独立。

## 3 根因归类

- CLI 命令与 Schema 约束未形成可升级的完整测试矩阵。
  - **类别**：spec-plan
- `_safe_error` 优先保留日志头部而非可操作错误尾部，是诊断可观测性不足。
  - **类别**：spec-plan
- 官方 CLI 网络回退耗时属于当前运行环境与订阅客户端行为。
  - **类别**：no repo change needed

## 4 对流程资产的改进建议

- 在 CLI Provider 维护流程中加入“升级前核对 `--help`、配置键、Schema 和最小真机冒烟”的兼容矩阵。
  - **落点**：spec-plan
  - **优先级**：high
- 为安全错误提取设计“保留最终 ERROR 片段、过滤无关 WARN、继续限制长度和敏感信息”的独立 follow-up。
  - **落点**：spec-plan
  - **优先级**：medium
- 在 README 的 CLI 运行边界中提醒网络回退可能需要提高 `WEB_RUN_TIMEOUT_SECONDS`，但不修改默认值。
  - **落点**：README
  - **优先级**：medium

## 5 建议优先级与后续动作

1. 后续升级 Codex/Claude/Gemini CLI 时，优先执行命令契约与结构化输出兼容矩阵，再合入依赖升级。
2. 下一轮可独立改善 `_safe_error` 的可操作错误提取；必须保留浏览器脱敏和长度上限。
3. 网络回退只需先通过启动参数调整 deadline，除非多环境持续复现，否则不修改全局默认值。
