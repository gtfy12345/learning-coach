#!/usr/bin/env bash
# 构建 LearningCoach.app（macOS 桌面应用）。
#
# 用法：
#   scripts/build_macos_app.sh              # 跑测试 → 生成图标 → 打包 → ad-hoc 签名
#   scripts/build_macos_app.sh --skip-tests # 跳过测试（快速迭代）
#
# 产物：dist/LearningCoach.app。仅本机使用：本地构建无 Gatekeeper
# 隔离标记，ad-hoc 签名后可直接双击运行；分发给他人需另行正式签名。

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "${PYTHON:-}" ]]; then
  echo "未找到可用的 Python 解释器；请先创建 .venv 或设置 PYTHON。" >&2
  exit 1
fi

SKIP_TESTS=0
for arg in "$@"; do
  case "$arg" in
    --skip-tests) SKIP_TESTS=1 ;;
    *) echo "未知参数：$arg" >&2; exit 1 ;;
  esac
done

if [[ "$SKIP_TESTS" -ne 1 ]]; then
  echo "==> 运行测试"
  PYTHONPATH=src "$PYTHON" -m pytest -q
fi

echo "==> 生成应用图标"
"$PYTHON" scripts/make_app_icon.py

echo "==> PyInstaller 打包"
"$PYTHON" -m PyInstaller packaging/LearningCoach.spec --noconfirm

echo "==> ad-hoc 签名（本机运行所需）"
codesign --force --deep --sign - dist/LearningCoach.app
codesign --verify --verbose=1 dist/LearningCoach.app

echo "==> 完成：dist/LearningCoach.app"
