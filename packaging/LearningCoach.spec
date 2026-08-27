# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：把 Learning Coach 打包成 LearningCoach.app。

用法（在仓库根目录执行）::

    python -m PyInstaller packaging/LearningCoach.spec --noconfirm

provider 集成（langchain_anthropic 等）经 ``init_chat_model`` 按名字动态
导入，uvicorn 的协议/循环、pywebview 的平台后端同样按字符串加载，
静态分析发现不了，因此在这里显式收集。
"""

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files

# SPECPATH 即 spec 所在的 packaging/ 目录，上一级才是仓库根目录。
repo_root = Path(SPECPATH).parent
# collect_* 工具通过导入目标包来定位文件，需要先把 src 加进模块搜索路径。
sys.path.insert(0, str(repo_root / "src"))
icon_path = repo_root / "packaging" / "icon.icns"

datas = []
binaries = []
hiddenimports = []

for package in (
    "langchain_anthropic",
    "langchain_google_genai",
    "langchain_openai",
    "tiktoken",
    "uvicorn",
    "webview",
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# web.py 通过 STATIC_DIR（包内 static/ 目录）提供前端页面。
datas += collect_data_files("learning_coach")

a = Analysis(
    [str(repo_root / "packaging" / "entry.py")],
    pathex=[str(repo_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LearningCoach",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon_path) if icon_path.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LearningCoach",
)

bundle = BUNDLE(
    coll,
    name="LearningCoach.app",
    icon=str(icon_path) if icon_path.is_file() else None,
    bundle_identifier="local.learningcoach.desktop",
    info_plist={
        "CFBundleName": "Learning Coach",
        "CFBundleDisplayName": "Learning Coach",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
    },
)
