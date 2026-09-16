"""The Dolby Vision profile of the running stream, and its enhancement layer.

Kodi names the dynamic range - ``VideoPlayer.HDRType`` says ``dolbyvision`` -
but not which profile carries it, and never whether a dual layer stream's
enhancement layer is a full one (FEL, which reconstructs the 12 bit master)
or a minimal one (MEL, which carries nothing but the metadata).  Both are in
the bitstream: CoreELEC 22 on Amlogic publishes the raw side data of the
stream it is decoding - the Dolby Vision RPU and the dvcC/dvvC configuration
record among them - through ``Player.Process(video.sidedata)``, and
``script.module.sidedata`` is what parses that.

That module is optional here, as everything else this add-on talks to is.
Installed, a layout can show ``Dolby Vision Profile 7.6 FEL``; without it,
or on a box that does not publish the label at all, the profile falls back
to Kodi's own ``VideoPlayer.HdrDetail`` - which names a bare ``8.1`` or
``7.6`` when the demuxer knew one - and the enhancement layer stays empty.

What is read describes the title, not the frame: a profile does not change
in the middle of a film.  So a parse runs at most once a second, stops
altogether once profile and layer are both known, and what was read is held
until something else starts playing.  That matters here in a way it does not
in a skin - the panel is redrawn four times a second, and running libdovi
over an RPU that often for a number that cannot change would be work done
for nothing.

The reading and the naming follow TinyPPI (the CoreELEC player process info
add-on by the same author), so a box running both names a stream the same
way on the television and on the panel.
"""

import re
import time

from .logger import log

try:
    from sidedata import parse_sidedata as _parse_sidedata  # type: ignore
except Exception:
    _parse_sidedata = None

#: A bare profile as ``VideoPlayer.HdrDetail`` reports one, e.g. ``8.1``.
PROFILE_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2})?$")

#: The enhancement layer types an RPU header names.
EL_TYPES = ("FEL", "MEL")

#: How often the side data may be parsed while the reading is incomplete.
PARSE_INTERVAL = 1.0

#: How many looks a stream gets before it is accepted as not Dolby Vision.
#: The first frames of a playback arrive before the demuxer has filled the
#: labels in, so a single empty look settles nothing.
MAX_ATTEMPTS = 5

EMPTY = {"profile": "", "label": "", "el": "", "line": ""}


def profile_label(profile):
    """``Profile 7.6`` - the profile named on its own.

    For a panel that has the format name elsewhere, or none at all, and
    only wants the profile spelled out.  English like every other format
    name this add-on prints (``4K UHD``, ``Dolby Vision``); a layout that
    wants another word writes ``${player.dvprofile|prefix:Profil }``.
    """
    profile = str(profile or "").strip()
    return "Profile %s" % profile if profile else ""


def describe(profile, el=""):
    """The whole line: ``Dolby Vision Profile 7.6 FEL``.

    A Dolby Vision stream whose profile nothing named reads as the bare
    format name - putting a number there would be a guess, and this is the
    line the panel is read for.
    """
    label = profile_label(profile)
    if not label:
        return "Dolby Vision"
    el = str(el or "").strip().upper()
    if el in EL_TYPES:
        return "Dolby Vision %s %s" % (label, el)
    return "Dolby Vision %s" % label


def available():
    """Whether the side data parser is installed."""
    return _parse_sidedata is not None


class DolbyVision(object):
    """The Dolby Vision fields of whatever is playing, read once per title.

    ``info`` and ``condition`` are the provider's own guarded Kodi calls, so
    this class needs no ``xbmc`` of its own and can be driven from a test.
    """

    def __init__(self, info, condition, clock=time.monotonic):
        self._info = info
        self._condition = condition
        self._clock = clock
        self._source = None
        self._fields = dict(EMPTY)
        self._settled = False
        self._attempts = 0
        self._next_parse = 0.0
        self._logged = False

    def fields(self):
        """``{"profile": "7.6", "label": "Profile 7.6", "el": "FEL",
        "line": "..."}``, all empty for a stream that is not Dolby Vision
        or not playing at all."""
        if not self._condition("Player.HasVideo"):
            self._reset(None)
            return self._fields
        source = self._info("Player.FilenameAndPath")
        if source != self._source:
            self._reset(source)
        if self._settled:
            return self._fields
        now = self._clock()
        if now < self._next_parse:
            return self._fields
        self._next_parse = now + PARSE_INTERVAL
        self._attempts += 1
        self._read()
        return self._fields

    def value(self, name):
        """One field by name, for the provider's key lookup."""
        return self.fields().get(name, "")

    # -- internals --------------------------------------------------------
    def _reset(self, source):
        self._source = source
        self._fields = dict(EMPTY)
        self._settled = False
        self._attempts = 0
        self._next_parse = 0.0

    def _read(self):
        parsed = self._parse(self._info("Player.Process(video.sidedata)"))
        config = parsed.get("config") or None
        rpu = parsed.get("rpu") or None

        if not self._is_dolby_vision(config, rpu):
            self._fields = dict(EMPTY)
            self._settled = self._attempts >= MAX_ATTEMPTS
            return

        profile = self._profile(config, rpu)
        el = ((rpu or {}).get("header") or {}).get("el_type") or ""
        el = el.upper() if el.upper() in EL_TYPES else ""
        self._fields = {"profile": profile, "label": profile_label(profile),
                        "el": el, "line": describe(profile, el)}
        self._settled = bool(profile) and self._layer_known(config, rpu)

    @staticmethod
    def _layer_known(config, rpu):
        """Whether there is nothing left to learn about the layers.

        A parsed RPU settles it either way: its header names FEL or MEL, and
        a stream without an enhancement layer has neither.  Failing that the
        configuration record settles the streams that carry no layer at all,
        and without the parser module there is nothing to wait for.
        """
        if not available():
            return True
        if rpu:
            return True
        return config is not None and not config.get("el_present")

    def _is_dolby_vision(self, config, rpu):
        """Kodi's own classification, with the bitstream as a second opinion.

        The label reads the container, so Dolby Vision announced through a
        Blu-ray playlist rather than the stream itself can be missing from
        it; a configuration record or an RPU that parsed is proof enough.
        """
        label = str(self._info("VideoPlayer.HDRType") or "").strip().lower()
        if "dolby" in label or "dovi" in label or label == "dv":
            return True
        return bool(config or rpu)

    def _profile(self, config, rpu):
        """``7.6`` - the profile and its base layer compatibility id.

        The dvcC/dvvC configuration record is container level truth and
        answers first; CoreELEC latches it from the demuxer's own hints, so
        it still names the source profile after the profile 4/7 -> 8
        conversion a player applies before the decoder.  Failing that Kodi's
        ``VideoPlayer.HdrDetail`` is read, and only when it holds a bare
        profile number so nothing unrelated leaks into the line.  The RPU's
        own guess is the last resort and carries no compatibility digit: a
        profile 10 stream has a profile 8 shaped RPU, so it is reported
        plain rather than invented.
        """
        number = (config or {}).get("profile")
        compat = (config or {}).get("compat_id")
        if number is not None and compat is not None:
            return "%s.%s" % (number, compat)
        detail = str(self._info("VideoPlayer.HdrDetail") or "").strip()
        if PROFILE_RE.match(detail):
            return detail
        guess = (rpu or {}).get("profile")
        return str(guess) if guess is not None else ""

    def _parse(self, raw):
        """The side data, parsed - or an empty result, never an exception.

        ``parse_sidedata`` degrades each section to ``None`` rather than
        raising, so the guard only covers the module being absent and the
        one failure it documents as out of its hands: a panic inside libdovi
        on malformed RPU bytes.  A failure costs the profile, logged once,
        and nothing else.
        """
        if _parse_sidedata is None or not raw:
            return {}
        try:
            parsed = _parse_sidedata(raw)
        except Exception as error:
            if not self._logged:
                self._logged = True
                log("the Dolby Vision side data could not be parsed: %s"
                    % error)
            return {}
        return parsed if isinstance(parsed, dict) else {}
