# zeit — Zeiterfassung in Markdown

Kleines Terminal-Tool, inspiriert von [Watson](https://github.com/jazzband/Watson),
mit einem Unterschied: Es gibt **keine Datenbank**. Jeder Zeiteintrag landet als
Zeile in einer ganz normalen Markdown-Datei im jeweiligen Projektordner.
Was in den Dateien steht, ist alles, was das Tool weiß — und alles, was du oder
ein KI-Assistent zum Auswerten braucht.

Läuft komplett lokal und offline. Kein Account, keine Cloud, keine Abhängigkeiten
außer Python (nur Standardbibliothek).

*[English README](README.en.md)*

## Installation

Voraussetzungen: **macOS** und **Python 3.9 oder neuer**. Python bringt macOS mit
den Entwicklerwerkzeugen mit (`xcode-select --install`, falls noch nicht da).

```bash
curl -fsSL https://raw.githubusercontent.com/keyanthx/zeit/main/install.sh | bash
```

Das Skript lädt zeit nach `~/.local/share/zeit`, richtet den Befehl `zeit` ein
und — falls [SwiftBar](https://swiftbar.app) installiert ist — die Menüleiste.
Lieber selbst? Dann so:

```bash
git clone https://github.com/keyanthx/zeit.git
cd zeit && ./install.sh
```

**Aktualisieren:** das Install-Skript erneut ausführen. **Entfernen:**
`~/.local/share/zeit/uninstall.sh` (deine Daten bleiben dabei erhalten).

**Erste Schritte:** Beim ersten Start von `zeit` führt dich ein **Tutorial** durch
alles — Einrichtung (Projektordner, Phasen, Menüleiste) und je eine Übung zu
Timer, Nachtragen, Pomodoro und Kalender, mit einem Übungsprojekt, das danach
wieder verschwindet. Esc beendet es jederzeit; noch einmal starten mit
`zeit tutorial` oder im TUI unter *Einstellungen → Tutorial*. Oder direkt los:

```bash
zeit start mein-projekt planung   # fragt nach, legt Projekt und Ordner an, startet
zeit stop                          # stoppt und trägt ein
zeit                               # Oberfläche im Terminal
```

Die Menüleiste ist optional: `brew install --cask swiftbar`, SwiftBar einmal
öffnen und einen Plugin-Ordner wählen, dann `install.sh` erneut ausführen.

**Deine Daten** liegen nur bei dir: welche Projekte es gibt und deine
Einstellungen in `~/.config/zeit/projekte.md`, die Zeiten selbst in einer
`Zeiterfassung.md` in jedem Projektordner.

## Was zeit kann

- **Timer** starten, stoppen, anhalten, fortsetzen — im Terminal, im TUI, in der
  Menüleiste oder in der GUI
- **Countdown** (Dauer oder „bis 17:00“) und **Pomodoro** mit eigenen Längen
- **Nachtragen** mit freier Eingabe („gestern 9-11:30“, „2h ab 14:00“) oder
  festen Feldern, auch nur als Tag ohne Uhrzeiten
- **Kalender** (Tag, Woche) und **Statistik** (Woche bis alles)
- **Termine** aus der macOS-Kalender-App übernehmen, mit Regeln für Projekt und
  Phase — und auf Wunsch erfasste Zeiten **in den Kalender schreiben**
- **Bericht und Feedback** (😄 😐 ☹️ + Notiz) nach jedem Block
- **Menüleiste** mit Klappmenü, Popup (TUI oder GUI) oder Terminalfenster

Die Oberfläche ist auf Deutsch.

## Bericht nach dem Beenden

Beendest du einen Timer, Countdown oder eine Pomodoro-Sitzung, zeigt `zeit`,
was eingetragen wurde — im TUI als Fenster, aus der Menüleiste (und aus dem
Pomodoro-/Countdown-Dialog) als macOS-Fenster mit **[Kalender öffnen] [OK]**,
im Terminal als Ausgabe:

```
■ Erfasst: hotel-seeblick / design-phase   (Pomodoro-Sitzung)
  09:00–10:55 · 4 Pomodoros · 1:40 h erfasst
    09:00–09:25  0:25  🍅
    …
  Pausen nicht erfasst: 0:15 · 1× angehalten
  Heute insgesamt: 3:15 h
```

Dazu gehören alle Abschnitte der Sitzung: bei Pomodoro und Countdown alles ab
ihrem Beginn (steht als `beginn=` in der Sitzungszeile), beim normalen Timer
die Kette der angehaltenen Abschnitte direkt davor. Nach **Abbrechen** gibt es
keinen Bericht — da wurde nichts eingetragen. Im Terminal zeigt
`zeit --fenster stop` den Bericht zusätzlich als Fenster.

## Feedback nach jedem Block

Nach jedem Block — Timer, Countdown, und beim Pomodoro nach **jedem
Fokusblock** — kannst du (musst aber nicht) festhalten, wie es lief:

- **Fokus:** 😄 fokussiert · 😐 so lala · ☹️ abgelenkt
- **Notiz:** ein freier Satz, z. B. „Mails haben gestört"

Im TUI erscheint die Auswahl direkt unter dem Bericht, in der Menüleiste ein
Fenster mit Bericht, Fokus-Knöpfen, Notizfeld und *Speichern · Überspringen ·
Kalender öffnen*, im Terminal eine kurze Frage (`1`/`2`/`3`, Enter überspringt).

Gespeichert wird in den Spalten **Fokus** und **Notiz** der letzten Zeile des
Blocks (Formatversion 3; ältere Dateien bekommen die leeren Spalten beim
nächsten Schreiben). Ein `|` in der Notiz wird zu `/`, damit die Tabelle heil
bleibt. Die Statistik zeigt im Abschnitt *Fokus & Notizen* die Verteilung, den
Fokus je Phase und die Notizen des Zeitraums; im Kalender steht die Bewertung
am Block.

## Kalendertermine übernehmen

Termine aus der **Kalender-App von macOS** erscheinen im Kalender von `zeit`
als blasse Blöcke neben deiner erfassten Zeit — im TUI als `░`-Streifen, im
Fenster gestrichelt umrandet. Übernommene Termine tragen ein ✓. So siehst du
auf einen Blick, welcher Termin noch nicht als Arbeitszeit erfasst ist, und
übernimmst ihn — auch Wochen später.

- **Welche Kalender:** unter *Einstellungen → Kalender* (TUI) bzw. als Häkchen
  in *Einstellungen …* (Menüleiste). Ganztägige Termine (Feiertage,
  Geburtstage) werden weggelassen.
- **Übernehmen im TUI:** im Kalender `a` → Termin wählen → Enter.
- **Übernehmen im Fenster:** Termin anklicken → Projekt und Phase prüfen →
  *Übernehmen*.
- Übernommene Termine werden normale Einträge mit der Art **📅**. An deinen
  Kalendern selbst ändert `zeit` nie etwas — es liest nur.
- Überschneidet sich ein Termin mit schon erfasster Zeit, wird das angezeigt
  und muss bestätigt werden. Termine, die noch nicht vorbei sind, lassen sich
  nicht übernehmen.

**Kalender-Regeln** sagen, welcher Termin zu welchem Projekt und welcher Phase
gehört — die erste passende gilt. Passt eine vollständige Regel, reicht ein
Enter bzw. Klick; sonst wirst du gefragt (der Regelvorschlag ist vorausgewählt).
Bearbeiten im TUI unter *Einstellungen → Kalender-Regeln* oder direkt in
`~/.config/zeit/projekte.md`:

```
| Wenn                         | Projekt        | Phase        |
|------------------------------|----------------|--------------|
| titel enthält Hotel Seeblick | hotel-seeblick | kennenlernen |
| kalender Arbeit              | ?              | ?            |
```

`?` heißt: beim Übernehmen nachfragen.

**Berechtigung:** macOS fragt beim ersten Zugriff, ob `zeit` deine Kalender
lesen darf — und zwar einmal **pro Programm**, aus dem es läuft: für das
Terminal (TUI) und für SwiftBar (Menüleiste und Fenster). Hast du abgelehnt:
*Systemeinstellungen → Datenschutz & Sicherheit → Kalender*.

## In den Kalender schreiben

Umgekehrt kann `zeit` deine erfassten Zeiten in die macOS-Kalender-App
schreiben: *Einstellungen → In Kalender schreiben* (TUI) bzw. in
*Einstellungen …* (Menüleiste). Standard ist **aus**.

- `zeit` legt dafür einen **eigenen Kalender „zeit"** an (in iCloud, also auf
  allen Geräten). Deine anderen Kalender werden nie angefasst; in der
  Kalender-App blendest du ihn mit einem Häkchen ein und aus.
- Jeder fertige Eintrag wird ein Termin „projekt · phase 🍅" — nach dem
  Stoppen, Nachtragen, Pomodoro-Fokus usw. Nachträge ohne Uhrzeit werden
  ganztägig. Nicht gespiegelt: 📅-Einträge (sie stehen ja schon in deinem
  Kalender) und der gerade laufende Timer.
- Es wird **abgeglichen**, nicht nur angehängt: Korrigierst oder löschst du
  einen Eintrag (auch direkt in der Markdown-Datei), passt sich der Termin
  beim nächsten Schreiben an. Dafür trägt jeder Termin in seinen Notizen eine
  Kennung („zeit-schlüssel: …"); nur solche Termine werden je verändert.
  Selbst angelegte Termine im Kalender „zeit" bleiben unberührt.
- Beim Einschalten fragt `zeit`, ob die bisherigen Einträge auch hinein sollen.
  „Nein" merkt es sich in `~/Library/Caches/zeit/kalender-ausnahmen.json`.
- Ausschalten lässt den Kalender „zeit" stehen — löschen kannst du ihn in der
  Kalender-App.

## Countdown

Ein Timer mit festgelegtem Ende: du sagst, **wie lange** (`2h`, `1:30`,
`90min`) oder **bis wann** (`17:00`) du arbeiten willst.

```bash
zeit countdown start baeckerei-mueller design-phase 2h
zeit countdown start baeckerei-mueller design-phase bis 17:00
```

Im TUI und in der Menüleiste: *Countdown starten* → Projekt → Phase →
Formular mit „Dauer" oder „Bis Uhrzeit" (vorgeschlagen: wie beim letzten Mal).
Die Menüleiste zeigt die Restzeit (`⏳ 1:23 h`), das TUI eine Live-Ansicht.

Ist die Zeit um, kommt eine Mitteilung mit Ton und ein Dialog
**[Countdown beenden] [Noch X min]** — die Zeit läuft weiter, bis du klickst
(Erinnerung nach 5, dann alle 15 Minuten). Einträge bekommen die Art ⏳.
Im Terminal: `zeit countdown mehr [minuten]`, `zeit countdown ende`.

## Anhalten, Fortsetzen, Abbrechen

Für den **normalen Timer**, den **Countdown** und den **Pomodoro-Fokus**:

```bash
zeit anhalten
zeit fortsetzen
zeit abbrechen
```

Im TUI stehen *Anhalten / Fortsetzen / Beenden / Abbrechen* oben im
Hauptmenü, in der Live-Ansicht die Tasten `h` (anhalten), `f` (fortsetzen),
`s` (beenden), `a` (abbrechen). In der Menüleiste stehen sie im Klappmenü.

- **Anhalten** unterbricht: die Zeit bis jetzt wird eingetragen, danach läuft
  keine Zeit. Beim Fortsetzen beginnt eine neue Zeile — die Lücke dazwischen
  ist die Unterbrechung. Beim Countdown und Pomodoro friert die Restzeit ein;
  das Ende verschiebt sich um die Unterbrechung (auch bei „bis 17:00").
- Eine Zeile, die durch Anhalten endete, bekommt ein ⏸ dazu (`⏳⏸`, `🍅⏸`, `⏸`).
  So zählt ein angehaltener und fortgesetzter Pomodoro trotzdem als **einer**.
- Ist etwas **15 Minuten angehalten**, fragt ein Dialog
  **[Beenden] [Fortsetzen]**, danach alle 15 Minuten wieder. Nichts wird von
  selbst fortgesetzt.
- Die **Pomodoro-Pause** lässt sich nicht anhalten — in ihr läuft ohnehin
  keine Zeit.
- **Abbrechen** verwirft den gerade laufenden Abschnitt, ohne ihn
  einzutragen, und beendet alles. Bereits eingetragene Abschnitte (fertige
  Pomodoros, Teile vor dem Anhalten) bleiben stehen. **Beenden** dagegen trägt
  die laufende Zeit ein.

## Pomodoro

Ein Pomodoro ist bei `zeit` eine Betriebsart des normalen Timers: jeder
Fokusblock wird ein ganz normaler Eintrag (mit 🍅 markiert), die Pausen werden
**nicht** erfasst. Optional — der normale Timer bleibt, wie er ist.

**Starten:** *Pomodoro starten* im TUI oder in der Menüleiste, oder

```bash
zeit pomodoro start baeckerei-mueller design-phase --fokus 50 --kurz 10
```

Bei jedem Start stellst du Fokus, kurze Pause, lange Pause und „lange Pause
nach N Pomodoros" ein. Vorgeschlagen werden die zuletzt benutzten Werte
(anfangs 25 / 5 / 15 / 4).

**Ablauf — alles auf Klick:**

```
Fokus ──[Pause starten]──> Pause ──[Weiter mit Fokus]──> Fokus …
                       (nach N Pomodoros: lange Pause)
```

Nichts wechselt von selbst. Läuft der Fokus über die geplante Zeit, zählt die
Zeit weiter, bis du *Pause starten* klickst — du hast ja weitergearbeitet. Die
Pause läuft, bis du *Weiter* klickst. Die Sitzung läuft im Kreis, bis du sie
beendest. Projekt und Phase bleiben pro Sitzung fest.

**Meldungen:** Ist ein Fokus oder eine Pause vorbei, kommt eine macOS-
Mitteilung mit Ton und ein Dialog mit drei Knöpfen:

| Fokus vorbei | Pause vorbei |
|---|---|
| Sitzung beenden · Noch X min · **Pause starten** | Sitzung beenden · Noch X min Pause · **Weiter mit Fokus** |

Reagierst du nicht, kommt die Erinnerung nach 5 Minuten, danach alle 15.
„Noch X min" verlängert ab *jetzt* — auch wenn schon überzogen ist.

**Anzeige:** Menüleiste `🍅 2/4 · 12 min`, in der Pause `☕ 3 min`, beim
Überziehen `+4 min` (orange). Im TUI eine Live-Ansicht mit sekundengenauer
Uhr, Fortschrittsbalken und `●●◐○` für den Satz:

| Taste | Wirkung |
|---|---|
| `p` | Pause starten (im Fokus) |
| `w` | weiter mit Fokus (in der Pause) |
| `n` | noch X min |
| `s` | Sitzung beenden |
| `←` | zurück ins Menü — die Sitzung läuft weiter |

**Im Terminal:** `zeit pomodoro pause`, `… weiter`, `… mehr [minuten]`,
`… ende`, und `zeit status` zeigt den Stand. Auch `zeit stop` beendet eine
Sitzung (ein laufender Fokus wird eingetragen), `zeit start …` bietet an, sie
zu beenden und umzuschalten.

**Wie die Meldungen kommen:** `zeit` hat keinen Dienst, der dauerhaft läuft.
Während einer Sitzung gibt es stattdessen einen kleinen Wecker-Prozess
(`pomodoro.py`), der alle paar Sekunden in die Zeiterfassungs-Datei schaut und
zur richtigen Zeit meldet. Nach jedem Wechsel übernimmt ein frischer Wecker,
nach dem Ende verschwindet er. Ist er einmal weg (Neustart), startet ihn die
Menüleiste oder das TUI von selbst neu. Klickst du im TUI oder in der
Menüleiste, während ein Dialog offen ist, schließt der Dialog sich von selbst.

**In der Datei** steht eine laufende Sitzung als Zeile unter „Läuft gerade",
je nach Art z. B.:

```
- 🍅 Pomodoro · zustand=fokus · phase=design-phase · nr=2 · seit=2026-09-24 09:30:12 · plan=25 · rest=0 · fokus=25 · kurz=5 · lang=15 · nach=4 · wecker=12345
- ⏳ Countdown · zustand=angehalten · phase=design-phase · seit=… · plan=90 · rest=4200 · wecker=…
- ⏸ Timer angehalten · zustand=angehalten · phase=design-phase · seit=… · wecker=…
```

`rest` sind beim Anhalten die übrigen Sekunden.

## Einstellungen

**Akzentfarbe** (TUI: *Einstellungen → Akzentfarbe*, Menüleiste: *Einstellungen …*):
Standard, Blau, Cyan, Grün, Gelb, Orange, Rot oder Magenta. Sie färbt im TUI
Titel und Auswahlbalken, den Text in der Menüleiste und Reiter, Balken und
Heatmap im Kalenderfenster. „Standard" lässt alles wie ursprünglich (die
Menüleiste bleibt in der Systemfarbe). Orange braucht ein Terminal mit 256
Farben, sonst erscheint dort Gelb.

*Einstellungen* im TUI oder in der Menüleiste: der **Ton** der Meldungen (die
macOS-Töne, mit Hörprobe, oder „kein Ton") und wie lange **„Noch X min"**
verlängert (Vorgabe 5). Gespeichert wird beides im Abschnitt „Einstellungen"
in `~/.config/zeit/projekte.md` — dort stehen auch die zuletzt benutzten Pomodoro-
Dauern.

## Zeit nachtragen

Vergessen zu starten? Zeit lässt sich nachträglich eintragen — im Terminal,
im TUI und in der Menüleiste, überall mit derselben Eingabe. Du tippst, was du
weißt, das Tool rechnet den Rest aus:

| Eingabe | ergibt |
|---------|--------|
| `9:00-11:30` | 09:00–11:30 |
| `2h ab 14:00` | 14:00–16:00 (Ende ausgerechnet) |
| `1,5h bis 17:00` | 15:30–17:00 (Anfang ausgerechnet) |
| `gestern 10-12` | davor oder dahinter darf ein Tag stehen |
| `gestern 3h` | **nur Tag**: 3 Stunden ohne Uhrzeiten |

Tage: `heute` (Standard), `gestern`, `vorgestern`, ein Wochentag (`montag` =
der letzte Montag), `23.9.`, `23.9.2026` oder `2026-09-23`.
Dauern: `2h`, `1,5h`, `2h30`, `90min`, `2 Stunden`, `2:30`.
Füllwörter wie „von", „für", „Uhr" stören nicht:
`gestern von 9 bis 11 Uhr` klappt genauso.

Vor dem Eintragen siehst du immer, was verstanden wurde, z. B.
`Di 23.09.2026, 15:30–17:00 (1:30 h)`. Überschneidet sich der Nachtrag mit
einem vorhandenen Eintrag — in *irgendeinem* Projekt —, wird das angezeigt, und
Enter bricht dann ab statt einzutragen. Nachträge werden chronologisch an der
richtigen Stelle einsortiert, nicht ans Ende gehängt.

**Nur Tag, ohne Uhrzeiten:** Weißt du nur noch, *wie lange* du an einem Tag
gearbeitet hast, aber nicht wann, trägst du nur Datum und Dauer ein. In der
Tabelle steht bei Start und Ende dann ein Strich:

```
| 2026-09-23 | –     | –     | 3:00  | design-phase |
```

Die Auswertung rechnet damit ganz normal. Einziger Unterschied: Bei solchen
Einträgen kann das Tool keine Überschneidungen erkennen — ohne Uhrzeit weiß es
nicht, ob sich zwei Einträge zeitlich überlappen. Innerhalb eines Tages stehen
sie hinter den Einträgen mit Uhrzeit.

Abgelehnt wird: ein Ende in der Zukunft, eine Dauer von null, über 24 Stunden,
und „Ende vor Anfang" — außer als kurze Nachtschicht (`23:00-01:00`). So wird
ein Tippfehler wie `9-8` nicht still zu 23 Stunden.

```bash
zeit nachtragen baeckerei-mueller design-phase gestern 2h ab 14:00
```

**Im TUI:** Menüpunkt *Zeit nachtragen* → Projekt → Phase → Formular mit
denselben Feldern und Vorgaben wie in der Menüleiste (siehe unten):

| Taste | Wirkung |
|-------|---------|
| `↑` `↓` (oder Tab) | Feld wechseln |
| `←` `→` | Wert ändern: ±15 Minuten, beim Datum ±1 Tag, bei Schaltern umlegen |
| tippen | überschreibt das Feld, z. B. `14:30`, `1,5h` oder beim Datum `gestern`, `3.9.` |
| `⏎` | eintragen |
| `Esc` | Eingabe im Feld verwerfen, beim zweiten Mal das Formular |

Im Formular heißt `←` also ausnahmsweise nicht „zurück" — sonst könnte ein
Tastendruck deine Eingaben verwerfen. Ungültiges (z. B. `25:00`) wird mit einem
Hinweis abgelehnt, das Feld behält seinen alten Wert.

Der Schalter **Uhrzeiten: mit / ohne (nur Tag)** steht direkt unter dem Datum.
Auf *ohne* werden Von, Bis und „Dauer verschiebt" ausgegraut und übersprungen —
übrig bleiben Datum und Dauer.

**In der Menüleiste:** *Zeit nachtragen …* → Projekt → Phase. Dann öffnet sich
ein Formular mit vier Feldern, vorausgefüllt mit „die letzte Stunde bis jetzt"
(auf 15 Minuten abgerundet):

```
Datum   [ 24.09.2026 ▲▼ ]  Donnerstag
        [ ] Nur Tag (ohne Uhrzeiten)
Von     [ 11:45 ▲▼ ]
Bis     [ 12:45 ▲▼ ]
Dauer   [ 1:00  ]          z. B. 1:30 · 1,5h · 90min
Dauer verschiebt:  (•) Ende  ( ) Anfang
```

Mit dem Häkchen **Nur Tag (ohne Uhrzeiten)** unter dem Datum werden Von, Bis und
der Schalter ausgegraut; eingetragen werden dann nur Datum und Dauer.

Die Felder rechnen sich gegenseitig nach: **Von** ändern schiebt Bis mit (die
Dauer bleibt), **Bis** ändern berechnet die Dauer neu, **Dauer** ändern
verschiebt das Ende — oder den Anfang, wenn du den Schalter umlegst. „2 Stunden
bis 17 Uhr" geht also so: Bis auf 17:00, Schalter auf *Anfang*, Dauer `2`.

Geprüft wird mit denselben Regeln wie im Terminal. Stimmt etwas nicht, öffnet
das Formular erneut mit deinen Werten und einem Hinweis oben. Das Formular ist
in JavaScript for Automation geschrieben, das macOS mitbringt — es steht als
Text im Plugin, weil SwiftBar jede Datei in seinem Ordner als Plugin ausführen
würde.

## Die Oberfläche

`zeit` **ohne weitere Argumente** öffnet eine Oberfläche im Terminal:

```bash
zeit
```

```
  zeit — Zeiterfassung

  ▶  baeckerei-mueller / design-phase
     seit 29.08.2026 09:12 — 2:47 Stunden

  ▸ Timer anhalten
    Timer beenden
    Timer abbrechen
    Timer starten
    Countdown starten
    Pomodoro starten
    Zeit nachtragen
    Übersicht — Projekte und Phasen
    Kalender
    Statistik
    Einstellungen
    Beenden

  ↑↓ wählen · →/⏎ öffnen · q oder Esc beenden
```

Überall gilt dieselbe Steuerung:

| Taste | Wirkung |
|-------|---------|
| `↑` `↓` (oder `k` `j`) | in der Liste wählen |
| `→` oder `⏎` | nach vorne — öffnen, bestätigen |
| `←` | eine Ebene zurück (im Hauptmenü absichtlich wirkungslos) |
| `q` oder `Esc` | zurück — und im Hauptmenü: beenden |

In Ja/Nein-Fragen gilt zusätzlich: `j` ja, `n` nein, `→` und `⏎` nehmen die
angezeigte Vorgabe. `←` bricht dort **immer** ab, nie zu — „nach hinten" ist
also auch dann harmlos, wenn gerade nach einem Löschen gefragt wird.

Beendet wird nur bewusst: mit `q`, `Esc` oder dem Menüpunkt „Beenden". Die
Links-Taste kann das Programm nicht schließen — im Hauptmenü gibt es keine
Ebene mehr, in die sie zurückführen könnte, also tut sie dort nichts.

Eine weitere Ausnahme: in Eingabefeldern (etwa beim Ordnerpfad) tun die Pfeiltasten
absichtlich nichts, damit ein Tastendruck nie den getippten Text verwirft.
Dort brichst du mit `Esc` ab.

Oben stehen die Aktionen für das, was gerade läuft (anhalten, fortsetzen,
beenden, abbrechen) — läuft nichts, fehlen sie.

**Übersicht** listet Projekte und Phasen und lässt sie bearbeiten:
`n` neu · `r` umbenennen · `d` entfernen · `K`/`J` verschieben ·
`o` Ordner eines Projekts wechseln (auf Wunsch zieht die vorhandene
`Zeiterfassung.md` mit um).

Zwei Sicherheitsnetze dabei: Beim **Umbenennen einer Phase** wird gefragt, ob
die bereits erfassten Einträge mitgeändert werden sollen — sonst zerfiele die
Phase still in zwei Kategorien und die Auswertung wäre falsch. Und **Entfernen
löscht nie Daten**: eine gelöschte Phase verschwindet nur aus der Liste, ein
gelöschtes Projekt nur aus der Registry. Die `Zeiterfassung.md` bleibt immer
liegen.

**Kalender** und **Statistik**: siehe den nächsten Abschnitt.

## Kalender und Statistik

Im TUI über die Menüpunkte *Kalender* und *Statistik*, in der Menüleiste über
*Kalender …* und *Statistik …* — dort öffnet sich ein eigenes Fenster mit den
Reitern **Tag · Woche · Statistik**. Beide zeigen dieselben Zahlen: gerechnet
wird an einer Stelle (`kalender.py`), nur gezeichnet wird zweimal.

**Tag:** eine vertikale Leiste, farbig nach Projekt, jeder Block beschriftet
mit Uhrzeit, Projekt, Phase und Art. **Woche:** sieben solche Leisten
nebeneinander, darunter die Tagessummen. Ein laufender Timer erscheint als
Block bis „jetzt". Nachträge ohne Uhrzeit stehen in einer eigenen Zeile
„ohne Uhrzeit" über dem Raster.

Das Zeitraster passt sich an: angezeigt werden nur die Stunden, in denen im
gewählten Zeitraum etwas erfasst wurde (z. B. 9–16 Uhr). Im TUI wird außerdem
die Feinheit gewählt, die auf den Bildschirm passt — 15, 30 oder 60 Minuten
pro Zeile; `█` = Abschnitt mindestens zur Hälfte belegt, `▒` = nur teilweise.

**Statistik** für Woche, Monat, Jahr oder alles:
- Gesamtzeit, Arbeitstage, Ø pro Arbeitstag, längster Tag, Pomodoros
- Verlauf (pro Tag, beim Jahr pro Woche, bei „Alles" pro Monat)
- Anteile nach Projekt und nach Phase (mit 🍅-Zählern), Projekt × Phase
- Arbeitsrhythmus: Heatmap Wochentag × Uhrzeit, typischer Tagesbeginn und
  -schluss, Stunden je Wochentag

| Taste (TUI) | Wirkung |
|---|---|
| `←` `→` | Tag / Woche / Zeitraum davor bzw. danach |
| `t` `w` | Kalender: Tag bzw. Woche |
| `z` | Statistik: Zeitraum umschalten (Woche · Monat · Jahr · Alles) |
| `h` | zurück zu heute / zum aktuellen Zeitraum |
| `↑` `↓` | blättern, wenn nicht alles auf den Bildschirm passt |
| `Esc` / `q` | zurück ins Menü |

Im Kalender und in der Statistik heißt `←` also ausnahmsweise „davor", nicht
„zurück" — wie bei einem Kalender üblich.

Im Fenster gehen dieselben Tasten (`←` `→` `t` `w` `s` `h` `z`), dazu Maus
und `⌘R` (neu laden) / `⌘W` (schließen). Solange es offen ist, holt es sich
jede Minute frische Daten; die gewählte Ansicht bleibt dabei stehen. Es ist
eine lokale Seite in `~/Library/Caches/zeit/`, gezeigt in einem Fenster aus
macOS-Bordmitteln (JavaScript for Automation) — offline, nichts zu
installieren.

## Befehle

Für schnelles Tippen im Vorbeigehen gibt es die Oberfläche nicht — dafür bleiben
die Befehle:

| Befehl | Was er tut |
|--------|------------|
| `zeit` | Oberfläche öffnen |
| `zeit nachtragen "<projekt>" "<phase>" <wann>` | Zeit nachträglich eintragen (siehe oben) |
| `zeit pomodoro start "<projekt>" "<phase>"` | Pomodoro-Sitzung starten (`--fokus --kurz --lang --nach`) |
| `zeit pomodoro pause` / `weiter` / `mehr` / `ende` | Sitzung steuern |
| `zeit countdown start "<projekt>" "<phase>" <2h \| bis 17:00>` | Countdown starten |
| `zeit countdown mehr` / `ende` | Countdown verlängern / beenden |
| `zeit anhalten` / `zeit fortsetzen` | Timer, Countdown oder Pomodoro-Fokus unterbrechen |
| `zeit --ja <befehl>` | ohne Rückfragen (für die Menüleiste) |
| `zeit start "<projekt>" "<phase>"` | Timer starten |
| `zeit stop` | Timer stoppen (Endzeit = jetzt) |
| `zeit stop --um 17:30` | Timer stoppen mit korrigierter Endzeit |
| `zeit status` | Läuft gerade etwas? Welches Projekt, welche Phase, seit wann? |
| `zeit abbrechen` | Laufenden Timer verwerfen, ohne Eintrag zu schreiben |

Groß- und Kleinschreibung, Leerzeichen und Umlaute sind egal:
`"Bäckerei Müller"` und `baeckerei-mueller` meinen dasselbe Projekt.

```bash
zeit start "Bäckerei Müller" "Design-Phase"
```

## Menüleiste (SwiftBar)

In der Menüleiste steht, was gerade läuft, z. B. `▶ design-phase 2:47`. Läuft
nichts, nur ein `⏱`. Ist der Timer über acht Stunden oder über Nacht gelaufen,
kommt ein `⚠` dazu — genau der Fall, für den die Menüleiste sich lohnt.

Im Klappmenü: die Aktionen für das, was gerade läuft, dann **Starten**,
**Countdown starten …**, **Pomodoro starten …** und **Zeit nachtragen …**
(jeweils mit Untermenüs für Projekt und Phase), sowie **Kalender …**,
**Statistik …** und **Einstellungen …**. Läuft schon ein Timer, wird er beim Starten
sauber gestoppt — dasselbe „Umschalten" wie im TUI.

Aufgebaut wird das von [SwiftBar](https://swiftbar.app) (`brew install --cask
swiftbar`). Das Plugin ist ein einzelnes Skript, `swiftbar/zeit.15s.py`,
das dieselben Markdown-Dateien liest — es gibt keinen zweiten Datenstand und
nichts zu synchronisieren. Die `15s` im Dateinamen ist das Aktualisierungs-
intervall; benenne die Datei um, wenn du es anders willst.

Damit SwiftBar nach dem Neustart wieder da ist: SwiftBar-Symbol anklicken →
**Preferences** → *Start at login*.

### Was ein Klick auf das Symbol tut

Einstellbar unter *Einstellungen → Klick auf Menüleiste* (TUI) bzw. *Klick auf
Symbol* in *Einstellungen …* (Menüleiste):

- **Klappmenü** (Standard) — wie oben beschrieben.
- **Popup** — unter dem Symbol klappt ein kleines Fenster auf. Darin läuft je
  nach Einstellung **Anzeige** das echte TUI oder die GUI (siehe unten).
  Klickst du daneben, verschwindet es. Mit **⧉** („Als Fenster öffnen“)
  bekommst du es zusätzlich als normales, verschiebbares Fenster.
- **Terminalfenster** — der Klick öffnet direkt ein kleines Terminalfenster mit
  dem TUI oben rechts (oder holt ein offenes nach vorn). Beim ersten Mal fragt
  macOS, ob SwiftBar das Terminal steuern darf.

In allen drei Fällen zeigt die Menüleiste weiter den aktuellen Stand. Im Popup-
und Terminal-Modus gibt es kein Klappmenü mehr — Einstellungen, auch das
Zurückstellen, findest du dann im TUI.

**Wie das Popup funktioniert:** SwiftBar zeigt dort eine Webseite. Darin läuft
xterm.js (in `web/`, MIT-Lizenz, liegt im Repo — läuft offline), ein Terminal-Emulator wie im Terminal von VS Code. `webterm.py` ist
ein kleiner lokaler Dienst (nur Python-Standardbibliothek), der `zeit` in einem
Pseudo-Terminal startet und es mit dem Popup verbindet. Er ist nur von deinem
Mac aus erreichbar (127.0.0.1) und verlangt ein zufälliges Kennwort
(`~/Library/Caches/zeit/webterm.json`).

**Farbschema:** Unter *Einstellungen → Farbschema* (TUI und Menüleisten-
Formular) wählst du eins der Profile des macOS-Terminals: Basic, Pro, Homebrew,
Ocean, Grass, Red Sands, Man Page, Novel, Silver Aerogel, Solid Colors, Clear
Dark, Clear Light. Es gilt für das Popup (eine Änderung wird nach ein paar
Sekunden sichtbar, auch bei offenem Popup) und für das zeit-Terminalfenster. Dort
bekommt nur dieses eine Fenster das Profil, deine anderen Terminals bleiben, wie
sie sind. *Standard* heißt: dunkles zeit-Aussehen im Popup bzw. dein eigenes
Standardprofil im Terminal. Das abgelöste Fenster („⧉ Als Fenster öffnen“)
bleibt immer dunkel. Die Farben stehen in `farbschemata.py`.

Eine Änderung ist im Popup sofort zu sehen: Der Dienst merkt, dass sich
`projekte.md` geändert hat, und schickt das neue Schema direkt über die
bestehende Verbindung.

Ist die **Akzentfarbe „Standard“**, passt sie sich im Popup und im
zeit-Terminalfenster dem Farbschema an, zum Beispiel Rot bei Man Page, Orange bei
Grass oder Weiß bei Ocean. Die Schrift in der markierten Zeile wird dabei
automatisch hell oder dunkel, damit sie lesbar bleibt. Eine selbst gewählte
Akzentfarbe (Blau, Grün …) bleibt, wie sie ist. In einem Terminal, das du selbst
öffnest, bleibt „Standard“ Türkis, weil zeit dessen Farben nicht kennt.

Zwei Eigenheiten von SwiftBar, die man ausprobieren musste:
- Die Popup-Seite muss eine **lokale Datei** sein
  (`~/Library/Caches/zeit/popup.html`, xterm.js steht direkt mit drin). Seiten
  über `http://` lädt SwiftBar zwar, zeigt sie im Popup aber nicht an.
- Hat das Symbol eine Farbe (`color=`), bleibt das Popup ebenfalls leer. Im
  Popup-Modus ist das ⏱ deshalb nicht eingefärbt.

### Die GUI (grafische Oberfläche)

Stellst du **Anzeige** auf *GUI* (im TUI unter *Einstellungen → Anzeige*, im
Formular der Menüleiste oder in der GUI selbst unter ⚙︎), zeigen Popup und
Fenster statt des TUI eine Oberfläche wie eine kleine macOS-App. Sie folgt
Hell/Dunkel des Systems und nutzt deine Akzentfarbe.

- **Timer:** oben groß, was gerade läuft (Timer, Countdown, Pomodoro, auch
  angehalten), mit den passenden Knöpfen. Darunter Projekt und Phase wählen und
  ▶ Timer, ⏳ Countdown, 🍅 Pomodoro oder ✎ Nachtragen starten. In den
  Auswahllisten kannst du mit „+ Neues Projekt …“ bzw. „+ Neue Phase …“ auch
  anlegen. Beim neuen Projekt schlägt zeit einen Ordner in deinem
  **Projektordner** vor (Einstellung, Standard `~/Documents`; er wird angelegt),
  mit „Ordner wählen …“ nimmst du einen anderen.
- **Nachtragen:** Datum, Von–Bis oder „Nur Tag“ mit Dauer. Darunter die
  Kalendertermine dieses Tages, jeder mit ✓ Übernehmen.
- **Kalender** und **Statistik:** dieselbe Seite wie im Kalenderfenster.
- **Einträge:** alle Projekte mit Summen, darunter jedes Projekt Tag für Tag.
  Ein Klick auf einen Eintrag öffnet ihn: Zeiten, Phase, Fokus und Notiz
  ändern oder den Eintrag löschen.
- **⚙︎ Einstellungen:** alles aus dem TUI, dazu die **Popup-Größe** (Kompakt
  380×560, Mittel 520×620, Groß 800×600; nur für die GUI, das TUI-Popup bleibt
  800×540).

Nach dem Beenden erscheinen Bericht und Feedback (😄 😐 ☹️ + Notiz) direkt in
der GUI. Ist ein Pomodoro-Fokus, eine Pause oder ein Countdown vorbei, während
du die GUI vor dir hast, fragt sie selbst und der Wecker öffnet keinen Dialog
(die Mitteilung mit Ton kommt trotzdem). Schließt du die GUI, ohne zu
reagieren, kommt der gewohnte Dialog.

**Tastatur:** Leertaste = Anhalten/Fortsetzen · S = Stoppen/Beenden ·
N = Timer mit der gewählten Auswahl starten · 1–4 = Reiter · ⌘, =
Einstellungen · Esc = Dialog schließen.

**Technik:** `web/gui.html`, `gui.css`, `gui.js` sind die Oberfläche,
`gui_api.py` ist die Schnittstelle dahinter. Sie benutzt dieselben Funktionen
wie Terminal und TUI, es gibt also keine zweite Logik. Im Popup sind die drei
Dateien zu einer lokalen Datei zusammengefügt
(`~/Library/Caches/zeit/gui-popup.html`). Weil das Popup bei jedem Öffnen neu
lädt, merkt sich die GUI Reiter und halb ausgefüllte Dialoge im Speicher des
Browsers.

### Warum `--ja`

Die Menüpunkte rufen `zeit --ja …` auf. Ohne Terminal kann niemand eine
Rückfrage beantworten, also beantwortet `--ja` alle Ja/Nein-Fragen mit Ja —
etwa „Timer stoppen und umschalten?". Rückfragen nach *Text* (der Ordner eines
neuen Projekts) bleiben absichtlich unbeantwortbar: Ordner anlegen soll man
gesehen haben. Ohne `--ja` bricht ein Aufruf ohne Terminal sauber ab und ändert
nichts.

## Wo liegt was

- **Pro Projekt:** `<Projektordner>/Zeiterfassung.md` — die eigentlichen Daten
- **Registry:** `~/.config/zeit/projekte.md` — welche Projekte gibt es, wo
  liegen sie, welche Phasen, deine Einstellungen und Kalender-Regeln. Auch das
  ist lesbares Markdown; du darfst es von Hand bearbeiten. (Frühere Versionen
  legten sie in `~/zeit/` ab — sie wird beim ersten Start automatisch umgezogen.)
- **Programm** (nach `install.sh` in `~/.local/share/zeit/`):
  - `zeit.py` — Logik und Befehle; als `~/.local/bin/zeit` im PATH
  - `tui.py` — die Oberfläche im Terminal
  - `tutorial.py` — die geführte Tour beim ersten Start
  - `pomodoro.py` — Wecker für Pomodoro, Countdown und Angehaltenes
  - `kalender.py` — Rechnungen für Kalender und Statistik
  - `termine.py` — liest Termine aus der Kalender-App
  - `kalender_schreiben.py` — schreibt erfasste Zeiten in den Kalender „zeit“
  - `kalender_fenster.py` — Kalender-/Statistikfenster
  - `feedback.py` — Feedback-Fenster nach einem Block
  - `farbschemata.py` — Farben für das TUI-Popup
  - `webterm.py` — lokaler Dienst für Popup und Fenster
  - `gui_api.py`, `web/gui.*` — die GUI
  - `swiftbar/zeit.15s.py` — die Menüleiste
  - `tests/` — Tests: `python3 -m unittest discover tests`
- **Zwischenspeicher:** `~/Library/Caches/zeit/` — darf jederzeit gelöscht werden.

## Das Dateiformat

```markdown
# Zeiterfassung — Bäckerei Müller

<!-- zeit-format: v3 -->

## Läuft gerade

- **design-phase** — gestartet 2026-08-29 09:12

## Einträge

| Datum      | Start | Ende  | Dauer | Phase        | Art | Fokus | Notiz |
|------------|-------|-------|-------|--------------|-----|-------|-------|
| 2026-08-28 | 09:00 | 11:30 | 2:30  | design-phase |     |
| 2026-08-28 | 13:15 | 13:40 | 0:25  | feedback     | 🍅  |
| 2026-08-27 | –     | –     | 3:00  | design-phase | ✎   |

<!-- zeit-ende -->
```

Die Spalte **Art** sagt, woher ein Eintrag stammt: leer = mit dem Timer
gemessen, 🍅 = Fokusblock eines Pomodoros, ⏳ = während eines Countdowns,
✎ = nachgetragen, 📅 = aus einem Kalendertermin übernommen. Ein zusätzliches ⏸ heißt: dieser Abschnitt endete durch
Anhalten. (Sie kam mit
Formatversion v2 dazu; ältere Dateien bekommen sie beim nächsten Schreiben
automatisch, alte Einträge bleiben dort leer.)

Drei Dinge, die man wissen sollte:

1. **Der laufende Timer steht im File.** Unter `## Läuft gerade` steht entweder
   `_(nichts)_` oder eine Zeile mit Phase und Startzeitpunkt. Deshalb weiß das
   Tool auch nach einem Neustart, was los ist — und du siehst es beim Draufschauen.
2. **Alles nach `<!-- zeit-ende -->` gehört dir.** Eigene Notizen dort bleiben
   unangetastet. Auch alles oberhalb von `## Läuft gerade` bleibt stehen.
3. **Ohne die Zeile `<!-- zeit-format: v… -->` fasst `zeit` eine Datei nicht an.**
   So kann es nie eine handgeschriebene Datei überschreiben.

Ging ein Eintrag über Mitternacht, steht in der Ende-Spalte z. B. `09:05 (+1)` —
also „09:05 am nächsten Tag".

## Neue Projekte und Phasen

Tippst du einen Namen, den es noch nicht gibt, fragt `zeit` nach, statt ihn
stillschweigend anzulegen — so wird ein Tippfehler nie zu einer neuen Kategorie.
Bei einem neuen Projekt wird zusätzlich nach dem Ordner gefragt; findet sich in
deinem **Projektordner** (Einstellung, Standard `~/Documents`) ein Ordner mit
passendem Namen, wird er vorgeschlagen und Enter übernimmt ihn. Die Projekte
können aber überall liegen — zeit braucht keine bestimmte Ordnerstruktur.

Zum Start gibt es nur drei neutrale Phasen: planung, umsetzung, abstimmung.
Eigene legst du einfach an — im TUI, in der GUI oder mit
`zeit start <projekt> <neue-phase>`. Nicht benötigte löschst du in
`~/.config/zeit/projekte.md`.

## Wenn du das Stoppen vergisst

Das Tool korrigiert **nie** von selbst. Es warnt nur — bei `zeit status`, beim
Stoppen und beim Starten eines neuen Timers —, sobald ein Timer über acht Stunden
oder über Mitternacht läuft. Die Korrektur machst du:

```bash
zeit stop --um 17:30
```

`HH:MM` gilt dabei als Uhrzeit **am Starttag**, nicht heute. Für Sonderfälle geht
auch `zeit stop --um "2026-08-28 17:30"`.

## Nur ein Timer gleichzeitig

Startest du etwas, während noch ein Timer läuft, zeigt `zeit` den laufenden an und
bietet an umzuschalten (alten stoppen, neuen starten). So kann dieselbe Stunde nie
zweimal in zwei Projekten landen. Lief der alte Timer weniger als eine Minute,
wird bewusst kein Eintrag geschrieben — das sind fast immer nur Vertipper.

## Auswerten

Für die schnellen Zahlen gibt es die Statistik (siehe oben). Für alles
Weitergehende kannst du einen KI-Assistenten (z. B. Claude) fragen:

> Lies alle `Zeiterfassung.md` aus meinen zeit-Projekten (siehe
> `~/.config/zeit/projekte.md`) und summiere die Stunden pro Projekt und Phase.

> Wie lange dauert die Design-Phase bei mir im Schnitt über alle Projekte?

## Etwas ändern

Fast alles stellst du in den Einstellungen ein (TUI, GUI oder Menüleiste). Ein
paar feste Werte stehen ganz oben in `zeit.py`: der Dateiname
`Zeiterfassung.md`, die Warnschwelle von acht Stunden und die Start-Phasen.

## Mitmachen

Fehler gefunden oder eine Idee? Gern als
[Issue](https://github.com/keyanthx/zeit/issues) oder Pull Request. Vor einem
Pull Request bitte die Tests laufen lassen:

```bash
python3 -m unittest discover tests
```

Sie laufen in einem leeren, vorübergehenden Benutzerordner — deine echten Daten
werden nie angefasst. zeit kommt bewusst ohne Abhängigkeiten aus (nur Python-
Standardbibliothek); xterm.js liegt fertig im Ordner `web/`.

## Lizenz

[MIT](LICENSE) — frei nutzbar, auch kommerziell. xterm.js steht ebenfalls unter
MIT ([web/LICENSE-xterm.txt](web/LICENSE-xterm.txt)).
