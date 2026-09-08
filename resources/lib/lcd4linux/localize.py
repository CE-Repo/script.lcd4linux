"""Access to the translated strings.

Two sources are used.  Ids from 30000 upwards are the add-on's own strings
and come from ``resources/language/``; anything below that is one of Kodi's
own strings, which is how the day and month names are translated without
shipping a copy of them.
"""

import os
import re

try:
    import xbmc  # type: ignore
    import xbmcaddon  # type: ignore
except ImportError:
    xbmc = None
    xbmcaddon = None

#: Languages the add-on ships, used when Kodi is not around.
LANGUAGES = ("de_de", "en_gb")
DEFAULT_LANGUAGE = "en_gb"

#: One ``msgctxt``/``msgid``/``msgstr`` triple.  The string body allows
#: backslash escapes so a quoted word inside a message is not cut short.
_QUOTED = r'"((?:[^"\\]|\\.)*)"'
_PO_ENTRY = re.compile(r'msgctxt "#(\d+)"\s*\nmsgid %s\s*\nmsgstr %s'
                       % (_QUOTED, _QUOTED))

#: First id of the add-on's own strings; below this Kodi is asked.
ADDON_STRING_BASE = 30000

#: Kodi's own day and month names.  The blocks are contiguous and start at
#: Monday and at January respectively.
WEEKDAY_BASE = 11           # 11..17  Monday .. Sunday
WEEKDAY_SHORT_BASE = 41     # 41..47  Mon .. Sun
MONTH_BASE = 21             # 21..32  January .. December
MONTH_SHORT_BASE = 51       # 51..62  Jan .. Dec

#: The same names in the add-on's own strings.  They are what the preview
#: tools use outside Kodi, and they keep the date readable on a Kodi build
#: that does not answer for the ids above.
OWN_WEEKDAY_BASE = 32450
OWN_WEEKDAY_SHORT_BASE = 32457
OWN_MONTH_BASE = 32464
OWN_MONTH_SHORT_BASE = 32476

_addon = None
_catalogue = None


def _language_directory():
    """``<addon>/resources/language`` from this module's own location."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "language")


def _offline_language():
    """Pick a shipped language from the environment, e.g. ``de_DE.UTF-8``."""
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = (os.environ.get(name) or "").strip().lower()
        if not value:
            continue
        code = re.split(r"[.:@]", value)[0].replace("-", "_")
        for candidate in LANGUAGES:
            if code == candidate or code.split("_")[0] == candidate.split("_")[0]:
                return candidate
    return DEFAULT_LANGUAGE


def _offline_catalogue():
    """Read the shipped strings when Kodi cannot be asked.

    Only the preview and contact sheet tools end up here; inside Kodi the
    add-on's own gettext handling is used.
    """
    global _catalogue
    if _catalogue is not None:
        return _catalogue
    _catalogue = {}
    path = os.path.join(_language_directory(),
                        "resource.language.%s" % _offline_language(),
                        "strings.po")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = handle.read()
    except (IOError, OSError):
        return _catalogue
    for number, english, translated in _PO_ENTRY.findall(data):
        value = translated or english
        _catalogue[int(number)] = value.replace('\\"', '"').replace("\\\\", "\\")
    return _catalogue


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
    try:
        number = int(string_id)
    except (TypeError, ValueError):
        return fallback
    if number >= ADDON_STRING_BASE:
        addon = _get_addon()
        if addon is not None:
            try:
                value = addon.getLocalizedString(number)
                if value:
                    return value
            except Exception:
                pass
            return fallback
        return _offline_catalogue().get(number, fallback)
    if xbmc is not None:
        try:
            value = xbmc.getLocalizedString(number)
            if value:
                return value
        except Exception:
            pass
    return fallback


def weekday(index, short=False):
    """Localised name of weekday ``index``, Monday being 0."""
    index = int(index) % 7
    base = WEEKDAY_SHORT_BASE if short else WEEKDAY_BASE
    own = OWN_WEEKDAY_SHORT_BASE if short else OWN_WEEKDAY_BASE
    return text(base + index) or text(own + index)


def month(number, short=False):
    """Localised name of month ``number``, January being 1."""
    index = (int(number) - 1) % 12
    base = MONTH_SHORT_BASE if short else MONTH_BASE
    own = OWN_MONTH_SHORT_BASE if short else OWN_MONTH_BASE
    return text(base + index) or text(own + index)
