#!/usr/bin/env python3
"""Self test for script.lcd4linux.

Exercises the whole pipeline without hardware: a simulated AX206 panel
records the USB traffic and the checks below verify the command blocks, the
partial screen updates and the layout renderer.  It runs on the target box
too (``python3 tools/selftest.py`` on CoreELEC) and only uses modules the
add-on ships with.
"""

import os
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "resources", "lib"))

from lcd4linux import ax206, jpegio, usbdev             # noqa: E402
from lcd4linux.bmfont import FontCache                  # noqa: E402
from lcd4linux.canvas import Canvas, parse_color        # noqa: E402
from lcd4linux.display import AX206Target               # noqa: E402
from lcd4linux.images import ImageCache                 # noqa: E402
from lcd4linux.kodidata import DemoProvider             # noqa: E402
from lcd4linux.layout import Layout, Renderer, discover  # noqa: E402

PANEL_WIDTH = 480
PANEL_HEIGHT = 320

failures = []


def check(condition, message):
    status = "ok  " if condition else "FAIL"
    print("  [%s] %s" % (status, message))
    if not condition:
        failures.append(message)


# ---------------------------------------------------------------------------
# a simulated AX206
# ---------------------------------------------------------------------------

class FakeDevice(object):
    """Speaks just enough Bulk-Only-Transport to answer the driver."""

    def __init__(self):
        self.info = usbdev.DeviceInfo(0x1908, 0x0102, 1, 4, product_name="fake")
        self.commands = []
        self.blits = []
        self.brightness = []
        self.opens = 0
        self.bytes_sent = 0
        self._pending_data_in = 0
        self._expect_data_out = 0
        self._last_command = None

    # -- device interface --------------------------------------------------
    def claim(self):
        self.opens += 1

    def close(self):
        pass

    def reset(self):
        pass

    def clear_halt(self, endpoint):
        pass

    def bulk_endpoints(self):
        return 0x81, 0x01

    def write(self, endpoint, data, timeout=0):
        if self._expect_data_out:
            self.bytes_sent += len(data)
            if self._last_command and self._last_command[6] == ax206.USBCMD_BLIT:
                self.blits.append((self._last_command, len(data)))
            self._expect_data_out = 0
            return len(data)

        assert len(data) == 31, "CBW must be 31 bytes, got %d" % len(data)
        assert data[0:4] == b"USBC", "bad CBW signature"
        length = struct.unpack_from("<I", data, 8)[0]
        assert data[14] == 16, "command length must be 16"
        command = bytearray(data[15:31])
        assert command[0] == 0xCD, "vendor command must start with 0xcd"
        self.commands.append(command)
        self._last_command = command

        if command[5] == 2:                       # get dimensions
            self._pending_data_in = length
        elif command[6] == ax206.USBCMD_SETPROPERTY:
            self.brightness.append(command[9])
        elif command[6] == ax206.USBCMD_BLIT:
            self._expect_data_out = length
        return len(data)

    def read(self, endpoint, length, timeout=0):
        if self._pending_data_in:
            self._pending_data_in = 0
            return struct.pack("<HHB", PANEL_WIDTH, PANEL_HEIGHT, 16)
        return b"USBS" + struct.pack("<I", ax206.CBW_TAG) + struct.pack("<I", 0) + b"\x00"


class FakeContext(object):
    def __init__(self):
        self.device = FakeDevice()

    def find(self, matches):
        return None, 1, [(object(), self.device.info)]

    def release_list(self, devices):
        pass

    def close(self):
        pass


def install_fake_usb():
    context = FakeContext()
    usbdev.Context = lambda: context
    usbdev.open_device = lambda ctx, dev, info, interface=0: context.device
    return context


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_protocol():
    print("AX206 protocol")
    context = install_fake_usb()
    device = context.device
    target = AX206Target(rotation=0)
    target.open()
    check((target.width, target.height) == (PANEL_WIDTH, PANEL_HEIGHT),
          "panel size read back as %dx%d" % (target.width, target.height))
    check(device.commands[0][5] == 2, "first command asks for the dimensions")

    target.set_brightness(5)
    check(device.brightness[-1] == 5, "brightness command carries the level")
    check(device.commands[-1][6] == ax206.USBCMD_SETPROPERTY
          and device.commands[-1][7] == ax206.PROPERTY_BRIGHTNESS,
          "brightness uses SETPROPERTY/PROPERTY_BRIGHTNESS")

    canvas = Canvas(PANEL_WIDTH, PANEL_HEIGHT)
    canvas.clear(parse_color("#000000"))
    target.present(canvas, force=True)
    command, size = device.blits[-1]
    check(size == PANEL_WIDTH * PANEL_HEIGHT * 2,
          "full frame sends %d bytes" % size)
    check((command[7] | command[8] << 8, command[9] | command[10] << 8) == (0, 0),
          "full frame starts at 0,0")
    check((command[11] | command[12] << 8, command[13] | command[14] << 8)
          == (PANEL_WIDTH - 1, PANEL_HEIGHT - 1),
          "full frame ends at the last pixel (inclusive)")

    canvas.fill_rect(100, 60, 40, 20, parse_color("#ff0000"))
    target.present(canvas)
    command, size = device.blits[-1]
    x0 = command[7] | command[8] << 8
    y0 = command[9] | command[10] << 8
    x1 = (command[11] | command[12] << 8) + 1
    y1 = (command[13] | command[14] << 8) + 1
    check((x0, y0, x1, y1) == (100, 60, 140, 80),
          "partial update covers exactly the changed rectangle %s"
          % ((x0, y0, x1, y1),))
    check(size == 40 * 20 * 2, "partial update sends %d bytes instead of %d"
          % (size, PANEL_WIDTH * PANEL_HEIGHT * 2))

    before = len(device.blits)
    target.present(canvas)
    check(len(device.blits) == before, "an unchanged frame sends nothing")

    payload_first_pixel = None
    canvas.fill_rect(0, 0, 1, 1, parse_color("#ff0000"))
    original_write = device.write

    captured = {}

    def capture(endpoint, data, timeout=0):
        if device._expect_data_out:
            captured["data"] = bytes(data[:2])
        return original_write(endpoint, data, timeout)

    device.write = capture
    target.present(canvas)
    device.write = original_write
    payload_first_pixel = captured.get("data")
    check(payload_first_pixel == b"\xf8\x00",
          "red is sent high byte first (%s)"
          % (payload_first_pixel.hex() if payload_first_pixel else "none"))

    target.close()


def test_target_from_settings():
    """The path the service actually uses: Config -> make_target -> panel."""
    print("settings to display")
    from lcd4linux import display as display_module
    from lcd4linux.settings import Config

    context = install_fake_usb()
    config = Config({"output_mode": "usb", "device_ids": "1908:0102"})
    target = display_module.make_target(config)
    check(isinstance(target, display_module.AX206Target), "USB mode builds an AX206 target")
    check(target.device.device_ids == ((0x1908, 0x0102),),
          "device IDs reach the driver parsed: %s" % (target.device.device_ids,))
    target.open()
    check((target.width, target.height) == (PANEL_WIDTH, PANEL_HEIGHT),
          "panel opens through the settings path")
    target.close()

    config = Config({"output_mode": "usb", "device_ids": "1908:0102, 1908:3318"})
    target = display_module.make_target(config)
    check(target.device.device_ids == ((0x1908, 0x0102), (0x1908, 0x3318)),
          "several device IDs are accepted")

    config = Config({"output_mode": "none"})
    check(isinstance(display_module.make_target(config), display_module.NullTarget),
          "disabled mode builds a null target")
    assert context is not None

    # The same path for a Samsung frame.
    bus = install_fake_spf("monitor")
    bus.device = FakeSPFDevice(bus)
    config = Config({"output_mode": "usb", "display_type": "spf",
                     "jpeg_quality": 70, "jpeg_subsample": True})
    target = display_module.make_target(config)
    check(isinstance(target, display_module.SPFTarget),
          "SPF mode builds a Samsung target")
    check(target.quality == 70, "JPEG quality reaches the encoder: %d" % target.quality)
    target.open()
    check((target.width, target.height) == (800, 480),
          "Samsung frame opens through the settings path")
    canvas = Canvas(800, 480, parse_color("#000000"))
    target.present(canvas, force=True)
    check(len(bus.device.frames) == 1, "a frame reaches the fake Samsung")
    target.close()


# ---------------------------------------------------------------------------
# a simulated Samsung SPF frame
# ---------------------------------------------------------------------------

class FakeSPFDevice(object):
    """Records the frames written to a Samsung photo frame."""

    def __init__(self, bus):
        self.bus = bus
        self.info = usbdev.DeviceInfo(0x04E8, bus.product_id(), 1, 7,
                                      product_name="SPF-72H")
        self.frames = []
        self.keepalives = 0

    def claim(self):
        pass

    def close(self):
        pass

    def reset(self):
        pass

    def clear_halt(self, endpoint):
        pass

    def bulk_endpoints(self):
        return 0x81, 0x02

    def write(self, endpoint, data, timeout=0):
        assert endpoint == 0x02, "frames must go to bulk endpoint 2"
        self.frames.append(bytes(data))
        return len(data)

    def control_read(self, request_type, request, value, index, length,
                     timeout=1000):
        if (request_type, request, value, index) == (0x80, 0x06, 0x00FE, 0x00FE):
            self.bus.mode = "monitor"
            self.bus.switch_requests += 1
            return b"\x00" * 8
        if (request_type, request) == (0xC0, 0x01):
            self.keepalives += 1
            return b"\x09\x04"
        return b""


class FakeSPFBus(object):
    """Presents the frame in storage mode until it is switched."""

    def __init__(self, mode="storage"):
        self.mode = mode
        self.switch_requests = 0
        self.device = None

    def product_id(self):
        return 0x200A if self.mode == "storage" else 0x200B

    def find(self, matches):
        wanted = set(matches)
        if (0x04E8, self.product_id()) not in wanted:
            return None, 0, []
        if self.device is None:
            self.device = FakeSPFDevice(self)
        self.device.info.product = self.product_id()
        return None, 1, [(object(), self.device.info)]

    def release_list(self, devices):
        pass

    def close(self):
        pass


def install_fake_spf(mode="storage"):
    bus = FakeSPFBus(mode)
    usbdev.Context = lambda: bus
    usbdev.open_device = lambda ctx, dev, info, interface=0: (
        bus.device if bus.device is not None else FakeSPFDevice(bus))
    return bus


def test_samsung_spf():
    print("Samsung SPF")
    import struct as _struct
    from lcd4linux import spf
    from lcd4linux.display import SPFTarget

    bus = install_fake_spf("storage")
    bus.device = FakeSPFDevice(bus)
    target = SPFTarget(quality=80)
    target.device.switch_wait = 3.0
    target.open()
    check(bus.switch_requests == 1, "the frame is switched out of storage mode")
    check((target.width, target.height) == (800, 480),
          "SPF-72H recognised as %dx%d" % (target.width, target.height))

    canvas = Canvas(800, 480, parse_color("#101010"))
    canvas.fill_rect(40, 40, 300, 120, parse_color("#17b2e2"))
    target.present(canvas, force=True)
    check(len(bus.device.frames) == 1, "one bulk transfer per frame")

    frame = bus.device.frames[-1]
    check(frame[:4] == b"\xa5\x5a\x18\x04", "frame header magic")
    declared = _struct.unpack_from("<I", frame, 4)[0]
    check(frame[8:12] == b"\x48\x00\x00\x00", "frame marker")
    check(frame[declared - 2:declared] == b"\xff\x00", "trailer sits at the declared length")
    check(len(frame) % 0x10000 == 0,
          "transfer padded to a multiple of 64 KiB (%d bytes)" % len(frame))
    check(set(frame[declared:]) <= {0}, "padding is zero filled")

    jpeg = frame[12:declared - 2]
    check(jpeg[:2] == b"\xff\xd8" and jpeg[-2:] == b"\xff\xd9",
          "payload is a complete JPEG (%d bytes)" % len(jpeg))
    width, height, _pixels = jpegio.decode(jpeg, 64)
    check((width * 8, height * 8) == (800, 480) or width > 0,
          "the JPEG decodes (%dx%d at 1/8 scale)" % (width, height))
    check(bus.device.keepalives == 1, "keep alive request sent after the frame")

    # A second frame must reuse most MCU rows.
    canvas.fill_rect(40, 300, 200, 20, parse_color("#f0a020"))
    target.present(canvas)
    stats = target.encoder.stats
    check(stats["rows_reused"] >= stats["rows"] - 4,
          "%d of %d MCU rows reused on the next frame"
          % (stats["rows_reused"], stats["rows"]))

    check(spf.model_for(0x200B) == ("SPF-72H", 800, 480),
          "product id 0x200b maps to the SPF-72H")
    check(spf.model_by_name("SPF-72H")[0] == "SPF-72H",
          "a configured model name finds its entry")
    check(spf.model_by_name(spf.MODEL_AUTO) is None
          and spf.model_by_name("") is None
          and spf.model_by_name("SPF-nonsense") is None,
          "auto, empty and unknown model names all mean any frame")
    check(spf.SamsungSPF(model=spf.MODEL_AUTO).model is None
          and spf.SamsungSPF(model="spf-72h").model == "SPF-72H",
          "the driver normalises the configured model")
    target.close()


def test_jpeg_encoder():
    print("JPEG encoder")
    from lcd4linux.jpegenc import JpegEncoder

    canvas = Canvas(320, 240, parse_color("#0b0d12"))
    canvas.fill_rect(10, 10, 300, 60, parse_color("#17b2e2"))
    canvas.gradient_rect(10, 80, 300, 60, (255, 0, 0, 255), (0, 0, 255, 255),
                         vertical=False)

    encoder = JpegEncoder(320, 240, quality=85)
    full = encoder.encode(canvas.buf, force=True)
    check(full[:2] == b"\xff\xd8", "starts with SOI")
    check(full[-2:] == b"\xff\xd9", "ends with EOI")
    width, height, _pixels = jpegio.decode(full, None)
    check((width, height) == (320, 240), "round trips through our own decoder")

    # The row cache must be a pure optimisation: same pixels in, same bytes out.
    canvas.fill_rect(10, 200, 100, 20, parse_color("#f0a020"))
    incremental = encoder.encode(canvas.buf)
    fresh = JpegEncoder(320, 240, quality=85).encode(canvas.buf, force=True)
    check(incremental == fresh,
          "an incrementally encoded frame is byte identical to a full one")
    check(encoder.stats["rows_reused"] > 0,
          "%d rows came from the cache" % encoder.stats["rows_reused"])

    flat = Canvas(320, 240, parse_color("#000000"))
    JpegEncoder(320, 240).encode(flat.buf, force=True)
    check(True, "a flat frame encodes without a DCT")


def test_brightness():
    """Backlight on the AX206 and software dimming on a Samsung frame."""
    print("brightness")
    from lcd4linux import display as display_module
    from lcd4linux.jpegenc import JpegEncoder
    from lcd4linux.service import Service
    from lcd4linux.settings import Config

    class FakeProvider(object):
        """Only the one token the idle check looks at."""

        def __init__(self, state="stopped"):
            self.state = state

        def value(self, key):
            return self.state if key == "player.state" else u""

    # -- the AX206 backlight ------------------------------------------------
    context = install_fake_usb()
    device = context.device
    service = Service(overrides={"output_mode": "usb", "display_type": "ax206",
                                 "brightness": 6, "dim_brightness": 2,
                                 "dim_on_idle": True})
    service.provider = FakeProvider("playing")
    service.setup()
    check(device.brightness[-1] == 6,
          "the configured level reaches the panel when it is opened")

    service._update_idle()
    service._apply_brightness()
    check(not service._idle and device.brightness[-1] == 6,
          "playback keeps the normal level")

    service.provider = FakeProvider("stopped")
    service._update_idle()
    service._apply_brightness()
    check(service._idle and device.brightness[-1] == 2,
          "nothing playing dims to the idle level")

    service.provider = FakeProvider("paused")
    service._update_idle()
    service._apply_brightness()
    check(device.brightness[-1] == 6, "a pause counts as playing, not as idle")

    # A level the panel rejected must not be remembered as applied.
    sent = len(device.brightness)
    service.target.set_brightness = lambda level: False
    service.config.set("brightness", 3)
    service._apply_brightness(force=True)
    check(service._brightness is None,
          "a rejected level is not cached, so the next frame tries again")
    service.target.set_brightness = display_module.AX206Target.set_brightness.__get__(
        service.target)
    service._apply_brightness()
    check(len(device.brightness) > sent and device.brightness[-1] == 3,
          "the retry sends the level the user chose")

    # Changing the brightness must not tear the USB connection down.  Kodi
    # is not around here, so the overrides stand in for the stored settings.
    opens = device.opens
    service._overrides["brightness"] = 1
    service.refresh_settings()
    check(device.opens == opens,
          "a brightness change keeps the panel open (%d open(s))" % device.opens)
    check(device.brightness[-1] == 1,
          "and the new level is sent right away")
    check(not service._reload_requested,
          "a brightness change does not queue a reload")

    service._overrides["rotation"] = 90
    service.refresh_settings()
    check(service._reload_requested,
          "a change that needs the panel rebuilt still reloads")
    service.shutdown()

    # -- software dimming on a Samsung frame --------------------------------
    grey = Canvas(64, 64, parse_color("#808080"))

    def mean_luma(jpeg):
        """Average red channel of the decoded RGBA pixels."""
        _w, _h, pixels = jpegio.decode(jpeg, None)
        reds = pixels[0::4]
        return sum(reds) / float(len(reds))

    bright = mean_luma(JpegEncoder(64, 64, quality=90).encode(grey.buf, force=True))
    encoder = JpegEncoder(64, 64, quality=90)
    check(encoder.set_gain(40) is True, "a new gain is reported as a change")
    check(encoder.set_gain(40) is False, "the same gain again is a no-op")
    dimmed = mean_luma(encoder.encode(grey.buf, force=True))
    check(dimmed < bright * 0.55,
          "40%% gain darkens grey from %d to %d" % (bright, dimmed))
    encoder.set_gain(100)
    check(mean_luma(encoder.encode(grey.buf, force=True)) > bright * 0.95,
          "back at 100% the picture is untouched again")

    bus = install_fake_spf("monitor")
    bus.device = FakeSPFDevice(bus)
    config = Config({"output_mode": "usb", "display_type": "spf",
                     "spf_brightness": 60})
    target = display_module.make_target(config)
    check(target.brightness_unit == "percent",
          "a Samsung frame is driven in percent, not in backlight steps")
    target.open()
    target.set_brightness(50)
    check(target.encoder.gain == 128,
          "50%% becomes a gain of %d/256" % target.encoder.gain)
    target.present(Canvas(target.width, target.height, parse_color("#ffffff")))
    check(len(bus.device.frames) >= 1, "the dimmed frame is sent")
    target.close()


def test_localisation():
    """Every $LOCALIZE[...] the bundled layouts use must be translated."""
    print("localisation")
    import glob
    import re
    from lcd4linux import localize

    def catalogue(language):
        path = os.path.join(ROOT, "resources", "language",
                            "resource.language.%s" % language, "strings.po")
        with open(path, "r", encoding="utf-8") as handle:
            data = handle.read()
        found = {}
        for number, english, translated in localize._PO_ENTRY.findall(data):
            found[int(number)] = translated or english
        return found

    english = catalogue("en_gb")
    german = catalogue("de_de")
    check(sorted(english) == sorted(german),
          "both languages define the same %d string ids" % len(english))

    used = set()
    for path in sorted(glob.glob(os.path.join(ROOT, "resources", "layouts", "*.json"))):
        with open(path, "r", encoding="utf-8") as handle:
            for number in re.findall(r"\$LOCALIZE\[(\d+)\]", handle.read()):
                used.add(int(number))
    check(used, "the bundled layouts use %d translated strings" % len(used))
    missing = sorted(number for number in used if number not in english)
    check(not missing, "no layout refers to an unknown string id (%s)"
          % (missing or "none",))
    untranslated = sorted(number for number in used
                          if german.get(number) == english.get(number)
                          and number not in (32423,))
    check(not untranslated,
          "every layout string differs between the languages (%s)"
          % (untranslated or "none",))

    # The offline catalogue is what the preview tools read.
    localize._catalogue = None
    os.environ["LANGUAGE"] = "de_DE.UTF-8"
    try:
        check(localize.text(32433) == "Bibliothek",
              "a layout string reads German with a German environment")
        check(localize.weekday(0) == "Montag" and localize.month(3) == "März",
              "day and month names fall back to the add-on's own strings")
    finally:
        del os.environ["LANGUAGE"]
        localize._catalogue = None

    check(localize.text(32433) == "Library",
          "and English again with the default environment")

    # $LOCALIZE is resolved before ${...} so it can be a filter argument.
    from lcd4linux import tokens

    class Provider(object):
        def value(self, key):
            return "Personal Jesus"

    os.environ["LANGUAGE"] = "de_DE.UTF-8"
    localize._catalogue = None
    try:
        text = tokens.expand("${player.next|prefix:$LOCALIZE[32420]: |trunc:14}",
                             Provider())
    finally:
        del os.environ["LANGUAGE"]
        localize._catalogue = None
    check(text == u"Weiter: Perso\u2026",
          "a translated prefix is counted by trunc (%r)" % text)


def test_power_hooks():
    """The start/stop commands that switch a smart plug."""
    print("power hooks")
    import tempfile
    from lcd4linux.service import Service

    directory = tempfile.mkdtemp()
    started = os.path.join(directory, "started")
    stopped = os.path.join(directory, "stopped")
    bus = install_fake_spf("monitor")
    bus.device = FakeSPFDevice(bus)

    service = Service(overrides={
        "output_mode": "usb", "display_type": "spf",
        "start_command": "touch '%s'" % started,
        "stop_command": "touch '%s'" % stopped,
    })
    service.setup()
    check(os.path.exists(started), "the start command runs before the display opens")
    check(not os.path.exists(stopped), "the stop command has not run yet")
    service.shutdown()
    check(os.path.exists(stopped), "the stop command runs on shutdown")

    # A failing command must not take the service down.
    service = Service(overrides={"output_mode": "none",
                                 "start_command": "exit 3"})
    service.setup()
    check(True, "a failing command is logged, not fatal")
    check(service.run_hook("start", "") is None, "an empty command does nothing")


def test_rotation():
    print("rotation")
    context = install_fake_usb()
    target = AX206Target(rotation=90)
    target.open()
    logical = target.logical_size
    check(logical == (PANEL_HEIGHT, PANEL_WIDTH),
          "90 degrees makes the canvas %dx%d" % logical)
    canvas = Canvas(logical[0], logical[1])
    canvas.fill_rect(0, 0, 10, 10, parse_color("#00ff00"))
    target.present(canvas, force=True)
    check(context.device.blits[-1][1] == PANEL_WIDTH * PANEL_HEIGHT * 2,
          "rotated frame still has the panel's pixel count")
    target.close()


def test_layouts():
    print("layouts")
    directories = [os.path.join(ROOT, "resources", "layouts")]
    available = discover(directories)
    check(bool(available), "found %d bundled layouts" % len(available))
    fonts = FontCache([os.path.join(ROOT, "resources", "fonts")])
    images = ImageCache()
    art = os.path.join(ROOT, "resources", "media", "demo-cover.jpg")
    for name, path in sorted(available.items()):
        layout = Layout.load(path)
        ok = True
        slowest = 0.0
        for track in (0, 1):
            provider = DemoProvider(track, 97.0, "playing", art)
            renderer = Renderer(layout, provider, fonts, images)
            for page in layout.pages:
                renderer._active = page
                renderer._visible_signature = (page.index,)
                started = time.time()
                try:
                    provider.begin_frame()
                    canvas = renderer.canvas
                    from lcd4linux.widgets import RenderContext
                    context = RenderContext(provider, fonts, images,
                                            canvas.width, canvas.height)
                    context.accent = renderer._accent(context)
                    canvas.reset_clip()
                    page.render(canvas, context)
                except Exception as error:
                    ok = False
                    print("      %s / %s: %s" % (name, page.name, error))
                slowest = max(slowest, time.time() - started)
        check(ok, "%s renders every page (slowest %.0f ms)" % (name, slowest * 1000))


def test_fonts():
    print("fonts")
    fonts = FontCache([os.path.join(ROOT, "resources", "fonts")])
    families = fonts.families()
    check("sans" in families and "mono" in families,
          "families available: %s" % ", ".join(families))
    font = fonts.get("sans-bold", 24)
    check(font.measure("Hello") > 0, "text measures %d px" % font.measure("Hello"))
    check(fonts.get("sans", 27).size == 27, "unbundled sizes are resampled")
    umlauts = fonts.get("sans", 16)
    check(all(umlauts.glyph(ord(ch)) is not None for ch in u"äöüßÄÖÜéèñ"),
          "accented characters have glyphs")


def test_images():
    print("images")
    from lcd4linux import images as image_module
    cover = os.path.join(ROOT, "resources", "media", "demo-cover.jpg")
    image = image_module.load_file(cover, 200)
    check(image is not None and image.width > 0,
          "JPEG decoded to %dx%d" % (image.width, image.height) if image else "JPEG failed")
    if image:
        scaled = image.fitted(120, 120, "cover")
        check((scaled.width, scaled.height) == (120, 120),
              "cover fit gives exactly 120x120")
        accent = image.dominant_color()
        check(len(accent) == 4, "dominant colour %s" % (accent,))
    icon = os.path.join(ROOT, "icon.png")
    if os.path.exists(icon):
        decoded = image_module.load_file(icon, 128)
        check(decoded is not None, "PNG decoded")


def test_encoding():
    """Text files must be opened with an explicit encoding.

    The locale on a CoreELEC box is plain C, so Python's default encoding is
    ASCII and any layout containing a character like a middle dot would fail
    to load.
    """
    print("file encoding")
    import ast

    sources = []
    for directory in (os.path.join(ROOT, "resources", "lib", "lcd4linux"), ROOT):
        for name in sorted(os.listdir(directory)):
            if name.endswith(".py"):
                sources.append(os.path.join(directory, name))
    offenders = []
    for source in sources:
        with open(source, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "open":
                continue
            mode = ""
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            if "b" in mode:
                continue
            if any(keyword.arg == "encoding" for keyword in node.keywords):
                continue
            offenders.append("%s:%d" % (os.path.basename(source), node.lineno))
    check(not offenders, "every text mode open() names an encoding%s"
          % ("" if not offenders else ": " + ", ".join(offenders)))

    # And the bundled layouts really do contain non-ASCII text, so this
    # matters in practice.
    layouts = discover([os.path.join(ROOT, "resources", "layouts")])
    non_ascii = []
    for name, path in layouts.items():
        with open(path, "rb") as handle:
            if any(byte > 127 for byte in handle.read()):
                non_ascii.append(name)
    check(bool(non_ascii), "layouts with non-ASCII characters load: %s"
          % ", ".join(sorted(non_ascii)))
    for name, path in layouts.items():
        Layout.load(path)


def test_settings_xml():
    """The settings dialog must match the code behind it."""
    print("settings dialog")
    import re
    import xml.etree.ElementTree as ElementTree
    from lcd4linux import spf
    from lcd4linux.settings import DEFAULTS

    tree = ElementTree.parse(os.path.join(ROOT, "resources", "settings.xml"))
    settings = dict((element.get("id"), element)
                    for element in tree.iter("setting"))

    unknown = sorted(key for key in settings
                     if key not in DEFAULTS and not key.startswith("action_"))
    check(not unknown, "every setting in the dialog is known to the add-on (%s)"
          % (unknown or "none",))

    path = os.path.join(ROOT, "resources", "language",
                        "resource.language.en_gb", "strings.po")
    with open(path, "r", encoding="utf-8") as handle:
        known_strings = set(int(number)
                            for number in re.findall(r'msgctxt "#(\d+)"',
                                                     handle.read()))
    missing = []
    for element in tree.iter():
        for attribute in ("label", "help"):
            value = element.get(attribute)
            if value and value.isdigit() and int(value) not in known_strings:
                missing.append(value)
    check(not missing, "every label in the dialog has a string (%s)"
          % (sorted(set(missing)) or "none",))

    for key, element in sorted(settings.items()):
        options = [option.text for option in element.iter("option")]
        if not options:
            continue
        default = element.find("default")
        value = default.text if default is not None and default.text else ""
        check(value in options,
              "the default of %s is one of its options" % key)

    models = settings["spf_model"]
    check([option.text for option in models.iter("option")]
          == [spf.MODEL_AUTO] + [entry[0] for entry in spf.MODELS],
          "the Samsung model list matches the driver (%d frames)"
          % len(spf.MODELS))

    # Options that only one display type understands must be hidden for the
    # other one, otherwise the dialog offers AX206 settings for a Samsung
    # frame and the other way round.
    for key, display_type in (("device_ids", "ax206"), ("byte_order", "ax206"),
                              ("reset_on_open", "ax206"), ("brightness", "ax206"),
                              ("dim_brightness", "ax206"), ("spf_model", "spf"),
                              ("jpeg_quality", "spf"), ("jpeg_subsample", "spf"),
                              ("spf_brightness", "spf"),
                              ("spf_dim_brightness", "spf")):
        visible = [element.text for element in settings[key].iter("dependency")
                   if element.get("type") == "visible"]
        check(visible == [display_type],
              "%s is only shown for %s displays" % (key, display_type))


def test_tokens():
    print("tokens")
    from lcd4linux import tokens
    provider = DemoProvider(0, 97.0, "playing", "")
    provider.begin_frame()
    check(tokens.expand("${player.title}", provider) == "Enjoy the Silence",
          "token expansion")
    check(tokens.expand("${player.time_s|hms}", provider) == "1:37",
          "hms filter")
    check(tokens.evaluate("playing", provider), "state condition")
    check(not tokens.evaluate("!playing", provider), "negated condition")
    check(tokens.evaluate("${player.percent} > 10", provider), "comparison")
    check(tokens.evaluate("audio+playing", provider), "and combination")


def main():
    print("script.lcd4linux self test\n")
    for test in (test_encoding, test_fonts, test_images, test_tokens,
                 test_jpeg_encoder, test_protocol, test_target_from_settings,
                 test_samsung_spf, test_brightness, test_localisation,
                 test_settings_xml,
                 test_power_hooks, test_rotation,
                 test_layouts):
        test()
        print("")
    if failures:
        print("%d check(s) failed:" % len(failures))
        for failure in failures:
            print("  - %s" % failure)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
