"""The background service.

Renders the active layout at a modest frame rate, pushes only the changed
part of the frame to the panel and reacts to Kodi events (playback, screen
saver, settings changes, notifications).
"""

import os
import time

from . import ax206
from . import display as display_module
from . import layout as layout_module
from . import localize
from .bmfont import FontCache
from .images import ImageCache
from .kodidata import make_provider
from .logger import debug, error, log
from .settings import Config, addon_path, ensure_user_directories, profile_path
from .canvas import parse_color

try:
    import xbmc  # type: ignore
    import xbmcaddon  # type: ignore
    import xbmcgui  # type: ignore
except ImportError:
    xbmc = None
    xbmcaddon = None
    xbmcgui = None

#: Commands accepted through ``NotifyAll(script.lcd4linux, <command>)``.
CONTROL_COMMANDS = ("reload", "next_page", "test_pattern", "message",
                    "brightness_up", "brightness_down")

#: Kodi events that are mirrored on the panel, mapped to
#: ``(string id, English fallback)``.
NOTIFICATION_MESSAGES = {
    "VideoLibrary.OnScanStarted": (32300, "Video library scan started"),
    "VideoLibrary.OnScanFinished": (32301, "Video library scan finished"),
    "VideoLibrary.OnCleanStarted": (32302, "Video library clean started"),
    "VideoLibrary.OnCleanFinished": (32303, "Video library clean finished"),
    "AudioLibrary.OnScanStarted": (32304, "Music library scan started"),
    "AudioLibrary.OnScanFinished": (32305, "Music library scan finished"),
    "System.OnSleep": (32306, "System going to sleep"),
    "System.OnWake": (32307, "System woken up"),
    "System.OnQuit": (32308, "Kodi is shutting down"),
    "System.OnRestart": (32309, "Kodi is restarting"),
}


class Notification(object):
    def __init__(self, heading, message, icon="", until=0.0):
        self.heading = heading or ""
        self.message = message or ""
        self.icon = icon
        self.until = until


class Monitor(xbmc.Monitor if xbmc is not None else object):
    """Watches Kodi for the events the service cares about."""

    def __init__(self, service):
        if xbmc is not None:
            xbmc.Monitor.__init__(self)
        self.service = service

    def onSettingsChanged(self):
        log("settings changed, reloading")
        self.service.request_reload()

    def onScreensaverActivated(self):
        self.service.set_screensaver(True)

    def onScreensaverDeactivated(self):
        self.service.set_screensaver(False)

    def onDPMSActivated(self):
        self.service.set_screensaver(True)

    def onDPMSDeactivated(self):
        self.service.set_screensaver(False)

    def onNotification(self, sender, method, data):
        self.service.on_notification(sender, method, data)


class Service(object):
    def __init__(self, config=None, overrides=None):
        #: Kept so a reload re-reads Kodi's settings without losing the
        #: overrides a caller (tests, tools) started the service with.
        self._overrides = dict(overrides or {})
        self.config = config or Config(self._overrides)
        self.monitor = Monitor(self) if xbmc is not None else None
        self.provider = make_provider(self._addon_info("name"),
                                      self._addon_info("version"))
        self.fonts = FontCache(self.config.font_directories)
        self.images = ImageCache(limit=32)
        self.target = None
        self.renderer = None
        self.layout = None
        self._reload_requested = False
        self._stop = False
        self._screensaver = False
        self._notification = None
        self._last_activity = time.time()
        self._blanked = False
        self._brightness = None
        self._next_open_attempt = 0.0
        self._open_failures = 0
        self._test_until = 0.0

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _addon_info(field):
        if xbmcaddon is None:
            return ""
        try:
            return xbmcaddon.Addon().getAddonInfo(field)
        except Exception:
            return ""

    def request_reload(self):
        self._reload_requested = True

    def set_screensaver(self, active):
        self._screensaver = bool(active)
        if not active:
            self._last_activity = time.time()

    def on_notification(self, sender, method, data):
        """Mirror the Kodi events that are worth putting on the panel."""
        if method.startswith("Other.") and method[6:] in CONTROL_COMMANDS:
            self._handle_command(method[6:], data)
            return
        if method in ("Player.OnPlay", "Player.OnResume", "Player.OnStop",
                      "Player.OnAVStart", "Player.OnPause"):
            self._last_activity = time.time()
            return
        if not self.config.notifications:
            return
        message = NOTIFICATION_MESSAGES.get(method)
        if message is not None:
            self.show_message(localize.text(*message), "")
            return
        if method.startswith("Other."):
            heading = sender or "Kodi"
            body = method[6:]
            try:
                import json
                payload = json.loads(data) if data else {}
                body = payload.get("message") or payload.get("title") or body
            except Exception:
                pass
            self.show_message(heading, str(body))

    def _handle_command(self, command, data):
        """React to a command sent with ``NotifyAll(script.lcd4linux, ...)``."""
        debug("command %s" % command)
        if command == "reload":
            self.request_reload()
        elif command == "next_page":
            if self.renderer is not None:
                page = self.renderer.next_page()
                if page is not None:
                    self.show_message(localize.text(32310, "Page"), page.name, 2)
        elif command == "test_pattern":
            self._test_until = time.time() + 10.0
        elif command == "brightness_up":
            self.config.set("brightness",
                            min(ax206.MAX_BRIGHTNESS,
                                int(self.config.brightness) + 1))
            self._apply_brightness(force=True)
        elif command == "brightness_down":
            self.config.set("brightness", max(0, int(self.config.brightness) - 1))
            self._apply_brightness(force=True)
        elif command == "message":
            heading = message = ""
            try:
                import json
                payload = json.loads(data) if data else {}
                heading = payload.get("heading", "")
                message = payload.get("message", "")
            except Exception:
                pass
            if heading or message:
                self.show_message(heading, message)

    def show_message(self, heading, message, seconds=None):
        """Put a banner on the panel (used by the script entry point too)."""
        seconds = seconds if seconds is not None else self.config.notification_seconds
        self._notification = Notification(heading, message, "",
                                          time.time() + max(1, int(seconds)))

    # -- setup ------------------------------------------------------------
    def setup(self):
        ensure_user_directories()
        self._install_example_layout()
        self.config = Config(self._overrides)
        self.fonts = FontCache(self.config.font_directories)
        self.images.clear()
        self.provider = make_provider(self._addon_info("name"),
                                      self._addon_info("version"))
        log("starting with %s" % self.config.describe())

        self._close_target()
        self.target = display_module.make_target(self.config)
        opened = self._open_target()

        width, height = self.target.logical_size
        if not width or not height:
            width, height = self.config.width, self.config.height
        self.layout = layout_module.load_layout(self.config.layout,
                                                self.config.layout_directories,
                                                (width, height))
        if (self.layout.width, self.layout.height) != (width, height):
            log("layout %s is designed for %dx%d but the display is %dx%d; "
                "rendering at the display size"
                % (self.layout.name, self.layout.width, self.layout.height,
                   width, height))
        self.renderer = layout_module.Renderer(
            self.layout, self.provider, self.fonts, self.images,
            float(self.config.page_interval), bool(self.config.smooth_images),
            size=(width, height))
        return opened

    def _install_example_layout(self):
        """Drop a copy of the default layout into the user directory once."""
        target_dir = profile_path("layouts")
        marker = os.path.join(target_dir, "custom.json.example")
        source = addon_path("resources", "layouts", "default.json")
        if os.path.exists(marker) or not os.path.exists(source):
            return
        try:
            # Copied as bytes: the file is UTF-8 and the locale on a CoreELEC
            # box is plain C, so text mode would try to decode it as ASCII.
            with open(source, "rb") as handle:
                data = handle.read()
            with open(marker, "wb") as handle:
                handle.write(data)
            log("example layout written to %s" % marker)
        except (IOError, OSError) as err:
            debug("cannot write example layout: %s" % err)

    def _publish_status(self, text):
        """Expose the connection state so the script entry point can show it."""
        debug("status: %s" % text)
        if xbmcgui is None:
            return
        try:
            xbmcgui.Window(10000).setProperty("lcd4linux.status", text)
        except Exception:
            pass

    def _open_target(self):
        try:
            self.target.open()
            self._open_failures = 0
            self._brightness = None
            self._apply_brightness(force=True)
            if isinstance(self.target, display_module.AX206Target):
                self._publish_status("%s | %dx%d" % (self.target.describe(),
                                                     self.target.width,
                                                     self.target.height))
            else:
                self._publish_status("%s | %dx%d" % (self.config.output_mode,
                                                     self.target.width,
                                                     self.target.height))
            return True
        except Exception as err:
            self._open_failures += 1
            self._next_open_attempt = time.time() + max(
                5, int(self.config.retry_seconds))
            self._publish_status(str(err))
            if self._open_failures == 1:
                error("cannot open the display: %s" % err)
                self._notify_user(err)
            else:
                debug("display still unavailable: %s" % err)
            return False

    def _notify_user(self, err):
        if xbmcgui is None:
            return
        try:
            xbmcgui.Dialog().notification(
                self._addon_info("name") or "LCD4Linux", str(err),
                xbmcgui.NOTIFICATION_WARNING, 6000)
        except Exception:
            pass

    def _close_target(self):
        if self.target is not None:
            try:
                self.target.close()
            except Exception as err:
                debug("error closing target: %s" % err)
            self.target = None

    # -- brightness / blanking -------------------------------------------
    def _wanted_brightness(self):
        if self._blanked:
            return 0
        if self._screensaver:
            if self.config.off_on_screensaver:
                return 0
            if self.config.dim_on_screensaver:
                return int(self.config.dim_brightness)
        return int(self.config.brightness)

    def _apply_brightness(self, force=False):
        level = self._wanted_brightness()
        if force or level != self._brightness:
            self.target.set_brightness(level)
            self._brightness = level

    def _update_idle(self, now):
        if not self.config.off_on_idle:
            self._blanked = False
            return
        idle = now - self._last_activity
        if xbmc is not None:
            try:
                idle = min(idle, xbmc.getGlobalIdleTime())
            except Exception:
                pass
        limit = max(1, int(self.config.idle_minutes)) * 60
        playing = str(self.provider.value("player.state")) in ("playing", "paused")
        self._blanked = (not playing) and idle >= limit

    # -- notification overlay ---------------------------------------------
    def _draw_notification(self, canvas, now):
        note = self._notification
        if note is None:
            return
        if now >= note.until:
            self._notification = None
            return
        width = canvas.width
        height = 56
        top = canvas.height - height - 8
        canvas.reset_clip()
        canvas.fill_round_rect(8, top, width - 16, height,
                               parse_color("#f00d1119"), 8)
        canvas.round_rect(8, top, width - 16, height,
                          parse_color("#3317b2e2"), 8, 1)
        heading_font = self.fonts.get("sans-bold", 16)
        body_font = self.fonts.get("sans", 15)
        canvas.push_clip(20, top + 6, width - 40, height - 10)
        try:
            canvas.draw_text(heading_font,
                             heading_font.ellipsize(note.heading, width - 44),
                             20, top + 8 + heading_font.ascent,
                             parse_color("#17b2e2"))
            canvas.draw_text(body_font,
                             body_font.ellipsize(note.message, width - 44),
                             20, top + 30 + body_font.ascent,
                             parse_color("#dfe5f0"))
        finally:
            canvas.pop_clip()

    # -- main loop --------------------------------------------------------
    def run(self):
        self.setup()
        log("service running")
        while not self._stop:
            started = time.time()
            try:
                self._tick(started)
            except ax206.DisplayError as err:
                error("display error: %s" % err)
                self._handle_disconnect()
            except Exception as err:
                error("unexpected error: %s" % err)
                if self.config.debug:
                    import traceback
                    error(traceback.format_exc())

            if self._reload_requested:
                self._reload_requested = False
                try:
                    self.setup()
                except Exception as err:
                    error("reload failed: %s" % err)

            interval = self._interval()
            elapsed = time.time() - started
            self._wait(max(0.05, interval - elapsed))
        self.shutdown()

    def _interval(self):
        state = str(self.provider.value("player.state"))
        if state in ("playing", "paused"):
            return self.config.frame_interval_playing
        return self.config.frame_interval_idle

    def _tick(self, now):
        if self.target is None:
            return
        if isinstance(self.target, display_module.AX206Target) and not self.target.is_open:
            if now < self._next_open_attempt:
                return
            if not self._open_target():
                return
            log("display reconnected")

        self._update_idle(now)
        self._apply_brightness()
        if self._blanked and self.config.off_on_idle:
            return

        if now < self._test_until:
            canvas = self.renderer.canvas
            self._draw_test_pattern(canvas)
        else:
            canvas = self.renderer.render(now)
            self._draw_notification(canvas, now)
        self.target.present(canvas)

    def _draw_test_pattern(self, canvas):
        """A calibration image: colour bars, a grid and the panel geometry."""
        width = canvas.width
        height = canvas.height
        canvas.reset_clip()
        canvas.clear(parse_color("#000000"))
        bars = ("#ffffff", "#ffff00", "#00ffff", "#00ff00",
                "#ff00ff", "#ff0000", "#0000ff", "#000000")
        bar_width = width // len(bars)
        for index, color in enumerate(bars):
            canvas.fill_rect(index * bar_width, 0, bar_width, height // 3,
                             parse_color(color))
        steps = 16
        step_width = width // steps
        for index in range(steps):
            level = index * 255 // (steps - 1)
            canvas.fill_rect(index * step_width, height // 3, step_width,
                             height // 8, (level, level, level, 255))
        for x in range(0, width, 40):
            canvas.fill_rect(x, height // 2, 1, height // 2, parse_color("#203040"))
        for y in range(height // 2, height, 40):
            canvas.fill_rect(0, y, width, 1, parse_color("#203040"))
        canvas.rect(0, 0, width, height, parse_color("#ff0000"), 1)
        font = self.fonts.get("sans-bold", 22)
        small = self.fonts.get("mono", 15)
        canvas.draw_text(font, "LCD4Linux test pattern", 16,
                         height // 2 + 34, parse_color("#ffffff"))
        canvas.draw_text(small, "%d x %d  rot %d  %s-endian"
                         % (width, height, self.config.rotation,
                            self.config.byte_order),
                         16, height // 2 + 60, parse_color("#9aa3b5"))
        canvas.draw_text(small, "red border must touch all four edges",
                         16, height // 2 + 82, parse_color("#9aa3b5"))

    def _handle_disconnect(self):
        if isinstance(self.target, display_module.AX206Target):
            try:
                self.target.close()
            except Exception:
                pass
        self._next_open_attempt = time.time() + max(
            5, int(self.config.retry_seconds))

    def _wait(self, seconds):
        if self.monitor is not None:
            if self.monitor.waitForAbort(seconds):
                self._stop = True
            return
        time.sleep(seconds)

    def stop(self):
        self._stop = True

    def shutdown(self):
        log("stopping")
        if self.target is not None and self.config.clear_on_exit:
            try:
                if isinstance(self.target, display_module.AX206Target) and self.target.is_open:
                    self.target.set_brightness(0)
                    self.target.device.clear(byte_order=self.config.byte_order)
            except Exception as err:
                debug("cannot clear the display: %s" % err)
        self._close_target()


def main():
    Service().run()
