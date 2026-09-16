# Settings, actions and troubleshooting

*Add-ons → Program add-ons → LCD4Linux* opens the menu; *Settings* from there,
or the usual context menu on the add-on, opens this dialog.

The dialog hides whatever does not apply: pick a *Display type* and only that
panel's options remain visible.

---

## Display → Connection

| Setting | Meaning |
|---|---|
| Display type | `AX206 USB LCD (AIDA64 type)` or `Samsung SPF photo frame` |
| Output | `USB display`, `Network display (browser or tablet)`, `Preview file only` (writes `preview.png` into the add-on data folder) or `Disabled` |
| USB device IDs | `1908:0102` by default, several separated by commas (AX206) |
| Display number | which panel to use when several are connected |
| Reset USB device when connecting | helps when another program left the panel in a bad state (AX206) |
| Reconnect interval | how long to wait before looking again after the display disappeared (20 s) |
| Start-up grace period | how long after the service starts the display is looked for every few seconds (180 s). For panels that boot slower than Kodi — a Samsung frame needs about half a minute. No "display missing" warning appears during this time |

## Display → Samsung photo frame

| Setting | Meaning |
|---|---|
| Samsung model | `Automatic` takes the frame it finds; pick a model only when several frames are connected |
| JPEG quality | 40–100, default 85. Lower is faster and sends less |
| Reduced colour resolution (4:2:0) | on: faster and smaller. Off: sharper coloured text, about twice the encoding time |

## Display → Picture

| Setting | Meaning |
|---|---|
| Rotation | 0/90/180/270 degrees, for portrait mounting |
| Mirror horizontally | for mirrored mounting |
| Pixel byte order | if the colours come out wrong — see below (AX206) |
| Override display size | only when the panel reports a wrong resolution. In network mode width and height are always editable, since nothing reports a size there |

## Display → Backlight

| Setting | Applies to | Meaning |
|---|---|---|
| Brightness | AX206 | Backlight level 0–7 |
| Brightness (software) | Samsung, network | 10–100%, the picture is darkened before sending |
| Dim while idle | both | Dims whenever nothing is playing. Paused still counts as playing |
| Idle brightness | AX206 | Backlight level while idle |
| Idle brightness (software) | Samsung, network | 0–100%; 0% is a black picture |
| Clear the display when Kodi stops | both | Black picture on shutdown |

Samsung frames and browsers have no backlight to control, so there the picture
is darkened rather than the lamp dimmed. It costs no extra CPU time — the
darkening lives in the JPEG encoder's colour tables.

## Layout

Active layout, the chooser, a user layout folder, the page interval, and the
buttons *Preview current layout*, *Show test pattern*, *Display status* and
*Reload service*.

*Choose layout…* shows a preview image per design without closing the
settings. Bundled images ship as `resources/thumbs/<design>.png`; layouts from
your own folder are rendered once on first use and cached in
`<addon data>/thumbs/`. The three sizes of one design (`default.json`,
`default-800x480.json`, `default-1024x600.json`) appear as a single entry,
because loading picks the right one anyway.

## Layout → Web editor

| Setting | Meaning |
|---|---|
| Layout editor in the browser | switches the web server on and off (default on) |
| Open the web editor | shows the address it is reachable at |
| Port | 8050 by default |
| Reachable from | `the whole network`, or `this box only` for a browser on the box itself |
| Password | empty means no prompt; otherwise any user name plus this password |

## Behaviour

Frame rate while playing and while idle, smooth image scaling, Kodi
notifications on the display, debug logging, and the **power hooks** that run a
shell command when the service starts and stops — see
[SETUP.md](SETUP.md#switching-the-frame-on-and-off).

## Language

Nothing to set: the add-on follows Kodi. Settings, on-screen messages, bundled
layouts and the names of weekdays and months exist in English and German. For
your own layouts see *Translating fixed words* in [LAYOUT.md](LAYOUT.md).

---

## Controlling it from Kodi

Bind any of these to a key, a favourite or a skin button:

```
RunScript(script.lcd4linux,next_page)        # next page
RunScript(script.lcd4linux,layout)           # choose layout
RunScript(script.lcd4linux,preview)          # show preview
RunScript(script.lcd4linux,test_pattern)     # test pattern
RunScript(script.lcd4linux,status)           # display status
RunScript(script.lcd4linux,reload)           # reload service
RunScript(script.lcd4linux,brightness_up)    # brighter
RunScript(script.lcd4linux,brightness_down)  # darker
```

Another add-on can push a message onto the display:

```python
xbmc.executeJSONRPC(json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "JSONRPC.NotifyAll",
    "params": {"sender": "script.lcd4linux", "message": "message",
               "data": {"heading": "Doorbell", "message": "Someone is here"}}}))
```

---

## Troubleshooting

**Nothing happens, or "No AX206 display found"**
Check `lsusb | grep 1908`. No device means cable, power, or a panel still on
its original firmware. *Display status* in the menu shows what the service
sees.

**Colours wrong, red and blue swapped, garbled picture**
Switch *Pixel byte order*. The default is "High byte first"; some panel
variants want the other one.

**Picture shifted or cut off**
Show the *test pattern*: the red frame must touch all four edges. If it does
not, enable *Override display size* and enter the real resolution.

**Stuttering, high CPU load**
Lower *Updates per second while playing* — 2 is usually plenty. Switch off
*Smooth image scaling*, or use `minimal.json`, which uses no images at all. On
a Samsung, also lower the *JPEG quality*; layouts with large flat areas encode
far faster than one with a full-screen background photo.

**Samsung: the frame stays in mass storage mode**
The log says "the frame stayed in USB mass storage mode". The add-on retries by
itself; if that does not help, unplug and replug the frame. Some models only
switch when they are powered on and not running a slideshow.

**Samsung: the picture freezes**
Without the keep-alive the frame drops out of monitor mode. The add-on sends it
after every frame, and it keeps sending frames even when nothing changes — a
clock without seconds still transmits, just to keep the frame awake.

**The display stays on after Kodi exits**
Enable *Clear the display when Kodi stops*.

**Reading the log**
Turn on *Debug logging*; messages appear in `kodi.log` prefixed with
`[script.lcd4linux]`.

**Checking the installation** — fonts, image decoders, protocol and every
layout, on the box or on a PC:

```sh
python3 /storage/.kodi/addons/script.lcd4linux/tools/selftest.py
```

---

## What a frame costs on a Samsung

The frame only accepts complete JPEG images, so the add-on re-encodes only the
block rows that changed. Measured on a desktop at 800×480, quality 85 — an
Amlogic box is roughly 4–6× slower:

| Layout | First frame | Ongoing | JPEG size |
|---|---|---|---|
| `minimal-800x480` | 113 ms | 9 ms | 23 kB |
| `dashboard-800x480` | 137 ms | 30 ms | 27 kB |
| `default-800x480` | 166 ms | 22 ms | 38 kB |
| `bigcover-800x480` | 168 ms | 12 ms | 28 kB |

A full-frame image costs most on the first frame; after that only the rows with
the clock and the progress bar are left. On a slow box, `minimal` is the
cheapest choice.
