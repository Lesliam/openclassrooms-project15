#!/usr/bin/env python3
"""Generate Coach-Terminal OLED face assets and a comparison preview.

Two rendering styles for the 128x64 monochrome SSD1306:
  - Style A "procedural": simple geometry (eye rings + pupils, line mouths).
    This mirrors, pixel-intent for pixel-intent, what the ESPHome display
    lambda in coach-terminal-faces-drawn.yaml draws at runtime. The preview
    is therefore an honest spec of the on-device output, not a mock-up.
  - Style B "bitmap": softer, cuter filled faces exported as 1-bit PNG frames
    that coach-terminal-faces-bitmap.yaml loads via the `image:` component.

Outputs:
  faces/face_*.png            1-bit frames consumed by the bitmap ESPHome config
  /tmp/faces_preview.png      scaled, labelled comparison sheet (for review)

Run: python faces_gen.py   (needs Pillow, already present for ESPHome)
"""

from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

W, H = 128, 64
FG, BG = 255, 0  # white pixels lit on a dark OLED

HERE = os.path.dirname(os.path.abspath(__file__))
FACES_DIR = os.path.join(HERE, "faces")
os.makedirs(FACES_DIR, exist_ok=True)

# Eye + mouth geometry shared by style A (kept identical in the ESPHome lambda).
LX, LY = 40, 28      # left eye centre
RX, RY = 88, 28      # right eye centre
ER = 13              # eye ring radius
PR = 4               # pupil radius
MX, MY = 64, 50      # mouth centre


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("1", (W, H), BG)
    return img, ImageDraw.Draw(img)


# --------------------------------------------------------------------------- #
# Style A — procedural (matches the ESPHome drawn lambda)                       #
# --------------------------------------------------------------------------- #
def _eye_ring(d, cx, cy, r=ER):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=FG)
    # 2px stroke: draw a second, inner ring
    d.ellipse([cx - r + 1, cy - r + 1, cx + r - 1, cy + r - 1], outline=FG)


def _pupil(d, cx, cy, dx=0, dy=0):
    d.ellipse([cx + dx - PR, cy + dy - PR, cx + dx + PR, cy + dy + PR], fill=FG)


def _blink(d, cx, cy):
    d.line([cx - ER, cy, cx + ER, cy], fill=FG, width=3)


def _brow(d, cx, cy):
    d.line([cx - ER, cy - ER - 4, cx + ER, cy - ER - 6], fill=FG, width=2)


def _polyline(d, pts):
    for a, b in zip(pts, pts[1:]):
        d.line([a, b], fill=FG, width=2)


def style_a(state: str, blink=False, mouth_open=True, dots=3) -> Image.Image:
    img, d = _canvas()
    if state == "idle":
        if blink:
            _blink(d, LX, LY); _blink(d, RX, RY)
        else:
            _eye_ring(d, LX, LY); _pupil(d, LX, LY, 0, 1)
            _eye_ring(d, RX, RY); _pupil(d, RX, RY, 0, 1)
        _polyline(d, [(54, 49), (58, 52), (64, 53), (70, 52), (74, 49)])  # smile
    elif state == "listening":
        _brow(d, LX, LY); _brow(d, RX, RY)                                # raised brows
        _eye_ring(d, LX, LY, ER + 1); _pupil(d, LX, LY)
        _eye_ring(d, RX, RY, ER + 1); _pupil(d, RX, RY)
        d.ellipse([MX - 4, MY - 4, MX + 4, MY + 4], outline=FG)           # small "o"
    elif state == "thinking":
        _eye_ring(d, LX, LY); _pupil(d, LX, LY, 3, -5)                    # look up-right
        _eye_ring(d, RX, RY); _pupil(d, RX, RY, 3, -5)
        d.line([56, 52, 72, 52], fill=FG, width=2)                        # flat mouth
        for i in range(dots):                                            # "..." top-right
            x = 100 + i * 9
            d.ellipse([x - 2, 9, x + 2, 13], fill=FG)
    elif state == "talking":
        _eye_ring(d, LX, LY); _pupil(d, LX, LY, 0, 0)
        _eye_ring(d, RX, RY); _pupil(d, RX, RY, 0, 0)
        if mouth_open:
            d.ellipse([MX - 7, MY - 6, MX + 7, MY + 6], fill=FG)         # open mouth
        else:
            d.line([MX - 7, MY, MX + 7, MY], fill=FG, width=2)           # closed
    return img


# --------------------------------------------------------------------------- #
# Style B — bitmap "cute" (exported as 1-bit frames for the image: component)   #
# --------------------------------------------------------------------------- #
def _cute_eye(d, cx, cy, up=False, wide=False):
    rw = 13 if wide else 11
    rh = 15 if wide else 13
    d.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=FG)             # big white eye
    hx, hy = (cx - 3, cy - 6) if up else (cx - 4, cy - 3)                # highlight hole
    d.ellipse([hx - 4, hy - 4, hx + 4, hy + 4], fill=BG)


def _cheek(d, cx, cy):
    d.ellipse([cx - 3, cy - 2, cx + 3, cy + 2], outline=FG)


def style_b(state: str, blink=False, mouth_open=True) -> Image.Image:
    img, d = _canvas()
    lx, rx, ey = 38, 90, 30
    if state == "idle":
        if blink:
            d.line([lx - 11, ey, lx + 11, ey], fill=FG, width=4)
            d.line([rx - 11, ey, rx + 11, ey], fill=FG, width=4)
        else:
            _cute_eye(d, lx, ey); _cute_eye(d, rx, ey)
        _cheek(d, 20, 44); _cheek(d, 108, 44)
        _polyline(d, [(52, 50), (58, 55), (64, 56), (70, 55), (76, 50)])  # big smile
    elif state == "listening":
        _cute_eye(d, lx, ey, wide=True); _cute_eye(d, rx, ey, wide=True)
        for r in (6, 11):                                                # "hearing" arcs
            d.arc([2 - r, ey - r, 2 + r, ey + r], -60, 60, fill=FG)
            d.arc([126 - r, ey - r, 126 + r, ey + r], 120, 240, fill=FG)
        d.ellipse([MX - 5, MY - 5, MX + 5, MY + 5], outline=FG)
    elif state == "thinking":
        _cute_eye(d, lx, ey, up=True); _cute_eye(d, rx, ey, up=True)
        d.line([58, 53, 70, 53], fill=FG, width=2)
        for i, r in enumerate((2, 3, 4)):                               # thought dots
            cx = 98 + i * 10
            d.ellipse([cx - r, 12 - r, cx + r, 12 + r], outline=FG)
    elif state == "talking":
        _cute_eye(d, lx, ey); _cute_eye(d, rx, ey)
        if mouth_open:
            d.ellipse([MX - 9, MY - 7, MX + 9, MY + 9], fill=FG)
            d.ellipse([MX - 4, MY - 1, MX + 4, MY + 5], fill=BG)         # inner mouth
        else:
            _polyline(d, [(55, 51), (60, 54), (64, 55), (68, 54), (73, 51)])
    return img


# --------------------------------------------------------------------------- #
# Bitmap frame export (the flashable assets)                                    #
# --------------------------------------------------------------------------- #
BITMAP_FRAMES = {
    "face_idle": style_b("idle"),
    "face_blink": style_b("idle", blink=True),
    "face_listen": style_b("listening"),
    "face_think1": style_b("thinking"),          # dots frame A (kept for future 2-frame)
    "face_think2": style_b("thinking"),          # dots frame B
    "face_talk_open": style_b("talking", mouth_open=True),
    "face_talk_closed": style_b("talking", mouth_open=False),
}


def export_bitmap_frames():
    for name, im in BITMAP_FRAMES.items():
        im.save(os.path.join(FACES_DIR, f"{name}.png"))
    print(f"wrote {len(BITMAP_FRAMES)} frames to {FACES_DIR}")


# --------------------------------------------------------------------------- #
# Text fallback screen (error / boot) — identical to the drawn+bitmap configs   #
# --------------------------------------------------------------------------- #
def text_screen(line2: str) -> Image.Image:
    img, d = _canvas()
    try:
        big = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 18)
        small = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans.ttf", 11)
    except OSError:
        big = small = ImageFont.load_default()
    d.text((0, 0), "Coach FR", fill=FG, font=big)
    d.text((0, 26), line2, fill=FG, font=small)
    d.text((0, 48), "up: 128 s", fill=FG, font=small)
    return img


# --------------------------------------------------------------------------- #
# Comparison sheet                                                              #
# --------------------------------------------------------------------------- #
def build_preview():
    scale = 3
    pad = 14
    cols = ["idle", "listening", "thinking", "talking"]
    col_labels = ["Idle / ready", "Listening", "Thinking", "Talking"]
    cw, ch = W * scale, H * scale

    try:
        title_f = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 22)
        lab_f = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans.ttf", 15)
    except OSError:
        title_f = lab_f = ImageFont.load_default()

    n = len(cols)
    sheet_w = pad + n * (cw + pad)
    sheet_h = 40 + 28 + 2 * (ch + 24 + pad) + (ch + 24 + pad)  # title + colhdr + 2 rows + text row
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 22))
    sd = ImageDraw.Draw(sheet)

    sd.text((pad, 8), "Coach Terminal - OLED face styles (128x64)", fill=(255, 255, 255), font=title_f)

    def paste_cell(x, y, frame_1bit, border):
        big = frame_1bit.convert("L").resize((cw, ch), Image.NEAREST).convert("RGB")
        # tint lit pixels a soft OLED blue-white
        px = big.load()
        for j in range(ch):
            for i in range(cw):
                if px[i, j][0] > 127:
                    px[i, j] = (150, 220, 255)
                else:
                    px[i, j] = (8, 10, 16)
        sheet.paste(big, (x, y))
        sd.rectangle([x, y, x + cw - 1, y + ch - 1], outline=border)

    y0 = 44
    # column headers
    for c, lbl in enumerate(col_labels):
        x = pad + c * (cw + pad)
        sd.text((x + 4, y0), lbl, fill=(180, 200, 255), font=lab_f)
    y0 += 24

    # Row A
    sd.text((pad, y0 + ch // 2), "A", fill=(120, 255, 180), font=title_f)
    for c, st in enumerate(cols):
        x = pad + c * (cw + pad)
        paste_cell(x, y0, style_a(st), (120, 255, 180))
    sd.text((pad, y0 + ch + 2), "Style A - procedural (drawn by lambda)", fill=(120, 255, 180), font=lab_f)
    y0 += ch + 24 + pad

    # Row B
    for c, st in enumerate(cols):
        x = pad + c * (cw + pad)
        paste_cell(x, y0, style_b(st), (255, 200, 120))
    sd.text((pad, y0 + ch + 2), "Style B - bitmap (cute, 1-bit image frames)", fill=(255, 200, 120), font=lab_f)
    y0 += ch + 24 + pad

    # Text fallback row (shared)
    paste_cell(pad, y0, text_screen("Connexion HA..."), (255, 120, 120))
    paste_cell(pad + (cw + pad), y0, text_screen("Erreur"), (255, 120, 120))
    paste_cell(pad + 2 * (cw + pad), y0, text_screen("Demarrage..."), (200, 200, 200))
    sd.text((pad, y0 + ch + 2), "Error / boot - BOTH styles fall back to this text screen (diagnostic)",
            fill=(255, 160, 160), font=lab_f)

    out = "/tmp/faces_preview.png"
    sheet.save(out)
    print(f"wrote preview {out} ({sheet_w}x{sheet_h})")
    return out


if __name__ == "__main__":
    export_bitmap_frames()
    build_preview()
