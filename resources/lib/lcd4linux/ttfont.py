"""Rasterising TrueType/OpenType outlines at run time.

The add-on used to ship every glyph pre-rendered at a handful of pixel sizes
because a stock Kodi has no imaging module.  That cost nine megabytes and
still only covered nine sizes, so four out of five pieces of text on screen
were resampled from a neighbouring size rather than drawn at their own.
Rasterising here instead makes every size the right one and reduces the
bundled fonts to the faces themselves.

Two backends, picked once at import time:

``freetype``
    ``libfreetype.so.6`` through ctypes, the same trick :mod:`.usbdev` uses
    for libusb.  Kodi draws its own interface with FreeType, so the library
    is already on the box, and it renders a glyph faster than the old format
    could be read off disk.

``python``
    A TrueType table reader feeding :mod:`.svgpath`, the scanline rasteriser
    the Font Awesome icons already go through.  Perhaps twenty times slower
    than FreeType and only used where the library cannot be loaded, but it
    keeps the add-on's promise that nothing outside it has to be installed.

Both hand back the same thing: a coverage bitmap with the pen offsets and
the advance, which is exactly what :class:`~.bmfont.Glyph` holds.
"""

import ctypes
import ctypes.util
import struct

from . import svgpath
from .logger import debug, log

# What ``render`` hands back:  ``(width, height, left, top, advance,
# coverage)``.  ``left``/``top`` are the pen offsets FreeType calls
# ``bitmap_left``/``bitmap_top`` - x to the right of the pen, y *above* the
# baseline - and ``coverage`` is one byte per pixel, row major.

#: Names to try, in order, before giving up on FreeType.
_LIBRARY_NAMES = ("libfreetype.so.6", "libfreetype.so", "libfreetype.dylib")


class FontError(Exception):
    """A face could not be opened or read."""


# ---------------------------------------------------------------------------
# FreeType through ctypes
# ---------------------------------------------------------------------------

_FT_Pos = ctypes.c_long
_FT_Fixed = ctypes.c_long
_FT_Long = ctypes.c_long


class _Vector(ctypes.Structure):
    _fields_ = [("x", _FT_Pos), ("y", _FT_Pos)]


class _BBox(ctypes.Structure):
    _fields_ = [("xMin", _FT_Pos), ("yMin", _FT_Pos),
                ("xMax", _FT_Pos), ("yMax", _FT_Pos)]


class _Generic(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("finalizer", ctypes.c_void_p)]


class _Bitmap(ctypes.Structure):
    _fields_ = [("rows", ctypes.c_uint), ("width", ctypes.c_uint),
                ("pitch", ctypes.c_int),
                ("buffer", ctypes.POINTER(ctypes.c_ubyte)),
                ("num_grays", ctypes.c_ushort), ("pixel_mode", ctypes.c_ubyte),
                ("palette_mode", ctypes.c_ubyte), ("palette", ctypes.c_void_p)]


class _Metrics(ctypes.Structure):
    _fields_ = [("width", _FT_Pos), ("height", _FT_Pos),
                ("horiBearingX", _FT_Pos), ("horiBearingY", _FT_Pos),
                ("horiAdvance", _FT_Pos),
                ("vertBearingX", _FT_Pos), ("vertBearingY", _FT_Pos),
                ("vertAdvance", _FT_Pos)]


class _Outline(ctypes.Structure):
    _fields_ = [("n_contours", ctypes.c_short), ("n_points", ctypes.c_short),
                ("points", ctypes.c_void_p), ("tags", ctypes.c_void_p),
                ("contours", ctypes.c_void_p), ("flags", ctypes.c_int)]


class _GlyphSlot(ctypes.Structure):
    _fields_ = [("library", ctypes.c_void_p), ("face", ctypes.c_void_p),
                ("next", ctypes.c_void_p), ("glyph_index", ctypes.c_uint),
                ("generic", _Generic), ("metrics", _Metrics),
                ("linearHoriAdvance", _FT_Fixed),
                ("linearVertAdvance", _FT_Fixed),
                ("advance", _Vector), ("format", ctypes.c_int),
                ("bitmap", _Bitmap), ("bitmap_left", ctypes.c_int),
                ("bitmap_top", ctypes.c_int), ("outline", _Outline)]


class _Size(ctypes.Structure):
    _fields_ = [("face", ctypes.c_void_p), ("generic", _Generic),
                ("x_ppem", ctypes.c_ushort), ("y_ppem", ctypes.c_ushort),
                ("x_scale", _FT_Fixed), ("y_scale", _FT_Fixed),
                ("ascender", _FT_Pos), ("descender", _FT_Pos),
                ("height", _FT_Pos), ("max_advance", _FT_Pos),
                ("internal", ctypes.c_void_p)]


class _Face(ctypes.Structure):
    _fields_ = [("num_faces", _FT_Long), ("face_index", _FT_Long),
                ("face_flags", _FT_Long), ("style_flags", _FT_Long),
                ("num_glyphs", _FT_Long),
                ("family_name", ctypes.c_char_p),
                ("style_name", ctypes.c_char_p),
                ("num_fixed_sizes", ctypes.c_int),
                ("available_sizes", ctypes.c_void_p),
                ("num_charmaps", ctypes.c_int), ("charmaps", ctypes.c_void_p),
                ("generic", _Generic), ("bbox", _BBox),
                ("units_per_EM", ctypes.c_ushort),
                ("ascender", ctypes.c_short), ("descender", ctypes.c_short),
                ("height", ctypes.c_short),
                ("max_advance_width", ctypes.c_short),
                ("max_advance_height", ctypes.c_short),
                ("underline_position", ctypes.c_short),
                ("underline_thickness", ctypes.c_short),
                ("glyph", ctypes.POINTER(_GlyphSlot)),
                ("size", ctypes.POINTER(_Size)),
                ("charmap", ctypes.c_void_p)]


_FacePointer = ctypes.POINTER(_Face)
_library = None
_freetype = None


def _load_freetype():
    """Load libfreetype once and describe the calls we make."""
    global _freetype, _library
    if _freetype is not None:
        return _freetype
    candidates = list(_LIBRARY_NAMES)
    found = ctypes.util.find_library("freetype")
    if found:
        candidates.insert(0, found)
    lib = None
    last_error = None
    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError as error:
            last_error = error
    if lib is None:
        raise FontError("libfreetype could not be loaded: %s" % last_error)

    lib.FT_Init_FreeType.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    lib.FT_New_Face.argtypes = [ctypes.c_void_p, ctypes.c_char_p, _FT_Long,
                                ctypes.POINTER(_FacePointer)]
    lib.FT_Done_Face.argtypes = [_FacePointer]
    lib.FT_Set_Pixel_Sizes.argtypes = [_FacePointer, ctypes.c_uint,
                                       ctypes.c_uint]
    lib.FT_Get_Char_Index.argtypes = [_FacePointer, ctypes.c_ulong]
    lib.FT_Get_Char_Index.restype = ctypes.c_uint
    lib.FT_Load_Glyph.argtypes = [_FacePointer, ctypes.c_uint, ctypes.c_int]
    lib.FT_Render_Glyph.argtypes = [ctypes.POINTER(_GlyphSlot), ctypes.c_int]

    handle = ctypes.c_void_p()
    if lib.FT_Init_FreeType(ctypes.byref(handle)):
        raise FontError("FT_Init_FreeType failed")
    _freetype, _library = lib, handle
    return lib


class FreeTypeBackend(object):
    """One face at one pixel size, rendered by libfreetype."""

    name = "freetype"

    #: FT_LOAD_DEFAULT; hinting on, which is what makes 12 px type legible.
    LOAD = 0
    RENDER_NORMAL = 0

    def __init__(self, path, size):
        lib = _load_freetype()
        self._lib = lib
        self._face = _FacePointer()
        if lib.FT_New_Face(_library, path.encode("utf-8"), 0,
                           ctypes.byref(self._face)):
            raise FontError("FreeType cannot read %s" % path)
        record = self._face.contents
        # A wrong struct layout - a FreeType whose FT_FaceRec does not match
        # the one above - shows up here as nonsense rather than as a crash
        # ten calls later, and the caller can still fall back to Python.
        if not 16 <= record.units_per_EM <= 16384 or record.num_glyphs <= 0:
            lib.FT_Done_Face(self._face)
            raise FontError("unexpected FreeType layout for %s" % path)
        lib.FT_Set_Pixel_Sizes(self._face, 0, int(size))
        metrics = record.size.contents
        self.family = (record.family_name or b"").decode("latin-1", "replace")
        self.ascent = metrics.ascender >> 6
        self.descent = max(0, -metrics.descender >> 6)
        self.height = metrics.height >> 6

    def close(self):
        if self._face:
            self._lib.FT_Done_Face(self._face)
            self._face = _FacePointer()

    def index(self, codepoint):
        return self._lib.FT_Get_Char_Index(self._face, codepoint)

    def advance(self, codepoint):
        index = self.index(codepoint)
        if not index:
            return None
        if self._lib.FT_Load_Glyph(self._face, index, self.LOAD):
            return None
        return self._face.contents.glyph.contents.advance.x >> 6

    def render(self, codepoint):
        index = self.index(codepoint)
        if not index:
            return None
        if self._lib.FT_Load_Glyph(self._face, index, self.LOAD):
            return None
        slot = self._face.contents.glyph
        if self._lib.FT_Render_Glyph(slot, self.RENDER_NORMAL):
            return None
        record = slot.contents
        bitmap = record.bitmap
        width, rows, pitch = bitmap.width, bitmap.rows, bitmap.pitch
        advance = record.advance.x >> 6
        if not width or not rows:
            return 0, 0, 0, 0, advance, bytearray()
        coverage = bytearray(width * rows)
        # A negative pitch means the rows are stored bottom up; FreeType only
        # does that for some formats, but copying row by row costs nothing
        # and handles both.
        for y in range(rows):
            start = (y if pitch >= 0 else rows - 1 - y) * abs(pitch)
            coverage[y * width:(y + 1) * width] = bytes(
                bitmap.buffer[start:start + width])
        return (width, rows, record.bitmap_left, record.bitmap_top, advance,
                coverage)


# ---------------------------------------------------------------------------
# a TrueType reader in plain Python
# ---------------------------------------------------------------------------

#: How finely a quadratic curve is chopped into straight segments.  Six is
#: past the point where more makes a visible difference even at 240 px, and
#: every extra step costs an edge in the rasteriser.
_CURVE_STEPS = 6


class PythonBackend(object):
    """The same face read with :mod:`struct` and filled by :mod:`.svgpath`.

    Only the tables an outline needs are touched: ``cmap`` to find the
    glyph, ``loca``/``glyf`` for its contours and ``hmtx`` for the advance.
    Hinting is ignored - there is no interpreter here - so small type comes
    out softer than FreeType draws it.
    """

    name = "python"

    def __init__(self, path, size):
        with open(path, "rb") as handle:
            self.data = handle.read()
        data = self.data
        if data[:4] not in (b"\x00\x01\x00\x00", b"true", b"ttcf"):
            # OpenType with PostScript outlines has a 'CFF ' table instead of
            # 'glyf', which this reader does not speak.
            if data[:4] == b"OTTO":
                raise FontError("%s has CFF outlines, which need FreeType"
                                % path)
            raise FontError("%s is not a TrueType font" % path)
        self.tables = {}
        count = struct.unpack_from(">H", data, 4)[0]
        for index in range(count):
            offset = 12 + index * 16
            tag = data[offset:offset + 4].decode("latin-1")
            start, length = struct.unpack_from(">II", data, offset + 8)
            self.tables[tag] = (start, length)
        for required in ("head", "maxp", "hhea", "hmtx", "loca", "glyf",
                         "cmap"):
            if required not in self.tables:
                raise FontError("%s has no %r table" % (path, required))

        head = self.tables["head"][0]
        self.units_per_em = struct.unpack_from(">H", data, head + 18)[0] or 1000
        long_loca = struct.unpack_from(">h", data, head + 50)[0]
        self.num_glyphs = struct.unpack_from(">H", data,
                                             self.tables["maxp"][0] + 4)[0]
        hhea = self.tables["hhea"][0]
        ascent, descent = struct.unpack_from(">hh", data, hhea + 4)
        self.num_hmetrics = struct.unpack_from(">H", data, hhea + 34)[0]

        self.scale = float(size) / self.units_per_em
        self.ascent = int(round(ascent * self.scale))
        self.descent = max(0, int(round(-descent * self.scale)))
        self.height = self.ascent + self.descent

        self._loca = self._read_loca(long_loca)
        self._cmap = self._read_cmap()
        self._outlines = {}
        self.family = ""

    def close(self):
        self._outlines.clear()

    # -- tables ------------------------------------------------------------
    def _read_loca(self, long_format):
        start = self.tables["loca"][0]
        count = self.num_glyphs + 1
        if long_format:
            return struct.unpack_from(">%dI" % count, self.data, start)
        short = struct.unpack_from(">%dH" % count, self.data, start)
        return tuple(value * 2 for value in short)

    def _read_cmap(self):
        """The Unicode subtable, flattened into ``{codepoint: glyph}``."""
        data = self.data
        start = self.tables["cmap"][0]
        count = struct.unpack_from(">H", data, start + 2)[0]
        chosen = None
        for index in range(count):
            platform, encoding, offset = struct.unpack_from(
                ">HHI", data, start + 4 + index * 8)
            if (platform, encoding) in ((3, 1), (0, 3), (0, 4), (0, 6)):
                chosen = start + offset
                break
        if chosen is None:
            raise FontError("no Unicode character map")
        if struct.unpack_from(">H", data, chosen)[0] != 4:
            raise FontError("unsupported character map format")

        segments = struct.unpack_from(">H", data, chosen + 6)[0] // 2
        span = segments * 2
        ends = struct.unpack_from(">%dH" % segments, data, chosen + 14)
        base = chosen + 16 + span
        starts = struct.unpack_from(">%dH" % segments, data, base)
        deltas = struct.unpack_from(">%dh" % segments, data, base + span)
        range_base = base + span * 2
        offsets = struct.unpack_from(">%dH" % segments, data, range_base)

        table = {}
        for index in range(segments):
            first, last = starts[index], min(ends[index], 0xFFFF)
            delta, offset = deltas[index], offsets[index]
            for code in range(first, last + 1):
                if offset == 0:
                    glyph = (code + delta) & 0xFFFF
                else:
                    position = (range_base + index * 2 + offset
                                + (code - first) * 2)
                    if position + 2 > len(data):
                        continue
                    glyph = struct.unpack_from(">H", data, position)[0]
                    if glyph:
                        glyph = (glyph + delta) & 0xFFFF
                if glyph:
                    table[code] = glyph
        return table

    # -- outlines ----------------------------------------------------------
    def _contours(self, glyph, depth=0):
        """Point lists in font units, curves already flattened."""
        cached = self._outlines.get(glyph)
        if cached is not None:
            return cached
        if glyph + 1 >= len(self._loca):
            return []
        begin, end = self._loca[glyph], self._loca[glyph + 1]
        if begin >= end:
            self._outlines[glyph] = []
            return []
        data = self.data
        offset = self.tables["glyf"][0] + begin
        count = struct.unpack_from(">h", data, offset)[0]
        if count < 0:
            result = self._composite(offset + 10, depth)
            self._outlines[glyph] = result
            return result

        ends = struct.unpack_from(">%dH" % count, data, offset + 10)
        position = offset + 10 + count * 2
        position += 2 + struct.unpack_from(">H", data, position)[0]
        total = ends[-1] + 1 if count else 0

        flags = []
        while len(flags) < total:
            flag = data[position]
            position += 1
            flags.append(flag)
            if flag & 8:                        # REPEAT
                flags.extend([flag] * data[position])
                position += 1
        flags = flags[:total]

        def coordinates(short_bit, same_bit, at):
            values = []
            value = 0
            for flag in flags:
                if flag & short_bit:
                    value += data[at] if flag & same_bit else -data[at]
                    at += 1
                elif not flag & same_bit:
                    value += struct.unpack_from(">h", data, at)[0]
                    at += 2
                values.append(value)
            return values, at

        xs, position = coordinates(2, 16, position)
        ys, _position = coordinates(4, 32, position)

        subpaths = []
        first = 0
        for last in ends:
            points = [(xs[i], ys[i], bool(flags[i] & 1))
                      for i in range(first, last + 1)]
            first = last + 1
            flat = _flatten(points)
            if flat:
                subpaths.append(flat)
        self._outlines[glyph] = subpaths
        return subpaths

    def _composite(self, position, depth):
        """A glyph assembled from others, e.g. an accented letter."""
        if depth > 4:                           # a cycle in a broken font
            return []
        data = self.data
        result = []
        while True:
            flags, index = struct.unpack_from(">HH", data, position)
            position += 4
            if flags & 0x0001:                  # ARG_1_AND_2_ARE_WORDS
                dx, dy = struct.unpack_from(">hh", data, position)
                position += 4
            else:
                dx, dy = struct.unpack_from(">bb", data, position)
                position += 2
            scale_x = scale_y = 1.0
            if flags & 0x0008:                  # WE_HAVE_A_SCALE
                scale_x = scale_y = _f2dot14(data, position)
                position += 2
            elif flags & 0x0040:                # X_AND_Y_SCALE
                scale_x = _f2dot14(data, position)
                scale_y = _f2dot14(data, position + 2)
                position += 4
            elif flags & 0x0080:                # TWO_BY_TWO
                scale_x = _f2dot14(data, position)
                scale_y = _f2dot14(data, position + 6)
                position += 8
            if not flags & 0x0002:
                # Point matching rather than an offset; rare enough that
                # placing the component at the origin beats not drawing it.
                dx = dy = 0
            for path in self._contours(index, depth + 1):
                result.append([(x * scale_x + dx, y * scale_y + dy)
                               for x, y in path])
            if not flags & 0x0020:              # MORE_COMPONENTS
                break
        return result

    # -- what the cache asks for -------------------------------------------
    def index(self, codepoint):
        return self._cmap.get(codepoint, 0)

    def _hmetrics(self, glyph):
        """``(advance, left side bearing)`` in font units."""
        start = self.tables["hmtx"][0]
        last = max(0, self.num_hmetrics - 1)
        if glyph <= last:
            return struct.unpack_from(">Hh", self.data, start + glyph * 4)
        # Past the last full entry only bearings follow, and every one of
        # those glyphs shares the last advance - how a monospaced face
        # stores its metrics in a few bytes.
        advance = struct.unpack_from(">H", self.data, start + last * 4)[0]
        offset = start + self.num_hmetrics * 4 + (glyph - self.num_hmetrics) * 2
        if offset + 2 > len(self.data):
            return advance, 0
        return advance, struct.unpack_from(">h", self.data, offset)[0]

    def _header_xmin(self, glyph):
        """``xMin`` out of the glyph header, 0 for an empty glyph."""
        begin, end = self._loca[glyph], self._loca[glyph + 1]
        if begin >= end:
            return 0
        return struct.unpack_from(">h", self.data,
                                  self.tables["glyf"][0] + begin + 2)[0]

    def advance(self, codepoint):
        glyph = self._cmap.get(codepoint)
        if not glyph:
            return None
        return int(round(self._hmetrics(glyph)[0] * self.scale))

    def render(self, codepoint):
        glyph = self._cmap.get(codepoint)
        if not glyph:
            return None
        units_advance, bearing = self._hmetrics(glyph)
        advance = int(round(units_advance * self.scale))
        paths = self._contours(glyph)
        if not paths:
            return 0, 0, 0, 0, advance, bytearray()
        # A face is positioned by its left side bearing, which is normally
        # the same as the outline's xMin but does not have to be; where the
        # two disagree the outline moves, and a renderer that ignored this
        # would put the glyph somewhere FreeType does not.
        shift = bearing - self._header_xmin(glyph)
        if shift:
            paths = [[(x + shift, y) for x, y in path] for path in paths]
        box = svgpath.bounds(paths)
        if box is None:
            return 0, 0, 0, 0, advance, bytearray()
        scale = self.scale
        # floor/ceil already take in the partial pixels at each edge, so the
        # box is exactly as wide as the outline covers - no slack on top, or
        # every glyph would sit a pixel off where FreeType puts it.
        left = _floor(box[0] * scale)
        top = _ceil(box[3] * scale)
        width = _ceil(box[2] * scale) - left
        height = top - _floor(box[1] * scale)
        if width <= 0 or height <= 0:
            return 0, 0, 0, 0, advance, bytearray()
        # Font units count upwards from the baseline, pixels downwards, so
        # the y scale is negated and the origin moved to the glyph's top.
        placed = svgpath.transform(paths, scale, -scale, -left, top)
        return (width, height, left, top, advance,
                svgpath.mask(placed, width, height))


def _f2dot14(data, position):
    return struct.unpack_from(">h", data, position)[0] / 16384.0


def _floor(value):
    return int(value) if value >= 0 or value == int(value) else int(value) - 1


def _ceil(value):
    return int(value) if value <= 0 or value == int(value) else int(value) + 1


def _flatten(points, steps=_CURVE_STEPS):
    """One TrueType contour as a straight-line point list.

    A contour alternates on- and off-curve points; two off-curve points in a
    row imply an on-curve point half way between them, which is where the
    format saves its space.
    """
    if not points:
        return []
    start = None
    for position, point in enumerate(points):
        if point[2]:
            start = position
            break
    if start is None:
        # Every point is off-curve: start from the implied midpoint between
        # the last and the first, so the contour still closes.
        first, last = points[0], points[-1]
        points = [((first[0] + last[0]) / 2.0,
                   (first[1] + last[1]) / 2.0, True)] + points
        start = 0
    points = points[start:] + points[:start]

    out = [(float(points[0][0]), float(points[0][1]))]
    count = len(points)
    index = 1
    while index <= count:
        current = points[index % count]
        if current[2]:
            out.append((float(current[0]), float(current[1])))
            index += 1
            continue
        following = points[(index + 1) % count]
        if following[2]:
            end = (float(following[0]), float(following[1]))
            index += 2
        else:
            end = ((current[0] + following[0]) / 2.0,
                   (current[1] + following[1]) / 2.0)
            index += 1
        x0, y0 = out[-1]
        cx, cy = float(current[0]), float(current[1])
        x1, y1 = end
        for step in range(1, steps + 1):
            t = step / float(steps)
            u = 1.0 - t
            out.append((u * u * x0 + 2.0 * u * t * cx + t * t * x1,
                        u * u * y0 + 2.0 * u * t * cy + t * t * y1))
    return out


# ---------------------------------------------------------------------------
# picking one
# ---------------------------------------------------------------------------

#: ``None`` until the first face is opened, then ``"freetype"`` or
#: ``"python"``.  Reported in the log and by the status dialog.
backend = None

_freetype_failed = None


def open_face(path, size):
    """Open ``path`` at ``size`` pixels with the best backend available."""
    global backend, _freetype_failed
    size = max(4, int(size))
    if _freetype_failed is None:
        try:
            face = FreeTypeBackend(path, size)
            _freetype_failed = False
            backend = "freetype"
            return face
        except FontError as error:
            # Only a missing or unusable *library* disables FreeType for
            # good; a face it refuses is retried in Python and the next face
            # gets FreeType again.
            if "libfreetype" in str(error) or "FT_Init" in str(error):
                _freetype_failed = True
                log("FreeType is not available (%s), falling back to the "
                    "built-in rasteriser" % error)
            else:
                debug("FreeType refused %s: %s" % (path, error))
    elif _freetype_failed is False:
        try:
            return FreeTypeBackend(path, size)
        except FontError as error:
            debug("FreeType refused %s: %s" % (path, error))
    face = PythonBackend(path, size)
    if backend is None:
        backend = "python"
    return face


def backend_name():
    """Which rasteriser is in use, for the log and the status dialog."""
    if backend is None:
        return "not started yet"
    return "FreeType" if backend == "freetype" else "the built-in rasteriser"
