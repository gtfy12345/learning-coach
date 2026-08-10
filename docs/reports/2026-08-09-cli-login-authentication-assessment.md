# 官方 CLI 登录态与 API Key 双通道交付复盘报告

> **日期**: 2026-08-09
> **审查人**: Codex

## 1 复盘范围与成功证据

- 本次交付在既有多 Provider、图片输入与结构化输出基础上，新增 Codex CLI、Claude Code 和 Gemini CLI 登录态调用，同时保留 OpenAI、Anthropic 与 Google GenAI 的 API Key 模式。
- 新增官方 CLI 登录、状态和退出委托；CLI 模型适配器；Codex/Claude 原生 schema 输出；Gemini JSON 提示词、Pydantic 校验与一次纠错重试；本地图片临时目录、超时和子进程环境隔离。
- `PYTHONPATH=src .venv/bin/pytest -q` 通过，结果为 `37 passed`；测试全部使用 fake/stub，没有登录账号、调用真模型或产生模型费用。
- `git diff --check` 与 `.venv/bin/python -m compileall -q src tests` 通过。
- 公众号文章更新为 12 页并逐页渲染检查；DOCX 表格几何检查通过，无压缩包错误，可访问性审计结果为 high/medium/low 各 0 项。
- 本会话没有创建未进入执行状态的 follow-up plan 或 checklist，不存在孤立跟进文档阻塞。

## 2 会话中的主要阻点/痛点

### 2.1 “登录”语义需要先确定认证通道

- **证据**：原实现只支持 Provider API Key；用户进一步要求“登录也要实现”，随后通过选项 A 明确为复用 Codex、Claude Code 与 Gemini 官方 CLI 的已登录会话。
- **影响**：如果不先区分“应用用户登录”“抽取客户端 token”和“调用官方 CLI 登录态”，实现会落到完全不同的安全与部署边界。

### 2.2 三家 CLI 的无头调用和结构化输出能力不对称

- **证据**：Codex 提供 `--output-schema`，Claude Code 提供 `--json-schema`；Gemini CLI 没有等价的 schema 参数，因此需要显式 `prompt_json`、本地校验和一次纠错重试。Gemini 也没有可安全映射的独立 status/logout 子命令。
- **影响**：不能用同一条命令模板或同一个能力布尔值覆盖三家客户端；适配器、错误提示和测试矩阵都必须分 Provider 处理。

### 2.3 仓库测试命令依赖已激活的虚拟环境

- **证据**：直接运行 `PYTHONPATH=src pytest -q` 返回 `pytest: command not found`；改用 `PYTHONPATH=src .venv/bin/pytest -q` 后 37 项测试全部通过。
- **影响**：自动化会话或新终端如果没有执行 `source .venv/bin/activate`，README 中的短命令不能直接复现验证结果。

### 2.4 外部文章是功能变更的易漂移消费者

- **证据**：功能完成后，既有第 02 篇文章仍写着“只实现 API 认证”和“20 项测试”，必须同步生成脚本、正文、参考资料与图示，再重新完成 12 页渲染审查。
- **影响**：文章源脚本位于临时目录、最终 DOCX 位于仓库外部；后续功能变化容易遗漏或失去可复现的生成入口。

### 2.5 强制复盘缺少报告基础设施

- **证据**：`retrospective` 要求 `docs/reports/README.md` 和 `INDEX.md`，但仓库原先没有 `docs/`；因此必须先运行 `init-docs` 流程才能记录复盘。
- **影响**：成功交付的收尾阶段才发现前置条件，增加了与功能本身无关的文档脚手架工作量。

## 3 根因归类

- 认证语义没有预先形成“模型 ID → 认证来源 → 部署场景 → 安全边界”的决策矩阵。
  - **类别**：spec-plan
- CLI 能力差异来自官方客户端契约，本身不是统一抽象可以消除的问题；当前实现通过 capability profile 和显式回退保留差异。
  - **类别**：无需仓库改动
- 测试说明默认操作者已经激活虚拟环境，没有为自动化或非交互终端提供环境无关的单一入口。
  - **类别**：README
- 公众号文章及其生成脚本不在仓库的可追踪交付链路中。
  - **类别**：spec-plan
- `retrospective` 强制要求报告目录，而 `init-docs` 没有只初始化 reports 的选项，也没有在功能开发开始时做前置检查。
  - **类别**：skill

## 4 对流程资产的改进建议

- 在后续认证类设计或实施计划中增加认证矩阵，至少列出 API Key、官方 CLI 会话、应用用户登录三种概念，以及每种模式的凭据所有者、是否适合服务端、退出方式和额度来源。
  - **落点**：spec-plan
  - **优先级**：high
- 为测试提供不依赖 shell 激活状态的稳定入口，例如 Make/脚本命令，或在 README 同时给出 `.venv/bin/python -m pytest` 的自动化写法。
  - **落点**：README
  - **优先级**：medium
- 把公众号文章生成源、图片源和渲染命令放入可版本化位置，或至少维护一份“代码行为变更时必须同步的文章断言”清单。
  - **落点**：spec-plan
  - **优先级**：high
- 为 `init-docs` 增加 `reports` 目标选项，或让 `retrospective` 在缺少基础设施时只初始化 reports 目录，避免为了单一报告创建所有文档分区。
  - **落点**：skill
  - **优先级**：medium
- 保留当前 Provider 能力差异，不把 Gemini CLI 的 `prompt_json` 描述为原生结构化输出；继续用 fake/stub 固化每家 CLI 的命令契约。
  - **落点**：无需仓库改动
  - **优先级**：high

## 5 建议优先级与后续动作

1. 下一轮涉及认证或模型接入时，先建立认证与能力矩阵，再开始修改模型层，避免把“登录”误解成 token 抽取或应用账户系统。
2. 将文章生成源纳入可复现交付链路，这是降低代码、README 与公众号文章三方漂移风险的最高价值文档改进。
3. 保持现有 CLI stub 测试矩阵；每次升级官方 CLI 版本时，先核对命令帮助与 JSON 输出契约，再调整适配器。
4. 测试入口和 reports-only 初始化属于流程体验优化，可以在不影响当前功能的后续维护中完成。
