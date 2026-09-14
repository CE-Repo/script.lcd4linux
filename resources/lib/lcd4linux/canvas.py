"""A small RGB565 software framebuffer with the primitives the layout
engine needs.

The buffer is an ``array('H')`` of 16 bit pixels which lets whole spans be
filled or copied with one C level slice assignment - important because this
runs in Kodi's interpreter on a low power ARM board.  Native byte order is
assumed to be little endian (every board Kodi runs on is), which is exactly
what the AX206 expects on the wire.
"""

import sys

from array import array

# ---------------------------------------------------------------------------
# colours
# ---------------------------------------------------------------------------

NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 200, 0), "blue": (0, 92, 255), "cyan": (0, 210, 230),
    "magenta": (255, 0, 200), "yellow": (255, 214, 0), "orange": (255, 138, 0),
    "grey": (128, 128, 128), "gray": (128, 128, 128), "silver": (190, 190, 190),
    "dimgrey": (64, 64, 64), "dimgray": (64, 64, 64), "purple": (150, 60, 220),
    "pink": (255, 105, 180), "lime": (128, 230, 0), "teal": (0, 160, 150),
    "brown": (140, 90, 50), "navy": (0, 40, 110), "gold": (240, 190, 60),
    "kodiblue": (23, 178, 226), "transparent": (0, 0, 0, 0),
}


def parse_color(value, default=(255, 255, 255, 255)):
    """Parse ``#RRGGBB``, ``#AARRGGBB``, ``#RGB``, ``r,g,b[,a]`` or a name.

    Returns an ``(r, g, b, a)`` tuple with 0-255 components.  The
    ``#AARRGGBB`` form is the one Kodi skins use, so layouts can be written
    with familiar values.
    """
    if value is None:
        return default
    if isinstance(value, (tuple, list)):
        parts = list(value) + [255] * (4 - len(value))
        return tuple(max(0, min(255, int(p))) for p in parts[:4])
    text = str(value).strip().lower()
    if not text:
        return default
    if text in NAMED_COLORS:
        rgb = NAMED_COLORS[text]
        return tuple(list(rgb) + [255] * (4 - len(rgb)))
    if text.startswith("#"):
        text = text[1:]
    elif text.startswith("0x"):
        text = text[2:]
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        try:
            nums = [int(float(p)) for p in parts]
        except ValueError:
            return default
        nums = nums + [255] * (4 - len(nums))
        return tuple(max(0, min(255, n)) for n in nums[:4])
    try:
        num = int(text, 16)
    except ValueError:
        return default
    if len(text) == 3:
        r = (num >> 8) & 0xF
        g = (num >> 4) & 0xF
        b = num & 0xF
        return (r * 17, g * 17, b * 17, 255)
    if len(text) == 6:
        return ((num >> 16) & 0xFF, (num >> 8) & 0xFF, num & 0xFF, 255)
    if len(text) == 8:
        return ((num >> 16) & 0xFF, (num >> 8) & 0xFF, num & 0xFF, (num >> 24) & 0xFF)
    return default


def rgb565(color):
    """Pack an ``(r, g, b[, a])`` tuple into a 16 bit RGB565 value."""
    r, g, b = color[0], color[1], color[2]
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def unpack565(value):
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


#: Lookup tables for :meth:`Canvas.to_rgb888`, which expands whole planes of
#: the framebuffer at once instead of walking it pixel by pixel.
_LITTLE_ENDIAN = sys.byteorder == "little"
_RED = bytes(((v >> 3) << 3) | (v >> 5) for v in range(256))
_GREEN_HIGH = bytes((v & 0x07) << 3 for v in range(256))
_GREEN_LOW = bytes(v >> 5 for v in range(256))
_GREEN = bytes(((v & 0x3F) << 2) | ((v & 0x3F) >> 4) for v in range(256))
_BLUE = bytes(((v & 0x1F) << 3) | ((v & 0x1F) >> 2) for v in range(256))


def mix(color_a, color_b, factor):
    """Linear interpolation between two ``(r, g, b, a)`` tuples."""
    factor = max(0.0, min(1.0, factor))
    return tuple(int(round(color_a[i] + (color_b[i] - color_a[i]) * factor))
                 for i in range(4))


# ---------------------------------------------------------------------------
# canvas
# ---------------------------------------------------------------------------

ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT = "left", "center", "right"


class Canvas(object):
    def __init__(self, width, height, background=(0, 0, 0, 255)):
        self.width = int(width)
        self.height = int(height)
        self.buf = array("H", [rgb565(background)]) * (self.width * self.height)
        self._clip = (0, 0, self.width, self.height)
        self._clip_stack = []

    # -- clipping ---------------------------------------------------------
    def push_clip(self, x, y, w, h):
        """Intersect the clip rectangle with ``x, y, w, h``."""
        self._clip_stack.append(self._clip)
        cx0, cy0, cx1, cy1 = self._clip
        nx0 = max(cx0, int(x))
        ny0 = max(cy0, int(y))
        nx1 = min(cx1, int(x) + int(w))
        ny1 = min(cy1, int(y) + int(h))
        self._clip = (nx0, ny0, max(nx0, nx1), max(ny0, ny1))
        return self._clip

    def pop_clip(self):
        if self._clip_stack:
            self._clip = self._clip_stack.pop()

    def reset_clip(self):
        self._clip = (0, 0, self.width, self.height)
        self._clip_stack = []

    # -- basic fills ------------------------------------------------------
    def clear(self, color=(0, 0, 0, 255)):
        value = rgb565(color)
        self.buf = array("H", [value]) * (self.width * self.height)

    def fill_rect(self, x, y, w, h, color):
        """Fill a rectangle, honouring the alpha channel of ``color``."""
        alpha = color[3] if len(color) > 3 else 255
        if alpha <= 0:
            return
        x0, y0, x1, y1 = self._clip
        px0 = max(x0, int(x))
        py0 = max(y0, int(y))
        px1 = min(x1, int(x) + int(w))
        py1 = min(y1, int(y) + int(h))
        if px1 <= px0 or py1 <= py0:
            return
        span = px1 - px0
        buf = self.buf
        width = self.width
        if alpha >= 255:
            row = array("H", [rgb565(color)]) * span
            for row_y in range(py0, py1):
                start = row_y * width + px0
                buf[start:start + span] = row
            return
        inv = 255 - alpha
        fr = (color[0] * alpha) // 255
        fg = (color[1] * alpha) // 255
        fb = (color[2] * alpha) // 255
        for row_y in range(py0, py1):
            base = row_y * width
            for px in range(base + px0, base + px1):
                dst = buf[px]
                dr = ((dst >> 11) & 0x1F) << 3
                dg = ((dst >> 5) & 0x3F) << 2
                db = (dst & 0x1F) << 3
                buf[px] = ((((fr + dr * inv // 255) & 0xF8) << 8)
                           | (((fg + dg * inv // 255) & 0xFC) << 3)
                           | ((fb + db * inv // 255) >> 3))

    def hline(self, x, y, w, color, thickness=1):
        self.fill_rect(x, y, w, thickness, color)

    def vline(self, x, y, h, color, thickness=1):
        self.fill_rect(x, y, thickness, h, color)

    def rect(self, x, y, w, h, color, thickness=1):
        """Draw a rectangle outline."""
        thickness = max(1, int(thickness))
        self.fill_rect(x, y, w, thickness, color)
        self.fill_rect(x, y + h - thickness, w, thickness, color)
        self.fill_rect(x, y + thickness, thickness, h - 2 * thickness, color)
        self.fill_rect(x + w - thickness, y + thickness, thickness, h - 2 * thickness, color)

    # -- rounded rectangles ----------------------------------------------
    def _round_spans(self, w, h, radius):
        """Per-row ``(left_inset, right_inset)`` for a rounded rectangle."""
        radius = max(0, min(int(radius), min(w, h) // 2))
        spans = [0] * h
        if radius <= 0:
            return spans
        for i in range(radius):
            dy = radius - i - 0.5
            dx = radius - (radius * radius - dy * dy) ** 0.5
            inset = int(round(dx))
            spans[i] = inset
            spans[h - 1 - i] = inset
        return spans

    def fill_round_rect(self, x, y, w, h, color, radius=0):
        w = int(w)
        h = int(h)
        if w <= 0 or h <= 0:
            return
        if radius <= 0:
            self.fill_rect(x, y, w, h, color)
            return
        spans = self._round_spans(w, h, radius)
        for row_y in range(h):
            inset = spans[row_y]
            self.fill_rect(x + inset, y + row_y, w - 2 * inset, 1, color)

    def round_rect(self, x, y, w, h, color, radius=0, thickness=1):
        w = int(w)
        h = int(h)
        thickness = max(1, int(thickness))
        if radius <= 0:
            self.rect(x, y, w, h, color, thickness)
            return
        outer = self._round_spans(w, h, radius)
        inner = self._round_spans(w - 2 * thickness, h - 2 * thickness,
                                  radius - thickness)
        for row_y in range(h):
            left = outer[row_y]
            right = w - outer[row_y]
            if thickness <= row_y < h - thickness:
                idx = row_y - thickness
                in_left = thickness + inner[idx]
                in_right = w - thickness - inner[idx]
                self.fill_rect(x + left, y + row_y, in_left - left, 1, color)
                self.fill_rect(x + in_right, y + row_y, right - in_right, 1, color)
            else:
                self.fill_rect(x + left, y + row_y, right - left, 1, color)

    def gradient_rect(self, x, y, w, h, color_a, color_b, vertical=True, radius=0):
        w = int(w)
        h = int(h)
        if w <= 0 or h <= 0:
            return
        spans = self._round_spans(w, h, radius) if radius > 0 else [0] * h
        if vertical:
            steps = max(1, h - 1)
            for row_y in range(h):
                color = mix(color_a, color_b, row_y / float(steps))
                inset = spans[row_y]
                self.fill_rect(x + inset, y + row_y, w - 2 * inset, 1, color)
        else:
            steps = max(1, w - 1)
            if radius > 0:
                # Draw column-wise but keep the rounded silhouette by
                # clipping each column against the row spans.
                for col in range(w):
                    color = mix(color_a, color_b, col / float(steps))
                    for row_y in range(h):
                        inset = spans[row_y]
                        if inset <= col < w - inset:
                            self.fill_rect(x + col, y + row_y, 1, 1, color)
            else:
                for col in range(w):
                    color = mix(color_a, color_b, col / float(steps))
                    self.fill_rect(x + col, y, 1, h, color)

    def fill_circle(self, cx, cy, radius, color):
        """Filled circle with anti-aliased edge."""
        radius = float(radius)
        if radius <= 0:
            return
        cx = float(cx)
        cy = float(cy)
        top = int(cy - radius - 1)
        bottom = int(cy + radius + 2)
        for py in range(top, bottom):
            dy = py + 0.5 - cy
            if abs(dy) > radius + 1:
                continue
            inner = radius * radius - dy * dy
            if inner <= 0:
                continue
            half = inner ** 0.5
            left = cx - half
            right = cx + half
            self.fill_rect(int(left + 1), py, int(right) - int(left + 1), 1, color)
            # Soften the two end pixels of the span.
            for edge, coverage in ((int(left), 1.0 - (left - int(left))),
                                   (int(right), right - int(right))):
                if coverage > 0.02:
                    faded = (color[0], color[1], color[2],
                             int((color[3] if len(color) > 3 else 255) * coverage))
                    self.fill_rect(edge, py, 1, 1, faded)

    def ring(self, cx, cy, radius, thickness, color):
        """Circle outline of the given thickness."""
        self.fill_circle(cx, cy, radius, color)
        inner = radius - max(1, thickness)
        if inner > 0:
            self.fill_circle(cx, cy, inner, (0, 0, 0, 0))

    def fill_polygon(self, points, color):
        """Scanline fill of a polygon given as ``[(x, y), ...]``."""
        if len(points) < 3:
            return
        ys = [point[1] for point in points]
        top = max(self._clip[1], int(min(ys)))
        bottom = min(self._clip[3], int(max(ys)) + 1)
        count = len(points)
        for py in range(top, bottom):
            scan = py + 0.5
            crossings = []
            for index in range(count):
                x0, y0 = points[index]
                x1, y1 = points[(index + 1) % count]
                if y0 == y1:
                    continue
                if (y0 <= scan < y1) or (y1 <= scan < y0):
                    crossings.append(x0 + (scan - y0) * (x1 - x0) / float(y1 - y0))
            if len(crossings) < 2:
                continue
            crossings.sort()
            for index in range(0, len(crossings) - 1, 2):
                left = crossings[index]
                right = crossings[index + 1]
                start = int(round(left))
                width = int(round(right)) - start
                if width > 0:
                    self.fill_rect(start, py, width, 1, color)

    def line(self, x0, y0, x1, y1, color, thickness=1):
        """Bresenham line; thickness is drawn as square dots."""
        x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
        if y0 == y1:
            self.fill_rect(min(x0, x1), y0, abs(x1 - x0) + 1, thickness, color)
            return
        if x0 == x1:
            self.fill_rect(x0, min(y0, y1), thickness, abs(y1 - y0) + 1, color)
            return
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.fill_rect(x0, y0, thickness, thickness, color)
            if x0 == x1 and y0 == y1:
                break
            err2 = 2 * err
            if err2 >= dy:
                err += dy
                x0 += sx
            if err2 <= dx:
                err += dx
                y0 += sy

    # -- text -------------------------------------------------------------
    def text_origin(self, font, text, x, w=None, align=ALIGN_LEFT):
        """Return the pen x position for ``text`` inside ``x .. x + w``."""
        if w is None or align == ALIGN_LEFT:
            return x
        text_width = font.measure(text)
        if align == ALIGN_CENTER:
            return x + (w - text_width) // 2
        if align == ALIGN_RIGHT:
            return x + w - text_width
        return x

    def draw_text(self, font, text, x, baseline, color):
        """Draw ``text`` with its baseline at ``baseline``.

        Returns the pen position after the last glyph.
        """
        if not text:
            return x
        alpha_scale = color[3] if len(color) > 3 else 255
        if alpha_scale <= 0:
            return x
        cx0, cy0, cx1, cy1 = self._clip
        buf = self.buf
        canvas_width = self.width
        fr = color[0]
        fg = color[1]
        fb = color[2]
        packed = rgb565(color)
        pen = int(x)
        baseline = int(baseline)
        for ch in text:
            glyph = font.glyph(ord(ch))
            if glyph is None:
                continue
            gx = pen + glyph.bearing_x
            gy = baseline - glyph.bearing_y
            if glyph.rows and gx < cx1 and gx + glyph.width > cx0 \
                    and gy < cy1 and gy + glyph.height > cy0:
                for row_index, row in enumerate(glyph.rows):
                    if row is None:
                        continue
                    py = gy + row_index
                    if py < cy0 or py >= cy1:
                        continue
                    start, data = row
                    row_base = py * canvas_width
                    px = gx + start
                    for value in data:
                        if px >= cx1:
                            break
                        if value and px >= cx0:
                            alpha = value if alpha_scale >= 255 else value * alpha_scale // 255
                            if alpha >= 250:
                                buf[row_base + px] = packed
                            elif alpha:
                                offset = row_base + px
                                dst = buf[offset]
                                inv = 255 - alpha
                                dr = ((dst >> 11) & 0x1F) << 3
                                dg = ((dst >> 5) & 0x3F) << 2
                                db = (dst & 0x1F) << 3
                                buf[offset] = (
                                    ((((fr * alpha + dr * inv) // 255) & 0xF8) << 8)
                                    | ((((fg * alpha + dg * inv) // 255) & 0xFC) << 3)
                                    | (((fb * alpha + db * inv) // 255) >> 3))
                        px += 1
            pen += glyph.advance
        return pen

    # -- bitmaps ----------------------------------------------------------
    def blit_sprite(self, x, y, sprite, opacity=255):
        """Draw an :class:`~.images.Sprite`.

        Opaque runs are copied with a slice assignment and only the few
        translucent pixels of a row go through the blend loop, which is what
        keeps cover art affordable on a low power box.
        """
        if opacity <= 0:
            return
        cx0, cy0, cx1, cy1 = self._clip
        x = int(x)
        y = int(y)
        buf = self.buf
        canvas_width = self.width
        for row_index, (start, opaque, partial) in enumerate(sprite.rows):
            py = y + row_index
            if py < cy0 or py >= cy1:
                continue
            row_base = py * canvas_width
            if opaque and opacity >= 255:
                left = x + start
                right = left + len(opaque)
                cut_left = max(0, cx0 - left)
                cut_right = max(0, right - cx1)
                if cut_left or cut_right:
                    if len(opaque) - cut_left - cut_right > 0:
                        target = row_base + left + cut_left
                        buf[target:target + len(opaque) - cut_left - cut_right] = \
                            opaque[cut_left:len(opaque) - cut_right]
                else:
                    target = row_base + left
                    buf[target:target + len(opaque)] = opaque
            elif opaque:
                for offset in range(len(opaque)):
                    px = x + start + offset
                    if px < cx0 or px >= cx1:
                        continue
                    value = opaque[offset]
                    self._blend_pixel(row_base + px,
                                      ((value >> 11) & 0x1F) << 3,
                                      ((value >> 5) & 0x3F) << 2,
                                      (value & 0x1F) << 3, opacity)
            for px_offset, r, g, b, alpha in partial:
                px = x + px_offset
                if px < cx0 or px >= cx1:
                    continue
                if opacity < 255:
                    alpha = alpha * opacity // 255
                if alpha:
                    self._blend_pixel(row_base + px, r, g, b, alpha)

    def _blend_pixel(self, offset, r, g, b, alpha):
        buf = self.buf
        if alpha >= 255:
            buf[offset] = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            return
        dst = buf[offset]
        inv = 255 - alpha
        dr = ((dst >> 11) & 0x1F) << 3
        dg = ((dst >> 5) & 0x3F) << 2
        db = (dst & 0x1F) << 3
        buf[offset] = (((((r * alpha + dr * inv) // 255) & 0xF8) << 8)
                       | ((((g * alpha + dg * inv) // 255) & 0xFC) << 3)
                       | (((b * alpha + db * inv) // 255) >> 3))

    def blit_canvas(self, other, x, y):
        """Copy another canvas in, row by row (no alpha)."""
        cx0, cy0, cx1, cy1 = self._clip
        x = int(x)
        y = int(y)
        sx0 = max(0, cx0 - x)
        sy0 = max(0, cy0 - y)
        sx1 = min(other.width, cx1 - x)
        sy1 = min(other.height, cy1 - y)
        if sx1 <= sx0 or sy1 <= sy0:
            return
        span = sx1 - sx0
        for row in range(sy0, sy1):
            src = row * other.width + sx0
            dst = (y + row) * self.width + x + sx0
            self.buf[dst:dst + span] = other.buf[src:src + span]

    # -- output -----------------------------------------------------------
    def rotated(self, degrees):
        """Return a new canvas rotated clockwise by 0/90/180/270 degrees."""
        degrees = int(degrees) % 360
        if degrees == 0:
            return self
        if degrees == 180:
            out = Canvas(self.width, self.height)
            out.buf = self.buf[::-1]
            return out
        out = Canvas(self.height, self.width)
        width = self.width
        height = self.height
        src = self.buf
        dst = out.buf
        if degrees == 90:
            # source row y becomes destination column (height - 1 - y)
            for y in range(height):
                row = src[y * width:(y + 1) * width]
                col = height - 1 - y
                dst[col:col + height * width:height] = row
        else:  # 270
            for y in range(height):
                row = src[y * width:(y + 1) * width]
                row.reverse()
                col = y
                dst[col:col + height * width:height] = row
        return out

    def to_bytes(self):
        """Native little endian RGB565 bytes, ready for the AX206."""
        return self.buf.tobytes()

    def to_rgb888(self):
        """Expand to plain RGB bytes (used by the PNG preview writer).

        Done with whole-buffer byte operations rather than a per-pixel loop:
        every preview the web editor draws goes through here, and on a low
        power box the loop version cost more than the rendering did.  The
        two bytes of a pixel are split into planes, each plane is expanded
        through a 256 entry table, and the two halves of the green channel
        are merged with a single big-integer ``or`` before being interleaved
        back into RGB triplets.
        """
        data = self.buf.tobytes()
        high, low = (data[1::2], data[0::2]) if _LITTLE_ENDIAN \
            else (data[0::2], data[1::2])
        count = len(high)
        if not count:
            return b""
        # Green straddles both bytes: the top three bits sit in the high
        # byte, the bottom three in the low one.
        green = (int.from_bytes(high.translate(_GREEN_HIGH), "big")
                 | int.from_bytes(low.translate(_GREEN_LOW), "big"))
        out = bytearray(count * 3)
        out[0::3] = high.translate(_RED)
        out[1::3] = green.to_bytes(count, "big").translate(_GREEN)
        out[2::3] = low.translate(_BLUE)
        return bytes(out)
