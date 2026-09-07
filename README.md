# LCD4Linux für CoreELEC / Kodi

Kodi-Add-on für die 3,5" USB-Displays mit **AX206**-Controller (480×320) – also
die Panels, die als **AIDA64-Displays**, „SmartDisplay" oder „USB Mini Screen"
verkauft werden und aus den Projekten
[dpf-ax](http://dpf-ax.sourceforge.net/) und
[lcd4linux](https://lcd4linux.bulix.org/) bekannt sind.

Das Add-on zeigt, was Kodi gerade abspielt – Titel, Interpret, Album, Cover,
Fortschrittsbalken mit gespielter und verbleibender Zeit – dazu Uhr,
CPU-Auslastung, Temperatur, Bibliotheksdaten und alles andere, was Kodi kennt.
**Der komplette Bildschirminhalt wird über JSON-Layoutdateien beschrieben** und
kann frei angepasst werden.

![Musikwiedergabe](resources/screenshots/default-music.png)
![Videowiedergabe](resources/screenshots/default-video.png)
![Großes Cover](resources/screenshots/bigcover.png)
![Dashboard](resources/screenshots/dashboard.png)

---

## Eigenschaften

* **Direkter USB-Zugriff** auf den AX206 über `libusb` (ctypes) – keine
  zusätzlichen Python-Module, kein `pyusb`, kein Compiler nötig.
* **Nur geänderte Bildbereiche** werden übertragen. Ein tickender
  Sekundenzeiger kostet ein paar hundert Bytes statt 300 kB pro Bild.
* **Frei anpassbare Layouts** als JSON: Seiten, Widgets, Positionen, Farben,
  Schriftgrößen, Bedingungen und Datenquellen.
* **Alle Kodi-InfoLabels** sind verwendbar (`${info:MusicPlayer.Album}`),
  ebenso alle Kodi-Bedingungen (`Player.HasVideo`).
* **Mehrere Seiten** mit Bedingungen und automatischem Wechsel
  (z. B. Musik-, Video-, Uhr- und Systemseite).
* **Widgets**: Text (mit Lauftext, Umbruch, Schatten), Fortschrittsbalken
  (Balken/Segmente, waagerecht/senkrecht, mit Knopf), Verlaufsdiagramm,
  Rechteck, Linie, Kreis, Bild, Symbol, Analoguhr.
* **Cover und Fanart** werden angezeigt – PNG- und JPEG-Dekoder sind im Add-on
  enthalten und laufen ohne Pillow/ffmpeg.
* **Weichgezeichnete Schriften** (DejaVu, vorgerendert) in jeder Größe.
* **Drehung** um 0/90/180/270 Grad, Spiegelung, einstellbare Byte-Reihenfolge.
* **Hintergrundbeleuchtung** dimmt beim Bildschirmschoner und schaltet bei
  Inaktivität ab.
* **Vorschau ohne Hardware**: Layouts lassen sich als PNG rendern.

---

## Installation

1. Repository als ZIP herunterladen (`Code → Download ZIP`) oder ein Release
   verwenden. Der Ordner im ZIP muss `script.lcd4linux` heißen.
2. Kodi → *Add-ons* → *Aus ZIP-Datei installieren* → ZIP auswählen.
3. Display anstecken. Der Dienst startet automatisch und sucht das Panel.
4. *Add-ons → Programm-Add-ons → LCD4Linux* öffnet das Menü
   (Layout wählen, Testbild, Status, Einstellungen).

Alternativ direkt auf die Box kopieren:

```sh
cd /storage/.kodi/addons
git clone https://github.com/CE-Repo/script.lcd4linux.git
systemctl restart kodi
```

### Hardware

| | |
|---|---|
| Controller | AX206 (mit dpf-ax-Firmware) |
| USB-ID | `1908:0102` |
| Auflösung | wird vom Display gemeldet, typisch 480×320 |
| Farbformat | RGB565, höherwertiges Byte zuerst |

Ob das Display erkannt wird, zeigt auf der Box:

```sh
lsusb | grep 1908
```

CoreELEC lädt für dieses Gerät kein `usb-storage`-Modul, das den Zugriff
blockieren würde; sollte doch ein Kerneltreiber daran hängen, löst das Add-on
ihn selbst ab. Kodi läuft auf CoreELEC als `root`, zusätzliche udev-Regeln sind
daher nicht nötig.

---

## Einstellungen

**Anzeige → Verbindung**

| Einstellung | Bedeutung |
|---|---|
| Ausgabe | `AX206-USB-Display`, `Nur Vorschaudatei` (schreibt `preview.png` in den Add-on-Datenordner) oder `Deaktiviert` |
| USB-Geräte-IDs | Standard `1908:0102`, mehrere durch Komma getrennt |
| Displaynummer | wenn mehrere Panels angeschlossen sind |
| USB-Gerät zurücksetzen | hilft, wenn ein anderes Programm das Display hängen ließ |
| Wiederverbindungsintervall | Wartezeit, bis nach einem abgezogenen Display erneut gesucht wird |

**Anzeige → Bild**

| Einstellung | Bedeutung |
|---|---|
| Drehung | 0/90/180/270 Grad, für Hochkant-Montage |
| Horizontal spiegeln | für Spiegelmontage |
| Byte-Reihenfolge | falls die Farben falsch sind – siehe *Fehlersuche* |
| Displaygröße überschreiben | nur nötig, wenn das Panel eine falsche Auflösung meldet |

**Anzeige → Hintergrundbeleuchtung**

Helligkeit 0–7, Dimmen beim Bildschirmschoner, Abschalten bei Inaktivität,
Display beim Beenden von Kodi löschen.

**Layout**

Aktives Layout, Layout-Auswahl, eigener Layout-Ordner, Seitenwechselintervall
sowie die Aktionsknöpfe *Vorschau*, *Testbild*, *Anzeigestatus* und
*Dienst neu laden*.

**Verhalten**

Bildwiederholrate bei Wiedergabe und im Leerlauf, weiche Bildskalierung,
Kodi-Benachrichtigungen auf dem Display, Debug-Protokollierung.

---

## Mitgelieferte Layouts

| Datei | Beschreibung |
|---|---|
| `default.json` | Vier Seiten: Musik (mit Cover), Video (mit Poster), Uhr, Systemwerte |
| `bigcover.json` | Bildschirmfüllendes Cover mit Infoleiste unten |
| `minimal.json` | Große Schrift, Segment-Fortschrittsbalken, keine Bilder – sehr sparsam |
| `dashboard.json` | Analoguhr, CPU, Temperatur, RAM und Verlaufsdiagramm |

---

## Eigene Layouts

Layouts liegen in

```
/storage/.kodi/userdata/addon_data/script.lcd4linux/layouts/
```

Dateien in diesem Ordner haben Vorrang vor den mitgelieferten – eine eigene
`default.json` dort überschreibt also die Vorlage, ohne dass ein Update sie
löscht. Beim ersten Start legt das Add-on dort `custom.json.example` als
Startpunkt ab: umbenennen in `meins.json`, anpassen, im Menü auswählen.

Kurzbeispiel:

```json
{
  "name": "Mein Layout",
  "size": [480, 320],
  "background": "#101317",
  "defaults": {"font": "sans", "size": 18, "color": "#ffffff"},
  "pages": [
    {
      "name": "Wiedergabe",
      "condition": "active",
      "widgets": [
        {"type": "text", "x": 20, "y": 24, "w": 440, "h": 40,
         "text": "${player.title}", "size": 30, "bold": true,
         "scroll": "marquee"},
        {"type": "text", "x": 20, "y": 70, "w": 440, "h": 28,
         "text": "${player.artist}", "size": 20, "color": "#17b2e2"},
        {"type": "progress", "x": 20, "y": 260, "w": 440, "h": 12,
         "value": "${player.percent}", "radius": 6, "color": "#17b2e2"},
        {"type": "text", "x": 20, "y": 280, "w": 200, "h": 24,
         "text": "${player.time} / ${player.duration}", "font": "mono"}
      ]
    }
  ]
}
```

Die vollständige Referenz – alle Widgets, Eigenschaften, Datenfelder, Filter
und Bedingungen – steht in **[docs/LAYOUT.de.md](docs/LAYOUT.de.md)**
(English: [docs/LAYOUT.en.md](docs/LAYOUT.en.md)).

### Layout ohne Hardware entwerfen

Auf dem PC (Python 3 genügt, kein Kodi):

```sh
python3 tools/preview.py --layout resources/layouts/default.json --page 0 --out vorschau.png
python3 tools/preview.py --track 1 --page 1 --out video.png     # Video-Demodaten
python3 tools/preview.py --rotate 90 --out hochkant.png
```

Auf der Box ohne Display: Einstellung *Ausgabe* auf **Nur Vorschaudatei**
stellen – jedes Bild landet dann als `preview.png` im Add-on-Datenordner. Im
Menü zeigt *Layout-Vorschau* das aktuelle Layout direkt in Kodi an.

---

## Steuerung aus Kodi heraus

Die Aktionen lassen sich auf Tasten, Favoriten oder Skin-Knöpfe legen:

```
RunScript(script.lcd4linux,next_page)        # nächste Seite
RunScript(script.lcd4linux,layout)           # Layout auswählen
RunScript(script.lcd4linux,preview)          # Vorschau anzeigen
RunScript(script.lcd4linux,test_pattern)     # Testbild
RunScript(script.lcd4linux,status)           # Anzeigestatus
RunScript(script.lcd4linux,reload)           # Dienst neu laden
RunScript(script.lcd4linux,brightness_up)    # heller
RunScript(script.lcd4linux,brightness_down)  # dunkler
```

Andere Add-ons können eine Meldung auf das Display schicken:

```python
xbmc.executeJSONRPC(json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "JSONRPC.NotifyAll",
    "params": {"sender": "script.lcd4linux", "message": "message",
               "data": {"heading": "Türklingel", "message": "Besuch da"}}}))
```

---

## Fehlersuche

**Nichts passiert / „Kein AX206-Display gefunden"**
`lsusb | grep 1908` prüfen. Erscheint das Gerät nicht, liegt es an Kabel,
Stromversorgung oder daran, dass das Panel noch die Original-Firmware hat.
Der Menüpunkt *Anzeigestatus* zeigt, was der Dienst sieht.

**Farben falsch, Rot und Blau vertauscht, verrauschtes Bild**
Einstellung *Byte-Reihenfolge* umschalten. Standard ist
„Höherwertiges Byte zuerst"; einzelne Panel-Varianten erwarten die andere
Reihenfolge.

**Bild verschoben oder abgeschnitten**
*Testbild* anzeigen lassen: Der rote Rahmen muss alle vier Kanten berühren.
Passt das nicht, *Displaygröße überschreiben* aktivieren und die tatsächliche
Auflösung eintragen.

**Ruckelnde Anzeige, hohe CPU-Last**
*Aktualisierungen pro Sekunde bei Wiedergabe* verringern (2 reicht meist),
*Bilder weich skalieren* abschalten oder `minimal.json` verwenden, das ohne
Bilder auskommt.

**Display bleibt nach dem Beenden von Kodi an**
*Display beim Beenden von Kodi löschen* aktivieren.

**Protokoll**
*Debug-Protokollierung* einschalten; die Meldungen stehen mit dem Präfix
`[script.lcd4linux]` in `kodi.log`.

**Selbsttest** – prüft Schriften, Bilddekoder, Protokoll und alle Layouts,
auch direkt auf der Box:

```sh
python3 /storage/.kodi/addons/script.lcd4linux/tools/selftest.py
```

---

## Aufbau

```
addon.xml                     Add-on-Manifest
service.py                    Dienst (läuft im Hintergrund)
default.py                    Menü / Aktionen
resources/settings.xml        Einstellungsdialog
resources/layouts/*.json      mitgelieferte Layouts
resources/fonts/*.l4f         vorgerenderte Bitmap-Schriften
resources/lib/lcd4linux/
    usbdev.py                 libusb-1.0 über ctypes
    ax206.py                  AX206-Protokoll (SCSI über USB)
    display.py                Ausgabeziele, Drehung, Teilaktualisierung
    canvas.py                 RGB565-Framebuffer und Zeichenprimitive
    bmfont.py                 Bitmap-Schriften
    pngio.py / jpegio.py      Bilddekoder in reinem Python
    images.py                 Laden, Skalieren, Sprites
    layout.py                 Layoutdateien, Seiten, Renderer
    widgets.py                Widgets
    tokens.py                 ${...}-Ersetzung, Filter, Bedingungen
    kodidata.py               Datenquellen (Kodi, System, Demo)
    settings.py               Einstellungen
    service.py                Hauptschleife
    ui.py                     Menü
tools/preview.py              Layout-Vorschau als PNG
tools/selftest.py             Selbsttest ohne Hardware
tools/mkfont.py               Schriften neu erzeugen (benötigt Pillow)
```

---

## English summary

Kodi/CoreELEC add-on for the 3.5" 480×320 USB LCD panels based on the **AX206**
controller – the displays sold as AIDA64 screens and known from the `dpf-ax`
and `lcd4linux` projects.

It shows what Kodi is playing (title, artist, album, cover art, a progress bar
with elapsed and remaining time) plus clock, CPU load, temperature and any Kodi
InfoLabel. Everything on screen is defined by JSON layout files, so pages,
widgets, colours, fonts, positions and data sources are fully customisable.

USB access uses `libusb` through `ctypes`; the PNG/JPEG decoders and the font
renderer are part of the add-on, so **no extra Python modules are required**.
Only the changed part of each frame is sent to the panel.

* Layout reference: [docs/LAYOUT.en.md](docs/LAYOUT.en.md)
* Design layouts without hardware: `python3 tools/preview.py --out preview.png`
* Verify an installation: `python3 tools/selftest.py`
* Settings, bundled layouts, remote-control actions and troubleshooting are
  described in the German sections above; the add-on's own user interface is
  available in English and German.

---

## Lizenz

MIT – siehe [LICENSE](LICENSE).

Die mitgelieferten Schriften stammen aus den
[DejaVu-Fonts](https://dejavu-fonts.github.io/) (Bitstream-Vera-Lizenz), siehe
[resources/fonts/LICENSE-DejaVu.txt](resources/fonts/LICENSE-DejaVu.txt).

Das AX206-Protokoll folgt den Projekten `dpf-ax` und dem AX206-Treiber von
`lcd4linux` (`drv_dpf.c`).
