# LCD4Linux für CoreELEC / Kodi

Kodi-Add-on für zwei Familien von USB-Displays:

* die 3,5" Panels mit **AX206**-Controller (480×320) – als **AIDA64-Displays**,
  „SmartDisplay" oder „USB Mini Screen" verkauft und aus den Projekten
  [dpf-ax](http://dpf-ax.sourceforge.net/) und
  [lcd4linux](https://lcd4linux.bulix.org/) bekannt;
* die **Samsung-SPF-Bilderrahmen** (SPF-72H, SPF-87H, SPF-107H und Verwandte,
  800×480 bis 1024×600) im „Mini-Monitor"-Modus.

Das Add-on zeigt, was Kodi gerade abspielt – Titel, Interpret, Album, Cover,
Fortschrittsbalken mit gespielter und verbleibender Zeit – dazu Uhr,
CPU-Auslastung, Temperatur, Bibliotheksdaten und alles andere, was Kodi kennt.
**Der komplette Bildschirminhalt wird über JSON-Layoutdateien beschrieben** und
kann frei angepasst werden.

![Musikwiedergabe](resources/screenshots/default-music.png)
![Videowiedergabe](resources/screenshots/default-video.png)
![Großes Cover](resources/screenshots/bigcover.png)
![Dashboard](resources/screenshots/dashboard.png)

Und auf dem 800×480-Rahmen:

![Samsung Musik](resources/screenshots/spf-music.png)
![Samsung Dashboard](resources/screenshots/spf-dashboard.png)

---

## Eigenschaften

* **Direkter USB-Zugriff** über `libusb` (ctypes) – keine zusätzlichen
  Python-Module, kein `pyusb`, kein Compiler nötig.
* **Nur geänderte Bildbereiche** werden übertragen. Beim AX206 kostet ein
  tickender Sekundenzeiger ein paar hundert Bytes statt 300 kB pro Bild; beim
  Samsung werden nur die geänderten JPEG-Blockzeilen neu kodiert.
* **Frei anpassbare Layouts** als JSON: Seiten, Widgets, Positionen, Farben,
  Schriftgrößen, Bedingungen und Datenquellen.
* **Layout-Baukasten im Browser**: Elemente mit der Maus setzen, ziehen und
  in der Größe ändern, mit einer Vorschau, die derselbe Renderer zeichnet wie
  das Display – vom Handy, Tablet oder PC im Netzwerk aus.
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
* **Hintergrundbeleuchtung** dimmt, solange nichts abgespielt wird – beim
  AX206 über die Beleuchtung, beim Samsung-Rahmen softwareseitig.
* **Deutsch und Englisch** auf dem Display: die mitgelieferten Layouts, die
  Seitennamen sowie Wochentage und Monate folgen der Sprache von Kodi. Eigene
  Layouts können mit `$LOCALIZE[...]` dasselbe tun.
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

### Unterstützte Hardware

Der **Displaytyp** wird in den Einstellungen gewählt – die beiden Familien
sprechen völlig verschiedene Protokolle.

#### AX206 (AIDA64-Typ)

| | |
|---|---|
| Controller | AX206 (mit dpf-ax-Firmware) |
| USB-ID | `1908:0102` |
| Auflösung | wird vom Display gemeldet, typisch 480×320 |
| Übertragung | rohe RGB565-Pixel, nur der geänderte Ausschnitt |
| Helligkeit | 8 Stufen, vom Add-on steuerbar |

```sh
lsusb | grep 1908
```

#### Samsung SPF

| | |
|---|---|
| Modelle | SPF-72H, SPF-75H/76H, SPF-83H/83M, SPF-85H/85P, SPF-86H/86P, SPF-87H, SPF-105P, SPF-107H, SPF-700T, SPF-800P, SPF-1000P |
| USB-ID | `04e8:200a` (Massenspeicher) → `04e8:200b` (Monitor), je nach Modell |
| Auflösung | 800×480 (SPF-72H), 800×600 oder 1024×600 je nach Modell |
| Übertragung | vollständiges JPEG pro Bild, kein Teilbereich möglich |
| Helligkeit | **nicht** über USB steuerbar – das Add-on dunkelt stattdessen das Bild ab |

```sh
lsusb | grep 04e8
```

Der Rahmen meldet sich zunächst als USB-Massenspeicher. Das Add-on schickt die
Umschaltanforderung selbst, der Rahmen verschwindet dann kurz vom Bus und
kommt mit einer neuen Produkt-ID im Monitor-Modus zurück – das dauert ein bis
drei Sekunden und passiert bei jedem Einschalten neu. `usb_modeswitch` wird
nicht benötigt.

##### Anschluss Schritt für Schritt

1. **Netzteil des Rahmens anschließen.** Ein 7"-Rahmen zieht mehr Strom, als
   ein USB-Port liefern darf – das mitgelieferte Netzteil ist Pflicht, der
   Rahmen läuft nicht über das USB-Kabel allein.
2. **USB-Kabel in den *Upstream*-Anschluss des Rahmens** (im Handbuch
   „up stream terminal", der Anschluss für die PC-Verbindung). Der Rahmen hat
   daneben noch einen USB-Host-Anschluss für Sticks – der funktioniert dafür
   nicht. Am besten das mitgelieferte Kabel verwenden.
3. **Anderes Ende an einen USB-2.0-Port der CoreELEC-Box.** Kein USB-Hub
   dazwischen, wenn es sich vermeiden lässt.
4. **Rahmen einschalten.** Fragt er auf dem Bildschirm nach der Betriebsart
   („Mass Storage" / „Mini Monitor" / Diashow), einmal **Mini Monitor**
   auswählen. Bleibt die Abfrage aus, macht das Add-on die Umschaltung selbst.
5. Auf der Box prüfen:

   ```sh
   lsusb | grep 04e8
   ```

   `04e8:200a` = Massenspeicher-Modus (noch nicht umgeschaltet),
   `04e8:200b` = Monitor-Modus (fertig). Im Add-on-Menü zeigt
   *Anzeigestatus* dasselbe im Klartext.
6. Im Add-on: *Einstellungen → Anzeige → Verbindung → Displaytyp* auf
   **Samsung-SPF-Bilderrahmen** stellen, dann *Dienst neu laden*.

##### Ein- und Ausschalten mit CoreELEC

Ehrliche Einordnung vorweg: **Das Mini-Monitor-Protokoll kennt keinen Befehl
für Helligkeit oder Ausschalten.** Der Rahmen nimmt ausschließlich Bilder
entgegen. Was das Add-on kann und was nicht:

| | |
|---|---|
| Beim Start von Kodi | Rahmen wird in den Monitor-Modus geschaltet, Bild erscheint – das läuft automatisch |
| Helligkeit | Das Add-on dunkelt das **Bild** ab (Einstellungen *Helligkeit (Software)* und *Helligkeit im Leerlauf (Software)*). Die Hintergrundbeleuchtung selbst bleibt unverändert |
| Beim Herunterfahren | Das Add-on zeigt ein **schwarzes Bild** (Einstellung *Display beim Beenden von Kodi löschen*). Die Hintergrundbeleuchtung bleibt an |
| Danach | Ohne Keep-Alive fällt der Rahmen nach kurzer Zeit in seine eigene Diashow zurück |
| Wirklich aus | Nur durch **Stromtrennung** – das kann kein USB-Befehl |

Für „wirklich aus" hängt man das Netzteil des Rahmens an eine schaltbare
Steckdose und lässt das Add-on sie mitschalten. Dafür gibt es
*Einstellungen → Verhalten → Schaltbefehle*:

| Einstellung | Wann |
|---|---|
| Befehl beim Start des Dienstes | läuft, **bevor** das Display geöffnet wird – also zum Einschalten |
| Befehl beim Beenden des Dienstes | läuft, **nachdem** die USB-Verbindung freigegeben wurde – also zum Ausschalten |

Beispiele, je nach Steckdose:

```sh
# Tasmota / Shelly per HTTP
curl -s "http://192.168.1.50/cm?cmnd=Power%20On"
curl -s "http://192.168.1.50/cm?cmnd=Power%20Off"

# Home Assistant
curl -s -X POST -H "Authorization: Bearer TOKEN"      -H "Content-Type: application/json"      -d '{"entity_id":"switch.bilderrahmen"}'      http://192.168.1.10:8123/api/services/switch/turn_on

# MQTT
mosquitto_pub -h 192.168.1.10 -t cmnd/rahmen/POWER -m ON
```

Zwei Dinge dazu:

* Der Rahmen braucht nach dem Einschalten einige Sekunden, bis er am USB-Bus
  erscheint. Das ist kein Problem – das Add-on sucht ihn im Abstand von
  *Wiederverbindungsintervall* (Standard 20 s) erneut und verbindet sich dann
  von selbst. Wer es eiliger hat, stellt den Wert auf 5 s.
* Ob der Rahmen nach dem Wiedereinschalten von allein hochfährt oder eine
  Taste braucht, hängt vom Gerät ab – einmal ausprobieren. Viele SPF gehen bei
  anliegendem Strom automatisch an; manche haben zusätzlich einen
  Auto-Ein/Aus-Zeitplan im eigenen Menü.

Ohne schaltbare Steckdose bleibt als Kompromiss: *Während des Leerlaufs
dimmen* aktivieren und *Helligkeit im Leerlauf (Software)* auf 0 % stellen –
dann zeigt der Rahmen ein schwarzes Bild, statt in die Diashow zu wechseln,
solange die Box läuft.

Kodi läuft auf CoreELEC als `root`, zusätzliche udev-Regeln sind für beide
Displays nicht nötig. Hängt ein Kerneltreiber am Gerät, löst das Add-on ihn ab.

---

## Einstellungen

**Anzeige → Verbindung**

| Einstellung | Bedeutung |
|---|---|
| Ausgabe | `USB-Display`, `Nur Vorschaudatei` (schreibt `preview.png` in den Add-on-Datenordner) oder `Deaktiviert` |
| USB-Geräte-IDs | Standard `1908:0102`, mehrere durch Komma getrennt (nur AX206) |
| Displaynummer | wenn mehrere Panels angeschlossen sind |
| USB-Gerät zurücksetzen | hilft, wenn ein anderes Programm das Display hängen ließ (nur AX206) |
| Wiederverbindungsintervall | Wartezeit, bis nach einem abgezogenen Display erneut gesucht wird |

**Anzeige → Verbindung → Displaytyp**

Wählt zwischen `AX206-USB-LCD (AIDA64-Typ)` und `Samsung-SPF-Bilderrahmen`.
Je nach Auswahl blendet der Dialog die passenden Optionen ein.

**Anzeige → Samsung-Bilderrahmen**

| Einstellung | Bedeutung |
|---|---|
| Samsung-Modell | Auswahlliste: `Automatisch` nimmt den gefundenen Rahmen, sonst ein Modell wie `SPF-72H` wählen (nur nötig, wenn mehrere Rahmen angeschlossen sind) |
| JPEG-Qualität | 40–100, Standard 85. Niedriger = schneller und weniger Daten |
| Reduzierte Farbauflösung (4:2:0) | an: schneller und kleiner; aus: schärfere farbige Schrift, etwa doppelte Kodierzeit |

**Anzeige → Bild**

| Einstellung | Bedeutung |
|---|---|
| Drehung | 0/90/180/270 Grad, für Hochkant-Montage |
| Horizontal spiegeln | für Spiegelmontage |
| Byte-Reihenfolge | falls die Farben falsch sind – siehe *Fehlersuche* (nur AX206) |
| Displaygröße überschreiben | nur nötig, wenn das Panel eine falsche Auflösung meldet |

**Anzeige → Hintergrundbeleuchtung**

| Einstellung | Bedeutung |
|---|---|
| Helligkeit | AX206: Stufe 0–7 der Hintergrundbeleuchtung |
| Helligkeit (Software) | Samsung: 10–100 %, das Bild wird vor dem Senden abgedunkelt |
| Während des Leerlaufs dimmen | dimmt, sobald nichts abgespielt wird; eine Pause zählt weiterhin als Wiedergabe |
| Helligkeit im Leerlauf | AX206: Stufe 0–7, solange nichts läuft |
| Helligkeit im Leerlauf (Software) | Samsung: 0–100 %, 0 % zeigt ein schwarzes Bild |
| Display beim Beenden von Kodi löschen | schwarzes Bild beim Herunterfahren |

Je nach *Displaytyp* ist immer nur das passende Paar sichtbar. Samsung-Rahmen
haben keine Helligkeitssteuerung über USB – dort wird nicht die Beleuchtung
geregelt, sondern das gesendete Bild abgedunkelt. Das kostet keine zusätzliche
Rechenzeit, weil die Abdunklung in der Farbtabelle des JPEG-Encoders steckt.

**Layout**

Aktives Layout, Layout-Auswahl, eigener Layout-Ordner, Seitenwechselintervall
sowie die Aktionsknöpfe *Vorschau*, *Testbild*, *Anzeigestatus* und
*Dienst neu laden*.

*Layout auswählen …* öffnet eine Liste mit einem Vorschaubild pro Design; die
Einstellungen bleiben dabei geöffnet, das gewählte Layout steht danach in der
Zeile darüber. Die Bilder liegen als `resources/thumbs/<design>.png` bei.
Layouts aus dem eigenen Ordner haben kein mitgeliefertes Bild – sie werden
beim ersten Öffnen der Liste einmal gerendert und in
`<Add-on-Daten>/thumbs/` zwischengespeichert. Mehrere Größen desselben
Designs (`default.json` und `default-800x480.json`) erscheinen als ein
Eintrag, weil beim Laden ohnehin die zum Panel passende Fassung genommen wird.

**Layout → Web-Editor**

| Einstellung | Bedeutung |
|---|---|
| Layout-Editor im Browser | schaltet den Webserver ein und aus (Standard: an) |
| Web-Editor öffnen | zeigt die Adresse, unter der der Editor erreichbar ist |
| Port | Standard 8050 |
| Erreichbar von | `dem ganzen Netzwerk` oder `nur dieser Box` (dann nur über einen Browser auf der Box selbst) |
| Passwort | leer = keine Abfrage; sonst fragt der Browser danach, der Benutzername ist beliebig |

**Sprache**

Es gibt nichts einzustellen: Das Add-on folgt der Sprache von Kodi. Die
Einstellungen, die Meldungen auf dem Display, die mitgelieferten Layouts und
die Namen von Wochentagen und Monaten liegen auf Deutsch und Englisch vor.
Wie eigene Layouts mitziehen, steht in
[docs/LAYOUT.de.md](docs/LAYOUT.de.md) unter *Feste Wörter übersetzen*.

**Verhalten**

Bildwiederholrate bei Wiedergabe und im Leerlauf, weiche Bildskalierung,
Kodi-Benachrichtigungen auf dem Display, Debug-Protokollierung sowie die
**Schaltbefehle**, mit denen beim Start und beim Beenden ein beliebiger
Shell-Befehl ausgeführt wird (siehe *Ein- und Ausschalten mit CoreELEC*).

---

## Alle Layouts auf einen Blick

Jede Vorlage in drei Zuständen – so wie das Add-on sie selbst auswählt:

**Video läuft**

![Übersicht Video](resources/screenshots/overview-video.png)

**Musik läuft**

![Übersicht Musik](resources/screenshots/overview-normal.png)

**Nichts läuft**

![Übersicht Leerlauf](resources/screenshots/overview-idle.png)

Neu erzeugen lassen sich die Übersichten mit

```sh
python3 tools/contact_sheet.py --state video --out uebersicht.png
# --state: video | series | normal | music | idle
# --all-sizes nimmt auch die 800x480-Fassungen mit auf
```

## Mitgelieferte Layouts

Ausgewählt wird nur der Name (z. B. `default.json`) – passt die Größe nicht,
nimmt das Add-on automatisch die Variante `default-800x480.json`.

**Viele Details – zum Davorsitzen**

| Datei | Beschreibung |
|---|---|
| `default.json` | Vier Seiten: Musik (mit Cover), Video (mit Poster), Uhr, Systemwerte |
| `bigcover.json` | Bildschirmfüllendes Cover mit Infoleiste unten |
| `minimal.json` | Große Schrift, Segment-Fortschrittsbalken, keine Bilder – sehr sparsam |
| `dashboard.json` | Analoguhr, CPU, Temperatur, RAM und Verlaufsdiagramm |

**XL – aus mehreren Metern lesbar**

Wenig Inhalt, sehr große Schrift, reines Schwarz als Hintergrund und kräftige
Farben. Auf einem 3,5"-Display ist das der Unterschied zwischen „ich müsste
aufstehen" und „sehe ich vom Sofa".

| Datei | Beschreibung |
|---|---|
| `xl-player.json` | Titel in 40 px über zwei Zeilen, Interpret/Serie groß darunter, dicker Balken, Zeiten in 38 px |
| `xl-remaining.json` | Die **Restzeit riesig** (96 px) in der Bildmitte – die eine Zahl, die man beim Film wirklich wissen will – plus Endzeit und Balken |
| `xl-clock.json` | Uhrzeit in 128 px, im Leerlauf mit Datum und CPU/Temperatur, bei Wiedergabe mit Titel und Balken darunter |
| `xl-system.json` | Uhr groß, darunter CPU, Temperatur und RAM als drei große Zahlen mit Balken und Verlaufsdiagramm |
| `cover-full.json` | Nur das Cover, formatfüllend, mit schmaler Infoleiste und Fortschrittsbalken am unteren Rand |

![XL Restzeit](resources/screenshots/xl-remaining.png)
![XL Wiedergabe](resources/screenshots/xl-player.png)
![XL System](resources/screenshots/xl-system.png)
![Cover formatfüllend](resources/screenshots/cover-full.png)

**Stile**

Gleiche Informationen, anderes Aussehen – such dir aus, was zum Wohnzimmer
passt.

| Datei | Beschreibung |
|---|---|
| `light.json` | Helles Thema, dunkle Schrift auf Weiß – für helle Räume und tagsüber deutlich angenehmer |
| `terminal.json` | Grün auf Schwarz, durchgehend Monospace, Segmentbalken – Konsolen-Optik und sehr gut lesbar |
| `neon.json` | Magenta/Cyan mit leuchtender Kontur um die Schrift, Verlaufsbalken |
| `vinyl.json` | Das Cover als runde Schallplatte samt Mittelloch, Text rechts daneben |

![Terminal](resources/screenshots/terminal.png)
![Neon](resources/screenshots/neon.png)
![Vinyl](resources/screenshots/vinyl.png)
![Hell](resources/screenshots/light.png)

**Andere Inhalte**

| Datei | Beschreibung |
|---|---|
| `nextup.json` | Oben der laufende Titel, unten **was als Nächstes kommt** – für Musik-Wiedergabelisten |
| `weather.json` | Uhr und Wetter nebeneinander, darunter CPU, Temperatur und RAM. Die Wetterseite erscheint nur, wenn in Kodi ein Wetter-Add-on eingerichtet ist |
| `library.json` | Filme, Serien und Alben als große Zähler, darunter Episoden, Songs und Interpreten |
| `portrait.json` | **Hochformat 320×480** für ein um 90° gedreht montiertes Display – Cover oben, Text darunter |

![Jetzt & Danach](resources/screenshots/nextup.png)
![Wetter](resources/screenshots/weather.png)
![Bibliothek](resources/screenshots/library.png)

Von jedem Layout gibt es die 800×480-Fassung mit dem Zusatz `-800x480`
(beim Hochformat `portrait-480x800.json`); das Add-on wählt sie automatisch,
wenn ein entsprechendes Panel angeschlossen ist.

Für das Hochformat zusätzlich *Einstellungen → Anzeige → Bild → Drehung* auf
90 oder 270 Grad stellen.

---

## Layout-Baukasten im Browser

Layouts lassen sich mit der Maus zusammenstellen, statt JSON zu tippen: Der
Dienst bringt einen kleinen Webserver mit, der einen Editor ausliefert.

![Layout-Baukasten](resources/screenshots/webeditor.png)

**Öffnen**

*Add-ons → LCD4Linux → Web-Editor* zeigt die Adresse an, meist

```
http://<IP-der-Box>:8050/
```

Die Adresse steht auch in den Einstellungen unter *Layout → Web-Editor*. Der
Editor läuft in jedem aktuellen Browser, auch auf Handy und Tablet – es wird
nichts nachgeladen, alles gehört zum Add-on.

**Was er kann**

* **Seiten** anlegen, kopieren, umsortieren und löschen – die Reiter oben
  links entsprechen den Seiten des Layouts.
* **Elemente** aus der Palette auf die Fläche ziehen oder anklicken: Text,
  Bild, Fortschrittsbalken, Diagramm, Rechteck, Linie, Kreis, Symbol und
  Analoguhr.
* **Verschieben und Größe ändern** mit der Maus, am Raster einrastend
  (`Alt` gedrückt halten schaltet das Einrasten aus, `Umschalt` hält beim
  Ziehen die Richtung). Pfeiltasten verschieben pixelweise, mit `Umschalt`
  in Zehnerschritten.
* **Eigenschaften** rechts: jedes Feld, das der Renderer kennt – Farben mit
  Farbwähler, Schriften, Ausrichtung, Lauftext, Bedingungen mit Vorlagen.
* **Datenfelder** über den Knopf `${}`: alle Tokens mit Erklärung, dazu die
  Filter (`|upper`, `|trunc:20`, `|hms` …), eingefügt an der Cursorstelle.
* **Vorschau**: Nach jeder Änderung rendert das Add-on das Bild selbst und
  zeigt es an – kein Nachbau im Browser, sondern genau das, was das Panel
  zeigen wird. Umschaltbar zwischen *Musik läuft*, *Video läuft*,
  *Pausiert*, *Nichts läuft* und – auf der Box – *Echte Daten*.
* **Speichern** in den eigenen Layout-Ordner und *Aufs Display* übernimmt das
  Layout sofort auf dem Panel.
* Rückgängig/Wiederholen (`Strg+Z` / `Strg+Y`), Duplizieren (`Strg+D`),
  Speichern (`Strg+S`), Löschen (`Entf`), Ausrichtungsknöpfe und ein
  JSON-Editor für den Feinschliff.

**Speicherort**

Gespeichert wird immer in den eigenen Ordner
(`.../addon_data/script.lcd4linux/layouts/`). Ein mitgeliefertes Layout wird
dabei nicht überschrieben: Die eigene Fassung hat Vorrang, das Original
kommt zurück, sobald die Kopie gelöscht wird.

**Ohne Box, nur am PC**

```sh
python3 tools/webeditor.py            # http://127.0.0.1:8050/
python3 tools/webeditor.py --bind all --port 8050 --password geheim
```

**Sicherheit**

Der Editor darf Layoutdateien schreiben und den Dienst neu laden. Im
Heimnetz ist das gewollt; in einem gemeinsam genutzten Netz sollte
*Erreichbar von* auf **nur dieser Box** stehen oder ein Passwort gesetzt
sein. Ausgeliefert werden ausschließlich die Dateien aus `resources/web/`,
gespeichert wird ausschließlich in den Layout-Ordner, und Dateinamen mit
Pfadangaben weist der Server ab.

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

### Layout auf eine andere Displaygröße umrechnen

Ein vorhandenes Layout lässt sich maßstäblich umrechnen, statt es von Hand
neu zu setzen:

```sh
python3 tools/scale_layout.py meins.json 800 480
# schreibt meins-800x480.json
```

Positionen und Boxen folgen dabei den beiden Achsen getrennt, Schriftgrößen,
Radien und Linienstärken der Höhe – so bleiben die Proportionen der Schrift
erhalten. Prozentangaben bleiben unverändert, weil sie schon relativ sind.

Eine Einschränkung: Weil beide Achsen unterschiedlich skalieren, wird aus
einem Kreis ein Oval. Layouts mit runden Elementen – etwa `vinyl.json` – muss
man danach von Hand nachziehen (Box wieder quadratisch machen).

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
Bilder auskommt. Beim Samsung zusätzlich die *JPEG-Qualität* senken; Layouts
mit großen einfarbigen Flächen kodieren deutlich schneller als solche mit
bildschirmfüllendem Hintergrundbild (siehe Tabelle unten).

**Samsung: Rahmen bleibt im Massenspeicher-Modus**
Im Protokoll steht dann „the frame did not come back in monitor mode".
Rahmen einmal aus- und wieder einstecken. Manche Modelle schalten nur um, wenn
sie eingeschaltet sind und nicht gerade eine Diashow abspielen.

**Samsung: Bild bleibt stehen**
Der Rahmen fällt ohne den Keep-Alive nach einiger Zeit aus dem Monitor-Modus.
Das Add-on schickt ihn nach jedem Bild; steht die Bildrate auf 1/s und das
Layout ändert sich nie (z. B. eine Uhr ohne Sekunden), wird trotzdem jedes
Bild gesendet, damit der Rahmen wach bleibt.

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

## Rechenaufwand beim Samsung

Der Rahmen nimmt nur vollständige JPEG-Bilder an. Das Add-on kodiert deshalb
nur die Blockzeilen neu, die sich geändert haben – gemessen auf einem
Arbeitsplatzrechner bei 800×480 und Qualität 85 (auf einer Amlogic-Box etwa
Faktor 4–6 langsamer):

| Layout | erstes Bild | laufende Aktualisierung | JPEG-Größe |
|---|---|---|---|
| `minimal-800x480` | 113 ms | 9 ms | 23 kB |
| `dashboard-800x480` | 137 ms | 30 ms | 27 kB |
| `default-800x480` | 166 ms | 22 ms | 38 kB |
| `bigcover-800x480` | 168 ms | 12 ms | 28 kB |

Ein voll­flächiges Bild kostet vor allem beim ersten Bild; danach bleiben nur
die Zeilen mit Uhr und Fortschrittsbalken übrig. Für langsame Boxen ist
`minimal` die sparsamste Wahl.

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
    spf.py                    Samsung-SPF-Protokoll (Mode-Switch, JPEG-Frames)
    jpegenc.py                JPEG-Encoder mit Blockzeilen-Cache
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
    thumbs.py                 Vorschaubilder für die Layout-Auswahl
    webui.py                  Webserver und API des Layout-Baukastens
    webschema.py              Widget-Felder und Tokens für den Editor
resources/web/                der Editor selbst (HTML, CSS, JavaScript)
tools/preview.py              Layout-Vorschau als PNG
tools/webeditor.py            Layout-Baukasten am PC starten
tools/scale_layout.py         Layout auf eine andere Displaygröße umrechnen
tools/contact_sheet.py        Übersichtsbild aller Layouts erzeugen
tools/make_thumbs.py          Vorschaubilder für die Layout-Auswahl erzeugen
tools/selftest.py             Selbsttest ohne Hardware
tools/mkfont.py               Schriften neu erzeugen (benötigt Pillow)
```

---

## English summary

Kodi/CoreELEC add-on for two families of USB display: the 3.5" 480×320 panels
based on the **AX206** controller (sold as AIDA64 screens, known from `dpf-ax`
and `lcd4linux`), and the **Samsung SPF** photo frames (SPF-72H, SPF-87H,
SPF-107H and relatives) in their mini monitor mode.

It shows what Kodi is playing (title, artist, album, cover art, a progress bar
with elapsed and remaining time) plus clock, CPU load, temperature and any Kodi
InfoLabel. Everything on screen is defined by JSON layout files, so pages,
widgets, colours, fonts, positions and data sources are fully customisable.

USB access uses `libusb` through `ctypes`; the PNG/JPEG decoders, the JPEG
*encoder* the Samsung frames need, and the font renderer are all part of the
add-on, so **no extra Python modules are required**. On the AX206 only the
changed rectangle is transferred; on the Samsung, which accepts complete JPEG
images only, only the MCU rows that changed are re-encoded.

* Layout reference: [docs/LAYOUT.en.md](docs/LAYOUT.en.md)
* **Layout editor in the browser**: the service serves a drag and drop editor
  at `http://<box>:8050/` (*Add-ons → LCD4Linux → Web editor* shows the
  address). Pages, widgets, colours and data fields are edited with the
  mouse, and the preview next to them is drawn by the add-on's own renderer,
  so it is exactly what the panel will show. On a PC without Kodi:
  `python3 tools/webeditor.py`
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
`lcd4linux` (`drv_dpf.c`). Das Samsung-SPF-Protokoll folgt dem Treiber
`drv_SamsungSPF.c` von lcd4linux, der auf `playusb` von Andre Puschmann und
den Arbeiten von Grace Woo aufbaut.
