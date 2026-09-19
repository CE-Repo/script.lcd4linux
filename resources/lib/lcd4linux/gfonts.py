"""Google Fonts, searchable offline and fetched when a layout uses one.

The same split as :mod:`.faicons`: the add-on ships the *index* of the whole
library - every family, its kind and the weights it has - in
``resources/fonts/googlefonts.json``, so the editor's font dialog can be
searched with no network at all.  A face is downloaded the first time
something actually draws with it and kept in ``<profile>/gfonts``, which is
what makes a box that boots without internet still show the fonts its
layouts use.

Nothing here blocks the renderer.  :func:`request` answers from the cache
and hands anything missing to a background thread, so a frame is never held
up by an HTTP request; until the file is there the layout falls back to a
bundled family.

Fonts: SIL Open Font License or Apache 2.0 - https://fonts.google.com/attribution
"""

import json
import os
import re
import threading
import time

from .logger import debug, log

#: Where the CSS that names the real file comes from.  Which format comes
#: back depends on what the caller looks like: a current browser is offered
#: WOFF2, which needs Brotli and the standard library has none.  An agent
#: Google does not recognise - this add-on, say - falls through to plain
#: TrueType, so asking honestly happens to be exactly right here.  No key,
#: no quota.
CSS_URL = "https://fonts.googleapis.com/css2"

#: How this add-on introduces itself when it asks.
AGENT = "script.lcd4linux (Kodi add-on)"

#: Weight a plain family is drawn at, and the one ``-bold`` asks for.
REGULAR = 400
BOLD = 700

#: Where a licence is looked for once a family has been fetched, in order.
LICENCE_URLS = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/%s/OFL.txt",
    "https://raw.githubusercontent.com/google/fonts/main/apache/%s/LICENSE.txt",
    "https://raw.githubusercontent.com/google/fonts/main/ufl/%s/UFL.txt",
)

#: Seconds an HTTP request may take before it is given up on.
TIMEOUT = 15.0

#: A face that could not be fetched is not tried again for this long, and
#: every download pauses this long once the network itself has failed.  One
#: unreachable host should cost one timeout, not one per frame.
MISS_SECONDS = 300.0
OFFLINE_SECONDS = 60.0

#: Nothing on Google Fonts comes close; this is only here so a redirect to
#: something enormous cannot fill the user's disk.
SIZE_LIMIT = 8 * 1024 * 1024

#: What a face has to start with to be one.  ``\x00\x01\x00\x00`` is
#: TrueType, ``OTTO`` is OpenType with PostScript outlines, ``true`` is the
#: old Apple spelling.
_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")

#: ``src: url(...) format('truetype')`` out of the CSS.  The format is the
#: interesting half: a reply that offers WOFF2 is no use here, and saying so
#: beats downloading a megabyte that cannot be unpacked.
_SOURCE = re.compile(r"url\((?P<url>[^)]+)\)"
                     r"(?:\s*format\('(?P<format>[^']*)'\))?")
_UNSAFE = re.compile(r"[^A-Za-z0-9]+")

_lock = threading.RLock()
_wake = threading.Event()
_queue = []
_misses = {}
_worker = None
_active = 0
_stopping = False
_offline_until = 0.0
_catalogue = None
_index_path = None
_cache_root = None
_downloads = True
_css_url = CSS_URL
_state_cache = None

#: Bumped every time a face lands, so :class:`~.bmfont.FontCache` can tell
#: that a family it had to substitute is now available.
generation = 0

_http = None


def http():
    """``(Request, urlopen, HTTPError)``, imported on first use.

    Same reasoning as in :mod:`.faicons`: the renderer imports this module
    for every frame but only ever downloads on a cache miss, and
    :mod:`urllib.request` drags :mod:`http.client`, :mod:`email` and
    :mod:`ssl` in behind it.
    """
    global _http
    if _http is None:
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        _http = (Request, urlopen, HTTPError)
    return _http


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

def configure(config=None, downloads=None, url=None, cache=None):
    """Apply the add-on settings (or explicit overrides) to this module."""
    global _downloads, _css_url, _cache_root
    if config is not None:
        _downloads = bool(config.get("font_download", True))
        source = str(config.get("font_source", "") or "").strip()
        _css_url = source or CSS_URL
    if downloads is not None:
        _downloads = bool(downloads)
    if url is not None:
        _css_url = url or CSS_URL
    if cache is not None:
        _cache_root = cache or None


def downloads_enabled():
    return bool(_downloads)


def index_path():
    """The bundled catalogue file."""
    global _index_path
    if _index_path is None:
        from .settings import addon_path
        _index_path = addon_path("resources", "fonts", "googlefonts.json")
    return _index_path


def cache_dir(*parts):
    """Where downloaded faces live.

    Deliberately not the user's own ``fonts`` folder: that one is scanned
    for families by file name, and a cache full of ``RobotoMono-700.ttf``
    would turn every download into a family nobody named.
    """
    if _cache_root:
        return os.path.join(_cache_root, *parts)
    from .settings import profile_path
    return profile_path("gfonts", *parts)


# ---------------------------------------------------------------------------
# the bundled catalogue
# ---------------------------------------------------------------------------

class Catalogue(object):
    """Every family Google serves, in the order the dialog shows them."""

    def __init__(self, data=None):
        data = data or {}
        self.generated = str(data.get("generated") or "")
        self.categories = dict(data.get("categories") or {})
        self.order = []
        self.entries = {}
        for row in data.get("families") or ():
            if not row:
                continue
            name = row[0]
            category = row[1] if len(row) > 1 else "s"
            weights = row[2] if len(row) > 2 else "4"
            italic = bool(row[3]) if len(row) > 3 else False
            self.entries[name.lower()] = {
                "name": name,
                "category": self.categories.get(category, "Sans Serif"),
                "weights": [int(digit) * 100 for digit in weights
                            if digit.isdigit()],
                "italic": italic,
            }
            self.order.append(name)

    def __len__(self):
        return len(self.order)

    @property
    def count(self):
        return len(self.order)

    def get(self, family):
        """The entry for ``family``, matched without regard to case."""
        return self.entries.get(str(family or "").strip().lower())

    def search(self, query="", category=None, offset=0, limit=60):
        """``(total, [entry, ...])`` for the dialog, most popular first.

        Eighteen hundred families is more than a dialog can show at once,
        so this pages the way the icon catalogue does.
        """
        words = [word for word in str(query or "").lower().split() if word]
        found = []
        for name in self.order:
            entry = self.entries[name.lower()]
            if category and entry["category"] != category:
                continue
            if words:
                haystack = name.lower()
                if not all(word in haystack for word in words):
                    continue
            found.append(entry)
        total = len(found)
        offset = max(0, int(offset or 0))
        rows = found[offset:offset + limit] if limit else found[offset:]
        return total, rows

    def nearest_weight(self, family, wanted):
        """The weight this family really has that is closest to ``wanted``."""
        entry = self.get(family)
        if not entry or not entry["weights"]:
            return wanted
        return min(entry["weights"], key=lambda w: (abs(w - wanted), w))


def catalogue():
    """The bundled index, read once."""
    global _catalogue
    if _catalogue is None:
        try:
            with open(index_path(), "r", encoding="utf-8") as handle:
                _catalogue = Catalogue(json.load(handle))
        except Exception as error:
            log("cannot read the Google Fonts index: %s" % error)
            _catalogue = Catalogue()
    return _catalogue


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------

#: Weight names a layout may write after the family, as the add-on already
#: spells a bold cut of a bundled one.
WEIGHT_NAMES = (("-bold", BOLD), ("-black", 900), ("-light", 300),
                ("-medium", 500), ("-thin", 100))


def split_name(text):
    """``("Roboto Mono", 700)`` out of what a layout wrote.

    A layout names a Google family the way Google spells it and gets the
    bold cut the same way it does with a bundled one, by a ``-bold``
    suffix - which is also what ``bold: true`` appends.  A plain number is
    understood too, which is how this module writes a cut down for its own
    queue and for :func:`used_by`.
    """
    name = str(text or "").strip()
    lowered = name.lower()
    for suffix, value in WEIGHT_NAMES:
        if lowered.endswith(suffix):
            return name[:-len(suffix)].strip(), value
    head, dash, tail = name.rpartition("-")
    if dash and head and tail.isdigit() and 1 <= len(tail) <= 4:
        return head.strip(), int(tail)
    return name, REGULAR


def resolve(text):
    """``(family, weight)`` as the catalogue spells them, or ``(None, 0)``."""
    name, weight = split_name(text)
    entry = catalogue().get(name)
    if entry is None:
        return None, 0
    return entry["name"], catalogue().nearest_weight(entry["name"], weight)


def name_for(family, weight):
    """How one cut is written where a single string is wanted."""
    return family if weight == REGULAR else "%s-%d" % (family, weight)


def slug(family, weight):
    """The cache file name for one cut, e.g. ``RobotoMono-700.ttf``."""
    return "%s-%d.ttf" % (_UNSAFE.sub("", family) or "font", weight)


def _directory_slug(family):
    """How the google/fonts repository spells a family in a path."""
    return _UNSAFE.sub("", family).lower()


# ---------------------------------------------------------------------------
# the cache
# ---------------------------------------------------------------------------

def cached_path(family, weight):
    """The file this cut would be cached in, whether or not it is there."""
    return cache_dir(slug(family, weight))


def lookup(text):
    """The path of an already cached face, or ``None``."""
    family, weight = resolve(text)
    if not family:
        return None
    path = cached_path(family, weight)
    return path if os.path.exists(path) else None


def _write(path, data):
    """Write a face, through a temporary file so a crash leaves no stub."""
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        try:
            os.makedirs(directory)
        except OSError:
            pass
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except (IOError, OSError) as error:
        _remove(tmp)
        log("cannot write %s: %s" % (path, error))
        return False
    return True


def _remove(path):
    try:
        os.remove(path)
    except (IOError, OSError):
        pass


# ---------------------------------------------------------------------------
# downloading
# ---------------------------------------------------------------------------

def _get(url, agent=AGENT, limit=SIZE_LIMIT):
    """Fetch a URL, returning the body or ``None``.

    Any failure that is not the server saying "no such thing" pauses every
    download for a while: a box with no route out should cost one timeout,
    not one per font on the page.
    """
    global _offline_until
    Request, urlopen, HTTPError = http()
    try:
        request = Request(url, headers={"User-Agent": agent or AGENT})
        handle = urlopen(request, timeout=TIMEOUT)
        try:
            return handle.read(limit)
        finally:
            handle.close()
    except Exception as error:
        served = isinstance(error, HTTPError) and 400 <= int(
            getattr(error, "code", 0) or 0) < 500
        if not served:
            with _lock:
                _offline_until = time.time() + OFFLINE_SECONDS
        debug("cannot fetch %s: %s" % (url, error))
        return None


def file_url(family, weight):
    """Ask Google which file to download for one cut.

    Only the Latin subset: it is a fraction of the size and already covers
    every character the add-on draws - ASCII, Latin-1 and Latin Extended-A.
    """
    from urllib.parse import urlencode
    query = urlencode({"family": "%s:wght@%d" % (family, weight),
                       "subset": "latin"})
    body = _get("%s?%s" % (_css_url, query), limit=65536)
    if body is None:
        return None
    text = body.decode("utf-8", "replace")
    fallback = None
    for match in _SOURCE.finditer(text):
        kind = (match.group("format") or "").lower()
        if kind in ("truetype", "opentype"):
            return match.group("url")
        if fallback is None:
            fallback = match.group("url")
    if fallback is None:
        # The family is unknown, or the answer was not CSS at all.
        debug("no font file for %s %d in the CSS answer" % (family, weight))
        return None
    # Something was offered but not in a format that was named as one this
    # add-on reads.  Worth trying - the magic bytes decide - but worth a
    # line in the log if it turns out to be WOFF2 after all.
    debug("%s %d came back as an unnamed format" % (family, weight))
    return fallback


def _fetch_licence(family):
    """Keep the licence next to the face, so the cache may be redistributed."""
    target = cache_dir("%s.LICENSE.txt" % (_UNSAFE.sub("", family) or "font"))
    if os.path.exists(target):
        return True
    name = _directory_slug(family)
    for pattern in LICENCE_URLS:
        body = _get(pattern % name, limit=262144)
        if body:
            return _write(target, body)
    debug("no licence found for %s" % family)
    return False


def download(text):
    """Fetch one cut.  Returns its path, or ``None`` on any failure."""
    global generation
    family, weight = resolve(text)
    if not family:
        return None
    path = cached_path(family, weight)
    if os.path.exists(path):
        return path
    url = file_url(family, weight)
    if url is None:
        return None
    body = _get(url)
    if not body:
        return None
    if not body.startswith(_MAGIC):
        # Almost always WOFF2 (``wOF2``), which needs Brotli; the standard
        # library has none, so there is nothing to be done with it.
        log("what came back for %s %d is not a font this add-on reads (%r)"
            % (family, weight, body[:4]))
        return None
    if not _write(path, body):
        return None
    _fetch_licence(family)
    with _lock:
        generation += 1
    global _state_cache
    _state_cache = None
    log("downloaded font %s %d (%.0f kB)" % (family, weight,
                                             len(body) / 1024.0))
    return path


def request(text):
    """The path if the face is here, otherwise queue it and return ``None``.

    Called from the renderer, so it never waits: the layout draws in a
    fallback family until the background thread has the real one.
    """
    family, weight = resolve(text)
    if not family:
        return None
    path = cached_path(family, weight)
    if os.path.exists(path):
        return path
    if not _downloads:
        return None
    now = time.time()
    with _lock:
        missed = _misses.get((family, weight))
        if missed is not None and now - missed < MISS_SECONDS:
            return None
        if now < _offline_until:
            return None
        if (family, weight) in _queue:
            return None
        _queue.append((family, weight))
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
        _worker = threading.Thread(target=_pump, name="lcd4linux-fonts")
        _worker.daemon = True
        _worker.start()


def _pump():
    """Download queued faces until the queue stays empty for a while."""
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
        family, weight = job
        try:
            if download(name_for(family, weight)) is None:
                with _lock:
                    _misses[(family, weight)] = time.time()
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
    # Reset so a service that starts again in the same Kodi process still
    # fetches.
    _stopping = False
    _wake.clear()


def pending():
    """How many faces are waiting for or busy with a download."""
    with _lock:
        return len(_queue) + _active


def drain(timeout=60.0):
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

def cache_state(max_age=2.0):
    """``{count, bytes, directory, total}`` describing the font cache."""
    global _state_cache
    snapshot = _state_cache
    if snapshot is not None and max_age and time.time() - snapshot[0] < max_age:
        return dict(snapshot[1])
    root = cache_dir()
    count = 0
    size = 0
    try:
        names = os.listdir(root)
    except (IOError, OSError):
        names = []
    for entry in names:
        if not entry.endswith(".ttf"):
            continue
        count += 1
        try:
            size += os.path.getsize(os.path.join(root, entry))
        except (IOError, OSError):
            pass
    found = {"count": count, "bytes": size, "directory": root,
             "total": catalogue().count, "downloads": bool(_downloads),
             "generated": catalogue().generated}
    _state_cache = (time.time(), found)
    return dict(found)


def cached_families():
    """Every family that has at least one cut on disk, spelled properly."""
    wanted = {}
    for name in catalogue().order:
        wanted[_UNSAFE.sub("", name)] = name
    found = set()
    try:
        names = os.listdir(cache_dir())
    except (IOError, OSError):
        return []
    for entry in names:
        if not entry.endswith(".ttf"):
            continue
        stem = entry[:-4].rpartition("-")[0]
        if stem in wanted:
            found.add(wanted[stem])
    return sorted(found)


def clear_cache():
    """Delete every cached face.  Returns how many files went."""
    global _state_cache
    removed = 0
    try:
        names = os.listdir(cache_dir())
    except (IOError, OSError):
        names = []
    for entry in names:
        if entry.endswith((".ttf", ".tmp", ".LICENSE.txt")):
            _remove(cache_dir(entry))
            removed += 1
    _state_cache = None
    with _lock:
        _misses.clear()
        del _queue[:]
    return removed


def prefetch(families=None, progress=None):
    """Fill the cache up front, for a box that will be offline later.

    ``families`` is an iterable of names as a layout writes them; without
    it every family a layout already uses is fetched.  ``progress`` is
    called as ``progress(done, total, name)`` so the Kodi dialog can show a
    bar.  Returns ``(cached, fetched, failed)``.
    """
    wanted = []
    for entry in families or ():
        family, weight = resolve(entry)
        if family and (family, weight) not in wanted:
            wanted.append((family, weight))
    total = len(wanted)
    cached = fetched = failed = 0
    for index, (family, weight) in enumerate(wanted):
        if progress is not None and progress(index, total, family) is False:
            break
        if os.path.exists(cached_path(family, weight)):
            cached += 1
            continue
        if not _downloads:
            failed += 1
            continue
        if download(name_for(family, weight)) is None:
            failed += 1
        else:
            fetched += 1
    return cached, fetched, failed


def used_by(spec, bundled=()):
    """Every Google family a layout spec names, as a layout writes them.

    Token driven names (``${...}``) cannot be known in advance and are
    skipped, and so is anything the add-on already ships, so what comes
    back is what a "cache this layout" button can actually fetch.
    """
    known = set(bundled)
    found = []

    def remember(value, bold=False):
        if not isinstance(value, str) or not value or "${" in value:
            return
        name = "%s-bold" % value if bold else value
        if name in known or value in known:
            return
        family, weight = resolve(name)
        if not family:
            return
        entry = name_for(family, weight)
        if entry not in found:
            found.append(entry)

    def walk(node, inherited):
        if isinstance(node, dict):
            family = node.get("font")
            if not isinstance(family, str):
                family = inherited
            if isinstance(node.get("font"), str):
                remember(node["font"], bool(node.get("bold")))
            elif family and node.get("bold"):
                remember(family, True)
            defaults = node.get("defaults")
            if isinstance(defaults, dict) and isinstance(defaults.get("font"),
                                                         str):
                inherited = defaults["font"]
                remember(inherited)
            for value in node.values():
                walk(value, family or inherited)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value, inherited)

    walk(spec, None)
    return found
