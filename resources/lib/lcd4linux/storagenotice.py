"""Hides Kodi's "device mounted / removed" notices for the Samsung frame.

A Samsung frame first shows up as a USB drive.  CoreELEC mounts it and Kodi
announces it, a moment later the service switches the frame into monitor
mode, the drive disappears and Kodi announces that too - on every start of
the box.  This little thread closes Kodi's notification while a frame is in
mass storage mode and for a short while after, so neither notice stays on
the screen.  Notifications at any other time are left alone.
"""

import threading
import time

from . import spf
from .logger import debug

try:
    import xbmc  # type: ignore
except ImportError:
    xbmc = None

#: How long after the frame was last seen as a USB drive a notification is
#: still taken for one of its notices.  The removal follows the switch
#: request within a second or two; Kodi may queue it behind the mount notice.
NOTICE_WINDOW_SECONDS = 20.0

#: How often Kodi is asked whether a notification is on screen.
POLL_SECONDS = 0.25

#: How often a notification that was left alone is looked at again, in case
#: Kodi replaced it with the next one from its queue.
RECHECK_SECONDS = 1.0


def _frame_notice_likely(now=None):
    """Whether a notification on screen is most likely about the frame."""
    now = time.time() if now is None else now
    if now - spf.storage_seen_at() < NOTICE_WINDOW_SECONDS:
        return True
    try:
        found = spf.SamsungSPF.enumerate()
    except Exception as err:
        debug("cannot look for a frame in storage mode: %s" % err)
        return False
    # enumerate() marks a frame in storage mode as seen.
    return any(mode == "storage" for _info, mode, _name in found)


class StorageNoticeGuard(object):
    """Closes Kodi's mount/unmount notices for the frame.

    ``enabled`` is asked on every poll, so the setting takes effect without
    restarting anything.
    """

    def __init__(self, enabled, is_visible=None, close=None):
        self._enabled = enabled
        self._is_visible = is_visible or _toast_visible
        self._close = close or _close_toast
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run,
                                        name="lcd4linux-notice-guard")
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2.0)
            self._thread = None

    def check(self, now=None):
        """One look at the screen; ``True`` when a notice was closed."""
        if not self._enabled() or not self._is_visible():
            return False
        if not _frame_notice_likely(now):
            return False
        self._close()
        debug("closed Kodi's notification about the frame's USB drive")
        return True

    def _run(self):
        shown = False
        next_check = 0.0
        while not self._stop.wait(POLL_SECONDS):
            try:
                visible = self._enabled() and self._is_visible()
                if not visible:
                    shown = False
                    continue
                now = time.time()
                if shown and now < next_check:
                    continue
                shown = True
                next_check = now + RECHECK_SECONDS
                if self.check(now):
                    shown = False
            except Exception as err:
                debug("notification guard: %s" % err)


def _toast_visible():
    if xbmc is None:
        return False
    return bool(xbmc.getCondVisibility("Window.IsVisible(notification)"))


def _close_toast():
    if xbmc is not None:
        xbmc.executebuiltin("Dialog.Close(notification,true)")
