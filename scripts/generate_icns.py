#!/usr/bin/env python3
"""Generate assets/cram-ai.icns from the tray icon drawing.

Requires: pillow (already a [tray] dependency)
macOS only (uses iconutil).

Usage:
    python scripts/generate_icns.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).parent.parent
ASSETS = REPO / 'assets'

# Sizes required by macOS iconset format
# Each produces icon_NxN.png; sizes ≤ 512 also get an @2x at double resolution.
SIZES = [16, 32, 128, 256, 512]


def _draw(size: int) -> Image.Image:
    img  = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad  = max(1, round(size * 2 / 64))
    r    = round(size * 14 / 64)
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=r,
        fill=(0, 245, 212, 230),
    )
    m = round(size * 13 / 64)
    w = max(2, round(size * 9 / 64))
    draw.arc([m, m, size - m, size - m], start=45, end=315,
             fill=(5, 4, 10, 255), width=w)
    return img


def main() -> None:
    if sys.platform != 'darwin':
        print('generate_icns.py requires macOS (iconutil).')
        sys.exit(1)

    iconset = ASSETS / 'cram-ai.iconset'
    iconset.mkdir(parents=True, exist_ok=True)

    for size in SIZES:
        _draw(size).save(iconset / f'icon_{size}x{size}.png')
        _draw(size * 2).save(iconset / f'icon_{size}x{size}@2x.png')

    icns = ASSETS / 'cram-ai.icns'
    subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(icns)], check=True)
    shutil.rmtree(iconset)
    print(f'Generated: {icns}')


if __name__ == '__main__':
    main()
