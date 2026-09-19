"""Fonts: finding a face, and turning it into glyphs the canvas can draw.

A face is a ``.ttf``/``.otf`` file rasterised at the exact pixel size a
layout asks for; :mod:`.ttfont` does that part.  The add-on used to carry
every glyph pre-rendered at nine sizes instead, which is what the ``.l4f``
reader below is still for: a bitmap font someone built earlier keeps working
if they drop it into their own fonts folder.

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

from . import gfonts
from . import ttfont
from .logger import debug

MAGIC = b"L4F2"

#: Extensions a face is looked for under, best first.
FACE_SUFFIXES = (".ttf", ".otf", ".ttc")

#: The bitmap format the add-on used to ship; still read, never written.
BITMAP_SUFFIX = ".l4f"

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
        # Through advance_of() rather than the glyph table: a scaled font
        # fills that table on demand and can answer a width without
        # rasterising the character first.
        get = self.advance_of
        for ch in text:
            width += get(ord(ch))
        return width

    def advance_of(self, code):
        """Advance width of one codepoint, 0 if the font has no glyph."""
        glyph = self._glyphs.get(code, self._fallback)
        return glyph.advance if glyph is not None else 0

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
        get = self.advance_of
        for ch in text:
            advance = get(ord(ch))
            if width + advance > budget:
                break
            out.append(ch)
            width += advance
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

    Only used when a layout asks for a pixel size that is not bundled.

    Characters are resampled the first time they are actually drawn, not all
    of them up front.  A bundled font carries some 360 glyphs while a page
    uses a few dozen, and resampling the whole set in pure Python is what
    used to make the first frame after a cold start take seconds per font -
    on a slow box, long enough to look like the add-on was not running.
    Advances are derived from the base font, so measuring, wrapping and
    ellipsizing never rasterise anything.
    """

    def __init__(self, base, size):
        factor = float(size) / float(base.size)
        self._base = base
        self._factor = factor
        Font.__init__(self, "%s@%d" % (base.name, size), size,
                      int(round(base.ascent * factor)),
                      int(round(base.descent * factor)),
                      max(1, int(round(base.line_height * factor))), {})

    def glyph(self, code):
        # The base font resolves its own fallback, so cache under the
        # codepoint it actually returned - otherwise every unknown character
        # would resample the fallback glyph again.
        source = self._base.glyph(code)
        if source is None:
            return None
        cached = self._glyphs.get(source.code)
        if cached is None:
            cached = _scale_glyph(source, self._factor)
            self._glyphs[source.code] = cached
        return cached

    def advance_of(self, code):
        source = self._base.glyph(code)
        if source is None:
            return 0
        return int(round(source.advance * self._factor))


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

    # The horizontal sample positions do not depend on the row, so they are
    # worked out once instead of once per pixel.  That keeps the inner loop
    # down to four lookups and a handful of multiplications, which matters
    # because this is the hottest pure-Python loop in the add-on.
    columns = []
    for x in range(width):
        fx = (x + 0.5) * sw / width - 0.5
        x0 = int(fx) if fx >= 0 else 0
        x1 = x0 + 1
        if x1 > sw - 1:
            x1 = sw - 1
        wx = fx - x0
        if wx < 0.0:
            wx = 0.0
        columns.append((x0, x1, wx, 1.0 - wx))

    pos = 0
    for y in range(height):
        fy = (y + 0.5) * sh / height - 0.5
        y0 = int(fy) if fy >= 0 else 0
        y1 = y0 + 1
        if y1 > sh - 1:
            y1 = sh - 1
        wy = fy - y0
        if wy < 0.0:
            wy = 0.0
        row0 = y0 * sw
        row1 = y1 * sw
        if row0 == row1 or wy == 0.0:
            # Sampling lands on a source row: no vertical blend needed.
            for x0, x1, wx, ix in columns:
                dst[pos] = int(src[row0 + x0] * ix + src[row0 + x1] * wx + 0.5)
                pos += 1
        else:
            iwy = 1.0 - wy
            for x0, x1, wx, ix in columns:
                top = src[row0 + x0] * ix + src[row0 + x1] * wx
                bottom = src[row1 + x0] * ix + src[row1 + x1] * wx
                dst[pos] = int(top * iwy + bottom * wy + 0.5)
                pos += 1
    return Glyph(glyph.code, advance, bx, by, width, height,
                 _trim_rows(bytes(dst), width, height))


def text_mask(font, text, margin=1):
    """Rasterise ``text`` into ``(width, height, coverage)``.

    The coverage map is one byte per pixel, which is what the glyphs hold
    anyway.  Used for the font samples the editor shows: a picture with a
    real alpha channel sits on any background, and the browser cannot draw
    a bitmap font itself.
    """
    margin = max(0, int(margin))
    width = max(1, font.measure(text) + 2 * margin)
    height = max(1, font.ascent + font.descent + 2 * margin)
    baseline = font.ascent + margin
    mask = bytearray(width * height)
    pen = margin
    for character in text:
        glyph = font.glyph(ord(character))
        if glyph is None:
            continue
        gx = pen + glyph.bearing_x
        gy = baseline - glyph.bearing_y
        for row_index, row in enumerate(glyph.rows or ()):
            if row is None:
                continue
            py = gy + row_index
            if py < 0 or py >= height:
                continue
            start, data = row
            px = gx + start
            base = py * width
            for value in data:
                if 0 <= px < width and value > mask[base + px]:
                    # The brighter of two overlapping glyphs wins, so a
                    # kerned pair does not come out darker where it meets.
                    mask[base + px] = value
                px += 1
        pen += glyph.advance
    return width, height, mask


class VectorFont(Font):
    """A face rasterised at one pixel size, a glyph at a time.

    The whole point of moving off the bitmap format is that any size is now
    the right size, so nothing is pre-rendered: a page uses a few dozen
    characters out of the several hundred a face carries, and rasterising
    the rest would be work nobody asked for.  Advances come straight from
    the face's metrics, so measuring, wrapping and ellipsizing a string
    never draws anything.
    """

    def __init__(self, face, name, size):
        self._face = face
        self._advances = {}
        self._missing = set()
        Font.__init__(self, name, size, face.ascent, face.descent,
                      max(1, face.height), {})

    # -- glyphs ------------------------------------------------------------
    def glyph(self, code):
        cached = self._glyphs.get(code)
        if cached is not None:
            return cached
        if code in self._missing:
            return self._fallback_glyph()
        rendered = self._face.render(code)
        if rendered is None:
            self._missing.add(code)
            return self._fallback_glyph()
        width, height, left, top, advance, coverage = rendered
        rows = _trim_rows(coverage, width, height) if width and height else []
        # bearing_y counts up from the baseline, which is what FreeType's
        # bitmap_top already is.
        glyph = Glyph(code, advance, left, top, width, height, rows)
        self._glyphs[code] = glyph
        self._advances[code] = advance
        return glyph

    def _fallback_glyph(self):
        """What a character the face does not carry is drawn as."""
        for code in (0x3F, 0x20):               # '?', then a blank
            if code in self._missing:
                continue
            glyph = self._glyphs.get(code)
            if glyph is None:
                glyph = self.glyph(code)
            if glyph is not None:
                return glyph
        return None

    def advance_of(self, code):
        cached = self._advances.get(code)
        if cached is not None:
            return cached
        advance = self._face.advance(code)
        if advance is None:
            fallback = self._fallback_glyph()
            advance = fallback.advance if fallback is not None else 0
            self._missing.add(code)
        self._advances[code] = advance
        return advance

    def close(self):
        self._face.close()


class FontCache(object):
    """Finds, loads and caches fonts.

    A family is a file named after it - ``sans.ttf``, ``mono-bold.ttf`` -
    looked for in each directory in turn, so a face dropped into the user's
    own fonts folder overrides a bundled one of the same name.  The old
    ``family-size.l4f`` bitmaps are still picked up where they exist.

    A name that is none of those but is in the Google Fonts catalogue is
    handed to :mod:`.gfonts`, which downloads it in the background; until
    the file is there the layout is drawn in a stand-in of the same kind,
    and the real face takes over on a later frame.
    """

    def __init__(self, directories):
        self.directories = [d for d in directories if d]
        self._cache = {}
        self._faces = None
        self._bitmaps = None
        #: Keys drawn in a stand-in, against the download count at the time.
        self._waiting = {}

    # -- discovery ---------------------------------------------------------
    def _scan(self):
        """Walk the font directories once, remembering what is where."""
        if self._faces is not None:
            return
        faces = {}
        bitmaps = {}
        # Reversed so that the first directory wins: it is scanned last and
        # overwrites whatever a later one put in.
        for directory in reversed(self.directories):
            try:
                names = sorted(os.listdir(directory))
            except OSError:
                continue
            for name in names:
                stem, _dot, suffix = name.rpartition(".")
                suffix = "." + suffix.lower()
                path = os.path.join(directory, name)
                if suffix in FACE_SUFFIXES:
                    if stem:
                        faces[stem] = path
                elif suffix == BITMAP_SUFFIX:
                    family, _sep, size = stem.rpartition("-")
                    if family and size.isdigit():
                        bitmaps.setdefault(family, {})[int(size)] = path
        self._faces = faces
        self._bitmaps = bitmaps

    def available(self):
        """Map of family name -> sorted list of bundled pixel sizes.

        A face has no fixed sizes, so it reports an empty list; what the
        editor wants from this is the family names.
        """
        self._scan()
        found = dict((family, sorted(sizes))
                     for family, sizes in self._bitmaps.items())
        for family in self._faces:
            found.setdefault(family, [])
        return found

    def families(self):
        self._scan()
        return sorted(set(self._faces) | set(self._bitmaps))

    def backend_name(self):
        """Which rasteriser the faces go through, for the log and dialogs.

        Nothing picks a backend until a face is actually opened, so asking
        before the first frame would only ever answer "not started yet";
        one character settles it.
        """
        if ttfont.backend is None:
            try:
                self.get(FAMILIES[0], 16).glyph(0x41)
            except Exception as error:
                debug("cannot open a face to probe the rasteriser: %s" % error)
        return ttfont.backend_name()

    # -- loading -----------------------------------------------------------
    def get(self, family, size):
        """Return a :class:`Font`; falls back to a bundled family."""
        family = (family or "sans").strip()
        size = max(6, int(size or 16))
        key = (family, size)
        cached = self._cache.get(key)
        if cached is not None:
            seen = self._waiting.get(key)
            if seen is None or seen == gfonts.generation:
                return cached
            # A face has landed since this one was drawn in a stand-in; it
            # may or may not be this family's, so build it again and find
            # out.  Downloads are rare, frames are not.
            del self._cache[key]
            del self._waiting[key]
        font, waiting = self._build(family, size)
        self._cache[key] = font
        if waiting:
            self._waiting[key] = gfonts.generation
        return font

    def _build(self, family, size):
        """``(font, waiting)`` for what a layout asked for.

        ``waiting`` says the font is a stand-in because the real face is
        still downloading, which is what tells :meth:`get` not to keep it.
        """
        self._scan()
        font = self._local(family, size)
        if font is not None:
            return font, False

        # Not on disk under that name, but Google may have it.
        google = gfonts.resolve(family)[0]
        if google:
            path = gfonts.request(family)
            if path:
                font = self._face(path, family, size)
                if font is not None:
                    return font, False
            else:
                # Queued, or downloads are off.  Either way something has to
                # be drawn now, in the same kind of face so the layout does
                # not jump about when the real one arrives.
                return self._stand_in(family, google, size), True

        # Unknown: the family's own base weight first, so ``oswald-bold``
        # lands on ``oswald`` rather than on the default face.
        base, _dash, _weight = family.rpartition("-")
        if base:
            font = self._local(base, size)
            if font is not None:
                return font, False
        return self._stand_in(family, None, size), False

    def _local(self, family, size):
        """A face or bitmap font on disk, or ``None`` if there is none."""
        path = self._faces.get(family)
        if path is not None:
            font = self._face(path, family, size)
            if font is not None:
                return font
        sizes = self._bitmaps.get(family)
        if sizes:
            if size in sizes:
                return self._load_exact(sizes[size])
            nearest = min(sizes, key=lambda s: (abs(s - size), -s))
            return _ScaledFont(self._load_exact(sizes[nearest]), size)
        return None

    def _face(self, path, family, size):
        try:
            return VectorFont(ttfont.open_face(path, size), family, size)
        except (ttfont.FontError, IOError, OSError, struct.error) as error:
            # A face that cannot be read must not take the display down;
            # a bitmap font, or another family, still draws something.
            debug("cannot use %s at %d px: %s" % (path, size, error))
            return None

    def _stand_in(self, family, google, size):
        """What to draw in while the real face is missing.

        A monospaced family is stood in for by ``mono``: swapping a column
        of figures to a proportional face and back again is the one
        substitution anybody notices.  Every candidate is tried rather than
        only named, because a face that will not open is no stand-in.
        """
        entry = gfonts.catalogue().get(google) if google else None
        base = "mono" if entry and entry["category"] == "Monospace" else "sans"
        if family.lower().endswith("-bold"):
            base += "-bold"
        tried = []
        for candidate in (base, base.split("-")[0]) + FAMILIES \
                + tuple(self.families()):
            if candidate in tried:
                continue
            tried.append(candidate)
            font = self._local(candidate, size)
            if font is not None:
                return font
        raise IOError("no usable font for %r in %s"
                      % (family, self.directories))

    def _load_exact(self, path):
        key = ("path", path)
        cached = self._cache.get(key)
        if cached is None:
            cached = Font.load(path)
            self._cache[key] = cached
        return cached

    def clear(self):
        for font in list(self._cache.values()):
            close = getattr(font, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass
        self._cache.clear()
        self._waiting.clear()
        self._faces = None
        self._bitmaps = None
