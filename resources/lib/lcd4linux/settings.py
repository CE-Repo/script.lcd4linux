"""Add-on configuration.

Reads Kodi's settings when running inside Kodi and falls back to sane
defaults everywhere else, so the same code can be exercised from a shell.
"""

import os

from . import ax206
from .logger import log, set_debug

try:
    import xbmcaddon  # type: ignore
    import xbmcvfs  # type: ignore
except ImportError:
    xbmcaddon = None
    xbmcvfs = None

ADDON_ID = "script.lcd4linux"

DEFAULTS = {
    "output_mode": "usb",
    "display_type": "ax206",
    "spf_model": "",
    "jpeg_quality": 85,
    "jpeg_subsample": True,
    "device_ids": "1908:0102",
    "device_index": 0,
    "device_serial": "",
    "byte_order": "big",
    "rotation": 0,
    "mirror": False,
    "force_size": False,
    "width": 480,
    "height": 320,
    "usb_timeout": 3000,
    "reset_on_open": False,
    "retry_seconds": 20,
    "brightness": 7,
    "dim_brightness": 1,
    "spf_brightness": 100,
    "spf_dim_brightness": 20,
    "dim_on_idle": True,
    "clear_on_exit": True,
    "layout": "default.json",
    "layout_dir": "",
    "page_interval": 15,
    "fps_playing": 4,
    "fps_idle": 1,
    "smooth_images": True,
    "start_command": "",
    "stop_command": "",
    "command_timeout": 15,
    "notifications": True,
    "notification_seconds": 4,
    "debug": False,
}


def addon_path(*parts):
    """Absolute path inside the installed add-on."""
    if xbmcaddon is not None:
        try:
            base = xbmcvfs.translatePath(xbmcaddon.Addon(ADDON_ID).getAddonInfo("path"))
            return os.path.join(base, *parts)
        except Exception:
            pass
    # <addon>/resources/lib/lcd4linux/settings.py -> <addon>
    here = os.path.abspath(__file__)
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))
    return os.path.join(base, *parts)


def profile_path(*parts):
    """Absolute path inside the add-on's user data directory."""
    if xbmcaddon is not None:
        try:
            base = xbmcvfs.translatePath(
                xbmcaddon.Addon(ADDON_ID).getAddonInfo("profile"))
            if not os.path.isdir(base):
                os.makedirs(base)
            return os.path.join(base, *parts)
        except Exception:
            pass
    base = os.path.join(os.path.expanduser("~"), ".lcd4linux")
    if not os.path.isdir(base):
        try:
            os.makedirs(base)
        except OSError:
            pass
    return os.path.join(base, *parts)


class Config(object):
    """A snapshot of the settings."""

    def __init__(self, overrides=None):
        self._addon = None
        if xbmcaddon is not None:
            try:
                self._addon = xbmcaddon.Addon(ADDON_ID)
            except Exception as error:
                log("cannot open add-on settings: %s" % error)
        self._values = dict(DEFAULTS)
        self._load()
        if overrides:
            self._values.update(overrides)
        set_debug(self.debug)

    # -- reading ----------------------------------------------------------
    def _load(self):
        if self._addon is None:
            return
        for key, default in DEFAULTS.items():
            try:
                if isinstance(default, bool):
                    value = self._addon.getSettingBool(key)
                elif isinstance(default, int):
                    value = self._addon.getSettingInt(key)
                else:
                    value = self._addon.getSettingString(key)
            except Exception:
                raw = ""
                try:
                    raw = self._addon.getSetting(key)
                except Exception:
                    pass
                if raw == "":
                    continue
                if isinstance(default, bool):
                    value = str(raw).lower() in ("true", "1", "yes")
                elif isinstance(default, int):
                    try:
                        value = int(float(raw))
                    except ValueError:
                        continue
                else:
                    value = raw
            self._values[key] = value

    def get(self, key, default=None):
        return self._values.get(key, default)

    def set(self, key, value):
        """Update a setting, persisting it in Kodi when possible."""
        self._values[key] = value
        if self._addon is None:
            return
        try:
            if isinstance(value, bool):
                self._addon.setSettingBool(key, value)
            elif isinstance(value, int):
                self._addon.setSettingInt(key, value)
            else:
                self._addon.setSettingString(key, str(value))
        except Exception as error:
            log("cannot store setting %s: %s" % (key, error))

    def __getattr__(self, name):
        values = self.__dict__.get("_values")
        if values is not None and name in values:
            return values[name]
        raise AttributeError(name)

    # -- derived values ---------------------------------------------------
    @property
    def device_ids_parsed(self):
        return ax206.parse_id_list(self._values["device_ids"])

    @property
    def layout_directories(self):
        """User layouts first so they can override the bundled ones."""
        directories = [self._values["layout_dir"] or profile_path("layouts"),
                       addon_path("resources", "layouts")]
        result = []
        for directory in directories:
            if xbmcvfs is not None and directory.startswith("special://"):
                directory = xbmcvfs.translatePath(directory)
            if directory and directory not in result:
                result.append(directory)
        return result

    @property
    def font_directories(self):
        return [profile_path("fonts"), addon_path("resources", "fonts")]

    @property
    def preview_path(self):
        return profile_path("preview.png")

    @property
    def frame_interval_playing(self):
        return 1.0 / max(1, int(self._values["fps_playing"]))

    @property
    def frame_interval_idle(self):
        return 1.0 / max(1, int(self._values["fps_idle"]))

    def describe(self):
        brightness = ("spf_brightness" if self._values["display_type"] == "spf"
                      else "brightness")
        keys = ("display_type", "output_mode", "device_ids", "rotation",
                "mirror", "byte_order", "layout", brightness, "fps_playing",
                "fps_idle")
        return ", ".join("%s=%s" % (key, self._values[key]) for key in keys)


def ensure_user_directories():
    """Create the user layout/font directories on first run."""
    for name in ("layouts", "fonts"):
        path = profile_path(name)
        if not os.path.isdir(path):
            try:
                os.makedirs(path)
            except OSError:
                pass
    return profile_path()
