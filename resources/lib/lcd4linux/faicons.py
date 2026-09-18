"""Font Awesome Free icons, searchable offline and cached on disk.

The add-on ships the *index* of the whole free set - every name, the styles
it exists in and the words it can be found by - in
``resources/icons/fontawesome.json``.  That is what the editor's icon dialog
searches, so picking an icon never needs a network connection.

The outlines themselves are fetched once, the first time an icon is actually
drawn or previewed, and written to ``<profile>/icons/<style>/<name>.json``.
From then on the icon is rendered from that cache, which is the point: a box
that boots without internet still draws every icon its layouts use.

Nothing here blocks the renderer.  :func:`request` answers from the caches
and hands anything missing to a background thread, so a frame is never held
up by an HTTP request.

Icons: CC BY 4.0 - https://fontawesome.com/license/free
"""

import json
import os
import re
import threading
import time

try:
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
except ImportError:  # pragma: no cover - Python 2 safety net
    from urllib2 import HTTPError, Request, urlopen  # type: ignore

from .logger import log, debug
from .settings import addon_path, profile_path

#: The Font Awesome Free release the bundled index describes.  Change it in
#: one place and rerun ``tools/mkicons.py``.
VERSION = "7.3.1"

#: Styles the free set covers, in the order they are searched.
STYLES = ("solid", "regular", "brands")

#: The single letter the index stores a style as.
STYLE_CODES = {"s": "solid", "r": "regular", "b": "brands"}

DEFAULT_STYLE = "solid"

#: Where an outline is fetched from.  jsDelivr serves the npm package, so
#: the URL is stable for every past release.
DOWNLOAD_URL = ("https://cdn.jsdelivr.net/npm/@fortawesome/"
                "fontawesome-free@%(version)s/svgs/%(style)s/%(name)s.svg")

#: The same icons as one file per style.  Filling the cache from these is
#: three requests instead of two thousand, which is what "cache everything
#: before the box goes offline" wants.
SPRITE_URL = ("https://cdn.jsdelivr.net/npm/@fortawesome/"
              "fontawesome-free@%(version)s/sprites/%(style)s.svg")

#: A sprite is a few hundred kB; this is the ceiling before it is refused.
SPRITE_LIMIT = 8 * 1024 * 1024

#: Seconds an HTTP request may take before it is given up on.
TIMEOUT = 10.0

#: How long a name that could not be fetched is remembered as missing, and
#: how long every download is paused after the network itself failed.  One
#: unreachable CDN should cost one timeout, not one per icon on the page.
MISS_SECONDS = 300.0
OFFLINE_SECONDS = 60.0

#: Outlines kept in memory; the rest stay on disk until they are needed.
MEMORY_LIMIT = 256

_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SYMBOL = re.compile(r"<symbol\b([^>]*)>(.*?)</symbol>", re.S)
_SYMBOL_ID = re.compile(r'id\s*=\s*"([^"]+)"')
_VIEWBOX = re.compile(r'viewBox\s*=\s*"([^"]*)"')
_PATH_DATA = re.compile(r'<path\b[^>]*\sd\s*=\s*"([^"]+)"', re.S)
_EVENODD = re.compile(r'fill-rule\s*=\s*"\s*evenodd\s*"')

INDEX_PATH = addon_path("resources", "icons", "fontawesome.json")

_lock = threading.Lock()
_catalogue = None
_outlines = {}
_misses = {}
_offline_until = 0.0
_queue = []
_active = 0
_wake = threading.Event()
_worker = None
_stopping = False

#: Set from the add-on settings; downloads can be switched off entirely for
#: a box that should never talk to the internet.
_downloads = True
_download_url = DOWNLOAD_URL
_cache_root = None


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

def configure(config=None, downloads=None, url=None, cache=None):
    """Apply the add-on settings (or explicit overrides) to this module."""
    global _downloads, _download_url, _cache_root
    if config is not None:
        _downloads = bool(config.get("icon_download", True))
        source = str(config.get("icon_source", "") or "").strip()
        _download_url = source or DOWNLOAD_URL
    if downloads is not None:
        _downloads = bool(downloads)
    if url is not None:
        _download_url = url or DOWNLOAD_URL
    if cache is not None:
        _cache_root = cache or None


def downloads_enabled():
    return bool(_downloads)


def cache_dir(*parts):
    """The directory cached outlines live in."""
    if _cache_root:
        return os.path.join(_cache_root, *parts)
    return profile_path("icons", *parts)


# ---------------------------------------------------------------------------
# the bundled catalogue
# ---------------------------------------------------------------------------

class Catalogue(object):
    """The bundled list of every free icon, with a name search over it."""

    def __init__(self, data=None):
        data = data or {}
        self.version = str(data.get("version") or VERSION)
        self.styles = tuple(data.get("styles") or STYLES)
        self.aliases = dict(data.get("aliases") or {})
        self.entries = {}
        self.order = []
        for entry in data.get("icons") or ():
            if not entry:
                continue
            name = entry[0]
            codes = entry[1] if len(entry) > 1 else "s"
            label = entry[2] if len(entry) > 2 else ""
            terms = entry[3] if len(entry) > 3 else ""
            styles = tuple(STYLE_CODES[code] for code in codes
                           if code in STYLE_CODES)
            if not styles:
                continue
            self.entries[name] = (styles, label or name.replace("-", " "),
                                  terms)
            self.order.append(name)

    def __len__(self):
        return len(self.order)

    @property
    def count(self):
        return len(self.order)

    def counts(self):
        """How many icons each style holds."""
        found = dict((style, 0) for style in self.styles)
        for styles, _, _ in self.entries.values():
            for style in styles:
                found[style] = found.get(style, 0) + 1
        return found

    def canonical(self, name):
        """Resolve an alias (a name from an older release) to today's name."""
        name = str(name or "").strip().lower()
        if name in self.entries:
            return name
        return self.aliases.get(name)

    def styles_of(self, name):
        entry = self.entries.get(self.canonical(name))
        return entry[0] if entry else ()

    def label_of(self, name):
        entry = self.entries.get(self.canonical(name))
        return entry[1] if entry else ""

    def has(self, name, style=None):
        styles = self.styles_of(name)
        return bool(styles) and (style is None or style in styles)

    def search(self, query="", style=None, offset=0, limit=0):
        """``(total, [(name, style, label), ...])`` for a search box.

        One entry per icon *and* style, so the dialog can offer the outlined
        and the filled version of a name side by side.  Matches are ranked
        so that typing "hear" puts *heart* before *headphones-simple*: the
        name first, then the label, then the search words Font Awesome ships
        with the icon.
        """
        words = [word for word in re.split(r"[\s,]+", str(query or "").lower())
                 if word]
        found = []
        for name in self.order:
            styles, label, terms = self.entries[name]
            if style and style not in styles:
                continue
            score = 0
            for word in words:
                rank = _rank(word, name, label, terms)
                if rank is None:
                    score = None
                    break
                score += rank
            if score is None:
                continue
            for candidate in STYLES:
                if candidate in styles and style in (None, "", candidate):
                    found.append((score, name, candidate, label))
        found.sort(key=lambda entry: (entry[0], entry[1],
                                      STYLES.index(entry[2])))
        total = len(found)
        offset = max(0, int(offset))
        window = found[offset:offset + limit] if limit else found[offset:]
        return total, [(name, best, label) for _, name, best, label in window]


def _rank(word, name, label, terms):
    """How well one search word fits an icon; ``None`` when it does not."""
    if name == word:
        return 0
    if name.startswith(word):
        return 1
    lowered = label.lower()
    if lowered.startswith(word):
        return 2
    if word in name:
        return 3
    if word in lowered:
        return 4
    if re.search(r"(?:^|[\s-])%s" % re.escape(word), terms):
        return 5
    if word in terms:
        return 6
    return None


def catalogue():
    """The bundled catalogue, read from disk on first use."""
    global _catalogue
    with _lock:
        if _catalogue is not None:
            return _catalogue
    data = {}
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (IOError, OSError) as error:
        log("no Font Awesome index at %s (%s)" % (INDEX_PATH, error))
    except ValueError as error:
        log("cannot read the Font Awesome index: %s" % error)
    loaded = Catalogue(data)
    with _lock:
        if _catalogue is None:
            _catalogue = loaded
        return _catalogue


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------

def split_name(text, default_style=None):
    """Split what a layout writes into ``(style, name)``.

    Accepted spellings, all of them case insensitive::

        heart                 the default style
        fa:heart              the same, said explicitly
        solid:heart           a named style
        brands/youtube        either separator works
        fa-regular-heart      the CSS class order
    """
    text = str(text or "").strip().lower()
    if not text:
        return None, ""
    for prefix in ("fa:", "fa-", "fontawesome:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    style = default_style
    for separator in (":", "/"):
        head, found, tail = text.partition(separator)
        if found and head in STYLES and tail:
            return head, tail.strip()
    for candidate in STYLES:
        if text.startswith(candidate + "-") and len(text) > len(candidate) + 1:
            return candidate, text[len(candidate) + 1:]
    return style, text


def resolve(text, default_style=None):
    """``(style, name)`` for an icon that exists, or ``(None, name)``.

    The style is filled in from the catalogue when the layout does not name
    one, which is what makes ``youtube`` find the brand icon.
    """
    style, name = split_name(text, default_style)
    if not name:
        return None, ""
    if not _NAME.match(name):
        return None, name
    book = catalogue()
    canonical = book.canonical(name)
    if canonical is None:
        if book.count:
            # The index knows the whole free set, so an unknown name is a
            # typo rather than something worth a request.
            return None, name
        # Without an index (a stripped down install) the name is taken on
        # trust and the download decides whether it exists.
        return style or default_style or DEFAULT_STYLE, name
    styles = book.styles_of(canonical)
    if style in styles:
        return style, canonical
    if style and style not in styles:
        debug("icon %s has no %s style, using %s" % (canonical, style, styles[0]))
    for candidate in STYLES:
        if candidate in styles:
            return candidate, canonical
    return styles[0], canonical


# ---------------------------------------------------------------------------
# outlines
# ---------------------------------------------------------------------------

class Outline(object):
    """One icon's path data, ready for :mod:`lcd4linux.svgpath`."""

    __slots__ = ("name", "style", "data", "width", "height", "even_odd",
                 "source")

    def __init__(self, name, style, data, width=512.0, height=512.0,
                 even_odd=False, source="cache"):
        self.name = name
        self.style = style
        self.data = data
        self.width = float(width) or 512.0
        self.height = float(height) or 512.0
        self.even_odd = bool(even_odd)
        self.source = source

    @property
    def key(self):
        return "%s/%s" % (self.style, self.name)

    def describe(self):
        """What the editor's dialog needs to draw a preview."""
        return {"name": self.name, "style": self.style, "d": self.data,
                "box": [self.width, self.height],
                "rule": "evenodd" if self.even_odd else "nonzero",
                "source": self.source}


def parse_svg(text, name="", style=""):
    """Pull the outline out of a Font Awesome SVG file."""
    if not text:
        return None
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    paths = _PATH_DATA.findall(text)
    if not paths:
        return None
    width = height = 512.0
    box = _VIEWBOX.search(text)
    if box:
        numbers = box.group(1).replace(",", " ").split()
        if len(numbers) == 4:
            try:
                width = float(numbers[2])
                height = float(numbers[3])
            except ValueError:
                pass
    # Several subpaths in one attribute and several <path> elements mean the
    # same thing to the filler, so they are simply joined.
    return Outline(name, style, " ".join(part.strip() for part in paths),
                   width, height, bool(_EVENODD.search(text)))


def sprites_available():
    """Whether the sprite shortcut can be used.

    Only the Font Awesome CDN is known to serve the sheets; a mirror set in
    the settings may hold nothing but the single icons, so there the cache
    is filled one request at a time instead.
    """
    return _download_url == DOWNLOAD_URL


def cached_file(style, name):
    return cache_dir(style, "%s.json" % name)


def read_cached(style, name):
    """The outline stored on disk, or ``None``."""
    path = cached_file(style, name)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except (IOError, OSError):
        return None
    except ValueError:
        log("discarding damaged icon cache entry %s" % path)
        _remove(path)
        return None
    if str(stored.get("version") or "") != VERSION or not stored.get("d"):
        # A different Font Awesome release drew this one; fetch it again so
        # the picture matches what the dialog showed.
        return None
    box = stored.get("box") or [512, 512]
    return Outline(name, style, stored["d"], box[0], box[1],
                   stored.get("rule") == "evenodd", "cache")


def write_cached(outline):
    """Store an outline so it is there the next time, network or not."""
    path = cached_file(outline.style, outline.name)
    directory = os.path.dirname(path)
    try:
        if not os.path.isdir(directory):
            os.makedirs(directory)
        temporary = "%s.%d.tmp" % (path, os.getpid())
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"version": VERSION, "name": outline.name,
                       "style": outline.style,
                       "box": [outline.width, outline.height],
                       "rule": "evenodd" if outline.even_odd else "nonzero",
                       "d": outline.data}, handle)
        # Renamed into place so a half written file is never read back.
        if os.path.exists(path):
            os.remove(path)
        os.rename(temporary, path)
        return True
    except (IOError, OSError) as error:
        log("cannot cache icon %s: %s" % (outline.key, error))
        return False


def _remove(path):
    try:
        os.remove(path)
    except (IOError, OSError):
        pass


def download(style, name):
    """Fetch one outline from the CDN.  Returns ``None`` on any failure."""
    global _offline_until
    if style not in STYLES or not _NAME.match(name or ""):
        # The name goes into a URL, so it is checked here too and not only
        # where it came from.
        return None
    url = _download_url % {"version": VERSION, "style": style, "name": name}
    try:
        request = Request(url, headers={
            "User-Agent": "script.lcd4linux (Kodi add-on)",
            "Accept": "image/svg+xml,*/*",
        })
        handle = urlopen(request, timeout=TIMEOUT)
        try:
            body = handle.read(262144)
        finally:
            handle.close()
    except Exception as error:
        # Anything from a DNS failure to a 404 lands here.  A 4xx means the
        # CDN answered and this one name is simply not there, so the other
        # icons are still worth trying; anything else says the box cannot
        # reach the network and pauses every download for a while.
        served = isinstance(error, HTTPError) and 400 <= int(
            getattr(error, "code", 0) or 0) < 500
        if not served:
            with _lock:
                _offline_until = time.time() + OFFLINE_SECONDS
        log("cannot download icon %s/%s: %s" % (style, name, error))
        return None
    outline = parse_svg(body, name, style)
    if outline is None:
        log("icon %s/%s is not an SVG" % (style, name))
        return None
    outline.source = "download"
    write_cached(outline)
    debug("downloaded icon %s/%s" % (style, name))
    return outline


def parse_sprite(text, style):
    """Every icon of a Font Awesome sprite sheet, as :class:`Outline`s."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    found = []
    for attributes, body in _SYMBOL.findall(text or ""):
        match = _SYMBOL_ID.search(attributes)
        if not match:
            continue
        name = match.group(1).strip().lower()
        if not _NAME.match(name):
            continue
        outline = parse_svg("<svg %s>%s</svg>" % (attributes, body), name,
                            style)
        if outline is not None:
            outline.source = "sprite"
            found.append(outline)
    return found


def fetch_style(style, progress=None):
    """Cache a whole style from its sprite sheet in one request.

    Returns ``(stored, total)``.  ``progress(done, total, name)`` is called
    as the icons are written and may return ``False`` to stop.
    """
    global _offline_until
    if style not in STYLES:
        return 0, 0
    if not _downloads or not sprites_available():
        return 0, 0
    url = SPRITE_URL % {"version": VERSION, "style": style}
    try:
        request = Request(url, headers={
            "User-Agent": "script.lcd4linux (Kodi add-on)",
            "Accept": "image/svg+xml,*/*",
        })
        handle = urlopen(request, timeout=max(TIMEOUT, 30.0))
        try:
            body = handle.read(SPRITE_LIMIT)
        finally:
            handle.close()
    except Exception as error:
        with _lock:
            _offline_until = time.time() + OFFLINE_SECONDS
        log("cannot download the %s sprite: %s" % (style, error))
        return 0, 0
    outlines = parse_sprite(body, style)
    total = len(outlines)
    stored = 0
    for index, outline in enumerate(outlines):
        if progress is not None and progress(index, total,
                                            outline.name) is False:
            break
        if write_cached(outline):
            stored += 1
    log("cached %d of %d %s icons from the sprite sheet"
        % (stored, total, style))
    return stored, total


def _remember(outline):
    with _lock:
        _outlines[(outline.style, outline.name)] = outline
        if len(_outlines) > MEMORY_LIMIT:
            for key in list(_outlines)[:len(_outlines) - MEMORY_LIMIT]:
                _outlines.pop(key, None)
        _misses.pop((outline.style, outline.name), None)


def lookup(style, name):
    """The outline from memory or disk, without touching the network."""
    if not style or not name:
        return None
    key = (style, name)
    with _lock:
        outline = _outlines.get(key)
    if outline is not None:
        return outline
    outline = read_cached(style, name)
    if outline is not None:
        _remember(outline)
    return outline


def outline(text, default_style=None, allow_download=True):
    """The outline for an icon, downloading it if need be.

    This one waits for the network, so it is for the editor and the cache
    tools; the renderer uses :func:`request`.
    """
    style, name = resolve(text, default_style)
    if not style or not name:
        return None
    found = lookup(style, name)
    if found is not None:
        return found
    if not allow_download or not _downloads:
        return None
    return outline_of(style, name)


def request(text, default_style=None):
    """The outline if it is already here, otherwise queue a download.

    Called once per frame per icon, so it never waits: the first frames
    after a fresh install draw nothing and the icon appears as soon as the
    background thread has it.
    """
    style, name = resolve(text, default_style)
    if not style or not name:
        return None
    found = lookup(style, name)
    if found is not None:
        return found
    if not _downloads:
        return None
    now = time.time()
    with _lock:
        missed = _misses.get((style, name))
        if missed is not None and now - missed < MISS_SECONDS:
            return None
        if now < _offline_until:
            return None
        if (style, name) in _queue:
            return None
        _queue.append((style, name))
    _start_worker()
    _wake.set()
    return None


# ---------------------------------------------------------------------------
# the background fetcher
# ---------------------------------------------------------------------------

def _start_worker():
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        if _stopping:
            return
        _worker = threading.Thread(target=_pump, name="lcd4linux-icons")
        _worker.daemon = True
        _worker.start()


def _pump():
    """Download queued icons until the queue stays empty for a while."""
    global _active
    idle = 0
    while not _stopping:
        with _lock:
            job = _queue.pop(0) if _queue else None
            if job is not None:
                _active += 1
        if job is None:
            _wake.clear()
            if idle >= 4:
                return
            idle += 1
            _wake.wait(5.0)
            continue
        idle = 0
        style, name = job
        try:
            if lookup(style, name) is not None:
                continue
            found = download(style, name)
            if found is None:
                with _lock:
                    _misses[(style, name)] = time.time()
            else:
                _remember(found)
        finally:
            with _lock:
                _active -= 1


def stop():
    """Ask the background thread to finish; used when the service shuts down."""
    global _stopping
    _stopping = True
    _wake.set()
    worker = _worker
    if worker is not None and worker.is_alive():
        worker.join(2.0)
    # Reset so a service that starts again in the same Kodi process (a
    # reload, or the script entry point after the service) still fetches.
    _stopping = False
    _wake.clear()


def pending():
    """How many icons are waiting for or busy with a download."""
    with _lock:
        return len(_queue) + _active


def drain(timeout=30.0):
    """Wait for the queued downloads, for the tools and the self test."""
    _start_worker()
    _wake.set()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pending():
            return True
        time.sleep(0.05)
    return not pending()


# ---------------------------------------------------------------------------
# cache maintenance
# ---------------------------------------------------------------------------

def cache_state():
    """``{count, bytes, directory, version}`` describing the icon cache."""
    root = cache_dir()
    count = 0
    size = 0
    for style in STYLES:
        directory = os.path.join(root, style)
        try:
            names = os.listdir(directory)
        except (IOError, OSError):
            continue
        for entry in names:
            if not entry.endswith(".json"):
                continue
            count += 1
            try:
                size += os.path.getsize(os.path.join(directory, entry))
            except (IOError, OSError):
                pass
    book = catalogue()
    return {"count": count, "bytes": size, "directory": root,
            "version": VERSION, "total": book.count,
            "variants": sum(book.counts().values()),
            "downloads": bool(_downloads)}


def clear_cache():
    """Delete every cached outline.  Returns how many files went."""
    root = cache_dir()
    removed = 0
    for style in STYLES:
        directory = os.path.join(root, style)
        try:
            names = os.listdir(directory)
        except (IOError, OSError):
            continue
        for entry in names:
            if entry.endswith(".json") or entry.endswith(".tmp"):
                _remove(os.path.join(directory, entry))
                removed += 1
    with _lock:
        _outlines.clear()
        _misses.clear()
        del _queue[:]
    return removed


def prefetch(icons=None, style=None, progress=None, allow_download=True):
    """Fill the cache up front, for a box that will be offline later.

    ``icons`` is an iterable of names (any spelling :func:`split_name`
    understands).  Without it the whole catalogue is fetched, which goes
    through the sprite sheets: one request per style instead of a couple of
    thousand.  ``progress`` is called as ``progress(done, total, name)`` so
    the Kodi dialog can show a bar.  Returns ``(cached, fetched, failed)``.
    """
    book = catalogue()
    if icons is None:
        wanted = [style] if style in STYLES else list(STYLES)
        counts = book.counts()
        expected = sum(counts.get(entry, 0) for entry in wanted) or 1
        done = 0
        cached = fetched = failed = 0
        for entry in wanted:
            offset = done
            done += counts.get(entry, 0)

            def step(index, total, name, base=offset):
                return progress(base + index, expected, name) \
                    if progress is not None else None

            stored, _total = fetch_style(entry, step if progress else None)
            if stored:
                fetched += stored
                failed += max(0, counts.get(entry, 0) - stored)
                continue
            # No sheet to be had (a mirror, or the request failed): fall
            # back to one request per icon for this style.
            names = ["%s:%s" % (found, name) for name, found, _label
                     in book.search(style=entry, limit=0)[1]]
            one_by_one = prefetch(names, progress=step,
                                  allow_download=allow_download)
            cached += one_by_one[0]
            fetched += one_by_one[1]
            failed += one_by_one[2]
        return cached, fetched, failed
    pairs = []
    for entry in icons:
        found = resolve(entry, style)
        if found[0] and found[1]:
            pairs.append(found)
    total = len(pairs)
    cached = fetched = failed = 0
    for index, (icon_style, name) in enumerate(pairs):
        if progress is not None and progress(index, total, name) is False:
            break
        if lookup(icon_style, name) is not None:
            cached += 1
            continue
        if not allow_download or not _downloads:
            failed += 1
            continue
        found = download(icon_style, name)
        if found is None:
            failed += 1
        else:
            _remember(found)
            fetched += 1
    return cached, fetched, failed


#: Missing icons of one style in a single request before the whole sprite
#: sheet is fetched instead.  Browsing a style page by page ends up pulling
#: most of it anyway, and one request beats fifty.
SPRITE_THRESHOLD = 4


def resolve_many(names, default_style=None, allow_download=True,
                 sprite_threshold=SPRITE_THRESHOLD):
    """Outlines for several icons, in the order they were asked for.

    Entries that do not exist come back as ``None``.  When a lot of one
    style is missing at once - which is what scrolling the icon dialog looks
    like - the style's sprite sheet is fetched once and every icon in it
    lands in the cache, so the next page needs no network at all.
    """
    pairs = [resolve(name, default_style) for name in names]
    found = [lookup(style, name) if style and name else None
             for style, name in pairs]
    if not allow_download or not _downloads:
        return found
    missing = {}
    for index, outline in enumerate(found):
        style, name = pairs[index]
        if outline is None and style and name:
            missing.setdefault(style, []).append(index)
    for style, indexes in sorted(missing.items()):
        if len(indexes) < sprite_threshold:
            continue
        if fetch_style(style)[0]:
            for index in list(indexes):
                found[index] = lookup(*pairs[index])
    for index, outline in enumerate(found):
        if outline is not None:
            continue
        style, name = pairs[index]
        if style and name:
            found[index] = outline_of(style, name)
    return found


def outline_of(style, name):
    """Download one icon, remembering a failure so it is not retried at once."""
    with _lock:
        if time.time() < _offline_until:
            return None
        missed = _misses.get((style, name))
        if missed is not None and time.time() - missed < MISS_SECONDS:
            return None
    found = download(style, name)
    if found is None:
        with _lock:
            _misses[(style, name)] = time.time()
        return None
    _remember(found)
    return found


def used_by(spec, builtin=()):
    """Every icon a layout spec refers to, as ``(style, name)`` pairs.

    Token driven names (``${...}``) cannot be known in advance and are
    skipped, so what comes back is what a "cache this layout" button can
    actually fetch.  ``builtin`` names the shapes the renderer draws
    itself - those need no download and are left out.
    """
    found = []

    def walk(node, default_style=None):
        if isinstance(node, dict):
            style = node.get("style") if isinstance(node.get("style"), str) \
                else default_style
            name = node.get("icon") if node.get("type") == "icon" else None
            if isinstance(name, str) and name and "${" not in name \
                    and name.strip().lower() not in builtin:
                pair = resolve(name, style)
                if pair[0] and pair[1] and pair not in found:
                    found.append(pair)
            for value in node.values():
                walk(value, style)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value, default_style)

    walk(spec, None)
    return found
