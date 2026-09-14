"""The background service.

Renders the active layout at a modest frame rate, pushes only the changed
part of the frame to the panel and reacts to Kodi events (playback, settings
changes, notifications).
"""

import os
import subprocess
import time

from . import ax206
from . import display as display_module
from .errors import DisplayError
from . import layout as layout_module
from . import localize
from .bmfont import FontCache
from .images import ImageCache
from .kodidata import make_provider
from .logger import debug, error, log
from .settings import (Config, DEFAULTS, addon_path, ensure_user_directories,
                       profile_path)
from .usbdev import USBError
from .canvas import parse_color

try:
    import xbmc  # type: ignore
    import xbmcaddon  # type: ignore
    import xbmcgui  # type: ignore
except ImportError:
    xbmc = None
    xbmcaddon = None
    xbmcgui = None

#: Settings that can only take effect by re-opening the panel or rebuilding
#: the renderer.  Everything else is applied in place: Kodi reports a change
#: for every step of a slider, and tearing the USB link down for each of them
#: is what used to make the brightness setting look like it did nothing.
RELOAD_SETTINGS = frozenset((
    "output_mode", "display_type", "spf_model", "device_ids", "device_index",
    "device_serial", "byte_order", "rotation", "mirror", "force_size",
    "width", "height", "usb_timeout", "reset_on_open", "jpeg_quality",
    "jpeg_subsample", "layout", "layout_dir",
))

#: Settings the web editor is built from.  They only restart the little
#: HTTP server, never the USB link, so changing the port does not blank the
#: panel.
WEB_SETTINGS = frozenset(("web_enabled", "web_port", "web_bind",
                          "web_password", "output_mode"))

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
        # Handled by the service thread so nothing touches the USB link from
        # Kodi's callback thread.
        self.service.request_settings_refresh()

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
        self.web = None
        self._web_signature = None
        self._reload_requested = False
        self._settings_dirty = False
        self._stop = False
        self._notification = None
        self._idle = True
        self._brightness = None
        self._next_open_attempt = 0.0
        self._open_failures = 0
        self._test_until = 0.0
        self._start_command_done = False

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

    def request_settings_refresh(self):
        self._settings_dirty = True

    def refresh_settings(self):
        """Pick up changed settings without disturbing the display.

        Only a change that the panel or the renderer was built from asks for
        a full reload; a brightness, notification or frame rate change is
        applied to the running service, so the USB connection stays up.
        """
        try:
            config = Config(self._overrides)
        except Exception as err:
            error("cannot read the settings: %s" % err)
            return
        changed = sorted(key for key in DEFAULTS
                         if self.config.get(key) != config.get(key))
        if not changed:
            return
        if RELOAD_SETTINGS.intersection(changed):
            log("settings changed (%s), reloading" % ", ".join(changed))
            self.request_reload()
            return
        log("settings changed (%s), applying them in place" % ", ".join(changed))
        self.config = config
        if WEB_SETTINGS.intersection(changed):
            self.start_web_editor()
        if self.renderer is not None:
            self.renderer.default_interval = float(config.page_interval)
            self.renderer.smooth_images = bool(config.smooth_images)
        self._apply_brightness(force=True)

    def on_notification(self, sender, method, data):
        """Mirror the Kodi events that are worth putting on the panel."""
        if method.startswith("Other.") and method[6:] in CONTROL_COMMANDS:
            self._handle_command(method[6:], data)
            return
        if method in ("Player.OnPlay", "Player.OnResume", "Player.OnStop",
                      "Player.OnAVStart", "Player.OnPause"):
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
            self._step_brightness(1)
        elif command == "brightness_down":
            self._step_brightness(-1)
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
        # Runs before the display is opened, so it can switch the power on.
        if not self._start_command_done:
            self.run_hook("start", self.config.start_command)
            self._start_command_done = True
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
        self.start_web_editor()
        return opened

    # -- web editor -------------------------------------------------------
    def start_web_editor(self):
        """(Re)start the browser based layout editor if it is switched on.

        Imported here rather than at the top: a box that never opens the
        editor should not pay for the HTTP server module, and a failure to
        start one must never keep the display from working.

        A reload triggered from the editor itself must not pull the server
        out from under the browser, so an already running editor whose
        settings did not change is left alone.
        """
        signature = tuple(self.config.get(key) for key in sorted(WEB_SETTINGS))
        if self.web is not None and signature == self._web_signature:
            return True
        self.stop_web_editor()
        self._web_signature = signature
        # In network mode the server is not an optional design tool, it is
        # the display; the switch cannot turn it off.
        if not self.config.web_enabled and self.config.output_mode != "network":
            self._publish_web_url("")
            return False
        try:
            from . import webui
            editor = webui.WebEditor(self.config, self)
            if not editor.start():
                self._publish_web_url("")
                return False
            self.web = editor
            self._publish_web_url(editor.url())
            return True
        except Exception as err:
            error("cannot start the web editor: %s" % err)
            self._publish_web_url("")
            return False

    def stop_web_editor(self):
        if self.web is None:
            return
        self._web_signature = None
        try:
            self.web.stop()
        except Exception as err:
            debug("cannot stop the web editor: %s" % err)
        self.web = None

    def _publish_web_url(self, url):
        """Let the add-on menu show where the editor is listening."""
        if xbmcgui is None:
            return
        try:
            xbmcgui.Window(10000).setProperty("lcd4linux.weburl", url)
        except Exception:
            pass

    def run_hook(self, name, command):
        """Run a user configured shell command, e.g. to switch a smart plug.

        Samsung frames have no power control in their USB protocol, so the
        only way to really switch one off is to cut its mains supply; this
        hook is how the add-on asks something else to do that.
        """
        command = (command or "").strip()
        if not command:
            return None
        timeout = max(1, int(self.config.command_timeout))
        log("running %s command: %s" % (name, command))
        try:
            process = subprocess.Popen(command, shell=True,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT)
        except Exception as err:
            error("cannot run the %s command: %s" % (name, err))
            return None
        try:
            output = process.communicate(timeout=timeout)[0]
        except Exception:
            process.kill()
            error("the %s command did not finish within %d s" % (name, timeout))
            return None
        if process.returncode != 0:
            error("the %s command failed with code %d: %s"
                  % (name, process.returncode,
                     (output or b"").decode("utf-8", "replace").strip()))
        elif output:
            debug("%s command output: %s"
                  % (name, output.decode("utf-8", "replace").strip()))
        return process.returncode

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
            # Before the first level is sent, not after the first frame: the
            # panel would otherwise start at the idle brightness.
            self._update_idle()
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

    # -- brightness / dimming ---------------------------------------------
    def _brightness_pair(self):
        """``(normal, idle)`` brightness in the unit the target expects.

        The AX206 has a real backlight and is driven with its 0-7 level; a
        Samsung frame has none, so it gets a percentage and darkens the
        picture itself.
        """
        if self.target is not None and self.target.brightness_unit == "level":
            return int(self.config.brightness), int(self.config.dim_brightness)
        return int(self.config.spf_brightness), int(self.config.spf_dim_brightness)

    def _wanted_brightness(self):
        normal, dim = self._brightness_pair()
        if self._idle and self.config.dim_on_idle:
            return dim
        return normal

    def _apply_brightness(self, force=False):
        if self.target is None:
            return
        level = self._wanted_brightness()
        if not force and level == self._brightness:
            return
        if self.target.set_brightness(level):
            self._brightness = level
        else:
            # Do not remember a level the panel never took - the next frame
            # tries again instead of assuming it arrived.
            self._brightness = None

    def _step_brightness(self, direction):
        """The ``brightness_up``/``brightness_down`` commands."""
        if self.target is not None and self.target.brightness_unit == "level":
            key, step, low, high = "brightness", 1, 0, ax206.MAX_BRIGHTNESS
        else:
            key, step, low, high = "spf_brightness", 10, 10, 100
        value = int(self.config.get(key, high)) + direction * step
        self.config.set(key, max(low, min(high, value)))
        self._apply_brightness(force=True)

    def _update_idle(self):
        """Idle simply means nothing is playing; a pause still counts."""
        state = str(self.provider.value("player.state"))
        self._idle = state not in ("playing", "paused")

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
            except (DisplayError, USBError) as err:
                error("display error: %s" % err)
                self._handle_disconnect()
            except Exception as err:
                error("unexpected error: %s" % err)
                if self.config.debug:
                    import traceback
                    error(traceback.format_exc())

            if self._settings_dirty:
                self._settings_dirty = False
                self.refresh_settings()

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
        if getattr(self.target, "is_open", True) is False:
            if now < self._next_open_attempt:
                return
            if not self._open_target():
                return
            log("display reconnected")

        # Open the frame here rather than leaving it to the renderer: the
        # idle check below needs fresh data, and while the test pattern is
        # up the renderer never runs at all - which used to freeze the
        # dimming and the frame rate at whatever they were ten seconds ago.
        self.provider.begin_frame(now)
        self._update_idle()
        self._apply_brightness()

        force_redraw = False
        if now < self._test_until:
            canvas = self.renderer.canvas
            self._draw_test_pattern(canvas)
            force_redraw = True
        else:
            canvas = self.renderer.render(now)
            self._draw_notification(canvas, now)
        self.target.present(canvas, force=force_redraw)

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
        canvas.draw_text(font, localize.text(32341, "LCD4Linux test pattern"),
                         16, height // 2 + 34, parse_color("#ffffff"))
        canvas.draw_text(small, "%d x %d  rot %d  %s-endian"
                         % (width, height, self.config.rotation,
                            self.config.byte_order),
                         16, height // 2 + 60, parse_color("#9aa3b5"))
        canvas.draw_text(small,
                         localize.text(32342,
                                       "red border must touch all four edges"),
                         16, height // 2 + 82, parse_color("#9aa3b5"))

    def _handle_disconnect(self):
        if hasattr(self.target, "is_open"):
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
        # Clearing comes first: a network display is cleared *through* the
        # web server, so stopping that before the black frame would leave
        # the tablet frozen on the last picture.
        if self.target is not None and self.config.clear_on_exit:
            try:
                if isinstance(self.target, display_module.AX206Target) and self.target.is_open:
                    self.target.set_brightness(0)
                    self.target.device.clear(byte_order=self.config.byte_order)
                elif isinstance(self.target, display_module.SPFTarget) and self.target.is_open:
                    self.target.blank()
                elif isinstance(self.target, display_module.NetworkTarget) and self.target.is_open:
                    self.target.blank()
                    # Give the streaming threads their turn on the socket.
                    time.sleep(0.5)
            except Exception as err:
                debug("cannot clear the display: %s" % err)
        self.stop_web_editor()
        self._publish_web_url("")
        self._close_target()
        # Last, so the power can be cut once the USB connection is closed.
        self.run_hook("stop", self.config.stop_command)


def main():
    Service().run()
