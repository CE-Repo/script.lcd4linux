"""AX206 USB LCD driver.

The AX206 is the controller inside the cheap "digital photo frame" panels
that are also sold as AIDA64 / SmartDisplay USB screens (the 3.5" 480x320
model among them).  It speaks USB mass storage Bulk-Only-Transport and
carries the display commands as a vendor specific 16 byte SCSI CDB starting
with ``0xcd``.

The command encoding, endpoint numbers and the RGB565 byte order below
follow the ``dpf-ax`` project and the AX206 driver of lcd4linux
(``drv_dpf.c``), which is where this add-on takes its name from.
"""

import struct
import threading
import time

from . import usbdev
from .logger import debug, error, log
from .usbdev import USBError

#: Vendor/product IDs of the known AX206 panels ("hacked" DPF firmware).
KNOWN_DEVICES = ((0x1908, 0x0102),)

ENDPOINT_OUT = 0x01
ENDPOINT_IN = 0x81

USBCMD_SETPROPERTY = 0x01
USBCMD_BLIT = 0x12

PROPERTY_BRIGHTNESS = 0x01

CBW_SIGNATURE = b"USBC"
CSW_SIGNATURE = b"USBS"
CBW_TAG = 0xEFBEADDE

DIR_IN = 0
DIR_OUT = 1

MAX_BRIGHTNESS = 7


class DisplayError(Exception):
    pass


def parse_id_list(text, default=KNOWN_DEVICES):
    """Parse ``"1908:0102, 1908:3318"`` into ``((vid, pid), ...)``."""
    if not text:
        return tuple(default)
    result = []
    for item in str(text).replace(";", ",").split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        vid, _, pid = item.partition(":")
        try:
            result.append((int(vid, 16), int(pid, 16)))
        except ValueError:
            continue
    return tuple(result) if result else tuple(default)


class AX206(object):
    """One connected AX206 panel."""

    def __init__(self, device_ids=KNOWN_DEVICES, index=0, serial=None,
                 timeout=3000):
        self.device_ids = tuple(device_ids)
        self.index = int(index)
        self.serial = serial or None
        self.timeout = int(timeout)
        self.width = 0
        self.height = 0
        self.info = None
        self._context = None
        self._device = None
        self._ep_in = ENDPOINT_IN
        self._ep_out = ENDPOINT_OUT
        self._lock = threading.RLock()
        self._brightness = None

    # -- discovery --------------------------------------------------------
    @classmethod
    def enumerate(cls, device_ids=KNOWN_DEVICES):
        """Return :class:`~.usbdev.DeviceInfo` objects for attached panels."""
        context = usbdev.Context()
        devices = None
        result = []
        try:
            devices, _count, found = context.find(device_ids)
            for device, info in found:
                try:
                    handle = usbdev.open_device(context, device, info)
                    handle.close()
                except USBError as err:
                    debug("cannot query %s: %s" % (info, err))
                result.append(info)
        finally:
            if devices is not None:
                context.release_list(devices)
            context.close()
        return result

    # -- lifecycle --------------------------------------------------------
    def open(self, reset=False):
        """Open the panel and read its native resolution."""
        with self._lock:
            if self._device is not None:
                return
            context = usbdev.Context()
            devices = None
            try:
                devices, _count, found = context.find(self.device_ids)
                if not found:
                    raise DisplayError(
                        "no AX206 display found (looked for %s)"
                        % ", ".join("%04x:%04x" % ids for ids in self.device_ids))
                chosen = None
                if self.serial:
                    for device, info in found:
                        handle = usbdev.open_device(context, device, info)
                        if info.serial == self.serial:
                            chosen = (device, info, handle)
                            break
                        handle.close()
                    if chosen is None:
                        raise DisplayError("no AX206 display with serial %s"
                                           % self.serial)
                else:
                    if self.index >= len(found):
                        raise DisplayError("AX206 display #%d not present, %d found"
                                           % (self.index, len(found)))
                    device, info = found[self.index]
                    chosen = (device, info, usbdev.open_device(context, device, info))
                _device, info, handle = chosen
                self.info = info
                self._device = handle
                if reset:
                    handle.reset()
                    time.sleep(0.2)
                handle.claim()
                ep_in, ep_out = handle.bulk_endpoints()
                self._ep_in = ep_in or ENDPOINT_IN
                self._ep_out = ep_out or ENDPOINT_OUT
                debug("using endpoints in=0x%02x out=0x%02x"
                      % (self._ep_in, self._ep_out))
                self._read_dimensions()
                log("AX206 opened: %s, %dx%d" % (info, self.width, self.height))
            except Exception:
                if self._device is not None:
                    try:
                        self._device.close()
                    except Exception:
                        pass
                    self._device = None
                context.close()
                raise
            finally:
                if devices is not None:
                    context.release_list(devices)
            self._context = context

    def close(self):
        with self._lock:
            if self._device is not None:
                try:
                    self._device.close()
                except Exception as err:
                    debug("error closing device: %s" % err)
                self._device = None
            if self._context is not None:
                try:
                    self._context.close()
                except Exception:
                    pass
                self._context = None

    @property
    def is_open(self):
        return self._device is not None

    # -- protocol ---------------------------------------------------------
    def _wrap_scsi(self, command, direction, data=None, read_length=0):
        """Send one command block wrapper and run its data phase."""
        if self._device is None:
            raise DisplayError("display is not open")
        block_length = read_length if direction == DIR_IN else (len(data) if data else 0)
        cbw = bytearray(31)
        cbw[0:4] = CBW_SIGNATURE
        struct.pack_into("<I", cbw, 4, CBW_TAG)
        struct.pack_into("<I", cbw, 8, block_length)
        # The reference driver leaves bmCBWFlags at 0 for both directions;
        # the AX206 firmware takes the direction from the vendor command.
        cbw[12] = 0x00
        cbw[13] = 0x00                      # LUN
        cbw[14] = len(command)
        cbw[15:15 + len(command)] = command

        device = self._device
        device.write(self._ep_out, bytes(cbw), self.timeout)

        payload = None
        if direction == DIR_OUT:
            if data:
                device.write(self._ep_out, data, max(self.timeout, 3000))
        elif read_length:
            payload = device.read(self._ep_in, read_length, max(self.timeout, 4000))
            if len(payload) != read_length:
                raise DisplayError("short read: got %d of %d bytes"
                                   % (len(payload), read_length))

        status = None
        for attempt in range(3):
            try:
                status = device.read(self._ep_in, 13, max(self.timeout, 5000))
                break
            except USBError as err:
                debug("CSW read attempt %d failed: %s" % (attempt + 1, err))
                time.sleep(0.05)
        if status is None or len(status) != 13:
            raise DisplayError("no command status wrapper received")
        if status[0:4] != CSW_SIGNATURE:
            raise DisplayError("invalid command status wrapper")
        if status[12] != 0:
            raise DisplayError("display rejected command (status %d)" % status[12])
        return payload

    @staticmethod
    def _command(*values):
        command = bytearray(16)
        command[0] = 0xCD
        for offset, value in values:
            command[offset] = value & 0xFF
        return command

    def _read_dimensions(self):
        command = self._command((5, 2))     # "get LCD parameters"
        payload = self._wrap_scsi(command, DIR_IN, read_length=5)
        width, height = struct.unpack_from("<HH", payload, 0)
        if not (0 < width <= 4096 and 0 < height <= 4096):
            raise DisplayError("implausible display size reported: %dx%d"
                               % (width, height))
        self.width = width
        self.height = height

    # -- public operations ------------------------------------------------
    def set_brightness(self, level):
        """Backlight level, 0 (off) to 7 (brightest)."""
        level = max(0, min(MAX_BRIGHTNESS, int(level)))
        with self._lock:
            command = self._command((5, 6), (6, USBCMD_SETPROPERTY),
                                    (7, PROPERTY_BRIGHTNESS), (8, 0),
                                    (9, level), (10, level >> 8))
            self._wrap_scsi(command, DIR_OUT)
            self._brightness = level

    @property
    def brightness(self):
        return self._brightness

    def blit(self, x0, y0, x1, y1, data):
        """Send RGB565 pixels for the half-open rectangle ``x0,y0 - x1,y1``."""
        x0 = max(0, int(x0))
        y0 = max(0, int(y0))
        x1 = min(self.width or int(x1), int(x1))
        y1 = min(self.height or int(y1), int(y1))
        if x1 <= x0 or y1 <= y0:
            return
        expected = (x1 - x0) * (y1 - y0) * 2
        if len(data) != expected:
            raise DisplayError("blit payload is %d bytes, expected %d"
                               % (len(data), expected))
        with self._lock:
            command = self._command(
                (5, 6), (6, USBCMD_BLIT),
                (7, x0), (8, x0 >> 8),
                (9, y0), (10, y0 >> 8),
                (11, x1 - 1), (12, (x1 - 1) >> 8),
                (13, y1 - 1), (14, (y1 - 1) >> 8),
                (15, 0))
            self._wrap_scsi(command, DIR_OUT, data)

    def clear(self, color=0x0000, byte_order="big"):
        """Fill the whole panel with one RGB565 colour."""
        if not self.width or not self.height:
            return
        pixel = struct.pack(">H" if byte_order == "big" else "<H", color)
        row = pixel * self.width
        self.blit(0, 0, self.width, self.height, row * self.height)

    def recover(self):
        """Try to bring the link back after an error."""
        with self._lock:
            if self._device is None:
                return False
            try:
                self._device.clear_halt(self._ep_in)
                self._device.clear_halt(self._ep_out)
                return True
            except USBError as err:
                error("USB recovery failed: %s" % err)
                return False
