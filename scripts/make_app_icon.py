"""生成 LearningCoach.app 图标（packaging/icon.icns）。

用 Pillow 画一个简洁的渐变底 + 展开书本图形，再交给系统自带
``iconutil`` 转成 .icns。脚本化生成保证可复现，产物不入库。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
ICONSET_DIR = REPO_ROOT / "packaging" / "build-icon.iconset"
OUTPUT_ICNS = REPO_ROOT / "packaging" / "icon.icns"

BASE_SIZE = 1024


def _rounded_gradient(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (size, size))
    top = (23, 92, 210, 255)
    bottom = (16, 165, 160, 255)
    for y in range(size):
        ratio = y / (size - 1)
        color = tuple(
            int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(4)
        )
        ImageDraw.Draw(gradient).line([(0, y), (size, y)], fill=color)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255
    )
    image.paste(gradient, (0, 0), mask)
    return image


def _draw_open_book(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    size = image.width
    stroke = max(2, size // 90)
    left = size * 0.18
    right = size * 0.82
    top = size * 0.34
    bottom = size * 0.72
    spine_x = size * 0.5

    # 展开的书：左右两页 + 中缝，白色主体、深色描边保持小尺寸可辨识。
    draw.polygon(
        [(left, top), (spine_x, top + size * 0.06), (spine_x, bottom), (left, bottom - size * 0.02)],
        fill=(255, 255, 255, 255),
    )
    draw.polygon(
        [(right, top), (spine_x, top + size * 0.06), (spine_x, bottom), (right, bottom - size * 0.02)],
        fill=(240, 249, 255, 255),
    )
    draw.line([(spine_x, top + size * 0.06), (spine_x, bottom)], fill=(13, 62, 140, 255), width=stroke)

    # 书页内示意几行文字。
    for page, x0 in ((0, left + size * 0.06), (1, spine_x + size * 0.04)):
        for row in range(3):
            y = top + size * (0.12 + row * 0.09)
            x_end = spine_x - size * 0.04 if page == 0 else right - size * 0.06
            draw.line([(x0, y), (x_end, y)], fill=(120, 150, 190, 255), width=stroke // 2)


def _write_iconset() -> None:
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir(parents=True)
    base = _rounded_gradient(BASE_SIZE)
    _draw_open_book(base)
    entries = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, size in entries.items():
        base.resize((size, size), Image.LANCZOS).save(ICONSET_DIR / name)


def main() -> int:
    _write_iconset()
    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(OUTPUT_ICNS)],
        check=True,
    )
    shutil.rmtree(ICONSET_DIR)
    print(f"图标已生成：{OUTPUT_ICNS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
