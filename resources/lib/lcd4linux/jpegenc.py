"""A baseline JPEG encoder in pure Python.

The Samsung SPF frames only accept complete JPEG images, so unlike the AX206
there is no way to send just the pixels that changed.  Encoding a whole
800x480 frame in the Kodi interpreter would be far too slow, so this encoder
uses three tricks:

* a restart marker after every MCU row, which makes each row independently
  coded and byte aligned - unchanged rows are then copied verbatim from the
  previous frame's bitstream;
* flat blocks (all 64 samples equal, very common in a UI) skip the DCT
  entirely and are emitted as a DC value;
* blocks that repeat are looked up in a small content cache.

Input is the RGB565 framebuffer of a :class:`~.canvas.Canvas`, so no
intermediate RGB conversion pass is needed.
"""

from array import array

# ---------------------------------------------------------------------------
# tables (ITU T.81 annex K)
# ---------------------------------------------------------------------------

ZIGZAG = (
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
)

QUANT_LUMA = (
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
)

QUANT_CHROMA = (
    17, 18, 24, 47, 99, 99, 99, 99,
    18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99,
    47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
)

DC_LUMA_BITS = (0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0)
DC_LUMA_VALS = tuple(range(12))
DC_CHROMA_BITS = (0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0)
DC_CHROMA_VALS = tuple(range(12))

AC_LUMA_BITS = (0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D)
AC_LUMA_VALS = (
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12,
    0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
    0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
    0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0,
    0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0A, 0x16,
    0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
    0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39,
    0x3A, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
    0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
    0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
    0x6A, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79,
    0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
    0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98,
    0x99, 0x9A, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7,
    0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
    0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5,
    0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xD2, 0xD3, 0xD4,
    0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
    0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA,
    0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8,
    0xF9, 0xFA,
)

AC_CHROMA_BITS = (0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77)
AC_CHROMA_VALS = (
    0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21,
    0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71,
    0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91,
    0xA1, 0xB1, 0xC1, 0x09, 0x23, 0x33, 0x52, 0xF0,
    0x15, 0x62, 0x72, 0xD1, 0x0A, 0x16, 0x24, 0x34,
    0xE1, 0x25, 0xF1, 0x17, 0x18, 0x19, 0x1A, 0x26,
    0x27, 0x28, 0x29, 0x2A, 0x35, 0x36, 0x37, 0x38,
    0x39, 0x3A, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
    0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58,
    0x59, 0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
    0x69, 0x6A, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78,
    0x79, 0x7A, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
    0x88, 0x89, 0x8A, 0x92, 0x93, 0x94, 0x95, 0x96,
    0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3, 0xA4, 0xA5,
    0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4,
    0xB5, 0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3,
    0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xD2,
    0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA,
    0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9,
    0xEA, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8,
    0xF9, 0xFA,
)


def _build_codes(bits, values):
    """Canonical Huffman table -> ``{symbol: (code, length)}``."""
    codes = {}
    code = 0
    index = 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            codes[values[index]] = (code, length)
            index += 1
            code += 1
        code <<= 1
    return codes


def _scale_quant(table, quality):
    quality = max(1, min(100, int(quality)))
    if quality < 50:
        scale = 5000 // quality
    else:
        scale = 200 - quality * 2
    scaled = []
    for value in table:
        step = (value * scale + 50) // 100
        scaled.append(max(1, min(255, step)))
    return scaled


# ---------------------------------------------------------------------------
# colour conversion, filled on demand
# ---------------------------------------------------------------------------

class _Component(dict):
    """RGB565 -> one YCbCr component, computed the first time it is seen.

    ``gain`` scales the RGB triple before the conversion, which is how the
    Samsung frames are dimmed: they have no backlight control, so the
    picture itself has to be darkened.  Folding it into this table makes the
    dimming free - the encoder looks a sample up either way.
    """

    __slots__ = ("index", "gain")

    def __init__(self, index, gain=256):
        dict.__init__(self)
        self.index = index
        self.gain = int(gain)

    def __missing__(self, key):
        r = ((key >> 11) & 0x1F) << 3
        g = ((key >> 5) & 0x3F) << 2
        b = (key & 0x1F) << 3
        r |= r >> 5
        g |= g >> 6
        b |= b >> 5
        gain = self.gain
        if gain != 256:
            r = (r * gain) >> 8
            g = (g * gain) >> 8
            b = (b * gain) >> 8
        if self.index == 0:
            value = (19595 * r + 38470 * g + 7471 * b) >> 16
        elif self.index == 1:
            value = 128 + ((-11056 * r - 21712 * g + 32768 * b) >> 16)
        else:
            value = 128 + ((32768 * r - 27440 * g - 5328 * b) >> 16)
        if value < 0:
            value = 0
        elif value > 255:
            value = 255
        # Samples are level shifted here so the DCT works on -128..127.
        value -= 128
        self[key] = value
        return value


# ---------------------------------------------------------------------------
# forward DCT (AAN, as in jfdctflt.c)
# ---------------------------------------------------------------------------

_A1 = 0.707106781186547524
_A2 = 0.541196100146196984
_A3 = _A1
_A4 = 1.306562964876376527
_A5 = 0.382683432365089772


def _forward_dct(block):
    """In place float AAN DCT of a 64 element list."""
    for offset in range(0, 64, 8):
        s0 = block[offset]
        s1 = block[offset + 1]
        s2 = block[offset + 2]
        s3 = block[offset + 3]
        s4 = block[offset + 4]
        s5 = block[offset + 5]
        s6 = block[offset + 6]
        s7 = block[offset + 7]

        t0 = s0 + s7
        t7 = s0 - s7
        t1 = s1 + s6
        t6 = s1 - s6
        t2 = s2 + s5
        t5 = s2 - s5
        t3 = s3 + s4
        t4 = s3 - s4

        t10 = t0 + t3
        t13 = t0 - t3
        t11 = t1 + t2
        t12 = t1 - t2

        block[offset] = t10 + t11
        block[offset + 4] = t10 - t11
        z1 = (t12 + t13) * _A1
        block[offset + 2] = t13 + z1
        block[offset + 6] = t13 - z1

        t10 = t4 + t5
        t11 = t5 + t6
        t12 = t6 + t7
        z5 = (t10 - t12) * _A5
        z2 = t10 * _A2 + z5
        z4 = t12 * _A4 + z5
        z3 = t11 * _A3
        z11 = t7 + z3
        z13 = t7 - z3
        block[offset + 5] = z13 + z2
        block[offset + 3] = z13 - z2
        block[offset + 1] = z11 + z4
        block[offset + 7] = z11 - z4

    for offset in range(8):
        s0 = block[offset]
        s1 = block[offset + 8]
        s2 = block[offset + 16]
        s3 = block[offset + 24]
        s4 = block[offset + 32]
        s5 = block[offset + 40]
        s6 = block[offset + 48]
        s7 = block[offset + 56]

        t0 = s0 + s7
        t7 = s0 - s7
        t1 = s1 + s6
        t6 = s1 - s6
        t2 = s2 + s5
        t5 = s2 - s5
        t3 = s3 + s4
        t4 = s3 - s4

        t10 = t0 + t3
        t13 = t0 - t3
        t11 = t1 + t2
        t12 = t1 - t2

        block[offset] = t10 + t11
        block[offset + 32] = t10 - t11
        z1 = (t12 + t13) * _A1
        block[offset + 16] = t13 + z1
        block[offset + 48] = t13 - z1

        t10 = t4 + t5
        t11 = t5 + t6
        t12 = t6 + t7
        z5 = (t10 - t12) * _A5
        z2 = t10 * _A2 + z5
        z4 = t12 * _A4 + z5
        z3 = t11 * _A3
        z11 = t7 + z3
        z13 = t7 - z3
        block[offset + 40] = z13 + z2
        block[offset + 24] = z13 - z2
        block[offset + 8] = z11 + z4
        block[offset + 56] = z11 - z4


def _aan_scale():
    """Per coefficient scale factors that undo the AAN output scaling.

    Together with the extra factor of eight applied where the quantisation
    factors are built, this matches libjpeg's float quantisation:
    ``1 / (quantval * aan[row] * aan[col] * 8)``.
    """
    scale = [1.0] * 64
    values = [1.0, 1.387039845, 1.306562965, 1.175875602,
              1.0, 0.785694958, 0.541196100, 0.275899379]
    for row in range(8):
        for col in range(8):
            scale[row * 8 + col] = values[row] * values[col]
    return scale


AAN_SCALE = _aan_scale()


# ---------------------------------------------------------------------------
# bit writer
# ---------------------------------------------------------------------------

class _BitWriter(object):
    __slots__ = ("out", "buffer", "count")

    def __init__(self):
        self.out = bytearray()
        self.buffer = 0
        self.count = 0

    def write(self, code, length):
        self.buffer = (self.buffer << length) | code
        self.count += length
        while self.count >= 8:
            self.count -= 8
            byte = (self.buffer >> self.count) & 0xFF
            self.out.append(byte)
            if byte == 0xFF:
                self.out.append(0x00)
        self.buffer &= (1 << self.count) - 1

    def flush(self):
        """Pad to a byte boundary with one bits, as the standard requires."""
        if self.count:
            self.write((1 << (8 - self.count)) - 1, 8 - self.count)
        self.buffer = 0
        self.count = 0
        return bytes(self.out)


def _magnitude(value):
    """Number of bits needed to code ``value`` plus its coded form."""
    if value < 0:
        size = value.bit_length() if value != -1 else 1
        magnitude = -value
        size = magnitude.bit_length()
        return size, (value + (1 << size) - 1)
    size = value.bit_length()
    return size, value


class JpegEncoder(object):
    """Encodes RGB565 frames as baseline JPEG."""

    def __init__(self, width, height, quality=85, subsample=True,
                 block_cache_size=8192):
        self.width = int(width)
        self.height = int(height)
        self.quality = int(quality)
        self.subsample = bool(subsample)
        self.block_cache_size = block_cache_size

        self.quant = [_scale_quant(QUANT_LUMA, quality),
                      _scale_quant(QUANT_CHROMA, quality)]
        # Quantisation tables are stored in zig-zag order in the file but the
        # coefficients come out of the DCT in natural order.
        self.natural_quant = []
        for table in self.quant:
            natural = [0] * 64
            for zig in range(64):
                natural[ZIGZAG[zig]] = table[zig]
            self.natural_quant.append(natural)
        self.factors = []
        for natural in self.natural_quant:
            self.factors.append([1.0 / (natural[index] * AAN_SCALE[index] * 8.0)
                                 for index in range(64)])

        self.dc_codes = [_build_codes(DC_LUMA_BITS, DC_LUMA_VALS),
                         _build_codes(DC_CHROMA_BITS, DC_CHROMA_VALS)]
        self.ac_codes = [_build_codes(AC_LUMA_BITS, AC_LUMA_VALS),
                         _build_codes(AC_CHROMA_BITS, AC_CHROMA_VALS)]

        self.gain = 256
        self.components = (_Component(0), _Component(1), _Component(2))

        self.mcu_width = 16 if self.subsample else 8
        self.mcu_height = 16 if self.subsample else 8
        self.mcus_x = (self.width + self.mcu_width - 1) // self.mcu_width
        self.mcus_y = (self.height + self.mcu_height - 1) // self.mcu_height

        self._header = self._build_header()
        self._row_cache = {}
        self._previous = None
        self._block_cache = {}
        self.stats = {"rows": 0, "rows_reused": 0, "blocks": 0,
                      "blocks_flat": 0, "blocks_cached": 0}

    # -- file structure ---------------------------------------------------
    def _build_header(self):
        out = bytearray()
        out += b"\xff\xd8"                                   # SOI
        out += b"\xff\xe0" + bytes((0, 16)) + b"JFIF\x00" \
            + bytes((1, 1, 0, 0, 1, 0, 1, 0, 0))             # APP0

        for index, table in enumerate(self.quant):            # DQT
            out += b"\xff\xdb" + bytes((0, 67, index))
            out += bytes(table)

        out += b"\xff\xc0" + bytes((0, 17, 8,                  # SOF0
                                    (self.height >> 8) & 0xFF, self.height & 0xFF,
                                    (self.width >> 8) & 0xFF, self.width & 0xFF,
                                    3))
        if self.subsample:
            out += bytes((1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1))
        else:
            out += bytes((1, 0x11, 0, 2, 0x11, 1, 3, 0x11, 1))

        for class_index, (bits, values) in enumerate(       # DHT
                ((DC_LUMA_BITS, DC_LUMA_VALS), (AC_LUMA_BITS, AC_LUMA_VALS),
                 (DC_CHROMA_BITS, DC_CHROMA_VALS), (AC_CHROMA_BITS, AC_CHROMA_VALS))):
            identifier = (0x00, 0x10, 0x01, 0x11)[class_index]
            length = 19 + len(values)
            out += b"\xff\xc4" + bytes(((length >> 8) & 0xFF, length & 0xFF,
                                        identifier))
            out += bytes(bits) + bytes(values)

        interval = self.mcus_x                                # DRI: one MCU row
        out += b"\xff\xdd" + bytes((0, 4, (interval >> 8) & 0xFF, interval & 0xFF))

        out += b"\xff\xda" + bytes((0, 12, 3, 1, 0x00, 2, 0x11, 3, 0x11,
                                    0, 63, 0))                # SOS
        return bytes(out)

    # -- block coding -----------------------------------------------------
    def _encode_block(self, writer, samples, table_index, predictor):
        """Quantise, entropy code and return the new DC predictor."""
        self.stats["blocks"] += 1
        first = samples[0]
        flat = True
        for value in samples:
            if value != first:
                flat = False
                break

        if flat:
            self.stats["blocks_flat"] += 1
            # A constant block has only a DC coefficient.
            dc = int(round(first * 8.0 / self.natural_quant[table_index][0]))
            coefficients = None
        else:
            key = (table_index, bytes((value + 128) & 0xFF for value in samples))
            cached = self._block_cache.get(key)
            if cached is not None:
                self.stats["blocks_cached"] += 1
                dc, coefficients = cached
            else:
                block = [float(value) for value in samples]
                _forward_dct(block)
                factors = self.factors[table_index]
                quantised = [0] * 64
                for index in range(64):
                    value = block[index] * factors[index]
                    quantised[index] = int(value + 0.5) if value >= 0 else -int(0.5 - value)
                dc = quantised[0]
                coefficients = []
                run = 0
                for zig in range(1, 64):
                    value = quantised[ZIGZAG[zig]]
                    if value == 0:
                        run += 1
                        continue
                    while run > 15:
                        coefficients.append((0xF0, 0, 0))
                        run -= 16
                    size, coded = _magnitude(value)
                    coefficients.append(((run << 4) | size, size, coded))
                    run = 0
                if run:
                    coefficients.append((0x00, 0, 0))
                if len(self._block_cache) < self.block_cache_size:
                    self._block_cache[key] = (dc, coefficients)

        dc_codes = self.dc_codes[table_index]
        diff = dc - predictor
        if diff == 0:
            writer.write(*dc_codes[0])
        else:
            size, coded = _magnitude(diff)
            code, length = dc_codes[size]
            writer.write(code, length)
            writer.write(coded, size)

        ac_codes = self.ac_codes[table_index]
        if coefficients is None:
            writer.write(*ac_codes[0x00])          # EOB
        else:
            for symbol, size, coded in coefficients:
                code, length = ac_codes[symbol]
                writer.write(code, length)
                if size:
                    writer.write(coded, size)
        return dc

    # -- frame ------------------------------------------------------------
    def encode(self, buffer, force=False):
        """Encode an RGB565 ``array('H')`` frame into JPEG bytes."""
        width = self.width
        height = self.height
        previous = None if force else self._previous
        if force:
            self._row_cache = {}

        luma, blue, red = self.components
        segments = [self._header]
        mcu_height = self.mcu_height
        mcu_width = self.mcu_width
        self.stats["rows"] = self.mcus_y
        self.stats["rows_reused"] = 0

        for mcu_y in range(self.mcus_y):
            top = mcu_y * mcu_height
            bottom = min(height, top + mcu_height)
            if previous is not None:
                start = top * width
                end = bottom * width
                if buffer[start:end] == previous[start:end]:
                    cached = self._row_cache.get(mcu_y)
                    if cached is not None:
                        self.stats["rows_reused"] += 1
                        segments.append(cached)
                        continue

            writer = _BitWriter()
            predictors = [0, 0, 0]
            for mcu_x in range(self.mcus_x):
                left = mcu_x * mcu_width
                if self.subsample:
                    for offset_y, offset_x in ((0, 0), (0, 8), (8, 0), (8, 8)):
                        samples = self._luma_block(buffer, left + offset_x,
                                                   top + offset_y, luma)
                        predictors[0] = self._encode_block(writer, samples, 0,
                                                           predictors[0])
                    samples = self._chroma_block(buffer, left, top, blue)
                    predictors[1] = self._encode_block(writer, samples, 1,
                                                       predictors[1])
                    samples = self._chroma_block(buffer, left, top, red)
                    predictors[2] = self._encode_block(writer, samples, 1,
                                                       predictors[2])
                else:
                    samples = self._luma_block(buffer, left, top, luma)
                    predictors[0] = self._encode_block(writer, samples, 0,
                                                       predictors[0])
                    samples = self._luma_block(buffer, left, top, blue)
                    predictors[1] = self._encode_block(writer, samples, 1,
                                                       predictors[1])
                    samples = self._luma_block(buffer, left, top, red)
                    predictors[2] = self._encode_block(writer, samples, 1,
                                                       predictors[2])

            data = writer.flush()
            if mcu_y != self.mcus_y - 1:
                data += bytes((0xFF, 0xD0 + (mcu_y & 7)))
            self._row_cache[mcu_y] = data
            segments.append(data)

        segments.append(b"\xff\xd9")
        self._previous = array("H", buffer)
        return b"".join(segments)

    # -- sample extraction ------------------------------------------------
    def _luma_block(self, buffer, x, y, component):
        width = self.width
        height = self.height
        samples = []
        append = samples.append
        for row in range(8):
            source_y = y + row
            if source_y >= height:
                source_y = height - 1
            base = source_y * width
            for col in range(8):
                source_x = x + col
                if source_x >= width:
                    source_x = width - 1
                append(component[buffer[base + source_x]])
        return samples

    def _chroma_block(self, buffer, x, y, component):
        """Point sampled 8x8 chroma block covering a 16x16 MCU."""
        width = self.width
        height = self.height
        samples = []
        append = samples.append
        for row in range(8):
            source_y = y + row * 2
            if source_y >= height:
                source_y = height - 1
            base = source_y * width
            for col in range(8):
                source_x = x + col * 2
                if source_x >= width:
                    source_x = width - 1
                append(component[buffer[base + source_x]])
        return samples

    def set_gain(self, percent):
        """Darken every frame to ``percent`` of its original brightness.

        Returns ``True`` when the gain actually changed, in which case the
        next frame has to be encoded in full: the cached rows and blocks
        were produced with the old gain.
        """
        gain = max(0, min(256, int(round(max(0.0, min(100.0, float(percent)))
                                        * 256.0 / 100.0))))
        if gain == self.gain:
            return False
        self.gain = gain
        self.components = (_Component(0, gain), _Component(1, gain),
                           _Component(2, gain))
        self._block_cache = {}
        self.reset()
        return True

    def reset(self):
        """Forget the cached frame, forcing a full encode next time."""
        self._previous = None
        self._row_cache = {}
