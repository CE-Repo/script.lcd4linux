"""Widgets a layout can place on a page.

Every widget is created once when the layout is loaded and then rendered on
each frame, so widgets can keep animation state (scroll offsets, graph
history) between frames.
"""

import math
import time

from . import canvas as canvas_module
from . import faicons
from . import images as images_module
from . import svgpath
from . import tokens
from .canvas import Canvas, parse_color
from .logger import debug

REGISTRY = {}

#: A box bigger than this is drawn upright even when it asks to be
#: turned: freeing and rotating it costs a pass per pixel, and at that
#: size it would be the whole frame budget of a low power box.
ROTATION_LIMIT = 640 * 640


def register(name):
    def decorator(cls):
        REGISTRY[name] = cls
        cls.type_name = name
        return cls
    return decorator


def resolve_length(value, reference, default=0):
    """Turn ``40``, ``"50%"`` or ``"-10"`` into pixels."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(round(value))
    text = str(value).strip()
    if not text:
        return default
    if text.endswith("%"):
        try:
            return int(round(float(text[:-1]) * reference / 100.0))
        except ValueError:
            return default
    try:
        return int(round(float(text)))
    except ValueError:
        return default


class RenderContext(object):
    """State handed to every widget while a frame is drawn."""

    def __init__(self, provider, fonts, images, width, height, now=None,
                 smooth_images=True):
        self.provider = provider
        self.fonts = fonts
        self.images = images
        self.width = width
        self.height = height
        self.now = now if now is not None else time.time()
        self.smooth_images = smooth_images
        self.accent = None

    def text(self, template):
        return tokens.expand(template, self.provider)

    def number(self, template, default=0.0):
        return tokens.number(template, self.provider, default)

    def visible(self, condition):
        return tokens.evaluate(condition, self.provider)

    def color(self, value, default=(255, 255, 255, 255)):
        """Resolve a colour, expanding tokens and the ``accent`` keyword."""
        if value is None:
            return default
        if isinstance(value, str):
            text = value.strip()
            if text.lower() == "accent":
                return self.accent or default
            if "${" in text:
                text = tokens.expand(text, self.provider)
            return parse_color(text, default)
        return parse_color(value, default)


class Widget(object):
    """Base class: geometry, visibility and shared helpers."""

    type_name = "widget"

    def __init__(self, spec, layout):
        self.spec = spec or {}
        self.layout = layout
        self.name = self.spec.get("name", "")
        self.condition = self.spec.get("condition") or self.spec.get("visible")
        self.opacity = self.spec.get("opacity", 100)
        #: The last turned picture and what it was made from; a rotated
        #: widget usually draws the same thing again next frame.
        self._turn_cache = None

    # -- geometry ---------------------------------------------------------
    def geometry(self, context):
        x = resolve_length(self.spec.get("x", 0), context.width)
        y = resolve_length(self.spec.get("y", 0), context.height)
        # Negative coordinates are measured from the right/bottom edge.
        if x < 0:
            x += context.width
        if y < 0:
            y += context.height
        width = resolve_length(self.spec.get("w", self.spec.get("width")),
                               context.width, context.width - x)
        height = resolve_length(self.spec.get("h", self.spec.get("height")),
                                context.height, context.height - y)
        return x, y, width, height

    def alpha_of(self, color, context):
        opacity = self.opacity
        if isinstance(opacity, str):
            opacity = context.number(opacity, 100)
        opacity = max(0, min(100, int(opacity)))
        if opacity >= 100:
            return color
        return (color[0], color[1], color[2],
                (color[3] if len(color) > 3 else 255) * opacity // 100)

    # -- rendering --------------------------------------------------------
    def is_visible(self, context):
        if self.condition is None:
            return True
        return context.visible(self.condition)

    def render(self, canvas, context):
        raise NotImplementedError

    def draw(self, canvas, context):
        if not self.is_visible(context):
            return
        try:
            angle = self.angle_of(context)
            if angle:
                self.render_turned(canvas, context, angle)
            else:
                self.render(canvas, context)
        except Exception as error:
            debug("widget %s (%s) failed: %s" % (self.name, self.type_name, error))

    # -- rotation ---------------------------------------------------------
    def angle_of(self, context):
        """The ``angle`` of this widget in degrees clockwise, 0 to 360."""
        value = self.spec.get("angle")
        if value is None:
            value = self.spec.get("rotate", self.spec.get("rotation"))
        if value is None:
            return 0.0
        if isinstance(value, str):
            if not value.strip():
                return 0.0
            value = context.number(value, 0.0)
        try:
            angle = float(value) % 360.0
        except (TypeError, ValueError):
            return 0.0
        return 0.0 if angle < 0.05 or angle > 359.95 else angle

    def render_turned(self, canvas, context, angle):
        """Draw this widget turned by ``angle`` degrees about its centre.

        The framebuffer holds no alpha, so the widget is drawn twice into
        offscreen sheets - once over black, once over white - and what the
        two have to say about each other is turned back into an RGBA
        picture (see :func:`~.canvas.extract_rgba`).  That picture is
        rotated and blitted, so a turned element sits over whatever is
        behind it exactly as an upright one does, anti-aliased edges
        included.

        Only the widget's own box is taken along: anything it draws outside
        that box - a long ``line`` reaching elsewhere, say - is cut off.
        """
        x, y, width, height = self.geometry(context)
        if width < 1 or height < 1:
            return
        left = max(0, x)
        top = max(0, y)
        right = max(left + 1, x + width)
        bottom = max(top + 1, y + height)
        if (right - left) * (bottom - top) > ROTATION_LIMIT:
            self.render(canvas, context)          # too big to be worth it
            return
        # The sheets cover the display plus whatever of the box hangs over
        # its right or bottom edge, so a turn can bring that part back in.
        sheet_width = max(canvas.width, right)
        sheet_height = max(canvas.height, bottom)
        region = (left, top, right - left, bottom - top)

        on_black = Canvas(sheet_width, sheet_height, (0, 0, 0, 255))
        on_black.push_clip(*region)
        self.render(on_black, context)
        on_white = Canvas(sheet_width, sheet_height, (255, 255, 255, 255))
        on_white.push_clip(*region)
        self.render(on_white, context)

        smooth = self.spec.get("anglesmooth", self.spec.get("rotatesmooth", True))
        signature = (angle, region, bool(smooth),
                     canvas_module.region_bytes(on_black, on_white, *region))
        cached = self._turn_cache
        if cached is not None and cached[0] == signature:
            sprite = cached[1]
        else:
            upright = images_module.Image(
                region[2], region[3],
                canvas_module.extract_rgba(on_black, on_white, *region))
            sprite = upright.turned(angle, bool(smooth)).sprite()
            self._turn_cache = (signature, sprite)
        # A turn is about the middle of the box, so the bigger picture the
        # corners need is hung around that same middle.
        canvas.blit_sprite(int(round(left + (region[2] - sprite.width) / 2.0)),
                           int(round(top + (region[3] - sprite.height) / 2.0)),
                           sprite)


# ---------------------------------------------------------------------------
# simple shapes
# ---------------------------------------------------------------------------

@register("rect")
class RectWidget(Widget):
    def render(self, canvas, context):
        x, y, width, height = self.geometry(context)
        radius = resolve_length(self.spec.get("radius", 0), min(width, height))
        fill = self.spec.get("color", self.spec.get("fill"))
        gradient = self.spec.get("gradient")
        if fill is not None or gradient:
            start = self.alpha_of(context.color(fill, (255, 255, 255, 255)), context)
            if gradient:
                end = self.alpha_of(context.color(gradient, start), context)
                vertical = str(self.spec.get("direction", "vertical")).startswith("v")
                canvas.gradient_rect(x, y, width, height, start, end, vertical, radius)
            else:
                canvas.fill_round_rect(x, y, width, height, start, radius)
        border = self.spec.get("border", 0)
        if border:
            border_color = self.alpha_of(
                context.color(self.spec.get("bordercolor"), (255, 255, 255, 255)),
                context)
            canvas.round_rect(x, y, width, height, border_color, radius, int(border))


@register("line")
class LineWidget(Widget):
    def render(self, canvas, context):
        x, y, width, height = self.geometry(context)
        color = self.alpha_of(context.color(self.spec.get("color"),
                                            (255, 255, 255, 255)), context)
        thickness = int(self.spec.get("thickness", 1))
        x2 = self.spec.get("x2")
        y2 = self.spec.get("y2")
        if x2 is None and y2 is None:
            # A plain separator fills its own box: a wide flat box draws a
            # horizontal rule as thick as the box, a tall narrow one a
            # vertical rule. "thickness" only raises that minimum.
            if height <= width:
                canvas.fill_rect(x, y, width, max(thickness, height), color)
            else:
                canvas.fill_rect(x, y, max(thickness, width), height, color)
            return
        end_x = resolve_length(x2, context.width, x + width)
        end_y = resolve_length(y2, context.height, y)
        canvas.line(x, y, end_x, end_y, color, thickness)


@register("circle")
class CircleWidget(Widget):
    def render(self, canvas, context):
        x, y, width, height = self.geometry(context)
        radius = resolve_length(self.spec.get("radius"), min(width, height),
                                min(width, height) // 2)
        cx = x + width / 2.0
        cy = y + height / 2.0
        color = self.alpha_of(context.color(self.spec.get("color"),
                                            (255, 255, 255, 255)), context)
        thickness = int(self.spec.get("thickness", 0))
        if thickness > 0:
            canvas.ring(cx, cy, radius, thickness, color)
        else:
            canvas.fill_circle(cx, cy, radius, color)


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------

@register("text")
class TextWidget(Widget):
    def __init__(self, spec, layout):
        Widget.__init__(self, spec, layout)
        self._scroll_state = {}

    def font(self, context):
        family = self.spec.get("font", self.layout.default_font)
        if self.spec.get("bold") and not family.endswith("-bold"):
            family += "-bold"
        size = int(self.spec.get("size", self.layout.default_size))
        return context.fonts.get(family, size)

    def render(self, canvas, context):
        x, y, width, height = self.geometry(context)
        font = self.font(context)
        text = context.text(self.spec.get("text", ""))
        if not text and not self.spec.get("showempty"):
            return

        padding = int(self.spec.get("padding", 0))
        x += padding
        y += padding
        width -= 2 * padding
        height -= 2 * padding
        if width <= 0:
            return

        background = self.spec.get("background")
        if background is not None:
            radius = resolve_length(self.spec.get("radius", 0), min(width, height))
            canvas.fill_round_rect(x - padding, y - padding,
                                   width + 2 * padding, height + 2 * padding,
                                   self.alpha_of(context.color(background), context),
                                   radius)

        color = self.alpha_of(context.color(self.spec.get("color"),
                                            self.layout.default_color), context)
        align = str(self.spec.get("align", "left")).lower()
        valign = str(self.spec.get("valign", "top")).lower()
        line_spacing = int(self.spec.get("linespacing", 0))
        line_height = font.line_height + line_spacing

        if self.spec.get("wrap"):
            max_lines = int(self.spec.get("lines", 0)) or max(1, height // line_height)
            lines = font.wrap(text, width)[:max_lines]
            if len(lines) == max_lines:
                lines[-1] = font.ellipsize(lines[-1], width)
        else:
            lines = [text]

        block_height = len(lines) * line_height
        if valign in ("center", "middle"):
            first_baseline = y + (height - block_height) // 2 + font.ascent
        elif valign == "bottom":
            first_baseline = y + height - block_height + font.ascent
        else:
            first_baseline = y + font.ascent

        scroll = str(self.spec.get("scroll", "none")).lower()
        canvas.push_clip(x, y, width, height)
        try:
            for index, line in enumerate(lines):
                baseline = first_baseline + index * line_height
                if len(lines) == 1 and scroll not in ("none", "", "false"):
                    self._draw_scrolling(canvas, context, font, line, x, baseline,
                                         width, color, scroll)
                else:
                    drawn = line if self.spec.get("wrap") else font.ellipsize(line, width)
                    pen = canvas.text_origin(font, drawn, x, width, align)
                    self._draw_with_effects(canvas, context, font, drawn, pen,
                                            baseline, color)
        finally:
            canvas.pop_clip()

    def _draw_with_effects(self, canvas, context, font, text, x, baseline, color):
        shadow = self.spec.get("shadow")
        if shadow:
            offset = int(self.spec.get("shadowoffset", 2))
            shadow_color = context.color(
                shadow if isinstance(shadow, str) else self.spec.get("shadowcolor"),
                (0, 0, 0, 160))
            canvas.draw_text(font, text, x + offset, baseline + offset, shadow_color)
        outline = self.spec.get("outline")
        if outline:
            outline_color = context.color(
                outline if isinstance(outline, str) else "#000000", (0, 0, 0, 200))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                canvas.draw_text(font, text, x + dx, baseline + dy, outline_color)
        canvas.draw_text(font, text, x, baseline, color)

    def _draw_scrolling(self, canvas, context, font, text, x, baseline, width,
                        color, mode):
        text_width = font.measure(text)
        if text_width <= width:
            align = str(self.spec.get("align", "left")).lower()
            pen = canvas.text_origin(font, text, x, width, align)
            self._draw_with_effects(canvas, context, font, text, pen, baseline, color)
            return

        speed = float(self.spec.get("scrollspeed", 30))  # pixels per second
        pause = float(self.spec.get("scrollpause", 2.0))
        state = self._scroll_state
        if state.get("text") != text:
            state.clear()
            state["text"] = text
            state["start"] = context.now

        elapsed = max(0.0, context.now - state.get("start", context.now))
        if mode in ("marquee", "loop", "auto"):
            gap = int(self.spec.get("scrollgap", 40))
            cycle = (text_width + gap) / speed if speed > 0 else 1.0
            offset = (elapsed % cycle) * speed
            self._draw_with_effects(canvas, context, font, text,
                                    int(x - offset), baseline, color)
            self._draw_with_effects(canvas, context, font, text,
                                    int(x - offset + text_width + gap), baseline,
                                    color)
        else:  # bounce / pingpong
            travel = text_width - width
            run = travel / speed if speed > 0 else 1.0
            cycle = 2 * (run + pause)
            position = elapsed % cycle
            if position < pause:
                offset = 0.0
            elif position < pause + run:
                offset = (position - pause) * speed
            elif position < 2 * pause + run:
                offset = travel
            else:
                offset = travel - (position - 2 * pause - run) * speed
            self._draw_with_effects(canvas, context, font, text,
                                    int(x - offset), baseline, color)


# ---------------------------------------------------------------------------
# progress and levels
# ---------------------------------------------------------------------------

@register("progress")
class ProgressWidget(Widget):
    def render(self, canvas, context):
        x, y, width, height = self.geometry(context)
        minimum = context.number(self.spec.get("min", 0), 0.0)
        maximum = context.number(self.spec.get("max", 100), 100.0)
        value = context.number(self.spec.get("value", "${player.percent}"), 0.0)
        span = maximum - minimum
        fraction = 0.0 if span == 0 else (value - minimum) / span
        fraction = max(0.0, min(1.0, fraction))

        vertical = str(self.spec.get("orientation", "horizontal")).startswith("v")
        radius = resolve_length(self.spec.get("radius", 0), min(width, height))
        background = self.spec.get("background", "#20242e")
        if background is not None:
            canvas.fill_round_rect(x, y, width, height,
                                   self.alpha_of(context.color(background), context),
                                   radius)

        color = self.alpha_of(context.color(self.spec.get("color"), (23, 178, 226, 255)),
                              context)
        gradient = self.spec.get("gradient")
        style = str(self.spec.get("style", "bar")).lower()

        if style == "segments":
            self._draw_segments(canvas, context, x, y, width, height, fraction,
                                color, vertical)
        else:
            if vertical:
                filled = int(round(height * fraction))
                if filled > 0:
                    if gradient:
                        canvas.gradient_rect(x, y + height - filled, width, filled,
                                             self.alpha_of(context.color(gradient, color), context),
                                             color, True, radius)
                    else:
                        canvas.fill_round_rect(x, y + height - filled, width, filled,
                                               color, radius)
            else:
                filled = int(round(width * fraction))
                if filled > 0:
                    if gradient:
                        canvas.gradient_rect(x, y, filled, height, color,
                                             self.alpha_of(context.color(gradient, color), context),
                                             False, radius)
                    else:
                        canvas.fill_round_rect(x, y, filled, height, color, radius)

        border = int(self.spec.get("border", 0))
        if border:
            canvas.round_rect(x, y, width, height,
                              self.alpha_of(context.color(self.spec.get("bordercolor"),
                                                          (90, 96, 110, 255)), context),
                              radius, border)

        knob = self.spec.get("knob")
        if knob:
            knob_color = self.alpha_of(context.color(
                knob if isinstance(knob, str) else self.spec.get("knobcolor"),
                (255, 255, 255, 255)), context)
            knob_radius = float(self.spec.get("knobsize", max(3, height // 2 + 2)))
            if vertical:
                canvas.fill_circle(x + width / 2.0,
                                   y + height - height * fraction, knob_radius,
                                   knob_color)
            else:
                canvas.fill_circle(x + width * fraction, y + height / 2.0,
                                   knob_radius, knob_color)

    def _draw_segments(self, canvas, context, x, y, width, height, fraction,
                       color, vertical):
        count = max(1, int(self.spec.get("segments", 20)))
        gap = int(self.spec.get("gap", 2))
        inactive = self.spec.get("inactivecolor")
        inactive_color = context.color(inactive, (40, 44, 54, 255)) if inactive else None
        lit = int(round(count * fraction))
        if vertical:
            size = max(1, (height - gap * (count - 1)) // count)
            for index in range(count):
                top = y + height - (index + 1) * size - index * gap
                shade = color
                if index >= lit:
                    if inactive_color is None:
                        continue
                    shade = inactive_color
                canvas.fill_rect(x, top, width, size, shade)
        else:
            size = max(1, (width - gap * (count - 1)) // count)
            for index in range(count):
                left = x + index * (size + gap)
                shade = color
                if index >= lit:
                    if inactive_color is None:
                        continue
                    shade = inactive_color
                canvas.fill_rect(left, y, size, height, shade)


@register("graph")
class GraphWidget(Widget):
    """A rolling sparkline of any numeric token."""

    def __init__(self, spec, layout):
        Widget.__init__(self, spec, layout)
        self.history = []
        self._last_sample = 0.0

    def render(self, canvas, context):
        x, y, width, height = self.geometry(context)
        interval = float(self.spec.get("interval", 1.0))
        points = max(2, int(self.spec.get("points", 60)))
        if context.now - self._last_sample >= interval or not self.history:
            self.history.append(context.number(self.spec.get("value", 0), 0.0))
            self._last_sample = context.now
            if len(self.history) > points:
                del self.history[:len(self.history) - points]

        minimum = context.number(self.spec.get("min", 0), 0.0)
        maximum = context.number(self.spec.get("max", 100), 100.0)
        span = (maximum - minimum) or 1.0
        color = self.alpha_of(context.color(self.spec.get("color"),
                                            (23, 178, 226, 255)), context)
        background = self.spec.get("background")
        if background is not None:
            canvas.fill_rect(x, y, width, height,
                             self.alpha_of(context.color(background), context))

        step = width / float(points - 1)
        fill = self.spec.get("fill")
        fill_color = self.alpha_of(context.color(fill, color), context) if fill else None
        count = len(self.history)
        offset = points - count
        columns = [int(x + (offset + index) * step) for index in range(count)]
        thickness = int(self.spec.get("thickness", 1))
        previous = None
        for index, sample in enumerate(self.history):
            fraction = max(0.0, min(1.0, (sample - minimum) / span))
            px = columns[index]
            py = int(y + height - fraction * height)
            if fill_color is not None:
                # Fill up to the next sample so translucent columns never
                # overlap and darken each other.
                right = columns[index + 1] if index + 1 < count else int(x + width)
                canvas.fill_rect(px, py, max(1, right - px), y + height - py,
                                 fill_color)
            if previous is not None:
                canvas.line(previous[0], previous[1], px, py, color, thickness)
            previous = (px, py)


# ---------------------------------------------------------------------------
# images and icons
# ---------------------------------------------------------------------------

@register("image")
class ImageWidget(Widget):
    def __init__(self, spec, layout):
        Widget.__init__(self, spec, layout)
        self._cached_key = None
        self._cached_image = None
        self._cached_final = False

    def render(self, canvas, context):
        x, y, width, height = self.geometry(context)
        source = context.text(self.spec.get("src", self.spec.get("path", "")))
        if not source:
            source = context.text(self.spec.get("fallback", ""))
        if not source:
            return
        fit = str(self.spec.get("fit", "contain")).lower()
        radius = resolve_length(self.spec.get("radius", 0), min(width, height))
        smooth = context.smooth_images
        key = (source, width, height, fit, radius, smooth)
        # Held on to only once it is the finished picture.  Until then the
        # widget asks again on every frame - which is what lets a rough
        # version be replaced by the sharp one, and what makes a picture
        # that is still being fetched turn up on its own.  The cache sees
        # to it that asking is cheap and not a re-read per frame.
        if key != self._cached_key or not self._cached_final:

            def prepare(raw, rough=False):
                prepared = raw.fitted(width, height, fit, smooth and not rough)
                if radius:
                    prepared = prepared.rounded(radius)
                return prepared

            # The decoder only has to deliver what this widget draws.
            # Asking for twice the box, as this used to, pushed the scaled
            # JPEG decoder a step finer and cost roughly three times as long
            # for a picture that looks the same once it has been fitted.
            self._cached_image, self._cached_final = \
                context.images.progressive(
                    key, source,
                    images_module.decode_size(width, height, fit),
                    prepare, lambda raw: prepare(raw, True))
            self._cached_key = key
        image = self._cached_image
        if image is None:
            return
        align = str(self.spec.get("align", "center")).lower()
        if align == "left":
            draw_x = x
        elif align == "right":
            draw_x = x + width - image.width
        else:
            draw_x = x + (width - image.width) // 2
        valign = str(self.spec.get("valign", "center")).lower()
        if valign == "top":
            draw_y = y
        elif valign == "bottom":
            draw_y = y + height - image.height
        else:
            draw_y = y + (height - image.height) // 2
        opacity = self.opacity
        if isinstance(opacity, str):
            opacity = context.number(opacity, 100)
        canvas.blit_sprite(draw_x, draw_y, image.sprite(),
                           max(0, min(255, int(opacity) * 255 // 100)))


ICONS = {
    "play": (("poly", ((0.25, 0.15), (0.85, 0.5), (0.25, 0.85))),),
    "pause": (("rect", (0.24, 0.15, 0.19, 0.7)), ("rect", (0.57, 0.15, 0.19, 0.7))),
    "stop": (("rect", (0.2, 0.2, 0.6, 0.6)),),
    "next": (("poly", ((0.15, 0.18), (0.62, 0.5), (0.15, 0.82))),
             ("rect", (0.68, 0.18, 0.14, 0.64))),
    "previous": (("poly", ((0.85, 0.18), (0.38, 0.5), (0.85, 0.82))),
                 ("rect", (0.18, 0.18, 0.14, 0.64))),
    "music": (("rect", (0.42, 0.12, 0.1, 0.55)), ("rect", (0.42, 0.12, 0.34, 0.11)),
              ("circle", (0.32, 0.72, 0.16)), ("circle", (0.66, 0.62, 0.16))),
    "movie": (("rect", (0.12, 0.24, 0.62, 0.52)),
              ("poly", ((0.78, 0.38), (0.92, 0.26), (0.92, 0.74), (0.78, 0.62)))),
    "tv": (("rect", (0.1, 0.24, 0.8, 0.52)), ("rect", (0.42, 0.76, 0.16, 0.08))),
    "speaker": (("rect", (0.16, 0.38, 0.2, 0.24)),
                ("poly", ((0.36, 0.38), (0.62, 0.16), (0.62, 0.84), (0.36, 0.62)))),
    "mute": (("rect", (0.12, 0.38, 0.18, 0.24)),
             ("poly", ((0.3, 0.38), (0.54, 0.16), (0.54, 0.84), (0.3, 0.62))),
             ("rect", (0.62, 0.46, 0.3, 0.08))),
    "clock": (("ring", (0.5, 0.5, 0.42, 0.08)), ("rect", (0.47, 0.24, 0.06, 0.3)),
              ("rect", (0.47, 0.47, 0.26, 0.06))),
    "cpu": (("rect", (0.24, 0.24, 0.52, 0.52)), ("rect", (0.38, 0.38, 0.24, 0.24)),
            ("rect", (0.34, 0.08, 0.06, 0.16)), ("rect", (0.6, 0.08, 0.06, 0.16)),
            ("rect", (0.34, 0.76, 0.06, 0.16)), ("rect", (0.6, 0.76, 0.06, 0.16))),
    "temp": (("rect", (0.42, 0.12, 0.16, 0.5)), ("circle", (0.5, 0.72, 0.2))),
    "star": (("poly", ((0.5, 0.06), (0.62, 0.38), (0.96, 0.38), (0.68, 0.58),
                       (0.79, 0.92), (0.5, 0.71), (0.21, 0.92), (0.32, 0.58),
                       (0.04, 0.38), (0.38, 0.38))),),
    "heart": (("circle", (0.32, 0.34, 0.24)), ("circle", (0.68, 0.34, 0.24)),
              ("poly", ((0.08, 0.42), (0.92, 0.42), (0.5, 0.94)))),
    "folder": (("rect", (0.08, 0.28, 0.84, 0.52)), ("rect", (0.08, 0.2, 0.36, 0.1))),
    "wifi": (("circle", (0.5, 0.78, 0.09)), ("ring", (0.5, 0.8, 0.32, 0.09)),
             ("ring", (0.5, 0.8, 0.56, 0.09))),
    "shuffle": (("poly", ((0.6, 0.12), (0.92, 0.3), (0.6, 0.48))),
                ("poly", ((0.6, 0.52), (0.92, 0.7), (0.6, 0.88))),
                ("rect", (0.08, 0.26, 0.5, 0.08)),
                ("rect", (0.08, 0.66, 0.5, 0.08))),
    "repeat": (("ring", (0.5, 0.5, 0.4, 0.09)),
               ("poly", ((0.62, 0.02), (0.92, 0.18), (0.62, 0.34)))),
    "disc": (("circle", (0.5, 0.5, 0.46)),),
    "dot": (("circle", (0.5, 0.5, 0.3)),),
}


# ---------------------------------------------------------------------------
# Font Awesome outlines
# ---------------------------------------------------------------------------

#: Rasterised icons, keyed by outline, size, colour and trimming.  An icon
#: costs a few hundred polygon edges to fill, which is fine once but not
#: four times a second, so the finished picture is what gets kept.
_RASTERS = {}
_RASTER_LIMIT = 48

#: Vertical samples per pixel row.  Four is the point where a 16 pixel glyph
#: stops looking ragged; more is not visible on a 480x320 panel.
_SAMPLES = 4


def _raster(outline, width, height, color, trim):
    """An RGBA :class:`~lcd4linux.images.Image` of one icon, cached."""
    key = (outline.style, outline.name, width, height, color, trim)
    entry = _RASTERS.get(key)
    if entry is not None:
        entry[1] = time.time()
        return entry[0]
    # Curves are flattened to roughly a third of a pixel at the size the
    # icon is actually drawn, so a big icon stays round and a small one
    # does not pay for points nobody can see.
    per_pixel = max(outline.width / float(max(1, width)),
                    outline.height / float(max(1, height)))
    paths = svgpath.parse(outline.data, max(0.05, per_pixel * 0.35))
    box = svgpath.bounds(paths) if trim else (0.0, 0.0, outline.width,
                                              outline.height)
    if box is None:
        return None
    box_width = max(1e-6, box[2] - box[0])
    box_height = max(1e-6, box[3] - box[1])
    scale = min(width / box_width, height / box_height)
    offset_x = (width - box_width * scale) / 2.0 - box[0] * scale
    offset_y = (height - box_height * scale) / 2.0 - box[1] * scale
    mask = svgpath.mask(svgpath.transform(paths, scale, scale, offset_x,
                                          offset_y),
                        width, height, _SAMPLES, outline.even_odd)
    red, green, blue = color[0], color[1], color[2]
    alpha = color[3] if len(color) > 3 else 255
    pixels = bytearray(width * height * 4)
    for index in range(width * height):
        coverage = mask[index]
        if not coverage:
            continue
        base = index * 4
        pixels[base] = red
        pixels[base + 1] = green
        pixels[base + 2] = blue
        pixels[base + 3] = coverage if alpha >= 255 else coverage * alpha // 255
    image = images_module.Image(width, height, pixels)
    if len(_RASTERS) >= _RASTER_LIMIT:
        for old, _ in sorted(_RASTERS.items(),
                             key=lambda item: item[1][1])[:8]:
            _RASTERS.pop(old, None)
    _RASTERS[key] = [image, time.time()]
    return image


def clear_raster_cache():
    """Drop the rasterised icons, e.g. after the icon cache was emptied."""
    _RASTERS.clear()


@register("icon")
class IconWidget(Widget):
    """A builtin shape or any icon from the Font Awesome Free set.

    The two dozen shapes in :data:`ICONS` are drawn from primitives and
    always available.  Everything else is looked up in the icon cache, which
    fills itself from the network the first time an icon is used and is read
    from disk from then on.
    """

    def render(self, canvas, context):
        x, y, width, height = self.geometry(context)
        name = context.text(str(self.spec.get("icon", self.spec.get("name", "play"))))
        name = name.strip()
        color = self.alpha_of(context.color(self.spec.get("color"),
                                            (255, 255, 255, 255)), context)
        shapes = ICONS.get(name.lower())
        if not shapes:
            self._render_outline(canvas, context, name, x, y, width, height,
                                 color)
            return
        size = min(width, height)
        offset_x = x + (width - size) / 2.0
        offset_y = y + (height - size) / 2.0
        for shape, values in shapes:
            if shape == "rect":
                canvas.fill_rect(offset_x + values[0] * size,
                                 offset_y + values[1] * size,
                                 max(1, values[2] * size), max(1, values[3] * size),
                                 color)
            elif shape == "poly":
                canvas.fill_polygon([(offset_x + px * size, offset_y + py * size)
                                     for px, py in values], color)
            elif shape == "circle":
                canvas.fill_circle(offset_x + values[0] * size,
                                   offset_y + values[1] * size,
                                   values[2] * size / 2.0, color)
            elif shape == "ring":
                canvas.ring(offset_x + values[0] * size,
                            offset_y + values[1] * size,
                            values[2] * size / 2.0,
                            max(1, int(values[3] * size)), color)

    def _render_outline(self, canvas, context, name, x, y, width, height,
                        color):
        """Draw a Font Awesome icon, if the cache already holds it.

        Asking for one that is not cached yet queues the download and draws
        nothing this frame; the icon turns up a moment later without the
        panel ever waiting for the network.
        """
        if not name or width < 1 or height < 1:
            return
        style = self.spec.get("style")
        style = context.text(str(style)).strip().lower() if style else None
        outline = faicons.request(name, style or None)
        if outline is None:
            return
        size = int(min(width, height))
        if size < 1:
            return
        image = _raster(outline, size, size, tuple(color[:3]),
                        bool(self.spec.get("trim", False)))
        if image is None:
            return
        alpha = color[3] if len(color) > 3 else 255
        canvas.blit_sprite(int(x + (width - size) // 2),
                           int(y + (height - size) // 2),
                           image.sprite(), alpha)


@register("analogclock")
class AnalogClockWidget(Widget):
    def render(self, canvas, context):
        x, y, width, height = self.geometry(context)
        size = min(width, height)
        cx = x + width / 2.0
        cy = y + height / 2.0
        radius = size / 2.0 - 1
        face = self.spec.get("face")
        if face is not None:
            canvas.fill_circle(cx, cy, radius, context.color(face, (20, 24, 32, 255)))
        rim = self.spec.get("rim")
        if rim is not None:
            canvas.ring(cx, cy, radius, int(self.spec.get("rimwidth", 2)),
                        context.color(rim, (90, 96, 110, 255)))
        color = self.alpha_of(context.color(self.spec.get("color"),
                                            (255, 255, 255, 255)), context)
        if self.spec.get("ticks", True):
            tick_color = context.color(self.spec.get("tickcolor"), (120, 128, 145, 255))
            for index in range(12):
                angle = index * math.pi / 6.0
                outer = radius * 0.92
                inner = radius * (0.78 if index % 3 else 0.7)
                canvas.line(cx + math.sin(angle) * inner, cy - math.cos(angle) * inner,
                            cx + math.sin(angle) * outer, cy - math.cos(angle) * outer,
                            tick_color, 1 if index % 3 else 2)
        now = time.localtime(context.now)
        hour_angle = (now.tm_hour % 12 + now.tm_min / 60.0) * math.pi / 6.0
        minute_angle = (now.tm_min + now.tm_sec / 60.0) * math.pi / 30.0
        canvas.line(cx, cy, cx + math.sin(hour_angle) * radius * 0.5,
                    cy - math.cos(hour_angle) * radius * 0.5, color, 3)
        canvas.line(cx, cy, cx + math.sin(minute_angle) * radius * 0.75,
                    cy - math.cos(minute_angle) * radius * 0.75, color, 2)
        if self.spec.get("seconds", True):
            second_angle = now.tm_sec * math.pi / 30.0
            second_color = context.color(self.spec.get("secondcolor"),
                                         (226, 62, 62, 255))
            canvas.line(cx, cy, cx + math.sin(second_angle) * radius * 0.85,
                        cy - math.cos(second_angle) * radius * 0.85, second_color, 1)
        canvas.fill_circle(cx, cy, 3, color)


def create(spec, layout):
    """Instantiate the widget described by ``spec``."""
    kind = str(spec.get("type", "text")).lower()
    cls = REGISTRY.get(kind)
    if cls is None:
        debug("unknown widget type %r, ignoring" % kind)
        return None
    return cls(spec, layout)
