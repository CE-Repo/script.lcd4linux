"""Presentation targets.

A target takes a finished :class:`~.canvas.Canvas` and puts it somewhere: on
a Samsung frame as JPEG, over the network to a browser, or into a PNG file
when the user only wants to preview a layout.
"""

import os
import threading
import time

from . import pngio
from . import spf
from .errors import DisplayError
from .jpegenc import JpegEncoder
from .canvas import Canvas
from .logger import log


class Target(object):
    """Common interface of all presentation targets."""

    width = 0
    height = 0
    rotation = 0

    def open(self):
        return True

    def close(self):
        pass

    def present(self, canvas, force=False):
        raise NotImplementedError

    def set_brightness(self, percent):
        """Apply a brightness, 0 (black) to 100 (untouched).

        No display this add-on drives has a backlight it can be told about,
        so every target darkens the picture itself; ``True`` when it was
        accepted.
        """
        return True

    @property
    def logical_size(self):
        """Canvas size, i.e. the physical size with rotation applied."""
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height


def _gain_table(percent):
    """256 entry byte table that scales an 8 bit channel to ``percent``."""
    percent = max(0, min(100, int(percent)))
    return bytes(bytearray((value * percent) // 100 for value in range(256)))


class NullTarget(Target):
    """Renders nowhere; used when the display is disabled."""

    def __init__(self, width=480, height=320, rotation=0):
        self.width = width
        self.height = height
        self.rotation = rotation

    def present(self, canvas, force=False):
        return True


class PreviewTarget(Target):
    """Writes every frame to a PNG file instead of a panel."""

    def __init__(self, path, width=480, height=320, rotation=0):
        self.path = path
        self.width = width
        self.height = height
        self.rotation = rotation
        self.frames = 0
        self.brightness = 100
        self._gain = None

    def set_brightness(self, percent):
        """Dim the preview the way the real display would be dimmed."""
        percent = max(0, min(100, int(percent)))
        self.brightness = percent
        self._gain = None if percent >= 100 else _gain_table(percent)
        return True

    def present(self, canvas, force=False):
        frame = canvas.rotated(self.rotation) if self.rotation else canvas
        directory = os.path.dirname(self.path)
        if directory and not os.path.isdir(directory):
            try:
                os.makedirs(directory)
            except OSError:
                pass
        pixels = frame.to_rgb888()
        if self._gain is not None:
            pixels = pixels.translate(self._gain)
        data = pngio.encode_rgb(frame.width, frame.height, pixels)
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, self.path)
        self.frames += 1
        return True


class SPFTarget(Target):
    """A Samsung SPF photo frame in mini monitor mode.

    The frame only takes whole JPEG images, so there is no partial update
    here; :class:`~.jpegenc.JpegEncoder` keeps the cost down instead by
    re-encoding only the MCU rows that changed.
    """

    #: An unchanged picture is sent again after this long, which is enough
    #: to keep the frame in monitor mode.  Sending it on every tick bought
    #: nothing but a busier frame: its decoder is slow, and the more
    #: pictures are queued behind it the likelier a transfer runs into the
    #: USB timeout.
    resend_seconds = 2.0

    def __init__(self, index=0, serial=None, rotation=0, mirror=False,
                 timeout=5000, model=None, quality=85, subsample=True,
                 size_override=None):
        self.device = spf.SamsungSPF(index, serial, timeout, model=model)
        self.rotation = int(rotation) % 360
        self.mirror = bool(mirror)
        self.quality = int(quality)
        self.subsample = bool(subsample)
        self.size_override = size_override
        self.width = 0
        self.height = 0
        self.encoder = None
        self.last_frame_bytes = 0
        self.brightness = 100
        self._redraw = False
        self._last_jpeg = None
        self._last_sent = 0.0

    def open(self):
        self.device.open()
        self.width = self.device.width
        self.height = self.device.height
        if self.size_override:
            override_w, override_h = self.size_override
            if override_w and override_h:
                log("overriding frame size %dx%d with %dx%d"
                    % (self.width, self.height, override_w, override_h))
                self.width, self.height = override_w, override_h
        self.encoder = JpegEncoder(self.width, self.height, self.quality,
                                   self.subsample)
        self.encoder.set_gain(self.brightness)
        self._redraw = True
        self._last_jpeg = None
        return True

    def close(self):
        self.device.close()
        self.encoder = None
        self._last_jpeg = None

    @property
    def is_open(self):
        return self.device.is_open

    def describe(self):
        info = self.device.info
        return "%s %s" % (self.device.name, info) if info else "Samsung SPF"

    def set_brightness(self, percent):
        """Dim in software, 0 (black) to 100 (untouched).

        The mini monitor protocol has no backlight command at all, so the
        only way to darken a Samsung frame is to send a darker picture.  The
        scaling happens inside the encoder's colour table, which costs
        nothing per frame; only the next frame has to be re-encoded in full
        because the cached rows still carry the old brightness.
        """
        percent = max(0, min(100, int(percent)))
        if percent == self.brightness and self.encoder is not None:
            return True
        self.brightness = percent
        if self.encoder is not None and self.encoder.set_gain(percent):
            self._redraw = True
        return True

    def present(self, canvas, force=False):
        frame = canvas
        if self.mirror:
            frame = _mirror(frame)
        if self.rotation:
            frame = frame.rotated(self.rotation)
        if frame.width != self.width or frame.height != self.height:
            raise DisplayError(
                "frame is %dx%d but the display is %dx%d"
                % (frame.width, frame.height, self.width, self.height))
        jpeg = self.encoder.encode(frame.buf, force=force or self._redraw)
        self._redraw = False
        self.last_frame_bytes = len(jpeg)
        now = time.time()
        if (not force and jpeg == self._last_jpeg
                and 0 <= now - self._last_sent < self.resend_seconds):
            return True
        self._send(jpeg, now)
        return True

    def _send(self, jpeg, now=None):
        # Forget the last picture first: if the transfer fails, the frame
        # is reset and must get the next one whatever it shows.
        self._last_jpeg = None
        self.device.send_image(jpeg)
        self._last_jpeg = jpeg
        self._last_sent = time.time() if now is None else now

    def blank(self):
        """Show a black picture; the closest thing to switching off."""
        if self.encoder is None:
            return
        dark = Canvas(self.width, self.height, (0, 0, 0, 255))
        jpeg = self.encoder.encode(dark.buf)
        self._send(jpeg)
        self._redraw = True


class NetworkTarget(Target):
    """Serves the frames over HTTP instead of pushing them down a USB bus.

    A browser opens ``/display`` on the add-on's own web server and gets an
    MJPEG stream - typically an old tablet on the wall running a kiosk app.
    A ``multipart/x-mixed-replace`` stream inside a plain ``<img>`` needs no
    JavaScript at all, which is what makes this work on the ancient WebKit
    of an Android 4.x tablet.

    Whole JPEG frames go out on the wire, but
    :class:`~.jpegenc.JpegEncoder` re-encodes only the MCU rows that changed,
    so a ticking clock costs a fraction of a full frame.

    The service thread writes frames and the server threads read them, so
    everything shared goes through :attr:`_condition`.
    """

    #: Re-send the current frame after this long without a new one.  It
    #: keeps NAT table entries and idle proxies from dropping the stream,
    #: and lets a client that connected mid-frame see a picture at all.
    keepalive = 10.0

    def __init__(self, width=800, height=480, rotation=0, mirror=False,
                 quality=85, subsample=True):
        self.width = int(width)
        self.height = int(height)
        self.rotation = int(rotation) % 360
        self.mirror = bool(mirror)
        self.quality = int(quality)
        self.subsample = bool(subsample)
        self.brightness = 100
        self.frames = 0
        self.last_frame_bytes = 0
        self.encoder = None
        self._redraw = False
        self._frame = b""
        self._condition = threading.Condition()

    def open(self):
        self.encoder = JpegEncoder(self.width, self.height, self.quality,
                                   self.subsample)
        self.encoder.set_gain(self.brightness)
        self._redraw = True
        return True

    def close(self):
        # Wake every streaming client so its thread notices the frames have
        # stopped instead of sitting in wait() until the socket times out.
        with self._condition:
            self.encoder = None
            self._condition.notify_all()

    @property
    def is_open(self):
        return self.encoder is not None

    def describe(self):
        return "network display"

    def set_brightness(self, percent):
        """Dim in software, 0 (black) to 100 (untouched).

        Same trick as the Samsung frame: the scaling lives in the encoder's
        colour table, so it costs nothing per frame.  Only the next frame
        has to be re-encoded in full because the cached rows still carry the
        old brightness.
        """
        percent = max(0, min(100, int(percent)))
        if percent == self.brightness and self.encoder is not None:
            return True
        self.brightness = percent
        if self.encoder is not None and self.encoder.set_gain(percent):
            self._redraw = True
        return True

    def present(self, canvas, force=False):
        if self.encoder is None:
            return False
        frame = canvas
        if self.mirror:
            frame = _mirror(frame)
        if self.rotation:
            frame = frame.rotated(self.rotation)
        if frame.width != self.width or frame.height != self.height:
            raise DisplayError(
                "frame is %dx%d but the display is %dx%d"
                % (frame.width, frame.height, self.width, self.height))
        jpeg = self.encoder.encode(frame.buf, force=force or self._redraw)
        self._redraw = False
        self.last_frame_bytes = len(jpeg)
        self._publish(jpeg)
        return True

    def blank(self):
        """Push a black picture, so a browser that stays open goes dark."""
        if self.encoder is None:
            return
        dark = Canvas(self.width, self.height, (0, 0, 0, 255))
        self._publish(self.encoder.encode(dark.buf, force=True))
        self._redraw = True

    # -- what the web server reads ----------------------------------------
    def _publish(self, jpeg):
        with self._condition:
            self._frame = jpeg
            self.frames += 1
            self._condition.notify_all()

    def latest(self):
        """``(jpeg, serial)`` of the frame on screen right now."""
        with self._condition:
            return self._frame, self.frames

    def wait(self, seen, timeout=None):
        """Block until a frame newer than ``seen`` exists.

        Returns ``(jpeg, serial)`` either way: on timeout the caller gets
        the unchanged frame back and re-sends it as a keep-alive.
        """
        if timeout is None:
            timeout = self.keepalive
        with self._condition:
            if self.frames == seen:
                self._condition.wait(timeout)
            return self._frame, self.frames


def _mirror(canvas):
    """Flip a canvas horizontally."""
    out = Canvas(canvas.width, canvas.height)
    width = canvas.width
    for row in range(canvas.height):
        start = row * width
        line = canvas.buf[start:start + width]
        line.reverse()
        out.buf[start:start + width] = line
    return out


def make_target(config):
    """Build the target described by a :class:`~.settings.Config`."""
    if config.output_mode == "preview":
        log("preview mode: frames are written to %s" % config.preview_path)
        return PreviewTarget(config.preview_path, config.width,
                             config.height, config.rotation)
    if config.output_mode == "none":
        return NullTarget(config.width, config.height, config.rotation)
    if config.output_mode == "network":
        # No panel reports a size here, so the configured one is the truth.
        log("network mode: frames are served at /display, %dx%d"
            % (config.width, config.height))
        return NetworkTarget(width=config.width,
                             height=config.height,
                             rotation=config.rotation,
                             mirror=config.mirror,
                             quality=config.jpeg_quality,
                             subsample=config.jpeg_subsample)
    override = None
    if config.force_size:
        override = (config.width, config.height)
    return SPFTarget(index=config.device_index,
                     serial=config.device_serial,
                     rotation=config.rotation,
                     mirror=config.mirror,
                     timeout=config.usb_timeout,
                     model=config.spf_model,
                     quality=config.jpeg_quality,
                     subsample=config.jpeg_subsample,
                     size_override=override)
