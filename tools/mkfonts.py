#!/usr/bin/env python3
"""Build the faces that ship with script.lcd4linux.

The add-on rasterises outlines itself (see ``resources/lib/lcd4linux/
ttfont.py``), so what it needs on disk is the face, not a pile of bitmaps.
DejaVu covers every letter the add-on draws but none of the media transport
signs, so the three of those are merged in from Noto Sans Symbols 2, and the
result is cut down to the characters a display actually shows - a full
DejaVu Sans is 742 kB, most of it scripts no layout will ever ask for.

Needs fontTools on the machine that runs it; the add-on itself needs
nothing.  Run it again only to refresh the faces or widen the character set:

    python3 tools/mkfonts.py [output-dir]
"""

import os
import shutil
import sys
import tempfile
import urllib.request

from fontTools import subset
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(ROOT, "resources", "fonts")

#: Where a source face is looked for before it is downloaded.
SYSTEM_DIRS = ("/usr/share/fonts/truetype/dejavu",
               "/usr/share/fonts/truetype/noto",
               "/usr/share/fonts/TTF")

CACHE_DIR = os.path.join(ROOT, "build", "fonts")

GOOGLE = "https://raw.githubusercontent.com/google/fonts/main/"

#: source file -> where to fetch it and which licence it comes under.
SOURCES = {
    "DejaVuSans.ttf": (None, "DejaVu"),
    "DejaVuSans-Bold.ttf": (None, "DejaVu"),
    "DejaVuSansMono.ttf": (None, "DejaVu"),
    "DejaVuSansMono-Bold.ttf": (None, "DejaVu"),
    "NotoSansSymbols2-Regular.ttf": ("ofl/notosanssymbols2",
                                     "NotoSansSymbols2"),
}

#: The four families the add-on ships.  Everything else is meant to be
#: fetched on demand from the font picker.
FAMILIES = {
    "sans": "DejaVuSans.ttf",
    "sans-bold": "DejaVuSans-Bold.ttf",
    "mono": "DejaVuSansMono.ttf",
    "mono-bold": "DejaVuSansMono-Bold.ttf",
}

#: Glyphs no text face carries, taken from Noto's symbol font instead: the
#: play, pause and stop signs a player layout wants.
SYMBOL_SOURCE = "NotoSansSymbols2-Regular.ttf"
SYMBOL_CODES = (0x23F5, 0x23F8, 0x23F9)         # ⏵ ⏸ ⏹

#: Punctuation, arrows and shapes beyond Latin that layouts use.  They cost
#: a few hundred bytes together and save a user from a missing-glyph box.
SYMBOLS = (
    "‐‑–—‘’‚“”„†"
    "•…‰‹›€™←↑→↓"
    "−∞≈≠≤≥■▲▶▼◀"
    "●★☆♪♫✓✗°"
)


def charset():
    """Every codepoint the shipped faces keep."""
    codes = set()
    codes.update(range(0x20, 0x7F))             # ASCII
    codes.update(range(0xA0, 0x100))            # Latin-1 supplement
    codes.update(range(0x100, 0x180))           # Latin Extended-A
    codes.update(ord(character) for character in SYMBOLS)
    codes.update(SYMBOL_CODES)
    return sorted(codes)


def source(name):
    """Local path of a source face, downloading it on first use."""
    for directory in SYSTEM_DIRS:
        candidate = os.path.join(directory, name)
        if os.path.exists(candidate):
            return candidate
    cached = os.path.join(CACHE_DIR, name)
    if os.path.exists(cached):
        return cached
    os.makedirs(CACHE_DIR, exist_ok=True)
    directory, _licence = SOURCES[name]
    if directory is None:
        raise IOError("%s is not installed; install fonts-dejavu or put it "
                      "in %s" % (name, CACHE_DIR))
    url = GOOGLE + directory + "/" + name
    print("fetching %s" % url)
    urllib.request.urlretrieve(url, cached)
    return cached


def fetch_licences(outdir):
    """Keep the licence of every shipped face next to it."""
    for name, (directory, licence) in sorted(SOURCES.items()):
        target = os.path.join(outdir, "LICENSE-%s.txt" % licence)
        if os.path.exists(target) or directory is None:
            continue
        for filename in ("OFL.txt", "LICENSE.txt"):
            try:
                with urllib.request.urlopen(GOOGLE + directory + "/"
                                            + filename) as handle:
                    text = handle.read()
            except Exception:
                continue
            with open(target, "wb") as handle:
                handle.write(text)
            print("wrote %s" % os.path.basename(target))
            break
        else:
            print("WARNING: no licence found for %s" % licence)


def _subset(path, codes, output):
    """Cut ``path`` down to ``codes`` and write it to ``output``."""
    options = subset.Options()
    options.layout_features = ["*"]             # keep kerning
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.recalc_bounds = True
    options.drop_tables += ["DSIG"]
    # Keep the source's modification date.  fontTools would otherwise stamp
    # the current time into head, so rerunning this tool would rewrite four
    # binaries that are otherwise identical - a diff nobody made.
    options.recalc_timestamp = False
    font = subset.load_font(path, options)
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=codes)
    subsetter.subset(font)
    subset.save_font(font, output, options)
    font.close()


def _codes_in(path):
    """Every codepoint a face maps."""
    with TTFont(path, lazy=True) as font:
        covered = set()
        for table in font["cmap"].tables:
            covered.update(table.cmap.keys())
    return covered


def cell_width(font):
    """The fixed advance of a monospaced face, or ``None`` if it varies."""
    widths = {advance for advance, _bearing in font["hmtx"].metrics.values()
              if advance > 0}
    return widths.pop() if len(widths) == 1 else None


def _graft(target_font, donor_path, codes, cell=None):
    """Copy ``codes`` out of ``donor_path`` into an open ``TTFont``.

    fontTools' own merger wants two faces that agree on rather a lot - the
    em square among them - which a text face and a symbol face never do.
    Drawing the donor glyph through a pen sidesteps all of that: components
    are decomposed on the way and the transform rescales the outline into
    the target's em square.

    ``cell`` is the fixed advance of a monospaced face.  A borrowed glyph
    arrives with the donor's own width, and one wide character is all it
    takes to push a column of figures out of line, so it is scaled down to
    fit the cell and centred in it.
    """
    donor = TTFont(donor_path)
    try:
        factor = (target_font["head"].unitsPerEm
                  / float(donor["head"].unitsPerEm))
        donor_glyphs = donor.getGlyphSet()
        donor_cmap = donor.getBestCmap()
        glyf = target_font["glyf"]
        hmtx = target_font["hmtx"]
        order = list(target_font.getGlyphOrder())
        added = []
        for code in codes:
            donor_name = donor_cmap.get(code)
            if donor_name is None:
                continue
            name = "uni%04X" % code
            while name in order:
                name += "_"
            scale = factor
            shift = 0.0
            advance = donor_glyphs[donor_name].width * factor
            if cell:
                measure = BoundsPen(donor_glyphs)
                donor_glyphs[donor_name].draw(measure)
                bounds = measure.bounds or (0, 0, 0, 0)
                drawn = (bounds[2] - bounds[0]) * factor
                if drawn > cell:
                    scale = factor * cell / drawn
                    drawn = cell
                shift = (cell - drawn) / 2.0 - bounds[0] * scale
                advance = cell
            pen = TTGlyphPen(target_font.getGlyphSet())
            donor_glyphs[donor_name].draw(
                TransformPen(pen, (scale, 0, 0, scale, shift, 0)))
            outline = pen.glyph()
            outline.recalcBounds(glyf)
            glyf[name] = outline
            # The left side bearing has to be the glyph's own xMin: a
            # renderer positions the outline by it, so a stale 0 slides the
            # symbol sideways by however far its contours start from zero.
            hmtx[name] = (int(round(advance)), int(getattr(outline, "xMin", 0)))
            order.append(name)
            added.append((code, name))
        if not added:
            return []
        target_font.setGlyphOrder(order)
        target_font["maxp"].numGlyphs = len(order)
        for table in target_font["cmap"].tables:
            if table.isUnicode():
                for code, name in added:
                    table.cmap[code] = name
        return [code for code, _name in added]
    finally:
        donor.close()


def build(family, filename, outdir):
    """Subset one face, grafting on the symbol glyphs it is missing."""
    target = os.path.join(outdir, "%s.ttf" % family)
    base = source(filename)
    wanted = charset()
    missing = [code for code in SYMBOL_CODES if code not in _codes_in(base)]

    workdir = tempfile.mkdtemp(prefix="lcd4linux-fonts-")
    try:
        main = os.path.join(workdir, "main.ttf")
        _subset(base, [code for code in wanted if code not in missing], main)
        if not missing:
            shutil.copy(main, target)
        else:
            donor = os.path.join(workdir, "symbols.ttf")
            _subset(source(SYMBOL_SOURCE), missing, donor)
            # Graft rather than leave a hole: a layout that draws ⏸ should
            # get a pause sign in whatever face it asked for, not a box.
            font = TTFont(main, recalcTimestamp=False)
            try:
                grafted = _graft(font, donor, missing, cell_width(font))
                font.save(target)
            finally:
                font.close()
            if len(grafted) != len(missing):
                print("WARNING: %s is missing %d symbol(s)"
                      % (family, len(missing) - len(grafted)))
            missing = grafted
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    before = os.path.getsize(base)
    after = os.path.getsize(target)
    print("%-10s %-28s %6.1f kB -> %5.1f kB%s"
          % (family, filename, before / 1024.0, after / 1024.0,
             "  (+%d symbols)" % len(missing) if missing else ""))
    return after


def main(argv):
    outdir = argv[1] if len(argv) > 1 else OUTPUT_DIR
    os.makedirs(outdir, exist_ok=True)
    print("character set: %d codepoints" % len(charset()))
    total = 0
    for family, filename in sorted(FAMILIES.items()):
        total += build(family, filename, outdir)
    fetch_licences(outdir)
    print("\n%d faces, %.1f kB in total" % (len(FAMILIES), total / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
