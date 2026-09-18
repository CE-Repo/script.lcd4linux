"""The user facing menu and its actions.

The service owns the USB connection, so anything that has to touch the panel
is forwarded to it with ``NotifyAll``; this module only deals with dialogs
and settings.
"""

import contextlib
import json

from . import ax206
from . import layout as layout_module
from . import layoutindex
from . import spf
from . import localize
from . import thumbs
from . import tokens
from .logger import log
from .settings import ADDON_ID, Config, profile_path

try:
    import xbmc  # type: ignore
    import xbmcaddon  # type: ignore
    import xbmcgui  # type: ignore
except ImportError:
    xbmc = None
    xbmcaddon = None
    xbmcgui = None


def notify_service(command, payload=None):
    """Send a control command to the running service."""
    if xbmc is None:
        log("not running inside Kodi, cannot send %r" % command)
        return False
    request = {
        "jsonrpc": "2.0", "id": 1, "method": "JSONRPC.NotifyAll",
        "params": {"sender": ADDON_ID, "message": command},
    }
    if payload is not None:
        request["params"]["data"] = payload
    xbmc.executeJSONRPC(json.dumps(request))
    return True


def _dialog():
    return xbmcgui.Dialog() if xbmcgui is not None else None


def _service_status():
    """What the service published about itself, empty when it is not up."""
    if xbmcgui is None:
        return ""
    try:
        return xbmcgui.Window(10000).getProperty("lcd4linux.status") or ""
    except Exception:
        return ""


@contextlib.contextmanager
def _busy():
    """Kodi's spinner while a menu action collects what it needs.

    Opening the layout chooser reads every layout file and looks for a
    preview picture of each; that is fast once the index and the previews
    are cached, but the first run after an update has nothing cached and
    used to look like the button had not been pressed at all.
    """
    shown = False
    if xbmc is not None:
        try:
            # Both calls wait: an asynchronous activation can still be on
            # its way when the close is issued, and the spinner would then
            # stay up over the dialog it was covering for.
            xbmc.executebuiltin("ActivateWindow(busydialognocancel)", True)
            shown = True
        except Exception as error:
            log("no busy dialog: %s" % error)
    try:
        yield
    finally:
        if shown:
            try:
                xbmc.executebuiltin("Dialog.Close(busydialognocancel)", True)
            except Exception as error:
                log("cannot close the busy dialog: %s" % error)


def _toast(message, heading=None):
    dialog = _dialog()
    if dialog is None:
        print(message)
        return
    dialog.notification(heading or localize.text(32000, "LCD4Linux"), message,
                        xbmcgui.NOTIFICATION_INFO, 4000)


def _layout_designs(available):
    """The layout files grouped by design: ``[(name, [variants])]``.

    ``default.json`` and ``default-800x480.json`` are one design drawn for
    two panels, so they share an entry.  The name without the size is what
    the setting stores; :func:`~.layout.load_layout` then picks the variant
    that fits the display.
    """
    designs = {}
    for name in sorted(available):
        designs.setdefault(thumbs.design_name(name), []).append(name)
    entries = []
    for design in sorted(designs):
        variants = designs[design]
        name = design + ".json"
        entries.append((name if name in available else variants[0], variants))
    return entries


def _render_pictures(pictures, todo, entries, available, config):
    """Draw the missing previews here and now, behind a progress bar."""
    progress = None
    if xbmcgui is not None:
        try:
            progress = xbmcgui.DialogProgressBG()
            progress.create(localize.text(32000, "LCD4Linux"),
                            localize.text(32327, "Rendering layout previews"))
        except Exception as error:
            log("no progress dialog: %s" % error)
            progress = None
    for step, index in enumerate(todo):
        name = entries[index][0]
        if progress is not None:
            progress.update(int(100.0 * step / len(todo)), message=name)
        pictures[index] = thumbs.cached_path(name, available[name],
                                             config.font_directories)
    if progress is not None:
        progress.close()


def _layout_pictures(entries, available, config):
    """The preview picture of every design, and what is still being drawn.

    The bundled designs ship a picture and the user's own are rendered once
    and then cached, so most of the time this is twenty path lookups.  When
    something does have to be rendered it takes seconds per layout, which is
    far too long to hold the dialog for: the running service is asked to do
    it in the background and those entries open without a picture, filled in
    the next time the chooser is opened.  Without a service there is nobody
    to hand the work to, so it happens here as it always did.

    Returns ``(pictures, pending)`` - one picture per entry, ``None`` where
    there is none yet, and the names being rendered in the background.
    """
    pictures = [thumbs.shipped_path(name) for name, _variants in entries]
    todo = []
    for index, picture in enumerate(pictures):
        if picture is not None:
            continue
        name = entries[index][0]
        picture = thumbs.cached_picture(name, available[name])
        if picture is None:
            todo.append(index)
        else:
            pictures[index] = picture
    if not todo:
        return pictures, []
    missing = [entries[index][0] for index in todo]
    if _service_status() and notify_service("render_thumbs",
                                            {"names": missing}):
        return pictures, missing
    _render_pictures(pictures, todo, entries, available, config)
    return pictures, []


def _select_layout(dialog, heading, labels, details, pictures, current):
    """The select dialog with a picture per layout, plain list as fallback."""
    if xbmcgui is not None and any(pictures):
        try:
            items = []
            for label, detail, picture in zip(labels, details, pictures):
                item = xbmcgui.ListItem(label, detail)
                if picture:
                    item.setArt({"icon": picture, "thumb": picture})
                items.append(item)
            return dialog.select(heading, items, useDetails=True,
                                 preselect=current)
        except Exception as error:
            log("cannot show the previews: %s" % error)
    return dialog.select(heading,
                         ["%s  (%s)" % pair for pair in zip(labels, details)],
                         preselect=current)


def _layout_entries(available, config):
    """The rows of the chooser: ``(entries, labels, details, current)``."""
    infos = layoutindex.read(available)
    entries = _layout_designs(available)
    labels, details = [], []
    for name, variants in entries:
        info = infos.get(name) or {}
        labels.append(tokens.localize_text(info.get("name")) or name)
        sizes = sorted(set("%dx%d" % (infos[variant]["width"],
                                      infos[variant]["height"])
                           for variant in variants
                           if "width" in (infos.get(variant) or {})))
        details.append("%s   %s" % (name, ", ".join(sizes)) if sizes else name)
    current = 0
    for index, (name, variants) in enumerate(entries):
        if config.layout == name or config.layout in variants:
            current = index
            break
    return entries, labels, details, current


def choose_layout():
    """Let the user pick one of the available layouts, shown as pictures."""
    config = Config()
    dialog = _dialog()
    with _busy():
        available = layout_module.discover(config.layout_directories)
        if not available:
            _toast(localize.text(32321, "No layout files found"))
            return
        if dialog is None:
            return
        entries, labels, details, current = _layout_entries(available, config)
        pictures, pending = _layout_pictures(entries, available, config)

    if pending:
        _toast(localize.text(32328, "Preparing layout previews"))
    choice = _select_layout(dialog, localize.text(32320, "Choose layout"),
                            labels, details, pictures, current)
    if choice < 0:
        return
    config.set("layout", entries[choice][0])
    notify_service("reload")
    _toast("%s  (%s)" % (labels[choice], entries[choice][0]))


def show_status():
    """Report what the service found on the USB bus."""
    lines = []
    status = _service_status()
    config = Config()
    lines.append("%s: %s" % (localize.text(32330, "Service"),
                             status or localize.text(32331, "not running")))
    try:
        if config.output_mode == "network":
            # Nothing to probe on the USB bus; what the user needs is the
            # address to point the tablet at.
            lines.append("%s %dx%d" % (localize.text(32522,
                                                     "Network display"),
                                       int(config.width), int(config.height)))
            lines.append(_display_url(config))
        elif config.display_type == "spf":
            frames = spf.SamsungSPF.enumerate()
            if frames:
                for info, mode, model in frames:
                    lines.append("%s [%s] %s" % (model, mode, info))
            else:
                lines.append(localize.text(32336,
                                           "No Samsung photo frame detected"))
        else:
            found = ax206.AX206.enumerate(config.device_ids_parsed)
            if found:
                for info in found:
                    lines.append(str(info))
            else:
                lines.append(localize.text(32332, "No AX206 display detected"))
    except Exception as error:
        lines.append("%s: %s" % (localize.text(32333, "USB error"), error))
    lines.append("")
    lines.append(config.describe())
    lines.append("%s: %s" % (localize.text(32334, "Layout folder"),
                             profile_path("layouts")))
    dialog = _dialog()
    if dialog is None:
        print("\n".join(lines))
        return
    dialog.textviewer(localize.text(32335, "Display status"), "\n".join(lines))


def _base_url(config):
    """Where the add-on's HTTP server is (or will be) listening."""
    from . import webui

    if xbmcgui is not None:
        try:
            url = xbmcgui.Window(10000).getProperty("lcd4linux.weburl")
        except Exception:
            url = ""
        if url:
            return url
    # The service is not up (yet); show where it will be listening.
    host = "127.0.0.1" if config.get("web_bind") == "local" else "0.0.0.0"
    return "http://%s:%d/" % (webui.local_address(host),
                              int(config.get("web_port", 8050)))


def _display_url(config):
    """The address a wall panel browser should open."""
    from urllib.parse import quote

    url = _base_url(config) + "display"
    password = str(config.get("web_password", "") or "")
    if password:
        url += "?key=" + quote(password, safe="")
    return url


def show_web_editor():
    """Tell the user where the browser based layout editor is listening."""
    config = Config()
    # In network mode the server is the display, so it runs regardless of
    # the editor switch.
    if not config.get("web_enabled", True) and config.output_mode != "network":
        _toast(localize.text(32346, "The web editor is switched off"))
        return
    url = ""
    if xbmcgui is not None:
        try:
            url = xbmcgui.Window(10000).getProperty("lcd4linux.weburl")
        except Exception:
            url = ""
    running = bool(url)
    if not url:
        url = _base_url(config)
    lines = [localize.text(32345, "Open this address in a browser:"), "", url, ""]
    if config.output_mode == "network":
        lines.append(localize.text(32521, "Wall panel address:"))
        lines.append("")
        lines.append(_display_url(config))
        lines.append("")
    if not running:
        lines.append(localize.text(32344, "The web editor is not running yet"))
        lines.append("")
    lines.append("%s: %s" % (localize.text(32334, "Layout folder"),
                             profile_path("layouts")))
    dialog = _dialog()
    if dialog is None:
        print("\n".join(lines))
        return
    dialog.textviewer(localize.text(32343, "Web editor"), "\n".join(lines))


def open_settings():
    if xbmcaddon is None:
        return
    try:
        xbmcaddon.Addon(ADDON_ID).openSettings()
    except Exception as error:
        log("cannot open settings: %s" % error)


def show_preview():
    """Render the current layout to a PNG and show it in Kodi."""
    from .bmfont import FontCache
    from .images import ImageCache
    from .kodidata import make_provider
    from . import pngio

    config = Config()
    fonts = FontCache(config.font_directories)
    images = ImageCache()
    provider = make_provider()
    layout = layout_module.load_layout(config.layout, config.layout_directories,
                                       (config.width, config.height))
    renderer = layout_module.Renderer(layout, provider, fonts, images,
                                      float(config.page_interval),
                                      bool(config.smooth_images))
    canvas = renderer.render()
    path = profile_path("preview.png")
    with open(path, "wb") as handle:
        handle.write(pngio.encode_rgb(canvas.width, canvas.height,
                                      canvas.to_rgb888()))
    if xbmc is not None:
        xbmc.executebuiltin('ShowPicture("%s")' % path)
    else:
        print("preview written to %s" % path)


ACTIONS = {
    "layout": choose_layout,
    "webeditor": show_web_editor,
    "status": show_status,
    "settings": open_settings,
    "preview": show_preview,
    "reload": lambda: (notify_service("reload"),
                       _toast(localize.text(32322, "Reloading"))),
    "next_page": lambda: notify_service("next_page"),
    "test_pattern": lambda: (notify_service("test_pattern"),
                             _toast(localize.text(32323, "Test pattern"))),
    "brightness_up": lambda: notify_service("brightness_up"),
    "brightness_down": lambda: notify_service("brightness_down"),
}

MENU = (
    ("layout", 32320, "Choose layout"),
    ("webeditor", 32343, "Web editor"),
    ("preview", 32324, "Preview layout"),
    ("next_page", 32325, "Next page"),
    ("test_pattern", 32323, "Test pattern"),
    ("status", 32335, "Display status"),
    ("reload", 32322, "Reload service"),
    ("settings", 32326, "Settings"),
)


def run(arguments):
    if arguments:
        action = ACTIONS.get(arguments[0])
        if action is None:
            log("unknown action %r" % arguments[0])
            return
        action()
        return
    dialog = _dialog()
    if dialog is None:
        print("available actions: %s" % ", ".join(sorted(ACTIONS)))
        return
    labels = [localize.text(string_id, fallback) for _, string_id, fallback in MENU]
    choice = dialog.select(localize.text(32000, "LCD4Linux"), labels)
    if choice < 0:
        return
    ACTIONS[MENU[choice][0]]()
