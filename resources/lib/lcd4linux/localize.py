"""Access to the add-on's translated strings."""

try:
    import xbmcaddon  # type: ignore
except ImportError:
    xbmcaddon = None

_addon = None


def _get_addon():
    global _addon
    if _addon is None and xbmcaddon is not None:
        try:
            _addon = xbmcaddon.Addon()
        except Exception:
            return None
    return _addon


def text(string_id, fallback=""):
    """Return the localised string ``string_id``, or ``fallback``."""
    addon = _get_addon()
    if addon is not None:
        try:
            value = addon.getLocalizedString(int(string_id))
            if value:
                return value
        except Exception:
            pass
    return fallback
