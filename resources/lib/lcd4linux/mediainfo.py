"""Readable names for what Kodi reports about the running stream.

Kodi hands out the raw identifiers of the demuxer: ``hevc`` rather than
H.265, ``truehd_atmos`` rather than Dolby TrueHD Atmos, ``8`` rather than
7.1, and a ``VideoPlayer.VideoResolution`` that says ``4K`` for a 2160p file
and ``1080`` for a 1080p one, so a layout cannot even append a "p" to it.
This module turns all of that into the labels a display should show.

The tables and the HDR classification follow TinyPPI (the CoreELEC player
process info add-on by the same author), so a box running both names a
stream the same way on the television and on the panel.
"""

import re

#: ``VideoPlayer.VideoCodec`` / ``MusicPlayer.Codec`` -> display label.
VIDEO_CODEC_NAMES = {
    "3iv2": "3ivx",
    "av1": "AV1",
    "avc1": "H.264",
    "div2": "DivX",
    "div3": "DivX",
    "divx": "DivX",
    "divx 4": "DivX",
    "dx50": "DivX",
    "flv": "FLV",
    "h264": "H.264",
    "hev1": "H.265",
    "hevc": "H.265",
    "hvc1": "H.265",
    "mp42": "MS MPEG-4 v2",
    "mp43": "MS MPEG-4 v3",
    "mp4v": "MPEG-4",
    "mpeg1": "MPEG-1",
    "mpeg1video": "MPEG-1",
    "mpeg2": "MPEG-2",
    "mpeg2video": "MPEG-2",
    "mpeg4": "MPEG-4",
    "mpg4": "MPEG-4",
    "rv40": "RealVideo",
    "svq1": "Sorenson 1",
    "svq3": "Sorenson 3",
    "theora": "Theora",
    "vc-1": "VC-1",
    "vc1": "VC-1",
    "vp6f": "On2 VP6",
    "vp8": "VP8",
    "vp9": "VP9",
    "wmv": "WMV",
    "wmv2": "WMV 8",
    "wmv3": "WMV 9",
    "wvc1": "VC-1",
    "xvid": "XviD",
}

#: ``VideoPlayer.AudioCodec`` / ``MusicPlayer.Codec`` -> display label.  The
#: Atmos and IMAX variants keep the plain codec name here; the object audio
#: is named separately by :func:`spatial_format` so a layout can place it
#: where it has room.
AUDIO_CODEC_NAMES = {
    # AAC
    "aac": "AAC",
    "aac_latm": "AAC",
    "aac_lc": "AAC-LC",
    "he_aac": "HE-AAC",
    "he_aac_v2": "HE-AAC v2",
    "aac_ssr": "AAC-SSR",
    "aac_ltp": "AAC-LTP",

    # Dolby
    "ac3": "Dolby Digital",
    "dolbydigital": "Dolby Digital",
    "eac3": "Dolby Digital Plus",
    "eac3_ddp_atmos": "Dolby Digital Plus",
    "truehd": "Dolby TrueHD",
    "truehd_atmos": "Dolby TrueHD",

    # DTS
    "dca": "DTS",
    "dts": "DTS",
    "dts_96_24": "DTS 96/24",
    "dts_es": "DTS-ES",
    "dts_express": "DTS Express",
    "dtshd": "DTS-HD",
    "dtshd_ma": "DTS-HD MA",
    "dtshd_hra": "DTS-HD HRA",
    "dtshd_ma_x": "DTS:X",
    "dtshd_ma_x_imax": "DTS:X",

    # Lossless / PCM
    "alac": "ALAC",
    "flac": "FLAC",
    "pcm": "PCM",
    "pcm_bluray": "LPCM",
    "pcm_s16le": "PCM",
    "pcm_s24le": "PCM",
    "wav": "WAV",
    "wavpack": "WavPack",

    # Compressed
    "ape": "APE",
    "mp1": "MP1",
    "mp2": "MP2",
    "mp3": "MP3",
    "mp3float": "MP3",
    "ogg": "Ogg Vorbis",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "wmapro": "WMA Pro",
    "wmav2": "WMA",

    # Misc
    "aif": "AIFF",
    "aifc": "AIFF-C",
    "aiff": "AIFF",
    "cdda": "CD Audio",
}

#: Codecs that carry height channels.  Kodi reports a plain channel count,
#: never the height channels, so the object audio has to come from the codec
#: id - which is why ``truehd`` and ``truehd_atmos`` are separate ids.
SPATIAL_FORMATS = {
    "eac3_ddp_atmos": "Atmos",
    "truehd_atmos": "Atmos",
    "dtshd_ma_x": "DTS:X",
    "dtshd_ma_x_imax": "IMAX Enhanced",
}

#: Channel count -> surround layout.
CHANNEL_LAYOUTS = {
    1: "1.0", 2: "2.0", 3: "2.1", 4: "4.0", 5: "5.0",
    6: "5.1", 7: "6.1", 8: "7.1", 10: "9.1", 12: "11.1",
}

#: Picture height -> ``(scan label stem, marketing name)``.  The height is
#: matched to the nearest standard at or below it, so an odd 1920x816
#: scope transfer is still 1080p and not "816p".
RESOLUTION_STEPS = (
    (4320, "4320", "8K UHD"),
    (2160, "2160", "4K UHD"),
    (1440, "1440", "QHD"),
    (1080, "1080", "Full HD"),
    (720, "720", "HD"),
    (576, "576", "SD"),
    (480, "480", "SD"),
    (360, "360", "SD"),
    (240, "240", "SD"),
)

#: Frame rates that are really fractional; a measured value this close to
#: one of them is the fraction, not a rate of its own.
FRACTIONAL_RATES = ((23.976, 0.05), (29.97, 0.05), (47.952, 0.05),
                    (59.94, 0.05), (119.88, 0.1))


def _clean(value):
    return str(value or "").strip()


def video_codec(name):
    """``hevc`` -> ``H.265``; anything unknown is upper-cased, not dropped."""
    text = _clean(name)
    if not text:
        return ""
    return VIDEO_CODEC_NAMES.get(text.lower(), text.upper())


def audio_codec(name):
    """``truehd_atmos`` -> ``Dolby TrueHD``; unknown ids are upper-cased."""
    text = _clean(name)
    if not text:
        return ""
    return AUDIO_CODEC_NAMES.get(text.lower(), text.upper())


def spatial_format(name):
    """``Atmos``, ``DTS:X``, ``IMAX Enhanced`` or ``""``."""
    return SPATIAL_FORMATS.get(_clean(name).lower(), "")


def audio_description(codec, channels=None):
    """The whole audio line: ``Dolby TrueHD Atmos 7.1``.

    Every part is optional, so a stream Kodi says little about still gives
    a sensible string instead of stray spaces.
    """
    parts = [audio_codec(codec), spatial_format(codec)]
    if channels not in (None, ""):
        parts.append(channel_layout(channels))
    return " ".join(part for part in parts if part)


def channel_layout(channels):
    """``8`` -> ``7.1``.

    The bed count only.  Kodi never reports the height channels of an Atmos
    or DTS:X track, so guessing ``7.1.2`` from an 8 channel TrueHD stream
    would put a number on the panel that nothing measured; the object audio
    is named by :func:`spatial_format` instead.

    An unmapped count is reported as ``<n> ch`` rather than swallowed: a
    display saying nothing is worse than one saying "9 ch".
    """
    text = _clean(channels)
    if not text:
        return ""
    try:
        count = int(float(text))
    except ValueError:
        # Already a layout such as "5.1", or something like "2.0 (stereo)".
        return text
    if count <= 0:
        return ""
    return CHANNEL_LAYOUTS.get(count) or "%d ch" % count


def hdr_type(raw):
    """Classify ``VideoPlayer.HDRType`` into a name a display can show.

    ``SDR``, ``HDR10``, ``HDR10+``, ``HLG`` or ``Dolby Vision``.  Kodi's own
    source side detection is used rather than the stream's side data, so a
    file that carries no dynamic metadata still names its format.  An empty
    label means the stream is not HDR signalled at all, i.e. SDR.
    """
    text = _clean(raw).lower()
    if not text:
        return "SDR"
    if "dolby" in text or "dovi" in text or text == "dv":
        return "Dolby Vision"
    if "hdr10+" in text or "hdr10plus" in text:
        return "HDR10+"
    if "hlg" in text:
        return "HLG"
    if "hdr10" in text or "hdr" in text or "pq" in text:
        return "HDR10"
    return "SDR"

#: Long HDR name -> the short tag a narrow panel has room for.
HDR_SHORT = {"Dolby Vision": "DV", "HDR10+": "HDR10+", "HDR10": "HDR10",
             "HLG": "HLG", "SDR": "SDR"}


def hdr_short(raw):
    """The same classification, abbreviated: ``DV`` instead of Dolby Vision."""
    return HDR_SHORT.get(hdr_type(raw), "SDR")


def _resolution_step(height):
    for step, stem, marketing in RESOLUTION_STEPS:
        if height >= step:
            return step, stem, marketing
    return 0, str(height), "SD"


def scan_suffix(scan_type):
    """``p`` or ``i`` from ``Player.Process(videoscantype)``, else ``p``.

    Kodi returns the letter itself, an empty string for progressive, or
    occasionally the whole word.
    """
    text = _clean(scan_type).lower()
    if not text:
        return "p"
    if text.startswith("i"):
        return "i"
    return "p"


def resolution(height, scan_type="", fallback=""):
    """``2160`` -> ``2160p``.

    ``fallback`` is Kodi's ``VideoPlayer.VideoResolution``, used when the
    process info is not available.  It is the label that made a layout show
    "4Kp": Kodi answers ``4K`` for a 2160 line picture and a bare number for
    everything else, so it is translated here rather than shown as it comes.
    """
    try:
        lines = int(float(_clean(height)))
    except ValueError:
        lines = 0
    if lines <= 0:
        return _resolution_from_label(fallback, scan_type)
    return "%s%s" % (_resolution_step(lines)[1], scan_suffix(scan_type))


def _resolution_from_label(label, scan_type=""):
    """Turn ``4K`` / ``1080`` / ``1080p`` into ``2160p`` / ``1080p``."""
    text = _clean(label)
    if not text:
        return ""
    lowered = text.lower()
    if lowered in ("4k", "uhd"):
        return "2160" + scan_suffix(scan_type)
    if lowered == "8k":
        return "4320" + scan_suffix(scan_type)
    if lowered.endswith(("p", "i")) and lowered[:-1].isdigit():
        return lowered
    if lowered.isdigit():
        return lowered + scan_suffix(scan_type)
    return text


def resolution_name(height, fallback=""):
    """The marketing name: ``4K UHD``, ``Full HD``, ``HD``, ``SD``."""
    try:
        lines = int(float(_clean(height)))
    except ValueError:
        lines = 0
    if lines <= 0:
        digits = re.sub(r"\D", "", _resolution_from_label(fallback))
        if not digits:
            return ""
        lines = int(digits)
    return _resolution_step(lines)[2]


def frame_rate(value):
    """``23.976023`` -> ``23.976``, ``25.000`` -> ``25``.

    Snapped to the fractional broadcast rates first, so a measured 23.9761
    is not shown as a rate nobody recognises.
    """
    try:
        rate = float(_clean(value))
    except ValueError:
        return ""
    if rate <= 0:
        return ""
    for target, tolerance in FRACTIONAL_RATES:
        if abs(rate - target) <= tolerance:
            rate = target
            break
    if rate == int(rate):
        return str(int(rate))
    return ("%.3f" % rate).rstrip("0").rstrip(".")
