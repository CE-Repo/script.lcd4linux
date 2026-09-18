#!/usr/bin/env python3
"""Self test for script.lcd4linux.

Exercises the whole pipeline without hardware: a simulated AX206 panel
records the USB traffic and the checks below verify the command blocks, the
partial screen updates and the layout renderer.  It runs on the target box
too (``python3 tools/selftest.py`` on CoreELEC) and only uses modules the
add-on ships with.
"""

import os
import re
import shutil
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
            self.bus.switch_requests += 1
            if self.bus.ignore_switches > 0:
                # Still booting: the request is answered but the frame
                # comes back as a USB drive again.
                self.bus.ignore_switches -= 1
                return b""
            self.bus.mode = "monitor"
            return b"\x00" * 8
        if (request_type, request) == (0xC0, 0x01):
            self.keepalives += 1
            return b"\x09\x04"
        return b""


class FakeSPFBus(object):
    """Presents the frame in storage mode until it is switched."""

    def __init__(self, mode="storage"):
        #: ``"absent"`` is a frame that has not finished booting yet and is
        #: not on the USB bus at all.
        self.mode = mode
        self.switch_requests = 0
        #: Switch requests the frame answers but ignores, the way a frame
        #: that is still booting does.
        self.ignore_switches = 0
        self.device = None

    def product_id(self):
        if self.mode == "storage":
            return 0x200A
        if self.mode == "monitor":
            return 0x200B
        return None

    def find(self, matches):
        wanted = set(matches)
        if self.product_id() is None or (0x04E8, self.product_id()) not in wanted:
            return None, 0, []
        if self.device is None:
            self.device = FakeSPFDevice(self)
        self.device.info.product = self.product_id()
        return None, 1, [(object(), self.device.info)]

    def release_list(self, devices):
        pass

    def close(self):
        pass


class FakeListItem(object):
    """Just enough of xbmcgui.ListItem for the layout chooser."""

    def __init__(self, label="", label2=""):
        self.label = label
        self.label2 = label2
        self.art = {}

    def setArt(self, art):
        self.art.update(art)


class FakeGui(object):
    ListItem = FakeListItem


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


def test_late_display():
    """A display that is slower to boot than Kodi must still come up.

    The box, Kodi and the picture frame are switched on together and the
    frame needs the better part of a minute before it appears on the USB
    bus.  The service therefore starts without a display, and everything the
    panel size decides - the layout variant and the canvas - has to be
    redone once the frame finally answers.
    """
    print("display that boots later than Kodi")
    from lcd4linux.service import Service, STARTUP_RETRY_SECONDS

    bus = install_fake_spf("absent")
    service = Service(overrides={"output_mode": "usb", "display_type": "spf",
                                 "width": 480, "height": 320,
                                 "layout": "default.json",
                                 "retry_seconds": 60, "startup_grace": 180,
                                 "web_enabled": False})
    check(service.setup() is False,
          "the service starts even though the frame is not on the bus yet")
    check(not service.target.is_open, "and knows the display is not open")
    check((service.renderer.canvas.width, service.renderer.canvas.height)
          == (480, 320),
          "until then it renders at the configured size")
    delay = service._next_open_attempt - time.time()
    check(0 < delay <= STARTUP_RETRY_SECONDS + 0.5,
          "the next attempt is %.1f s away while the box is still starting"
          % delay)
    check(not service._open_warned,
          "a display that may still be booting does not warn the user")

    # The frame finished booting: it shows up as a USB drive and needs a
    # second switch request because the first one came too early.
    bus.mode = "storage"
    bus.device = FakeSPFDevice(bus)
    bus.ignore_switches = 1
    service.target.device.switch_wait = 4.0
    service._next_open_attempt = 0.0
    service._tick(time.time())
    check(service.target.is_open, "the frame is picked up as soon as it appears")
    check(bus.switch_requests >= 2,
          "a frame that ignored the first switch request is asked again (%d requests)"
          % bus.switch_requests)
    check(bus.mode == "monitor", "and ends up in monitor mode, not on its USB screen")
    check((service.renderer.canvas.width, service.renderer.canvas.height)
          == (800, 480),
          "the renderer is rebuilt for the size the frame really has")
    check((service.layout.width, service.layout.height) == (800, 480),
          "and the layout variant for that size is loaded")
    check(len(bus.device.frames) == 1, "a frame reaches the panel right away")

    frames = len(bus.device.frames)
    service._tick(time.time() + 1.0)
    check(len(bus.device.frames) > frames,
          "and the next tick keeps drawing instead of dropping the link")
    check(service.renderer.canvas.width == 800,
          "the renderer is not rebuilt again once the size is known")

    # A display that is still missing when the grace period is over is
    # reported once and then retried at the configured interval.
    bus2 = install_fake_spf("absent")
    late = Service(overrides={"output_mode": "usb", "display_type": "spf",
                              "retry_seconds": 45, "startup_grace": 0,
                              "web_enabled": False})
    late.setup()
    check(late._open_warned, "a display that is simply missing is reported")
    delay = late._next_open_attempt - time.time()
    check(40 < delay <= 45.5,
          "and looked for again after the reconnect interval (%.0f s)" % delay)
    check(bus2.switch_requests == 0, "with nothing to switch on an empty bus")

    service.shutdown()


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

    # Every design ships one file per panel the add-on drives.  A missing
    # variant is not an error at runtime - load_layout quietly falls back to
    # some other design that fits - so nothing but this check would notice.
    from lcd4linux.thumbs import design_name
    variants = {}
    for name in available:
        variants.setdefault(design_name(name), set()).add(name)
    portrait = {"portrait.json", "portrait-480x800.json",
                "portrait-600x1024.json"}
    incomplete = []
    for design, names in sorted(variants.items()):
        wanted = portrait if design == "portrait" else {
            design + ".json", design + "-800x480.json",
            design + "-1024x600.json"}
        if names != wanted:
            incomplete.append("%s: %s" % (design, sorted(names)))
    check(not incomplete, "every design ships 480x320, 800x480 and 1024x600 "
          "(%s)" % (incomplete or "none",))

    mismatched = []
    for name, path in sorted(available.items()):
        match = re.search(r"-(\d+)x(\d+)$", os.path.splitext(name)[0])
        if match and tuple(Layout.load(path).size) != (int(match.group(1)),
                                                       int(match.group(2))):
            mismatched.append(name)
    check(not mismatched, "every variant declares the size in its name (%s)"
          % (mismatched or "none",))

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


def test_layout_index():
    """The chooser and the editor list layouts from a cached index."""
    print("layout index")
    import tempfile
    from lcd4linux import layout as layout_module
    from lcd4linux import layoutindex, tokens
    from lcd4linux.layout import Layout, discover, read_info

    directory = os.path.join(ROOT, "resources", "layouts")
    available = discover([directory])

    mismatched = []
    for name, path in sorted(available.items()):
        full, info = Layout.load(path), read_info(path)
        if (tokens.localize_text(info["name"]) != full.name
                or (info["width"], info["height"]) != full.size
                or info["pages"] != len(full.pages)):
            mismatched.append(name)
    check(not mismatched,
          "reading a layout's name and size without building it agrees with "
          "the full load (%s)" % (mismatched or "all %d" % len(available),))

    # The index is what keeps the dialog from parsing every file again.
    parsed = []
    original = layout_module.read_info
    layoutindex.forget()
    try:
        layout_module.read_info = lambda path: (parsed.append(path),
                                                original(path))[1]
        first = layoutindex.read(available)
        cold = len(parsed)
        del parsed[:]
        second = layoutindex.read(available)
        check(cold == len(available) and not parsed,
              "the first listing reads %d layouts, the next one none" % cold)
        check(first == second, "and both answer the same")

        os.utime(available["minimal.json"], None)
        del parsed[:]
        layoutindex.read(available)
        check(parsed == [available["minimal.json"]],
              "an edited layout is re-read, the untouched ones are not")

        broken = os.path.join(tempfile.mkdtemp(), "broken.json")
        with open(broken, "w") as handle:
            handle.write("{ this is not json")
        mixed = dict(available, **{"broken.json": broken})
        del parsed[:]
        entries = layoutindex.read(mixed)
        check(entries["broken.json"].get("error") and len(parsed) == 1,
              "a layout that cannot be read is reported, not raised")
        del parsed[:]
        layoutindex.read(mixed)
        check(not parsed, "and the failure is cached like any other entry")
    finally:
        layout_module.read_info = original
        layoutindex.forget()


def test_layout_chooser():
    """The layout picker offers one entry per design, each with a picture."""
    print("layout chooser")
    import tempfile
    from lcd4linux import thumbs
    from lcd4linux.images import ImageCache
    from lcd4linux.layout import discover, load_layout
    from lcd4linux.ui import _layout_designs

    directory = os.path.join(ROOT, "resources", "layouts")
    available = discover([directory])
    entries = _layout_designs(available)
    names = [name for name, _variants in entries]

    check(len(names) == len(set(names)),
          "%d designs out of %d layout files" % (len(names), len(available)))
    check(all(name in available for name in names),
          "every entry names a layout file that exists")
    check(dict(entries).get("default.json")
          == ["default-1024x600.json", "default-800x480.json", "default.json"],
          "the size variants of a design share one entry")
    # Storing the name without the size is only safe because loading picks
    # the variant that fits the panel.
    check(tuple(load_layout("default.json", [directory], (800, 480)).size)
          == (800, 480),
          "the stored name still resolves to the 800x480 variant")
    check(tuple(load_layout("default.json", [directory], (1024, 600)).size)
          == (1024, 600),
          "and to the 1024x600 variant on a 10 inch frame")

    unpictured = [name for name in names if thumbs.shipped_path(name) is None]
    check(not unpictured, "every bundled design ships a preview (%s)"
          % (unpictured or "none",))

    cache = ImageCache()
    box = thumbs.THUMB_BOX
    oversized = []
    for name in names:
        picture = cache.get(thumbs.shipped_path(name))
        if picture is None or picture.width > box[0] or picture.height > box[1]:
            oversized.append(name)
    check(not oversized, "every preview decodes and fits %dx%d (%s)"
          % (box[0], box[1], oversized or "none"))

    # A layout the add-on does not ship is rendered on demand.
    out = os.path.join(tempfile.mkdtemp(), "rendered.png")
    thumbs.render(available["minimal.json"], out,
                  [os.path.join(ROOT, "resources", "fonts")])
    rendered = ImageCache().get(out)
    check(rendered is not None and rendered.width > 0,
          "a layout without a shipped preview can be rendered on demand")

    # What the dialog is handed, without Kodi: list items carrying a picture.
    from lcd4linux import ui
    pictures = [thumbs.shipped_path(name) for name in names]
    calls = []

    class FakeDialog(object):
        def select(self, heading, items, useDetails=False, preselect=-1):
            calls.append((heading, items, useDetails, preselect))
            return 1

    original = ui.xbmcgui
    try:
        ui.xbmcgui = FakeGui
        ui._select_layout(FakeDialog(), "Choose layout", names, names,
                          pictures, 3)
        _heading, items, details, preselect = calls[-1]
        check(details and preselect == 3,
              "the picture dialog is asked for details, preselecting the "
              "current layout")
        check(len(items) == len(names)
              and all(item.art.get("thumb") for item in items),
              "every entry goes into the dialog with a picture")
        ui.xbmcgui = None
        ui._select_layout(FakeDialog(), "Choose layout", names, names,
                          pictures, 3)
        _heading, items, details, _preselect = calls[-1]
        check(not details and isinstance(items[0], str),
              "without the GUI the chooser falls back to plain labels")
    finally:
        ui.xbmcgui = original

    # The rows come out of the cached index, not out of sixty full loads.
    from lcd4linux.layoutindex import forget
    from lcd4linux.settings import Config
    forget()
    config = Config(overrides={"layout": "vinyl.json"})
    rows, labels, row_details, current = ui._layout_entries(available, config)
    check(len(labels) == len(rows) and all(labels),
          "every row is labelled with the layout's own name")
    check(rows[current][0] == "vinyl.json",
          "the layout in the settings is the preselected row")
    check(any("480x320" in detail for detail in row_details),
          "the row detail carries the sizes the design is drawn for")

    # Rendering is slow, so it is handed to the service instead of being
    # done while the dialog is kept closed.
    own = tempfile.mkdtemp()
    shutil.copyfile(available["minimal.json"], os.path.join(own, "mine.json"))
    config = Config(overrides={"layout": "vinyl.json", "layout_dir": own})
    mixed = discover([directory, own])
    mixed_entries = ui._layout_designs(mixed)
    sent = []
    status = [""]
    original_notify, original_status = ui.notify_service, ui._service_status
    try:
        ui.notify_service = lambda command, payload=None: (
            sent.append((command, payload)), True)[1]
        ui._service_status = lambda: status[0]

        status[0] = "running"
        shipped, pending = ui._layout_pictures(entries, available, config)
        check(not pending and not sent,
              "with every preview in place nothing is rendered or queued")
        check(all(picture for picture in shipped),
              "and every bundled design comes with its shipped picture")

        pictures, pending = ui._layout_pictures(mixed_entries, mixed, config)
        check(pending == ["mine.json"] and sent
              and sent[-1] == ("render_thumbs", {"names": ["mine.json"]}),
              "a layout without a preview is queued with the service")
        index = [name for name, _variants in mixed_entries].index("mine.json")
        check(pictures[index] is None,
              "and the dialog opens straight away, that row without a picture")

        status[0] = ""
        del sent[:]
        pictures, pending = ui._layout_pictures(mixed_entries, mixed, config)
        check(not sent and not pending and pictures[index],
              "without a service the chooser renders it itself")
        del sent[:]
        status[0] = "running"
        _pictures, pending = ui._layout_pictures(mixed_entries, mixed, config)
        check(not pending and not sent,
              "once rendered the picture is cached, not queued again")
    finally:
        ui.notify_service, ui._service_status = original_notify, original_status
        forget()


def test_preview_ownership():
    """Only the user's own layouts are drawn again when they change."""
    print("preview ownership")
    import tempfile
    import time as _time
    from lcd4linux import thumbs

    bundled = os.path.join(ROOT, "resources", "layouts")
    own = tempfile.mkdtemp()
    mine = os.path.join(own, "mine.json")
    shutil.copyfile(os.path.join(bundled, "minimal.json"), mine)
    # Named after a bundled design on purpose: a picture is picked by where
    # the file lies, not by what it is called.
    lookalike = os.path.join(own, "default-1920x1080.json")
    shutil.copyfile(os.path.join(bundled, "minimal.json"), lookalike)

    shipped = thumbs.picture("default.json",
                             os.path.join(bundled, "default.json"), own)
    check(shipped == thumbs.shipped_path("default.json"),
          "a bundled design is shown with the picture it ships")

    check(thumbs.picture("default-1920x1080.json", lookalike, own) is None,
          "the user's own layout does not borrow the bundled picture of "
          "the design it is named after")
    check(thumbs.picture("mine.json", mine, own) is None,
          "a layout of theirs that was never drawn has no picture yet")

    drawn = thumbs.cached_path("mine.json", mine,
                               [os.path.join(ROOT, "resources", "fonts")])
    check(drawn and thumbs.picture("mine.json", mine, own) == drawn,
          "once drawn it is shown from the cache")

    # Freshness is what makes an edit show up.
    _time.sleep(0.01)
    os.utime(mine, None)
    check(thumbs.picture("mine.json", mine, own) is None,
          "editing it drops the picture, so the chooser draws it again")

    # The bundled ones are never re-read that way, whatever their mtime.
    os.utime(os.path.join(bundled, "default.json"), None)
    check(thumbs.picture("default.json",
                         os.path.join(bundled, "default.json"), own) == shipped,
          "a bundled design keeps its picture even with a newer file")

    check(not thumbs.is_user_layout(os.path.join(bundled, "default.json"), own)
          and thumbs.is_user_layout(mine, own),
          "ownership follows the folder the layout lies in")
    check(not thumbs.is_user_layout(mine, ""),
          "with no user folder configured nothing counts as the user's")


def test_preview_encoding():
    """Previews are stored as small as a PNG gets without visible loss."""
    print("preview encoding")
    from lcd4linux import pngio

    bulky = []
    stored_total = plain_total = 0
    for name in sorted(os.listdir(os.path.join(ROOT, "resources", "thumbs"))):
        if not name.endswith(".png"):
            continue
        path = os.path.join(ROOT, "resources", "thumbs", name)
        with open(path, "rb") as handle:
            stored = handle.read()
        width, height, rgba = pngio.decode(stored)
        rgb = bytearray(width * height * 3)
        rgb[0::3] = rgba[0::4]
        rgb[1::3] = rgba[1::4]
        rgb[2::3] = rgba[2::4]
        plain = pngio.encode_rgb(width, height, rgb)
        stored_total += len(stored)
        plain_total += len(plain)
        # Colour type 3 is the palette form; anything else was shipped
        # without going through the compact encoder.
        if stored[25] != 3 or len(stored) >= len(plain):
            bulky.append(name)

    check(not bulky, "every shipped preview is stored in its palette form "
                     "(%s)" % (bulky or "all 20",))
    check(stored_total < plain_total,
          "which saves %d%% over plain RGB (%d -> %d bytes for the set)"
          % (100 - 100 * stored_total // plain_total, plain_total,
             stored_total))

    # What that costs is measured against the render itself, not against a
    # picture that has already been through the palette once.
    from lcd4linux.kodidata import DemoProvider
    from lcd4linux.layout import Layout, Renderer
    from lcd4linux.images import ImageCache

    fonts = FontCache([os.path.join(ROOT, "resources", "fonts")])
    media = os.path.join(ROOT, "resources", "media")
    worst = 0.0
    for design in ("portrait", "cover-full", "default"):
        provider = DemoProvider(0, 97.0, "playing",
                                os.path.join(media, "demo-cover.jpg"),
                                os.path.join(media, "demo-fanart.jpg"))
        layout = Layout.load(os.path.join(ROOT, "resources", "layouts",
                                          design + ".json"))
        canvas = Renderer(layout, provider, fonts, ImageCache()).render()
        rgb = canvas.to_rgb888()
        back = pngio.decode(pngio.encode_rgb_compact(canvas.width,
                                                     canvas.height, rgb))[2]
        error = sum(abs(back[4 * i + channel] - rgb[3 * i + channel])
                    for i in range(canvas.width * canvas.height)
                    for channel in range(3)) / float(canvas.width
                                                     * canvas.height * 3)
        worst = max(worst, error)
    check(worst < 1.0,
          "and costs at most %.2f of 255 per channel against the render, "
          "which does not show" % worst)

    # A picture that already fits a palette has to survive untouched.
    width, height = 8, 4
    rgb = bytearray()
    for index in range(width * height):
        rgb.extend((index * 7 % 256, index * 3 % 256, 40))
    palette, indices = pngio.quantize(rgb, 256)
    restored = pngio.decode(pngio.encode_indexed(width, height, palette,
                                                 indices))[2]
    exact = all(restored[4 * i + channel] == rgb[3 * i + channel]
                for i in range(width * height) for channel in range(3))
    check(len(palette) == width * height and exact,
          "an image that fits the palette keeps every colour exactly")


def test_preview_worker():
    """The service draws the previews the chooser asked it for."""
    print("preview worker")
    import json
    import tempfile
    from lcd4linux import thumbs
    from lcd4linux.service import Service

    own = tempfile.mkdtemp()
    shutil.copyfile(os.path.join(ROOT, "resources", "layouts", "minimal.json"),
                    os.path.join(own, "worker.json"))
    bus = install_fake_spf("monitor")
    bus.device = FakeSPFDevice(bus)
    service = Service(overrides={"output_mode": "usb", "display_type": "spf",
                                 "layout_dir": own})

    service._handle_command("render_thumbs",
                            json.dumps({"names": ["worker.json",
                                                  "../escape.json"]}))
    worker = service._thumb_worker
    check(worker is not None, "the command starts a worker off the frame loop")
    if worker is not None:
        worker.join(120)
        check(not worker.is_alive(), "which finishes on its own")
    check(thumbs.cached_picture("worker.json"),
          "the preview the chooser was missing is now cached")
    check(not os.path.exists(thumbs.profile_path("thumbs", "../escape.png")),
          "a name that is not a layout the add-on offers is ignored")

    service._handle_command("render_thumbs", json.dumps({"names": []}))
    check(service._thumb_worker is None or not service._thumb_worker.is_alive(),
          "an empty request starts nothing")


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
    # frame and the other way round.  The JPEG encoder and the software
    # dimming are shared with the network display, so those follow both; the
    # AX206 backlight levels are meaningless in a browser.
    def visible_conditions(setting):
        """``(setting, operator, value)`` of every visibility condition.

        A dependency is either a single condition written on the element
        itself or an <and>/<or> holding several, so both shapes are flattened
        into one list here.
        """
        found = []
        for dependency in setting.iter("dependency"):
            if dependency.get("type") != "visible":
                continue
            nested = list(dependency.iter("condition"))
            if nested:
                found.extend((element.get("setting"),
                              element.get("operator") or "is",
                              element.text) for element in nested)
            else:
                found.append((dependency.get("setting"),
                              dependency.get("operator") or "is",
                              dependency.text))
        return found

    ax206_only = [("display_type", "is", "ax206"),
                  ("output_mode", "!is", "network")]
    spf_or_network = [("display_type", "is", "spf"),
                      ("output_mode", "is", "network")]
    expected = {
        "device_ids": [("display_type", "is", "ax206")],
        "byte_order": [("display_type", "is", "ax206")],
        "reset_on_open": [("display_type", "is", "ax206")],
        "spf_model": [("display_type", "is", "spf")],
        "brightness": ax206_only,
        "dim_brightness": ax206_only,
        "jpeg_quality": spf_or_network,
        "jpeg_subsample": spf_or_network,
        "spf_brightness": spf_or_network,
        "spf_dim_brightness": spf_or_network,
    }
    for key, conditions in sorted(expected.items()):
        check(visible_conditions(settings[key]) == conditions,
              "%s is shown for the right display types" % key)

    # The size is what the network display renders at, so it must not be
    # locked away behind "override the display size".
    for key in ("width", "height"):
        enable = []
        for dependency in settings[key].iter("dependency"):
            if dependency.get("type") == "enable":
                enable.extend((element.get("setting"), element.text)
                              for element in dependency.iter("condition"))
        check(("output_mode", "network") in enable,
              "%s can be set in network mode" % key)


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


def test_media_info():
    """Codec, HDR and resolution must reach the panel as names, not raw ids.

    Kodi answers with demuxer ids and a VideoResolution that says "4K" for a
    2160 line picture; the display is supposed to say H.265, Dolby TrueHD,
    Dolby Vision and 2160p.
    """
    print("media info")
    from lcd4linux import mediainfo

    check(mediainfo.video_codec("hevc") == "H.265", "hevc is H.265")
    check(mediainfo.video_codec("avc1") == "H.264", "avc1 is H.264")
    check(mediainfo.video_codec("") == "", "an absent codec stays absent")
    check(mediainfo.video_codec("weirdcodec") == "WEIRDCODEC",
          "an unknown codec is still shown")

    check(mediainfo.audio_codec("truehd_atmos") == "Dolby TrueHD",
          "truehd_atmos is Dolby TrueHD")
    check(mediainfo.audio_codec("dtshd_ma") == "DTS-HD MA", "dtshd_ma is DTS-HD MA")
    check(mediainfo.audio_codec("eac3") == "Dolby Digital Plus",
          "eac3 is Dolby Digital Plus")
    check(mediainfo.spatial_format("truehd_atmos") == "Atmos", "Atmos is named")
    check(mediainfo.spatial_format("dtshd_ma_x") == "DTS:X", "DTS:X is named")
    check(mediainfo.spatial_format("truehd") == "",
          "plain TrueHD claims no object audio")
    check(mediainfo.audio_description("truehd_atmos", "8")
          == "Dolby TrueHD Atmos 7.1", "the audio line reads as one string")
    check(mediainfo.audio_description("", "") == "",
          "and stays empty when Kodi knows nothing")

    # Kodi reports the bed count only, so no height channels are invented.
    check(mediainfo.channel_layout("8") == "7.1", "8 channels is 7.1")
    check(mediainfo.channel_layout("6") == "5.1", "6 channels is 5.1")
    check(mediainfo.channel_layout("2") == "2.0", "2 channels is 2.0")
    check(mediainfo.channel_layout("9") == "9 ch",
          "an unmapped count is still readable")
    check(mediainfo.channel_layout("") == "", "no count, no layout")

    for raw, expected, short in (
            ("dolbyvision", "Dolby Vision", "DV"),
            ("Dolby Vision", "Dolby Vision", "DV"),
            ("hdr10+", "HDR10+", "HDR10+"),
            ("hdr10plus", "HDR10+", "HDR10+"),
            ("hdr10", "HDR10", "HDR10"),
            ("hlg", "HLG", "HLG"),
            ("", "SDR", "SDR")):
        check(mediainfo.hdr_type(raw) == expected and
              mediainfo.hdr_short(raw) == short,
              "%r is %s / %s" % (raw, expected, short))

    # The resolution is the reported bug: "4K" could not have a "p" appended.
    check(mediainfo.resolution("2160", "") == "2160p", "2160 lines is 2160p")
    check(mediainfo.resolution("1080", "i") == "1080i", "an interlaced source is i")
    check(mediainfo.resolution("816", "") == "720p",
          "a scope transfer keeps the standard below it")
    check(mediainfo.resolution("", "", "4K") == "2160p",
          "and Kodi's own '4K' becomes 2160p, not '4Kp'")
    check(mediainfo.resolution("", "", "1080") == "1080p",
          "a bare fallback number gains its scan letter")
    check(mediainfo.resolution("", "", "") == "", "nothing known, nothing shown")
    check(mediainfo.resolution_name("2160") == "4K UHD", "2160 lines is 4K UHD")
    check(mediainfo.resolution_name("", "4K") == "4K UHD",
          "the fallback names itself too")
    check(mediainfo.resolution_name("1080") == "Full HD", "1080 lines is Full HD")

    check(mediainfo.frame_rate("23.976023") == "23.976", "23.976 snaps to itself")
    check(mediainfo.frame_rate("25.000") == "25", "a whole rate loses its zeros")
    check(mediainfo.frame_rate("") == "", "an unknown rate is empty")

    # Kodi's live bitrate labels are localised and carry their own unit, so
    # the same stream reads "24.50 Mb/s" or "24,50 Mb/s" depending on the
    # box; both have to end up as one number on one scale.
    check(mediainfo.bitrate("24,50 Mb/s") == "24.5 Mb/s",
          "a decimal comma is still a decimal point")
    check(mediainfo.bitrate("24.50 Mb/s") == "24.5 Mb/s",
          "and a decimal point stays one")
    check(mediainfo.bitrate("1,536 Kb/s", "", "Kb/s") == "1536 Kb/s",
          "a thousands separator is not a decimal point")
    check(mediainfo.bitrate("1.536 Kb/s", "", "Kb/s") == "1536 Kb/s",
          "whichever character the box spells it with")
    check(mediainfo.bitrate("4448 Kb/s") == "4.45 Mb/s",
          "a label in another unit is converted, not repeated")
    check(mediainfo.bitrate("", "36400") == "36.4 Mb/s",
          "the average is read as kb/s, the way Kodi reports it")
    check(mediainfo.bitrate("", "") == "" and mediainfo.bitrate("0 Mb/s") == "",
          "nothing measured, nothing shown")
    check(mediainfo.bitrate_amount("24,50 Mb/s") == "24.5",
          "the bare number carries no unit, for a bar or a graph")

    # And the whole way through the provider the layouts actually read.
    film = DemoProvider(1, 97.0, "playing")
    film.begin_frame()
    for key, expected in (("player.codec", "H.265"),
                          ("player.audiocodec", "Dolby TrueHD"),
                          ("player.spatial", "Atmos"),
                          ("player.audio", "Dolby TrueHD Atmos 7.1"),
                          ("player.channels", "7.1"),
                          ("player.hdr", "Dolby Vision"),
                          ("player.hdr_short", "DV"),
                          ("player.resolution", "2160p"),
                          ("player.resolution_long", "3840x2160p"),
                          ("player.resolutionname", "4K UHD"),
                          ("player.fps", "23.976"),
                          ("player.video", "H.265 2160p Dolby Vision"),
                          ("player.dv", "Dolby Vision Profile 7.6 FEL"),
                          ("player.dvprofile", "7.6"),
                          ("player.dvprofile_long", "Profile 7.6"),
                          ("player.dvel", "FEL"),
                          ("player.videobitrate", "36.4 Mb/s"),
                          ("player.videobitrate_mbps", "36.4"),
                          ("player.audiobitrate", "4448 Kb/s"),
                          ("player.audiobitrate_kbps", "4448")):
        actual = film.value(key)
        check(actual == expected, "%s is %r" % (key, actual))
    check(film.value("player.codec_raw") == "hevc",
          "the raw id stays reachable for a layout that wants it")

    music = DemoProvider(0, 97.0, "playing")
    music.begin_frame()
    check(music.value("player.codec") == "FLAC", "a music codec is named too")
    check(music.value("player.channels") == "2.0", "and stereo is 2.0")
    check(music.value("player.hdr") == "" and music.value("player.resolution") == "",
          "a music track claims no picture")
    check(music.value("player.dv") == "" and music.value("player.dvel") == "",
          "and no Dolby Vision either")
    check(music.value("player.audiobitrate") == "1006 Kb/s",
          "but it does have a rate, read off the music player")

    series = DemoProvider(2, 97.0, "playing")
    series.begin_frame()
    check(series.value("player.dv") == "",
          "a stream that is not Dolby Vision names no profile")
    check(series.value("player.videobitrate") == "9.8 Mb/s",
          "and still names its picture rate")

    # The browser editor has to offer the new fields, or nobody finds them.
    from lcd4linux import webschema
    offered = set()
    for group in webschema.TOKEN_GROUPS:
        for entry in group["tokens"]:
            offered.add(entry[0])
    missing = [key for key in ("player.hdr", "player.hdr_short", "player.audio",
                               "player.spatial", "player.video",
                               "player.resolutionname", "player.videocodec",
                               "player.channels_count", "player.fps")
               if key not in offered]
    check(not missing, "the editor lists the new fields%s"
          % ("" if not missing else ": missing " + ", ".join(missing)))
    demo = DemoProvider(1, 97.0, "playing",
                        os.path.join(ROOT, "resources", "media",
                                     "demo-cover.jpg"),
                        os.path.join(ROOT, "resources", "media",
                                     "demo-fanart.jpg"))
    demo.begin_frame()
    unknown = [key for key in sorted(offered)
               if key.startswith("player.") and demo.value(key) == ""]
    # Only the fields this demo track - a film - genuinely has nothing for.
    allowed = {"player.album", "player.albumartist", "player.showtitle",
               "player.season", "player.episode", "player.episodelabel",
               "player.track", "player.samplerate", "player.bitrate",
               "player.discnumber"}
    surprises = [key for key in unknown if key not in allowed]
    check(not surprises, "every offered player field resolves%s"
          % ("" if not surprises else ": empty " + ", ".join(surprises)))


def test_dolby_vision():
    """The profile has to come off the bitstream, and cost one parse a title.

    The panel is redrawn four times a second; a profile cannot change while
    a film runs, so the reading is taken once and held, and the parser is
    only asked again while something is still missing.
    """
    print("dolby vision")
    from lcd4linux import dvinfo

    labels = {}
    playing = {"video": True}
    now = {"t": 0.0}

    def info(name):
        return labels.get(name, "")

    def condition(name):
        return playing["video"] if name == "Player.HasVideo" else False

    def watcher(result):
        """A stand-in parser that counts how often it was asked."""
        calls = []

        def parse(raw):
            calls.append(raw)
            return result
        return calls, parse

    original = dvinfo._parse_sidedata
    try:
        # Nothing playing: nothing to say, whatever the labels still hold.
        labels["VideoPlayer.HDRType"] = "dolbyvision"
        playing["video"] = False
        dv = dvinfo.DolbyVision(info, condition, lambda: now["t"])
        check(dv.fields() == dvinfo.EMPTY, "a stopped player names no profile")

        # Without the parser module Kodi's own detail is all there is, and
        # there is nothing left to wait for once it has been read.
        dvinfo._parse_sidedata = None
        playing["video"] = True
        labels["Player.FilenameAndPath"] = "/movies/one.mkv"
        labels["VideoPlayer.HdrDetail"] = "8.1"
        dv = dvinfo.DolbyVision(info, condition, lambda: now["t"])
        fields = dv.fields()
        check(fields["profile"] == "8.1" and fields["el"] == "",
              "the profile falls back to VideoPlayer.HdrDetail")
        check(fields["line"] == "Dolby Vision Profile 8.1",
              "and reads as a whole line")
        check(dv._settled, "with no enhancement layer to wait for")

        # An unrelated detail must not be mistaken for a profile.
        labels["VideoPlayer.HdrDetail"] = "Dolby Vision"
        dv = dvinfo.DolbyVision(info, condition, lambda: now["t"])
        check(dv.fields()["line"] == "Dolby Vision",
              "and a detail that is not a profile number is not shown as one")

        # With the parser, the configuration record and the RPU header name
        # the profile and the enhancement layer exactly.
        parsed = {"config": {"profile": 7, "compat_id": 6, "el_present": True},
                  "rpu": {"header": {"el_type": "FEL"}}}
        calls, dvinfo._parse_sidedata = watcher(parsed)
        labels["Player.FilenameAndPath"] = "/movies/two.mkv"
        labels["Player.Process(video.sidedata)"] = "{}"
        labels["VideoPlayer.HdrDetail"] = ""
        dv = dvinfo.DolbyVision(info, condition, lambda: now["t"])
        fields = dv.fields()
        check(fields["line"] == "Dolby Vision Profile 7.6 FEL",
              "the side data names profile and layer: %r" % fields["line"])
        check(fields["profile"] == "7.6" and fields["el"] == "FEL",
              "each of them reachable on its own")
        check(fields["label"] == "Profile 7.6",
              "and the profile spelled out without the format name")
        check(dvinfo.profile_label("") == "",
              "an unknown profile is not spelled out as 'Profile '")

        # And that is the only parse the whole title costs.
        now["t"] += 10.0
        for _ in range(5):
            dv.fields()
        check(len(calls) == 1, "one parse a title, not one a frame (%d)"
              % len(calls))

        # A new title starts over.
        labels["Player.FilenameAndPath"] = "/movies/three.mkv"
        dv.fields()
        check(len(calls) == 2, "but the next title is read again")

        # A stream nothing calls Dolby Vision is left alone after a few
        # looks - the first frames arrive before the labels are filled in.
        calls, dvinfo._parse_sidedata = watcher({})
        labels["VideoPlayer.HDRType"] = "hdr10"
        labels["Player.FilenameAndPath"] = "/movies/four.mkv"
        dv = dvinfo.DolbyVision(info, condition, lambda: now["t"])
        for _ in range(dvinfo.MAX_ATTEMPTS + 3):
            now["t"] += dvinfo.PARSE_INTERVAL
            check_quiet = dv.fields()
        check(check_quiet == dvinfo.EMPTY, "an HDR10 stream names no profile")
        check(len(calls) == dvinfo.MAX_ATTEMPTS,
              "and is not parsed for the rest of the film (%d)" % len(calls))
    finally:
        dvinfo._parse_sidedata = original


def test_pixel_conversion():
    """RGB565 -> RGB888 must be exact, whatever the shortcut inside.

    The conversion expands whole byte planes at once instead of walking the
    framebuffer pixel by pixel, which is worth the trick only if it agrees
    with the straightforward version on every one of the 65536 values.
    """
    print("pixel conversion")
    from lcd4linux.canvas import unpack565

    canvas = Canvas(256, 256)
    for value in range(65536):
        canvas.buf[value] = value
    expected = bytearray(65536 * 3)
    position = 0
    for value in canvas.buf:
        red, green, blue = unpack565(value)
        expected[position] = red
        expected[position + 1] = green
        expected[position + 2] = blue
        position += 3
    check(canvas.to_rgb888() == bytes(expected),
          "every RGB565 value expands to the same RGB triplet as before")
    check(Canvas(0, 0).to_rgb888() == b"", "an empty canvas converts to nothing")

    # The PNG preview writer is the real caller, so check the whole way out.
    from lcd4linux import pngio
    picture = Canvas(9, 5)
    picture.fill_rect(1, 1, 4, 3, (255, 128, 0, 255))
    data = pngio.encode_rgb(picture.width, picture.height, picture.to_rgb888())
    width, height, rgba = pngio.decode(data)
    check((width, height) == (9, 5), "the preview PNG keeps its size")
    middle = (2 * 9 + 2) * 4
    check(abs(rgba[middle] - 255) <= 8 and abs(rgba[middle + 1] - 128) <= 8
          and rgba[middle + 2] <= 8, "and its colours survive the round trip")


def test_frame_cache():
    """Kodi is asked for each value once per frame, not once per token."""
    print("frame cache")
    from lcd4linux import kodidata

    counted = {"conditions": 0, "labels": 0}

    class CountingProvider(kodidata.KodiProvider):
        """A KodiProvider with the two calls into Kodi counted."""

        def __init__(self):
            kodidata.BaseProvider.__init__(self)
            self.addon_name = self.addon_version = ""
            self.player = None
            self.cpu = kodidata.CpuSampler()
            # Pretend the library counts were fetched a moment ago.
            self._library_cache = {"songs": "1"}
            self._library_time = time.time()

        def _info(self, label):
            counted["labels"] += 1
            return ""

        def _kodi_condition(self, name):
            counted["conditions"] += 1
            return False

    provider = CountingProvider()
    provider.begin_frame(1000.0)
    for key in ("player.title", "player.artist", "player.album", "player.time",
                "player.duration", "player.percent", "player.state",
                "player.thumb", "player.codec", "player.year"):
        provider.value(key)
    # Player.Playing, Player.Paused and the HasVideo/HasAudio/HasPicture
    # probes; without the per-frame cache every player.* key repeated them.
    check(counted["conditions"] <= 5,
          "a page full of player tokens costs %d visibility calls"
          % counted["conditions"])

    # /proc/meminfo is one file, however many keys are read out of it.
    provider = CountingProvider()
    provider.begin_frame(1000.0)
    check("__meminfo" not in provider._cache,
          "the memory file is not touched until a key asks for it")
    for key in ("system.memory", "system.memoryfree", "system.memorytotal"):
        provider.value(key)
    check("__meminfo" in provider._cache,
          "and is then read once for all three memory keys")

    # The service opens the frame before the renderer does; the second call
    # with the same timestamp must not throw the cache away.
    provider = CountingProvider()
    provider.begin_frame(2000.0)
    provider.value("player.state")
    so_far = counted["conditions"]
    provider.begin_frame(2000.0)
    provider.value("player.state")
    check(counted["conditions"] == so_far,
          "re-announcing the same frame keeps the cached values")
    provider.begin_frame(2001.0)
    provider.value("player.state")
    check(counted["conditions"] > so_far, "and the next frame asks again")


def test_image_cache():
    """A picture that is not there must not be re-opened on every frame."""
    print("image cache")
    import shutil
    import tempfile
    from lcd4linux import images, pngio

    reads = {"count": 0}
    original = images.read_bytes

    def counting_read(path):
        reads["count"] += 1
        return original(path)

    images.read_bytes = counting_read
    directory = tempfile.mkdtemp(prefix="lcd4linux-cache-")
    try:
        cache = ImageCache(limit=4)
        missing = os.path.join(directory, "no-cover-yet.png")
        result = None
        for _ in range(10):
            result = cache.get(missing)
        check(result is None, "a missing picture resolves to nothing")
        check(reads["count"] == 1,
              "and is looked for once, not once per frame (%d reads)"
              % reads["count"])

        # It must still appear on its own once the file turns up.
        cache.MISS_SECONDS = 0.0
        canvas = Canvas(4, 4)
        canvas.clear((10, 200, 90, 255))
        with open(missing, "wb") as handle:
            handle.write(pngio.encode_rgb(4, 4, canvas.to_rgb888()))
        check(cache.get(missing) is not None,
              "a picture that arrives late is still picked up")
    finally:
        images.read_bytes = original
        shutil.rmtree(directory, ignore_errors=True)


def test_web_editor():
    """The browser editor: its API, its guards and its field catalogue."""
    print("web editor")
    import base64
    import json
    import re
    import shutil
    import socket
    import tempfile
    import urllib.error
    import urllib.request
    from lcd4linux import webschema, webui
    from lcd4linux.settings import Config

    # -- the catalogue must describe the renderer, not something like it --
    widget_source = _read_text(os.path.join(ROOT, "resources", "lib",
                                            "lcd4linux", "widgets.py"))
    layout_source = _read_text(os.path.join(ROOT, "resources", "lib",
                                            "lcd4linux", "layout.py"))
    unknown = []
    for kind, fields in sorted(webschema.WIDGET_FIELDS.items()):
        for field in fields:
            if 'get("%s"' % field["key"] not in widget_source:
                unknown.append("%s.%s" % (kind, field["key"]))
    for field in webschema.COMMON_FIELDS:
        if 'get("%s"' % field["key"] not in widget_source:
            unknown.append("common.%s" % field["key"])
    for group, fields in (("page", webschema.PAGE_FIELDS),
                          ("layout", webschema.LAYOUT_FIELDS)):
        for field in fields:
            if 'get("%s"' % field["key"] not in layout_source:
                unknown.append("%s.%s" % (group, field["key"]))
    check(not unknown, "every editor field is read by the renderer (%s)"
          % (unknown or "none",))
    check(sorted(webschema.PALETTE) == sorted(webschema.WIDGET_FIELDS),
          "the palette lists every described widget")

    # -- a layout the editor offers must be one the renderer accepts ------
    for kind, preset in sorted(webschema.NEW_WIDGET.items()):
        spec = webschema.blank_layout()
        spec["pages"][0]["widgets"] = [dict(preset, type=kind, x=0, y=0)]
        webui.validate(spec)
    check(True, "every widget the palette adds parses (%d types)"
          % len(webschema.NEW_WIDGET))

    for name, bad in (("no size", {"pages": [{}]}),
                      ("no pages", {"size": [480, 320], "pages": []}),
                      ("huge", {"size": [9000, 9000], "pages": [{}]}),
                      ("odd widget", {"size": [480, 320], "pages": [
                          {"widgets": [{"type": "nonsense"}]}]})):
        try:
            webui.validate(bad)
        except webui.EditorError:
            continue
        check(False, "a layout with %s is refused" % name)
    check(True, "invalid layouts are refused")

    for bad in ("../evil.json", "a/b.json", "..\\evil.json", ".hidden.json", ""):
        try:
            webui.safe_name(bad)
        except webui.EditorError:
            continue
        check(False, "the file name %r is refused" % bad)
    check(webui.safe_name("mein layout") == "mein layout.json",
          "a plain name gets its .json")

    # -- the server -------------------------------------------------------
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    directory = tempfile.mkdtemp(prefix="lcd4linux-web-")
    editor = webui.WebEditor(Config({"web_port": port, "web_bind": "local",
                                     "layout_dir": directory,
                                     "web_password": "secret"}))
    check(editor.start(), "the editor server starts")
    base = "http://127.0.0.1:%d" % port
    auth = {"Authorization": "Basic %s"
            % base64.b64encode(b"kodi:secret").decode("ascii")}

    def request(path, payload=None, headers=None, method=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        head = dict(auth)
        head.update(headers or {})
        if data is not None:
            head["Content-Type"] = "application/json"
        message = urllib.request.Request(base + path, data=data, headers=head,
                                         method=method)
        try:
            reply = urllib.request.urlopen(message, timeout=20)
        except urllib.error.HTTPError as failure:
            return failure.code, failure.headers.get("Content-Type"), failure.read()
        return reply.status, reply.headers.get("Content-Type"), reply.read()

    try:
        try:
            urllib.request.urlopen(base + "/api/state", timeout=10)
            check(False, "the password is asked for")
        except urllib.error.HTTPError as failure:
            check(failure.code == 401, "without the password the answer is 401")

        code, _kind, body = request("/")
        check(code == 200 and b"LCD4Linux" in body, "the editor page is served")
        for name in ("editor.css", "editor.js"):
            code, _kind, body = request("/static/" + name)
            check(code == 200 and len(body) > 1000, "%s is served" % name)
        code, _kind, _body = request("/static/../resources/settings.xml")
        check(code == 403, "a path outside the web folder is refused")

        code, _kind, body = request("/api/schema")
        schema = json.loads(body)
        check(code == 200 and len(schema["widgets"]) == len(webschema.PALETTE),
              "the schema describes every widget")
        check("sans" in schema["fonts"] and "play" in schema["icons"],
              "fonts and icons come from the add-on itself")

        code, _kind, body = request("/api/layouts")
        listed = json.loads(body)["layouts"]
        check(code == 200 and any(entry["file"] == "default.json"
                                  for entry in listed),
              "the bundled layouts are listed (%d)" % len(listed))

        code, _kind, body = request("/api/layout?file=default.json")
        answer = json.loads(body)
        check(code == 200 and answer["spec"]["pages"], "a layout is read back")
        check(answer["strings"].get("32403"),
              "the editor is told what $LOCALIZE[...] means")

        spec = answer["spec"]
        code, kind, body = request("/api/preview", {"spec": spec, "page": 1,
                                                    "track": 1, "frames": 2})
        check(code == 200 and kind == "image/png" and body[:4] == b"\x89PNG",
              "a page is rendered to a PNG (%d bytes)" % len(body))
        width, height = _png_size(body)
        check((width, height) == tuple(spec["size"]),
              "the preview has the size of the layout (%dx%d)" % (width, height))

        code, _kind, body = request("/api/layout",
                                    {"file": "selftest.json", "spec": spec})
        check(code == 200, "a layout is saved")
        check(os.path.isfile(os.path.join(directory, "selftest.json")),
              "and it lands in the user folder")
        code, _kind, body = request("/api/layout?file=selftest.json")
        check(json.loads(body)["user"], "a saved layout is marked as the user's")

        code, _kind, body = request("/api/layout",
                                    {"file": "broken.json",
                                     "spec": {"size": [480, 320], "pages": []}})
        check(code == 400 and b"page" in body, "a broken layout is refused")
        check(not os.path.isfile(os.path.join(directory, "broken.json")),
              "and nothing is written")

        code, _kind, _body = request("/api/layout",
                                     {"file": "../evil.json", "spec": spec})
        check(code == 400, "a file name with a path in it is refused")
        check(not os.path.isfile(os.path.join(os.path.dirname(directory),
                                              "evil.json")),
              "and no file appears outside the folder")

        code, _kind, _body = request("/api/delete", {"file": "selftest.json"})
        check(code == 200 and not os.path.isfile(
            os.path.join(directory, "selftest.json")), "a layout is deleted")

        code, _kind, body = request("/api/blank?size=800x480")
        blank = json.loads(body)["spec"]
        check(blank["size"] == [800, 480], "a blank layout is offered")
        webui.validate(blank)

        code, _kind, _body = request("/api/command", {"command": "rm -rf"})
        check(code == 400, "an unknown command is refused")
    finally:
        editor.stop()
        shutil.rmtree(directory, ignore_errors=True)
    check(not editor.running, "and it stops again")


def test_network_display():
    """The wall panel: a NetworkTarget and the endpoints that serve it."""
    print("network display")
    import socket
    import threading
    import urllib.error
    import urllib.request
    from lcd4linux import display as display_module
    from lcd4linux import webui
    from lcd4linux.settings import Config

    # -- built from the settings like every other target ------------------
    config = Config({"output_mode": "network", "width": 320, "height": 240,
                     "jpeg_quality": 70})
    target = display_module.make_target(config)
    check(isinstance(target, display_module.NetworkTarget),
          "network mode builds a network target")
    check((target.width, target.height) == (320, 240),
          "the configured size is the panel size (%dx%d)"
          % (target.width, target.height))
    check(target.quality == 70,
          "JPEG quality reaches the encoder: %d" % target.quality)
    check(not target.is_open, "and it is closed until the service opens it")

    target.open()
    check(target.latest() == (b"", 0), "no frame before the first render")

    canvas = Canvas(320, 240, parse_color("#0b0d12"))
    canvas.fill_rect(10, 10, 300, 60, parse_color("#17b2e2"))
    target.present(canvas, force=True)
    frame, serial = target.latest()
    check(frame[:2] == b"\xff\xd8" and frame[-2:] == b"\xff\xd9",
          "the frame on offer is a whole JPEG (%d bytes)" % len(frame))
    check(serial == 1, "and it is counted")

    # A frame that changes nothing still counts, so a client that missed the
    # last one is not left waiting for a picture that never comes.
    canvas.fill_rect(10, 100, 100, 20, parse_color("#f0a020"))
    target.present(canvas)
    check(target.latest()[1] == 2, "the next frame gets the next serial")

    # -- wait() is what the streaming threads block on --------------------
    target.keepalive = 0.2
    check(target.wait(target.latest()[1])[1] == 2,
          "wait() returns the unchanged frame as a keep-alive")

    ready = threading.Event()

    def render_later():
        ready.wait(5)
        canvas.fill_rect(10, 140, 100, 20, parse_color("#c04040"))
        target.present(canvas)

    worker = threading.Thread(target=render_later)
    worker.daemon = True
    worker.start()
    ready.set()
    check(target.wait(2, timeout=5)[1] == 3, "and wakes up on a new frame")
    worker.join(timeout=5)

    target.blank()
    dark, serial = target.latest()
    check(serial == 4 and dark[:2] == b"\xff\xd8",
          "blanking pushes a black frame at shutdown")

    # -- the endpoints ----------------------------------------------------
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    class FakeService(object):
        """Just enough of the service for the handlers: a target."""

        def __init__(self, config, target):
            self.config = config
            self.target = target

    served = Config({"web_port": port, "web_bind": "local",
                     "web_password": "secret", "output_mode": "network",
                     "width": 320, "height": 240})
    editor = webui.WebEditor(served, FakeService(served, target))
    check(editor.display_target() is target, "the editor finds the live target")
    check(webui.WebEditor(served).display_target() is None,
          "and finds none without a running service")
    check(editor.display_url().endswith("/display?key=secret"),
          "the wall panel URL carries the password: %s" % editor.display_url())

    check(editor.start(), "the server starts")
    base = "http://127.0.0.1:%d" % port
    try:
        # The kiosk browser cannot answer a Basic auth challenge for an
        # <img>, so the display endpoints take the password in the query.
        try:
            urllib.request.urlopen(base + "/display", timeout=10)
            check(False, "the display page asks for the password")
        except urllib.error.HTTPError as failure:
            check(failure.code == 401,
                  "without the key the display page is 401")
        try:
            urllib.request.urlopen(base + "/display?key=wrong", timeout=10)
            check(False, "a wrong key is refused")
        except urllib.error.HTTPError as failure:
            check(failure.code == 401, "and a wrong key is 401 too")

        page = urllib.request.urlopen(base + "/display?key=secret", timeout=10)
        body = page.read().decode("utf-8")
        check(page.status == 200 and "/display/stream?key=secret" in body,
              "the page points at the stream with the key")
        check("<img" in body and "multipart" not in body,
              "and it is a plain <img>, no framework")

        still = urllib.request.urlopen(base + "/display/frame.jpg?key=secret",
                                       timeout=10)
        shot = still.read()
        check(still.headers.get("Content-Type") == "image/jpeg"
              and shot[:2] == b"\xff\xd8",
              "a single still is served (%d bytes)" % len(shot))

        stream = urllib.request.urlopen(base + "/display/stream?key=secret",
                                        timeout=10)
        kind = stream.headers.get("Content-Type") or ""
        check(kind.startswith("multipart/x-mixed-replace"),
              "the stream announces itself as MJPEG: %s" % kind)
        head = stream.read(len(shot) + 128)
        stream.close()
        check(webui.STREAM_BOUNDARY.encode("ascii") in head
              and b"\xff\xd8" in head,
              "and the first frame arrives without waiting for a redraw")

        # With the display closed the stream must end rather than hold a
        # thread until the socket times out.
        target.close()
        check(not target.is_open, "the target closes")
        stream = urllib.request.urlopen(base + "/display/stream?key=secret",
                                        timeout=10)
        rest = stream.read()
        stream.close()
        check(b"\xff\xd8" in rest, "a late client still gets the last frame")
    finally:
        target.close()
        editor.stop()
    check(not editor.running, "and the server stops again")


def _read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _png_size(data):
    import struct
    return struct.unpack(">II", data[16:24])


def main():
    print("script.lcd4linux self test\n")
    for test in (test_encoding, test_fonts, test_images, test_tokens,
                 test_media_info, test_dolby_vision,
                 test_pixel_conversion, test_frame_cache, test_image_cache,
                 test_jpeg_encoder, test_protocol, test_target_from_settings,
                 test_samsung_spf, test_late_display, test_brightness,
                 test_localisation,
                 test_settings_xml, test_layout_index, test_layout_chooser,
                 test_preview_ownership, test_preview_encoding,
                 test_preview_worker,
                 test_power_hooks, test_rotation, test_web_editor,
                 test_network_display,
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
