# macOS 桌面应用交付

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-27

**关联 Checklist**: [checklist](./implementation-checklist.md)

## 1 目标

交付可双击运行的 `LearningCoach.app`：进程内启动现有 FastAPI 服务并监听
回环随机端口，用 pywebview 原生窗口加载现有前端，关窗即退出。现有 Web
API、工作流与前端页面零改动，仅本机使用（本地构建 + ad-hoc 签名）。

## 2 背景

当前 Web MVP 需要 `PYTHONPATH=src python -m learning_coach web` 加浏览器访问，
对非开发场景不友好。项目为单进程单用户本地应用（回环监听、无外部服务），
适合直接打包成桌面应用。设计取舍见
[macOS 桌面应用设计文档](../../spec/macos-desktop-app-design.md)。

## 3 实施步骤

### Phase 1: 桌面入口与运行时引导

#### 1.1 desktop 模块

新增 `src/learning_coach/desktop.py`：数据目录解析
（`LEARNING_COACH_DATA_HOME` 覆盖 / macOS 默认
`~/Library/Application Support/LearningCoach`）、`.env` 加载、持久化默认值
（`setdefault` 不覆盖显式配置）、PATH 补齐、flock 单实例锁、空闲端口选择、
uvicorn 后台线程、健康检查轮询、pywebview 窗口（懒加载保证无头可测）。

#### 1.2 CLI 子命令

`cli.py` 新增 `desktop` 子命令（`--headless` / `--port` / `--data-home`），
非零退出码才转 `SystemExit`，与 `web` 子命令风格一致。

### Phase 2: 打包与构建

#### 2.1 PyInstaller 打包配置

`packaging/entry.py` 冻结入口 + `packaging/LearningCoach.spec`：
`collect_all` 显式收集动态导入的 provider 集成（langchain_anthropic 等）、
tiktoken 数据、uvicorn 协议、webview 平台后端；`collect_data_files` 打入
`learning_coach/static`；windowed 模式生成 `.app`。

#### 2.2 图标与构建脚本

`scripts/make_app_icon.py` 用 Pillow 生成 iconset 后经 `iconutil` 转
`.icns`（产物不入库）；`scripts/build_macos_app.sh` 串联
测试 → 图标 → PyInstaller → ad-hoc 签名与校验。

### Phase 3: 冒烟与文档

#### 3.1 冒烟验证

未打包：`python -m learning_coach desktop --headless` + health 探活；
打包后：运行 `dist/LearningCoach.app/Contents/MacOS/LearningCoach --headless`
探活并优雅退出。

#### 3.2 文档同步

README 桌面应用章节、`.env.example` 说明 `LEARNING_COACH_DATA_HOME`、
spec/plan 文档与索引、work-journal 交付记录。

## 4 验收标准

- `PYTHONPATH=src pytest` 全量通过，桌面相关测试不需要 GUI/API Key。
- 未打包与打包后 headless 冒烟均能在限时内返回 `/api/health` 200 并优雅退出。
- 二次启动被单实例锁拒绝且提示清晰。
- 现有 CLI / `web` 子命令行为不变；README 边界描述与实现一致。

## 5 风险与应对

| 风险 | 应对措施 |
|------|----------|
| PyInstaller 漏收动态导入（provider/uvicorn/webview） | spec 中 `collect_all` 显式收集；打包后 headless 冒烟逐项验证 |
| 打包体积偏大（langchain 全家桶） | 属预期边界，README 说明；不做裁剪优化 |
| GUI 进程最小 PATH 导致 CLI 模型失效 | 启动时补齐 `/opt/homebrew/bin` 等常见目录 |
| 既有测试依赖本机 `.env`（test_model.py） | 修复为 monkeypatch 凭据提取，恢复密闭性（与本计划无因果，属顺手修复既有缺陷） |

## 6 关联文档

- [macOS 桌面应用设计文档](../../spec/macos-desktop-app-design.md)
