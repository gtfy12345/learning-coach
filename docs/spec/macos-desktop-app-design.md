# macOS 桌面应用 设计文档

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-27

## 1 概述

把 Learning Coach 从「终端启动 `web` 子命令 + 浏览器访问」改造为可双击运行的
macOS 桌面应用 `LearningCoach.app`：应用在进程内启动现有 FastAPI 服务并监听
回环随机端口，用 pywebview 创建的原生窗口（WKWebView）加载现有静态前端，
关闭窗口即退出应用。现有 Web API、工作流、前端页面零改动。

## 2 设计目标

- 双击 `.app` 即可使用，不依赖终端、浏览器和 `PYTHONPATH=src`。
- 完全复用现有 `web.py` 服务与 `static/` 前端，不引入 Xcode/Node/Rust 工具链。
- 桌面数据（`.env`、SQLite 持久化）收敛到 macOS 规范位置，不污染仓库目录。
- 仅本机使用：PyInstaller 本地构建 + ad-hoc 签名，无需 Apple 开发者账号。
- 桌面入口各环节可无头测试，不需要真实模型 API。

## 3 架构设计

```
LearningCoach.app（PyInstaller windowed，入口 packaging/entry.py）
└─ learning_coach.desktop.run_desktop()
   1. bootstrap_environment()  解析数据目录、加载 .env、默认持久化路径、补 PATH
   2. SingleInstanceLock      flock 文件锁，二次启动提示后退出
   3. pick_free_port()        回环地址随机空闲端口
   4. build_application()     LearningSessionService(env_file=数据目录/.env) + create_app(service=...)
   5. start_local_server()    后台线程运行 uvicorn
   6. wait_for_health()       轮询 /api/health 就绪
   7. run_gui()               pywebview 窗口加载 http://127.0.0.1:{port}/
   8. 窗口关闭 → server.should_exit → 优雅停机 → 释放锁 → 进程退出
```

关键决策：

| ID | 决策 | 结论 | 理由 |
|----|------|------|------|
| D-1 | 窗口技术 | pywebview（WKWebView） | 纯 Python 栈；前端零构建直接复用；不引入 Xcode/Node |
| D-2 | 打包工具 | PyInstaller 6 | 对 langchain 等复杂依赖的 hiddenimports 支持成熟；py2app 维护弱 |
| D-3 | 数据目录 | `~/Library/Application Support/LearningCoach`（`LEARNING_COACH_DATA_HOME` 可覆盖） | 符合 macOS 规范；Finder 启动的进程 CWD 不可写也不可控 |
| D-4 | 持久化默认值 | 桌面模式默认设置 `CHECKPOINT_DB_PATH`/`MEMORY_DB_PATH` 到数据目录 SQLite | 桌面应用「退出丢会话」不符合预期；显式配置仍然优先（setdefault） |
| D-5 | 单实例 | flock 文件锁（数据目录 `app.lock`） | 崩溃自动释放、无端口冲突；socket 方案有误判风险 |
| D-6 | CLI 模型可用性 | 启动时把 `/opt/homebrew/bin` 等补进 PATH | GUI 进程只继承最小 PATH，`shutil.which` 找不到 codex/claude CLI |
| D-7 | 分发边界 | 仅本机使用，不做签名公证 | 本地构建无隔离标记，ad-hoc 签名即可运行；正式分发另行立项 |

## 4 接口定义

### 4.1 公开接口

- CLI 子命令：`python -m learning_coach desktop [--headless] [--port N] [--data-home PATH]`。
- 构建脚本：`scripts/build_macos_app.sh [--skip-tests]`，产物 `dist/LearningCoach.app`。
- 环境变量：`LEARNING_COACH_DATA_HOME`（数据目录覆盖，见 `.env.example`）。

### 4.2 内部接口

- `resolve_data_home(environ, *, platform)` / `bootstrap_environment(environ)`：目录解析与环境引导。
- `augment_path(environ, *, extra_dirs)`：PATH 补齐，幂等。
- `SingleInstanceLock.acquire()/release()`：flock 单实例锁。
- `pick_free_port(host)` / `start_local_server(app, *, host, port)` / `wait_for_health(host, port, ...)`。
- `build_application(env_file)`：注入 `env_file` 构造 FastAPI 应用，复用 `web.create_app(service=...)`。
- `run_gui(url)`：懒加载 pywebview，保证无头环境可导入测试。

## 5 数据结构

桌面模式数据目录布局：

```
~/Library/Application Support/LearningCoach/
├── .env              # 设置页勾选「保存到本机 .env」时写入；API Key 仅在勾选时落盘
├── checkpoints.db    # 默认 CHECKPOINT_DB_PATH（已显式配置则尊重原值）
├── memory.db         # 默认 MEMORY_DB_PATH（同上）
└── app.lock          # 单实例 flock 锁文件（内容为当前 PID）
```

## 6 错误处理

- 数据目录创建失败 / `.env` 不可读：按现有异常路径抛出，不静默吞掉。
- 单实例锁被占用：GUI 模式弹出原生提示窗口，headless 模式输出 stderr，退出码 1。
- 健康检查超时（默认 30 秒）：输出错误、优雅停机、释放锁、退出码 1。
- 窗口正常关闭或 Ctrl+C（headless）：优雅停机（`timeout_graceful_shutdown=5`）后退出码 0。

## 7 验收标准

| ID | 场景 | Given | When | Then | Phase |
|----|------|-------|------|------|-------|
| C-1 | 环境引导 | 数据目录含 `.env` | `bootstrap_environment()` | `.env` 键进入环境；未配置的持久化路径落到目录内 SQLite | P1 |
| C-2 | 显式配置优先 | 环境已有 `CHECKPOINT_DB_PATH` | `bootstrap_environment()` | 原值不被覆盖 | P1 |
| C-3 | 单实例 | 已有一个实例持有锁 | 第二个实例启动 | 获取锁失败，提示后退出 | P1 |
| C-4 | 服务就绪 | 桌面入口启动 | 轮询 `/api/health` | 限时内返回 200 | P1 |
| C-5 | 冒烟 | 构建完成 | `LearningCoach --headless` | 健康检查通过、Ctrl+C 优雅退出 | P2 |
| C-6 | 窗口生命周期 | GUI 模式启动 | 关闭窗口 | uvicorn 优雅停机、进程退出 | P2 |

## 8 关联文档

- [实现计划](../plan/macos-desktop-app/implementation.md)
- [README 桌面应用章节](../../README.md)
