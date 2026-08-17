# 国产模型兼容接入与模型页面优化交付复盘报告

> **日期**: 2026-08-17
> **审查人**: Codex

## 1 复盘范围与成功证据

本次交付为已完成“先教后测与本地模型设置”的 follow-up，范围包括 DeepSeek、通义千问、智谱 GLM 和自定义 OpenAI 兼容 Provider，后端 Base URL/秘密边界，以及首页与 `/settings` 的桌面、移动端体验。

成功证据：

- `PYTHONPATH=src .venv/bin/pytest -q` 全量通过，共收集 360 个测试。
- `tests/test_model.py`、`tests/test_model_config.py`、`tests/test_model_config_api.py` 与 `tests/test_web.py` 覆盖兼容模型构建、URL 拒绝边界、脱敏、一次性测试票据、页面静态契约和既有 Provider 回归。
- `node --check` 验证 `app.js` 与 `settings.js` 语法通过。
- 使用真实 LangChain 客户端构造验证 `deepseek:deepseek-v4-flash` 正确映射为 `ChatOpenAI`、模型名 `deepseek-v4-flash` 和 `https://api.deepseek.com`，未发起网络模型调用。
- 浏览器在桌面与 390px 移动视口验证 Provider 切换、推荐模型/Base URL、同 Provider 凭据去重、首页导航和无横向溢出；浏览器会话已关闭。
- 新服务进程 PID 48159 已在 `127.0.0.1:8000` 监听，`/api/config` 健康检查通过，设置页返回全部国产 Provider 入口。
- plan/spec/checklist 已转为 `completed`，实施和测试 Checklist 全部勾选，context 校验、`git diff --check`、Header 与 INDEX 漂移检查通过；本次 follow-up 有明确执行 owner，不存在孤儿计划风险。

## 2 会话中的主要阻点/痛点

### 2.1 共享脚本默认 Python 缺少 PyYAML

- **证据**：首次运行 `match_change_context.py` 时系统 `python3` 报告 `PyYAML is not installed`，切换到仓库 `.venv/bin/python` 后成功。
- **影响**：产生一次无效调用，并增加了环境判断成本；同类 context 校验脚本也可能遇到相同问题。

### 2.2 浏览器命令入口不一致

- **证据**：`agent-browser` 直接命令不存在；按 Skill 备用入口改用 `npx --yes agent-browser` 后，桌面/移动验证全部成功。
- **影响**：浏览器验证启动多一次探测；没有影响产品实现或最终证据。

### 2.3 后台重启方式在当前执行环境静默退出

- **证据**：`nohup ... &` 返回 PID 48101，但进程立即结束且日志为空；改用持久统一终端会话后 PID 48159 正常完成 Uvicorn startup 并通过健康检查。
- **影响**：服务短暂不可用并增加一次诊断循环；精确停止旧 PID 的范围控制正确，没有影响其他进程。

### 2.4 INDEX 自动同步不移动计划状态分组

- **证据**：`sync-doc-index --fix-index` 自动修正了 spec 状态，但把 completed plan 位于 Active 分组报告为需 LLM 处理，最终手动整体移动父行与单元测试子行。
- **影响**：这是 Skill 已声明的人工判断路径，只增加一次小范围编辑，不属于交付缺陷。

## 3 根因归类

- 仓库虚拟环境与系统 Python 的依赖集合不同；共享脚本示例固定写 `python3`，未优先解析项目 `.venv`。
  - **类别**：skill
- Browser Skill 的核心示例以全局二进制为主，虽然允许 `npx`，但没有把自动 fallback 放到首个执行步骤。
  - **类别**：skill
- 当前工具执行环境对普通 shell 后台子进程的生命周期不稳定，持久终端会话才是可靠的服务承载方式。
  - **类别**：无需仓库改动
- INDEX 分组移动需要理解父/子行关系，自动脚本刻意不处理，现有 Skill 已给出正确人工流程。
  - **类别**：无需仓库改动

## 4 对流程资产的改进建议

- 在 change-intake、implement 和 sync-doc-index 的命令示例中优先使用“存在 `.venv/bin/python` 则采用，否则回退 `python3`”的统一解析方式。
  - **落点**：相关 Skill
  - **优先级**：medium
- 在 Agent Browser Skill 的 Core Workflow 开头增加二进制探测，并把 `npx --yes agent-browser` 明确为无全局安装时的第一 fallback。
  - **落点**：agent-browser Skill
  - **优先级**：low
- 保持服务重启使用精确端口/PID检查、持久终端会话和 HTTP 健康检查的组合；不把本次 shell 后台行为泛化为仓库缺陷。
  - **落点**：无需仓库改动
  - **优先级**：medium
- 保持 sync-doc-index 对状态分组只报告、不自动移动的安全边界；父行与 `↳` 子行必须作为整体人工确认。
  - **落点**：无需仓库改动
  - **优先级**：low

## 5 建议优先级与后续动作

1. 下一轮最值得实施的是统一共享脚本的 Python 解释器解析，避免每个文档工作流重复遇到 PyYAML 环境差异。
2. 服务运行继续使用当前持久终端会话；若未来需要一键常驻，应单独设计受支持的本机服务管理脚本，而不是在本次功能中临时扩展。
3. 浏览器 fallback 和 INDEX 分组移动均已有可靠路径，可延后到相关 Skill 的独立维护周期处理。
4. 本次功能无需新增 bug 记录；没有发现可复现的产品回归，发生的阻点均属于工具/环境执行摩擦。
