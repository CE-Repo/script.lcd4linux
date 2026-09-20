"""What the browser editor needs to know about layouts.

The editor builds its property panel from this catalogue instead of hard
coding the fields in JavaScript, so a new widget option only has to be
described once - here, next to the renderer that reads it.

Labels carry both languages (``label`` and ``label_de``); the page picks the
one matching the browser.  That keeps the ~200 short words of the editor out
of the Kodi string table, which only covers what is drawn on the panel.
"""

from . import faicons
from . import widgets as widget_module

#: Widget types in the order the palette shows them.
PALETTE = ("text", "image", "progress", "graph", "rect", "line", "circle",
           "icon", "analogclock")


def _field(key, kind, label, label_de, **extra):
    field = {"key": key, "type": kind, "label": label, "label_de": label_de}
    field.update(extra)
    return field


def _options(*pairs):
    return [{"value": value, "label": label, "label_de": label_de}
            for value, label, label_de in pairs]


ALIGN_OPTIONS = _options(("left", "left", "links"),
                         ("center", "centre", "mittig"),
                         ("right", "right", "rechts"))

VALIGN_OPTIONS = _options(("top", "top", "oben"),
                          ("middle", "middle", "mittig"),
                          ("bottom", "bottom", "unten"))

FIT_OPTIONS = _options(("contain", "contain", "einpassen"),
                       ("cover", "cover", "füllend"),
                       ("stretch", "stretch", "verzerren"))

SCROLL_OPTIONS = _options(("none", "none", "kein"),
                          ("marquee", "marquee", "Laufband"),
                          ("bounce", "bounce", "hin und her"))

ICON_STYLE_OPTIONS = _options(("", "automatic", "automatisch"),
                              ("solid", "solid", "gefüllt"),
                              ("regular", "outlined", "Umriss"),
                              ("brands", "brands", "Marken"))

#: Properties every widget understands.
COMMON_FIELDS = [
    _field("name", "text", "Name", "Name",
           hint="only shown in the debug log", hint_de="nur im Protokoll"),
    _field("x", "length", "X", "X", default=0),
    _field("y", "length", "Y", "Y", default=0),
    _field("w", "length", "Width", "Breite"),
    _field("h", "length", "Height", "Höhe"),
    _field("lockaspect", "bool", "Lock aspect ratio", "Seitenverhältnis sperren",
           editoronly=True,
           hint="width and height then follow each other, dragging and typing",
           hint_de="Breite und Höhe folgen einander, beim Ziehen wie beim Tippen"),
    _field("angle", "angle", "Rotation °", "Drehung °", default=0,
           min=0, max=360,
           hint="clockwise, about the middle of the box",
           hint_de="im Uhrzeigersinn, um die Mitte des Rahmens"),
    _field("condition", "condition", "Condition", "Bedingung"),
    _field("opacity", "number", "Opacity %", "Deckkraft %",
           default=100, min=0, max=100),
]

WIDGET_FIELDS = {
    "text": [
        _field("text", "token", "Text", "Text", default="", multiline=True,
               hint="{...} ties words to a value and drops both when it is empty",
               hint_de="{...} bindet Wörter an einen Wert und lässt beide"
                       " weg, wenn er leer ist"),
        _field("font", "font", "Font", "Schrift"),
        _field("size", "number", "Size", "Größe", min=6, max=200),
        _field("bold", "bool", "Bold", "Fett"),
        _field("color", "color", "Colour", "Farbe"),
        _field("align", "select", "Align", "Ausrichtung", options=ALIGN_OPTIONS),
        _field("valign", "select", "Vertical align", "Senkrecht",
               options=VALIGN_OPTIONS),
        _field("wrap", "bool", "Wrap", "Umbrechen"),
        _field("lines", "number", "Max lines", "Max. Zeilen", min=0, max=20),
        _field("linespacing", "number", "Line spacing", "Zeilenabstand"),
        _field("padding", "number", "Padding", "Innenabstand", min=0),
        _field("background", "color", "Background", "Hintergrund"),
        _field("radius", "number", "Corner radius", "Eckenradius", min=0),
        _field("scroll", "select", "Scroll", "Lauftext", options=SCROLL_OPTIONS),
        _field("scrollspeed", "number", "Scroll speed", "Tempo (px/s)"),
        _field("scrollpause", "number", "Scroll pause", "Pause (s)"),
        _field("scrollgap", "number", "Scroll gap", "Abstand"),
        _field("shadow", "color", "Shadow", "Schatten"),
        _field("shadowoffset", "number", "Shadow offset", "Schattenversatz"),
        _field("outline", "color", "Outline", "Umriss"),
        _field("showempty", "bool", "Draw when empty", "Auch leer zeichnen"),
    ],
    "progress": [
        _field("value", "token", "Value", "Wert", default="${player.percent}"),
        _field("min", "number", "Minimum", "Minimum", default=0),
        _field("max", "number", "Maximum", "Maximum", default=100),
        _field("orientation", "select", "Orientation", "Richtung",
               options=_options(("horizontal", "horizontal", "waagerecht"),
                                ("vertical", "vertical", "senkrecht"))),
        _field("color", "color", "Colour", "Farbe"),
        _field("gradient", "color", "Gradient", "Verlauf"),
        _field("background", "color", "Background", "Hintergrund"),
        _field("radius", "number", "Corner radius", "Eckenradius", min=0),
        _field("border", "number", "Border", "Rahmen", min=0),
        _field("bordercolor", "color", "Border colour", "Rahmenfarbe"),
        _field("style", "select", "Style", "Stil",
               options=_options(("bar", "bar", "Balken"),
                                ("segments", "segments", "Segmente"))),
        _field("segments", "number", "Segments", "Segmente", min=1),
        _field("gap", "number", "Gap", "Lücke", min=0),
        _field("inactivecolor", "color", "Inactive colour", "Farbe (unbenutzt)"),
        _field("knob", "bool", "Knob", "Knopf"),
        _field("knobsize", "number", "Knob size", "Knopfgröße"),
        _field("knobcolor", "color", "Knob colour", "Knopffarbe"),
    ],
    "graph": [
        _field("value", "token", "Value", "Wert", default="${system.cpu}"),
        _field("min", "number", "Minimum", "Minimum", default=0),
        _field("max", "number", "Maximum", "Maximum", default=100),
        _field("points", "number", "Samples", "Messwerte", min=2),
        _field("interval", "number", "Interval (s)", "Abstand (s)"),
        _field("color", "color", "Colour", "Farbe"),
        _field("fill", "color", "Fill", "Füllung"),
        _field("background", "color", "Background", "Hintergrund"),
        _field("thickness", "number", "Thickness", "Stärke", min=1),
    ],
    "rect": [
        _field("color", "color", "Colour", "Farbe"),
        _field("gradient", "color", "Gradient", "Verlauf"),
        _field("direction", "select", "Direction", "Richtung",
               options=_options(("vertical", "vertical", "senkrecht"),
                                ("horizontal", "horizontal", "waagerecht"))),
        _field("radius", "number", "Corner radius", "Eckenradius", min=0),
        _field("border", "number", "Border", "Rahmen", min=0),
        _field("bordercolor", "color", "Border colour", "Rahmenfarbe"),
    ],
    "line": [
        _field("color", "color", "Colour", "Farbe"),
        _field("thickness", "number", "Thickness", "Stärke", min=1),
        _field("x2", "length", "End X", "Ende X"),
        _field("y2", "length", "End Y", "Ende Y"),
    ],
    "circle": [
        _field("color", "color", "Colour", "Farbe"),
        _field("radius", "number", "Radius", "Radius", min=0),
        _field("thickness", "number", "Ring width", "Ringstärke", min=0,
               hint="0 fills the circle", hint_de="0 füllt den Kreis"),
    ],
    "image": [
        _field("src", "token", "Source", "Quelle", default="${player.thumb}"),
        _field("fallback", "token", "Fallback", "Ersatzquelle"),
        _field("fit", "select", "Fit", "Einpassen", options=FIT_OPTIONS),
        _field("radius", "number", "Corner radius", "Eckenradius", min=0),
        _field("align", "select", "Align", "Ausrichtung", options=ALIGN_OPTIONS),
        _field("valign", "select", "Vertical align", "Senkrecht",
               options=VALIGN_OPTIONS),
    ],
    "icon": [
        _field("icon", "icon", "Symbol", "Symbol", default="play",
               hint="pick from the built-in shapes or all of Font Awesome Free",
               hint_de="aus den eingebauten Formen oder ganz Font Awesome Free"),
        _field("style", "select", "Style", "Stil", options=ICON_STYLE_OPTIONS,
               hint="only for Font Awesome symbols",
               hint_de="nur für Font-Awesome-Symbole"),
        _field("color", "color", "Colour", "Farbe"),
        _field("trim", "bool", "Fill the box", "Rahmen ausfüllen",
               hint="scale the outline instead of keeping Font Awesome's padding",
               hint_de="Umriss skalieren statt den Rand von Font Awesome zu behalten"),
    ],
    "analogclock": [
        _field("face", "color", "Face", "Zifferblatt"),
        _field("rim", "color", "Rim", "Rand"),
        _field("rimwidth", "number", "Rim width", "Randstärke", min=0),
        _field("color", "color", "Hands", "Zeiger"),
        _field("secondcolor", "color", "Second hand", "Sekundenzeiger"),
        _field("ticks", "bool", "Ticks", "Striche", default=True),
        _field("tickcolor", "color", "Tick colour", "Strichfarbe"),
        _field("seconds", "bool", "Second hand", "Sekundenzeiger", default=True),
    ],
}

PAGE_FIELDS = [
    _field("name", "text", "Name", "Name"),
    _field("condition", "condition", "Condition", "Bedingung"),
    _field("duration", "number", "Duration (s)", "Dauer (s)", min=0,
           hint="0 uses the layout interval", hint_de="0 nutzt das Layout-Intervall"),
    _field("priority", "number", "Priority", "Priorität",
           hint="higher wins over lower pages", hint_de="höher verdrängt niedriger"),
    _field("background", "color", "Background", "Hintergrund"),
    _field("backgroundimage", "token", "Background image", "Hintergrundbild"),
    _field("backgroundfallback", "token", "Background fallback",
           "Ersatz-Hintergrund",
           hint="used when the background image is missing",
           hint_de="wird genutzt, wenn das Hintergrundbild fehlt"),
    _field("backgrounddim", "number", "Dim %", "Abdunkeln %", min=0, max=100),
]

LAYOUT_FIELDS = [
    _field("name", "text", "Name", "Name"),
    _field("background", "color", "Background", "Hintergrund"),
    _field("accent", "text", "Accent colour", "Akzentfarbe",
           hint="a colour or auto:${player.thumb}",
           hint_de="Farbe oder auto:${player.thumb}"),
    _field("pageinterval", "number", "Page interval (s)", "Seitenwechsel (s)",
           min=0),
]

DEFAULT_FIELDS = [
    _field("font", "font", "Default font", "Standardschrift"),
    _field("size", "number", "Default size", "Standardgröße", min=6, max=200),
    _field("color", "color", "Default colour", "Standardfarbe"),
]

#: Sizes of the displays the add-on drives, offered when a layout is created.
SIZES = [
    {"size": [800, 480], "label": "Samsung SPF 800×480"},
    {"size": [1024, 600], "label": "Samsung SPF 1024×600"},
    {"size": [480, 800], "label": "Samsung SPF 480×800 (90°)"},
    {"size": [480, 320], "label": "Small display 480×320"},
    {"size": [320, 480], "label": "Small display 320×480 (90°)"},
]

#: Data fields, grouped the way the token picker lists them.
TOKEN_GROUPS = [
    {
        "id": "player", "label": "Playback", "label_de": "Wiedergabe",
        "tokens": [
            ("player.title", "Title", "Titel"),
            ("player.artist", "Artist", "Interpret"),
            ("player.albumartist", "Album artist", "Album-Interpret"),
            ("player.album", "Album", "Album"),
            ("player.genre", "Genre", "Genre"),
            ("player.year", "Year", "Jahr"),
            ("player.track", "Track number", "Titelnummer"),
            ("player.discnumber", "Disc", "CD"),
            ("player.rating", "Rating", "Bewertung"),
            ("player.showtitle", "TV show", "Serie"),
            ("player.season", "Season", "Staffel"),
            ("player.episode", "Episode", "Folge"),
            ("player.episodelabel", "S02E05", "S02E05"),
            ("player.plot", "Plot", "Handlung"),
            ("player.time", "Elapsed", "Gespielt"),
            ("player.time_s", "Elapsed (s)", "Gespielt (s)"),
            ("player.duration", "Duration", "Länge"),
            ("player.duration_s", "Duration (s)", "Länge (s)"),
            ("player.remaining", "Remaining", "Restzeit"),
            ("player.remaining_s", "Remaining (s)", "Restzeit (s)"),
            ("player.percent", "Progress 0-100", "Fortschritt 0-100"),
            ("player.starttime", "Started at", "Beginn"),
            ("player.finishtime", "Ends at", "Ende"),
            ("player.state", "playing/paused/stopped", "playing/paused/stopped"),
            ("player.mediatype", "audio/video/…", "audio/video/…"),
            ("player.thumb", "Cover", "Cover"),
            ("player.poster", "Poster", "Poster"),
            ("player.fanart", "Fanart", "Fanart"),
            ("player.clearlogo", "Clearlogo", "Clearlogo"),
            ("player.codec", "Codec (H.265, FLAC)", "Codec (H.265, FLAC)"),
            ("player.videocodec", "Video codec (H.265)", "Video-Codec (H.265)"),
            ("player.audiocodec", "Audio codec (Dolby TrueHD)",
             "Ton-Codec (Dolby TrueHD)"),
            ("player.spatial", "Object audio (Atmos, DTS:X)",
             "Objektton (Atmos, DTS:X)"),
            ("player.audio", "Audio line (Dolby TrueHD Atmos 7.1)",
             "Tonzeile (Dolby TrueHD Atmos 7.1)"),
            ("player.hdr", "Dynamic range (Dolby Vision, HDR10+)",
             "Dynamikumfang (Dolby Vision, HDR10+)"),
            ("player.hdr_short", "Dynamic range, short (DV)",
             "Dynamikumfang, kurz (DV)"),
            ("player.dv", "Dolby Vision line (Profile 7.6 FEL)",
             "Dolby-Vision-Zeile (Profil 7.6 FEL)"),
            ("player.dvprofile", "Dolby Vision profile (7.6)",
             "Dolby-Vision-Profil (7.6)"),
            ("player.dvprofile_long", "Profile, spelled out (Profile 7.6)",
             "Profil, ausgeschrieben (Profile 7.6)"),
            ("player.dvel", "Enhancement layer (FEL, MEL)",
             "Enhancement Layer (FEL, MEL)"),
            ("player.bitrate", "Bitrate", "Bitrate"),
            ("player.videobitrate", "Video bitrate (24.5 Mb/s)",
             "Video-Bitrate (24.5 Mb/s)"),
            ("player.videobitrate_mbps", "Video bitrate, number only",
             "Video-Bitrate, nur Zahl"),
            ("player.audiobitrate", "Audio bitrate (1536 Kb/s)",
             "Ton-Bitrate (1536 Kb/s)"),
            ("player.audiobitrate_kbps", "Audio bitrate, number only",
             "Ton-Bitrate, nur Zahl"),
            ("player.samplerate", "Sample rate", "Abtastrate"),
            ("player.channels", "Channels (5.1)", "Kanäle (5.1)"),
            ("player.channels_count", "Channel count (6)", "Kanalzahl (6)"),
            ("player.resolution", "Resolution (2160p)", "Auflösung (2160p)"),
            ("player.resolution_long", "Resolution (3840x2160p)",
             "Auflösung (3840x2160p)"),
            ("player.resolutionname", "Resolution name (4K UHD)",
             "Auflösungsname (4K UHD)"),
            ("player.video", "Video line (H.265 2160p HDR10)",
             "Videozeile (H.265 2160p HDR10)"),
            ("player.videowidth", "Picture width", "Bildbreite"),
            ("player.videoheight", "Picture height", "Bildhöhe"),
            ("player.fps", "Frame rate (23.976)", "Bildrate (23.976)"),
            ("player.aspect", "Aspect", "Seitenverhältnis"),
            ("player.next", "Next title", "Nächster Titel"),
            ("player.nextartist", "Next artist", "Nächster Interpret"),
            ("player.playlistposition", "Playlist position", "Listenposition"),
            ("player.playlistlength", "Playlist length", "Listenlänge"),
            ("player.filename", "File", "Datei"),
            ("player.path", "Folder", "Ordner"),
        ],
    },
    {
        "id": "system", "label": "System", "label_de": "System",
        "tokens": [
            ("system.time", "Clock", "Uhrzeit"),
            ("system.time12", "Clock 12 h", "Uhrzeit 12 h"),
            ("system.timesec", "Clock with seconds", "Uhrzeit mit Sekunden"),
            ("system.seconds", "Seconds", "Sekunden"),
            ("system.date", "Date", "Datum"),
            ("system.date_iso", "Date ISO", "Datum ISO"),
            ("system.date_short", "Date short", "Datum kurz"),
            ("system.date_long", "Date long", "Datum lang"),
            ("system.weekday", "Weekday", "Wochentag"),
            ("system.weekday_short", "Weekday short", "Wochentag kurz"),
            ("system.day", "Day", "Tag"),
            ("system.month", "Month", "Monat"),
            ("system.monthname", "Month name", "Monatsname"),
            ("system.year", "Year", "Jahr"),
            ("system.cpu", "CPU load %", "CPU-Last %"),
            ("system.cputemp", "CPU temperature", "CPU-Temperatur"),
            ("system.gputemp", "GPU temperature", "GPU-Temperatur"),
            ("system.memory", "Memory used %", "Speicher belegt %"),
            ("system.memoryfree", "Memory free", "Speicher frei"),
            ("system.memorytotal", "Memory total", "Speicher gesamt"),
            ("system.uptime", "Uptime", "Laufzeit"),
            ("system.hostname", "Host name", "Rechnername"),
            ("system.ip", "IP address", "IP-Adresse"),
            ("system.kodiversion", "Kodi version", "Kodi-Version"),
            ("system.buildversion", "Build", "Build"),
            ("system.freespace", "Free disk space", "Freier Speicher"),
            ("system.volume", "Volume", "Lautstärke"),
            ("system.muted", "Muted", "Stumm"),
            ("system.screensaver", "Screensaver", "Bildschirmschoner"),
            ("system.profile", "Profile", "Profil"),
        ],
    },
    {
        "id": "weather", "label": "Weather", "label_de": "Wetter",
        "tokens": [
            ("weather.temperature", "Temperature", "Temperatur"),
            ("weather.conditions", "Conditions", "Wetterlage"),
            ("weather.location", "Location", "Ort"),
        ],
    },
    {
        "id": "library", "label": "Library", "label_de": "Bibliothek",
        "tokens": [
            ("library.songs", "Songs", "Titel"),
            ("library.albums", "Albums", "Alben"),
            ("library.artists", "Artists", "Interpreten"),
            ("library.movies", "Movies", "Filme"),
            ("library.tvshows", "TV shows", "Serien"),
            ("library.episodes", "Episodes", "Folgen"),
        ],
    },
    {
        "id": "addon", "label": "Add-on", "label_de": "Add-on",
        "tokens": [
            ("addon.name", "Add-on name", "Add-on-Name"),
            ("addon.version", "Add-on version", "Add-on-Version"),
            ("info:MusicPlayer.Album", "Any Kodi InfoLabel",
             "Jedes Kodi-InfoLabel"),
            ("bool:Player.HasVideo", "Any Kodi condition as 1/0",
             "Jede Kodi-Bedingung als 1/0"),
        ],
    },
]

#: Filters offered behind the ``|`` in the token picker.
FILTERS = [
    ("upper", "UPPER CASE", "GROSSBUCHSTABEN"),
    ("lower", "lower case", "kleinbuchstaben"),
    ("title", "Title Case", "Wortanfänge groß"),
    ("capitalize", "First letter", "Erster Buchstabe groß"),
    ("strip", "Trim spaces", "Leerzeichen entfernen"),
    ("trunc:20", "Shorten to 20 characters", "Auf 20 Zeichen kürzen"),
    ("pad:3", "Pad to 3 characters", "Auf 3 Zeichen auffüllen"),
    ("hms", "Seconds as m:ss", "Sekunden als m:ss"),
    ("hhmmss", "Seconds as h:mm:ss", "Sekunden als h:mm:ss"),
    ("int", "Whole number", "Ganze Zahl"),
    ("round:1", "Round to 1 decimal", "Auf 1 Stelle runden"),
    ("abs", "Absolute value", "Betrag"),
    ("default:-", "Fallback text", "Ersatztext"),
    ("prefix: · ", "Prefix, dropped when empty", "Davor, entfällt wenn leer"),
    ("suffix: ", "Suffix, dropped when empty", "Dahinter, entfällt wenn leer"),
    ("replace:a:b", "Replace", "Ersetzen"),
    ("first:,", "First part", "Erster Teil"),
]

#: Ready made ``{...}`` groups for the picker.  Everything in a group goes
#: when its values do, which is how words and punctuation are tied to the
#: field they belong to instead of being left standing on their own.
GROUPS = [
    ("{${player.title} live}",
     "A word behind the value", "Ein Wort hinter dem Wert"),
    ("{Track ${player.track}}",
     "A word in front of it", "Ein Wort davor"),
    ("{${player.artist} · ${player.album}}",
     "Two values and their punctuation",
     "Zwei Werte samt Satzzeichen"),
    ("${player.album}{ (${player.year})}",
     "An addition only while it is known",
     "Ein Zusatz nur solange er bekannt ist"),
    ("{${player.album}{ (${player.year})}}",
     "Groups may sit inside groups", "Gruppen dürfen ineinander stehen"),
]

#: Ready made conditions for the drop down next to a condition field.
CONDITIONS = [
    ("", "always", "immer"),
    ("playing", "something is playing", "es läuft etwas"),
    ("paused", "paused", "pausiert"),
    ("stopped", "nothing is playing", "nichts läuft"),
    ("active", "playing or paused", "läuft oder pausiert"),
    ("!active", "not playing", "läuft nicht"),
    ("audio", "music", "Musik"),
    ("video", "video", "Video"),
    ("audio|video", "music or video", "Musik oder Video"),
    ("screensaver", "screensaver on", "Bildschirmschoner an"),
    ("${player.album}", "album is known", "Album bekannt"),
    ("${player.percent} > 90", "more than 90 % played", "über 90 % gespielt"),
    ("${system.cputemp} >= 70", "CPU above 70 °C", "CPU über 70 °C"),
]

#: Starting geometry and options for a widget dropped on the canvas.
NEW_WIDGET = {
    "text": {"w": 240, "h": 28, "text": "${player.title}", "size": 22},
    "image": {"w": 120, "h": 120, "src": "${player.thumb}", "fit": "cover",
              "radius": 8},
    "progress": {"w": 240, "h": 10, "value": "${player.percent}", "radius": 5,
                 "color": "#17b2e2", "background": "#20242e"},
    "graph": {"w": 240, "h": 60, "value": "${system.cpu}", "color": "#17b2e2",
              "fill": "#2217b2e2", "points": 60, "interval": 2},
    "rect": {"w": 160, "h": 60, "color": "#1e2330", "radius": 6},
    "line": {"w": 200, "h": 1, "color": "#2c3344"},
    "circle": {"w": 60, "h": 60, "color": "#17b2e2"},
    "icon": {"w": 24, "h": 24, "icon": "play", "color": "#f2f5fa"},
    "analogclock": {"w": 96, "h": 96, "color": "#f2f5fa", "rim": "#2c3344",
                    "face": "#11141c"},
}

def blank_layout(width=480, height=320):
    """A small but complete layout the "new layout" button starts from."""
    return {
        "name": "My layout",
        "size": [int(width), int(height)],
        "background": "#0b0d12",
        "defaults": {"font": "sans", "size": 18, "color": "#f2f5fa"},
        "pageinterval": 15,
        "pages": [{
            "name": "Page 1",
            "widgets": [
                {"type": "text", "x": 16, "y": 16, "w": int(width) - 32,
                 "h": 34, "text": "${player.title}", "size": 26, "bold": True,
                 "color": "#ffffff", "scroll": "marquee"},
                {"type": "text", "x": 16, "y": 54, "w": int(width) - 32,
                 "h": 26, "text": "${player.artist}", "size": 18,
                 "color": "#9aa3b5"},
                {"type": "text", "x": 16, "y": int(height) - 44,
                 "w": int(width) - 32, "h": 30, "text": "${system.time}",
                 "size": 24, "align": "right", "color": "#6f7891"},
            ],
        }],
    }


def describe_icons():
    """What the icon dialog needs to know before its first search.

    The names themselves are not sent along: the whole free set is a few
    thousand entries, so the dialog asks ``/api/icons`` for the page it is
    showing instead of holding all of them.
    """
    book = faicons.catalogue()
    return {
        "version": book.version,
        "count": book.count,
        "styles": [{"value": style, "count": book.counts().get(style, 0)}
                   for style in faicons.STYLES],
        "default": faicons.DEFAULT_STYLE,
        "downloads": faicons.downloads_enabled(),
        "licence": "Font Awesome Free - icons: CC BY 4.0",
        "url": "https://fontawesome.com/license/free",
    }


def describe_fonts(fonts=None):
    """Every family the add-on can draw, and what it can do with it.

    The editor cannot render the face itself, so its font dialog asks
    ``/api/fontsample`` for a picture per family; this is the list it walks
    and what it prints beside each sample.  ``sizes`` is empty for a real
    face, which draws any size asked of it, and lists the fixed sizes of an
    older ``.l4f`` bitmap font where someone still has one.
    """
    if fonts is None:
        return [{"name": "sans", "sizes": [], "scalable": True,
                 "bold": False}]
    available = fonts.available()
    return [{"name": name, "sizes": sorted(available[name]),
             "scalable": not available[name],
             "bold": ("%s-bold" % name) in available}
            for name in sorted(available)]


def describe(fonts=None):
    """The whole catalogue, as the editor fetches it from ``/api/schema``."""
    families = sorted(fonts.families()) if fonts is not None else ["sans", "mono"]
    types = []
    for kind in PALETTE:
        if kind not in widget_module.REGISTRY:
            continue
        types.append({"type": kind, "fields": WIDGET_FIELDS.get(kind, [])})
    return {
        "widgets": types,
        "common": COMMON_FIELDS,
        "page": PAGE_FIELDS,
        "layout": LAYOUT_FIELDS,
        "defaults": DEFAULT_FIELDS,
        "sizes": SIZES,
        "fonts": families,
        "fontinfo": describe_fonts(fonts),
        "icons": sorted(widget_module.ICONS),
        "faicons": describe_icons(),
        "tokens": [{"id": group["id"], "label": group["label"],
                    "label_de": group["label_de"],
                    "tokens": [{"token": token, "label": label,
                                "label_de": label_de}
                               for token, label, label_de in group["tokens"]]}
                   for group in TOKEN_GROUPS],
        "filters": [{"filter": name, "label": label, "label_de": label_de}
                    for name, label, label_de in FILTERS],
        "groups": [{"snippet": snippet, "label": label, "label_de": label_de}
                   for snippet, label, label_de in GROUPS],
        "conditions": [{"value": value, "label": label, "label_de": label_de}
                       for value, label, label_de in CONDITIONS],
        "new": NEW_WIDGET,
    }
