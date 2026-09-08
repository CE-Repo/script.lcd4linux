"""Minimal pure-Python PNG reader/writer.

Only what the add-on needs: reading the bundled icons and any PNG the user
drops into a layout, and writing the layout preview snapshots.  Supports
8 bit greyscale/RGB/RGBA/palette images plus tRNS transparency, which
covers everything Kodi and common icon sets produce.
"""

import struct
import zlib

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw, width, height, bpp, stride):
    out = bytearray(stride * height)
    prev = bytearray(stride)
    pos = 0
    for row in range(height):
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if filter_type == 0:
            pass
        elif filter_type == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        else:
            raise ValueError("unsupported PNG filter %d" % filter_type)
        out[row * stride:(row + 1) * stride] = line
        prev = line
    return out


def decode(data):
    """Decode PNG bytes into ``(width, height, rgba_bytearray)``."""
    if data[:8] != PNG_MAGIC:
        raise ValueError("not a PNG file")
    pos = 8
    width = height = 0
    depth = color_type = 0
    palette = None
    trns = None
    idat = []
    while pos < len(data):
        length, ctype = struct.unpack_from(">I4s", data, pos)
        pos += 8
        chunk = data[pos:pos + length]
        pos += length + 4  # skip CRC
        if ctype == b"IHDR":
            width, height, depth, color_type, _comp, _filt, interlace = \
                struct.unpack(">IIBBBBB", chunk)
            if interlace:
                raise ValueError("interlaced PNG is not supported")
            if depth not in (1, 2, 4, 8, 16):
                raise ValueError("unsupported PNG bit depth %d" % depth)
        elif ctype == b"PLTE":
            palette = chunk
        elif ctype == b"tRNS":
            trns = chunk
        elif ctype == b"IDAT":
            idat.append(chunk)
        elif ctype == b"IEND":
            break
    raw = zlib.decompress(b"".join(idat))

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    bits = channels * depth
    stride = (width * bits + 7) // 8
    bpp = max(1, bits // 8)
    lines = _unfilter(raw, width, height, bpp, stride)

    rgba = bytearray(width * height * 4)
    sample_max = (1 << depth) - 1

    def samples(row):
        """Yield the unpacked samples of one row."""
        base = row * stride
        if depth == 8:
            return lines[base:base + width * channels]
        if depth == 16:
            return lines[base:base + width * channels * 2:2]
        values = bytearray()
        per_byte = 8 // depth
        mask = sample_max
        needed = width * channels
        for index in range(needed):
            byte = lines[base + index // per_byte]
            shift = 8 - depth * (index % per_byte + 1)
            values.append((byte >> shift) & mask)
        return values

    for row in range(height):
        src = samples(row)
        dst = row * width * 4
        if color_type == 0:
            for x in range(width):
                value = src[x]
                if depth not in (8, 16):
                    value = value * 255 // sample_max
                rgba[dst] = rgba[dst + 1] = rgba[dst + 2] = value
                rgba[dst + 3] = 255
                dst += 4
        elif color_type == 2:
            for x in range(width):
                offset = x * 3
                rgba[dst] = src[offset]
                rgba[dst + 1] = src[offset + 1]
                rgba[dst + 2] = src[offset + 2]
                rgba[dst + 3] = 255
                dst += 4
        elif color_type == 3:
            for x in range(width):
                index = src[x]
                offset = index * 3
                rgba[dst] = palette[offset]
                rgba[dst + 1] = palette[offset + 1]
                rgba[dst + 2] = palette[offset + 2]
                rgba[dst + 3] = trns[index] if trns and index < len(trns) else 255
                dst += 4
        elif color_type == 4:
            for x in range(width):
                offset = x * 2
                rgba[dst] = rgba[dst + 1] = rgba[dst + 2] = src[offset]
                rgba[dst + 3] = src[offset + 1]
                dst += 4
        else:
            for x in range(width):
                offset = x * 4
                rgba[dst] = src[offset]
                rgba[dst + 1] = src[offset + 1]
                rgba[dst + 2] = src[offset + 2]
                rgba[dst + 3] = src[offset + 3]
                dst += 4

    if color_type == 2 and trns and len(trns) >= 6:
        key = (struct.unpack(">3H", trns[:6]))
        key = tuple(k & 0xFF for k in key)
        for i in range(0, len(rgba), 4):
            if (rgba[i], rgba[i + 1], rgba[i + 2]) == key:
                rgba[i + 3] = 0
    return width, height, rgba


def encode_rgb(width, height, rgb):
    """Encode plain RGB bytes into a PNG file."""
    raw = bytearray()
    stride = width * 3
    for row in range(height):
        raw.append(0)
        raw.extend(rgb[row * stride:(row + 1) * stride])

    def chunk(tag, payload):
        out = struct.pack(">I", len(payload)) + tag + payload
        return out + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    return b"".join((
        PNG_MAGIC,
        chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
        chunk(b"IDAT", zlib.compress(bytes(raw), 6)),
        chunk(b"IEND", b""),
    ))


def encode_rgba(width, height, rgba):
    raw = bytearray()
    stride = width * 4
    for row in range(height):
        raw.append(0)
        raw.extend(rgba[row * stride:(row + 1) * stride])

    def chunk(tag, payload):
        out = struct.pack(">I", len(payload)) + tag + payload
        return out + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    return b"".join((
        PNG_MAGIC,
        chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
        chunk(b"IDAT", zlib.compress(bytes(raw), 6)),
        chunk(b"IEND", b""),
    ))
