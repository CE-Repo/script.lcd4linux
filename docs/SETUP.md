# Setup

Three kinds of output. Pick one under *Settings → Display → Connection →
Output*, and for a USB panel also set *Display type* — the two panel families
speak completely different protocols.

Kodi runs as `root` on CoreELEC, so neither display needs udev rules. If a
kernel driver has claimed the device, the add-on detaches it.

---

## AX206 (AIDA64 type)

| | |
|---|---|
| Controller | AX206 with the dpf-ax firmware |
| USB ID | `1908:0102` |
| Resolution | reported by the panel, typically 480×320 |
| Transfer | raw RGB565, changed rectangle only |
| Brightness | 8 backlight levels, driven by the add-on |

Plug it in and check that the box sees it:

```sh
lsusb | grep 1908
```

If nothing shows up, it is the cable, the power, or a panel still running its
original firmware — these displays need the dpf-ax firmware flashed.

That is the whole setup; the defaults are correct for this panel.

---

## Samsung SPF photo frames

| | |
|---|---|
| Models | SPF-72H, SPF-75H/76H, SPF-83H/83M, SPF-85H/85P, SPF-86H/86P, SPF-87H, SPF-105P, SPF-107H, SPF-700T, SPF-800P, SPF-1000P |
| USB ID | `04e8:200a` (mass storage) → `04e8:200b` (monitor), varies by model |
| Resolution | 800×480, 800×600 or 1024×600 depending on the model |
| Transfer | a complete JPEG per frame — no partial updates |
| Brightness | **not** controllable over USB; the picture is darkened instead |

### Connecting it

1. **Connect the frame's own power supply.** A 7" frame draws more current
   than a USB port may deliver — it will not run off the USB cable alone.
2. **USB cable into the frame's *upstream* port** (the manual calls it the
   "up stream terminal", the one for connecting a PC). The host port next to
   it, for memory sticks, does not work for this. Use the supplied cable if
   you still have it.
3. **Other end into a USB 2.0 port on the box**, without a hub if you can
   avoid one.
4. **Switch the frame on.** If it asks for an operating mode on screen
   ("Mass Storage" / "Mini Monitor" / slideshow), pick **Mini Monitor** once.
   If it does not ask, the add-on switches it over itself.
5. Check on the box — `04e8:200a` means it has not switched yet, `04e8:200b`
   means it is in monitor mode:

   ```sh
   lsusb | grep 04e8
   ```

   The menu entry *Display status* says the same thing in plain words.
6. Set *Display type* to **Samsung SPF photo frame**, then *Reload service*.

### The mode switch

The frame first appears as a USB mass storage device. The add-on sends the
switch request itself — the frame drops off the bus for one to three seconds
and returns with a new product ID. This happens on every power-up.
`usb_modeswitch` is not needed.

A frame typically takes about half a minute longer to boot than Kodi, so the
service starts without a display, looks for it every few seconds during the
*Start-up grace period* (180 s by default), repeats the switch request for as
long as the frame reports itself as a drive, and rebuilds the layout once the
frame reports its real resolution. No manual restart needed.

### Switching the frame on and off

The honest version first: **the mini monitor protocol has no command for
brightness or for power.** The frame only accepts pictures.

| | |
|---|---|
| Kodi starts | The frame is switched to monitor mode and the picture appears — automatic |
| Brightness | The add-on darkens the **picture** (*Brightness (software)*, *Idle brightness (software)*). The backlight itself is untouched |
| Kodi shuts down | The add-on sends a **black picture** (*Clear the display when Kodi stops*). The backlight stays on |
| After that | Without the keep-alive the frame drops back into its own slideshow |
| Genuinely off | Only by **cutting the power** — no USB command can do it |

For genuinely off, put the frame's power supply on a switchable socket and let
*Settings → Behaviour → Power hooks* switch it along:

| Setting | When it runs |
|---|---|
| Command when the service starts | **before** the display is opened — so, switch on |
| Command when the service stops | **after** the USB connection is released — so, switch off |

```sh
# Tasmota / Shelly over HTTP
curl -s "http://192.168.1.50/cm?cmnd=Power%20On"
curl -s "http://192.168.1.50/cm?cmnd=Power%20Off"

# Home Assistant
curl -s -X POST -H "Authorization: Bearer TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"entity_id":"switch.photo_frame"}' \
     http://192.168.1.10:8123/api/services/switch/turn_on

# MQTT
mosquitto_pub -h 192.168.1.10 -t cmnd/frame/POWER -m ON
```

Two caveats. The frame needs a few seconds to appear on the bus after power
comes back — not a problem, the add-on retries every *Reconnect interval*
(20 s by default; drop it to 5 s if you are impatient). And whether the frame
powers up by itself or wants a button press depends on the model, so try it
once. Many SPF models start automatically when power is applied, and some have
an auto on/off schedule in their own menu.

**Without a switchable socket** the compromise is *Dim while idle* with *Idle
brightness (software)* at 0%: a black picture instead of the frame's
slideshow, for as long as the box is running.

---

## Network display (browser or tablet)

Instead of a USB panel, the add-on serves its frames over its own web
interface to any browser in full screen.

| | |
|---|---|
| Hardware | anything with a browser — tablet, phone, old laptop, second monitor |
| Resolution | free, set under *Display → Picture* |
| Transfer | MJPEG over HTTP; a full JPEG per frame, with only changed block rows re-encoded |
| Brightness | in software, the picture is darkened before it is sent |

Set *Output* to **Network display (browser or tablet)**. In this mode the HTTP
server always runs, regardless of the switch for the layout editor — here it
*is* the display. The address appears in the menu under *Display status* and
*Web editor*:

```
http://<box>:8050/display
```

| Address | Serves |
|---|---|
| `/display` | the full-screen page for the tablet |
| `/display?fit=fill` | the same, stretched to the whole screen instead of letterboxed |
| `/display/stream` | the raw MJPEG stream |
| `/display/frame.jpg` | the current frame as a single file |

If a web interface password is set it is appended as `?key=<password>`, on
purpose: a kiosk browser cannot answer a Basic auth challenge for an `<img>`.
The editor itself stays behind Basic auth.

The page is deliberately tiny — one `<img>` fed by a
`multipart/x-mixed-replace` stream, no WebSocket, no canvas — which is exactly
why it runs on the ancient WebKit of an Android 4.4 tablet. Its only
JavaScript reconnects when the box restarts; without JavaScript the page still
shows pictures.

**Bandwidth:** 800×480 at quality 85 is about 28 kB per frame, so roughly
0.2 Mbit/s while idling at one frame per second.

**Resolution:** the bundled layouts come in 480×320, 800×480 and 1024×600. Set
a 1280×800 tablet to one of those and let the browser scale up, or render
natively and convert the layouts with `tools/scale_layout.py`.

### Setting up the tablet

An Android tablet **cannot** be booted remotely, and auto-boot on the charger
needs root and does not work everywhere. So the tablet stays on and only its
**screen** goes on and off.

1. Install a kiosk browser — *Fully Kiosk Browser* (Android 4.4 and up) or the
   open source *WallPanel*.
2. Point it at the `/display` address as its start page.
3. Enable "keep screen on" and switch off the screensaver.
4. Under *Settings → Behaviour → Power hooks* in Kodi:

```sh
# Command when the service starts - screen on
curl -s --max-time 3 "http://192.168.1.60:2323/?cmd=screenOn&password=SECRET"

# Command when the service stops - screen off
curl -s --max-time 3 "http://192.168.1.60:2323/?cmd=screenOff&password=SECRET"
```

The `--max-time` matters: the start command runs *before* the display is
opened and would otherwise stall the service start until the *Command timeout*
(15 s) whenever the tablet is off the Wi-Fi.

To keep the tablet at full brightness while idle, switch off *Dim while idle*
or set *Idle brightness (software)* to 100%. On shutdown the add-on sends a
black picture before the power hook fires, so a browser left open does not
freeze on the last frame.

**On continuous operation:** old Li-ion batteries like to swell on a permanent
charger. With a wall-mounted tablet, check the back occasionally.
