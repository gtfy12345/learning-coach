# 国产模型兼容接入与模型页面优化实施计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-17

**关联 Checklist**: [implementation-checklist.md](./implementation-checklist.md)

## 1 目标

为现有内存模型配置增加 DeepSeek、通义千问、智谱 GLM 和自定义 OpenAI 兼容 Provider，并优化首页模型入口与设置页，使用户能更低成本地完成选择、测试和应用，同时保持秘密不落盘与会话运行时隔离。

## 2 背景

当前 `/settings` 只支持 OpenAI、Anthropic 和 Google GenAI，且三个固定 Key 输入框始终展示。仓库已支持 `OPENAI_BASE_URL` 启动配置，但页面配置协议没有 Base URL，也不能保留国产 Provider 身份。原模型设置计划已经 completed，本次按 follow-up 新建执行 owner。

## 3 实施步骤

### Phase 1: OpenAI 兼容 Provider 契约

#### 1.1 增加 Provider 注册表与 Base URL 校验

扩展 API Provider 类型和请求 Schema，定义三个内置国产 Provider及自定义兼容 Provider；验证所选 Provider 的 Key、HTTPS 地址和 URL 结构。

#### 1.2 实现兼容模型构建与候选测试传参

把逻辑 Provider 映射到 LangChain OpenAI Chat Model，按 Provider 传递模型名称、API Key 和 Base URL；保持现有 Provider 路径及模型缓存行为。

#### 1.3 保持脱敏、一次性票据与会话隔离契约

验证成功、失败、过期和重复使用路径均不泄漏 Key，失败不替换当前运行时，公开配置继续显示逻辑 Provider。

### Phase 2: 首页与模型设置页体验

#### 2.1 重构设置页 Provider 与动态凭据交互

加入国产 Provider 与自定义兼容预设，Provider 变化自动填充推荐模型和默认 Base URL；只渲染实际选中的 Provider 凭据，相同 Provider 合并。

#### 2.2 优化配置方式、当前运行时与操作反馈

使用清晰的 API/CLI 配置分区、运行时摘要、步骤提示和测试/应用状态，保持字段变化即使票据失效、应用后清空 Key。

#### 2.3 优化首页入口、响应式布局与可访问性

让首页页头的模型设置入口更明确；补齐键盘焦点、可识别标签、窄屏布局和长模型名换行。

### Phase 3: 文档与交付验证

#### 3.1 更新公开配置说明

同步 README 与 `.env.example`，说明支持范围、推荐 Provider、HTTPS 自定义端点、测试费用和内存边界。

#### 3.2 完成全量与浏览器验证

运行相关测试、完整测试、前端语法、文档上下文、`git diff --check`，并在桌面与移动视口完成页面视觉和交互验证。

## 4 验收标准

- DeepSeek、通义千问与智谱 GLM 可通过页面预设完成最小连接测试并应用。
- 自定义 OpenAI 兼容 Provider 接受合法 HTTPS Base URL，拒绝不安全或缺失地址。
- 现有 OpenAI、Anthropic、Google 和 CLI 配置行为保持兼容。
- 页面只显示当前选中 Provider 需要的 Key 与地址，且不写浏览器存储。
- 首页模型状态与设置入口清晰，设置页在桌面和移动端均可用。
- 自动化测试不调用真实模型，完整 API Key 不进入响应、日志、磁盘或快照。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 兼容 API 对工具调用支持不一致 | 保持真实最小结构化输出测试，失败时不应用 |
| Provider 预设随官方变更 | 集中注册表与前端契约测试；允许用户修改模型和内置端点 |
| 自定义地址访问敏感目标 | 限制 HTTPS，拒绝凭据、查询串与片段，接口继续仅回环可用 |
| 页面动态字段遗漏 Key | 由所选 Provider 集合生成字段并在提交前校验 |
| 新契约破坏测试桩 | `base_urls` 使用可选参数并同步所有直接消费者 |

## 6 关联文档

- [设计文档](../../spec/evaluation-security-delivery-follow-up-teach-first-model-settings-follow-up-domestic-models-ui-design.md)
- [单元测试计划](./unit-test-plan.md)
- [原 Follow-up 计划](../evaluation-security-delivery-follow-up-teach-first-model-settings/implementation.md)
- [原设计文档](../../spec/evaluation-security-delivery-follow-up-teach-first-model-settings-design.md)
- [原交付评估](../../reports/2026-08-17-teach-first-model-settings-assessment.md)
