#!/usr/bin/env python3
"""Build-time rasteriser for the bitmap fonts shipped with script.lcd4linux.

The add-on has to run on a plain CoreELEC/Kodi Python installation where
neither Pillow nor FreeType is available, so all glyphs are rasterised here
(on a development machine) into a compact binary format that the add-on can
read with nothing but ``struct`` and ``zlib``.

Every family covers the same characters.  Most faces stop somewhere in Latin
Extended-A and none of them draws ``⏵ ⏸ ⏹ ♪ ✓``, so a glyph the chosen face
does not have is taken from DejaVu instead: a layout never loses a character
by picking a different font.

Needs Pillow and fontTools on the machine that runs it; the add-on itself
needs neither.

Usage:  python3 tools/mkfont.py [output-dir] [family ...]
"""

import os
import struct
import sys
import urllib.request
import zlib

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

MAGIC = b"L4F2"

SOURCE_DIR = "/usr/share/fonts/truetype/dejavu"

#: Where a glyph comes from when the family itself has none, in the order
#: they are asked.  DejaVu carries the letters; the play, pause and stop
#: signs are in none of the text faces, not even DejaVu, so Noto's symbol
#: font closes that gap.
FALLBACKS = ("DejaVuSans.ttf", "NotoSansSymbols2-Regular.ttf")

#: A monospaced face borrows from a monospaced one first: a column of
#: figures that picks up one proportional letter stops lining up, which is
#: the only reason anyone chose a monospaced font in the first place.
MONO_FALLBACKS = ("DejaVuSansMono.ttf",) + FALLBACKS

#: The repository carries the rasterised bitmaps, not the TTFs behind them:
#: a source face is ten times the size of the sizes anyone would ship, and
#: it would be dead weight on every box that installs the add-on.  They are
#: fetched once into ``build/fonts``, which git ignores.
CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "build", "fonts")

GOOGLE = "https://raw.githubusercontent.com/google/fonts/main/"

#: source file -> (directory in the google/fonts repository, licence name)
#: Every one of these is SIL Open Font License 1.1 or Apache 2.0, so the
#: add-on may ship what it rasterises out of them.
SOURCES = {
    "Inter[opsz,wght].ttf": ("ofl/inter", "Inter"),
    "Roboto[wdth,wght].ttf": ("ofl/roboto", "Roboto"),
    "RobotoCondensed[wght].ttf": ("ofl/robotocondensed", "RobotoCondensed"),
    "Oswald[wght].ttf": ("ofl/oswald", "Oswald"),
    "BebasNeue-Regular.ttf": ("ofl/bebasneue", "BebasNeue"),
    "Anton-Regular.ttf": ("ofl/anton", "Anton"),
    "Michroma-Regular.ttf": ("ofl/michroma", "Michroma"),
    "JetBrainsMono[wght].ttf": ("ofl/jetbrainsmono", "JetBrainsMono"),
    "NotoSansSymbols2-Regular.ttf": ("ofl/notosanssymbols2", "NotoSansSymbols2"),
    "SourceCodePro[wght].ttf": ("ofl/sourcecodepro", "SourceCodePro"),
    "RobotoMono[wght].ttf": ("ofl/robotomono", "RobotoMono"),
    "FiraMono-Regular.ttf": ("ofl/firamono", "FiraMono"),
    "FiraMono-Bold.ttf": ("ofl/firamono", "FiraMono"),
    "IBMPlexMono-Regular.ttf": ("ofl/ibmplexmono", "IBMPlexMono"),
    "IBMPlexMono-Bold.ttf": ("ofl/ibmplexmono", "IBMPlexMono"),
    "Inconsolata[wdth,wght].ttf": ("ofl/inconsolata", "Inconsolata"),
    "SpaceMono-Regular.ttf": ("ofl/spacemono", "SpaceMono"),
    "ShareTechMono-Regular.ttf": ("ofl/sharetechmono", "ShareTechMono"),
    "CourierPrime-Regular.ttf": ("ofl/courierprime", "CourierPrime"),
}


def source(name):
    """Local path of a source face, downloading it on first use."""
    local = os.path.join(SOURCE_DIR, name)
    if os.path.exists(local):
        return local
    if name not in SOURCES:
        raise IOError("no source known for %r" % name)
    cached = os.path.join(CACHE_DIR, name)
    if not os.path.exists(cached):
        os.makedirs(CACHE_DIR, exist_ok=True)
        directory, _licence = SOURCES[name]
        url = GOOGLE + directory + "/" + urllib.parse.quote(name, safe="[],")
        print("fetching %s" % url)
        urllib.request.urlretrieve(url, cached)
    return cached


def fetch_licences(outdir):
    """Put the licence of every downloaded face next to the bitmaps."""
    written = []
    for name, (directory, licence) in sorted(SOURCES.items()):
        target = os.path.join(outdir, "LICENSE-%s.txt" % licence)
        if os.path.exists(target):
            continue
        for filename in ("OFL.txt", "LICENSE.txt"):
            try:
                with urllib.request.urlopen(GOOGLE + directory + "/" + filename) as fh:
                    text = fh.read()
            except Exception:
                continue
            with open(target, "wb") as handle:
                handle.write(text)
            written.append(target)
            break
        else:
            print("WARNING: no licence found for %s" % licence)
    return written

# The large sizes matter: layouts meant to be read from across the room use
# 80 to 130 px type, and resampling that far up from 64 px looks soft.  The
# small ones only matter for faces anyone would set a status line in, so a
# display face that is unreadable below 20 px does not carry them.
TEXT_SIZES = (12, 16, 20, 24, 32, 48, 64, 96)
BOLD_SIZES = (12, 16, 20, 24, 32, 48, 64, 96, 128)
DISPLAY_SIZES = (20, 24, 32, 48, 64, 96)
MONO_SIZES = (12, 16, 20, 24, 32, 48, 64)

#: family -> (source, sizes in pixels).  The source is a file name, or that
#: name with the instance a variable font is pinned to: without one a
#: variable face draws its lightest weight.
FAMILIES = {
    # The workhorses, from the DejaVu the build machine already has.
    "sans": ("DejaVuSans.ttf", TEXT_SIZES),
    "sans-bold": ("DejaVuSans-Bold.ttf", BOLD_SIZES),

    # Text faces: what a status line or a track title is set in.
    "inter": (("Inter[opsz,wght].ttf", {"wght": 400, "opsz": 28}), TEXT_SIZES),
    "inter-bold": (("Inter[opsz,wght].ttf", {"wght": 700, "opsz": 28}),
                   TEXT_SIZES),
    "roboto": (("Roboto[wdth,wght].ttf", {"wght": 400, "wdth": 100}),
               TEXT_SIZES),
    "roboto-bold": (("Roboto[wdth,wght].ttf", {"wght": 700, "wdth": 100}),
                    TEXT_SIZES),

    # Narrow faces: a long title fits across 480 pixels in these.
    "condensed": (("RobotoCondensed[wght].ttf", {"wght": 400}), TEXT_SIZES),
    "condensed-bold": (("RobotoCondensed[wght].ttf", {"wght": 700}),
                       TEXT_SIZES),
    "oswald": (("Oswald[wght].ttf", {"wght": 400}), DISPLAY_SIZES),
    "oswald-bold": (("Oswald[wght].ttf", {"wght": 600}), DISPLAY_SIZES),

    # Display faces: headlines and clocks, no use below 20 px.
    "bebas": ("BebasNeue-Regular.ttf", DISPLAY_SIZES),
    "anton": ("Anton-Regular.ttf", DISPLAY_SIZES),
    "michroma": ("Michroma-Regular.ttf", DISPLAY_SIZES),

    # Monospace: columns of figures that must not wobble.
    "mono": ("DejaVuSansMono.ttf", (12, 16, 20, 24, 32, 48)),
    "mono-bold": ("DejaVuSansMono-Bold.ttf", (12, 16, 20, 24, 32, 48, 64, 96)),
    "jetbrains": (("JetBrainsMono[wght].ttf", {"wght": 400}), MONO_SIZES),
    "jetbrains-bold": (("JetBrainsMono[wght].ttf", {"wght": 700}), MONO_SIZES),
    "sourcecode": (("SourceCodePro[wght].ttf", {"wght": 400}), MONO_SIZES),
    "sourcecode-bold": (("SourceCodePro[wght].ttf", {"wght": 700}), MONO_SIZES),
    "robotomono": (("RobotoMono[wght].ttf", {"wght": 400}), MONO_SIZES),
    "robotomono-bold": (("RobotoMono[wght].ttf", {"wght": 700}), MONO_SIZES),
    "firamono": ("FiraMono-Regular.ttf", MONO_SIZES),
    "firamono-bold": ("FiraMono-Bold.ttf", MONO_SIZES),
    "plexmono": ("IBMPlexMono-Regular.ttf", MONO_SIZES),
    "plexmono-bold": ("IBMPlexMono-Bold.ttf", MONO_SIZES),
    "inconsolata": (("Inconsolata[wdth,wght].ttf",
                     {"wght": 400, "wdth": 100}), MONO_SIZES),
    "inconsolata-bold": (("Inconsolata[wdth,wght].ttf",
                          {"wght": 700, "wdth": 100}), MONO_SIZES),
    "spacemono": ("SpaceMono-Regular.ttf", MONO_SIZES),
    "sharetech": ("ShareTechMono-Regular.ttf", MONO_SIZES),
    "courierprime": ("CourierPrime-Regular.ttf", MONO_SIZES),
}

#: Which of them keep every glyph the same width, fallbacks included.
MONOSPACED = frozenset(name for name in FAMILIES
                       if name.split("-")[0] in (
                           "mono", "jetbrains", "sourcecode", "robotomono",
                           "firamono", "plexmono", "inconsolata", "spacemono",
                           "sharetech", "courierprime"))

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


def _covered(path):
    """The code points ``path`` actually draws."""
    tt = TTFont(path, fontNumber=0, lazy=True)
    codes = set()
    for table in tt["cmap"].tables:
        codes.update(table.cmap.keys())
    tt.close()
    return codes


def _open(path, size, axes):
    font = ImageFont.truetype(path, size)
    if axes:
        # A variable font draws its lightest instance unless pinned.
        font.set_variation_by_axes(
            [axes.get(tag.decode() if isinstance(tag, bytes) else tag, 400)
             for tag in _axis_tags(path)])
    return font


def _axis_tags(path):
    tt = TTFont(path, fontNumber=0, lazy=True)
    tags = [axis.axisTag for axis in tt["fvar"].axes] if "fvar" in tt else []
    tt.close()
    return tags


def build(family, ttf, size, outdir, fallbacks=None):
    fallbacks = fallbacks or (MONO_FALLBACKS if family in MONOSPACED
                              else FALLBACKS)
    axes = None
    if isinstance(ttf, tuple):
        ttf, axes = ttf
    path = ttf if os.path.isabs(ttf) else source(ttf)
    font = _open(path, size, axes)
    have = _covered(path)
    spares = []          # loaded lazily, most families need none of them
    # A monospaced family keeps one cell width, whatever a glyph was
    # borrowed from: a figure column that picks up a proportional symbol
    # stops lining up.
    cell = None
    if family in MONOSPACED:
        try:
            cell = int(round(font.getlength("0")))
        except Exception:
            cell = None
    ascent, descent = font.getmetrics()
    line_height = ascent + descent

    glyphs = []
    blob = bytearray()
    # Scratch image, generously sized so no glyph is ever clipped.
    pad = size * 2 + 8
    scratch = Image.new("L", (size * 3 + 16, size * 3 + 16), 0)

    for code in charset():
        ch = chr(code)
        drawn = font
        if code not in have:
            # The face has no such glyph, so one of the fallbacks draws it
            # and the character does not silently vanish from a layout.
            if not spares:
                spares = [(_covered(source(name)),
                           ImageFont.truetype(source(name), size))
                          for name in fallbacks]
            for covers, spare in spares:
                if code in covers:
                    drawn = spare
                    break
        try:
            mask = drawn.getmask(ch, mode="L")
        except Exception:
            continue
        try:
            advance = int(round(drawn.getlength(ch)))
        except Exception:
            advance = size // 2
        # What was borrowed is centred in the cell rather than left hanging
        # off one edge of it.
        shift = 0
        if cell:
            if drawn is not font and advance != cell:
                shift = (cell - advance) // 2
            advance = cell

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
        draw.text((pad, pad), ch, font=drawn, fill=255, anchor="ls")
        bbox = scratch.getbbox()
        if bbox is None:
            glyphs.append((code, advance, 0, 0, 0, 0, len(blob)))
            continue
        x0, y0, x1, y1 = bbox
        bmp = scratch.crop(bbox)
        bw, bh = bmp.size
        # bearing_x: pixels right of the pen position
        # bearing_y: pixels above the baseline
        bearing_x = x0 - pad + shift
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
    wanted = sys.argv[2:]
    os.makedirs(outdir, exist_ok=True)
    for name in fetch_licences(outdir):
        print("licence: %s" % name)
    total = 0
    for family in sorted(FAMILIES):
        if wanted and family not in wanted:
            continue
        ttf, sizes = FAMILIES[family]
        for size in sorted(sizes):
            path, n = build(family, ttf, size, outdir)
            total += n
            print("%-44s %7d bytes" % (path, n))
    print("total: %d bytes" % total)


if __name__ == "__main__":
    main()
