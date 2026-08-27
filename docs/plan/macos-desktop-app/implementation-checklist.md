# macOS 桌面应用交付 Checklist

> **版本**: 1.0
> **状态**: completed
> **更新日期**: 2026-08-27

**关联计划**: [计划文档](./implementation.md)

## Phase 1: 桌面入口与运行时引导

- [x] 1.1 desktop 模块：数据目录/环境引导/PATH/单实例锁/端口/服务线程/健康检查/GUI 懒加载
- [x] 1.2 CLI `desktop` 子命令（--headless/--port/--data-home）

## Phase 2: 打包与构建

- [x] 2.1 packaging/entry.py + LearningCoach.spec（动态导入显式收集、static 数据、windowed .app）
- [x] 2.2 图标生成脚本 + build_macos_app.sh（测试→图标→打包→ad-hoc 签名）

## Phase 3: 冒烟与文档

- [x] 3.1 未打包 headless 冒烟（health 200 + SIGINT 优雅退出 exit 0）
- [x] 3.2 打包产物 headless 冒烟（health 200；windowed 冻结包不响应 SIGINT，以 SIGTERM 结束，数据完好）
- [x] 3.3 README / .env.example / docs 索引与 work-journal 同步
- [x] 3.4 `PYTHONPATH=src pytest` 全量通过（405 passed）+ `git diff --check` 干净

## 验证记录

- 2026-08-27：`tests/test_desktop.py` 14 项通过；完整套件在修完既有 `test_model.py` 环境泄漏后通过。
- 2026-08-27：打包冒烟发现 windowed 冻结包忽略 SIGINT（PyInstaller bootloader 行为），GUI 主路径（关窗退出）不受影响，冒烟脚本改用 SIGTERM。
