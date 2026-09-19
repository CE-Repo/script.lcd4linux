"""A very small ctypes binding for libusb-1.0.

Kodi add-ons cannot rely on ``pyusb`` being installed, and CoreELEC does not
ship it, but ``libusb-1.0.so`` is always present because Kodi itself links
against it.  Only the handful of calls the display driver needs are bound.
"""

import ctypes
import ctypes.util

from .logger import debug, log

LIBUSB_ERRORS = {
    0: "success", -1: "input/output error", -2: "invalid parameter",
    -3: "access denied (insufficient permissions)", -4: "no such device",
    -5: "entity not found", -6: "resource busy", -7: "operation timed out",
    -8: "overflow", -9: "pipe error", -10: "system call interrupted",
    -11: "insufficient memory", -12: "operation not supported",
    -99: "other error",
}

LIBUSB_ENDPOINT_IN = 0x80
LIBUSB_REQUEST_GET_DESCRIPTOR = 0x06
LIBUSB_DT_CONFIG = 0x02
LIBUSB_DT_STRING = 0x03
LIBUSB_TRANSFER_TYPE_BULK = 0x02


class USBError(Exception):
    def __init__(self, message, code=None):
        if code is not None:
            message = "%s (%d: %s)" % (message, code,
                                       LIBUSB_ERRORS.get(code, "unknown"))
        Exception.__init__(self, message)
        self.code = code


class _DeviceDescriptor(ctypes.Structure):
    _fields_ = [
        ("bLength", ctypes.c_uint8),
        ("bDescriptorType", ctypes.c_uint8),
        ("bcdUSB", ctypes.c_uint16),
        ("bDeviceClass", ctypes.c_uint8),
        ("bDeviceSubClass", ctypes.c_uint8),
        ("bDeviceProtocol", ctypes.c_uint8),
        ("bMaxPacketSize0", ctypes.c_uint8),
        ("idVendor", ctypes.c_uint16),
        ("idProduct", ctypes.c_uint16),
        ("bcdDevice", ctypes.c_uint16),
        ("iManufacturer", ctypes.c_uint8),
        ("iProduct", ctypes.c_uint8),
        ("iSerialNumber", ctypes.c_uint8),
        ("bNumConfigurations", ctypes.c_uint8),
    ]


_LIBRARY_NAMES = ("libusb-1.0.so.0", "libusb-1.0.so", "libusb.so.1.0",
                  "libusb-1.0.dylib")

_lib = None


def library():
    """Load libusb once and configure the prototypes we use."""
    global _lib
    if _lib is not None:
        return _lib
    candidates = list(_LIBRARY_NAMES)
    found = ctypes.util.find_library("usb-1.0")
    if found:
        candidates.insert(0, found)
    last_error = None
    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError as error:
            last_error = error
            lib = None
    if lib is None:
        raise USBError("libusb-1.0 could not be loaded: %s" % last_error)

    lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    lib.libusb_init.restype = ctypes.c_int
    lib.libusb_exit.argtypes = [ctypes.c_void_p]
    lib.libusb_exit.restype = None
    lib.libusb_get_device_list.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))]
    lib.libusb_get_device_list.restype = ctypes.c_ssize_t
    lib.libusb_free_device_list.argtypes = [
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
    lib.libusb_free_device_list.restype = None
    lib.libusb_get_device_descriptor.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_DeviceDescriptor)]
    lib.libusb_get_device_descriptor.restype = ctypes.c_int
    lib.libusb_get_bus_number.argtypes = [ctypes.c_void_p]
    lib.libusb_get_bus_number.restype = ctypes.c_uint8
    lib.libusb_get_device_address.argtypes = [ctypes.c_void_p]
    lib.libusb_get_device_address.restype = ctypes.c_uint8
    lib.libusb_open.argtypes = [ctypes.c_void_p,
                                ctypes.POINTER(ctypes.c_void_p)]
    lib.libusb_open.restype = ctypes.c_int
    lib.libusb_close.argtypes = [ctypes.c_void_p]
    lib.libusb_close.restype = None
    lib.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_claim_interface.restype = ctypes.c_int
    lib.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_release_interface.restype = ctypes.c_int
    lib.libusb_kernel_driver_active.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_kernel_driver_active.restype = ctypes.c_int
    lib.libusb_detach_kernel_driver.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_detach_kernel_driver.restype = ctypes.c_int
    lib.libusb_attach_kernel_driver.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_attach_kernel_driver.restype = ctypes.c_int
    lib.libusb_bulk_transfer.argtypes = [
        ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_void_p, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.c_uint]
    lib.libusb_bulk_transfer.restype = ctypes.c_int
    lib.libusb_control_transfer.argtypes = [
        ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint16,
        ctypes.c_uint16, ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint]
    lib.libusb_control_transfer.restype = ctypes.c_int
    lib.libusb_reset_device.argtypes = [ctypes.c_void_p]
    lib.libusb_reset_device.restype = ctypes.c_int
    lib.libusb_clear_halt.argtypes = [ctypes.c_void_p, ctypes.c_ubyte]
    lib.libusb_clear_halt.restype = ctypes.c_int
    try:
        lib.libusb_set_auto_detach_kernel_driver.argtypes = [
            ctypes.c_void_p, ctypes.c_int]
        lib.libusb_set_auto_detach_kernel_driver.restype = ctypes.c_int
    except AttributeError:
        pass
    _lib = lib
    return _lib


class DeviceInfo(object):
    """Identifying data for a device found on the bus."""

    def __init__(self, vendor, product, bus, address, manufacturer="",
                 product_name="", serial=""):
        self.vendor = vendor
        self.product = product
        self.bus = bus
        self.address = address
        self.manufacturer = manufacturer
        self.product_name = product_name
        self.serial = serial

    def __str__(self):
        text = "%04x:%04x bus %d device %d" % (self.vendor, self.product,
                                               self.bus, self.address)
        if self.product_name:
            text += " (%s)" % self.product_name
        if self.serial:
            text += " serial %s" % self.serial
        return text


class Context(object):
    """An initialised libusb context."""

    def __init__(self):
        self.lib = library()
        self._ctx = ctypes.c_void_p()
        result = self.lib.libusb_init(ctypes.byref(self._ctx))
        if result != 0:
            raise USBError("libusb_init failed", result)

    def close(self):
        if self._ctx:
            self.lib.libusb_exit(self._ctx)
            self._ctx = ctypes.c_void_p()

    def find(self, matches):
        """Return ``[(device_pointer, DeviceInfo)]`` for matching VID/PIDs.

        ``matches`` is an iterable of ``(vendor, product)`` tuples.  The
        returned pointers stay valid until :meth:`release_list` is called.
        """
        wanted = set(matches)
        devices = ctypes.POINTER(ctypes.c_void_p)()
        count = self.lib.libusb_get_device_list(self._ctx, ctypes.byref(devices))
        if count < 0:
            raise USBError("libusb_get_device_list failed", int(count))
        found = []
        descriptor = _DeviceDescriptor()
        for index in range(count):
            device = devices[index]
            if self.lib.libusb_get_device_descriptor(device, ctypes.byref(descriptor)) != 0:
                continue
            key = (descriptor.idVendor, descriptor.idProduct)
            if wanted and key not in wanted:
                continue
            found.append((device, DeviceInfo(
                descriptor.idVendor, descriptor.idProduct,
                self.lib.libusb_get_bus_number(device),
                self.lib.libusb_get_device_address(device))))
        return devices, count, found

    def release_list(self, devices):
        if devices:
            self.lib.libusb_free_device_list(devices, 1)


class Device(object):
    """An opened USB device with one claimed interface."""

    def __init__(self, context, handle, info, interface=0):
        self.context = context
        self.lib = context.lib
        self.handle = handle
        self.info = info
        self.interface = interface
        self._detached = False
        self._claimed = False

    # -- lifecycle --------------------------------------------------------
    def claim(self):
        if hasattr(self.lib, "libusb_set_auto_detach_kernel_driver"):
            self.lib.libusb_set_auto_detach_kernel_driver(self.handle, 1)
        try:
            if self.lib.libusb_kernel_driver_active(self.handle, self.interface) == 1:
                if self.lib.libusb_detach_kernel_driver(self.handle, self.interface) == 0:
                    self._detached = True
                    debug("detached kernel driver from interface %d" % self.interface)
        except Exception as error:
            debug("kernel driver check failed: %s" % error)
        result = self.lib.libusb_claim_interface(self.handle, self.interface)
        if result != 0:
            raise USBError("cannot claim interface %d" % self.interface, result)
        self._claimed = True

    def close(self):
        if self.handle:
            if self._claimed:
                self.lib.libusb_release_interface(self.handle, self.interface)
                self._claimed = False
            if self._detached:
                try:
                    self.lib.libusb_attach_kernel_driver(self.handle, self.interface)
                except Exception:
                    pass
                self._detached = False
            self.lib.libusb_close(self.handle)
            self.handle = None

    def reset(self):
        if self.handle:
            self.lib.libusb_reset_device(self.handle)

    def clear_halt(self, endpoint):
        if self.handle:
            self.lib.libusb_clear_halt(self.handle, endpoint)

    # -- transfers --------------------------------------------------------
    def write(self, endpoint, data, timeout=3000):
        buffer_ = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        transferred = ctypes.c_int(0)
        result = self.lib.libusb_bulk_transfer(
            self.handle, endpoint, buffer_, len(data),
            ctypes.byref(transferred), timeout)
        if result != 0:
            raise USBError("bulk write of %d bytes failed" % len(data), result)
        return transferred.value

    def read(self, endpoint, length, timeout=3000):
        buffer_ = (ctypes.c_ubyte * length)()
        transferred = ctypes.c_int(0)
        result = self.lib.libusb_bulk_transfer(
            self.handle, endpoint, buffer_, length,
            ctypes.byref(transferred), timeout)
        if result != 0:
            raise USBError("bulk read of %d bytes failed" % length, result)
        return bytes(bytearray(buffer_[:transferred.value]))

    def control_read(self, request_type, request, value, index, length,
                     timeout=1000):
        buffer_ = (ctypes.c_ubyte * length)()
        result = self.lib.libusb_control_transfer(
            self.handle, request_type, request, value, index, buffer_, length,
            timeout)
        if result < 0:
            raise USBError("control transfer failed", result)
        return bytes(bytearray(buffer_[:result]))

    # -- descriptors ------------------------------------------------------
    def string_descriptor(self, index):
        if not index:
            return ""
        try:
            raw = self.control_read(LIBUSB_ENDPOINT_IN,
                                    LIBUSB_REQUEST_GET_DESCRIPTOR,
                                    (LIBUSB_DT_STRING << 8) | index,
                                    0x0409, 255)
        except USBError:
            return ""
        if len(raw) < 2:
            return ""
        try:
            return raw[2:].decode("utf-16-le").rstrip("\x00")
        except Exception:
            return ""

    def bulk_endpoints(self):
        """Find the bulk IN/OUT endpoints of the first interface.

        The configuration descriptor is fetched as raw bytes and parsed here
        so no libusb struct layouts have to be mirrored in ctypes.
        """
        try:
            header = self.control_read(LIBUSB_ENDPOINT_IN,
                                       LIBUSB_REQUEST_GET_DESCRIPTOR,
                                       (LIBUSB_DT_CONFIG << 8), 0, 9)
            if len(header) < 4:
                return None, None
            total = header[2] | (header[3] << 8)
            raw = self.control_read(LIBUSB_ENDPOINT_IN,
                                    LIBUSB_REQUEST_GET_DESCRIPTOR,
                                    (LIBUSB_DT_CONFIG << 8), 0, total)
        except USBError as error:
            debug("cannot read configuration descriptor: %s" % error)
            return None, None

        ep_in = ep_out = None
        pos = 0
        while pos + 1 < len(raw):
            length = raw[pos]
            if length < 2:
                break
            if raw[pos + 1] == 0x05 and length >= 6:  # endpoint descriptor
                address = raw[pos + 2]
                attributes = raw[pos + 3]
                if attributes & 0x03 == LIBUSB_TRANSFER_TYPE_BULK:
                    if address & LIBUSB_ENDPOINT_IN and ep_in is None:
                        ep_in = address
                    elif not address & LIBUSB_ENDPOINT_IN and ep_out is None:
                        ep_out = address
            pos += length
        return ep_in, ep_out


def open_device(context, device, info, interface=0):
    handle = ctypes.c_void_p()
    result = context.lib.libusb_open(device, ctypes.byref(handle))
    if result != 0 or not handle:
        raise USBError("cannot open %s" % info, result)
    opened = Device(context, handle, info, interface)
    try:
        descriptor = _DeviceDescriptor()
        if context.lib.libusb_get_device_descriptor(device, ctypes.byref(descriptor)) == 0:
            info.manufacturer = opened.string_descriptor(descriptor.iManufacturer)
            info.product_name = opened.string_descriptor(descriptor.iProduct)
            info.serial = opened.string_descriptor(descriptor.iSerialNumber)
    except Exception as error:
        debug("cannot read string descriptors: %s" % error)
    return opened


def available():
    """True when libusb can be loaded at all."""
    try:
        library()
        return True
    except USBError as error:
        log("libusb unavailable: %s" % error)
        return False
