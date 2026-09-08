"""Preview pictures for the layout chooser.

Rendering a layout takes a moment on a set top box, so the bundled designs
ship with a picture rendered by ``tools/make_thumbs.py``; only layouts from
the user's own folder are rendered on demand and cached in the profile.

The size variants of one design (``default.json`` and
``default-800x480.json``) share a picture: they draw the same design and
:func:`~.layout.load_layout` picks the variant that fits the panel.
"""

import os
import re

from . import pngio
from .layout import Layout, Renderer
from .logger import log
from .settings import addon_path, profile_path

#: Pictures are scaled into this box, which is plenty for the dialog.
THUMB_BOX = (480, 320)

_SIZE_SUFFIX = re.compile(r"^(.+)-\d+x\d+$")


def design_name(name):
    """The design behind a layout file name, without its size variant."""
    stem = name[:-5] if name.lower().endswith(".json") else name
    match = _SIZE_SUFFIX.match(stem)
    return match.group(1) if match else stem


def shipped_path(name):
    """The picture that ships with the add-on, if the design has one."""
    path = addon_path("resources", "thumbs", design_name(name) + ".png")
    return path if os.path.isfile(path) else None


def render(layout_path, out_path, font_directories=None, box=THUMB_BOX):
    """Render one layout with demo data and write it as a PNG."""
    from .bmfont import FontCache
    from .images import Image, ImageCache
    from .kodidata import DemoProvider

    fonts = FontCache(font_directories or [addon_path("resources", "fonts")])
    provider = DemoProvider(0, 97.0, "playing",
                            addon_path("resources", "media", "demo-cover.jpg"),
                            addon_path("resources", "media", "demo-fanart.jpg"))
    renderer = Renderer(Layout.load(layout_path), provider, fonts, ImageCache())
    canvas = renderer.render()

    rgb = canvas.to_rgb888()
    width, height = canvas.width, canvas.height
    if box and (width > box[0] or height > box[1]):
        rgba = bytearray(width * height * 4)
        rgba[0::4] = rgb[0::3]
        rgba[1::4] = rgb[1::3]
        rgba[2::4] = rgb[2::3]
        rgba[3::4] = b"\xff" * (width * height)
        scaled = Image(width, height, rgba).fitted(box[0], box[1], "contain")
        width, height = scaled.width, scaled.height
        rgb = bytearray(width * height * 3)
        rgb[0::3] = scaled.pixels[0::4]
        rgb[1::3] = scaled.pixels[1::4]
        rgb[2::3] = scaled.pixels[2::4]

    directory = os.path.dirname(out_path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(out_path, "wb") as handle:
        handle.write(pngio.encode_rgb(width, height, rgb))
    return out_path


def cached_is_fresh(name, layout_path):
    """Whether a rendered picture is cached and newer than the layout."""
    out_path = profile_path("thumbs", design_name(name) + ".png")
    try:
        return (os.path.isfile(out_path)
                and os.path.getmtime(out_path) >= os.path.getmtime(layout_path))
    except OSError:
        return False


def cached_path(name, layout_path, font_directories=None):
    """A picture for a layout the add-on does not ship, rendered once."""
    out_path = profile_path("thumbs", design_name(name) + ".png")
    if cached_is_fresh(name, layout_path):
        return out_path
    try:
        return render(layout_path, out_path, font_directories)
    except Exception as error:
        log("cannot render a preview for %s: %s" % (name, error))
        return None


def path_for(name, layout_path, font_directories=None, render_missing=True):
    """The picture to show for a layout, or ``None`` if there is none."""
    path = shipped_path(name)
    if path or not render_missing:
        return path
    return cached_path(name, layout_path, font_directories)
