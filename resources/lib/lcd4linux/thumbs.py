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
    # Written beside the target and moved into place: the service renders
    # these while the chooser is reading them, and half a PNG looks fresh
    # enough to :func:`cached_is_fresh` to be handed to Kodi.
    temporary = out_path + ".tmp"
    try:
        with open(temporary, "wb") as handle:
            handle.write(pngio.encode_rgb_compact(width, height, rgb))
        os.replace(temporary, out_path)
    except Exception:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise
    return out_path


def cached_is_fresh(name, layout_path):
    """Whether a rendered picture is cached and newer than the layout."""
    out_path = profile_path("thumbs", design_name(name) + ".png")
    try:
        return (os.path.isfile(out_path)
                and os.path.getmtime(out_path) >= os.path.getmtime(layout_path))
    except OSError:
        return False


def cached_picture(name):
    """The picture drawn for a layout earlier, or ``None`` if there is none."""
    out_path = profile_path("thumbs", design_name(name) + ".png")
    return out_path if os.path.isfile(out_path) else None


def is_user_layout(layout_path, user_directory):
    """Whether a layout file is one the user wrote themselves."""
    if not user_directory or not layout_path:
        return False
    try:
        return (os.path.abspath(os.path.dirname(layout_path))
                == os.path.abspath(user_directory))
    except (OSError, ValueError):
        return False


def picture(name, layout_path, user_directory):
    """The picture to show for a layout, ``None`` if it has to be drawn.

    Which of the two rules applies is decided by where the file lies, not
    by what it is called.  A layout in the user's own folder is drawn from
    that file, so its picture only holds while it is newer than the layout:
    edit the layout and it is drawn again.  A ``default-1920x1080.json`` of
    their own is theirs as well, and must not be shown with the bundled
    ``default`` picture just because the name matches.

    Everything that comes with the add-on is shown with the picture it
    ships.  Those files only change when the add-on is updated, and the
    picture is updated with them, so there is never anything to redraw -
    which is the whole point of shipping them.
    """
    if is_user_layout(layout_path, user_directory):
        if not cached_is_fresh(name, layout_path):
            return None
        return profile_path("thumbs", design_name(name) + ".png")
    shipped = shipped_path(name)
    if shipped is not None:
        return shipped
    # A bundled design with no picture of its own is a packaging slip, but
    # whatever was drawn for it once is still right: it cannot change
    # without an update, and an update brings its picture along.
    return cached_picture(name)


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
