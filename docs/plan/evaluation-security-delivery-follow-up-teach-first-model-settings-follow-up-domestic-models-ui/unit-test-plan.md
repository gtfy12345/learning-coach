# 国产模型兼容接入与模型页面优化单元测试计划

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-17

**关联 Checklist**: [unit-test-plan-checklist.md](./unit-test-plan-checklist.md)

## 1 测试目标

验证国产 Provider 注册表、URL 安全校验、OpenAI 兼容模型构建、配置服务秘密边界、API 契约与页面动态交互，同时回归现有 Provider 和 CLI 行为。

## 2 测试原则

- 所有模型调用使用 fake/stub，不访问外部网络或产生费用。
- 每个实现项先新增失败断言，再完成最小实现。
- API Key 使用可识别假值并断言不出现在响应与错误中。
- 页面测试同时覆盖静态契约、JavaScript 语法和真实浏览器交互。

## 3 测试范围

### Phase 1: OpenAI 兼容 Provider 契约

#### 1.1 Provider 与 URL Schema

覆盖内置 Provider 默认地址、自定义地址必填、HTTP/凭据/查询/片段拒绝、未使用 Provider 输入忽略或剔除。

#### 1.2 模型构建与配置服务

断言兼容 Provider 使用 OpenAI model provider、裸模型名、对应 Key 与 Base URL；不同角色/Provider 正确传参，现有模型路径不变。

#### 1.3 API 安全与运行时语义

覆盖测试成功、构建失败、缺 Key、一次性票据、逻辑 Provider 摘要和秘密不回显。

### Phase 2: 首页与模型设置页体验

#### 2.1 Provider 与动态凭据 UI

断言页面包含国产与自定义选项、推荐模型/地址元数据、动态凭据容器，不保留旧固定三 Key 布局。

#### 2.2 配置状态与操作反馈

使用浏览器验证 Provider 切换、去重、测试门禁、错误状态和应用后清空 Key。

#### 2.3 首页、响应式与可访问性

检查首页明确设置入口、表单 label/ARIA、键盘焦点、长模型名和移动视口无横向溢出。

### Phase 3: 文档与交付验证

#### 3.1 公开文档契约

断言 README 与 `.env.example` 包含国产 Provider、自定义 HTTPS 端点和内存边界。

#### 3.2 回归验证

运行 `tests/test_model.py`、`tests/test_model_config.py`、`tests/test_model_config_api.py`、Web 测试、完整 pytest、JavaScript 语法和 diff 检查。

## 4 通过标准

- 所有新增与回归测试通过。
- 测试过程不访问真实 Provider。
- 浏览器桌面/移动验证无功能、可访问性或明显视觉问题。
- 文档、实现和页面使用一致的 Provider ID、默认地址与安全边界。

## 5 关联文档

- [实施计划](./implementation.md)
- [设计文档](../../spec/evaluation-security-delivery-follow-up-teach-first-model-settings-follow-up-domestic-models-ui-design.md)
