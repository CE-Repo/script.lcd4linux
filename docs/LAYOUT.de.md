# Layout-Referenz

Ein Layout ist eine JSON-Datei, die beschreibt, **was** wo auf dem Display
steht. Zeilen, die mit `//` oder `#` beginnen, werden als Kommentar
übersprungen.

Eigene Layouts gehören nach

```
/storage/.kodi/userdata/addon_data/script.lcd4linux/layouts/
```

Dateien dort haben Vorrang vor den mitgelieferten und überleben Updates.
Nach dem Bearbeiten: *Dienst neu laden* im Menü (oder Layout neu auswählen).

In der Layout-Auswahl bekommt ein eigenes Layout automatisch ein
Vorschaubild: Es wird beim ersten Öffnen der Liste einmal gerendert und in
`addon_data/script.lcd4linux/thumbs/` abgelegt. Wird die Layoutdatei
geändert, entsteht das Bild beim nächsten Öffnen neu.

Layoutdateien werden als **UTF-8** gelesen; eine Byte-Reihenfolge-Markierung
(BOM), wie sie manche Windows-Editoren schreiben, wird toleriert.

Die Größe im Feld `size` muss zum Display passen. Für die beiden
unterstützten Displaygrößen gibt es jeweils eigene Dateien: heißt das
ausgewählte Layout `default.json` und ist ein 800×480-Panel angeschlossen,
verwendet das Add-on automatisch `default-800x480.json`, sofern vorhanden.
Eigene Layouts folgen derselben Regel – `meins-800x480.json` neben
`meins.json`.

Umrechnen muss man nicht von Hand:

```sh
python3 tools/scale_layout.py meins.json 800 480
```

### Aus der Ferne lesbar

Auf einem 3,5"-Display entscheidet die Schriftgröße darüber, ob man etwas
erkennt oder nicht. Als Anhaltspunkte für 480×320:

* Wichtigste Information: 40–130 px. Ein Titel in 40 px ist aus zwei bis drei
  Metern lesbar, eine Uhrzeit in 128 px quer durchs Zimmer.
* Nebeninformation: nicht unter 20 px. Alles darunter ist aus der Ferne nur
  noch eine graue Linie.
* Kontrast schlägt Feinheit: Weiß auf Schwarz. Dunkelgraue Schrift auf fast
  schwarzem Grund (etwa `#4a5266` auf `#0b0d12`) sieht am Schreibtisch gut
  aus und verschwindet aus drei Metern vollständig – für Nebeninformation
  lieber `#a8b0c0`.
* Wenige Elemente: drei bis fünf pro Seite. Was übrig bleibt, darf groß sein.
* Balken dick machen: 18–26 px statt 8–12 px.

Die mitgelieferten `xl-*`-Layouts sind nach diesen Regeln gebaut und ein
guter Ausgangspunkt zum Abkupfern.

---

## 1. Grundgerüst

```json
{
  "name": "Mein Layout",
  "size": [480, 320],
  "background": "#0b0d12",
  "accent": "auto:${player.thumb}",
  "pageinterval": 15,
  "defaults": {"font": "sans", "size": 18, "color": "#f2f5fa"},
  "pages": [ ... ]
}
```

| Feld | Bedeutung |
|---|---|
| `name` | Anzeigename in der Layout-Auswahl |
| `size` | `[Breite, Höhe]` in Pixeln, für dieses Panel `[480, 320]` |
| `background` | Hintergrundfarbe des gesamten Layouts |
| `accent` | Akzentfarbe. Feste Farbe oder `auto:${...}` – dann wird die auffälligste Farbe des angegebenen Bildes benutzt (z. B. des Covers). Widgets schreiben dafür `"color": "accent"` |
| `pageinterval` | Sekunden pro Seite, wenn eine Seite keine eigene `duration` hat |
| `defaults` | Vorgaben für Schrift (`font`), Größe (`size`) und Farbe (`color`) aller Textwidgets |
| `pages` | Liste der Seiten |

---

## 2. Seiten

```json
{
  "name": "Musik",
  "condition": "audio",
  "duration": 0,
  "priority": 10,
  "background": "#0b0d12",
  "backgroundimage": "${player.thumb}",
  "backgrounddim": 88,
  "widgets": [ ... ]
}
```

| Feld | Bedeutung |
|---|---|
| `name` | Name der Seite (erscheint kurz beim manuellen Weiterschalten) |
| `condition` | Sichtbarkeitsbedingung, siehe Abschnitt 6. Fehlt sie, ist die Seite immer sichtbar |
| `duration` | Anzeigedauer in Sekunden; `0` nutzt `pageinterval` des Layouts |
| `priority` | Höhere Zahl gewinnt: Sind Seiten mit `priority: 10` sichtbar, werden alle mit kleinerer Priorität ignoriert. So verdrängt eine Wiedergabeseite die Uhrseite |
| `background` | Hintergrundfarbe dieser Seite |
| `backgroundimage` | Hintergrundbild (Pfad oder Token), wird bildschirmfüllend zugeschnitten |
| `backgrounddim` | 0–100 %, wie stark das Hintergrundbild abgedunkelt wird |
| `widgets` | Liste der Widgets, in Zeichenreihenfolge (später = weiter vorne) |

Sind mehrere Seiten gleichzeitig sichtbar, wechselt das Add-on reihum durch
sie. Ändert sich die Menge der sichtbaren Seiten (z. B. Wiedergabe startet),
beginnt es wieder bei der ersten.

---

## 3. Gemeinsame Widget-Eigenschaften

```json
{"type": "text", "x": 20, "y": 30, "w": 200, "h": 24, "condition": "playing"}
```

| Feld | Bedeutung |
|---|---|
| `type` | Widget-Typ, siehe Abschnitt 4 |
| `name` | frei wählbar, taucht nur im Debug-Protokoll auf |
| `x`, `y` | Position der linken oberen Ecke |
| `w` / `width`, `h` / `height` | Größe; fehlt sie, reicht das Widget bis zum rechten bzw. unteren Rand |
| `condition` / `visible` | Bedingung, siehe Abschnitt 6 |
| `opacity` | 0–100 % Deckkraft |

**Positionsangaben** dürfen sein:

* Zahlen: `"x": 20`
* Prozent: `"x": "50%"` (bezogen auf die Displaybreite bzw. -höhe)
* negative Zahlen: `"x": -100` misst vom rechten Rand, `"y": -40` vom unteren

**Farben** dürfen sein:

* `"#RRGGBB"` – z. B. `"#17b2e2"`
* `"#AARRGGBB"` – mit Alphakanal wie in Kodi-Skins, z. B. `"#80000000"` (halb­transparentes Schwarz)
* `"#RGB"` – Kurzform
* `"r,g,b"` oder `"r,g,b,a"` – z. B. `"255,138,0"`
* Namen: `black`, `white`, `red`, `green`, `blue`, `cyan`, `magenta`, `yellow`,
  `orange`, `grey`, `silver`, `dimgrey`, `purple`, `pink`, `lime`, `teal`,
  `brown`, `navy`, `gold`, `kodiblue`, `transparent`
* `"accent"` – die Akzentfarbe des Layouts
* Farben dürfen auch Tokens enthalten

**Schriften**: `sans`, `sans-bold`, `mono`, `mono-bold`. Jede Größe ist
möglich; nicht mitgelieferte Größen werden aus der nächstliegenden berechnet.
Eigene `.l4f`-Schriften können in den Ordner `fonts` neben `layouts` gelegt
werden (erzeugbar mit `tools/mkfont.py`).

---

## 4. Widgets

### `text`

```json
{"type": "text", "x": 20, "y": 24, "w": 440, "h": 34,
 "text": "${player.title}", "size": 26, "bold": true,
 "align": "center", "scroll": "marquee", "shadow": "#000000"}
```

| Feld | Standard | Bedeutung |
|---|---|---|
| `text` | – | Text mit `${...}`-Tokens |
| `font` | `defaults.font` | Schriftfamilie |
| `size` | `defaults.size` | Schriftgröße in Pixel |
| `bold` | `false` | hängt `-bold` an die Familie an |
| `color` | `defaults.color` | Textfarbe |
| `align` | `left` | `left`, `center`, `right` |
| `valign` | `top` | `top`, `middle`/`center`, `bottom` |
| `wrap` | `false` | Zeilenumbruch innerhalb der Breite |
| `lines` | automatisch | maximale Zeilenzahl bei `wrap` |
| `linespacing` | `0` | zusätzlicher Zeilenabstand |
| `padding` | `0` | Innenabstand |
| `background` | – | Hintergrundfarbe hinter dem Text |
| `radius` | `0` | Eckenradius des Hintergrunds |
| `scroll` | `none` | `marquee` (endlos), `bounce` (hin und her) |
| `scrollspeed` | `30` | Pixel pro Sekunde |
| `scrollpause` | `2.0` | Pause an den Enden bei `bounce` |
| `scrollgap` | `40` | Abstand zwischen Wiederholungen bei `marquee` |
| `shadow` | – | Schattenfarbe (oder `true`) |
| `shadowoffset` | `2` | Versatz des Schattens |
| `outline` | – | Umrissfarbe |
| `showempty` | `false` | Widget auch zeichnen, wenn der Text leer ist |

Passt der Text nicht und ist `scroll` aus, wird er mit `…` gekürzt.

### `progress`

```json
{"type": "progress", "x": 20, "y": 260, "w": 440, "h": 12,
 "value": "${player.percent}", "radius": 6, "color": "accent",
 "background": "#1e2330", "knob": true}
```

| Feld | Standard | Bedeutung |
|---|---|---|
| `value` | `${player.percent}` | Zahl oder Token |
| `min`, `max` | `0`, `100` | Wertebereich |
| `orientation` | `horizontal` | `horizontal` oder `vertical` (füllt von unten) |
| `color` | Kodi-Blau | Farbe des gefüllten Teils |
| `gradient` | – | zweite Farbe für einen Verlauf |
| `background` | `#20242e` | Farbe der Leiste, `null` für keine |
| `radius` | `0` | Eckenradius |
| `border`, `bordercolor` | `0` | Rahmenbreite und -farbe |
| `style` | `bar` | `bar` oder `segments` |
| `segments` | `20` | Anzahl der Segmente bei `style: segments` |
| `gap` | `2` | Lücke zwischen Segmenten |
| `inactivecolor` | – | Farbe nicht erreichter Segmente |
| `knob` | `false` | Knopf am Fortschrittspunkt |
| `knobsize`, `knobcolor` | | Größe und Farbe des Knopfes |

### `graph`

Verlaufsdiagramm eines Zahlenwerts.

| Feld | Standard | Bedeutung |
|---|---|---|
| `value` | – | Token, das eine Zahl liefert |
| `min`, `max` | `0`, `100` | Wertebereich |
| `points` | `60` | Anzahl gespeicherter Messwerte |
| `interval` | `1.0` | Sekunden zwischen zwei Messwerten |
| `color` | Kodi-Blau | Linienfarbe |
| `fill` | – | Füllfarbe unter der Linie (gern mit Alpha, z. B. `#2217b2e2`) |
| `background` | – | Hintergrundfarbe |
| `thickness` | `1` | Linienstärke |

### `rect`

| Feld | Bedeutung |
|---|---|
| `color` / `fill` | Füllfarbe |
| `gradient` | Zielfarbe eines Verlaufs |
| `direction` | `vertical` (Standard) oder `horizontal` |
| `radius` | Eckenradius |
| `border`, `bordercolor` | Rahmen |

### `line`

| Feld | Bedeutung |
|---|---|
| `color` | Farbe |
| `thickness` | Stärke |
| `x2`, `y2` | Endpunkt für eine schräge Linie |

Ohne `x2`/`y2` füllt die Linie ihre eigene Box: eine breite flache Box ergibt
eine waagerechte Linie in Boxhöhe (`"w": 440, "h": 3` also 3 px hoch), eine
hohe schmale Box eine senkrechte. `thickness` hebt nur die Mindeststärke an.

### `circle`

| Feld | Bedeutung |
|---|---|
| `color` | Farbe |
| `radius` | Radius; ohne Angabe die halbe Widgetgröße |
| `thickness` | `0` = gefüllt, sonst Ringstärke |

### `image`

```json
{"type": "image", "x": 18, "y": 18, "w": 180, "h": 180,
 "src": "${player.thumb}", "fit": "cover", "radius": 10}
```

| Feld | Standard | Bedeutung |
|---|---|---|
| `src` / `path` | – | Dateipfad oder Token; `image://`-URLs von Kodi werden aufgelöst |
| `fallback` | – | Ersatzquelle, wenn `src` leer ist |
| `fit` | `contain` | `contain` (ganz sichtbar), `cover` (füllt und beschneidet), `stretch` |
| `radius` | `0` | abgerundete Ecken |
| `align`, `valign` | `center` | Ausrichtung innerhalb der Box |
| `opacity` | `100` | Deckkraft |

PNG und JPEG (Baseline) werden unterstützt; progressive JPEGs nicht. Bilder
werden zwischengespeichert und nur bei Wechsel neu dekodiert.

### `icon`

Vektorsymbole, beliebig skalierbar und einfärbbar.

```json
{"type": "icon", "x": 18, "y": 212, "w": 20, "h": 20, "icon": "play", "color": "accent"}
```

Verfügbar: `play`, `pause`, `stop`, `next`, `previous`, `music`, `movie`,
`tv`, `speaker`, `mute`, `clock`, `cpu`, `temp`, `star`, `heart`, `folder`,
`wifi`, `shuffle`, `repeat`, `disc`, `dot`.

Der Name darf ein Token sein, z. B. `"icon": "${player.mediatype}"` in
Verbindung mit passenden Symbolnamen.

### `analogclock`

| Feld | Standard | Bedeutung |
|---|---|---|
| `face` | – | Zifferblattfarbe |
| `rim`, `rimwidth` | – | Rand |
| `color` | weiß | Stunden- und Minutenzeiger |
| `secondcolor` | rot | Sekundenzeiger |
| `ticks` | `true` | Stundenstriche |
| `tickcolor` | grau | Farbe der Striche |
| `seconds` | `true` | Sekundenzeiger anzeigen |

---

## 5. Datenfelder (Tokens)

Tokens stehen in `${...}` und dürfen überall im Text, in Zahlenfeldern
(`value`), in Farben und in Bedingungen verwendet werden.

### Wiedergabe – `player.*`

| Token | Inhalt |
|---|---|
| `state` | `playing`, `paused` oder `stopped` |
| `mediatype` | `audio`, `video`, `picture`, `none` |
| `playing`, `paused` | `1` oder `0` |
| `time`, `time_s` | gespielte Zeit als `m:ss` bzw. in Sekunden |
| `duration`, `duration_s` | Gesamtlänge |
| `remaining`, `remaining_s` | Restzeit |
| `percent` | Fortschritt 0–100 |
| `title`, `artist`, `albumartist`, `album`, `genre`, `year` | Metadaten |
| `track`, `discnumber`, `rating` | Musikangaben |
| `showtitle`, `season`, `episode`, `episodelabel`, `plot` | Serienangaben (`episodelabel` ergibt z. B. `S02E05`) |
| `thumb` / `cover` / `art`, `poster`, `fanart` | Bildquellen |
| `codec`, `audiocodec`, `bitrate`, `samplerate`, `channels` | Tonformat |
| `resolution`, `aspect` | Bildformat |
| `next`, `nextartist` | nächster Titel |
| `playlistposition`, `playlistlength` | Position in der Wiedergabeliste |
| `starttime`, `finishtime` | Uhrzeit von Beginn und Ende |
| `filename`, `path` | Datei und Ordner |
| `speed`, `seeking` | Abspielgeschwindigkeit, Spulen |

Nicht aufgeführte Namen werden als Kodi-InfoLabel `Player.<Name>` gelesen.

### System – `system.*`

`time`, `time12`, `timesec`, `seconds`, `date`, `date_iso`, `date_short`,
`date_long`, `weekday`, `weekday_short`, `day`, `month`, `monthname`, `year`,
`cpu`, `cputemp`, `gputemp`, `memory`, `memoryfree`, `memorytotal`, `uptime`,
`hostname`, `ip`, `kodiversion`, `buildversion`, `freespace`, `volume`,
`muted`, `screensaver`, `profile`.

Temperatur und CPU-Last kommen direkt aus `/sys` bzw. `/proc`, funktionieren
auf CoreELEC also auch dann, wenn Kodi selbst nichts meldet.

### Weitere

| Token | Inhalt |
|---|---|
| `weather.temperature`, `weather.conditions`, `weather.location` | Wetter-Add-on von Kodi |
| `library.songs`, `library.albums`, `library.artists`, `library.movies`, `library.tvshows`, `library.episodes` | Bibliotheksgrößen (alle 5 Minuten aktualisiert) |
| `addon.name`, `addon.version` | dieses Add-on |
| `info:<InfoLabel>` | **jedes** Kodi-InfoLabel, z. B. `${info:MusicPlayer.Album}` |
| `bool:<Bedingung>` | `1`/`0` für jede Kodi-Bedingung |

Die vollständige InfoLabel-Liste steht im
[Kodi-Wiki](https://kodi.wiki/view/InfoLabels).

### Filter

Filter werden mit `|` angehängt und lassen sich verketten:

```
${player.title|upper|trunc:20}
${player.time_s|hms}
${player.year|prefix: · }
```

| Filter | Wirkung |
|---|---|
| `upper`, `lower`, `title`, `capitalize` | Groß-/Kleinschreibung |
| `strip` | Leerzeichen entfernen |
| `trunc:N` | auf N Zeichen kürzen, mit `…` |
| `pad:N` oder `pad:N:z` | rechtsbündig auffüllen |
| `hms` | Sekunden als `m:ss` bzw. `h:mm:ss` |
| `hhmmss` | Sekunden immer als `h:mm:ss` |
| `int` | Nachkommastellen abschneiden |
| `round:N` | auf N Stellen runden |
| `abs` | Betrag |
| `default:Text` | Ersatztext, wenn leer |
| `prefix:Text` | Text davorsetzen – aber nur, wenn der Wert nicht leer ist |
| `suffix:Text` | Text anhängen, ebenfalls nur bei nicht leerem Wert |
| `replace:alt:neu` | ersetzen |
| `first:Trenner` | erster Teil, Standardtrenner `,` |

`prefix` und `suffix` sind praktisch für Trennzeichen, die verschwinden
sollen, wenn es nichts zu trennen gibt:
`${player.year}${player.genre|prefix: · }`.

### Feste Wörter übersetzen – `$LOCALIZE[...]`

Fest eingetragene Wörter lassen sich übersetzen, indem statt des Wortes eine
String-ID geschrieben wird – dieselbe Schreibweise wie in Kodi-Skins:

```json
{"type": "text", "x": 16, "y": 8, "text": "$LOCALIZE[32433]"}
```

* IDs ab **30000** kommen aus `resources/language/` dieses Add-ons.
* IDs darunter kommen aus Kodi selbst, zum Beispiel `$LOCALIZE[31]` für
  „Verfügbar".

`$LOCALIZE[...]` wird **vor** den `${...}`-Tokens ersetzt und darf deshalb
auch als Filterargument stehen, wo `trunc` die übersetzte Länge zählen muss:

```
${player.next|prefix:$LOCALIZE[32420]: |trunc:32}
```

Auch `name` einer Seite darf so geschrieben werden; dieser Name erscheint als
Einblendung beim Seitenwechsel. Die mitgelieferten Layouts sind vollständig so
aufgebaut, die IDs der Wörter stehen ab 32400 in beiden Sprachdateien.

Wochentags- und Monatsnamen (`${system.weekday}`, `${system.monthname}`,
`${system.date_long}`) übersetzt das Add-on von sich aus, dafür ist nichts zu
tun.

---

## 6. Bedingungen

`condition` steuert, ob eine Seite oder ein Widget gezeichnet wird.

**Zustände des Add-ons**

| Bedingung | Wahr, wenn |
|---|---|
| `playing` | etwas läuft |
| `paused` | pausiert |
| `stopped` / `idle` | nichts läuft |
| `active` / `hasmedia` | läuft oder pausiert |
| `audio` | Musik läuft oder pausiert |
| `video` | Video läuft oder pausiert |
| `screensaver` | Bildschirmschoner aktiv |
| `always` / `never` | immer / nie |

**Kodi-Bedingungen** – jede Bedingung aus dem Kodi-Wiki, z. B.
`Player.HasVideo`, `System.HasNetwork`, `Window.IsActive(home)`.

**Vergleiche**

```json
"condition": "${player.percent} > 90"
"condition": "${system.cputemp} >= 70"
"condition": "${player.title} contains Live"
```

Operatoren: `==`, `!=`, `>`, `<`, `>=`, `<=`, ` contains `, ` startswith `,
` endswith `.

**Vorhandensein** – ein einzelnes Token ist wahr, wenn es nicht leer ist:

```json
"condition": "${player.album}"
```

**Verknüpfungen**

* `!` verneint: `"!active"`
* `+` verbindet mit UND: `"audio+playing"`
* `|` verbindet mit ODER: `"audio|video"`

```json
"condition": "video+${player.percent} > 95"
```

---

## 7. Tipps

* **Nach dem Bearbeiten** *Dienst neu laden* im Add-on-Menü aufrufen.
* **Fehler im Layout** stehen im Kodi-Protokoll; ein Widget, das eine Ausnahme
  auslöst, wird übersprungen, der Rest der Seite wird trotzdem gezeichnet.
  Bei ungültigem JSON fällt das Add-on auf das erste gefundene Layout zurück.
* **Sparsam bleiben**: Text und Rechtecke sind sehr billig, Bilder werden
  einmal beim Wechsel dekodiert. Ein Hintergrundbild wird zwischengespeichert
  und kostet danach nichts mehr.
* **Übertragen wird nur, was sich ändert.** Ein Layout ohne Sekundenanzeige
  und ohne Lauftext erzeugt im Leerlauf praktisch keinen USB-Verkehr.
* **Vorschau** auf dem PC:
  `python3 tools/preview.py --layout mein.json --page 0 --out test.png`
* **Testbild** (Menü → *Testbild*) prüft Auflösung, Drehung und
  Byte-Reihenfolge: Der rote Rahmen muss alle vier Kanten berühren, der
  Graukeil muss gleichmäßig verlaufen.
* **Samsung-Rahmen**: Jedes Bild geht als vollständiges JPEG über den Bus, es
  wird aber nur neu kodiert, was sich geändert hat. Große einfarbige Flächen
  sind praktisch gratis, ein bildschirmfüllendes Foto kostet beim ersten Bild
  am meisten. Wenn es zu langsam ist: *JPEG-Qualität* senken, die
  *reduzierte Farbauflösung* eingeschaltet lassen und ein Layout ohne
  Hintergrundbild wählen.
