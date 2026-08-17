# 先教后测与本地模型设置单元测试计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-17

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 1 测试原则

- 所有模型、API Provider 与 CLI 认证使用 fake/stub，不调用真实服务、不产生费用。
- 先锁定用户可见顺序、分支与秘密边界，再实现生产代码。
- 同时覆盖 JSON、SSE、CLI、Graph 恢复与前端静态契约。

## Phase 1: 先教后测工作流测试

- State 与请求 Schema 接受两种模式并拒绝未知值。
- 默认新会话先产生教学输出，再中断为 `understanding_check`。
- 理解检查通过跳过补讲，未通过写入缺口并进入一次补讲。
- 理解检查不增加正式 `attempts`；最终 80 分与两次上限不变。
- `diagnose_first`、旧状态缺模式、代码审批和暂停恢复保持原行为。

## Phase 2: 模型配置与认证服务测试

- API 配置校验主/评价模型各自的 Provider 与密钥映射，公开投影不含密钥。
- API 候选必须通过 fake 最小模型请求才返回 5 分钟有效的 `test_id`；验证最多 8 个候选的淘汰规则，未测试、失败、过期和重复应用均被拒绝。
- 构建失败不替换当前运行时；成功切换递增版本。
- 新旧会话分别绑定新旧运行时，JSON、SSE 和恢复路径一致。
- Codex/Claude 认证委托正确官方命令；非回环或跨源写请求返回 403。
- 错误响应、日志替身、State 和序列化结果不出现测试密钥。

## Phase 3: Web 与前端测试

- `/settings` 页面包含 API/CLI 模式、Provider/模型选择、主/评价模型、密钥、测试门禁与登录状态控件。
- API 测试成功前禁用应用按钮，字段变更使已有测试结果失效；页面显示真实请求费用提示。
- 首页模式选择默认 `teach_first`，FormData 包含 `learning_mode`。
- 时间线和提示文案按实际中断类型展示教学、理解检查或诊断。
- JS 不使用 localStorage/sessionStorage/cookie 保存密钥，语法检查通过。

## Phase 4: 文档与回归测试

- README 与 `.env.example` 明确默认模式、设置页、内存密钥和 CLI 登录边界。
- 运行 Graph、Web、模型、认证、CLI 聚焦测试及完整测试套件。
- 运行 compileall、`node --check`、context/索引检查和 `git diff --check`。
