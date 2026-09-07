"""Image loading, scaling and caching for the layout engine.

Everything works with plain RGBA ``bytearray`` buffers.  Decoding is done by
the bundled pure-Python PNG/JPEG readers; if Pillow happens to be installed
(for example through ``script.module.pillow``) it is used instead because it
is considerably faster.
"""

import os
import time
from array import array

try:
    from urllib.parse import unquote
except ImportError:  # pragma: no cover - Python 2 safety net
    from urllib import unquote  # type: ignore

from . import pngio
from . import jpegio
from .logger import log

try:
    from PIL import Image as _PILImage  # type: ignore
except Exception:
    _PILImage = None

try:
    import xbmcvfs  # type: ignore
except ImportError:
    xbmcvfs = None


class Sprite(object):
    """An image converted to RGB565 and split into fast and slow spans.

    Each row is stored as ``(opaque_start, opaque_pixels, partial)`` where
    ``opaque_pixels`` is an ``array('H')`` that a canvas can drop in with one
    slice assignment, and ``partial`` lists the few pixels that need real
    alpha blending (anti-aliased corners, letterboxing, soft edges).
    """

    __slots__ = ("width", "height", "rows")

    def __init__(self, width, height, rows):
        self.width = width
        self.height = height
        self.rows = rows


def build_sprite(width, height, pixels):
    """Convert RGBA bytes into a :class:`Sprite`."""
    rows = []
    for y in range(height):
        base = y * width * 4
        # Find the longest fully opaque run; that is the part that can be
        # copied instead of blended.
        start = 0
        while start < width and pixels[base + start * 4 + 3] != 255:
            start += 1
        end = width
        while end > start and pixels[base + (end - 1) * 4 + 3] != 255:
            end -= 1
        opaque = array("H")
        partial = []
        for x in range(start, end):
            index = base + x * 4
            alpha = pixels[index + 3]
            value = (((pixels[index] & 0xF8) << 8)
                     | ((pixels[index + 1] & 0xFC) << 3)
                     | (pixels[index + 2] >> 3))
            if alpha == 255:
                opaque.append(value)
            else:
                # A hole inside the run: keep the slot (it is overwritten
                # again by the blend below) and remember the real pixel.
                opaque.append(value)
                partial.append((x, pixels[index], pixels[index + 1],
                                pixels[index + 2], alpha))
        for x in list(range(0, start)) + list(range(end, width)):
            index = base + x * 4
            alpha = pixels[index + 3]
            if alpha:
                partial.append((x, pixels[index], pixels[index + 1],
                                pixels[index + 2], alpha))
        rows.append((start, opaque, partial))
    return Sprite(width, height, rows)


class Image(object):
    """An RGBA raster."""

    __slots__ = ("width", "height", "pixels", "_sprite")

    def __init__(self, width, height, pixels):
        self.width = width
        self.height = height
        self.pixels = pixels
        self._sprite = None

    def sprite(self):
        """A cached blit-ready version of this image."""
        if self._sprite is None:
            self._sprite = build_sprite(self.width, self.height, self.pixels)
        return self._sprite

    # -- geometry ---------------------------------------------------------
    def scaled(self, width, height, smooth=True):
        width = max(1, int(width))
        height = max(1, int(height))
        if width == self.width and height == self.height:
            return self
        if smooth:
            return Image(width, height, _resample_bilinear(
                self.pixels, self.width, self.height, width, height))
        return Image(width, height, _resample_nearest(
            self.pixels, self.width, self.height, width, height))

    def cropped(self, x, y, width, height):
        x = max(0, int(x))
        y = max(0, int(y))
        width = min(int(width), self.width - x)
        height = min(int(height), self.height - y)
        out = bytearray(width * height * 4)
        for row in range(height):
            src = ((y + row) * self.width + x) * 4
            dst = row * width * 4
            out[dst:dst + width * 4] = self.pixels[src:src + width * 4]
        return Image(width, height, out)

    def fitted(self, width, height, mode="contain", smooth=True):
        """Resize into a ``width`` x ``height`` box.

        ``contain`` keeps the whole image (letterboxed by the caller),
        ``cover`` fills the box and crops the overflow, ``stretch`` ignores
        the aspect ratio.
        """
        width = max(1, int(width))
        height = max(1, int(height))
        if mode == "stretch":
            return self.scaled(width, height, smooth)
        scale_x = width / float(self.width)
        scale_y = height / float(self.height)
        scale = min(scale_x, scale_y) if mode == "contain" else max(scale_x, scale_y)
        new_w = max(1, int(round(self.width * scale)))
        new_h = max(1, int(round(self.height * scale)))
        result = self.scaled(new_w, new_h, smooth)
        if mode == "cover" and (new_w > width or new_h > height):
            result = result.cropped((new_w - width) // 2, (new_h - height) // 2,
                                    width, height)
        return result

    # -- effects ----------------------------------------------------------
    def rounded(self, radius):
        """Soften the corners by writing an anti-aliased alpha mask."""
        radius = int(radius)
        if radius <= 0:
            return self
        radius = min(radius, min(self.width, self.height) // 2)
        pixels = bytearray(self.pixels)
        for corner_y in range(radius):
            dy = radius - corner_y - 0.5
            for corner_x in range(radius):
                dx = radius - corner_x - 0.5
                dist = (dx * dx + dy * dy) ** 0.5
                if dist <= radius - 0.5:
                    continue
                coverage = max(0.0, min(1.0, radius + 0.5 - dist))
                factor = int(coverage * 255)
                for px, py in ((corner_x, corner_y),
                               (self.width - 1 - corner_x, corner_y),
                               (corner_x, self.height - 1 - corner_y),
                               (self.width - 1 - corner_x, self.height - 1 - corner_y)):
                    index = (py * self.width + px) * 4 + 3
                    pixels[index] = pixels[index] * factor // 255
        return Image(self.width, self.height, pixels)

    def dominant_color(self):
        """A saturated average colour, useful as an accent from cover art."""
        pixels = self.pixels
        step = max(4, (self.width * self.height // 2000)) * 4
        total_r = total_g = total_b = 0
        count = 0
        best = (0, 0, 0)
        best_score = -1.0
        for index in range(0, len(pixels) - 3, step):
            r, g, b, a = pixels[index], pixels[index + 1], pixels[index + 2], pixels[index + 3]
            if a < 128:
                continue
            total_r += r
            total_g += g
            total_b += b
            count += 1
            high = max(r, g, b)
            low = min(r, g, b)
            if high < 40 or high > 245:
                continue
            score = (high - low) * (high / 255.0)
            if score > best_score:
                best_score = score
                best = (r, g, b)
        if best_score > 25:
            return (best[0], best[1], best[2], 255)
        if count:
            return (total_r // count, total_g // count, total_b // count, 255)
        return (128, 128, 128, 255)


# ---------------------------------------------------------------------------
# resampling
# ---------------------------------------------------------------------------

def _resample_nearest(pixels, src_w, src_h, dst_w, dst_h):
    out = bytearray(dst_w * dst_h * 4)
    x_map = [min(src_w - 1, x * src_w // dst_w) * 4 for x in range(dst_w)]
    for y in range(dst_h):
        src_row = min(src_h - 1, y * src_h // dst_h) * src_w * 4
        dst = y * dst_w * 4
        for x in range(dst_w):
            src = src_row + x_map[x]
            out[dst:dst + 4] = pixels[src:src + 4]
            dst += 4
    return out


def _resample_bilinear(pixels, src_w, src_h, dst_w, dst_h):
    if src_w >= dst_w * 2 and src_h >= dst_h * 2:
        # Big reduction: average boxes instead, it is both faster per output
        # pixel and avoids the aliasing bilinear would produce.
        return _resample_box(pixels, src_w, src_h, dst_w, dst_h)
    out = bytearray(dst_w * dst_h * 4)
    x_info = []
    for x in range(dst_w):
        fx = (x + 0.5) * src_w / dst_w - 0.5
        if fx < 0:
            fx = 0.0
        x0 = int(fx)
        x1 = min(x0 + 1, src_w - 1)
        x_info.append((x0 * 4, x1 * 4, fx - x0))
    for y in range(dst_h):
        fy = (y + 0.5) * src_h / dst_h - 0.5
        if fy < 0:
            fy = 0.0
        y0 = int(fy)
        y1 = min(y0 + 1, src_h - 1)
        wy = fy - y0
        row0 = y0 * src_w * 4
        row1 = y1 * src_w * 4
        dst = y * dst_w * 4
        for x0off, x1off, wx in x_info:
            for channel in range(4):
                top = pixels[row0 + x0off + channel] * (1 - wx) + pixels[row0 + x1off + channel] * wx
                bottom = pixels[row1 + x0off + channel] * (1 - wx) + pixels[row1 + x1off + channel] * wx
                out[dst + channel] = int(top * (1 - wy) + bottom * wy + 0.5)
            dst += 4
    return out


def _resample_box(pixels, src_w, src_h, dst_w, dst_h):
    out = bytearray(dst_w * dst_h * 4)
    x_bounds = [(x * src_w // dst_w, max(x * src_w // dst_w + 1, (x + 1) * src_w // dst_w))
                for x in range(dst_w)]
    for y in range(dst_h):
        y0 = y * src_h // dst_h
        y1 = max(y0 + 1, (y + 1) * src_h // dst_h)
        dst = y * dst_w * 4
        for x0, x1 in x_bounds:
            r = g = b = a = 0
            count = 0
            for sy in range(y0, y1):
                base = (sy * src_w + x0) * 4
                for _ in range(x1 - x0):
                    r += pixels[base]
                    g += pixels[base + 1]
                    b += pixels[base + 2]
                    a += pixels[base + 3]
                    base += 4
                    count += 1
            out[dst] = r // count
            out[dst + 1] = g // count
            out[dst + 2] = b // count
            out[dst + 3] = a // count
            dst += 4
    return out


# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------

def decode_bytes(data, max_size=None):
    """Decode PNG or JPEG bytes into an :class:`Image`."""
    if not data:
        raise ValueError("empty image data")
    if _PILImage is not None:
        try:
            import io
            with _PILImage.open(io.BytesIO(data)) as handle:
                if max_size:
                    handle.draft("RGB", (max_size, max_size))
                converted = handle.convert("RGBA")
                return Image(converted.width, converted.height,
                             bytearray(converted.tobytes()))
        except Exception as error:
            log("Pillow failed to decode image (%s), using builtin decoder" % error)
    if data[:8] == pngio.PNG_MAGIC:
        width, height, rgba = pngio.decode(data)
        return Image(width, height, rgba)
    if data[:2] == b"\xff\xd8":
        width, height, rgba = jpegio.decode(data, max_size)
        return Image(width, height, rgba)
    raise ValueError("unsupported image format")


def resolve_path(path):
    """Turn a Kodi art reference into something readable.

    ``image://`` URLs wrap the real location; ``special://`` paths are
    translated when running inside Kodi.
    """
    if not path:
        return ""
    text = str(path)
    if text.startswith("image://"):
        text = unquote(text[8:])
        if text.endswith("/"):
            text = text[:-1]
    if text.startswith("special://") and xbmcvfs is not None:
        try:
            text = xbmcvfs.translatePath(text)
        except Exception:
            pass
    return text


def read_bytes(path):
    """Read a local, special:// or network path, preferring Kodi's VFS."""
    path = resolve_path(path)
    if not path:
        return b""
    if xbmcvfs is not None:
        try:
            handle = xbmcvfs.File(path)
            try:
                data = handle.readBytes()
            finally:
                handle.close()
            if data:
                return bytes(data)
        except Exception as error:
            log("VFS read failed for %s: %s" % (path, error))
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except (IOError, OSError):
        return b""


class ImageCache(object):
    """Decoded images keyed by source path and requested size."""

    def __init__(self, limit=24):
        self.limit = limit
        self._entries = {}

    def get(self, path, max_size=None):
        key = (path, max_size)
        entry = self._entries.get(key)
        if entry is not None:
            entry[1] = time.time()
            return entry[0]
        data = read_bytes(path)
        if not data:
            return None
        try:
            image = decode_bytes(data, max_size)
        except Exception as error:
            log("cannot decode %s: %s" % (path, error))
            image = None
        self._store(key, image)
        return image

    def put(self, key, image):
        self._store(key, image)

    def lookup(self, key):
        entry = self._entries.get(key)
        if entry is None:
            return None
        entry[1] = time.time()
        return entry[0]

    def _store(self, key, image):
        self._entries[key] = [image, time.time()]
        if len(self._entries) > self.limit:
            oldest = sorted(self._entries.items(), key=lambda item: item[1][1])
            for old_key, _ in oldest[:len(self._entries) - self.limit]:
                self._entries.pop(old_key, None)

    def clear(self):
        self._entries.clear()


def load_file(path, max_size=None):
    """Convenience wrapper used by the tools and the preview renderer."""
    if not os.path.exists(resolve_path(path)) and xbmcvfs is None:
        return None
    data = read_bytes(path)
    if not data:
        return None
    return decode_bytes(data, max_size)
