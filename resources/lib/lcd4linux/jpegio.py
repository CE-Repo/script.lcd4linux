"""A compact baseline JPEG decoder in pure Python.

Kodi caches artwork as JPEG, and a stock CoreELEC image has neither Pillow
nor an ``ffmpeg`` binary, so cover art would otherwise be impossible.  The
decoder therefore supports a *scaled* inverse DCT: blocks can be
reconstructed at 1x1, 2x2, 4x4 or 8x8 pixels, which is how a 500x500 cover
is turned into the ~200 px thumbnail a layout actually needs in a fraction
of the time a full decode would cost.

Baseline (SOF0) and extended sequential (SOF1) Huffman JPEGs are supported.
Progressive files raise :class:`UnsupportedJPEG`; callers fall back to a
placeholder.
"""

import math
import struct

ZIGZAG = (
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
)


class UnsupportedJPEG(Exception):
    pass


# ---------------------------------------------------------------------------
# scaled IDCT basis
# ---------------------------------------------------------------------------

_BASIS_CACHE = {}


def _basis(n):
    """Orthonormal n point IDCT matrix, pre-scaled for 8 -> n downscaling."""
    table = _BASIS_CACHE.get(n)
    if table is None:
        table = []
        for x in range(n):
            row = []
            for u in range(n):
                c = math.sqrt(0.5) if u == 0 else 1.0
                row.append(math.sqrt(2.0 / n) * c
                           * math.cos((2 * x + 1) * u * math.pi / (2.0 * n)))
            table.append(row)
        _BASIS_CACHE[n] = table
    return table


#: How many bits the lookup below is indexed by.  Eight covers the great
#: majority of the codes in a photograph and keeps the table at 256 entries,
#: which is built once per table and per picture.
_PEEK = 8


class _Huffman(object):
    """Canonical Huffman table as described in ITU T.81 annex F.

    Alongside the three arrays the specification describes, a flat lookup
    from the next eight bits to ``(symbol, length)``.  Walking the code bit
    by bit was costing a Python call per bit - some three quarters of a
    million of them for one piece of fanart - and nearly every code is
    short enough to come out of the table in one step.
    """

    def __init__(self, counts, symbols):
        self.symbols = symbols
        self.mincode = [0] * 17
        self.maxcode = [-1] * 17
        self.valptr = [0] * 17
        self.fast = [None] * (1 << _PEEK)
        code = 0
        k = 0
        for length in range(1, 17):
            self.valptr[length] = k
            self.mincode[length] = code
            code += counts[length - 1]
            k += counts[length - 1]
            self.maxcode[length] = code - 1 if counts[length - 1] else -1
            if length <= _PEEK:
                spread = 1 << (_PEEK - length)
                for offset in range(counts[length - 1]):
                    entry = (symbols[self.valptr[length] + offset], length)
                    start = (self.mincode[length] + offset) << (_PEEK - length)
                    for slot in range(start, start + spread):
                        self.fast[slot] = entry
            code <<= 1


class _Component(object):
    __slots__ = ("cid", "h", "v", "tq", "td", "ta", "pred",
                 "blocks_w", "blocks_h", "plane", "plane_w", "plane_h")


class _BitReader(object):
    def __init__(self, data, pos):
        self.data = data
        self.pos = pos
        self.buf = 0
        self.count = 0
        self.marker = 0

    def _next_byte(self):
        data = self.data
        if self.pos >= len(data):
            return 0
        byte = data[self.pos]
        self.pos += 1
        if byte == 0xFF:
            nxt = data[self.pos] if self.pos < len(data) else 0xD9
            if nxt == 0x00:
                self.pos += 1
                return 0xFF
            # A real marker: stop consuming and feed zero bits from here on.
            self.marker = nxt
            self.pos -= 1
            return 0
        return byte

    def _fill(self, need):
        """Make sure at least ``need`` bits are in the buffer.

        Everything above ``count`` is dropped on the way, so the buffer
        stays a handful of bits wide however long the scan runs.  Past a
        marker ``_next_byte`` keeps handing out zeroes without moving on,
        which is exactly the padding the specification asks for.
        """
        while self.count < need:
            self.buf = ((self.buf & ((1 << self.count) - 1)) << 8) \
                | self._next_byte()
            self.count += 8

    def bit(self):
        if self.count == 0:
            self.buf = self._next_byte()
            self.count = 8
        self.count -= 1
        return (self.buf >> self.count) & 1

    def bits(self, length):
        if length <= 0:
            return 0
        self._fill(length)
        self.count -= length
        return (self.buf >> self.count) & ((1 << length) - 1)

    def decode(self, table):
        self._fill(_PEEK)
        entry = table.fast[(self.buf >> (self.count - _PEEK)) & ((1 << _PEEK) - 1)]
        if entry is not None:
            self.count -= entry[1]
            return entry[0]
        # A code longer than the table covers: rare, and worth nothing more
        # than the plain walk the specification describes.
        code = 0
        for length in range(1, 17):
            code = (code << 1) | self.bit()
            maxcode = table.maxcode[length]
            if maxcode >= 0 and code <= maxcode:
                return table.symbols[table.valptr[length] + code - table.mincode[length]]
        return 0

    def receive_extend(self, length):
        if length == 0:
            return 0
        value = self.bits(length)
        if value < (1 << (length - 1)):
            value -= (1 << length) - 1
        return value

    def restart(self):
        """Skip to the next RST marker and reset the bit buffer."""
        self.count = 0
        self.marker = 0
        data = self.data
        while self.pos < len(data) - 1:
            if data[self.pos] == 0xFF and 0xD0 <= data[self.pos + 1] <= 0xD7:
                self.pos += 2
                return True
            self.pos += 1
        return False


def _decode_block(reader, comp, dc_table, ac_table, quant, n, out, out_stride,
                  out_x, out_y):
    """Decode one 8x8 block and write its n x n reconstruction."""
    coeffs = [0.0] * (n * n)
    symbol = reader.decode(dc_table)
    diff = reader.receive_extend(symbol)
    comp.pred += diff
    coeffs[0] = comp.pred * quant[0]

    nonzero_ac = False
    k = 1
    while k < 64:
        rs = reader.decode(ac_table)
        run = rs >> 4
        size = rs & 15
        if size == 0:
            if run != 15:
                break
            k += 16
            continue
        k += run
        if k > 63:
            break
        value = reader.receive_extend(size) * quant[k]
        pos = ZIGZAG[k]
        row = pos >> 3
        col = pos & 7
        if row < n and col < n:
            coeffs[row * n + col] = value
            nonzero_ac = True
        k += 1

    scale = n / 8.0
    if not nonzero_ac:
        # Extremely common: flat block, skip the transform entirely.
        value = int(coeffs[0] * scale / n + 128.5)
        if value < 0:
            value = 0
        elif value > 255:
            value = 255
        for row in range(n):
            base = (out_y + row) * out_stride + out_x
            for col in range(n):
                out[base + col] = value
        return

    basis = _basis(n)
    # rows
    tmp = [0.0] * (n * n)
    for row in range(n):
        src = row * n
        for x in range(n):
            brow = basis[x]
            acc = 0.0
            for u in range(n):
                value = coeffs[src + u]
                if value:
                    acc += brow[u] * value
            tmp[src + x] = acc
    for col in range(n):
        for y in range(n):
            brow = basis[y]
            acc = 0.0
            for v in range(n):
                value = tmp[v * n + col]
                if value:
                    acc += brow[v] * value
            value = int(acc * scale + 128.5)
            if value < 0:
                value = 0
            elif value > 255:
                value = 255
            out[(out_y + y) * out_stride + out_x + col] = value


def decode(data, max_size=None):
    """Decode ``data`` to ``(width, height, rgba bytearray)``.

    ``max_size`` is the longest edge the caller needs; the decoder picks the
    cheapest IDCT scale that still delivers at least that many pixels.
    """
    if data[:2] != b"\xff\xd8":
        raise UnsupportedJPEG("not a JPEG file")

    pos = 2
    quant = {}
    dc_tables = {}
    ac_tables = {}
    components = []
    width = height = 0
    restart_interval = 0
    adobe_transform = None
    progressive = False

    while pos < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        pos += 2
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xD9:
            break
        length = struct.unpack_from(">H", data, pos)[0]
        segment = data[pos + 2:pos + length]
        if marker == 0xDB:
            index = 0
            while index < len(segment):
                pq = segment[index] >> 4
                tq = segment[index] & 15
                index += 1
                table = [0] * 64
                for i in range(64):
                    if pq:
                        table[i] = struct.unpack_from(">H", segment, index)[0]
                        index += 2
                    else:
                        table[i] = segment[index]
                        index += 1
                quant[tq] = table
        elif marker in (0xC0, 0xC1, 0xC2):
            if marker == 0xC2:
                progressive = True
            precision = segment[0]
            height, width = struct.unpack_from(">HH", segment, 1)
            count = segment[5]
            if precision != 8:
                raise UnsupportedJPEG("only 8 bit JPEG is supported")
            components = []
            for i in range(count):
                comp = _Component()
                comp.cid = segment[6 + i * 3]
                comp.h = segment[7 + i * 3] >> 4
                comp.v = segment[7 + i * 3] & 15
                comp.tq = segment[8 + i * 3]
                comp.pred = 0
                components.append(comp)
        elif marker in (0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            raise UnsupportedJPEG("unsupported JPEG coding process")
        elif marker == 0xC4:
            index = 0
            while index < len(segment):
                tc = segment[index] >> 4
                th = segment[index] & 15
                index += 1
                counts = list(segment[index:index + 16])
                index += 16
                total = sum(counts)
                symbols = list(segment[index:index + total])
                index += total
                table = _Huffman(counts, symbols)
                if tc == 0:
                    dc_tables[th] = table
                else:
                    ac_tables[th] = table
        elif marker == 0xDD:
            restart_interval = struct.unpack_from(">H", segment, 0)[0]
        elif marker == 0xEE and segment[:5] == b"Adobe":
            adobe_transform = segment[11] if len(segment) > 11 else None
        elif marker == 0xDA:
            if progressive:
                raise UnsupportedJPEG("progressive JPEG is not supported")
            count = segment[0]
            scan = []
            for i in range(count):
                cid = segment[1 + i * 2]
                tables = segment[2 + i * 2]
                for comp in components:
                    if comp.cid == cid:
                        comp.td = tables >> 4
                        comp.ta = tables & 15
                        scan.append(comp)
                        break
            pos += length
            return _decode_scan(data, pos, width, height, components, scan,
                                quant, dc_tables, ac_tables, restart_interval,
                                adobe_transform, max_size)
        pos += length
    raise UnsupportedJPEG("no image data found")


def _pick_scale(width, height, max_size):
    """The cheapest eighth that still delivers ``max_size`` pixels.

    Every step from 1/8 to 8/8 is available, not just the powers of two:
    the basis is built for whatever ``n`` is asked for.  That matters at
    the top end, where the jump from 4/8 to 8/8 used to quadruple the work
    for a picture only ten per cent wider than 4/8 already gave - a
    1024x600 panel showing 1080p fanart landed on exactly that step.
    """
    if not max_size:
        return 8
    longest = max(width, height)
    for n in range(1, 9):
        if longest * n / 8.0 >= max_size:
            return n
    return 8


def _decode_scan(data, pos, width, height, components, scan, quant,
                 dc_tables, ac_tables, restart_interval, adobe_transform,
                 max_size):
    if not components or not width or not height:
        raise UnsupportedJPEG("malformed JPEG header")

    n = _pick_scale(width, height, max_size)
    hmax = max(c.h for c in components)
    vmax = max(c.v for c in components)
    mcus_x = (width + 8 * hmax - 1) // (8 * hmax)
    mcus_y = (height + 8 * vmax - 1) // (8 * vmax)

    for comp in components:
        comp.blocks_w = mcus_x * comp.h
        comp.blocks_h = mcus_y * comp.v
        comp.plane_w = comp.blocks_w * n
        comp.plane_h = comp.blocks_h * n
        comp.plane = bytearray(comp.plane_w * comp.plane_h)
        comp.pred = 0

    reader = _BitReader(data, pos)
    mcu = 0
    total_mcus = mcus_x * mcus_y
    while mcu < total_mcus:
        if restart_interval and mcu and mcu % restart_interval == 0:
            if not reader.restart():
                break
            for comp in components:
                comp.pred = 0
        mcu_x = mcu % mcus_x
        mcu_y = mcu // mcus_x
        for comp in scan:
            qt = quant.get(comp.tq)
            dct = dc_tables.get(comp.td)
            act = ac_tables.get(comp.ta)
            if qt is None or dct is None or act is None:
                raise UnsupportedJPEG("missing JPEG table")
            for by in range(comp.v):
                for bx in range(comp.h):
                    _decode_block(reader, comp, dct, act, qt, n,
                                  comp.plane, comp.plane_w,
                                  (mcu_x * comp.h + bx) * n,
                                  (mcu_y * comp.v + by) * n)
        mcu += 1
        if reader.marker and reader.marker != 0 and not (0xD0 <= reader.marker <= 0xD7):
            break

    out_w = max(1, int(math.ceil(width * n / 8.0)))
    out_h = max(1, int(math.ceil(height * n / 8.0)))
    rgba = bytearray(out_w * out_h * 4)

    if len(components) == 1:
        plane = components[0].plane
        stride = components[0].plane_w
        index = 0
        for y in range(out_h):
            base = y * stride
            for x in range(out_w):
                value = plane[base + x]
                rgba[index] = value
                rgba[index + 1] = value
                rgba[index + 2] = value
                rgba[index + 3] = 255
                index += 4
        return out_w, out_h, rgba

    ycc = components[:3]
    y_comp, cb_comp, cr_comp = ycc[0], ycc[1], ycc[2]
    y_plane, cb_plane, cr_plane = y_comp.plane, cb_comp.plane, cr_comp.plane
    # Pre-compute the horizontal sample mapping once per component.
    cb_map = [min(cb_comp.plane_w - 1, x * cb_comp.h // hmax) for x in range(out_w)]
    cr_map = [min(cr_comp.plane_w - 1, x * cr_comp.h // hmax) for x in range(out_w)]
    y_map = [min(y_comp.plane_w - 1, x * y_comp.h // hmax) for x in range(out_w)]

    index = 0
    for y in range(out_h):
        y_row = min(y_comp.plane_h - 1, y * y_comp.v // vmax) * y_comp.plane_w
        cb_row = min(cb_comp.plane_h - 1, y * cb_comp.v // vmax) * cb_comp.plane_w
        cr_row = min(cr_comp.plane_h - 1, y * cr_comp.v // vmax) * cr_comp.plane_w
        for x in range(out_w):
            luma = y_plane[y_row + y_map[x]]
            cb = cb_plane[cb_row + cb_map[x]] - 128
            cr = cr_plane[cr_row + cr_map[x]] - 128
            r = luma + ((91881 * cr) >> 16)
            g = luma - ((22554 * cb + 46802 * cr) >> 16)
            b = luma + ((116130 * cb) >> 16)
            rgba[index] = 0 if r < 0 else (255 if r > 255 else r)
            rgba[index + 1] = 0 if g < 0 else (255 if g > 255 else g)
            rgba[index + 2] = 0 if b < 0 else (255 if b > 255 else b)
            rgba[index + 3] = 255
            index += 4
    return out_w, out_h, rgba
