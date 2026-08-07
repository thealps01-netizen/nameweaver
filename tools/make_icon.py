#!/usr/bin/env python3
"""tools/make_icon.py — Nameweaver için basit, marka-nötr bir .ico üretir.

Yuvarlatılmış köşeli, degrade zeminli, uygulamanın baş harfini taşıyan bir ikon.
Kendi ikonun varsa bu dosyayı değiştir ya da nameweaver.ico'yu elle koy.

Gerekli: pip install Pillow
"""

import os
from PIL import Image, ImageDraw, ImageFont

APP_NAME = "Nameweaver"
SLUG     = "nameweaver"
SIZES    = [256, 128, 64, 48, 32, 16]
C1       = (37, 99, 235)    # mavi
C2       = (14, 165, 233)   # camgöbeği


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    for y in range(size):                       # dikey degrade
        d.line([(0, y), (size, y)], fill=_lerp(C1, C2, y / max(1, size - 1)) + (255,))

    radius = int(size * 0.22)                    # yuvarlatılmış köşe maskesi
    mask   = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.putalpha(mask)

    letter = (APP_NAME[:1] or "A").upper()       # baş harf
    try:
        font = ImageFont.truetype("segoeuib.ttf", int(size * 0.56))
    except Exception:
        font = ImageFont.load_default()
    d    = ImageDraw.Draw(img)
    bbox = d.textbbox((0, 0), letter, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]),
           letter, font=font, fill=(255, 255, 255, 235))
    return img


def main():
    root   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out    = os.path.join(root, f"{SLUG}.ico")
    frames = [make(s) for s in SIZES]
    frames[0].save(out, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[1:])
    print(f"{SLUG}.ico  ->  {out}")


if __name__ == "__main__":
    main()
