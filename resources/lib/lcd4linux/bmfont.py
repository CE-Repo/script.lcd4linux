"""Loader and renderer for the bundled ``.l4f`` bitmap fonts.

The format is produced by ``tools/mkfont.py``.  Everything here is pure
Python so it works on any Kodi build without extra binary modules.

Layout of a ``.l4f`` file (all little endian)::

    'L4F2'                     magic
    u8 name_len, u8 reserved
    name_len bytes             font name, utf-8
    u16 size, u16 ascent, u16 descent, u16 line_height, u32 glyph_count
    glyph_count * (u32 codepoint, i16 advance, i16 bearing_x, i16 bearing_y,
                   u8 width, u8 height, u32 offset)
    u32 blob_len, u32 packed_len
    packed_len bytes           zlib compressed alpha bitmaps (8 bit coverage)
"""

import os
import struct
import zlib

MAGIC = b"L4F2"

_GLYPH_STRUCT = struct.Struct("<IhhhBBI")
_HEAD_STRUCT = struct.Struct("<HHHHI")

#: Families that ship with the add-on, in the order they are offered.
FAMILIES = ("sans", "sans-bold", "mono", "mono-bold")


class Glyph(object):
    """A single rasterised character.

    ``rows`` holds one entry per bitmap row: ``(x_offset, alpha_bytes)`` with
    fully transparent pixels already trimmed from both ends, which keeps the
    inner blit loop short for the many glyphs that are mostly empty.
    """

    __slots__ = ("code", "advance", "bearing_x", "bearing_y", "width",
                 "height", "rows")

    def __init__(self, code, advance, bearing_x, bearing_y, width, height, rows):
        self.code = code
        self.advance = advance
        self.bearing_x = bearing_x
        self.bearing_y = bearing_y
        self.width = width
        self.height = height
        self.rows = rows


def _trim_rows(data, width, height):
    rows = []
    for y in range(height):
        line = data[y * width:(y + 1) * width]
        start = 0
        end = width
        while start < end and line[start] == 0:
            start += 1
        while end > start and line[end - 1] == 0:
            end -= 1
        if start >= end:
            rows.append(None)
        else:
            rows.append((start, line[start:end]))
    return rows


class Font(object):
    """A bitmap font at one specific pixel size."""

    def __init__(self, name, size, ascent, descent, line_height, glyphs):
        self.name = name
        self.size = size
        self.ascent = ascent
        self.descent = descent
        self.line_height = line_height
        self._glyphs = glyphs
        self._fallback = glyphs.get(0x3F) or glyphs.get(0x20)

    # -- construction -----------------------------------------------------
    @classmethod
    def load(cls, path):
        with open(path, "rb") as fh:
            raw = fh.read()
        if raw[:4] != MAGIC:
            raise ValueError("%s is not a lcd4linux bitmap font" % path)
        pos = 4
        name_len = raw[pos]
        pos += 2
        name = raw[pos:pos + name_len].decode("utf-8")
        pos += name_len
        size, ascent, descent, line_height, count = _HEAD_STRUCT.unpack_from(raw, pos)
        pos += _HEAD_STRUCT.size
        entries = []
        for _ in range(count):
            entries.append(_GLYPH_STRUCT.unpack_from(raw, pos))
            pos += _GLYPH_STRUCT.size
        blob_len, packed_len = struct.unpack_from("<II", raw, pos)
        pos += 8
        blob = zlib.decompress(raw[pos:pos + packed_len])
        if len(blob) != blob_len:
            raise ValueError("corrupt font %s" % path)

        glyphs = {}
        for code, advance, bx, by, bw, bh, off in entries:
            if bw and bh:
                rows = _trim_rows(blob[off:off + bw * bh], bw, bh)
            else:
                rows = []
            glyphs[code] = Glyph(code, advance, bx, by, bw, bh, rows)
        return cls(name, size, ascent, descent, line_height, glyphs)

    # -- glyph access -----------------------------------------------------
    def glyph(self, code):
        return self._glyphs.get(code, self._fallback)

    def measure(self, text):
        """Return the advance width of ``text`` in pixels."""
        width = 0
        get = self._glyphs.get
        fallback = self._fallback
        for ch in text:
            glyph = get(ord(ch), fallback)
            if glyph is not None:
                width += glyph.advance
        return width

    def ellipsize(self, text, max_width, ellipsis=u"…"):
        """Shorten ``text`` so it fits into ``max_width`` pixels."""
        if max_width <= 0 or self.measure(text) <= max_width:
            return text
        dots = self.measure(ellipsis)
        if dots > max_width:
            return u""
        budget = max_width - dots
        out = []
        width = 0
        get = self._glyphs.get
        for ch in text:
            glyph = get(ord(ch), self._fallback)
            if glyph is None:
                continue
            if width + glyph.advance > budget:
                break
            out.append(ch)
            width += glyph.advance
        return u"".join(out).rstrip() + ellipsis

    def wrap(self, text, max_width):
        """Greedy word wrap, returns a list of lines."""
        lines = []
        for paragraph in text.split("\n"):
            words = paragraph.split(" ")
            current = ""
            for word in words:
                candidate = word if not current else current + " " + word
                if self.measure(candidate) <= max_width or not current:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        return lines


class _ScaledFont(Font):
    """A font resampled from a neighbouring size.

    Only used when a layout asks for a pixel size that is not bundled; the
    alpha bitmaps are resampled with bilinear interpolation once and then
    cached like any other font.
    """

    def __init__(self, base, size):
        factor = float(size) / float(base.size)
        glyphs = {}
        for code, glyph in base._glyphs.items():
            glyphs[code] = _scale_glyph(glyph, factor)
        Font.__init__(self, "%s@%d" % (base.name, size), size,
                      int(round(base.ascent * factor)),
                      int(round(base.descent * factor)),
                      max(1, int(round(base.line_height * factor))), glyphs)


def _scale_glyph(glyph, factor):
    width = int(round(glyph.width * factor))
    height = int(round(glyph.height * factor))
    advance = int(round(glyph.advance * factor))
    bx = int(round(glyph.bearing_x * factor))
    by = int(round(glyph.bearing_y * factor))
    if not width or not height or not glyph.rows:
        return Glyph(glyph.code, advance, bx, by, 0, 0, [])

    # Expand the trimmed rows back into a dense bitmap for resampling.
    src = bytearray(glyph.width * glyph.height)
    for y, row in enumerate(glyph.rows):
        if row is None:
            continue
        start, data = row
        base = y * glyph.width + start
        src[base:base + len(data)] = data

    dst = bytearray(width * height)
    sw, sh = glyph.width, glyph.height
    for y in range(height):
        fy = (y + 0.5) * sh / height - 0.5
        y0 = int(fy) if fy >= 0 else 0
        y1 = min(y0 + 1, sh - 1)
        wy = fy - y0
        if wy < 0:
            wy = 0.0
        for x in range(width):
            fx = (x + 0.5) * sw / width - 0.5
            x0 = int(fx) if fx >= 0 else 0
            x1 = min(x0 + 1, sw - 1)
            wx = fx - x0
            if wx < 0:
                wx = 0.0
            a = (src[y0 * sw + x0] * (1 - wx) + src[y0 * sw + x1] * wx) * (1 - wy) \
                + (src[y1 * sw + x0] * (1 - wx) + src[y1 * sw + x1] * wx) * wy
            dst[y * width + x] = int(a + 0.5)
    return Glyph(glyph.code, advance, bx, by, width, height,
                 _trim_rows(bytes(dst), width, height))


class FontCache(object):
    """Finds, loads and caches fonts, with nearest-size fallback."""

    def __init__(self, directories):
        self.directories = [d for d in directories if d]
        self._cache = {}
        self._available = None

    # -- discovery --------------------------------------------------------
    def available(self):
        """Map of family name -> sorted list of bundled pixel sizes."""
        if self._available is None:
            found = {}
            for directory in self.directories:
                try:
                    names = os.listdir(directory)
                except OSError:
                    continue
                for name in names:
                    if not name.endswith(".l4f"):
                        continue
                    stem = name[:-4]
                    family, _, size = stem.rpartition("-")
                    if not family or not size.isdigit():
                        continue
                    found.setdefault(family, {})[int(size)] = os.path.join(directory, name)
            self._available = found
        return self._available

    def families(self):
        return sorted(self.available().keys())

    # -- loading ----------------------------------------------------------
    def get(self, family, size):
        """Return a :class:`Font`; falls back to a bundled family/size."""
        family = (family or "sans").strip()
        size = max(6, int(size or 16))
        key = (family, size)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        table = self.available()
        sizes = table.get(family)
        if sizes is None:
            # Unknown family: try the plain weight, then anything at all.
            base = family.split("-")[0]
            sizes = table.get(base)
            if sizes is None and table:
                sizes = table[sorted(table)[0]]
        if not sizes:
            raise IOError("no bitmap fonts found in %s" % (self.directories,))

        if size in sizes:
            font = Font.load(sizes[size])
        else:
            nearest = min(sizes, key=lambda s: (abs(s - size), -s))
            base_font = self._load_exact(sizes[nearest])
            font = _ScaledFont(base_font, size)
        self._cache[key] = font
        return font

    def _load_exact(self, path):
        key = ("path", path)
        cached = self._cache.get(key)
        if cached is None:
            cached = Font.load(path)
            self._cache[key] = cached
        return cached

    def clear(self):
        self._cache.clear()
        self._available = None
