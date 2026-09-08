#!/usr/bin/env python3
"""Build-time rasteriser for the bitmap fonts shipped with script.lcd4linux.

The add-on has to run on a plain CoreELEC/Kodi Python installation where
neither Pillow nor FreeType is available, so all glyphs are rasterised here
(on a development machine) into a compact binary format that the add-on can
read with nothing but ``struct`` and ``zlib``.

Usage:  python3 tools/mkfont.py [output-dir]
"""

import os
import struct
import sys
import zlib

from PIL import Image, ImageDraw, ImageFont

MAGIC = b"L4F2"

SOURCE_DIR = "/usr/share/fonts/truetype/dejavu"

# family -> (ttf file, sizes in pixels)
# The large sizes matter: layouts meant to be read from across the room use
# 80 to 130 px type, and resampling that far up from 64 px looks soft.
FAMILIES = {
    "sans": ("DejaVuSans.ttf", (12, 16, 20, 24, 32, 48, 64, 96)),
    "sans-bold": ("DejaVuSans-Bold.ttf", (12, 16, 20, 24, 32, 48, 64, 96, 128)),
    "mono": ("DejaVuSansMono.ttf", (12, 16, 20, 24, 32, 48)),
    "mono-bold": ("DejaVuSansMono-Bold.ttf", (12, 16, 20, 24, 32, 48, 64, 96)),
}

# Latin-1, Latin Extended-A and a curated set of symbols that layouts use.
SYMBOLS = (
    "‐‑–—‘’‚“”„†"
    "•…‰‹›€™←↑→↓"
    "−∞≈≠≤≥■▲▶▼◀"
    "●★☆♪♫✓✗⏵⏸⏹°"
)


def charset():
    codes = set()
    codes.update(range(0x20, 0x7F))       # ASCII
    codes.update(range(0xA0, 0x100))      # Latin-1 supplement
    codes.update(range(0x100, 0x180))     # Latin Extended-A
    codes.update(ord(c) for c in SYMBOLS)
    return sorted(codes)


def build(family, ttf, size, outdir):
    font = ImageFont.truetype(os.path.join(SOURCE_DIR, ttf), size)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent

    glyphs = []
    blob = bytearray()
    # Scratch image, generously sized so no glyph is ever clipped.
    pad = size * 2 + 8
    scratch = Image.new("L", (size * 3 + 16, size * 3 + 16), 0)

    for code in charset():
        ch = chr(code)
        try:
            mask = font.getmask(ch, mode="L")
        except Exception:
            continue
        try:
            advance = int(round(font.getlength(ch)))
        except Exception:
            advance = size // 2

        bw, bh = mask.size
        if bw and bh:
            glyph = Image.frombytes("L", (bw, bh), bytes(mask))
            bbox = glyph.getbbox()
        else:
            bbox = None

        if bbox is None:
            # Whitespace: advance only, no pixels.
            glyphs.append((code, advance, 0, 0, 0, 0, len(blob)))
            continue

        # Pillow's mask origin is the text origin at (0, ascent-top-of-line);
        # render through a draw call so the offsets stay consistent.
        scratch.paste(0, (0, 0, scratch.size[0], scratch.size[1]))
        draw = ImageDraw.Draw(scratch)
        draw.text((pad, pad), ch, font=font, fill=255, anchor="ls")
        bbox = scratch.getbbox()
        if bbox is None:
            glyphs.append((code, advance, 0, 0, 0, 0, len(blob)))
            continue
        x0, y0, x1, y1 = bbox
        bmp = scratch.crop(bbox)
        bw, bh = bmp.size
        # bearing_x: pixels right of the pen position
        # bearing_y: pixels above the baseline
        bearing_x = x0 - pad
        bearing_y = pad - y0
        glyphs.append((code, advance, bearing_x, bearing_y, bw, bh, len(blob)))
        blob.extend(bmp.tobytes())

    name = "%s-%d" % (family, size)
    header = bytearray()
    header.extend(MAGIC)
    nm = name.encode("utf-8")
    header.extend(struct.pack("<BB", len(nm), 0))
    header.extend(nm)
    header.extend(struct.pack("<HHHHI", size, ascent, descent, line_height, len(glyphs)))
    for code, advance, bx, by, bw, bh, off in glyphs:
        header.extend(struct.pack("<IhhhBBI", code, advance, bx, by, bw, bh, off))

    packed = zlib.compress(bytes(blob), 9)
    header.extend(struct.pack("<II", len(blob), len(packed)))
    header.extend(packed)

    path = os.path.join(outdir, name + ".l4f")
    with open(path, "wb") as fh:
        fh.write(bytes(header))
    return path, len(header)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "resources/fonts"
    os.makedirs(outdir, exist_ok=True)
    total = 0
    for family, (ttf, sizes) in FAMILIES.items():
        for size in sizes:
            path, n = build(family, ttf, size, outdir)
            total += n
            print("%-40s %7d bytes" % (path, n))
    print("total: %d bytes" % total)


if __name__ == "__main__":
    main()
