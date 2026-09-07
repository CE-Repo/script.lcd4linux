"""Logging helper that works inside Kodi and from a plain shell."""

import sys

try:
    import xbmc  # type: ignore
except ImportError:
    xbmc = None

ADDON_ID = "script.lcd4linux"

_debug_enabled = False


def set_debug(enabled):
    global _debug_enabled
    _debug_enabled = bool(enabled)


def debug_enabled():
    return _debug_enabled


def log(message, level=None):
    text = "[%s] %s" % (ADDON_ID, message)
    if xbmc is not None:
        try:
            xbmc.log(text, level if level is not None else xbmc.LOGINFO)
            return
        except Exception:
            pass
    sys.stderr.write(text + "\n")


def debug(message):
    if not _debug_enabled:
        return
    text = "[%s] %s" % (ADDON_ID, message)
    if xbmc is not None:
        try:
            xbmc.log(text, xbmc.LOGDEBUG)
            return
        except Exception:
            pass
    sys.stderr.write(text + "\n")


def error(message):
    text = "[%s] %s" % (ADDON_ID, message)
    if xbmc is not None:
        try:
            xbmc.log(text, xbmc.LOGERROR)
            return
        except Exception:
            pass
    sys.stderr.write(text + "\n")
