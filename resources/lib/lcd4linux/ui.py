"""The user facing menu and its actions.

The service owns the USB connection, so anything that has to touch the panel
is forwarded to it with ``NotifyAll``; this module only deals with dialogs
and settings.
"""

import json

from . import ax206
from . import layout as layout_module
from . import spf
from . import localize
from . import thumbs
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


def _layout_pictures(entries, available, config):
    """The preview picture of every design, rendering the user's own once."""
    pictures = [thumbs.shipped_path(name) for name, _variants in entries]
    todo = [index for index, picture in enumerate(pictures) if picture is None]
    slow = [index for index in todo
            if not thumbs.cached_is_fresh(entries[index][0],
                                          available[entries[index][0]])]
    progress = None
    if slow and xbmcgui is not None:
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
    return pictures


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


def choose_layout():
    """Let the user pick one of the available layouts, shown as pictures."""
    config = Config()
    available = layout_module.discover(config.layout_directories)
    if not available:
        _toast(localize.text(32321, "No layout files found"))
        return
    dialog = _dialog()
    if dialog is None:
        return

    loaded = {}
    for name, path in available.items():
        try:
            loaded[name] = layout_module.Layout.load(path)
        except Exception as error:
            log("cannot read the layout %s: %s" % (name, error))

    entries = _layout_designs(available)
    labels, details = [], []
    for name, variants in entries:
        parsed = loaded.get(name)
        labels.append(parsed.name if parsed is not None else name)
        sizes = sorted(set("%dx%d" % (loaded[variant].width,
                                      loaded[variant].height)
                           for variant in variants if variant in loaded))
        details.append("%s   %s" % (name, ", ".join(sizes)) if sizes else name)

    current = 0
    for index, (name, variants) in enumerate(entries):
        if config.layout == name or config.layout in variants:
            current = index
            break

    pictures = _layout_pictures(entries, available, config)
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
    status = ""
    if xbmcgui is not None:
        try:
            status = xbmcgui.Window(10000).getProperty("lcd4linux.status")
        except Exception:
            status = ""
    config = Config()
    lines.append("%s: %s" % (localize.text(32330, "Service"),
                             status or localize.text(32331, "not running")))
    try:
        if config.display_type == "spf":
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


def show_web_editor():
    """Tell the user where the browser based layout editor is listening."""
    from . import webui

    config = Config()
    if not config.get("web_enabled", True):
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
        # The service is not up (yet); show where it will be listening.
        host = "127.0.0.1" if config.get("web_bind") == "local" else "0.0.0.0"
        url = "http://%s:%d/" % (webui.local_address(host),
                                 int(config.get("web_port", 8099)))
    lines = [localize.text(32345, "Open this address in a browser:"), "", url, ""]
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
