"""Everything a layout can display.

The provider exposes a flat key space (``player.title``, ``system.cpu`` ...)
plus two escape hatches: ``info:<InfoLabel>`` reaches any Kodi info label and
``bool:<Condition>`` any Kodi boolean condition, so users are not limited to
the keys implemented here.
"""

import math
import os
import socket
import time

from . import localize
from .logger import debug

try:
    import xbmc  # type: ignore
    import xbmcgui  # type: ignore
except ImportError:
    xbmc = None
    xbmcgui = None

def weekday_name(when, short=False):
    """Day name in Kodi's language, falling back to the C locale."""
    return (localize.weekday(when.tm_wday, short)
            or time.strftime("%a" if short else "%A", when))


def month_name(when, short=False):
    """Month name in Kodi's language, falling back to the C locale."""
    return (localize.month(when.tm_mon, short)
            or time.strftime("%b" if short else "%B", when))


def long_date(when):
    """``Monday, 08 September 2026`` in Kodi's language and order."""
    pattern = localize.text(32340, "{weekday}, {day} {month} {year}")
    return (pattern.replace("{weekday}", weekday_name(when))
            .replace("{day}", time.strftime("%d", when))
            .replace("{month}", month_name(when))
            .replace("{year}", time.strftime("%Y", when)))


THERMAL_PATHS = (
    "/sys/class/thermal/thermal_zone0/temp",
    "/sys/devices/virtual/thermal/thermal_zone0/temp",
    "/sys/class/hwmon/hwmon0/temp1_input",
)

GPU_THERMAL_PATHS = (
    "/sys/class/thermal/thermal_zone1/temp",
    "/sys/devices/virtual/thermal/thermal_zone1/temp",
)


def _read_first(paths):
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read().strip()
        except (IOError, OSError):
            continue
    return ""


def format_size(number_of_bytes):
    """Human readable size, e.g. ``412.7 GB``."""
    try:
        value = float(number_of_bytes)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit in ("B", "KB", "MB") and value >= 100:
                return "%.0f %s" % (value, unit)
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return ""


def _looks_like_address(text):
    """True for something that could be an IPv4/IPv6 address."""
    text = (text or "").strip()
    if not text:
        return False
    if text.count(".") == 3 and all(
            part.isdigit() and int(part) < 256 for part in text.split(".")):
        return True
    return ":" in text and text.replace(":", "").replace(".", "").isalnum()


def format_time(seconds, force_hours=False):
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if total < 0:
        total = 0
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours or force_hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    return "%d:%02d" % (minutes, secs)


class BaseProvider(object):
    """Caches values for the duration of one rendered frame."""

    def __init__(self):
        self._cache = {}
        self._frame = 0
        #: Timestamp of the frame being rendered; the renderer sets this so
        #: offline previews can advance a virtual clock.
        self.now = None

    def begin_frame(self, now=None):
        """Start a frame, dropping the values cached for the previous one.

        Both the service and the renderer announce the frame - the service
        needs the player state before it decides on brightness and frame
        rate, the renderer needs it while drawing - so a second call with
        the same timestamp is ignored instead of throwing the cache away and
        asking Kodi for everything twice.
        """
        if now is not None and now == self.now and self._frame:
            return
        self._cache = {}
        self._frame += 1
        self.now = now

    def clock(self):
        return self.now if self.now is not None else time.time()

    # -- public API -------------------------------------------------------
    def value(self, key):
        key = (key or "").strip()
        if not key:
            return u""
        if key in self._cache:
            return self._cache[key]
        result = self._resolve(key)
        if result is None:
            result = u""
        self._cache[key] = result
        return result

    def condition(self, name):
        name = (name or "").strip()
        lowered = name.lower()
        if lowered.startswith("bool:"):
            return self._kodi_condition(name[5:])
        builtin = self._builtin_condition(lowered)
        if builtin is not None:
            return builtin
        return self._kodi_condition(name)

    # -- to implement -----------------------------------------------------
    def _resolve(self, key):
        raise NotImplementedError

    def _kodi_condition(self, name):
        return False

    def _builtin_condition(self, name):
        state = str(self.value("player.state")).lower()
        media = str(self.value("player.mediatype")).lower()
        if name == "playing":
            return state == "playing"
        if name == "paused":
            return state == "paused"
        if name in ("stopped", "idle"):
            return state == "stopped"
        if name in ("active", "hasmedia"):
            return state in ("playing", "paused")
        if name == "audio":
            return media == "audio" and state in ("playing", "paused")
        if name == "video":
            return media == "video" and state in ("playing", "paused")
        if name == "screensaver":
            return bool(self.value("system.screensaver") == "1")
        return None

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _cpu_temperature():
        raw = _read_first(THERMAL_PATHS)
        if not raw:
            return ""
        try:
            value = float(raw)
        except ValueError:
            return ""
        if value > 1000:
            value /= 1000.0
        return "%.0f" % value

    @staticmethod
    def _gpu_temperature():
        raw = _read_first(GPU_THERMAL_PATHS)
        if not raw:
            return ""
        try:
            value = float(raw)
        except ValueError:
            return ""
        if value > 1000:
            value /= 1000.0
        return "%.0f" % value

    def _meminfo(self):
        """``/proc/meminfo`` as a dict, read at most once per frame.

        A layout that shows used, free and total memory asks three separate
        keys, and each one is a different cache entry, so without this the
        file was opened three times for a single frame.
        """
        if "__meminfo" in self._cache:
            return self._cache["__meminfo"]
        fields = None
        try:
            with open("/proc/meminfo", "r", encoding="ascii") as handle:
                fields = {}
                for line in handle:
                    name, _, rest = line.partition(":")
                    fields[name.strip()] = int(rest.strip().split()[0])
        except (IOError, OSError, ValueError, IndexError):
            fields = None
        self._cache["__meminfo"] = fields
        return fields

    #: Checked in order; the first one that exists is reported.
    STORAGE_PATHS = ("/storage", "/var/media", "/home", "/")

    def _disk(self, what):
        """Free/used/total space of the data partition."""
        for path in self.STORAGE_PATHS:
            try:
                stats = os.statvfs(path)
            except (OSError, AttributeError):
                continue
            block = stats.f_frsize or stats.f_bsize
            total = stats.f_blocks * block
            free = stats.f_bavail * block
            if not total:
                continue
            if what == "free":
                return format_size(free)
            if what == "used":
                return format_size(total - free)
            if what == "total":
                return format_size(total)
            if what == "free_percent":
                return "%.0f" % (100.0 * free / total)
        return ""

    @staticmethod
    def _hostname():
        try:
            return socket.gethostname()
        except Exception:
            return ""

    @staticmethod
    def _ip_address():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect(("10.255.255.255", 1))
                return sock.getsockname()[0]
            finally:
                sock.close()
        except Exception:
            return ""


class CpuSampler(object):
    """Rolling CPU usage from ``/proc/stat``."""

    def __init__(self, min_interval=1.0):
        self.min_interval = min_interval
        self._last_sample = None
        self._last_time = 0.0
        self._value = 0.0

    def usage(self):
        now = time.time()
        if now - self._last_time < self.min_interval and self._last_sample:
            return self._value
        try:
            with open("/proc/stat", "r", encoding="ascii") as handle:
                fields = handle.readline().split()
        except (IOError, OSError):
            return self._value
        if len(fields) < 5 or fields[0] != "cpu":
            return self._value
        values = [int(item) for item in fields[1:8] if item.isdigit()]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        if self._last_sample:
            prev_total, prev_idle = self._last_sample
            delta_total = total - prev_total
            delta_idle = idle - prev_idle
            if delta_total > 0:
                self._value = max(0.0, min(100.0, 100.0 * (delta_total - delta_idle) / delta_total))
        self._last_sample = (total, idle)
        self._last_time = now
        return self._value


class KodiProvider(BaseProvider):
    """Live data from the running Kodi instance."""

    def __init__(self, addon_name="", addon_version=""):
        BaseProvider.__init__(self)
        self.addon_name = addon_name
        self.addon_version = addon_version
        self.player = xbmc.Player() if xbmc is not None else None
        self.cpu = CpuSampler()
        self._library_cache = {}
        self._library_time = 0.0

    # -- infrastructure ---------------------------------------------------
    def _info(self, label):
        if xbmc is None:
            return u""
        try:
            return xbmc.getInfoLabel(label) or u""
        except Exception:
            return u""

    def _kodi_condition(self, name):
        if xbmc is None or not name:
            return False
        try:
            return bool(xbmc.getCondVisibility(name))
        except Exception:
            return False

    def _player_times(self):
        """``(elapsed, total)`` in seconds, or ``(0, 0)``."""
        cached = self._cache.get("__times")
        if cached is not None:
            return cached
        elapsed = total = 0.0
        if self.player is not None:
            try:
                if self.player.isPlaying():
                    elapsed = float(self.player.getTime())
                    total = float(self.player.getTotalTime())
            except Exception:
                elapsed = total = 0.0
        if not total:
            # Live streams and some add-ons report no duration.
            try:
                total = float(self._info("Player.Duration(secs)") or 0)
            except ValueError:
                total = 0.0
        result = (max(0.0, elapsed), max(0.0, total))
        self._cache["__times"] = result
        return result

    def _state(self):
        """``playing``/``paused``/``stopped``, resolved once per frame.

        Every ``player.*`` key needs the state, but each key is cached under
        its own name, so a page with a dozen of them used to ask Kodi for
        the same two visibility conditions a dozen times per frame.
        """
        cached = self._cache.get("__state")
        if cached is not None:
            return cached
        if xbmc is None:
            state = "stopped"
        elif self._kodi_condition("Player.Playing"):
            state = "playing"
        elif self._kodi_condition("Player.Paused"):
            state = "paused"
        else:
            state = "stopped"
        self._cache["__state"] = state
        return state

    def _media_type(self):
        """``video``/``audio``/``picture``/``none``, resolved once per frame."""
        cached = self._cache.get("__mediatype")
        if cached is not None:
            return cached
        if self._kodi_condition("Player.HasVideo"):
            media = "video"
        elif self._kodi_condition("Player.HasAudio"):
            media = "audio"
        elif self._kodi_condition("Player.HasPicture"):
            media = "picture"
        else:
            media = "none"
        self._cache["__mediatype"] = media
        return media

    def _library_counts(self):
        now = time.time()
        if self._library_cache and now - self._library_time < 300:
            return self._library_cache
        counts = {}
        if xbmc is not None:
            import json
            queries = (
                ("songs", "AudioLibrary.GetSongs"),
                ("albums", "AudioLibrary.GetAlbums"),
                ("artists", "AudioLibrary.GetArtists"),
                ("movies", "VideoLibrary.GetMovies"),
                ("tvshows", "VideoLibrary.GetTVShows"),
                ("episodes", "VideoLibrary.GetEpisodes"),
            )
            for name, method in queries:
                request = {
                    "jsonrpc": "2.0", "id": 1, "method": method,
                    "params": {"limits": {"start": 0, "end": 1}},
                }
                try:
                    reply = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
                    counts[name] = str(reply["result"]["limits"]["total"])
                except Exception:
                    counts[name] = ""
        self._library_cache = counts
        self._library_time = now
        return counts

    # -- key resolution ---------------------------------------------------
    def _resolve(self, key):
        lowered = key.lower()
        if lowered.startswith("info:"):
            return self._info(key[5:])
        if lowered.startswith("bool:"):
            return "1" if self._kodi_condition(key[5:]) else "0"
        namespace, _, name = lowered.partition(".")
        handler = getattr(self, "_ns_" + namespace, None)
        if handler is None:
            return self._info(key)
        return handler(name)

    # -- namespaces -------------------------------------------------------
    def _ns_player(self, name):
        elapsed, total = self._player_times()
        state = self._state()
        media = self._media_type()

        if name == "state":
            return state
        if name == "mediatype":
            return media
        if name == "playing":
            return "1" if state == "playing" else "0"
        if name == "paused":
            return "1" if state == "paused" else "0"
        if name in ("time", "elapsed"):
            return format_time(elapsed)
        if name in ("time_s", "elapsed_s"):
            return "%d" % elapsed
        if name == "duration":
            return format_time(total) if total else ""
        if name == "duration_s":
            return "%d" % total
        if name == "remaining":
            return format_time(max(0.0, total - elapsed)) if total else ""
        if name == "remaining_s":
            return "%d" % max(0.0, total - elapsed)
        if name == "percent":
            return "%.2f" % (100.0 * elapsed / total) if total else "0"
        if name == "speed":
            return self._info("Player.PlaySpeed")
        if name == "title":
            return (self._info("Player.Title")
                    or self._info("MusicPlayer.Title")
                    or self._info("VideoPlayer.Title"))
        if name == "artist":
            return (self._info("MusicPlayer.Artist")
                    or self._info("VideoPlayer.Director"))
        if name == "albumartist":
            return self._info("MusicPlayer.AlbumArtist")
        if name == "album":
            return self._info("MusicPlayer.Album")
        if name == "genre":
            return (self._info("MusicPlayer.Genre")
                    or self._info("VideoPlayer.Genre"))
        if name == "year":
            return (self._info("MusicPlayer.Year")
                    or self._info("VideoPlayer.Year"))
        if name == "track":
            return self._info("MusicPlayer.TrackNumber")
        if name == "discnumber":
            return self._info("MusicPlayer.DiscNumber")
        if name == "rating":
            return (self._info("MusicPlayer.Rating")
                    or self._info("VideoPlayer.Rating"))
        if name == "showtitle":
            return self._info("VideoPlayer.TVShowTitle")
        if name == "season":
            return self._info("VideoPlayer.Season")
        if name == "episode":
            return self._info("VideoPlayer.Episode")
        if name == "episodelabel":
            season = self._info("VideoPlayer.Season")
            episode = self._info("VideoPlayer.Episode")
            if season and episode:
                return "S%02dE%02d" % (int(season), int(episode)) \
                    if season.isdigit() and episode.isdigit() else "%s x %s" % (season, episode)
            return episode
        if name == "plot":
            return self._info("VideoPlayer.Plot")
        if name in ("thumb", "cover", "art"):
            return (self._info("Player.Art(thumb)")
                    or self._info("MusicPlayer.Cover")
                    or self._info("VideoPlayer.Cover")
                    or self._info("Player.Icon"))
        if name == "fanart":
            return self._info("Player.Art(fanart)")
        if name == "poster":
            return self._info("Player.Art(poster)")
        if name == "filename":
            return self._info("Player.Filename")
        if name == "path":
            return self._info("Player.Folderpath")
        if name == "codec":
            return (self._info("MusicPlayer.Codec")
                    or self._info("VideoPlayer.VideoCodec"))
        if name == "audiocodec":
            return self._info("VideoPlayer.AudioCodec")
        if name == "bitrate":
            return self._info("MusicPlayer.BitRate")
        if name == "samplerate":
            return self._info("MusicPlayer.SampleRate")
        if name == "channels":
            return (self._info("MusicPlayer.Channels")
                    or self._info("VideoPlayer.AudioChannels"))
        if name == "resolution":
            return self._info("VideoPlayer.VideoResolution")
        if name == "aspect":
            return self._info("VideoPlayer.VideoAspect")
        if name == "next":
            return (self._info("MusicPlayer.Offset(1).Title")
                    or self._info("VideoPlayer.NextTitle"))
        if name == "nextartist":
            return self._info("MusicPlayer.Offset(1).Artist")
        if name == "playlistposition":
            return self._info("MusicPlayer.PlaylistPosition") or self._info("VideoPlayer.PlaylistPosition")
        if name == "playlistlength":
            return self._info("MusicPlayer.PlaylistLength") or self._info("VideoPlayer.PlaylistLength")
        if name == "starttime":
            return self._info("Player.StartTime")
        if name == "finishtime":
            return self._info("Player.FinishTime")
        if name == "seeking":
            return "1" if self._kodi_condition("Player.Seeking") else "0"
        return self._info("Player." + name)

    def _ns_system(self, name):
        now = time.localtime()
        if name == "time":
            return time.strftime("%H:%M", now)
        if name == "time12":
            return time.strftime("%I:%M %p", now).lstrip("0")
        if name == "seconds":
            return time.strftime("%S", now)
        if name == "timesec":
            return time.strftime("%H:%M:%S", now)
        if name == "date":
            return time.strftime("%d.%m.%Y", now)
        if name == "date_iso":
            return time.strftime("%Y-%m-%d", now)
        if name == "date_short":
            return time.strftime("%d.%m.", now)
        if name == "date_long":
            return long_date(now)
        if name == "weekday":
            return weekday_name(now)
        if name == "weekday_short":
            return weekday_name(now, True)
        if name == "day":
            return time.strftime("%d", now)
        if name == "month":
            return time.strftime("%m", now)
        if name == "monthname":
            return month_name(now)
        if name == "year":
            return time.strftime("%Y", now)
        if name in ("cpu", "cpuusage"):
            return "%.0f" % self.cpu.usage()
        if name in ("cputemp", "temperature"):
            return self._cpu_temperature() or self._info("System.CPUTemperature")
        if name == "gputemp":
            return self._gpu_temperature() or self._info("System.GPUTemperature")
        if name in ("memory", "memoryused"):
            fields = self._meminfo()
            if not fields:
                return self._info("System.Memory(used.percent)")
            total = fields.get("MemTotal", 0)
            available = fields.get("MemAvailable", fields.get("MemFree", 0))
            if not total:
                return ""
            return "%.0f" % (100.0 * (total - available) / total)
        if name == "memoryfree":
            fields = self._meminfo()
            if not fields:
                return self._info("System.Memory(free)")
            return "%d" % (fields.get("MemAvailable", fields.get("MemFree", 0)) // 1024)
        if name == "memorytotal":
            fields = self._meminfo()
            return "%d" % (fields.get("MemTotal", 0) // 1024) if fields else ""
        if name == "uptime":
            return self._info("System.Uptime")
        if name == "hostname":
            return self._hostname()
        if name in ("ip", "ipaddress"):
            # Some Kodi builds hand back the label name instead of an address,
            # so the socket lookup wins and the info label is only a fallback.
            address = self._ip_address()
            if address:
                return address
            reported = self._info("System.IPAddress")
            return reported if _looks_like_address(reported) else ""
        if name == "kodiversion":
            return self._info("System.BuildVersion").split(" ")[0]
        if name == "buildversion":
            return self._info("System.BuildVersion")
        if name == "freespace":
            return self._disk("free")
        if name == "freespace_percent":
            return self._disk("free_percent")
        if name == "usedspace":
            return self._disk("used")
        if name == "totalspace":
            return self._disk("total")
        if name == "volume":
            return self._info("Player.Volume")
        if name == "muted":
            return "1" if self._kodi_condition("Player.Muted") else "0"
        if name == "screensaver":
            return "1" if self._kodi_condition("System.ScreenSaverActive") else "0"
        if name == "profile":
            return self._info("System.ProfileName")
        return self._info("System." + name)

    def _ns_weather(self, name):
        mapping = {
            "temperature": "Weather.Temperature",
            "temp": "Weather.Temperature",
            "conditions": "Weather.Conditions",
            "location": "Weather.Location",
            "fanart": "Weather.FanartCode",
            "plugin": "Weather.Plugin",
        }
        return self._info(mapping.get(name, "Weather." + name))

    def _ns_library(self, name):
        return self._library_counts().get(name, "")

    def _ns_addon(self, name):
        if name == "name":
            return self.addon_name
        if name == "version":
            return self.addon_version
        return ""

    def _ns_container(self, name):
        return self._info("Container." + name)

    def _ns_window(self, name):
        return self._info("Window." + name)


class DemoProvider(BaseProvider):
    """Fake data so layouts can be designed without Kodi or hardware."""

    TRACKS = (
        {
            "title": "Enjoy the Silence", "artist": "Depeche Mode",
            "album": "Violator", "year": "1990", "genre": "Synth-Pop",
            "duration": 372, "mediatype": "audio", "track": "4",
            "codec": "flac", "samplerate": "44100", "bitrate": "1006",
            "channels": "2",
        },
        {
            "title": "The Dark Knight", "artist": "Christopher Nolan",
            "album": "", "year": "2008", "genre": "Action",
            "duration": 9120, "mediatype": "video", "track": "",
            "codec": "h264", "resolution": "2160", "channels": "8",
            "showtitle": "", "season": "", "episode": "",
        },
        {
            "title": "Winter Is Coming", "artist": "",
            "album": "", "year": "2011", "genre": "Fantasy",
            "duration": 3720, "mediatype": "video", "track": "",
            "codec": "h265", "resolution": "1080", "channels": "6",
            "showtitle": "Game of Thrones", "season": "1", "episode": "1",
        },
    )

    def __init__(self, track=0, elapsed=None, state="playing", art="",
                 fanart=""):
        BaseProvider.__init__(self)
        self.track = self.TRACKS[track % len(self.TRACKS)]
        self.state = state
        self.art = art
        self.fanart = fanart
        self._start = time.time()
        self._fixed_elapsed = elapsed
        self.cpu = CpuSampler()

    def _elapsed(self):
        if self._fixed_elapsed is not None:
            return float(self._fixed_elapsed)
        return (self.clock() - self._start) % max(1, self.track["duration"])

    def _kodi_condition(self, name):
        lowered = name.lower()
        if lowered == "player.playing":
            return self.state == "playing"
        if lowered == "player.paused":
            return self.state == "paused"
        if lowered == "player.hasaudio":
            return self.track["mediatype"] == "audio"
        if lowered == "player.hasvideo":
            return self.track["mediatype"] == "video"
        return False

    def _resolve(self, key):
        lowered = key.lower()
        if lowered.startswith("info:") or lowered.startswith("bool:"):
            return ""
        namespace, _, name = lowered.partition(".")
        if namespace == "player":
            elapsed = self._elapsed()
            total = float(self.track["duration"])
            values = {
                "state": self.state, "mediatype": self.track["mediatype"],
                "playing": "1" if self.state == "playing" else "0",
                "paused": "1" if self.state == "paused" else "0",
                "time": format_time(elapsed), "time_s": "%d" % elapsed,
                "duration": format_time(total), "duration_s": "%d" % total,
                "remaining": format_time(total - elapsed),
                "remaining_s": "%d" % (total - elapsed),
                "percent": "%.2f" % (100.0 * elapsed / total),
                "thumb": self.art, "cover": self.art, "art": self.art,
                "poster": self.art, "fanart": self.fanart or self.art,
                "next": "Personal Jesus", "nextartist": "Depeche Mode",
                "playlistposition": "4", "playlistlength": "12",
                "speed": "1", "rating": "8.4",
                "starttime": time.strftime("%H:%M", time.localtime(
                    time.time() - elapsed)),
                "finishtime": time.strftime("%H:%M", time.localtime(
                    time.time() + total - elapsed)),
                "plot": "A demo synopsis so wrapped text can be checked "
                        "while a layout is being designed.",
                "filename": "demo.mkv", "path": "/storage/demo/",
                "audiocodec": "dts", "aspect": "2.35",
            }
            show = self.track.get("showtitle", "")
            season = self.track.get("season", "")
            episode = self.track.get("episode", "")
            values.update({
                "showtitle": show, "season": season, "episode": episode,
                "episodelabel": ("S%02dE%02d" % (int(season), int(episode)))
                                if season and episode else "",
            })
            if self.track["mediatype"] != "video":
                values["plot"] = ""
            values.update({
                "title": self.track["title"], "artist": self.track["artist"],
                "album": self.track["album"], "year": self.track["year"],
                "genre": self.track["genre"], "track": self.track["track"],
                "codec": self.track["codec"],
                "samplerate": self.track.get("samplerate", ""),
                "bitrate": self.track.get("bitrate", ""),
                "channels": self.track.get("channels", ""),
                "resolution": self.track.get("resolution", ""),
            })
            return values.get(name, "")
        if namespace == "system":
            now = time.localtime(self.clock())
            values = {
                "time": time.strftime("%H:%M", now),
                "timesec": time.strftime("%H:%M:%S", now),
                "seconds": time.strftime("%S", now),
                "date": time.strftime("%d.%m.%Y", now),
                "date_iso": time.strftime("%Y-%m-%d", now),
                "date_short": time.strftime("%d.%m.", now),
                "date_long": long_date(now),
                "weekday": weekday_name(now),
                "weekday_short": weekday_name(now, True),
                "day": time.strftime("%d", now),
                "month": time.strftime("%m", now),
                "monthname": month_name(now),
                "year": time.strftime("%Y", now),
                "memoryfree": "1204", "memorytotal": "3072",
                "gputemp": "51", "muted": "0", "buildversion": "21.2 Omega",
                "profile": "Master user",
                # Synthetic but plausible load so graphs and bars have
                # something to show in a preview.
                "cpu": "%.0f" % (34 + 26 * math.sin(self.clock() / 40.0)
                                 + 8 * math.sin(self.clock() / 11.0)),
                "cputemp": self._cpu_temperature() or "47",
                "memory": "%.0f" % (38 + 4 * math.sin(self.clock() / 23.0)),
                "uptime": "3 hours",
                "hostname": self._hostname() or "coreelec",
                "ip": self._ip_address() or "192.168.1.42",
                "kodiversion": "21.2", "volume": "-12.0 dB",
                "freespace": "412.7 GB", "freespace_percent": "63",
                "usedspace": "238.1 GB", "totalspace": "650.8 GB",
                "screensaver": "0",
            }
            return values.get(name, "")
        if namespace == "weather":
            return {"temperature": "18", "conditions": "Partly Cloudy",
                    "location": "Berlin"}.get(name, "")
        if namespace == "library":
            return {"songs": "12483", "albums": "1041", "artists": "612",
                    "movies": "384", "tvshows": "27",
                    "episodes": "1892"}.get(name, "")
        if namespace == "addon":
            return {"name": "LCD4Linux", "version": "1.0.0"}.get(name, "")
        return ""


def make_provider(addon_name="", addon_version=""):
    if xbmc is not None:
        return KodiProvider(addon_name, addon_version)
    debug("xbmc module unavailable, using the demo data provider")
    return DemoProvider()
