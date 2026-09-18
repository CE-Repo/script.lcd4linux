"""A cached index over the layout files: name, size and page count.

Listing the layouts means opening every one of them, and the add-on ships
sixty files for twenty designs.  The result barely changes - a layout file
is edited now and then, the bundled ones never - so it is kept in the
profile and reused as long as the file behind an entry is untouched.  One
small read then replaces sixty parses, which is what the layout chooser and
the web editor spend their startup on.

Freshness is decided per file by modification time and size, the same way
:mod:`.thumbs` decides whether a rendered preview still matches its layout.
"""

import json
import os

from . import layout as layout_module
from .logger import debug
from .settings import profile_path

#: Bumped when the shape of an entry changes, so an old cache is discarded
#: instead of being read with the wrong fields.
INDEX_VERSION = 1


def _cache_path():
    return profile_path("layouts.index.json")


def _signature(path):
    """What makes an entry stale: the file was written or changed length."""
    info = os.stat(path)
    return [int(info.st_mtime), int(info.st_size)]


def _load_cache():
    try:
        with open(_cache_path(), "r", encoding="utf-8") as handle:
            cached = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(cached, dict) or cached.get("version") != INDEX_VERSION:
        return {}
    entries = cached.get("entries")
    return entries if isinstance(entries, dict) else {}


def _store_cache(entries):
    path = _cache_path()
    temporary = path + ".tmp"
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"version": INDEX_VERSION, "entries": entries}, handle)
        os.replace(temporary, path)
    except (OSError, ValueError) as error:
        # A read only profile only costs the cache, never the listing.
        debug("cannot store the layout index: %s" % error)
        try:
            os.remove(temporary)
        except OSError:
            pass


def read(available):
    """``{name: info}`` for the layouts in ``available`` (``{name: path}``).

    An entry is what :func:`~.layout.read_info` returns, or ``{"error": ...}``
    for a file that could not be read.  Failures are cached too: a layout
    with a typo in it should not cost a parse attempt on every listing.
    """
    cached = _load_cache()
    entries = {}
    result = {}
    changed = False
    for name in sorted(available):
        path = available[name]
        try:
            signature = _signature(path)
        except OSError as error:
            result[name] = {"error": str(error)}
            changed = True
            continue
        entry = cached.get(path)
        if not (isinstance(entry, dict) and entry.get("sig") == signature
                and isinstance(entry.get("info"), dict)):
            try:
                info = layout_module.read_info(path)
            except Exception as error:
                info = {"error": str(error)}
            entry = {"sig": signature, "info": info}
            changed = True
        entries[path] = entry
        result[name] = entry["info"]
    if changed or set(entries) != set(cached):
        _store_cache(entries)
    return result


def forget():
    """Drop the cache, so the next listing reads every layout again."""
    try:
        os.remove(_cache_path())
    except OSError:
        pass
