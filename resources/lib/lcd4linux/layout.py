"""Layout files: pages, page selection and frame rendering.

A layout is a JSON document::

    {
      "name": "Now Playing",
      "size": [480, 320],
      "background": "#0b0d12",
      "defaults": {"font": "sans", "size": 18, "color": "#ffffff"},
      "pages": [
        {"name": "music", "condition": "audio", "duration": 0,
         "widgets": [ {"type": "text", "x": 16, "y": 12, "text": "..."} ]}
      ]
    }

Pages whose ``condition`` is false are skipped; the remaining ones are shown
in turn for ``duration`` seconds each (0 = stay until the page set changes).
"""

import json
import os
import time

from . import tokens
from . import widgets as widget_module
from .canvas import Canvas, parse_color
from .logger import debug, error, log

DEFAULT_SIZE = (480, 320)


class Page(object):
    def __init__(self, spec, layout, index):
        self.spec = spec or {}
        self.layout = layout
        self.index = index
        self.name = self.spec.get("name", "page %d" % (index + 1))
        self.condition = self.spec.get("condition") or self.spec.get("visible")
        self.duration = float(self.spec.get("duration", 0) or 0)
        self.priority = int(self.spec.get("priority", 0))
        self.background = self.spec.get("background")
        self.background_image = self.spec.get("backgroundimage")
        self.background_dim = int(self.spec.get("backgrounddim", 0))
        self._background_cache = None
        self._background_key = None
        self.widgets = []
        for entry in self.spec.get("widgets", []):
            widget = widget_module.create(entry, layout)
            if widget is not None:
                self.widgets.append(widget)

    def is_visible(self, provider):
        if self.condition is None:
            return True
        return tokens.evaluate(self.condition, provider)

    def render(self, canvas, context):
        background = self.background if self.background is not None \
            else self.layout.background
        color = context.color(background, (0, 0, 0, 255))
        source = context.text(self.background_image) if self.background_image else ""
        key = (color, source, canvas.width, canvas.height, self.background_dim)
        if source:
            # The composed background rarely changes, so keep it and copy it
            # in with row slices instead of blending it again every frame.
            if key != self._background_key or self._background_cache is None:
                cached = Canvas(canvas.width, canvas.height)
                cached.clear(color)
                self._render_background(cached, context, source)
                self._background_cache = cached
                self._background_key = key
            canvas.blit_canvas(self._background_cache, 0, 0)
        else:
            canvas.clear(color)
        for widget in self.widgets:
            widget.draw(canvas, context)

    def _render_background(self, canvas, context, source):
        key = ("bg", source, canvas.width, canvas.height)
        image = context.images.lookup(key)
        if image is None:
            raw = context.images.get(source, max(canvas.width, canvas.height))
            if raw is None:
                return
            image = raw.fitted(canvas.width, canvas.height, "cover",
                               context.smooth_images)
            context.images.put(key, image)
        canvas.blit_sprite(0, 0, image.sprite())
        if self.background_dim:
            canvas.fill_rect(0, 0, canvas.width, canvas.height,
                             (0, 0, 0, max(0, min(255, self.background_dim * 255 // 100))))


class Layout(object):
    """A parsed layout file."""

    def __init__(self, spec, path=None):
        self.spec = spec or {}
        self.path = path
        self.name = self.spec.get("name") or (
            os.path.splitext(os.path.basename(path))[0] if path else "layout")
        size = self.spec.get("size") or DEFAULT_SIZE
        try:
            self.width, self.height = int(size[0]), int(size[1])
        except (TypeError, ValueError, IndexError):
            self.width, self.height = DEFAULT_SIZE
        self.background = self.spec.get("background", "#000000")
        defaults = self.spec.get("defaults", {}) or {}
        self.default_font = defaults.get("font", "sans")
        self.default_size = int(defaults.get("size", 18))
        self.default_color = parse_color(defaults.get("color", "#ffffff"))
        self.accent = self.spec.get("accent")
        self.page_interval = float(self.spec.get("pageinterval", 0) or 0)
        self.pages = [Page(entry, self, index)
                      for index, entry in enumerate(self.spec.get("pages", []))]
        if not self.pages:
            self.pages = [Page({"name": "empty", "widgets": []}, self, 0)]

    # -- loading ----------------------------------------------------------
    @classmethod
    def load(cls, path):
        with open(path, "r") as handle:
            text = handle.read()
        return cls(_parse_json(text, path), path)

    @classmethod
    def from_string(cls, text, path=None):
        return cls(_parse_json(text, path or "<string>"), path)


def _parse_json(text, path):
    """Parse JSON, tolerating ``//`` and ``#`` comment lines."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    try:
        return json.loads(cleaned)
    except ValueError as err:
        raise ValueError("%s: invalid JSON (%s)" % (path, err))


class Renderer(object):
    """Chooses the page to show and draws frames."""

    def __init__(self, layout, provider, fonts, images, default_interval=15.0,
                 smooth_images=True, size=None):
        self.layout = layout
        self.provider = provider
        self.fonts = fonts
        self.images = images
        self.default_interval = default_interval
        self.smooth_images = smooth_images
        width, height = size or (layout.width, layout.height)
        self.canvas = Canvas(width, height)
        self._active = None
        self._active_since = 0.0
        self._visible_signature = None

    # -- page selection ---------------------------------------------------
    def visible_pages(self):
        pages = [page for page in self.layout.pages if page.is_visible(self.provider)]
        if not pages:
            return []
        top = max(page.priority for page in pages)
        return [page for page in pages if page.priority == top]

    def select_page(self, now):
        pages = self.visible_pages()
        if not pages:
            self._active = None
            return None
        signature = tuple(page.index for page in pages)
        if signature != self._visible_signature:
            # The set of eligible pages changed (playback started, ...):
            # restart the rotation at its first page.
            self._visible_signature = signature
            self._active = pages[0]
            self._active_since = now
            return self._active
        if self._active not in pages:
            self._active = pages[0]
            self._active_since = now
            return self._active
        duration = self._active.duration or self.layout.page_interval \
            or self.default_interval
        if len(pages) > 1 and duration > 0 and now - self._active_since >= duration:
            position = pages.index(self._active)
            self._active = pages[(position + 1) % len(pages)]
            self._active_since = now
        return self._active

    def next_page(self, now=None):
        """Manually advance to the next eligible page."""
        now = now if now is not None else time.time()
        pages = self.visible_pages()
        if len(pages) < 2:
            return self._active
        position = pages.index(self._active) if self._active in pages else -1
        self._active = pages[(position + 1) % len(pages)]
        self._active_since = now
        return self._active

    @property
    def active_page(self):
        return self._active

    # -- rendering --------------------------------------------------------
    def render(self, now=None):
        """Draw the current page and return the canvas."""
        now = now if now is not None else time.time()
        self.provider.begin_frame(now)
        page = self.select_page(now)
        context = widget_module.RenderContext(
            self.provider, self.fonts, self.images, self.canvas.width,
            self.canvas.height, now, self.smooth_images)
        context.accent = self._accent(context)
        self.canvas.reset_clip()
        if page is None:
            self.canvas.clear(parse_color(self.layout.background))
            return self.canvas
        page.render(self.canvas, context)
        return self.canvas

    def _accent(self, context):
        """Resolve the layout wide ``accent`` colour, possibly from artwork."""
        accent = self.layout.accent
        if not accent:
            return None
        text = str(accent).strip()
        if text.lower().startswith("auto"):
            _, _, source = text.partition(":")
            source = source.strip() or "${player.thumb}"
            path = context.text(source)
            if not path:
                return None
            key = ("accent", path)
            cached = self.images.lookup(key)
            if cached is None:
                image = self.images.get(path, 96)
                if image is None:
                    return None
                cached = image.dominant_color()
                self.images.put(key, cached)
            return cached
        return context.color(text)


def discover(directories):
    """Find layout files, later directories overriding earlier ones."""
    found = {}
    for directory in directories:
        if not directory or not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.lower().endswith(".json"):
                continue
            found[name] = os.path.join(directory, name)
    return found


def load_layout(name, directories, fallback_size=DEFAULT_SIZE):
    """Load ``name`` from the first directory that has it."""
    available = discover(directories)
    path = available.get(name)
    if path is None and name and not name.lower().endswith(".json"):
        path = available.get(name + ".json")
    if path is None and available:
        path = available[sorted(available)[0]]
        log("layout %r not found, falling back to %s" % (name, path))
    if path is None:
        error("no layout files found in %s" % (directories,))
        return Layout({"name": "empty", "size": list(fallback_size),
                       "pages": [{"name": "empty", "widgets": []}]})
    debug("loading layout %s" % path)
    return Layout.load(path)
