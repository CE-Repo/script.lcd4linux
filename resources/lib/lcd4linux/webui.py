"""The browser based layout editor ("Baukasten").

The service can run a small HTTP server that serves a drag and drop editor
for the JSON layouts.  Everything is stdlib: :mod:`http.server` in a daemon
thread, no framework, no external assets - a CoreELEC box has no package
manager to install one from, and the browser may have no internet either.

The interesting part is the preview: instead of guessing in JavaScript what
a layout will look like, the page posts the layout being edited to
``/api/preview`` and gets back a PNG drawn by the very renderer that feeds
the panel.  The editor only draws selection boxes on top of it, so what is
dragged around is always what the display will show.

API
---

======================== ========================================
``GET  /``               the editor page
``GET  /api/schema``     widget types, fields, tokens, fonts, icons
``GET  /api/state``      active layout, panel size, service status
``GET  /api/layouts``    every layout the add-on can see
``GET  /api/layout``     one layout: ``?file=default.json``
``POST /api/layout``     save ``{"file": ..., "spec": {...}}``
``POST /api/delete``     remove a layout from the user folder
``POST /api/activate``   make a layout the one shown on the panel
``POST /api/preview``    render a layout to a PNG
``POST /api/command``    reload, next page or test pattern
======================== ========================================
"""

import base64
import json
import os
import re
import threading
import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import layout as layout_module
from . import pngio
from . import webschema
from .logger import debug, error, log
from .settings import Config, addon_path, ensure_user_directories, profile_path

try:
    import xbmc  # type: ignore
    import xbmcgui  # type: ignore
except ImportError:
    xbmc = None
    xbmcgui = None

#: Layout files may only be named like this: the name reaches the file
#: system, so no directories, no dots leading anywhere.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}\.json$")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

#: Uploaded layouts larger than this are refused; the biggest bundled one is
#: about 12 kB, so this is roomy without letting a stray POST eat the box.
MAX_BODY = 2 * 1024 * 1024


class EditorError(Exception):
    """Something the browser did wrong; reported as a 400 with a message."""


# ---------------------------------------------------------------------------
# layout files
# ---------------------------------------------------------------------------

def user_directory(config=None):
    """Where the editor saves: the user's layout folder."""
    config = config or Config()
    return config.get("layout_dir") or profile_path("layouts")


def safe_name(name):
    """Check a layout file name, rather than repair one.

    Quietly turning ``../evil.json`` into ``evil.json`` would write a file
    the browser did not ask for, so anything with a path in it is refused.
    """
    name = (name or "").strip()
    if "/" in name or "\\" in name or name.startswith("."):
        raise EditorError("invalid file name %r" % name)
    if not name.lower().endswith(".json"):
        name += ".json"
    if not SAFE_NAME.match(name):
        raise EditorError("invalid file name %r" % name)
    return name


def list_layouts(config=None):
    """Every layout, with its size and where it came from."""
    config = config or Config()
    directories = config.layout_directories
    user_dir = os.path.abspath(directories[0]) if directories else ""
    entries = []
    for name, path in sorted(layout_module.discover(directories).items()):
        entry = {"file": name, "path": path, "name": name,
                 "user": os.path.abspath(os.path.dirname(path)) == user_dir,
                 "size": None, "pages": 0, "error": ""}
        try:
            parsed = layout_module.Layout.load(path)
            entry["name"] = parsed.name
            entry["size"] = [parsed.width, parsed.height]
            entry["pages"] = len(parsed.pages)
        except Exception as err:
            entry["error"] = str(err)
        entries.append(entry)
    return entries


def read_layout(name, config=None):
    config = config or Config()
    name = safe_name(name)
    available = layout_module.discover(config.layout_directories)
    path = available.get(name)
    if path is None:
        raise EditorError("no layout called %s" % name)
    with open(path, "r", encoding="utf-8-sig") as handle:
        text = handle.read()
    directories = config.layout_directories
    user_dir = os.path.abspath(directories[0]) if directories else ""
    return {"file": name, "spec": json.loads(_strip_comments(text)),
            "path": path, "strings": translations(text),
            "user": os.path.abspath(os.path.dirname(path)) == user_dir}


def translations(text):
    """``{"32403": "Musik"}`` for every ``$LOCALIZE[...]`` in a layout.

    The editor shows page names as they will read on the panel, without
    having to know the string table itself.
    """
    from . import localize
    found = {}
    for number in set(re.findall(r"\$LOCALIZE\[(\d+)\]", text)):
        found[number] = localize.text(number)
    return found


def write_layout(name, spec, config=None):
    """Store a layout in the user folder, atomically.

    A bundled name is allowed: the user folder comes first in the search
    path, so saving ``default.json`` shadows the shipped one instead of
    overwriting it - and deleting the copy brings the original back.
    """
    name = safe_name(name)
    validate(spec)
    ensure_user_directories()
    directory = user_directory(config)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    path = os.path.join(directory, name)
    temporary = path + ".tmp"
    data = json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=False)
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(data + "\n")
    os.replace(temporary, path)
    log("layout saved from the web editor: %s" % path)
    return path


def delete_layout(name, config=None):
    name = safe_name(name)
    path = os.path.join(user_directory(config), name)
    if not os.path.isfile(path):
        raise EditorError("%s is not in the user folder" % name)
    os.remove(path)
    log("layout deleted from the web editor: %s" % path)
    return path


def validate(spec):
    """Refuse anything the renderer could not read back."""
    if not isinstance(spec, dict):
        raise EditorError("a layout must be a JSON object")
    size = spec.get("size")
    if not (isinstance(size, (list, tuple)) and len(size) == 2):
        raise EditorError('"size" must be [width, height]')
    try:
        width, height = int(size[0]), int(size[1])
    except (TypeError, ValueError):
        raise EditorError('"size" must be two numbers')
    if not (16 <= width <= 4096 and 16 <= height <= 4096):
        raise EditorError("the size must be between 16 and 4096 pixels")
    pages = spec.get("pages")
    if not isinstance(pages, list) or not pages:
        raise EditorError("a layout needs at least one page")
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise EditorError("page %d is not an object" % (index + 1))
        widgets = page.get("widgets", [])
        if not isinstance(widgets, list):
            raise EditorError('the "widgets" of page %d is not a list'
                              % (index + 1))
        for widget in widgets:
            if not isinstance(widget, dict):
                raise EditorError("page %d has a widget that is not an object"
                                  % (index + 1))
            kind = str(widget.get("type", "text")).lower()
            if kind not in webschema.WIDGET_FIELDS:
                raise EditorError("unknown widget type %r" % kind)
    # Parsing it is the real test: it builds every widget the way the
    # service will.
    layout_module.Layout(spec)
    return True


def _strip_comments(text):
    lines = [line for line in text.splitlines()
             if not line.strip().startswith(("//", "#"))]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# preview rendering
# ---------------------------------------------------------------------------

class PreviewRenderer(object):
    """Draws layout previews with the add-on's own renderer.

    Fonts and decoded pictures are expensive to build, so they are kept
    between requests; a lock keeps two browser tabs from rendering into the
    same caches at once.
    """

    def __init__(self, config=None):
        from .bmfont import FontCache
        from .images import ImageCache

        self.config = config or Config()
        self.fonts = FontCache(self.config.font_directories)
        self.images = ImageCache(limit=24)
        self.lock = threading.Lock()

    def provider(self, data="demo", track=0, elapsed=97.0, state="playing"):
        from .kodidata import DemoProvider, make_provider

        if data == "live" and xbmc is not None:
            return make_provider()
        return DemoProvider(track, elapsed, state,
                            addon_path("resources", "media", "demo-cover.jpg"),
                            addon_path("resources", "media", "demo-fanart.jpg"))

    def render(self, spec, page=None, data="demo", track=0, state="playing",
               elapsed=97.0, frames=1, step=1.0):
        """Return the PNG of one page of ``spec``."""
        layout = layout_module.Layout(spec)
        provider = self.provider(data, track, elapsed, state)
        with self.lock:
            renderer = layout_module.Renderer(
                layout, provider, self.fonts, self.images,
                float(self.config.page_interval),
                bool(self.config.smooth_images))
            if page is not None and layout.pages:
                chosen = layout.pages[int(page) % len(layout.pages)]
                # The editor edits one page at a time, so conditions must not
                # decide which one is drawn.
                renderer._active = chosen
                renderer._visible_signature = (chosen.index,)
                renderer.select_page = lambda now: chosen
            started = time.time()
            canvas = None
            # Graphs and scrolling text need a few frames before they show
            # anything; a virtual clock gives them one without waiting.
            for index in range(max(1, int(frames))):
                canvas = renderer.render(started + index * float(step))
            return pngio.encode_rgb(canvas.width, canvas.height,
                                    canvas.to_rgb888())


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "LCD4Linux"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------
    def log_message(self, format, *args):  # noqa: A002 (signature is fixed)
        debug("web: %s" % (format % args))

    @property
    def editor(self):
        return self.server.editor

    def _send(self, code, body=b"", content_type="text/plain; charset=utf-8",
              headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The editor is a design tool: never let a stale page or preview
        # survive a save.
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload, code=200):
        self._send(code, json.dumps(payload, ensure_ascii=False),
                   "application/json; charset=utf-8")

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise EditorError("the request is too large")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError as err:
            raise EditorError("invalid JSON: %s" % err)

    def _authorised(self):
        password = self.editor.password
        if not password:
            return True
        header = self.headers.get("Authorization") or ""
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
            except Exception:
                return False
            return decoded.partition(":")[2] == password
        return False

    # -- entry points -----------------------------------------------------
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        if not self._authorised():
            self._send(401, "authentication required",
                       headers={"WWW-Authenticate": 'Basic realm="LCD4Linux"'})
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = dict((key, values[0])
                     for key, values in parse_qs(parsed.query).items())
        try:
            if method == "GET":
                self._get(path, query)
            else:
                self._post(path, query)
        except EditorError as err:
            self._send_json({"error": str(err)}, 400)
        except Exception as err:
            error("web editor: %s" % err)
            if self.editor.config.debug:
                import traceback
                error(traceback.format_exc())
            self._send_json({"error": str(err)}, 500)

    # -- reading ----------------------------------------------------------
    def _get(self, path, query):
        if path in ("/", "/index.html"):
            self._send_file("index.html")
        elif path == "/api/schema":
            self._send_json(self.editor.schema())
        elif path == "/api/state":
            self._send_json(self.editor.state())
        elif path == "/api/layouts":
            config = self.editor.config
            self._send_json({"layouts": list_layouts(config),
                             "active": config.layout})
        elif path == "/api/layout":
            self._send_json(read_layout(query.get("file", ""),
                                        self.editor.config))
        elif path == "/api/blank":
            size = query.get("size", "480x320").lower().split("x")
            width = int(size[0]) if size[0].isdigit() else 480
            height = int(size[1]) if len(size) > 1 and size[1].isdigit() else 320
            self._send_json({"spec": webschema.blank_layout(width, height)})
        elif path.startswith("/static/"):
            self._send_file(path[len("/static/"):])
        else:
            self._send(404, "not found")

    def _send_file(self, relative):
        relative = relative.replace("\\", "/").lstrip("/")
        if ".." in relative.split("/"):
            self._send(403, "forbidden")
            return
        path = os.path.join(self.editor.web_root, *relative.split("/"))
        if not os.path.isfile(path):
            self._send(404, "not found")
            return
        with open(path, "rb") as handle:
            body = handle.read()
        kind = CONTENT_TYPES.get(os.path.splitext(path)[1].lower(),
                                 "application/octet-stream")
        self._send(200, body, kind)

    # -- writing ----------------------------------------------------------
    def _post(self, path, query):
        if path == "/api/preview":
            payload = self._read_json()
            png = self.editor.preview.render(
                payload.get("spec") or {},
                page=payload.get("page"),
                data=payload.get("data", "demo"),
                track=int(payload.get("track", 0) or 0),
                state=payload.get("state", "playing"),
                elapsed=float(payload.get("elapsed", 97.0) or 0),
                frames=int(payload.get("frames", 1) or 1))
            self._send(200, bytes(png), "image/png")
        elif path == "/api/layout":
            payload = self._read_json()
            name = safe_name(payload.get("file", ""))
            write_layout(name, payload.get("spec") or {}, self.editor.config)
            if payload.get("activate"):
                self.editor.activate(name)
            elif payload.get("reload") and self.editor.config.layout == name:
                # The panel is showing this very layout: let it pick the
                # new version up straight away.
                self.editor.command("reload")
            self._send_json({"ok": True, "file": name})
        elif path == "/api/delete":
            payload = self._read_json()
            delete_layout(payload.get("file", ""), self.editor.config)
            self._send_json({"ok": True})
        elif path == "/api/activate":
            payload = self._read_json()
            name = safe_name(payload.get("file", ""))
            self.editor.activate(name)
            self._send_json({"ok": True, "active": name})
        elif path == "/api/command":
            payload = self._read_json()
            command = str(payload.get("command", ""))
            if command not in ("reload", "next_page", "test_pattern"):
                raise EditorError("unknown command %r" % command)
            self.editor.command(command)
            self._send_json({"ok": True})
        elif path == "/api/validate":
            payload = self._read_json()
            validate(payload.get("spec") or {})
            self._send_json({"ok": True})
        else:
            self._send(404, "not found")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, editor):
        self.editor = editor
        ThreadingHTTPServer.__init__(self, address, Handler)


class WebEditor(object):
    """Owns the HTTP server and the state the handlers need."""

    def __init__(self, config=None, service=None):
        self._config = config or Config()
        self.service = service
        self.preview = PreviewRenderer(self._config)
        self.web_root = addon_path("resources", "web")
        self.password = str(self.config.get("web_password", "") or "")
        self._server = None
        self._thread = None
        self._schema = None

    @property
    def config(self):
        """The settings in force.

        The service replaces its :class:`~.settings.Config` whenever Kodi
        reports a change, so ask it rather than holding on to the snapshot
        the editor was built with.
        """
        if self.service is not None and getattr(self.service, "config", None):
            return self.service.config
        return self._config

    # -- server -----------------------------------------------------------
    @property
    def port(self):
        return int(self.config.get("web_port", 8050) or 8050)

    @property
    def host(self):
        # "local" keeps the editor on the box itself, which is what a
        # shared or untrusted network wants; the default listens on every
        # interface so the editor can be opened from a desktop browser.
        return "127.0.0.1" if self.config.get("web_bind") == "local" else "0.0.0.0"

    @property
    def running(self):
        return self._server is not None

    def start(self):
        if self._server is not None:
            return True
        if not os.path.isdir(self.web_root):
            error("the web editor files are missing (%s)" % self.web_root)
            return False
        try:
            self._server = _Server((self.host, self.port), self)
        except OSError as err:
            error("cannot start the web editor on %s:%d: %s"
                  % (self.host, self.port, err))
            self._server = None
            return False
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.5},
                                        name="lcd4linux-web")
        self._thread.daemon = True
        self._thread.start()
        log("web editor listening on %s" % self.url())
        return True

    def stop(self):
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception as err:
            debug("cannot stop the web editor: %s" % err)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        log("web editor stopped")

    def url(self, address=None):
        return "http://%s:%d/" % (address or local_address(self.host), self.port)

    # -- data for the handlers --------------------------------------------
    def schema(self):
        if self._schema is None:
            self._schema = webschema.describe(self.preview.fonts)
        return self._schema

    def state(self):
        config = self.config
        status = ""
        if xbmcgui is not None:
            try:
                status = xbmcgui.Window(10000).getProperty("lcd4linux.status")
            except Exception:
                status = ""
        return {
            "active": config.layout,
            "size": [int(config.width), int(config.height)],
            "display": config.display_type,
            "rotation": int(config.rotation),
            "status": status,
            "kodi": xbmc is not None,
            "userdir": user_directory(config),
            "live": xbmc is not None,
        }

    def activate(self, name):
        """Make ``name`` the layout the panel shows."""
        self.config.set("layout", name)
        self.command("reload")

    def command(self, command):
        if self.service is not None:
            # Running inside the service: no round trip through Kodi.
            self.service._handle_command(command, None)
            return True
        from .ui import notify_service
        return notify_service(command)


def local_address(host="0.0.0.0"):
    """The address to show the user, ideally the one on the LAN."""
    if host not in ("0.0.0.0", "::"):
        return host
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Nothing is sent; connecting a UDP socket just picks the route.
        probe.connect(("8.8.8.8", 53))
        return probe.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        probe.close()
