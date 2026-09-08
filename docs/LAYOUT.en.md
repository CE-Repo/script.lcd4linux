# Layout reference

A layout is a JSON file describing **what** is shown **where** on the panel.
Lines starting with `//` or `#` are skipped as comments.

Put your own layouts in

```
/storage/.kodi/userdata/addon_data/script.lcd4linux/layouts/
```

Files there take precedence over the bundled ones and survive updates.
After editing, choose *Reload service* from the add-on menu.

Layout files are read as **UTF-8**; a byte order mark, as written by some
Windows editors, is tolerated.

The `size` field has to match the display. Each bundled layout exists for both
supported sizes: if the selected layout is `default.json` and an 800x480 panel
is attached, the add-on automatically uses `default-800x480.json` when that
file exists. Your own layouts follow the same rule - `mine-800x480.json` next
to `mine.json`.

Rescaling does not have to be done by hand:

```sh
python3 tools/scale_layout.py mine.json 800 480
```

### Readable from a distance

On a 3.5" panel the font size decides whether something can be read at all.
Rules of thumb for 480x320:

* Primary information: 40-130 px. A title at 40 px reads from two or three
  metres, a clock at 128 px across the room.
* Secondary information: not below 20 px. Anything smaller turns into a grey
  smudge from a distance.
* Contrast beats subtlety: white on black. Dark grey on near black (say
  `#4a5266` on `#0b0d12`) looks good at the desk and disappears completely
  from three metres - use `#a8b0c0` for secondary text instead.
* Few elements: three to five per page. What is left may then be large.
* Make bars thick: 18-26 px instead of 8-12 px.

The bundled `xl-*` layouts follow these rules and are a good starting point.

---

## 1. Skeleton

```json
{
  "name": "My layout",
  "size": [480, 320],
  "background": "#0b0d12",
  "accent": "auto:${player.thumb}",
  "pageinterval": 15,
  "defaults": {"font": "sans", "size": 18, "color": "#f2f5fa"},
  "pages": [ ... ]
}
```

| Field | Meaning |
|---|---|
| `name` | Name shown in the layout picker |
| `size` | `[width, height]` in pixels, `[480, 320]` for this panel |
| `background` | Background colour of the whole layout |
| `accent` | Accent colour. A fixed colour, or `auto:${...}` to take the most striking colour of that image (typically the cover art). Widgets then use `"color": "accent"` |
| `pageinterval` | Seconds per page for pages without their own `duration` |
| `defaults` | Default `font`, `size` and `color` for text widgets |
| `pages` | List of pages |

---

## 2. Pages

```json
{
  "name": "Music",
  "condition": "audio",
  "duration": 0,
  "priority": 10,
  "background": "#0b0d12",
  "backgroundimage": "${player.thumb}",
  "backgrounddim": 88,
  "widgets": [ ... ]
}
```

| Field | Meaning |
|---|---|
| `name` | Page name (briefly shown when switching manually) |
| `condition` | Visibility condition, see section 6. Without it the page is always eligible |
| `duration` | Seconds to show the page; `0` uses the layout's `pageinterval` |
| `priority` | Higher wins: if any page with `priority: 10` is visible, all lower priority pages are ignored. That is how a playback page hides the clock page |
| `background` | Background colour of this page |
| `backgroundimage` | Background image (path or token), cropped to fill |
| `backgrounddim` | 0-100 %, how much the background image is darkened |
| `widgets` | Widgets in drawing order (later ones are on top) |

When several pages are visible at once, the add-on cycles through them. If the
set of visible pages changes (playback starts, for example), it restarts at the
first one.

---

## 3. Common widget properties

```json
{"type": "text", "x": 20, "y": 30, "w": 200, "h": 24, "condition": "playing"}
```

| Field | Meaning |
|---|---|
| `type` | Widget type, see section 4 |
| `name` | Free text, only used in debug logging |
| `x`, `y` | Top-left corner |
| `w` / `width`, `h` / `height` | Size; without it the widget extends to the right/bottom edge |
| `condition` / `visible` | Condition, see section 6 |
| `opacity` | 0-100 % |

**Positions** may be:

* numbers: `"x": 20`
* percentages: `"x": "50%"` (of the display width/height)
* negative numbers: `"x": -100` measures from the right edge, `"y": -40` from the bottom

**Colours** may be:

* `"#RRGGBB"`, e.g. `"#17b2e2"`
* `"#AARRGGBB"` with alpha, exactly like Kodi skins, e.g. `"#80000000"`
* `"#RGB"` short form
* `"r,g,b"` or `"r,g,b,a"`
* names: `black`, `white`, `red`, `green`, `blue`, `cyan`, `magenta`,
  `yellow`, `orange`, `grey`, `silver`, `dimgrey`, `purple`, `pink`, `lime`,
  `teal`, `brown`, `navy`, `gold`, `kodiblue`, `transparent`
* `"accent"` for the layout's accent colour
* colours may contain tokens

**Fonts**: `sans`, `sans-bold`, `mono`, `mono-bold`, in any pixel size; sizes
that are not bundled are resampled from the nearest one. Extra `.l4f` fonts can
be dropped into the `fonts` folder next to `layouts` (create them with
`tools/mkfont.py`).

---

## 4. Widgets

### `text`

```json
{"type": "text", "x": 20, "y": 24, "w": 440, "h": 34,
 "text": "${player.title}", "size": 26, "bold": true,
 "align": "center", "scroll": "marquee", "shadow": "#000000"}
```

| Field | Default | Meaning |
|---|---|---|
| `text` | – | Text with `${...}` tokens |
| `font` | `defaults.font` | Font family |
| `size` | `defaults.size` | Pixel size |
| `bold` | `false` | Appends `-bold` to the family |
| `color` | `defaults.color` | Text colour |
| `align` | `left` | `left`, `center`, `right` |
| `valign` | `top` | `top`, `middle`/`center`, `bottom` |
| `wrap` | `false` | Word wrap inside the width |
| `lines` | automatic | Maximum number of wrapped lines |
| `linespacing` | `0` | Extra leading |
| `padding` | `0` | Inner padding |
| `background` | – | Colour behind the text |
| `radius` | `0` | Corner radius of that background |
| `scroll` | `none` | `marquee` (endless), `bounce` (back and forth) |
| `scrollspeed` | `30` | Pixels per second |
| `scrollpause` | `2.0` | Pause at both ends for `bounce` |
| `scrollgap` | `40` | Gap between repetitions for `marquee` |
| `shadow` | – | Shadow colour (or `true`) |
| `shadowoffset` | `2` | Shadow offset |
| `outline` | – | Outline colour |
| `showempty` | `false` | Draw even when the text is empty |

Text that does not fit is shortened with `…` unless it scrolls.

### `progress`

```json
{"type": "progress", "x": 20, "y": 260, "w": 440, "h": 12,
 "value": "${player.percent}", "radius": 6, "color": "accent",
 "background": "#1e2330", "knob": true}
```

| Field | Default | Meaning |
|---|---|---|
| `value` | `${player.percent}` | Number or token |
| `min`, `max` | `0`, `100` | Range |
| `orientation` | `horizontal` | `horizontal` or `vertical` (fills upwards) |
| `color` | Kodi blue | Colour of the filled part |
| `gradient` | – | Second colour for a gradient |
| `background` | `#20242e` | Track colour, `null` for none |
| `radius` | `0` | Corner radius |
| `border`, `bordercolor` | `0` | Border width and colour |
| `style` | `bar` | `bar` or `segments` |
| `segments` | `20` | Segment count for `style: segments` |
| `gap` | `2` | Gap between segments |
| `inactivecolor` | – | Colour of segments not reached yet |
| `knob` | `false` | Knob at the current position |
| `knobsize`, `knobcolor` | | Knob size and colour |

### `graph`

Rolling sparkline of a numeric value.

| Field | Default | Meaning |
|---|---|---|
| `value` | – | Token producing a number |
| `min`, `max` | `0`, `100` | Range |
| `points` | `60` | Number of samples kept |
| `interval` | `1.0` | Seconds between samples |
| `color` | Kodi blue | Line colour |
| `fill` | – | Fill colour under the line (use alpha, e.g. `#2217b2e2`) |
| `background` | – | Background colour |
| `thickness` | `1` | Line width |

### `rect`

| Field | Meaning |
|---|---|
| `color` / `fill` | Fill colour |
| `gradient` | Target colour of a gradient |
| `direction` | `vertical` (default) or `horizontal` |
| `radius` | Corner radius |
| `border`, `bordercolor` | Border |

### `line`

| Field | Meaning |
|---|---|
| `color` | Colour |
| `thickness` | Width |
| `x2`, `y2` | End point for a diagonal line |

Without `x2`/`y2` the line fills its own box: a wide flat box gives a
horizontal rule as thick as the box (`"w": 440, "h": 3` is 3 px tall), a tall
narrow one a vertical rule. `thickness` only raises that minimum.

### `circle`

| Field | Meaning |
|---|---|
| `color` | Colour |
| `radius` | Radius; defaults to half the widget size |
| `thickness` | `0` = filled, otherwise ring width |

### `image`

```json
{"type": "image", "x": 18, "y": 18, "w": 180, "h": 180,
 "src": "${player.thumb}", "fit": "cover", "radius": 10}
```

| Field | Default | Meaning |
|---|---|---|
| `src` / `path` | – | File path or token; Kodi `image://` URLs are resolved |
| `fallback` | – | Alternative source when `src` is empty |
| `fit` | `contain` | `contain`, `cover` (fills and crops), `stretch` |
| `radius` | `0` | Rounded corners |
| `align`, `valign` | `center` | Alignment inside the box |
| `opacity` | `100` | Opacity |

PNG and baseline JPEG are supported, progressive JPEG is not. Images are
cached and only decoded again when the source changes.

### `icon`

Vector icons, scalable and tintable.

```json
{"type": "icon", "x": 18, "y": 212, "w": 20, "h": 20, "icon": "play", "color": "accent"}
```

Available: `play`, `pause`, `stop`, `next`, `previous`, `music`, `movie`,
`tv`, `speaker`, `mute`, `clock`, `cpu`, `temp`, `star`, `heart`, `folder`,
`wifi`, `shuffle`, `repeat`, `disc`, `dot`.

The name may be a token, for example `"icon": "${player.mediatype}"` together
with matching icon names.

### `analogclock`

| Field | Default | Meaning |
|---|---|---|
| `face` | – | Dial colour |
| `rim`, `rimwidth` | – | Rim |
| `color` | white | Hour and minute hands |
| `secondcolor` | red | Second hand |
| `ticks` | `true` | Hour ticks |
| `tickcolor` | grey | Tick colour |
| `seconds` | `true` | Show the second hand |

---

## 5. Data fields (tokens)

Tokens are written as `${...}` and work in text, in numeric fields (`value`),
in colours and in conditions.

### Playback - `player.*`

| Token | Content |
|---|---|
| `state` | `playing`, `paused` or `stopped` |
| `mediatype` | `audio`, `video`, `picture`, `none` |
| `playing`, `paused` | `1` or `0` |
| `time`, `time_s` | Elapsed time as `m:ss` and in seconds |
| `duration`, `duration_s` | Total length |
| `remaining`, `remaining_s` | Remaining time |
| `percent` | Progress 0-100 |
| `title`, `artist`, `albumartist`, `album`, `genre`, `year` | Metadata |
| `track`, `discnumber`, `rating` | Music details |
| `showtitle`, `season`, `episode`, `episodelabel`, `plot` | TV details (`episodelabel` gives `S02E05`) |
| `thumb` / `cover` / `art`, `poster`, `fanart` | Artwork sources |
| `codec`, `audiocodec`, `bitrate`, `samplerate`, `channels` | Audio format |
| `resolution`, `aspect` | Video format |
| `next`, `nextartist` | Next item |
| `playlistposition`, `playlistlength` | Position in the playlist |
| `starttime`, `finishtime` | Wall clock start and end |
| `filename`, `path` | File and folder |
| `speed`, `seeking` | Play speed, seeking |

Anything not listed is read as the Kodi InfoLabel `Player.<name>`.

### System - `system.*`

`time`, `time12`, `timesec`, `seconds`, `date`, `date_iso`, `date_short`,
`date_long`, `weekday`, `weekday_short`, `day`, `month`, `monthname`, `year`,
`cpu`, `cputemp`, `gputemp`, `memory`, `memoryfree`, `memorytotal`, `uptime`,
`hostname`, `ip`, `kodiversion`, `buildversion`, `freespace`, `volume`,
`muted`, `screensaver`, `profile`.

Temperature and CPU load are read from `/sys` and `/proc` directly, so they
work on CoreELEC even when Kodi itself reports nothing.

### Others

| Token | Content |
|---|---|
| `weather.temperature`, `weather.conditions`, `weather.location` | Kodi's weather add-on |
| `library.songs`, `library.albums`, `library.artists`, `library.movies`, `library.tvshows`, `library.episodes` | Library counts (refreshed every 5 minutes) |
| `addon.name`, `addon.version` | This add-on |
| `info:<InfoLabel>` | **Any** Kodi InfoLabel, e.g. `${info:MusicPlayer.Album}` |
| `bool:<Condition>` | `1`/`0` for any Kodi boolean condition |

The full InfoLabel list is in the [Kodi wiki](https://kodi.wiki/view/InfoLabels).

### Filters

Filters are appended with `|` and can be chained:

```
${player.title|upper|trunc:20}
${player.time_s|hms}
${player.year|prefix: · }
```

| Filter | Effect |
|---|---|
| `upper`, `lower`, `title`, `capitalize` | Case conversion |
| `strip` | Trim whitespace |
| `trunc:N` | Shorten to N characters with `…` |
| `pad:N` or `pad:N:x` | Right align to N characters |
| `hms` | Seconds as `m:ss` or `h:mm:ss` |
| `hhmmss` | Seconds always as `h:mm:ss` |
| `int` | Drop decimals |
| `round:N` | Round to N decimals |
| `abs` | Absolute value |
| `default:text` | Replacement when empty |
| `prefix:text` | Prepend text, but only when the value is not empty |
| `suffix:text` | Append text, likewise only when not empty |
| `replace:old:new` | Replace |
| `first:sep` | First part, separator defaults to `,` |

`prefix` and `suffix` are handy for separators that should disappear when
there is nothing to separate:
`${player.year}${player.genre|prefix: · }`.

---

## 6. Conditions

`condition` decides whether a page or widget is drawn.

**Add-on states**

| Condition | True when |
|---|---|
| `playing` | Something is playing |
| `paused` | Playback is paused |
| `stopped` / `idle` | Nothing is playing |
| `active` / `hasmedia` | Playing or paused |
| `audio` | Music is playing or paused |
| `video` | Video is playing or paused |
| `screensaver` | Screensaver is active |
| `always` / `never` | Always / never |

**Kodi conditions** - any condition from the Kodi wiki, e.g.
`Player.HasVideo`, `System.HasNetwork`, `Window.IsActive(home)`.

**Comparisons**

```json
"condition": "${player.percent} > 90"
"condition": "${system.cputemp} >= 70"
"condition": "${player.title} contains Live"
```

Operators: `==`, `!=`, `>`, `<`, `>=`, `<=`, ` contains `, ` startswith `,
` endswith `.

**Presence** - a bare token is true when it expands to something non-empty:

```json
"condition": "${player.album}"
```

**Combinations**

* `!` negates: `"!active"`
* `+` is AND: `"audio+playing"`
* `|` is OR: `"audio|video"`

```json
"condition": "video+${player.percent} > 95"
```

---

## 7. Tips

* **After editing** choose *Reload service* from the add-on menu.
* **Layout errors** go to the Kodi log; a widget that raises is skipped and
  the rest of the page is still drawn. Invalid JSON makes the add-on fall
  back to the first layout it finds.
* **Stay cheap**: text and rectangles cost almost nothing, images are decoded
  once when they change, and a background image is cached after the first
  frame.
* **Only changes are transmitted.** A layout without seconds and without
  scrolling text produces virtually no USB traffic while idle.
* **Preview** on a PC:
  `python3 tools/preview.py --layout mine.json --page 0 --out test.png`
* **Test pattern** (menu → *Test pattern*) verifies resolution, rotation and
  byte order: the red frame must touch all four edges and the grey wedge must
  be smooth.
* **Samsung frames**: every frame travels as a complete JPEG, but only what
  changed is re-encoded. Large flat areas are almost free, a full screen photo
  costs the most on the first frame. If it is too slow, lower the *JPEG
  quality*, leave *reduced colour resolution* on and pick a layout without a
  background image.
