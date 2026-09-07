"""Presentation targets.

A target takes a finished :class:`~.canvas.Canvas` and puts it somewhere:
on the AX206 panel over USB, or into a PNG file when the user only wants to
preview a layout.  The AX206 target keeps a copy of the last frame so that
only the changed region has to travel over the bus, which is what keeps the
refresh rate usable on a 480x320 panel.
"""

import os
from array import array

from . import ax206
from . import pngio
from . import spf
from .errors import DisplayError
from .jpegenc import JpegEncoder
from .canvas import Canvas
from .logger import error, log

#: Rectangles smaller than this fraction of the screen are sent as partial
#: updates; anything larger is cheaper to push in one go.
FULL_FRAME_THRESHOLD = 0.55


def _first_difference(left, right, low, high):
    """Index of the first differing element in ``[low, high)``."""
    while high - low > 8:
        middle = (low + high) // 2
        if left[low:middle] == right[low:middle]:
            low = middle
        else:
            high = middle
    for index in range(low, high):
        if left[index] != right[index]:
            return index
    return high


def _last_difference(left, right, low, high):
    """Index after the last differing element in ``[low, high)``."""
    while high - low > 8:
        middle = (low + high) // 2
        if left[middle:high] == right[middle:high]:
            high = middle
        else:
            low = middle
    for index in range(high - 1, low - 1, -1):
        if left[index] != right[index]:
            return index + 1
    return low


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

    def set_brightness(self, level):
        pass

    @property
    def logical_size(self):
        """Canvas size, i.e. the physical size with rotation applied."""
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height


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

    def present(self, canvas, force=False):
        frame = canvas.rotated(self.rotation) if self.rotation else canvas
        directory = os.path.dirname(self.path)
        if directory and not os.path.isdir(directory):
            try:
                os.makedirs(directory)
            except OSError:
                pass
        data = pngio.encode_rgb(frame.width, frame.height, frame.to_rgb888())
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, self.path)
        self.frames += 1
        return True


class AX206Target(Target):
    """The real panel."""

    def __init__(self, device_ids=ax206.KNOWN_DEVICES, index=0, serial=None,
                 rotation=0, mirror=False, byte_order="big", timeout=3000,
                 reset_on_open=False, size_override=None):
        self.device = ax206.AX206(device_ids, index, serial, timeout)
        self.rotation = int(rotation) % 360
        self.mirror = bool(mirror)
        self.byte_order = byte_order
        self.reset_on_open = reset_on_open
        self.size_override = size_override
        self.width = 0
        self.height = 0
        self._previous = None
        self._failures = 0

    # -- lifecycle --------------------------------------------------------
    def open(self):
        self.device.open(reset=self.reset_on_open)
        self.width = self.device.width
        self.height = self.device.height
        if self.size_override:
            override_w, override_h = self.size_override
            if override_w and override_h and (override_w, override_h) != (self.width, self.height):
                log("overriding reported size %dx%d with %dx%d"
                    % (self.width, self.height, override_w, override_h))
                self.width, self.height = override_w, override_h
                self.device.width, self.device.height = override_w, override_h
        self._previous = None
        return True

    def close(self):
        self.device.close()
        self._previous = None

    @property
    def is_open(self):
        return self.device.is_open

    def set_brightness(self, level):
        try:
            self.device.set_brightness(level)
        except Exception as err:
            error("cannot set brightness: %s" % err)

    def describe(self):
        info = self.device.info
        return str(info) if info else "AX206"

    # -- output -----------------------------------------------------------
    def present(self, canvas, force=False):
        """Push ``canvas`` to the panel, sending only what changed."""
        frame = canvas
        if self.mirror:
            frame = _mirror(frame)
        if self.rotation:
            frame = frame.rotated(self.rotation)
        if frame.width != self.width or frame.height != self.height:
            raise DisplayError(
                "frame is %dx%d but the panel is %dx%d"
                % (frame.width, frame.height, self.width, self.height))

        rect = None
        if force or self._previous is None:
            rect = (0, 0, self.width, self.height)
        else:
            rect = self._dirty_rect(frame.buf)
            if rect is None:
                return True
            area = (rect[2] - rect[0]) * (rect[3] - rect[1])
            if area > self.width * self.height * FULL_FRAME_THRESHOLD:
                rect = (0, 0, self.width, self.height)

        payload = self._extract(frame.buf, rect)
        try:
            self.device.blit(rect[0], rect[1], rect[2], rect[3], payload)
        except Exception:
            self._failures += 1
            self._previous = None
            raise
        self._failures = 0
        self._previous = array("H", frame.buf)
        return True

    def _dirty_rect(self, buf):
        previous = self._previous
        width = self.width
        first_row = None
        last_row = None
        for row in range(self.height):
            start = row * width
            end = start + width
            if buf[start:end] != previous[start:end]:
                if first_row is None:
                    first_row = row
                last_row = row
        if first_row is None:
            return None
        left = width
        right = 0
        for row in range(first_row, last_row + 1):
            start = row * width
            end = start + width
            if buf[start:end] == previous[start:end]:
                continue
            row_left = _first_difference(buf, previous, start, end) - start
            row_right = _last_difference(buf, previous, start, end) - start
            if row_left < left:
                left = row_left
            if row_right > right:
                right = row_right
        return (left, first_row, right, last_row + 1)

    def _extract(self, buf, rect):
        left, top, right, bottom = rect
        width = self.width
        span = right - left
        if span == width:
            chunk = array("H", buf[top * width:bottom * width])
        else:
            chunk = array("H")
            for row in range(top, bottom):
                start = row * width + left
                chunk.extend(buf[start:start + span])
        if self.byte_order == "big":
            # The AX206 expects the high byte of each RGB565 pixel first.
            chunk.byteswap()
        return chunk.tobytes()


class SPFTarget(Target):
    """A Samsung SPF photo frame in mini monitor mode.

    The frame only takes whole JPEG images, so there is no partial update
    here; :class:`~.jpegenc.JpegEncoder` keeps the cost down instead by
    re-encoding only the MCU rows that changed.
    """

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
        return True

    def close(self):
        self.device.close()
        self.encoder = None

    @property
    def is_open(self):
        return self.device.is_open

    def describe(self):
        info = self.device.info
        return "%s %s" % (self.device.name, info) if info else "Samsung SPF"

    def set_brightness(self, level):
        # No backlight control in this protocol; a level of 0 blanks the
        # picture instead so "off when idle" still does something useful.
        return

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
        jpeg = self.encoder.encode(frame.buf, force=force)
        self.last_frame_bytes = len(jpeg)
        self.device.send_image(jpeg)
        return True

    def blank(self):
        """Show a black picture; the closest thing to switching off."""
        if self.encoder is None:
            return
        dark = Canvas(self.width, self.height, (0, 0, 0, 255))
        jpeg = self.encoder.encode(dark.buf)
        self.device.send_image(jpeg)


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
        target = PreviewTarget(config.preview_path, config.width,
                               config.height, config.rotation)
        log("preview mode: frames are written to %s" % config.preview_path)
        return target
    if config.output_mode == "none":
        return NullTarget(config.width, config.height, config.rotation)
    override = None
    if config.force_size:
        override = (config.width, config.height)
    if config.display_type == "spf":
        return SPFTarget(index=config.device_index,
                         serial=config.device_serial,
                         rotation=config.rotation,
                         mirror=config.mirror,
                         timeout=config.usb_timeout,
                         model=config.spf_model,
                         quality=config.jpeg_quality,
                         subsample=config.jpeg_subsample,
                         size_override=override)
    return AX206Target(device_ids=config.device_ids_parsed,
                       index=config.device_index,
                       serial=config.device_serial,
                       rotation=config.rotation,
                       mirror=config.mirror,
                       byte_order=config.byte_order,
                       timeout=config.usb_timeout,
                       reset_on_open=config.reset_on_open,
                       size_override=override)
