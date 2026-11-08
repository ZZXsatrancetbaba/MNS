# -*- coding: utf-8 -*-
"""MNS logosunu (assets/mns.ico) uretir. Pillow gerektirir."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICO = ASSETS / "mns.ico"
PNG = ASSETS / "mns.png"

SIZES = [16, 24, 32, 48, 64, 128, 256]
BG_TOP = (20, 32, 56)
BG_BOTTOM = (8, 12, 22)
ACCENT = (62, 166, 255)
ACCENT_2 = (47, 191, 113)
FG = (240, 246, 255)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in (
        "C:/Windows/Fonts/seguisb.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_image(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # arka plan: yuvarlatilmis kare + dikey gradyan
    radius = int(size * 0.22)
    gradient = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(gradient)
    for y in range(size):
        ratio = y / max(size - 1, 1)
        color = tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * ratio) for i in range(3)
        )
        gdraw.line([(0, y), (size, y)], fill=color + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.paste(gradient, (0, 0), mask)

    # cerceve
    draw.rounded_rectangle(
        [int(size * 0.03), int(size * 0.03), size - int(size * 0.03), size - int(size * 0.03)],
        radius=int(radius * 0.9),
        outline=ACCENT + (170,),
        width=max(2, int(size * 0.012)),
    )

    # aksan cizgileri
    draw.rounded_rectangle(
        [int(size * 0.12), int(size * 0.70), int(size * 0.88), int(size * 0.745)],
        radius=int(size * 0.02),
        fill=ACCENT_2 + (230,),
    )
    draw.rounded_rectangle(
        [int(size * 0.12), int(size * 0.79), int(size * 0.58), int(size * 0.825)],
        radius=int(size * 0.017),
        fill=ACCENT + (200,),
    )

    # MNS yazisi
    text = "MNS"
    font = _font(int(size * 0.34))
    bbox = draw.textbbox((0, 0), text, font=font)
    tx = (size - (bbox[2] - bbox[0])) / 2 - bbox[0]
    ty = size * 0.30 - bbox[1]
    draw.text((tx + size * 0.012, ty + size * 0.012), text, font=font, fill=(0, 0, 0, 110))
    draw.text((tx, ty), text, font=font, fill=FG + (255,))

    # kucuk nokta (durum ledi)
    dot = int(size * 0.055)
    draw.ellipse(
        [size - int(size * 0.22), int(size * 0.16), size - int(size * 0.22) + dot,
         int(size * 0.16) + dot],
        fill=ACCENT_2 + (255,),
    )
    return img


def write_ico(frames: list[Image.Image], target: Path) -> None:
    """PNG tabanli cok boyutlu .ico dosyasi yazar (Windows Vista+ destekler)."""
    import io
    import struct

    payloads = []
    for frame in frames:
        buffer = io.BytesIO()
        frame.save(buffer, format="PNG", optimize=True)
        payloads.append(buffer.getvalue())

    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    for frame, data in zip(frames, payloads):
        size = frame.width
        dim = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)

    target.write_bytes(header + entries + b"".join(payloads))


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    base = make_image(1024)
    base.save(PNG)
    frames = [base.resize((s, s), Image.LANCZOS) for s in sorted(SIZES)]
    write_ico(frames, ICO)
    print(f"Ikon olusturuldu: {ICO} ({ICO.stat().st_size} bayt)")
    print(f"PNG olusturuldu  : {PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
