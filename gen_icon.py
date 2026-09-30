# -*- coding: utf-8 -*-
"""Regenerate icon.ico (multi-size, BMP-format entries for PyInstaller).

Design: rounded blue gradient tile + wireframe globe (network) + green health badge.
Two render modes: dense >=64px, simplified chunky <=48px so 16px stays legible.
Run:  python gen_icon.py     (writes icon.ico next to this file)
"""
import struct
import numpy as np
from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.abspath(__file__)) if False else None
import os
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "icon.ico")

TILE_R = 0.235
TOP = np.array([0x2E, 0x7C, 0xE2], float)
BOT = np.array([0x0E, 0x3A, 0x8C], float)
SIZES = [16, 24, 32, 48, 64, 128, 256]

def hx(s):
    s = s.lstrip('#')
    return np.array([int(s[i:i+2], 16) for i in (0, 2, 4)], float)

def lerp(a, b, t):
    t = np.clip(t, 0, 1)[..., None]
    return a[None, None, :] * (1 - t) + b[None, None, :] * t

def rounded_mask(size, radius):
    m = Image.new('L', (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m

def build_tile(SS):
    yy, xx = np.mgrid[0:SS, 0:SS].astype(float)
    t = xx / SS * 0.55 + yy / SS * 0.45
    rgb = lerp(TOP, BOT, t)
    r = np.sqrt((xx / SS - 0.26) ** 2 + (yy / SS - 0.18) ** 2)
    glow = np.clip(1 - r / 0.55, 0, 1) ** 2 * 0.22
    rgb = rgb + 255.0 * glow[..., None]
    b = np.clip((yy / SS - 0.72) / 0.28, 0, 1) * 0.10
    rgb = rgb * (1 - b[..., None])
    tile = Image.fromarray(np.dstack([np.clip(rgb, 0, 255),
                                      np.full((SS, SS), 255, np.uint8)]).astype(np.uint8), 'RGBA')
    tile.putalpha(rounded_mask(SS, int(SS * TILE_R)))
    return tile

def draw_globe(img, cx, cy, r, SS, dense):
    d = ImageDraw.Draw(img)
    w_globe = int(SS * (0.0132 if dense else 0.0300))
    w_line = int(SS * (0.0108 if dense else 0.0260))

    clip = Image.new('L', (SS, SS), 0)
    ImageDraw.Draw(clip).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    d.ellipse([cx - r, cy - r, cx + r, cy + r],
              outline=(255, 255, 255, 240), width=w_globe)

    P = Image.new('RGBA', (SS, SS), (0, 0, 0, 0))
    dp = ImageDraw.Draw(P)
    for frac in ((-0.55, 0.0, 0.55) if not dense else (-0.62, -0.28, 0.0, 0.28, 0.62)):
        ry = r * frac
        half = np.sqrt(max(r * r - ry * ry, 1))
        h = half * 0.30
        dp.ellipse([cx - half, cy + ry - h, cx + half, cy + ry + h],
                   outline=(255, 255, 255, 200), width=w_line)
    eq = Image.new('RGBA', (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(eq).ellipse([cx - r, cy - r * 0.30, cx + r, cy + r * 0.30],
                               outline=(255, 255, 255, 232), width=int(w_line * 1.2))
    merged = Image.alpha_composite(P, eq)
    P.putalpha(Image.composite(merged.getchannel('A'),
                               Image.new('L', (SS, SS), 0), clip))
    img.alpha_composite(P)

    if dense:
        M = Image.new('RGBA', (SS, SS), (0, 0, 0, 0))
        for ang in (-45, 0, 45):
            pad = int(r * 0.10) + 8
            box = int(2 * (r + pad))
            e = Image.new('RGBA', (box, box), (0, 0, 0, 0))
            wide = 1.0 if ang == 0 else 0.55
            ew, eh = 2 * r * wide, 2 * r
            ImageDraw.Draw(e).ellipse([(box - ew) / 2, (box - eh) / 2,
                                       (box + ew) / 2, (box + eh) / 2],
                                      outline=(255, 255, 255, 200), width=w_line)
            e = e.rotate(ang, resample=Image.BICUBIC, center=(box / 2, box / 2))
            M.alpha_composite(e, (int(cx - box / 2), int(cy - box / 2)))
        M.putalpha(Image.composite(M.getchannel('A'), Image.new('L', (SS, SS), 0), clip))
        img.alpha_composite(M)

        nr = int(r * 0.070)
        for x, y in [(cx - r, cy), (cx + r, cy), (cx, cy - r), (cx, cy + r),
                     (cx + r * 0.55, cy - r * 0.30)]:
            d.ellipse([x - nr, y - nr, x + nr, y + nr], fill=(255, 255, 255, 255))
            d.ellipse([x - nr * 1.6, y - nr * 1.6, x + nr * 1.6, y + nr * 1.6],
                      outline=(255, 255, 255, 80), width=int(nr * 0.55))
    return img

def draw_badge(img, bx, by, br, SS, dense):
    yy, xx = np.mgrid[0:SS, 0:SS].astype(float)
    inb = ((xx - bx) / br) ** 2 + ((yy - by) / br) ** 2 <= 1.0
    t = np.clip((xx - bx + by - yy) / (2 * br) * 0.5 + 0.5, 0, 1)
    g = lerp(hx('#3FE08A'), hx('#0B8A48'), t)
    a = (inb * 255).astype(np.uint8)
    badge = Image.new('RGBA', (SS, SS), (0, 0, 0, 0))
    badge.paste(Image.fromarray(np.dstack([g, a]).astype(np.uint8), 'RGBA'),
                (0, 0), Image.fromarray(a, 'L'))
    d = ImageDraw.Draw(badge)
    d.ellipse([bx - br * 1.15, by - br * 1.15, bx + br * 1.15, by + br * 1.15],
              outline=(255, 255, 255, 235), width=int(br * (0.11 if dense else 0.16)))
    lw = int(br * (0.30 if dense else 0.34))
    d.line([(bx - br * 0.52, by + br * 0.04), (bx - br * 0.12, by + br * 0.44),
            (bx + br * 0.58, by - br * 0.42)], fill=(255, 255, 255, 255),
           width=lw, joint='curve')
    return Image.alpha_composite(img, badge)

def render(dense, SS):
    img = build_tile(SS)
    cx, cy, r = SS * 0.500, SS * (0.455 if dense else 0.460), SS * (0.245 if dense else 0.250)
    img = draw_globe(img, cx, cy, r, SS, dense)
    br = SS * (0.155 if dense else 0.160)
    bx, by = SS * 0.715, SS * (0.735 if dense else 0.740)
    return draw_badge(img, bx, by, br, SS, dense)

def make_bmp_data(img):
    w, h = img.size
    info = struct.pack('<I i i H H I I i i I I', 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    row_size = ((w + 31) // 32) * 4
    return info + img.tobytes('raw', 'BGRA') + bytes(row_size * h)

def main():
    big = render(dense=True, SS=2048)
    small = render(dense=False, SS=512)
    datas = []
    for s in SIZES:
        src = big if s >= 64 else small
        img = src.resize((s, s), Image.LANCZOS).convert('RGBA')
        datas.append(make_bmp_data(img))
    dir_size = 6 + 16 * len(SIZES)
    offsets, cur = [], dir_size
    for bd in datas:
        offsets.append(cur)
        cur += len(bd)
    with open(OUT, 'wb') as f:
        f.write(struct.pack('<HHH', 0, 1, len(SIZES)))
        for i, s in enumerate(SIZES):
            f.write(struct.pack('<BBBBhhII',
                                s if s < 256 else 0, s if s < 256 else 0,
                                0, 0, 1, 32, len(datas[i]), offsets[i]))
        for bd in datas:
            f.write(bd)
    print('wrote', OUT)

if __name__ == '__main__':
    main()