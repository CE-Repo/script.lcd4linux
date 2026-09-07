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


def choose_layout():
    """Let the user pick one of the available layout files."""
    config = Config()
    available = layout_module.discover(config.layout_directories)
    if not available:
        _toast(localize.text(32321, "No layout files found"))
        return
    names = sorted(available)
    labels = []
    for name in names:
        try:
            parsed = layout_module.Layout.load(available[name])
            labels.append("%s  (%s)" % (parsed.name, name))
        except Exception as error:
            labels.append("%s  [%s]" % (name, error))
    dialog = _dialog()
    if dialog is None:
        return
    current = names.index(config.layout) if config.layout in names else 0
    choice = dialog.select(localize.text(32320, "Choose layout"), labels,
                           preselect=current)
    if choice < 0:
        return
    config.set("layout", names[choice])
    notify_service("reload")
    _toast(labels[choice])


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
