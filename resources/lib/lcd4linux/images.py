"""Image loading, scaling and caching for the layout engine.

Everything works with plain RGBA ``bytearray`` buffers.  Decoding is done by
the bundled pure-Python PNG/JPEG readers, so nothing outside the add-on has
to be installed.
"""

import errno
import hashlib
import math
import os
import struct
import threading
import time
import zlib
from array import array

try:
    from urllib.parse import quote, unquote
except ImportError:  # pragma: no cover - Python 2 safety net
    from urllib import quote, unquote  # type: ignore

from . import pngio
from . import jpegio
from .logger import debug, debug_enabled, log

try:
    import xbmcvfs  # type: ignore
except ImportError:
    xbmcvfs = None


class Sprite(object):
    """An image converted to RGB565 and split into fast and slow spans.

    Each row is stored as ``(runs, partial)``.  ``runs`` holds one
    ``(start, array('H'))`` pair per stretch of fully opaque pixels, which a
    canvas can drop in with a single slice assignment, and ``partial`` lists
    the few pixels that need real alpha blending (anti-aliased edges,
    letterboxing, soft corners).  Transparent pixels appear in neither, so
    the hole in a clear logo or an icon keeps whatever was behind it.
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
        runs = []
        partial = []
        opaque = None
        for x in range(width):
            index = base + x * 4
            alpha = pixels[index + 3]
            if alpha == 255:
                value = (((pixels[index] & 0xF8) << 8)
                         | ((pixels[index + 1] & 0xFC) << 3)
                         | (pixels[index + 2] >> 3))
                if opaque is None:
                    opaque = array("H")
                    runs.append((x, opaque))
                opaque.append(value)
                continue
            # Anything not fully opaque ends the run it interrupts; only
            # pixels that actually cover something are blended.
            opaque = None
            if alpha:
                partial.append((x, pixels[index], pixels[index + 1],
                                pixels[index + 2], alpha))
        rows.append((runs, partial))
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
    def flattened(self, color=None, dim=0):
        """An opaque copy over ``color``, blended ``dim``/255 toward black.

        This is what a page background is: a solid colour, the picture on
        top of it, and a black veil over both.  Drawing it that way meant
        three passes over the canvas on the render thread, the veil alone
        being an alpha blend per pixel.  Done here it is one pass, and it
        happens wherever this image is prepared - for the service, on the
        loader thread.
        """
        dim = max(0, min(255, int(dim)))
        if color is None and dim <= 0:
            return self
        keep = 255 - dim
        pixels = self.pixels
        out = bytearray(len(pixels))
        for index in range(0, len(pixels), 4):
            alpha = pixels[index + 3]
            if alpha == 255 or color is None:
                red = pixels[index]
                green = pixels[index + 1]
                blue = pixels[index + 2]
            else:
                # The canvas is opaque, so whatever the picture does not
                # cover is the page colour rather than a hole.
                inverse = 255 - alpha
                red = (pixels[index] * alpha + color[0] * inverse) // 255
                green = (pixels[index + 1] * alpha + color[1] * inverse) // 255
                blue = (pixels[index + 2] * alpha + color[2] * inverse) // 255
                alpha = 255
            if dim:
                red = red * keep // 255
                green = green * keep // 255
                blue = blue * keep // 255
            out[index] = red
            out[index + 1] = green
            out[index + 2] = blue
            out[index + 3] = alpha
        return Image(self.width, self.height, out)

    def turned(self, degrees, smooth=True):
        """A copy rotated clockwise by ``degrees``, in a box that fits it.

        The result is wider and taller than the original for anything that
        is not a quarter turn, and whatever the corners sweep out is left
        transparent, so the caller only has to centre it over the place the
        upright version sat.  Quarter turns take a separate path: they are
        a pure index shuffle, exact to the pixel and several times cheaper
        than sampling, and they are what most rotated elements use.
        """
        angle = float(degrees) % 360.0
        if angle < 0.05 or angle > 359.95:
            return self
        if abs(angle - 90.0) < 0.05:
            return self._quarter_turn(1)
        if abs(angle - 180.0) < 0.05:
            return self._quarter_turn(2)
        if abs(angle - 270.0) < 0.05:
            return self._quarter_turn(3)
        return self._free_turn(angle, smooth)

    def _quarter_turn(self, steps):
        """1, 2 or 3 clockwise quarter turns, by moving pixels about."""
        steps = int(steps) % 4
        if steps == 0:
            return self
        source = self.pixels
        width = self.width
        height = self.height
        if steps == 2:
            out = bytearray(len(source))
            count = width * height
            for index in range(count):
                src = (count - 1 - index) * 4
                dst = index * 4
                out[dst:dst + 4] = source[src:src + 4]
            return Image(width, height, out)
        # A quarter turn swaps the sides of the box.
        out = bytearray(len(source))
        for y in range(height):
            row = y * width * 4
            for x in range(width):
                if steps == 1:
                    dst = (x * height + (height - 1 - y)) * 4
                else:
                    dst = ((width - 1 - x) * height + y) * 4
                src = row + x * 4
                out[dst:dst + 4] = source[src:src + 4]
        return Image(height, width, out)

    def _free_turn(self, angle, smooth):
        """Any other angle, by sampling the source for every output pixel."""
        radians = math.radians(angle)
        sin = math.sin(radians)
        cos = math.cos(radians)
        width = self.width
        height = self.height
        out_w = max(1, int(math.ceil(abs(width * cos) + abs(height * sin))))
        out_h = max(1, int(math.ceil(abs(width * sin) + abs(height * cos))))
        source = self.pixels
        out = bytearray(out_w * out_h * 4)
        # Screen coordinates run downwards, so this matrix turns clockwise.
        # Every output pixel is mapped back into the source rather than the
        # other way round, which is what keeps the result free of holes.
        centre_x = (width - 1) / 2.0
        centre_y = (height - 1) / 2.0
        offset_x = (out_w - 1) / 2.0
        offset_y = (out_h - 1) / 2.0
        for out_y in range(out_h):
            dv = out_y - offset_y
            base_x = dv * sin + centre_x
            base_y = dv * cos + centre_y
            step_x = cos
            step_y = -sin
            dst = out_y * out_w * 4
            du = -offset_x
            for _out_x in range(out_w):
                src_x = base_x + du * step_x
                src_y = base_y + du * step_y
                du += 1.0
                if smooth:
                    _sample_bilinear(source, width, height, src_x, src_y,
                                     out, dst)
                else:
                    px = int(src_x + 0.5)
                    py = int(src_y + 0.5)
                    if 0 <= px < width and 0 <= py < height:
                        src = (py * width + px) * 4
                        out[dst:dst + 4] = source[src:src + 4]
                dst += 4
        return Image(out_w, out_h, out)

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

def _sample_bilinear(pixels, width, height, x, y, out, dst):
    """Write the colour at the fractional point ``x, y`` into ``out``.

    Alpha is folded into the colour before the four neighbours are mixed and
    taken out again afterwards, so the transparent pixels around a glyph
    cannot bleed their black into its edge.  Anything outside the source is
    transparent, which is what gives a rotated box its empty corners.
    """
    left = int(math.floor(x))
    top = int(math.floor(y))
    if left < -1 or top < -1 or left >= width or top >= height:
        return
    fx = x - left
    fy = y - top
    red = green = blue = alpha = 0.0
    for offset_y, weight_y in ((0, 1.0 - fy), (1, fy)):
        py = top + offset_y
        if weight_y <= 0.0 or py < 0 or py >= height:
            continue
        row = py * width * 4
        for offset_x, weight_x in ((0, 1.0 - fx), (1, fx)):
            px = left + offset_x
            if weight_x <= 0.0 or px < 0 or px >= width:
                continue
            weight = weight_x * weight_y
            index = row + px * 4
            pixel_alpha = pixels[index + 3] * weight
            red += pixels[index] * pixel_alpha
            green += pixels[index + 1] * pixel_alpha
            blue += pixels[index + 2] * pixel_alpha
            alpha += pixel_alpha
    if alpha < 0.5:
        return
    out[dst] = min(255, int(red / alpha + 0.5))
    out[dst + 1] = min(255, int(green / alpha + 0.5))
    out[dst + 2] = min(255, int(blue / alpha + 0.5))
    out[dst + 3] = min(255, int(alpha + 0.5))


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
        wx = fx - x0
        x_info.append((x0 * 4, x1 * 4, 1.0 - wx, wx))
    dst = 0
    # Written out rather than looped over the four channels: this runs once
    # per pixel of a whole panel and the interpreter's own overhead - the
    # range, the index arithmetic - was costing more than the arithmetic.
    for y in range(dst_h):
        fy = (y + 0.5) * src_h / dst_h - 0.5
        if fy < 0:
            fy = 0.0
        y0 = int(fy)
        y1 = min(y0 + 1, src_h - 1)
        wy = fy - y0
        iwy = 1.0 - wy
        row0 = y0 * src_w * 4
        row1 = y1 * src_w * 4
        for x0off, x1off, iwx, wx in x_info:
            top_left = row0 + x0off
            top_right = row0 + x1off
            low_left = row1 + x0off
            low_right = row1 + x1off
            w00 = iwx * iwy
            w01 = wx * iwy
            w10 = iwx * wy
            w11 = wx * wy
            out[dst] = int(pixels[top_left] * w00 + pixels[top_right] * w01
                           + pixels[low_left] * w10 + pixels[low_right] * w11
                           + 0.5)
            out[dst + 1] = int(pixels[top_left + 1] * w00
                               + pixels[top_right + 1] * w01
                               + pixels[low_left + 1] * w10
                               + pixels[low_right + 1] * w11 + 0.5)
            out[dst + 2] = int(pixels[top_left + 2] * w00
                               + pixels[top_right + 2] * w01
                               + pixels[low_left + 2] * w10
                               + pixels[low_right + 2] * w11 + 0.5)
            out[dst + 3] = int(pixels[top_left + 3] * w00
                               + pixels[top_right + 3] * w01
                               + pixels[low_left + 3] * w10
                               + pixels[low_right + 3] * w11 + 0.5)
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
    if data[:8] == pngio.PNG_MAGIC:
        width, height, rgba = pngio.decode(data)
        return Image(width, height, rgba)
    if data[:2] == b"\xff\xd8":
        width, height, rgba = jpegio.decode(data, max_size)
        return Image(width, height, rgba)
    raise ValueError("unsupported image format")


def decode_size(width, height, fit="contain"):
    """The longest edge a decoder has to deliver to fill a box sharply.

    ``contain`` and ``stretch`` are bounded by the longer edge of the box.
    ``cover`` is bounded by the shorter one, and how much of the original
    that takes depends on the shape of the picture - which is not known
    until it has been decoded.  16:9 is assumed, which is what fanart is and
    is wider than any poster or piece of cover art, so the decode is never
    short and never the full frame either.
    """
    width = max(1, int(width))
    height = max(1, int(height))
    if str(fit).lower() == "cover":
        return max(width, height, min(width, height) * 16 // 9)
    return max(width, height)


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


def _vfs_read(path):
    try:
        handle = xbmcvfs.File(path)
        try:
            data = handle.readBytes()
        finally:
            handle.close()
        return bytes(data) if data else b""
    except Exception as error:
        log("VFS read failed for %s: %s" % (path, error))
        return b""


def read_bytes(path):
    """Read a local, special:// or network path, preferring Kodi's VFS."""
    text = str(path or "")
    resolved = resolve_path(text)
    if not resolved:
        return b""
    if xbmcvfs is not None:
        candidates = [resolved]
        if text.startswith("image://"):
            # Kodi's own copy first.  An ``image://`` URL only wraps the
            # place the picture came from, and for library art that place
            # is the web - unwrapping it and reading that means fetching
            # the full sized original over the network all over again.
            # Handed to the VFS unchanged, Kodi serves the texture it has
            # already cached locally, scaled to its own limit.
            candidates.insert(0, text)
        for candidate in candidates:
            data = _vfs_read(candidate)
            if data:
                return data
    try:
        with open(resolved, "rb") as handle:
            return handle.read()
    except (IOError, OSError):
        return b""


def texture_bytes(path):
    """Kodi's own copy of a picture, made by Kodi's own decoder.

    The decoders in here are written in Python and cannot read every
    picture in the world: a progressive JPEG, above all, which a good
    part of the fanart on the internet is, and which is why some titles
    showed their backdrop and others did not.

    Kodi reads all of them.  Handed a path wrapped in ``image://`` its
    VFS produces the texture it caches for its own skin - a plain
    baseline JPEG or a PNG, already scaled down to its texture limit -
    and that is something these decoders can always read.
    """
    if xbmcvfs is None:
        return b""
    text = str(path or "")
    if not text or text.startswith("image://"):
        # Already Kodi's copy; asking for the same thing again is pointless.
        return b""
    return _vfs_read("image://%s/" % quote(text, safe=""))


def _decode_or_log(path, data, max_size):
    """Decode ``data``, reporting what went wrong instead of raising."""
    if not data:
        return None
    try:
        return decode_bytes(data, max_size)
    except Exception as error:
        log("cannot decode %s: %s" % (_short(path), error))
        return None


#: Magic and version of the files in the on disk picture cache.  Not an
#: image format anybody else reads: a finished RGBA buffer, deflated.
#: Storing a PNG would mean un-filtering it again on the way back in, and
#: that costs more than the deflate saves.
_BLOB_MAGIC = b"L4LI"
_BLOB_HEADER = struct.Struct(">4sHH")


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _short(path):
    """The tail of a path or URL, which is all a log line needs."""
    text = str(path or "")
    if len(text) <= 60:
        return text
    return "..." + text[-57:]


def _blob_encode(image):
    return (_BLOB_HEADER.pack(_BLOB_MAGIC, image.width, image.height)
            + zlib.compress(bytes(image.pixels), 1))


def _blob_decode(data):
    if len(data) <= _BLOB_HEADER.size:
        raise ValueError("truncated")
    magic, width, height = _BLOB_HEADER.unpack(data[:_BLOB_HEADER.size])
    if magic != _BLOB_MAGIC:
        raise ValueError("not one of ours")
    pixels = bytearray(zlib.decompress(data[_BLOB_HEADER.size:]))
    if len(pixels) != width * height * 4:
        raise ValueError("wrong length")
    return Image(width, height, pixels)


class ImageCache(object):
    """Decoded images keyed by source path and requested size.

    With ``background=True`` the cache also runs a worker thread and grows a
    second, asynchronous entry point, :meth:`request`.  Decoding a piece of
    fanart costs seconds of pure Python, and the service draws its frames
    from a single loop - doing that work inline froze the whole display,
    clock and progress bar included, until the picture was ready.  The
    worker does the reading, decoding, scaling and sprite building instead;
    the render thread only ever gets a finished picture or ``None``.
    """

    #: How long a path that could not be read is remembered as missing.
    #: Long enough that a wall of cover art Kodi has not downloaded yet is
    #: not re-opened on every frame, short enough that the picture appears
    #: on its own once the file is there.
    MISS_SECONDS = 5.0

    #: How many pictures may wait for the worker at once.  A page that asks
    #: for more gets the rest on a later frame rather than piling up a queue
    #: that is stale by the time it is worked off.
    QUEUE_LIMIT = 8

    #: Raw decodes held back for a moment so that a poster and a background
    #: built from the same file do not decode it twice.  They are large and
    #: only ever an intermediate step, so they are kept apart from the
    #: prepared pictures instead of crowding them out of the cache.
    RAW_LIMIT = 3

    #: How many finished pictures ``directory`` keeps.  They are small - a
    #: panel sized RGBA buffer deflates to some tens of kilobytes - so this
    #: is a couple of megabytes for a whole library's worth of covers.
    DISK_LIMIT = 200

    #: And how long one of them is trusted.  Art behind an unchanged URL
    #: does get replaced now and then, and a month is short enough that a
    #: stale picture rights itself without anybody clearing a cache.
    DISK_DAYS = 30

    def __init__(self, limit=24, background=False, directory=None):
        self.limit = limit
        self.directory = directory
        self._entries = {}
        self._misses = {}
        self._raw = {}
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._background = bool(background)
        self._queue = []
        self._pending = set()
        self._worker = None
        self._stop = False
        self._writes = 0

    # -- synchronous access ----------------------------------------------
    def get(self, path, max_size=None):
        key = (path, max_size)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry[1] = time.time()
                return entry[0]
            missed_at = self._misses.get(key)
            if missed_at is not None and time.time() - missed_at < self.MISS_SECONDS:
                return None
        data = read_bytes(path)
        image = None
        texture = b""
        if data and jpegio.is_progressive(data):
            # A progressive JPEG can be read here, but only the slow way:
            # every scan of the whole picture, at full size, before a
            # single pixel exists.  Kodi's decoder is C and it keeps a
            # baseline copy of everything its own skin has shown, so ask
            # for that first and keep the slow road for when there is none.
            texture = texture_bytes(path)
            image = _decode_or_log(path, texture, max_size)
            if image is None:
                debug("%s is progressive; decoding it the long way"
                      % _short(path))
        if image is None:
            image = _decode_or_log(path, data, max_size)
        if image is None and not texture:
            # Either nothing came back or nothing in here could read it.
            # Kodi can read it - it is showing the same picture in its own
            # skin - so the second try goes through its texture cache.
            texture = texture_bytes(path)
            if texture and texture != data:
                image = _decode_or_log(path, texture, max_size)
                if image is not None:
                    debug("%s came out of Kodi's texture cache" % _short(path))
        if image is None:
            # Remembered briefly rather than cached for good: the file may
            # still be on its way, but retrying it every frame means a
            # failing open per frame for as long as the page is up.
            self._remember_miss(key)
            return None
        with self._lock:
            self._misses.pop(key, None)
            self._store(key, image)
        return image

    def put(self, key, image):
        with self._lock:
            self._store(key, image)

    def lookup(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            entry[1] = time.time()
            return entry[0]

    # -- asynchronous access ---------------------------------------------
    def request(self, key, path, max_size=None, prepare=None):
        """The finished picture for ``key``, or ``None`` while it is loading.

        ``prepare`` turns the decoded original into whatever the caller wants
        to keep - scaled to a widget, cropped, a dominant colour.  It runs on
        the worker thread, so everything expensive stays off the render loop.
        Without a worker the whole thing happens right here, which is what
        the preview renderer and the command line tools need.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry[1] = time.time()
                return entry[0]
            if self._background:
                missed_at = self._misses.get(key)
                if missed_at is not None \
                        and time.time() - missed_at < self.MISS_SECONDS:
                    return None
                if key not in self._pending \
                        and len(self._queue) < self.QUEUE_LIMIT:
                    self._queue.append((key, path, max_size, prepare))
                    self._pending.add(key)
                    self._start_worker()
                    self._wake.notify()
                return None
        return self._prepare(key, path, max_size, prepare)

    #: Below this the decode is quick enough that a rough version first
    #: would only put a blurry frame in front of the real one.  Above it -
    #: a full panel of fanart, essentially - it is worth it.
    DRAFT_ABOVE = 400

    def progressive(self, key, path, max_size, prepare, draft_prepare=None):
        """The finished picture, or something to look at until it is there.

        Returns ``(image, finished)``.  ``finished`` is false both when
        nothing can be drawn yet and when what comes back is the rough
        version, so that a caller which caches its result knows not to.

        ``draft_prepare`` builds the rough one and should cut whatever
        corners it can - the caller's own smoothing, in particular, since
        scaling a small picture up smoothly costs more than decoding it.
        """
        draft = None
        if max_size >= self.DRAFT_ABOVE and not self.known(key):
            size = max(1, max_size // 2)
            draft = self.request(key + ("draft", size), path, size,
                                 draft_prepare or prepare)
        image = self.request(key, path, max_size, prepare)
        if image is not None:
            return image, True
        return draft, False

    def known(self, key):
        """Whether this picture can be had without decoding anything.

        Used to decide whether a rough stand-in is worth asking for: if the
        real one is a deflate away, drawing something worse first would only
        put a blurry frame in front of it.
        """
        with self._lock:
            if key in self._entries:
                return True
        path = self._disk_path(key)
        return bool(path) and os.path.exists(path)

    def _prepare(self, key, path, max_size, prepare):
        # A picture this panel has drawn before is already the right size:
        # reading it back costs a deflate rather than a JPEG decode and a
        # scale, which for a piece of 1080p fanart is the difference
        # between a tenth of a second and several of them.
        image = self._read_disk(key)
        if image is not None:
            started = time.time()
            image.sprite()
            with self._lock:
                self._misses.pop(key, None)
                self._store(key, image)
            debug("%s from the picture cache in %d ms"
                  % (_short(path), (time.time() - started) * 1000))
            return image

        started = time.time()
        raw = self._raw_image(path, max_size)
        decoded_at = time.time()
        if raw is None:
            # Nothing to show yet - or nothing that decodes.  Either way the
            # answer keeps for a few seconds, so the caller does not ask for
            # it again on every frame.
            self._remember_miss(key)
            return None
        try:
            image = raw if prepare is None else prepare(raw)
        except Exception as error:
            log("cannot prepare %s: %s" % (path, error))
            image = None
        if image is not None and hasattr(image, "sprite"):
            # Built here rather than on the first blit: it is another pass
            # over every pixel, and here it happens on the worker's time.
            image.sprite()
        finished_at = time.time()
        if debug_enabled():
            debug("%s: %dx%d read and decoded in %d ms, prepared in %d ms"
                  % (_short(path), raw.width, raw.height,
                     (decoded_at - started) * 1000,
                     (finished_at - decoded_at) * 1000))
        with self._lock:
            self._misses.pop(key, None)
            self._store(key, image)
        self._write_disk(key, image)
        return image

    # -- the picture cache on disk ----------------------------------------
    def _disk_path(self, key):
        if not self.directory:
            return None
        name = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()
        return os.path.join(self.directory, name + ".l4i")

    def _read_disk(self, key):
        path = self._disk_path(key)
        if not path:
            return None
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except (IOError, OSError):
            return None
        try:
            image = _blob_decode(data)
        except Exception:
            # A half written or outdated file is simply drawn again.
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        try:
            os.utime(path, None)
        except OSError:
            pass
        return image

    def _write_disk(self, key, image):
        path = self._disk_path(key)
        if not path or image is None or not hasattr(image, "pixels"):
            return
        try:
            if not os.path.isdir(self.directory):
                os.makedirs(self.directory)
            # Written beside the real name and moved into place, so that a
            # reader never gets half a file - the worker writes these while
            # the render thread is running.
            temporary = "%s.%d" % (path, os.getpid())
            with open(temporary, "wb") as handle:
                handle.write(_blob_encode(image))
            if os.path.exists(path):
                os.remove(path)
            os.rename(temporary, path)
        except (IOError, OSError) as error:
            if getattr(error, "errno", None) != errno.ENOSPC:
                debug("cannot keep a picture in %s: %s" % (self.directory, error))
            return
        with self._lock:
            self._writes += 1
            due = self._writes % 25 == 1
        if due:
            self._prune_disk()

    def _prune_disk(self):
        """Drop the oldest and the stalest, now and then rather than always."""
        try:
            names = [name for name in os.listdir(self.directory)
                     if name.endswith(".l4i")]
        except OSError:
            return
        stale = time.time() - self.DISK_DAYS * 86400
        entries = []
        for name in names:
            full = os.path.join(self.directory, name)
            try:
                touched = os.path.getmtime(full)
            except OSError:
                continue
            if touched < stale:
                _remove(full)
                continue
            entries.append((touched, full))
        if len(entries) <= self.DISK_LIMIT:
            return
        entries.sort()
        for _, full in entries[:len(entries) - self.DISK_LIMIT]:
            _remove(full)

    def _raw_image(self, path, max_size):
        raw_key = (path, max_size)
        with self._lock:
            entry = self._raw.get(raw_key)
            if entry is not None:
                entry[1] = time.time()
                return entry[0]
        image = self.get(path, max_size)
        if image is None:
            return None
        with self._lock:
            self._raw[raw_key] = [image, time.time()]
            if len(self._raw) > self.RAW_LIMIT:
                oldest = sorted(self._raw.items(), key=lambda item: item[1][1])
                for old_key, _ in oldest[:len(self._raw) - self.RAW_LIMIT]:
                    self._raw.pop(old_key, None)
            # The original is only a step on the way to the prepared picture;
            # leaving a full frame of fanart in the main cache would push
            # several of the pictures actually being drawn out of it.
            self._entries.pop(raw_key, None)
        return image

    def _remember_miss(self, key):
        with self._lock:
            if len(self._misses) > 4 * self.limit:
                self._misses.clear()
            self._misses[key] = time.time()

    # -- worker -----------------------------------------------------------
    def _start_worker(self):
        """Start the loader thread.  Called with the lock held."""
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop = False
        self._worker = threading.Thread(target=self._work,
                                        name="lcd4linux-images")
        self._worker.daemon = True
        self._worker.start()

    def _work(self):
        while True:
            with self._lock:
                while not self._queue and not self._stop:
                    self._wake.wait(1.0)
                if self._stop:
                    return
                key, path, max_size, prepare = self._queue.pop(0)
            try:
                self._prepare(key, path, max_size, prepare)
            except Exception as error:
                log("cannot load %s: %s" % (path, error))
            finally:
                with self._lock:
                    self._pending.discard(key)

    def stop(self):
        """Let the worker finish; safe on a cache that never started one."""
        with self._lock:
            self._stop = True
            self._queue = []
            self._pending.clear()
            self._wake.notify_all()
            worker = self._worker
            self._worker = None
        if worker is not None and worker.is_alive():
            worker.join(2.0)

    # -- housekeeping -----------------------------------------------------
    def _store(self, key, image):
        """Remember one entry, evicting the coldest.  Lock held."""
        self._entries[key] = [image, time.time()]
        if len(self._entries) > self.limit:
            oldest = sorted(self._entries.items(), key=lambda item: item[1][1])
            for old_key, _ in oldest[:len(self._entries) - self.limit]:
                self._entries.pop(old_key, None)

    def clear(self, disk=False):
        with self._lock:
            self._entries.clear()
            self._misses.clear()
            self._raw.clear()
            self._queue = []
            self._pending.clear()
        if disk and self.directory:
            try:
                names = os.listdir(self.directory)
            except OSError:
                return
            for name in names:
                if name.endswith(".l4i"):
                    _remove(os.path.join(self.directory, name))


def load_file(path, max_size=None):
    """Convenience wrapper used by the tools and the preview renderer."""
    if not os.path.exists(resolve_path(path)) and xbmcvfs is None:
        return None
    data = read_bytes(path)
    if not data:
        return None
    return decode_bytes(data, max_size)
