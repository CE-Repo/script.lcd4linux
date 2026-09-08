"""Samsung SPF photo frame driver ("mini monitor" mode).

These frames enumerate as a USB mass storage device and have to be switched
into monitor mode with a vendor specific descriptor request.  Once switched,
they accept complete JPEG images only - there is no way to update part of
the screen, which is why :mod:`.jpegenc` goes to some length to make a full
frame cheap.

Wire format of one frame::

    a5 5a 18 04 | length (u32 LE) | 48 00 00 00 | JPEG | ff 00 | zero padding

where ``length`` counts header, image and trailer, and the whole block is
padded to a multiple of 64 KiB before it is written to bulk endpoint 2.

The command encoding follows the SamsungSPF driver of lcd4linux, which in
turn goes back to Andre Puschmann's playusb and Grace Woo's picframe work.
"""

import struct
import threading
import time

from . import usbdev
from .errors import DisplayError
from .logger import debug, log
from .usbdev import USBError

VENDOR_SAMSUNG = 0x04E8

#: ``name, storage mode product id, monitor mode product id, width, height``
MODELS = (
    ("SPF-72H", 0x200A, 0x200B, 800, 480),
    ("SPF-75H", 0x200E, 0x200F, 800, 480),
    ("SPF-76H", 0x200E, 0x200F, 800, 480),
    ("SPF-83H", 0x200C, 0x200D, 800, 600),
    ("SPF-83M", 0x2005, 0x2006, 800, 600),
    ("SPF-85H", 0x2012, 0x2013, 800, 600),
    ("SPF-85P", 0x2016, 0x2017, 800, 600),
    ("SPF-86H", 0x2012, 0x2013, 800, 600),
    ("SPF-86P", 0x2016, 0x2017, 800, 600),
    ("SPF-87H", 0x2025, 0x2026, 800, 480),
    ("SPF-87H-v2", 0x2033, 0x2034, 800, 480),
    ("SPF-105P", 0x201C, 0x201B, 1024, 600),
    ("SPF-107H", 0x2027, 0x2028, 1024, 600),
    ("SPF-107H-v2", 0x2035, 0x2036, 1024, 600),
    ("SPF-700T", 0x204F, 0x2050, 800, 600),
    ("SPF-800P", 0x2037, 0x2038, 800, 480),
    ("SPF-1000P", 0x2039, 0x2040, 1024, 600),
)

#: Model setting value that means "whichever frame is on the bus".
MODEL_AUTO = "auto"

FRAME_HEADER = b"\xa5\x5a\x18\x04"
FRAME_MARKER = b"\x48\x00\x00\x00"
FRAME_TRAILER = b"\xff\x00"
PAD_SIZE = 0x10000
ENDPOINT_OUT = 0x02

#: Vendor request that keeps the SPF-87H and friends in monitor mode.
KEEPALIVE_REQUEST_TYPE = 0xC0
KEEPALIVE_REQUEST = 0x01

#: The descriptor request that flips a frame out of mass storage mode.
SWITCH_REQUEST_TYPE = 0x80
SWITCH_REQUEST = 0x06
SWITCH_VALUE = 0x00FE
SWITCH_INDEX = 0x00FE
SWITCH_LENGTH = 0xFE


def storage_ids():
    return tuple((VENDOR_SAMSUNG, model[1]) for model in MODELS)


def monitor_ids():
    return tuple((VENDOR_SAMSUNG, model[2]) for model in MODELS)


def model_for(product_id):
    """``(name, width, height)`` for a monitor mode product id."""
    for name, _storage, monitor, width, height in MODELS:
        if monitor == product_id:
            return name, width, height
    return None


def model_by_name(name):
    """The :data:`MODELS` entry for a model name, ``None`` for automatic."""
    name = (name or "").strip().lower()
    if name in ("", MODEL_AUTO):
        return None
    for entry in MODELS:
        if entry[0].lower() == name:
            return entry
    return None


class SamsungSPF(object):
    """One connected Samsung photo frame in monitor mode."""

    def __init__(self, index=0, serial=None, timeout=5000, switch_wait=8.0,
                 model=None):
        self.index = int(index)
        self.serial = serial or None
        self.timeout = int(timeout)
        self.switch_wait = float(switch_wait)
        wanted = (model or "").strip()
        entry = model_by_name(wanted)
        if entry is None and wanted and wanted.lower() != MODEL_AUTO:
            log("unknown Samsung model %s, using whichever frame is found"
                % wanted)
        self.model = entry[0] if entry else None
        self.name = ""
        self.width = 0
        self.height = 0
        self.info = None
        self._context = None
        self._device = None
        self._ep_out = ENDPOINT_OUT
        self._lock = threading.RLock()

    # -- discovery --------------------------------------------------------
    @classmethod
    def enumerate(cls):
        """Frames on the bus, in either mode.

        Returns ``[(DeviceInfo, mode, model name)]`` with ``mode`` being
        ``"storage"`` or ``"monitor"``.
        """
        context = usbdev.Context()
        devices = None
        found = []
        try:
            devices, _count, matches = context.find(storage_ids() + monitor_ids())
            for _device, info in matches:
                for name, storage, monitor, _w, _h in MODELS:
                    if info.product == monitor:
                        found.append((info, "monitor", name))
                        break
                    if info.product == storage:
                        found.append((info, "storage", name))
                        break
        finally:
            if devices is not None:
                context.release_list(devices)
            context.close()
        return found

    # -- mode switching ---------------------------------------------------
    def _switch_to_monitor(self, context):
        """Ask every frame still in storage mode to become a monitor."""
        devices = None
        switched = 0
        try:
            devices, _count, matches = context.find(storage_ids())
            for device, info in matches:
                try:
                    handle = usbdev.open_device(context, device, info)
                except USBError as error:
                    log("cannot open %s for mode switch: %s" % (info, error))
                    continue
                try:
                    log("switching %s into monitor mode" % info)
                    try:
                        handle.control_read(SWITCH_REQUEST_TYPE, SWITCH_REQUEST,
                                            SWITCH_VALUE, SWITCH_INDEX,
                                            SWITCH_LENGTH, 1000)
                    except USBError as error:
                        # The frame usually drops off the bus mid-request,
                        # which surfaces as an I/O error and is expected.
                        debug("mode switch request returned %s" % error)
                    switched += 1
                finally:
                    handle.close()
        finally:
            if devices is not None:
                context.release_list(devices)
        return switched

    # -- lifecycle --------------------------------------------------------
    def open(self):
        with self._lock:
            if self._device is not None:
                return
            context = usbdev.Context()
            try:
                if not self._find_monitor(context):
                    if not self._switch_to_monitor(context):
                        raise DisplayError(
                            "no Samsung photo frame found (looked for %d known models)"
                            % len(MODELS))
                    # The frame re-enumerates with a new product id.
                    deadline = time.time() + self.switch_wait
                    while time.time() < deadline:
                        time.sleep(0.5)
                        if self._find_monitor(context):
                            break
                    else:
                        raise DisplayError(
                            "the frame did not come back in monitor mode within %.0f s"
                            % self.switch_wait)
                log("Samsung %s opened: %s, %dx%d"
                    % (self.name, self.info, self.width, self.height))
            except Exception:
                if self._device is not None:
                    try:
                        self._device.close()
                    except Exception:
                        pass
                    self._device = None
                context.close()
                raise
            self._context = context

    def _find_monitor(self, context):
        """Open the frame if one is already in monitor mode."""
        devices = None
        try:
            devices, _count, matches = context.find(monitor_ids())
            if not matches:
                return False
            chosen = None
            for device, info in matches:
                if self.serial:
                    handle = usbdev.open_device(context, device, info)
                    if info.serial == self.serial:
                        chosen = (info, handle)
                        break
                    handle.close()
                    continue
                if self.model:
                    entry = model_by_name(self.model)
                    if entry and info.product != entry[2]:
                        continue
                chosen = (info, usbdev.open_device(context, device, info))
                break
            if chosen is None:
                return False
            info, handle = chosen
            try:
                handle.claim()
            except USBError as error:
                handle.close()
                raise DisplayError("cannot claim the frame: %s" % error)
            _in, ep_out = handle.bulk_endpoints()
            self._ep_out = ep_out or ENDPOINT_OUT
            self._device = handle
            self.info = info
            details = model_for(info.product)
            if details:
                self.name, self.width, self.height = details
            else:
                self.name = "SPF"
                self.width, self.height = 800, 480
            return True
        finally:
            if devices is not None:
                context.release_list(devices)

    def close(self):
        with self._lock:
            if self._device is not None:
                try:
                    self._device.close()
                except Exception as error:
                    debug("error closing frame: %s" % error)
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

    # -- output -----------------------------------------------------------
    def send_image(self, jpeg):
        """Send one complete JPEG frame."""
        if self._device is None:
            raise DisplayError("frame is not open")
        payload_length = len(FRAME_HEADER) + 4 + len(FRAME_MARKER) \
            + len(jpeg) + len(FRAME_TRAILER)
        block = bytearray()
        block += FRAME_HEADER
        block += struct.pack("<I", payload_length)
        block += FRAME_MARKER
        block += jpeg
        block += FRAME_TRAILER
        padding = (PAD_SIZE - (len(block) % PAD_SIZE)) % PAD_SIZE
        if padding:
            block += b"\x00" * padding
        with self._lock:
            self._device.write(self._ep_out, bytes(block), self.timeout)
            self._keepalive()

    def _keepalive(self):
        """Vendor request that stops the frame leaving monitor mode."""
        try:
            self._device.control_read(KEEPALIVE_REQUEST_TYPE, KEEPALIVE_REQUEST,
                                      0, 0, 2, self.timeout)
        except USBError as error:
            debug("keep alive request failed: %s" % error)

    def set_brightness(self, level):
        """The mini monitor protocol has no backlight control."""
        return False
