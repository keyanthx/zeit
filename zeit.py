#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zeit — Zeiterfassung fürs Terminal, deren einzige "Datenbank" lesbares Markdown ist.

Pro Projekt gibt es genau eine Datei:  <Projektordner>/Zeiterfassung.md
Darin steht oben, ob gerade ein Timer läuft, und darunter eine Tabelle mit
allen abgeschlossenen Einträgen. Mehr Zustand existiert nicht — was in den
Dateien steht, ist alles, was das Tool weiß.

Befehle:
    zeit start "<projekt>" "<phase>"   Timer starten
    zeit stop [--um HH:MM]             Timer stoppen (optional mit korrigierter Endzeit)
    zeit status                        Läuft gerade etwas?
    zeit abbrechen                     Laufenden Timer verwerfen, ohne Eintrag
    zeit countdown start "<projekt>" "<phase>" <2h | bis 17:00>
    zeit anhalten / zeit fortsetzen    Timer, Countdown oder Pomodoro-Fokus unterbrechen
    zeit nachtragen "<projekt>" "<phase>" <wann>
                                       Zeit nachträglich eintragen, z. B.
                                       "gestern 9:00-11:30" oder "2h ab 14:00"
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
from collections import namedtuple
from datetime import date, datetime, timedelta
from datetime import time as tageszeit
from pathlib import Path


# ===========================================================================
# Einstellungen — alles, was du vermutlich mal ändern willst, steht hier oben
# ===========================================================================

# Deine Konfiguration (welche Projekte gibt es, wo liegen sie, welche Phasen,
# Einstellungen) liegt getrennt vom Programm in ~/.config/zeit/ — so kann das
# Programm aktualisiert oder neu installiert werden, ohne dass deine Daten
# berührt werden. Sie ist bewusst selbst wieder Markdown.
BASIS = Path.home() / ".config" / "zeit"
CONFIG_DATEI = BASIS / "projekte.md"

# Früher lag die Konfiguration neben dem Programm in ~/zeit/. Sie wird beim
# ersten Start einmal an den neuen Ort umgezogen (siehe _alte_config_umziehen).
ALTE_CONFIG_DATEI = Path.home() / "zeit" / "projekte.md"

# So heißt die Zeiterfassungs-Datei innerhalb eines Projektordners.
DATEINAME = "Zeiterfassung.md"

# Ab dieser Dauer warnt das Tool, dass du das Stoppen vergessen haben könntest.
WARNUNG_AB_STUNDEN = 8

# Phasen, mit denen die Konfiguration beim ersten Mal befüllt wird — bewusst
# nur ein kleiner, neutraler Anfang. Eigene Phasen legst du jederzeit an
# (TUI, GUI oder einfach `zeit start <projekt> <neue-phase>`).
STANDARD_PHASEN = ["planung", "umsetzung", "abstimmung"]


# ===========================================================================
# Feste Bestandteile des Dateiformats — die ändert man besser nicht
# ===========================================================================

# Wird von `zeit --ja ...` gesetzt: beantwortet Ja/Nein-Rückfragen automatisch
# mit Ja. Gedacht für Aufrufe ohne Terminal — etwa aus der Menüleiste, wo
# niemand eine Rückfrage beantworten könnte. Freitext-Rückfragen (z. B. nach
# einem Ordner) bleiben bewusst unbeantwortbar: was dort passiert, soll man
# gesehen haben.
ANNAHME_JA = False

# Marker, an denen das Tool "seine" Dateien wiedererkennt. Fehlt der Marker,
# fasst das Tool die Datei nicht an — so kann es nie fremde Notizen zerstören.
FORMAT_MARKER = "<!-- zeit-format: v3 -->"
# Erkennt jede Version. v1 hatte 5 Spalten, v2 zusätzlich "Art", v3 zusätzlich
# "Fokus" und "Notiz" (das freiwillige Feedback nach einem Block).
# Alte Dateien werden gelesen und beim nächsten Schreiben zu v2.
FORMAT_RE = re.compile(r"<!-- zeit-format: v\d+ -->")
CONFIG_MARKER = "<!-- zeit-config: v1 -->"

# Ab hier gehört die Datei wieder dir: alles nach diesem Marker bleibt unangetastet.
ENDE_MARKER = "<!-- zeit-ende -->"

H_LAEUFT = "## Läuft gerade"
H_EINTRAEGE = "## Einträge"
NICHTS = "_(nichts)_"

SPALTEN = ["Datum", "Start", "Ende", "Dauer", "Phase", "Art", "Fokus", "Notiz"]

# Feedback nach einem Block (freiwillig): wie fokussiert, plus Notiz
FOKUS_WERTE = ["😄", "😐", "☹️"]
FOKUS_NAMEN = {"😄": "fokussiert", "😐": "so lala", "☹️": "abgelenkt"}

# Werte der Spalte "Art": woher ein Eintrag stammt
ART_NORMAL = ""          # mit dem Timer gemessen
ART_POMODORO = "🍅"      # Fokusblock eines Pomodoros
ART_NACHTRAG = "✎"       # nachträglich eingetragen
ART_COUNTDOWN = "⏳"     # während eines Countdowns gemessen
ART_KALENDER = "📅"      # aus einem Kalendertermin übernommen
ANGEHALTEN = "⏸"         # Zusatz, z. B. "🍅⏸": dieser Abschnitt endete durch
                         # Anhalten. Gezählt werden in der Auswertung nur ganze 🍅.

# Eine laufende Zeile sieht so aus:
#   - **design-phase** — gestartet 2026-08-29 09:12
LAEUFT_RE = re.compile(
    r"^-\s+\*\*(.+?)\*\*\s+—\s+gestartet\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*$"
)


# ===========================================================================
# Kleine Helfer
# ===========================================================================

def slug(text):
    """'Bäckerei Müller' -> 'baeckerei-mueller'.

    Dadurch ist es egal, ob du ein Projekt mit Großbuchstaben, Leerzeichen
    oder Umlauten tippst — es landet immer in derselben Kategorie.
    """
    text = text.strip().lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(alt, neu)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def fehler(text):
    """Meldung auf stderr ausgeben und mit Fehlercode beenden."""
    print(f"Fehler: {text}", file=sys.stderr)
    sys.exit(1)


def warnung(text):
    print(f"⚠  {text}")


def frage_ja_nein(text, standard=True):
    """Ja/Nein-Rückfrage. Ohne Terminal (z. B. in einem Skript) wird abgebrochen,
    damit das Tool nie unbemerkt hängen bleibt."""
    if ANNAHME_JA:
        print(f"{text} → automatisch: ja")
        return True
    if not sys.stdin.isatty():
        fehler(f"Rückfrage nicht möglich, weil kein Terminal da ist: {text}")
    hinweis = "[J/n]" if standard else "[j/N]"
    while True:
        antwort = input(f"{text} {hinweis} ").strip().lower()
        if antwort == "":
            return standard
        if antwort in ("j", "ja", "y", "yes"):
            return True
        if antwort in ("n", "nein", "no"):
            return False


def frage_text(text, standard=""):
    """Freitext-Rückfrage mit optionalem Vorschlag (Enter übernimmt ihn)."""
    if not sys.stdin.isatty():
        fehler(f"Rückfrage nicht möglich, weil kein Terminal da ist: {text}")
    hinweis = f"\n     [Enter übernimmt: {standard}]" if standard else ""
    antwort = input(f"{text}{hinweis}\n     > ").strip()
    return antwort or standard


def dauer_text(delta):
    """timedelta -> '2:30' (Stunden:Minuten, auf ganze Minuten gerundet)."""
    minuten = int(round(delta.total_seconds() / 60))
    return f"{minuten // 60}:{minuten % 60:02d}"


def _tabellenzellen(zeile):
    """'| a | b |' -> ['a', 'b']"""
    return [z.strip() for z in zeile.strip().strip("|").split("|")]


def _ist_trennzeile(zelle):
    """Erkennt die '|-----|-----|'-Zeile unter dem Tabellenkopf."""
    return bool(re.fullmatch(r":?-+:?", zelle))


def _breite(text):
    """Wie breit ein Text im Terminal/Editor erscheint. 🍅 belegt zwei Spalten,
    obwohl es nur ein Zeichen ist — sonst verrutscht die Tabelle."""
    breite = 0
    for zeichen in text:
        if unicodedata.combining(zeichen) or zeichen == "\ufe0f":
            continue
        breite += 2 if unicodedata.east_asian_width(zeichen) in ("W", "F") else 1
    return breite


def _auffuellen(text, breite):
    return text + " " * max(0, breite - _breite(text))


def _tabelle(kopf, zeilen):
    """Baut eine sauber ausgerichtete Markdown-Tabelle als Liste von Zeilen.

    Die Spaltenbreiten werden bei jedem Schreiben neu berechnet, damit die
    Tabelle auch nach dem 200. Eintrag noch ordentlich aussieht.
    """
    breiten = [len(s) for s in kopf]
    for zeile in zeilen:
        for i, zelle in enumerate(zeile):
            breiten[i] = max(breiten[i], _breite(zelle))

    def bau(zellen):
        return "| " + " | ".join(_auffuellen(z, breiten[i]) for i, z in enumerate(zellen)) + " |"

    ergebnis = [bau(kopf), "|" + "|".join("-" * (b + 2) for b in breiten) + "|"]
    ergebnis += [bau(z) for z in zeilen]
    return ergebnis


# ===========================================================================
# Konfiguration lesen und schreiben (~/zeit/projekte.md)
# ===========================================================================

def _alte_config_umziehen():
    """Zieht ~/zeit/projekte.md einmalig nach ~/.config/zeit/ um (frühere Versionen)."""
    if CONFIG_DATEI.exists() or not ALTE_CONFIG_DATEI.is_file():
        return
    import shutil
    BASIS.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ALTE_CONFIG_DATEI), str(CONFIG_DATEI))


def lade_config():
    """Liest die Registry. Gibt (projekte, phasen) zurück:
    projekte = dict  kurzname -> Ordner-Pfad,  phasen = Liste von Namen."""
    _alte_config_umziehen()
    if not CONFIG_DATEI.exists():
        return {}, list(STANDARD_PHASEN)

    projekte, phasen = {}, []
    abschnitt = None
    for zeile in CONFIG_DATEI.read_text(encoding="utf-8").splitlines():
        s = zeile.strip()
        if s.startswith("## "):
            abschnitt = s[3:].strip().lower()
            continue
        if abschnitt == "projekte" and s.startswith("|"):
            zellen = _tabellenzellen(s)
            if len(zellen) != 2:
                continue
            if zellen[0].lower() == "kurzname" or _ist_trennzeile(zellen[0]):
                continue  # Kopf- oder Trennzeile
            projekte[zellen[0]] = Path(zellen[1])
        elif abschnitt == "phasen" and s.startswith("- "):
            phasen.append(s[2:].strip())
    return projekte, phasen


# Einstellungen stehen als eigener Abschnitt in projekte.md, z. B.
#   - pomodoro-ton: Glass
# pomodoro-fokus/-kurze-pause/-lange-pause/-lange-pause-nach sind die zuletzt
# beim Start benutzten Werte — sie werden beim nächsten Start vorgeschlagen.
STANDARD_EINSTELLUNGEN = {
    "pomodoro-ton": "Glass",
    "pomodoro-verlaengern": 5,
    "pomodoro-fokus": 25,
    "pomodoro-kurze-pause": 5,
    "pomodoro-lange-pause": 15,
    "pomodoro-lange-pause-nach": 4,
    "countdown-art": "dauer",          # zuletzt benutzt: "dauer" oder "bis"
    "countdown-dauer": 60,             # zuletzt benutzte Dauer in Minuten
    "kalender-quellen": "",            # Namen der macOS-Kalender, durch ; getrennt
    "akzentfarbe": "Standard",         # TUI, Menüleiste und Kalenderfenster
    "kalender-schreiben": "aus",       # "an": erfasste Zeiten in den Kalender "zeit" spiegeln
    "menueleiste-klick": "menue",      # Klick aufs Symbol: menue / popup / terminal
    "farbschema": "Standard",          # Farben im Popup und im zeit-Terminalfenster (farbschemata.py)
    "anzeige": "tui",                  # was Popup und Fenster zeigen: tui / gui
    "popup-groesse": "mittel",         # Größe des GUI-Popups: kompakt / mittel / gross
    "projektordner": "~/Documents",    # hier schlägt zeit Ordner für neue Projekte vor
    "tutorial": "neu",                 # "fertig", sobald das Tutorial durch ist oder übersprungen wurde
}

# Akzentfarben: Name -> (Farbe für das Terminal, Farbe für Menüleiste/Fenster).
# Terminalfarben sind Nummern: 0–7 die Grundfarben, 208 ein Orange (nur in
# Terminals mit 256 Farben — sonst wird Gelb genommen).
# "Standard" = wie ursprünglich: Cyan im Terminal, Systemfarbe in der Menüleiste
# (None = nicht einfärben), das übliche Blau im Fenster.
AKZENTFARBEN = {
    "Standard": (6, None),
    "Blau": (4, "#3b82f6"), "Cyan": (6, "#06b6d4"), "Grün": (2, "#22c55e"),
    "Gelb": (3, "#eab308"), "Orange": (208, "#f97316"), "Rot": (1, "#ef4444"),
    "Magenta": (5, "#d946ef"),
}


# Was ein Klick auf das Menüleisten-Symbol öffnet
KLICK_ARTEN = {"menue": "Klappmenü", "popup": "Popup", "terminal": "Terminalfenster"}

# Was im Popup (und im Fenster „⧉ Als Fenster öffnen“) zu sehen ist
ANZEIGEN = {"tui": "TUI (Terminal-Oberfläche)", "gui": "GUI (grafische Oberfläche)"}

# Größe des GUI-Popups: Name -> (Breite, Höhe) in Punkten. Das TUI-Popup bleibt
# immer 800×540, weil das TUI eine Mindestbreite braucht.
POPUP_GROESSEN = {"kompakt": ("Kompakt", 380, 560), "mittel": ("Mittel", 520, 620),
                  "gross": ("Groß", 800, 600)}

# Die GUI meldet sich regelmäßig, solange sie sichtbar ist und den Fokus hat.
# Der Wecker zeigt dann keinen eigenen Dialog, sondern überlässt die Frage ihr.
GUI_SICHTBAR = Path.home() / "Library" / "Caches" / "zeit" / "gui-sichtbar"


def projekt_suchordner(einstellungen=None):
    """Der Ordner, in dem zeit für neue Projekte einen passenden Unterordner sucht
    bzw. einen neuen vorschlägt (Einstellung „Projektordner“)."""
    return Path((einstellungen or lade_einstellungen())["projektordner"]).expanduser()


def gui_offen():
    """Ist die GUI gerade vor deinen Augen (in den letzten 4 Sekunden gemeldet)?"""
    try:
        return datetime.now().timestamp() - GUI_SICHTBAR.stat().st_mtime < 4
    except OSError:
        return False


def akzentfarbe(einstellungen=None):
    """(Terminalfarbe, Hex-Farbe) der eingestellten Akzentfarbe.

    Akzentfarbe „Standard“ passt sich dem Farbschema an — aber nur dort, wo das
    Farbschema auch gilt: im Popup und im zeit-Terminalfenster. Die beiden setzen
    dafür ZEIT_FARBSCHEMA=1. In einem Terminal, das du selbst öffnest, bleibt
    es beim Türkis, denn dessen Farben kennt zeit nicht.
    """
    e = einstellungen or lade_einstellungen()
    name = e["akzentfarbe"]
    if name == "Standard" and os.environ.get("ZEIT_FARBSCHEMA"):
        import farbschemata
        return farbschemata.schema(e["farbschema"])["akzent"], None
    return AKZENTFARBEN.get(name, AKZENTFARBEN["Standard"])
TOENE = ["Glass", "Ping", "Hero", "Submarine", "Purr", "Pop", "Funk", "Tink",
         "Blow", "Bottle", "Frog", "Morse", "Sosumi", "Basso"]
KEIN_TON = "kein Ton"


def lade_einstellungen():
    """Liest den Abschnitt "Einstellungen". Fehlendes kommt aus den Vorgaben."""
    einstellungen = dict(STANDARD_EINSTELLUNGEN)
    if not CONFIG_DATEI.exists():
        return einstellungen
    abschnitt = None
    for zeile in CONFIG_DATEI.read_text(encoding="utf-8").splitlines():
        s = zeile.strip()
        if s.startswith("## "):
            abschnitt = s[3:].strip().lower()
        elif abschnitt == "einstellungen" and s.startswith("- ") and ":" in s:
            k, v = (x.strip() for x in s[2:].split(":", 1))
            if k in STANDARD_EINSTELLUNGEN:
                if isinstance(STANDARD_EINSTELLUNGEN[k], int):
                    try:
                        einstellungen[k] = int(v)
                    except ValueError:
                        pass            # Unsinn von Hand eingetragen: Vorgabe bleibt
                else:
                    einstellungen[k] = v
    return einstellungen


# Kalender-Regeln: welcher Termin zu welchem Projekt und welcher Phase gehört.
# Sie stehen als Tabelle in projekte.md; die erste passende Regel gilt.
#   Wenn: "titel enthält <Text>" (Groß-/Kleinschreibung egal) oder "kalender <Name>"
#   Projekt/Phase: ein Name, oder "?" = beim Übernehmen nachfragen
Regel = namedtuple("Regel", "art wert projekt phase")
FRAGEN = "?"


def _regel_lesen(wenn, projekt, phase):
    treffer = re.fullmatch(r"(titel enthält|titel|kalender)\s+(.+)", wenn.strip(), re.IGNORECASE)
    if not treffer:
        return None
    art = "kalender" if treffer[1].lower() == "kalender" else "titel"
    return Regel(art, treffer[2].strip(), projekt.strip() or FRAGEN, phase.strip() or FRAGEN)


def regel_text(regel):
    return f"{'titel enthält' if regel.art == 'titel' else 'kalender'} {regel.wert}"


def lade_regeln():
    if not CONFIG_DATEI.exists():
        return []
    regeln, abschnitt = [], None
    for zeile in CONFIG_DATEI.read_text(encoding="utf-8").splitlines():
        s = zeile.strip()
        if s.startswith("## "):
            abschnitt = s[3:].strip().lower()
        elif abschnitt == "kalender-regeln" and s.startswith("|"):
            zellen = _tabellenzellen(s)
            if len(zellen) == 3 and zellen[0].lower() != "wenn" and not _ist_trennzeile(zellen[0]):
                regel = _regel_lesen(*zellen)
                if regel:
                    regeln.append(regel)
    return regeln


def speichere_regeln(regeln):
    projekte, phasen = lade_config()
    speichere_config(projekte, phasen, regeln=regeln)


def regel_fuer(titel, kalender, regeln):
    """Die erste Regel, die auf einen Termin passt — oder None."""
    for regel in regeln:
        if regel.art == "kalender" and regel.wert.lower() == kalender.lower():
            return regel
        if regel.art == "titel" and regel.wert.lower() in titel.lower():
            return regel
    return None


def kalender_quellen(einstellungen=None):
    """Die ausgewählten macOS-Kalender als Liste von Namen."""
    text = (einstellungen or lade_einstellungen())["kalender-quellen"]
    return [n.strip() for n in text.split(";") if n.strip()]


def speichere_einstellungen(einstellungen):
    projekte, phasen = lade_config()
    speichere_config(projekte, phasen, einstellungen)


def speichere_config(projekte, phasen, einstellungen=None, regeln=None):
    """Schreibt die Registry komplett neu — sie ist klein und gehört dem Tool."""
    if einstellungen is None:
        einstellungen = lade_einstellungen()
    if regeln is None:
        regeln = lade_regeln()
    BASIS.mkdir(parents=True, exist_ok=True)
    zeilen = [
        "# zeit — Projekte und Phasen",
        "",
        "Diese Datei wird von `zeit` gelesen und geschrieben.",
        "Du kannst sie jederzeit von Hand bearbeiten.",
        "",
        CONFIG_MARKER,
        "",
        "## Projekte",
        "",
    ]
    zeilen += _tabelle(
        ["Kurzname", "Ordner"],
        # bewusst NICHT sortiert: die Reihenfolge in der Datei ist die,
        # die du im TUI unter "Übersicht" selbst festlegst
        [[name, str(pfad)] for name, pfad in projekte.items()],
    )
    zeilen += ["", "## Phasen", ""]
    zeilen += [f"- {p}" for p in phasen]
    zeilen += ["", "## Einstellungen", "",
               "Ton: einer der macOS-Töne (Glass, Ping, Hero …) oder „kein Ton“.",
               "Die Pomodoro-Dauern sind die zuletzt benutzten Werte — sie werden",
               "beim nächsten Start vorgeschlagen.", ""]
    zeilen += [f"- {k}: {v}" for k, v in einstellungen.items()]
    zeilen += ["", "## Kalender-Regeln", "",
               "Welcher Kalendertermin zu welchem Projekt und welcher Phase gehört.",
               "Die erste passende Regel gilt. „?“ heißt: beim Übernehmen nachfragen.",
               "Wenn: „titel enthält <Text>“ oder „kalender <Name>“.", ""]
    zeilen += _tabelle(["Wenn", "Projekt", "Phase"],
                       [[regel_text(r), r.projekt, r.phase] for r in regeln])
    CONFIG_DATEI.write_text("\n".join(zeilen) + "\n", encoding="utf-8")


# ===========================================================================
# Zeiterfassungs-Dateien lesen und schreiben
# ===========================================================================

class Zeitdatei:
    """Eine geparste Zeiterfassungs-Datei.

    kopf      Zeilen vor '## Läuft gerade'   (bleiben unangetastet)
    laeuft    (phase, startzeitpunkt) oder None
    eintraege Liste von 6er-Listen: Datum, Start, Ende, Dauer, Phase, Art
    rest      Zeilen nach dem Ende-Marker    (bleiben unangetastet)
    sitzung   Zustand einer Sitzung (Pomodoro, Countdown, angehaltener Timer) oder None
    """

    def __init__(self, kopf, laeuft, eintraege, rest, sitzung=None):
        self.kopf = kopf
        self.laeuft = laeuft
        self.eintraege = eintraege
        self.rest = rest
        self.sitzung = sitzung


# Eine Sitzung steht als eine Zeile unter "Läuft gerade". Ihre Art verrät der
# Anfang der Zeile, danach folgen Felder als name=wert, z. B.:
#
#   - 🍅 Pomodoro · zustand=fokus · phase=design-phase · nr=2 · seit=2026-09-24 09:30:12 ·
#     plan=25 · rest=0 · fokus=25 · kurz=5 · lang=15 · nach=4 · wecker=12345
#   - ⏳ Countdown · zustand=laeuft · phase=design-phase · seit=… · plan=90 · rest=0 · wecker=…
#   - ⏸ Timer angehalten · zustand=angehalten · phase=design-phase · seit=… · wecker=…
#
# zustand  Pomodoro: fokus / pause / angehalten — Countdown: laeuft / angehalten
#          — angehaltener normaler Timer: angehalten
# phase    zu welcher Phase die Sitzung gehört (in Pausen und beim Anhalten läuft
#          kein Timer, der sie sonst verraten würde)
# seit     wann der jetzige Abschnitt begann (sekundengenau); beim Anhalten: seit
#          wann angehalten ist
# beginn   wann die ganze Sitzung begann (für den Bericht am Ende)
# plan     geplante Minuten ab "seit" ("Noch X min" erhöht ihn; kann Nachkommastellen
#          haben, weil nach dem Fortsetzen genau die Restzeit weiterläuft)
# rest     nur beim Anhalten: wie viele Sekunden noch übrig waren (negativ = überzogen)
# nr, fokus, kurz, lang, nach   nur Pomodoro: der wievielte, und die Einstellungen
# wecker   Prozessnummer des Weckers, der die Meldungen verschickt
SITZUNG_PRAEFIXE = {"pomodoro": "- 🍅 Pomodoro", "countdown": "- ⏳ Countdown",
                    "timer": "- ⏸ Timer angehalten"}
SITZUNG_FELDER = {
    "pomodoro": ["zustand", "phase", "nr", "seit", "beginn", "plan", "rest", "fokus", "kurz",
                 "lang", "nach", "wecker"],
    "countdown": ["zustand", "phase", "seit", "beginn", "plan", "rest", "wecker"],
    "timer": ["zustand", "phase", "seit", "wecker"],
}
SITZUNG_ZUSTAENDE = {"pomodoro": ("fokus", "pause", "angehalten"),
                     "countdown": ("laeuft", "angehalten"), "timer": ("angehalten",)}
_GANZZAHLEN = {"nr", "rest", "fokus", "kurz", "lang", "nach", "wecker"}


def _sitzung_zeile(z):
    teile = [SITZUNG_PRAEFIXE[z["typ"]]]
    for k in SITZUNG_FELDER[z["typ"]]:
        wert = z.get(k, 0)
        if k in ("seit", "beginn"):
            wert = f"{z.get(k) or z['seit']:%Y-%m-%d %H:%M:%S}"
        elif k == "plan":
            wert = f"{round(wert, 2):g}"          # 25 statt 25.0, 12.5 bleibt
        teile.append(f"{k}={wert}")
    return " · ".join(teile)


def _sitzung_lesen(zeile):
    """Sitzungs-Zeile -> dict (mit "typ"), oder None wenn es keine (lesbare) ist."""
    zeile = zeile.strip()
    typ = next((t for t, praefix in SITZUNG_PRAEFIXE.items() if zeile.startswith(praefix)), None)
    if typ is None:
        return None
    werte = {}
    for teil in zeile[len(SITZUNG_PRAEFIXE[typ]):].split("·"):
        if "=" in teil:
            k, v = teil.split("=", 1)
            werte[k.strip()] = v.strip()
    try:
        z = {"typ": typ, "zustand": werte["zustand"], "phase": werte["phase"],
             "seit": datetime.strptime(werte["seit"], "%Y-%m-%d %H:%M:%S")}
        for k in SITZUNG_FELDER[typ]:
            if k in _GANZZAHLEN:
                z[k] = int(werte.get(k, 0))       # fehlt in älteren Zeilen -> 0
            elif k == "plan":
                z[k] = float(werte.get(k, 0))
            elif k == "beginn":                   # fehlt in älteren Zeilen -> seit
                z[k] = (datetime.strptime(werte["beginn"], "%Y-%m-%d %H:%M:%S")
                        if "beginn" in werte else z["seit"])
    except (KeyError, ValueError):
        return None
    return z if z["zustand"] in SITZUNG_ZUSTAENDE[typ] else None


def _neuer_kopf(titel):
    return [f"# Zeiterfassung — {titel}", "", FORMAT_MARKER]


def zeitdatei_pfad(ordner):
    return ordner / DATEINAME


def lese_zeitdatei(pfad, titel):
    """Liest eine Zeiterfassungs-Datei ein. Existiert sie nicht, wird eine
    leere Struktur zurückgegeben (geschrieben wird erst später)."""
    if not pfad.exists():
        return Zeitdatei(_neuer_kopf(titel), None, [], [])

    text = pfad.read_text(encoding="utf-8")
    if not FORMAT_RE.search(text):
        fehler(
            f"{pfad} existiert schon, stammt aber nicht von `zeit`.\n"
            f"       Ich fasse sie nicht an. Benenne sie um oder füge die Zeile\n"
            f"       {FORMAT_MARKER} oben ein."
        )

    kopf, laeuft_roh, eintraege_roh, rest = [], [], [], []
    ziel = kopf
    hinter_ende = False
    for zeile in text.splitlines():
        if hinter_ende:
            rest.append(zeile)
            continue
        s = zeile.strip()
        if s == H_LAEUFT:
            ziel = laeuft_roh
            continue
        if s == H_EINTRAEGE:
            ziel = eintraege_roh
            continue
        if s == ENDE_MARKER:
            hinter_ende = True
            continue
        ziel.append(zeile)

    # laufenden Timer und ggf. Pomodoro-Sitzung heraussuchen
    laeuft, sitzung = None, None
    for zeile in laeuft_roh:
        treffer = LAEUFT_RE.match(zeile.strip())
        if treffer and laeuft is None:
            phase, datum, uhrzeit = treffer.groups()
            laeuft = (phase, datetime.strptime(f"{datum} {uhrzeit}", "%Y-%m-%d %H:%M"))
        sitzung = sitzung or _sitzung_lesen(zeile)

    # Tabellenzeilen einsammeln
    eintraege = []
    for zeile in eintraege_roh:
        s = zeile.strip()
        if not s.startswith("|"):
            continue
        zellen = _tabellenzellen(s)
        if not zellen or zellen[0] == SPALTEN[0] or _ist_trennzeile(zellen[0]):
            continue  # Kopf- oder Trennzeile
        if 5 <= len(zellen) < len(SPALTEN):
            # ältere Formatversion: fehlende Spalten (Art, Fokus, Notiz) leer
            zellen += [""] * (len(SPALTEN) - len(zellen))
        if len(zellen) != len(SPALTEN):
            fehler(
                f"{pfad}: diese Tabellenzeile hat {len(zellen)} statt "
                f"{len(SPALTEN)} Spalten:\n       {s}"
            )
        eintraege.append(zellen)

    return Zeitdatei(kopf, laeuft, eintraege, rest, sitzung)


def schreibe_zeitdatei(pfad, datei):
    """Schreibt die Datei neu — Kopf und Rest werden dabei wörtlich übernommen."""
    kopf = "\n".join(datei.kopf).rstrip() or "\n".join(_neuer_kopf(pfad.parent.name))
    kopf = FORMAT_RE.sub(FORMAT_MARKER, kopf)      # alte Formatversion -> v2
    laeuft_zeilen = []
    if datei.laeuft:
        phase, start = datei.laeuft
        laeuft_zeilen.append(f"- **{phase}** — gestartet {start:%Y-%m-%d %H:%M}")
    if datei.sitzung:
        laeuft_zeilen.append(_sitzung_zeile(datei.sitzung))
    laeuft_block = "\n".join(laeuft_zeilen) or NICHTS
    tabelle = "\n".join(_tabelle(SPALTEN, datei.eintraege))
    rest = "\n".join(datei.rest).strip()

    teile = [kopf, H_LAEUFT, laeuft_block, H_EINTRAEGE, tabelle, ENDE_MARKER]
    if rest:
        teile.append(rest)

    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text("\n\n".join(teile) + "\n", encoding="utf-8")
    # Ist "In Kalender schreiben" an, gleicht ein Hintergrundprozess den
    # Kalender "zeit" ab (siehe kalender_schreiben.py) — niemand muss warten.
    try:
        # zeit.py kann über den Symlink ~/.local/bin/zeit laufen — dann liegt sein
        # Ordner nicht automatisch im Suchpfad. Also ausdrücklich eintragen.
        ordner = str(Path(__file__).resolve().parent)
        if ordner not in sys.path:
            sys.path.insert(0, ordner)
        sys.modules.setdefault("zeit", sys.modules[__name__])
        import kalender_schreiben
        kalender_schreiben.anstossen()
    except Exception:
        pass            # die Zeiterfassung selbst darf daran nie scheitern


def ist_fremde_datei(pfad):
    """True, wenn die Datei zwar existiert, aber nicht von `zeit` stammt."""
    return pfad.exists() and not FORMAT_RE.search(pfad.read_text(encoding="utf-8"))


def finde_aktiv(projekte, warner=warnung):
    """Wie finde_laufenden_timer, findet aber auch eine Pomodoro-Sitzung, die
    gerade in der Pause ist (dann läuft kein Timer, aber die Sitzung schon).
    Gibt (kurzname, ordner, zeitdatei) zurück oder None."""
    for name, ordner in projekte.items():
        pfad = zeitdatei_pfad(ordner)
        if not pfad.exists():
            continue
        if ist_fremde_datei(pfad):
            warner(f"{pfad} stammt nicht von `zeit` und wird übersprungen.")
            continue
        datei = lese_zeitdatei(pfad, ordner.name)
        if datei.laeuft or datei.sitzung:
            return name, ordner, datei
    return None


def finde_laufenden_timer(projekte, warner=warnung):
    """Sucht in ALLEN Projektdateien nach einem laufenden Timer.

    Das Tool hat keinen eigenen Speicher: die Markdown-Dateien sind die
    einzige Quelle der Wahrheit, also wird bei Bedarf einmal durchgeschaut.
    Gibt (kurzname, ordner, zeitdatei) zurück oder None.
    """
    for name, ordner in projekte.items():
        pfad = zeitdatei_pfad(ordner)
        if not pfad.exists():
            continue
        # Fremde Datei? Hier nur überspringen und melden. Ein hartes Abbrechen
        # wäre falsch: sonst würde eine einzige fremde Datei jeden Befehl für
        # ALLE Projekte blockieren. Der Abbruch kommt erst, wenn du genau
        # dieses Projekt benutzt (dann greift lese_zeitdatei).
        # `warner` ist auswechselbar, damit das TUI die Meldung einsammeln
        # kann, statt sie mitten in die Oberfläche zu drucken.
        if ist_fremde_datei(pfad):
            warner(f"{pfad} stammt nicht von `zeit` und wird übersprungen.")
            continue
        datei = lese_zeitdatei(pfad, ordner.name)
        if datei.laeuft:
            return name, ordner, datei
    return None


def _datum_aus(text):
    """'2026-08-28' -> date, oder None wenn unlesbar."""
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _minuten_aus(text):
    """'2:30' -> 150, oder None wenn unlesbar."""
    treffer = re.fullmatch(r"(\d+):([0-5]\d)", text.strip())
    return int(treffer[1]) * 60 + int(treffer[2]) if treffer else None


Eintrag = namedtuple("Eintrag", "projekt datum minuten phase art fokus notiz start")


def alle_eintraege(projekte, warner=warnung):
    """Liest alle abgeschlossenen Einträge aus allen Projektdateien ein.

    Rückgabe: Liste von Eintrag(projekt, datum, minuten, phase, art). Unlesbare Zeilen
    werden gemeldet und übersprungen, statt alles abzubrechen — die Dateien
    darfst du schließlich von Hand bearbeiten.
    """
    ergebnis = []
    for name, ordner in projekte.items():
        pfad = zeitdatei_pfad(ordner)
        if not pfad.exists():
            continue
        if ist_fremde_datei(pfad):
            warner(f"{pfad} stammt nicht von `zeit` und wird übersprungen.")
            continue
        for zellen in lese_zeitdatei(pfad, ordner.name).eintraege:
            datum = _datum_aus(zellen[0])
            minuten = _minuten_aus(zellen[3])
            if datum is None or minuten is None:
                warner(f"{pfad}: unlesbare Zeile: {' | '.join(zellen)}")
                continue
            ergebnis.append(Eintrag(name, datum, minuten, zellen[4], zellen[5],
                                    zellen[6], zellen[7], zellen[1]))
    return ergebnis


def phase_umbenennen(projekte, alt, neu):
    """Benennt eine Phase in allen vorhandenen Einträgen um.

    Wird beim Umbenennen im TUI gebraucht: sonst zerfiele eine Phase in zwei
    Kategorien und die Auswertung wäre still falsch.
    Rückgabe: Anzahl der geänderten Einträge.
    """
    anzahl = 0
    for name, ordner in projekte.items():
        pfad = zeitdatei_pfad(ordner)
        if not pfad.exists() or ist_fremde_datei(pfad):
            continue
        datei = lese_zeitdatei(pfad, ordner.name)
        geaendert = False
        for zellen in datei.eintraege:
            if zellen[4] == alt:
                zellen[4] = neu
                anzahl += 1
                geaendert = True
        if datei.laeuft and datei.laeuft[0] == alt:
            datei.laeuft = (neu, datei.laeuft[1])
            geaendert = True
        if datei.sitzung and datei.sitzung["phase"] == alt:
            datei.sitzung["phase"] = neu
            geaendert = True
        if geaendert:
            schreibe_zeitdatei(pfad, datei)
    return anzahl


def pruefe_vergessen(start, jetzt=None):
    """Warnt, wenn ein Timer verdächtig lange läuft — ändert aber nichts."""
    jetzt = jetzt or datetime.now()
    dauer = jetzt - start
    verdaechtig = False
    if start.date() != jetzt.date():
        warnung(f"Der Timer läuft seit dem {start:%d.%m.%Y}, also über Mitternacht hinaus.")
        verdaechtig = True
    if dauer >= timedelta(hours=WARNUNG_AB_STUNDEN):
        warnung(f"Er läuft schon {dauer_text(dauer)} Stunden — Stoppen vergessen?")
        verdaechtig = True
    if verdaechtig:
        print("   Es wird nichts automatisch korrigiert. Mit richtiger Endzeit stoppen:")
        print("       zeit stop --um 17:30     (HH:MM gilt als Uhrzeit am Starttag)")
    return verdaechtig


# ===========================================================================
# Befehle
# ===========================================================================

def _ordner_vorschlag(kurzname):
    """Sucht im Projektordner (Einstellung) einen Ordner, dessen Name zum Kurznamen passt."""
    suchordner = projekt_suchordner()
    if not suchordner.is_dir():
        return None
    for kandidat in sorted(suchordner.iterdir()):
        if kandidat.is_dir() and slug(kandidat.name) == kurzname:
            return kandidat
    return None


def _projekt_anlegen(kurzname, projekte, phasen):
    """Fragt nach dem Ordner für ein neues Projekt und speichert es."""
    vorschlag = _ordner_vorschlag(kurzname)
    eingabe = frage_text("   In welchem Ordner soll die Zeiterfassung liegen?",
                         str(vorschlag) if vorschlag else "")
    if not eingabe:
        fehler("Ohne Ordner kann das Projekt nicht angelegt werden.")
    # .resolve() macht aus einer relativen Eingabe einen eindeutigen absoluten
    # Pfad — sonst hinge in der Registry ein Pfad, der davon abhängt, in welchem
    # Ordner du gerade standest, als du das Projekt angelegt hast.
    ordner = Path(eingabe).expanduser().resolve()
    if not ordner.exists():
        if not frage_ja_nein(f"   {ordner} existiert nicht. Anlegen?"):
            sys.exit(0)
        ordner.mkdir(parents=True)
    projekte[kurzname] = ordner
    speichere_config(projekte, phasen)
    print(f"✓ Projekt '{kurzname}' gespeichert → {ordner}")
    return ordner


def _eintragszeile(start, ende, phase, art=ART_NORMAL):
    """Baut eine Tabellenzeile: Datum, Start, Ende, Dauer, Phase.

    Geht der Eintrag über Mitternacht, wird das in der Ende-Spalte sichtbar
    gemacht, z. B. '09:05 (+1)' — sonst wäre die Zeile irreführend.
    """
    tage = (ende.date() - start.date()).days
    return [
        f"{start:%Y-%m-%d}",
        f"{start:%H:%M}",
        f"{ende:%H:%M}" + (f" (+{tage})" if tage else ""),
        dauer_text(ende - start),
        phase,
        art,
        "",          # Fokus — kommt ggf. mit dem Feedback
        "",          # Notiz
    ]


# ===========================================================================
# Nachtragen
# ===========================================================================

WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WOCHENTAGE_LANG = ["montag", "dienstag", "mittwoch", "donnerstag",
                   "freitag", "samstag", "sonntag"]

# Eine Uhrzeit, wie Menschen sie tippen: "9", "9:30", "9.30", "14 Uhr"
_UHRZEIT = r"(\d{1,2})(?:[:.](\d{2}))?(?:\s*uhr)?"

BEISPIELE = ("9:00-11:30  ·  2h ab 14:00  ·  1,5h bis 17:00  ·  gestern 10-12"
             "  ·  gestern 3h (nur Tag)")

# Ergebnis eines Nachtrags. Bei "nur Tag" (ohne Uhrzeiten) sind start und
# ende None — dann gibt es nur das Datum und die Dauer in Minuten.
Nachtrag = namedtuple("Nachtrag", "datum start ende minuten")
NUR_TAG = "–"   # steht in der Tabelle bei Start und Ende, wenn es keine Uhrzeit gibt


def _uhrzeit(stunde, minute):
    s, m = int(stunde), int(minute or 0)
    if s > 23 or m > 59:
        raise ValueError(f"{stunde}:{minute or '00'} ist keine gültige Uhrzeit.")
    return tageszeit(s, m)


def _dauer_parsen(text):
    """'2h', '1.5h', '2 stunden', '2h30', '90min', '2:30' -> Minuten. Sonst None."""
    text = text.strip()
    treffer = re.fullmatch(r"(\d+):(\d{2})", text)
    if treffer:
        return int(treffer[1]) * 60 + int(treffer[2])
    treffer = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*(?:h|std|stunden?)\.?(?:\s*(\d+)\s*(?:m|min|minuten)?)?", text)
    if treffer:
        return int(round(float(treffer[1]) * 60)) + int(treffer[2] or 0)
    treffer = re.fullmatch(r"(\d+)\s*(?:m|min|minuten)", text)
    if treffer:
        return int(treffer[1])
    return None


def _datum_herausloesen(text, datum, heute):
    """Sucht eine Datumsangabe im Text. Rückgabe: (datum, rest_ohne_datum).

    Versteht: heute, gestern, vorgestern, Wochentage ("montag" = der letzte
    Montag, heute eingeschlossen), 23.9., 23.9.2026 und 2026-09-23.
    Ohne Angabe bleibt das übergebene Datum stehen.
    """
    for wort, tage in (("vorgestern", 2), ("gestern", 1), ("heute", 0)):
        if re.search(rf"\b{wort}\b", text):
            return heute - timedelta(days=tage), re.sub(rf"\b{wort}\b", " ", text)

    for nummer, name in enumerate(WOCHENTAGE_LANG):
        if re.search(rf"\b{name}\b", text):
            zurueck = (heute.weekday() - nummer) % 7
            return heute - timedelta(days=zurueck), re.sub(rf"\b{name}\b", " ", text)

    try:
        treffer = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
        if treffer:
            gefunden = date(int(treffer[1]), int(treffer[2]), int(treffer[3]))
            return gefunden, text.replace(treffer[0], " ")

        # "23.9." oder "23.9.2026" — der Punkt nach dem Monat ist Pflicht,
        # sonst wäre "1.5h" (anderthalb Stunden) ein Datum.
        treffer = re.search(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})?(?![\d.])", text)
        if treffer:
            jahr = int(treffer[3]) if treffer[3] else heute.year
            if jahr < 100:
                jahr += 2000
            gefunden = date(jahr, int(treffer[2]), int(treffer[1]))
            # "30.12." am 2. Januar meint den Dezember davor
            if not treffer[3] and gefunden > heute:
                gefunden = gefunden.replace(year=jahr - 1)
            return gefunden, text.replace(treffer[0], " ")
    except ValueError:
        raise ValueError("Dieses Datum gibt es nicht.")

    return datum, text


def nachtrag_parsen(text, datum=None, heute=None):
    """Versteht eine Zeitangabe wie ein Mensch sie tippt.

    Rückgabe: ein Nachtrag (datum, start, ende, minuten). Bei Unverständlichem
    ein ValueError mit einer Erklärung, die man direkt anzeigen kann.

      9:00-11:30          von–bis
      2h ab 14:00         Dauer + Anfang  -> Ende wird ausgerechnet
      1,5h bis 17:00      Dauer + Ende    -> Anfang wird ausgerechnet
      gestern 10-12       davor oder dahinter darf ein Datum stehen
      gestern 3h          nur Tag und Dauer, ohne Uhrzeiten

    `datum` ist der Tag, der gilt, wenn im Text keiner steht (Standard: heute).
    """
    heute = heute or date.today()
    datum = datum or heute
    t = " " + text.strip().lower().replace(",", ".").replace("–", "-").replace("—", "-") + " "

    datum, t = _datum_herausloesen(t, datum, heute)
    t = re.sub(r"\b(für|fuer|lang|um|von|am)\b", " ", t)   # Füllwörter
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        raise ValueError(f"Es fehlt die Uhrzeit oder die Dauer.\nBeispiele: {BEISPIELE}")

    von_bis = re.fullmatch(rf"{_UHRZEIT}\s*(?:-|bis)\s*{_UHRZEIT}", t)
    if von_bis:
        start = datetime.combine(datum, _uhrzeit(von_bis[1], von_bis[2]))
        ende = datetime.combine(datum, _uhrzeit(von_bis[3], von_bis[4]))
        if ende == start:
            raise ValueError("Anfang und Ende sind gleich — die Dauer ist null.")
        if ende < start:
            # Ende vor Anfang: entweder über Mitternacht (23:00-01:00) oder
            # ein Tippfehler (9-8 würde sonst still zu 23 Stunden). Nur kurze
            # Nachtschichten werden als "über Mitternacht" gelesen.
            ende += timedelta(days=1)
            if ende - start > timedelta(hours=12):
                raise ValueError("Das Ende liegt vor dem Anfang.\n"
                                 "Über Mitternacht geht, z. B. 23:00-01:00.")
    else:
        ab = re.search(rf"\bab\s*{_UHRZEIT}", t)
        bis = re.search(rf"\bbis\s*{_UHRZEIT}", t)
        if not ab and not bis and _dauer_parsen(t) is not None:
            return _nur_tag(datum, _dauer_parsen(t), heute)
        if bool(ab) == bool(bis):
            raise ValueError(f"Das verstehe ich nicht.\nBeispiele: {BEISPIELE}")
        anker = ab or bis
        rest = (t[:anker.start()] + " " + t[anker.end():]).strip()
        minuten = _dauer_parsen(rest)
        if minuten is None:
            raise ValueError(f"'{rest or '?'}' ist keine Dauer, die ich kenne.\n"
                             "Beispiele: 2h  ·  1,5h  ·  2h30  ·  90min")
        punkt = datetime.combine(datum, _uhrzeit(anker[1], anker[2]))
        if ab:
            start, ende = punkt, punkt + timedelta(minutes=minuten)
        else:
            start, ende = punkt - timedelta(minutes=minuten), punkt

    if ende - start <= timedelta(0):
        raise ValueError("Die Dauer ist null.")
    if ende - start > timedelta(hours=24):
        raise ValueError("Mehr als 24 Stunden am Stück — vermutlich ein Tippfehler.")
    if ende > datetime.now() + timedelta(minutes=1):
        raise ValueError(f"Das Ende ({ende:%d.%m. %H:%M}) liegt in der Zukunft.\n"
                         "Nachtragen geht nur für Vergangenes.")
    return Nachtrag(start.date(), start, ende, int((ende - start).total_seconds() // 60))


def _nur_tag(datum, minuten, heute):
    """Nachtrag ohne Uhrzeiten: nur ein Tag und eine Dauer."""
    if minuten <= 0:
        raise ValueError("Die Dauer ist null.")
    if minuten > 24 * 60:
        raise ValueError("Mehr als 24 Stunden an einem Tag — vermutlich ein Tippfehler.")
    if datum > heute:
        raise ValueError("Das Datum liegt in der Zukunft.\nNachtragen geht nur für Vergangenes.")
    return Nachtrag(datum, None, None, minuten)


def beschreibe_nachtrag(n):
    """-> 'Di 23.09.2026, 09:00–11:30 (2:30 h)' oder 'Di 23.09.2026, ohne Uhrzeit (3:00 h)'"""
    if n.start is None:
        return (f"{WOCHENTAGE_KURZ[n.datum.weekday()]} {n.datum:%d.%m.%Y}, "
                f"ohne Uhrzeit ({dauer_text(timedelta(minutes=n.minuten))} h)")
    return beschreibe_zeitraum(n.start, n.ende)


def konflikte_fuer(projekte, n):
    """Überschneidungen eines Nachtrags. Ohne Uhrzeiten lässt sich keine
    Überschneidung feststellen — dann bleibt die Liste leer."""
    return [] if n.start is None else ueberschneidungen(projekte, n.start, n.ende)


def beschreibe_zeitraum(start, ende):
    """-> 'Di 23.09.2026, 09:00–11:30 (2:30 h)'"""
    tage = (ende.date() - start.date()).days
    plus = f" (+{tage} Tag{'e' if tage > 1 else ''})" if tage else ""
    return (f"{WOCHENTAGE_KURZ[start.weekday()]} {start:%d.%m.%Y}, "
            f"{start:%H:%M}–{ende:%H:%M}{plus} ({dauer_text(ende - start)} h)")


def _zeitraum_aus(zellen):
    """Tabellenzeile -> (start, ende) als datetime, oder None wenn unlesbar."""
    treffer = re.fullmatch(r"(\d{2}:\d{2})(?:\s*\(\+(\d+)\))?", zellen[2].strip())
    if not treffer:
        return None
    try:
        start = datetime.strptime(f"{zellen[0]} {zellen[1]}", "%Y-%m-%d %H:%M")
        ende = datetime.strptime(f"{zellen[0]} {treffer[1]}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return start, ende + timedelta(days=int(treffer[2] or 0))


def ueberschneidungen(projekte, start, ende):
    """Findet vorhandene Einträge (in ALLEN Projekten), die sich mit dem
    Zeitraum überschneiden — sonst würde dieselbe Stunde doppelt gezählt.
    Rückgabe: Liste lesbarer Beschreibungen, leer wenn alles frei ist."""
    treffer = []
    for name, ordner in projekte.items():
        pfad = zeitdatei_pfad(ordner)
        if not pfad.exists() or ist_fremde_datei(pfad):
            continue
        datei = lese_zeitdatei(pfad, ordner.name)
        for zellen in datei.eintraege:
            zeitraum = _zeitraum_aus(zellen)
            if zeitraum and zeitraum[0] < ende and start < zeitraum[1]:
                treffer.append(f"{name} / {zellen[4]}: {zellen[0]} {zellen[1]}–{zellen[2]}")
        if datei.laeuft and datei.laeuft[1] < ende:
            treffer.append(f"{name} / {datei.laeuft[0]}: läuft seit "
                           f"{datei.laeuft[1]:%d.%m. %H:%M}")
    return treffer


def nachtragen(ordner, phase, n, art=ART_NACHTRAG):
    """Trägt einen Zeitraum ein — chronologisch an der richtigen Stelle.

    Beim Stoppen kommt ein Eintrag immer ans Ende, das passt von selbst.
    Ein Nachtrag gehört aber meist weiter nach oben; die Tabelle soll
    zeitlich geordnet bleiben, damit sie lesbar bleibt.
    """
    pfad = zeitdatei_pfad(ordner)
    datei = lese_zeitdatei(pfad, ordner.name)
    if n.start is None:
        zeile = [f"{n.datum:%Y-%m-%d}", NUR_TAG, NUR_TAG,
                 dauer_text(timedelta(minutes=n.minuten)), phase, art, "", ""]
    else:
        zeile = _eintragszeile(n.start, n.ende, phase, art)
    # (Ein "–" sortiert hinter jede Uhrzeit: Einträge ohne Uhrzeit stehen am
    # Ende ihres Tages.)
    pos = len(datei.eintraege)
    while pos > 0 and (datei.eintraege[pos - 1][0], datei.eintraege[pos - 1][1]) > (zeile[0], zeile[1]):
        pos -= 1
    datei.eintraege.insert(pos, zeile)
    schreibe_zeitdatei(pfad, datei)
    return pfad


# ===========================================================================
# Pomodoro
# ===========================================================================
#
# Eine Sitzung ist eine Betriebsart des normalen Timers: im Fokus läuft ein
# ganz normaler Timer (sein Eintrag bekommt 🍅), in der Pause läuft keiner.
# Alle Wechsel passieren auf Klick. Meldungen verschickt ein kleiner Wecker-
# Prozess (pomodoro.py), der nur während einer Sitzung existiert.

POMODORO_GRENZEN = {"fokus": (1, 240), "kurz": (1, 120), "lang": (1, 180), "nach": (1, 12)}
POMODORO_NAMEN = {"fokus": "Fokus", "kurz": "Kurze Pause", "lang": "Lange Pause",
                  "nach": "Lange Pause nach"}


def pomodoro_werte_pruefen(werte):
    """werte: dict mit fokus, kurz, lang, nach. Wirft ValueError mit Erklärung."""
    for k, (unten, oben) in POMODORO_GRENZEN.items():
        if not unten <= int(werte[k]) <= oben:
            einheit = "Pomodoros" if k == "nach" else "Minuten"
            raise ValueError(f"{POMODORO_NAMEN[k]}: {unten} bis {oben} {einheit}.")


def sitzung_ende(z):
    return z["seit"] + timedelta(minutes=z["plan"])


def ist_lange_pause(z):
    """Nach jedem N-ten Pomodoro kommt die lange Pause."""
    return z["nr"] % z["nach"] == 0


def satz_position(z):
    """Der wievielte Pomodoro im aktuellen Satz (1 … nach)."""
    return (z["nr"] - 1) % z["nach"] + 1


def _rest_text(sekunden):
    """Restzeit lesbar: 'noch 12 min', 'noch 1:23 h' oder '+3 min' (überzogen)."""
    if sekunden <= 0:
        return f"+{int(-sekunden // 60)} min"
    minuten = math.ceil(sekunden / 60)
    return f"noch {minuten} min" if minuten < 60 else f"noch {minuten // 60}:{minuten % 60:02d} h"


def sitzung_text(z, jetzt=None):
    """Kurzbeschreibung für alle Anzeigen, z. B.
    ("🍅", "Fokus 2/4", "noch 12 min"), ("☕", "Kurze Pause", "+3 min"),
    ("⏳", "Countdown", "noch 1:23 h") oder ("⏸", "Countdown angehalten", "seit 4 min")."""
    jetzt = jetzt or datetime.now()
    if z["zustand"] == "angehalten":
        seit = f"seit {int((jetzt - z['seit']).total_seconds() // 60)} min"
        if z["typ"] == "timer":
            return "⏸", "Timer angehalten", seit
        was = (f"Fokus {satz_position(z)}/{z['nach']}" if z["typ"] == "pomodoro" else "Countdown")
        uebrig = _rest_text(z["rest"]).replace("noch ", "")
        return "⏸", f"{was} angehalten", f"{seit} · {uebrig} übrig"
    zeit_text = _rest_text((sitzung_ende(z) - jetzt).total_seconds())
    if z["typ"] == "countdown":
        return "⏳", "Countdown", zeit_text
    if z["zustand"] == "fokus":
        return "🍅", f"Fokus {satz_position(z)}/{z['nach']}", zeit_text
    return "☕", ("Lange Pause" if ist_lange_pause(z) else "Kurze Pause"), zeit_text


def _wecker_starten():
    """Startet den Wecker als eigenständigen Prozess und gibt seine Nummer zurück.

    start_new_session=True löst ihn vom Aufrufer: er läuft weiter, auch wenn
    das TUI geschlossen wird oder SwiftBar seinen Befehl beendet.
    In Tests schaltet ZEIT_KEIN_WECKER=1 das ab.
    """
    if os.environ.get("ZEIT_KEIN_WECKER"):
        return 0
    skript = Path(__file__).resolve().parent / "pomodoro.py"
    prozess = subprocess.Popen(
        [sys.executable, str(skript), "wecker"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True)
    return prozess.pid


def wecker_laeuft(pid):
    """Läuft unter dieser Nummer wirklich unser Wecker? (Nach einem Neustart
    könnte dieselbe Nummer einem ganz anderen Programm gehören.)"""
    if not pid:
        return False
    ergebnis = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                              capture_output=True, text=True)
    return "pomodoro.py" in ergebnis.stdout


def _sitzung_schreiben(ordner, datei):
    """Startet einen frischen Wecker und schreibt den Zustand samt dessen Nummer.

    Jeder Wecker prüft regelmäßig, ob noch *seine* Nummer in der Datei steht —
    der bisherige beendet sich also von selbst. So gibt es nie zwei.
    """
    if datei.sitzung:
        datei.sitzung["wecker"] = _wecker_starten()
    schreibe_zeitdatei(zeitdatei_pfad(ordner), datei)


def wecker_sicherstellen(projekte):
    """Läuft eine Sitzung, aber kein Wecker (z. B. nach einem Neustart), wird
    einer nachgestartet. Menüleiste und TUI rufen das regelmäßig auf."""
    aktiv = finde_aktiv(projekte, warner=lambda _: None)
    if aktiv and aktiv[2].sitzung and not wecker_laeuft(aktiv[2].sitzung["wecker"]):
        _sitzung_schreiben(aktiv[1], aktiv[2])


def _grundart(sitzung):
    """Welche Art ein Eintrag bekommt, der während dieser Sitzung gemessen wurde."""
    if sitzung and sitzung["typ"] == "pomodoro":
        return ART_POMODORO
    if sitzung and sitzung["typ"] == "countdown":
        return ART_COUNTDOWN
    return ART_NORMAL


def anhalten(ordner, datei):
    """Hält den laufenden Timer an — normalen Timer, Countdown oder Pomodoro-Fokus.

    Der bisherige Abschnitt wird eingetragen (Art mit ⏸), danach läuft keine
    Zeit mehr. Bei Countdown und Pomodoro wird die Restzeit gemerkt: nach dem
    Fortsetzen läuft genau sie weiter, das Ende verschiebt sich also.
    """
    jetzt = datetime.now().replace(microsecond=0)
    z = datei.sitzung
    art = _grundart(z) + ANGEHALTEN
    if z is None:                                   # normaler Timer
        neu = {"typ": "timer", "zustand": "angehalten", "phase": datei.laeuft[0],
               "seit": jetzt, "wecker": 0}
    else:
        neu = dict(z, zustand="angehalten", seit=jetzt,
                   rest=int((sitzung_ende(z) - jetzt).total_seconds()))
    datei.sitzung = neu
    ergebnis = _stoppe(ordner, datei, _jetzt(), art=art)
    _sitzung_schreiben(ordner, datei)               # Wecker für die 15-min-Erinnerung
    return ergebnis


def fortsetzen(ordner, datei):
    """Setzt einen angehaltenen Timer fort: ab jetzt läuft wieder ein Timer."""
    z = datei.sitzung
    jetzt = datetime.now().replace(microsecond=0)
    datei.laeuft = (z["phase"], jetzt.replace(second=0))
    if z["typ"] == "timer":                         # normaler Timer: Sitzung endet
        datei.sitzung = None
        schreibe_zeitdatei(zeitdatei_pfad(ordner), datei)
        return
    z.update(zustand="fokus" if z["typ"] == "pomodoro" else "laeuft",
             seit=jetzt, plan=z["rest"] / 60, rest=0)
    _sitzung_schreiben(ordner, datei)


def countdown_minuten(art, text, jetzt=None):
    """Wie viele Minuten der Countdown dauern soll.

    art "dauer": '2h', '1:30', '90min', '1,5' (nackte Zahl = Stunden)
    art "bis":   '17:00', '17', '17.30' — bis zu dieser Uhrzeit (heute; liegt
                 sie gerade hinter uns und ist es nicht zu weit, dann morgen)
    """
    jetzt = jetzt or datetime.now()
    text = text.strip().lower().replace(",", ".")
    if art == "dauer":
        minuten = _dauer_parsen(text)
        if minuten is None and re.fullmatch(r"\d+(?:\.\d+)?", text):
            minuten = int(round(float(text) * 60))
        if minuten is None:
            raise ValueError(f"'{text}' ist keine Dauer (z. B. 2h, 1:30, 90min).")
        if not 1 <= minuten <= 24 * 60:
            raise ValueError("Die Dauer muss zwischen 1 Minute und 24 Stunden liegen.")
        return float(minuten)
    treffer = re.fullmatch(rf"(?:bis\s*)?{_UHRZEIT}", text)
    if not treffer:
        raise ValueError(f"'{text}' ist keine Uhrzeit (z. B. 17:00).")
    ende = datetime.combine(jetzt.date(), _uhrzeit(treffer[1], treffer[2]))
    if ende <= jetzt:
        ende += timedelta(days=1)
        if ende - jetzt > timedelta(hours=12):
            raise ValueError(f"{ende:%H:%M} ist schon vorbei.")
    return (ende - jetzt).total_seconds() / 60


def countdown_starten(ordner, phase, minuten, art="dauer"):
    """Startet einen Countdown. Ein laufender Timer bzw. eine Sitzung muss
    vorher beendet sein."""
    datei = lese_zeitdatei(zeitdatei_pfad(ordner), ordner.name)
    jetzt = datetime.now().replace(microsecond=0)
    if art == "bis":
        # "bis 17:00" soll genau 17:00 ergeben — nicht 16:59:59, nur weil
        # zwischen Rechnen und Starten ein paar Millisekunden vergangen sind
        ziel = (jetzt + timedelta(minutes=minuten, seconds=30)).replace(second=0)
        minuten = (ziel - jetzt).total_seconds() / 60
    datei.laeuft = (phase, jetzt.replace(second=0))
    datei.sitzung = {"typ": "countdown", "zustand": "laeuft", "phase": phase, "seit": jetzt, "beginn": jetzt,
                     "plan": minuten, "rest": 0, "wecker": 0}
    _sitzung_schreiben(ordner, datei)
    einstellungen = lade_einstellungen()
    einstellungen.update({"countdown-art": art, "countdown-dauer": max(1, int(round(minuten)))})
    speichere_einstellungen(einstellungen)
    return datei.sitzung


def pomodoro_starten(ordner, phase, werte):
    """Startet eine Sitzung (Fokus 1). Ein anderer laufender Timer bzw. eine
    andere Sitzung muss vorher beendet sein. werte: fokus, kurz, lang, nach."""
    pomodoro_werte_pruefen(werte)
    werte = {k: int(werte[k]) for k in POMODORO_GRENZEN}
    datei = lese_zeitdatei(zeitdatei_pfad(ordner), ordner.name)
    jetzt = datetime.now().replace(microsecond=0)
    datei.laeuft = (phase, jetzt.replace(second=0))
    datei.sitzung = dict(werte, typ="pomodoro", zustand="fokus", phase=phase, nr=1, seit=jetzt, beginn=jetzt,
                         plan=werte["fokus"], rest=0, wecker=0)
    _sitzung_schreiben(ordner, datei)
    # als Vorschlag für den nächsten Start merken
    einstellungen = lade_einstellungen()
    einstellungen.update({"pomodoro-fokus": werte["fokus"], "pomodoro-kurze-pause": werte["kurz"],
                          "pomodoro-lange-pause": werte["lang"],
                          "pomodoro-lange-pause-nach": werte["nach"]})
    speichere_einstellungen(einstellungen)
    return datei.sitzung


def pomodoro_pause(ordner, datei):
    """Fokus beenden (wird mit 🍅 eingetragen) und die Pause beginnen."""
    z = datei.sitzung
    lang = ist_lange_pause(z)
    z.update(zustand="pause", seit=datetime.now().replace(microsecond=0),
             plan=z["lang"] if lang else z["kurz"])
    ergebnis = _stoppe(ordner, datei, _jetzt(), art=ART_POMODORO) if datei.laeuft else None
    _sitzung_schreiben(ordner, datei)
    return ergebnis


def pomodoro_weiter(ordner, datei):
    """Pause beenden (wird nicht erfasst) und den nächsten Fokus beginnen."""
    z = datei.sitzung
    jetzt = datetime.now().replace(microsecond=0)
    z.update(zustand="fokus", nr=z["nr"] + 1, seit=jetzt, plan=z["fokus"])
    datei.laeuft = (z["phase"], jetzt.replace(second=0))
    _sitzung_schreiben(ordner, datei)


def verlaengern(ordner, datei, minuten):
    """"Noch X min": ab jetzt noch X Minuten — auch wenn schon überzogen ist.
    Der Wecker bleibt derselbe; er merkt die neue Planzeit von selbst."""
    z = datei.sitzung
    # gerundet, nicht aufgerundet: sonst zeigt "Noch 5 min" danach "noch 6 min"
    vergangen = int((datetime.now() - z["seit"]).total_seconds() / 60 + 0.5)
    z["plan"] = max(z["plan"], vergangen) + minuten
    schreibe_zeitdatei(zeitdatei_pfad(ordner), datei)


def sitzung_beenden(ordner, datei, ende=None):
    """Sitzung beenden. Im Fokus wird die bisherige Zeit eingetragen (🍅),
    in der Pause gibt es nichts einzutragen. Der Wecker endet von selbst."""
    art = _grundart(datei.sitzung)
    datei.sitzung = None
    if datei.laeuft:
        return _stoppe(ordner, datei, ende or _jetzt(), art=art)
    schreibe_zeitdatei(zeitdatei_pfad(ordner), datei)
    return None


# ===========================================================================
# Bericht nach dem Beenden
# ===========================================================================

BERICHT_ARTEN = {"pomodoro": (ART_POMODORO, ART_POMODORO + ANGEHALTEN),
                 "countdown": (ART_COUNTDOWN, ART_COUNTDOWN + ANGEHALTEN),
                 "timer": (ART_NORMAL, ANGEHALTEN)}


def bericht(name, ordner, typ, phase, bis, beginn=None, letzter_start=None):
    """Was eine gerade beendete Sitzung eingetragen hat.

    Pomodoro/Countdown: alle Abschnitte dieser Phase ab `beginn`.
    Normaler Timer: der letzte Abschnitt und rückwärts alle direkt davor
    liegenden, die durch Anhalten (⏸) endeten — also die ganze Kette.
    letzter_start: Beginn des gerade beendeten Abschnitts (falls bekannt) —
    damit sich nie ein älterer Eintrag unterschiebt.
    Rückgabe: dict, oder None wenn nichts eingetragen wurde.
    """
    arten = BERICHT_ARTEN[typ]
    abschnitte = []
    for zellen in lese_zeitdatei(zeitdatei_pfad(ordner), ordner.name).eintraege:
        zeitraum = _zeitraum_aus(zellen)
        if zeitraum and zellen[4] == phase and zellen[5] in arten and zeitraum[1] <= bis + timedelta(minutes=1):
            abschnitte.append((zeitraum[0], zeitraum[1], zellen[5]))
    abschnitte.sort()
    if beginn is not None:
        abschnitte = [a for a in abschnitte if a[0] >= beginn - timedelta(minutes=1)]
    else:
        # Der zuletzt beendete Abschnitt muss genau jetzt (bzw. beim Anhalten)
        # geendet haben — sonst lief der Timer unter einer Minute und hat gar
        # nichts eingetragen, und ein älterer Eintrag darf nicht einspringen.
        kette = []
        for a in reversed(abschnitte):
            if not kette:
                passt = (a[0] == letzter_start if letzter_start
                         else abs((a[1] - bis).total_seconds()) < 60)
                if passt:
                    kette.append(a)
                continue
            if a[2] == ANGEHALTEN and a[1] <= kette[-1][0]:
                kette.append(a)                      # davor angehalten: gehört dazu
            else:
                break
        abschnitte = list(reversed(kette))
    if not abschnitte:
        return None
    heute = datetime.now().date()
    projekte, _ = lade_config()
    heute_gesamt = sum(e.minuten for e in alle_eintraege(projekte, warner=lambda _: None)
                       if e.datum == heute)
    minuten = sum(int(round((e - s).total_seconds() / 60)) for s, e, _ in abschnitte)
    spanne = int(round((abschnitte[-1][1] - abschnitte[0][0]).total_seconds() / 60))
    letzter = abschnitte[-1][0]
    return {"ziel": (f"{letzter:%Y-%m-%d}", f"{letzter:%H:%M}"),    # hier kommt Feedback hin
            "projekt": name, "phase": phase, "typ": typ, "abschnitte": abschnitte,
            "minuten": minuten, "luecken": max(0, spanne - minuten),
            "pomodoros": sum(1 for a in abschnitte if a[2] == ART_POMODORO),
            "angehalten": sum(1 for a in abschnitte if a[2].endswith(ANGEHALTEN)),
            "heute": heute_gesamt}


def bericht_zeilen(b):
    """Der Bericht als Textzeilen — gleich für Terminal, TUI und Menüleiste."""
    std = lambda m: dauer_text(timedelta(minutes=m))
    art = {"pomodoro": "Pomodoro-Sitzung", "countdown": "Countdown", "timer": "Timer"}[b["typ"]]
    erster, letzter = b["abschnitte"][0][0], b["abschnitte"][-1][1]
    kopf = f"{erster:%H:%M}–{letzter:%H:%M}"
    if b["pomodoros"]:
        kopf += f" · {b['pomodoros']} Pomodoro{'s' if b['pomodoros'] != 1 else ''}"
    zeilen = [f"■ Erfasst: {b['projekt']} / {b['phase']}   ({art})",
              f"  {kopf} · {std(b['minuten'])} h erfasst"]
    if len(b["abschnitte"]) > 1:
        for s, e, a in b["abschnitte"][-8:]:
            zeilen.append(f"    {s:%H:%M}–{e:%H:%M}  {std(int(round((e - s).total_seconds() / 60)))}  {a}".rstrip())
        if len(b["abschnitte"]) > 8:
            zeilen.insert(2, f"    … ({len(b['abschnitte']) - 8} frühere Abschnitte)")
    zusatz = []
    if b["luecken"]:
        zusatz.append(f"{'Pausen' if b['typ'] == 'pomodoro' else 'Unterbrechungen'} nicht erfasst: "
                      f"{std(b['luecken'])}")
    if b["angehalten"]:
        zusatz.append(f"{b['angehalten']}× angehalten")
    if zusatz:
        zeilen.append("  " + " · ".join(zusatz))
    zeilen.append(f"  Heute insgesamt: {std(b['heute'])} h")
    return zeilen


def beenden_mit_bericht(name, ordner, datei, ende=None):
    """Beendet, was läuft (Timer, Countdown, Pomodoro — auch angehalten), und
    liefert den Bericht (oder None, wenn nichts eingetragen wurde)."""
    z = datei.sitzung
    typ = z["typ"] if z else "timer"
    phase = z["phase"] if z else datei.laeuft[0]
    beginn = z.get("beginn") if z and typ != "timer" else None
    ende = ende or _jetzt()
    # Angehaltener Timer: sein letzter Abschnitt endete beim Anhalten, nicht jetzt
    bis = z["seit"].replace(second=0) if z and typ == "timer" else ende
    letzter_start = datei.laeuft[1] if (datei.laeuft and typ == "timer") else None
    sitzung_beenden(ordner, datei, ende)
    return bericht(name, ordner, typ, phase, bis, beginn, letzter_start)


# Das Bericht-Fenster für die Menüleiste (und den Wecker): ein macOS-Dialog.
# "Kalender öffnen" startet das Kalenderfenster (Tagesansicht).
_BERICHT_DIALOG = """on run argv
    activate
    set antwort to display dialog (item 1 of argv) with title "zeit — erfasst" ¬
        buttons {"Kalender öffnen", "OK"} default button "OK"
    if button returned of antwort is "Kalender öffnen" then
        do shell script quoted form of (item 2 of argv) & " " & quoted form of (item 3 of argv) & " oeffnen tag > /dev/null 2>&1 &"
    end if
end run"""


def feedback_fenster(zeilen, ordner, ziel):
    """Bericht + freiwilliges Feedback als macOS-Fenster (feedback.py), ohne
    auf das Schließen zu warten. ziel: (datum, start) der Zeile für das Feedback."""
    if os.environ.get("ZEIT_KEIN_WECKER"):          # in Tests keine Fenster
        return
    cfg = {"bericht": "\n".join(zeilen), "ordner": str(ordner), "datum": ziel[0], "start": ziel[1]}
    subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "feedback.py"),
                      json.dumps(cfg, ensure_ascii=False)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def feedback_terminal(ordner, ziel):
    """Freiwilliges Feedback im Terminal — Enter überspringt."""
    antwort = input("Wie fokussiert?  1 😄  2 😐  3 ☹️   n = nur Notiz   (Enter = überspringen): ").strip()
    fokus = {"1": FOKUS_WERTE[0], "2": FOKUS_WERTE[1], "3": FOKUS_WERTE[2]}.get(antwort, "")
    if not fokus and antwort.lower() != "n":
        return
    notiz = input("Notiz (Enter = keine): ").strip()
    if fokus or notiz:
        feedback_setzen(ordner, ziel[0], ziel[1], fokus, notiz)
        print("✓ Feedback gespeichert.")


def fokusblock_bericht(name, ergebnis):
    """Kurzer Bericht für einen einzelnen Pomodoro-Fokusblock (bei "Pause starten")."""
    _, phase, start, ende = ergebnis
    return [f"🍅 Fokus beendet: {name} / {phase}",
            f"  {start:%H:%M}–{ende:%H:%M} · {dauer_text(ende - start)} h erfasst"]


def bericht_fenster(zeilen):
    """Zeigt den Bericht als macOS-Fenster, ohne auf das Schließen zu warten."""
    if os.environ.get("ZEIT_KEIN_WECKER"):          # in Tests keine Fenster
        return
    skript = Path(__file__).resolve().parent / "kalender_fenster.py"
    prozess = subprocess.Popen(["osascript", "-", "\n".join(zeilen), sys.executable, str(skript)],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True, text=True)
    prozess.stdin.write(_BERICHT_DIALOG)
    prozess.stdin.close()


def notiz_saeubern(text):
    """Eine Notiz darf die Tabelle nicht zerbrechen: | wird /, Umbrüche werden Leerzeichen."""
    return " ".join(text.replace("|", "/").split())


def feedback_setzen(ordner, datum, start, fokus="", notiz=""):
    """Speichert Fokus und Notiz an der Zeile mit diesem Datum und Beginn.
    Rückgabe: True, wenn die Zeile gefunden wurde."""
    if fokus and fokus not in FOKUS_WERTE:
        raise ValueError(f"Fokus muss eins von {' '.join(FOKUS_WERTE)} sein.")
    pfad = zeitdatei_pfad(ordner)
    datei = lese_zeitdatei(pfad, ordner.name)
    for zellen in reversed(datei.eintraege):
        if zellen[0] == datum and zellen[1] == start:
            zellen[6], zellen[7] = fokus, notiz_saeubern(notiz)
            schreibe_zeitdatei(pfad, datei)
            return True
    return False


def _stoppe(ordner, datei, ende, art=None):
    """Beendet den laufenden Timer und schreibt ihn als Tabellenzeile fest.

    Dauerte er weniger als eine Minute, wird bewusst KEINE Zeile geschrieben:
    solche Null-Einträge entstehen praktisch nur durch Vertipper (falsches
    Projekt gestartet und sofort umgeschaltet) und würden die Tabelle zumüllen.
    Rückgabe: (pfad, phase, start, ende) — oder None, wenn nichts eingetragen wurde.
    """
    phase, start = datei.laeuft
    if ende < start:
        fehler(
            f"Die Endzeit {ende:%Y-%m-%d %H:%M} liegt vor dem Start "
            f"{start:%Y-%m-%d %H:%M}."
        )
    datei.laeuft = None
    pfad = zeitdatei_pfad(ordner)
    if int(round((ende - start).total_seconds() / 60)) == 0:
        schreibe_zeitdatei(pfad, datei)
        return None
    if art is None:      # z. B. im Pomodoro-Fokus gemessen -> 🍅, im Countdown -> ⏳
        art = _grundart(datei.sitzung)
    datei.eintraege.append(_eintragszeile(start, ende, phase, art))
    schreibe_zeitdatei(pfad, datei)
    return pfad, phase, start, ende


def _stopp_meldung(name, phase, start, ende):
    """Einheitliche Ausgabe nach dem Stoppen — inklusive Hinweis auf Tageswechsel."""
    tage = (ende.date() - start.date()).days
    zusatz = "" if not tage else (" (+1 Tag)" if tage == 1 else f" (+{tage} Tage)")
    print(f"■ {name} / {phase} — {start:%H:%M}–{ende:%H:%M}{zusatz}, "
          f"Dauer {dauer_text(ende - start)}")


def _endzeit(text, start):
    """--um 17:30                 -> 17:30 am Starttag (der typische Korrekturfall)
       --um '2026-08-28 17:30'    -> genau dieser Zeitpunkt"""
    text = text.strip()
    try:
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            stunde, minute = (int(t) for t in text.split(":"))
            return start.replace(hour=stunde, minute=minute, second=0, microsecond=0)
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        fehler(f"--um '{text}' verstehe ich nicht. Erwartet: HH:MM oder 'YYYY-MM-DD HH:MM'.")


def _projekt_und_phase(projekt_text, phase_text):
    """Löst Projekt und Phase auf und legt sie nach Rückfrage neu an.
    Wird von `start` und `nachtragen` gemeinsam benutzt.
    Rückgabe: (projekte, phasen, kurzname, ordner, phase)."""
    projekte, phasen = lade_config()

    # --- Projekt bestimmen, bei Bedarf nach Rückfrage neu anlegen ---------
    p = slug(projekt_text)
    if p not in projekte:
        print(f"Projekt '{projekt_text}' ist noch nicht gespeichert.")
        if projekte:
            print("   Bekannt sind: " + ", ".join(sorted(projekte)))
        if not frage_ja_nein(f"   Als '{p}' neu anlegen?"):
            sys.exit(0)
        ordner = _projekt_anlegen(p, projekte, phasen)
    else:
        ordner = projekte[p]

    # --- Phase bestimmen, bei Bedarf nach Rückfrage neu anlegen -----------
    ph = slug(phase_text)
    if ph not in phasen:
        print(f"Phase '{phase_text}' ist noch nicht gespeichert.")
        print("   Bekannt sind: " + ", ".join(phasen))
        if not frage_ja_nein(f"   '{ph}' als neue Phase anlegen?"):
            sys.exit(0)
        phasen.append(ph)
        speichere_config(projekte, phasen)
        print(f"✓ Phase '{ph}' gespeichert")
    return projekte, phasen, p, ordner, ph


def befehl_nachtragen(args):
    projekte, _, p, ordner, ph = _projekt_und_phase(args.projekt, args.phase)
    try:
        n = nachtrag_parsen(" ".join(args.wann))
    except ValueError as grund:
        fehler(str(grund).replace("\n", "\n       "))

    print(f"Nachtrag: {p} / {ph} — {beschreibe_nachtrag(n)}")
    konflikte = konflikte_fuer(projekte, n)
    if konflikte:
        warnung("Das überschneidet sich mit:")
        for k in konflikte:
            print(f"     {k}")
        if not frage_ja_nein("   Trotzdem eintragen?", standard=False):
            sys.exit(0)
    pfad = nachtragen(ordner, ph, n)
    print("✓ eingetragen")
    print(f"  {pfad}")


SITZUNGSNAMEN = {"pomodoro": "Pomodoro-Sitzung", "countdown": "Countdown", "timer": "Timer"}


def _sitzung_beschreiben(name, datei):
    """Eine Zeile wie 'Countdown a / design-phase (noch 12 min)'."""
    z = datei.sitzung
    if not z:
        phase, start = datei.laeuft
        return f"Timer {name} / {phase}, seit {start:%H:%M}"
    _, was, rest = sitzung_text(z)
    return f"{SITZUNGSNAMEN[z['typ']]} {name} / {z['phase']} ({was}, {rest})"


def _warum_kein_eintrag(datei):
    z = datei.sitzung
    if z and z["zustand"] == "pause":
        return "war in der Pause"
    if z and z["zustand"] == "angehalten":
        return "war angehalten"
    return "unter einer Minute"


def _vorher_beenden(projekte):
    """Läuft schon etwas (Timer, Countdown, Pomodoro — auch angehalten)? Dann
    Umschalten anbieten. Es darf immer nur eins laufen."""
    aktiv = finde_aktiv(projekte)
    if not aktiv:
        return
    alt_name, alt_ordner, alt_datei = aktiv
    print(f"Es läuft bereits: {_sitzung_beschreiben(alt_name, alt_datei)}")
    if alt_datei.laeuft and not alt_datei.sitzung:
        pruefe_vergessen(alt_datei.laeuft[1])
    if not frage_ja_nein("   Beenden und umschalten?"):
        print("Abgebrochen — es läuft weiter.")
        sys.exit(0)
    alt_phase = alt_datei.sitzung["phase"] if alt_datei.sitzung else alt_datei.laeuft[0]
    grund = _warum_kein_eintrag(alt_datei)
    ergebnis = sitzung_beenden(alt_ordner, alt_datei)
    if ergebnis:
        _stopp_meldung(alt_name, *ergebnis[1:])
    else:
        print(f"■ {alt_name} / {alt_phase} — beendet, kein Eintrag ({grund}).")


def befehl_start(args):
    projekte, phasen, p, ordner, ph = _projekt_und_phase(args.projekt, args.phase)

    _vorher_beenden(projekte)

    # --- Neuen Timer starten ---------------------------------------------
    pfad = zeitdatei_pfad(ordner)
    datei = lese_zeitdatei(pfad, ordner.name)
    jetzt = _jetzt()
    datei.laeuft = (ph, jetzt)
    schreibe_zeitdatei(pfad, datei)
    print(f"▶ {p} / {ph} — gestartet {jetzt:%H:%M}")
    print(f"  {pfad}")


def _aktive_sitzung(typ):
    """Die laufende Sitzung dieses Typs, sonst Fehlermeldung."""
    projekte, _ = lade_config()
    aktiv = finde_aktiv(projekte)
    if not aktiv or not aktiv[2].sitzung or aktiv[2].sitzung["typ"] != typ:
        fehler(f"Es läuft gerade kein{'e' if typ == 'pomodoro' else ''} "
               f"{SITZUNGSNAMEN[typ]}.")
    return aktiv


def _stand_zeigen(z):
    symbol, was, rest = sitzung_text(z)
    print(f"{symbol} {was} — {rest}")


def _mehr_oder_ende(args, typ):
    """"mehr" und "ende" sind bei Pomodoro und Countdown gleich."""
    name, ordner, datei = _aktive_sitzung(typ)
    z = datei.sitzung
    if args.aktion == "mehr":
        if not datei.laeuft and z["zustand"] == "angehalten":
            fehler("Angehalten — erst fortsetzen: zeit fortsetzen")
        verlaengern(ordner, datei, args.minuten or lade_einstellungen()["pomodoro-verlaengern"])
        _stand_zeigen(z)
    else:
        _bericht_ausgeben(name, ordner, datei, None, args)


def befehl_pomodoro(args):
    if args.aktion == "start":
        projekte, _, p, ordner, ph = _projekt_und_phase(args.projekt, args.phase)
        vorgabe = lade_einstellungen()
        werte = {"fokus": args.fokus or vorgabe["pomodoro-fokus"],
                 "kurz": args.kurz or vorgabe["pomodoro-kurze-pause"],
                 "lang": args.lang or vorgabe["pomodoro-lange-pause"],
                 "nach": args.nach or vorgabe["pomodoro-lange-pause-nach"]}
        try:
            pomodoro_werte_pruefen(werte)
        except ValueError as grund:
            fehler(str(grund))
        _vorher_beenden(projekte)
        pomodoro_starten(ordner, ph, werte)
        print(f"🍅 {p} / {ph} — Fokus 1/{werte['nach']}, {werte['fokus']} min")
        print(f"   Pausen {werte['kurz']} / {werte['lang']} min, lange Pause nach {werte['nach']}")
        return
    if args.aktion in ("mehr", "ende"):
        return _mehr_oder_ende(args, "pomodoro")

    name, ordner, datei = _aktive_sitzung("pomodoro")
    z = datei.sitzung
    if z["zustand"] == "angehalten":
        fehler("Der Fokus ist angehalten — erst fortsetzen: zeit fortsetzen")
    if args.aktion == "pause":
        if z["zustand"] != "fokus":
            fehler("Die Sitzung ist schon in der Pause. Weiter mit: zeit pomodoro weiter")
        ergebnis = pomodoro_pause(ordner, datei)
        if ergebnis:
            _stopp_meldung(name, *ergebnis[1:])
            ziel = (f"{ergebnis[2]:%Y-%m-%d}", f"{ergebnis[2]:%H:%M}")
            if getattr(args, "fenster", False):
                feedback_fenster(fokusblock_bericht(name, ergebnis), ordner, ziel)
            elif sys.stdin.isatty() and not ANNAHME_JA:
                feedback_terminal(ordner, ziel)
    else:                                            # weiter
        if z["zustand"] != "pause":
            fehler("Die Sitzung ist gerade im Fokus. Pause mit: zeit pomodoro pause")
        pomodoro_weiter(ordner, datei)
    _stand_zeigen(z)


def befehl_countdown(args):
    if args.aktion == "start":
        projekte, _, p, ordner, ph = _projekt_und_phase(args.projekt, args.phase)
        text = " ".join(args.wann)
        art = "bis" if text.strip().lower().startswith("bis") else "dauer"
        try:
            minuten = countdown_minuten(art, text)
        except ValueError as grund:
            fehler(str(grund))
        _vorher_beenden(projekte)
        z = countdown_starten(ordner, ph, minuten, art)
        ende = sitzung_ende(z)
        print(f"⏳ {p} / {ph} — Countdown bis {ende:%H:%M} ({_rest_text(minuten * 60)})")
        return
    return _mehr_oder_ende(args, "countdown")


def befehl_anhalten(args):
    projekte, _ = lade_config()
    aktiv = finde_aktiv(projekte)
    if not aktiv or not aktiv[2].laeuft:
        if aktiv and aktiv[2].sitzung["zustand"] == "angehalten":
            fehler("Ist schon angehalten. Weiter mit: zeit fortsetzen")
        if aktiv:
            fehler("In der Pomodoro-Pause läuft keine Zeit, die man anhalten könnte.")
        fehler("Es läuft gerade kein Timer.")
    name, ordner, datei = aktiv
    ergebnis = anhalten(ordner, datei)
    if ergebnis:
        _stopp_meldung(name, *ergebnis[1:])
    _stand_zeigen(datei.sitzung)
    print("   Weiter mit: zeit fortsetzen")


def befehl_fortsetzen(args):
    projekte, _ = lade_config()
    aktiv = finde_aktiv(projekte)
    if not aktiv or not aktiv[2].sitzung or aktiv[2].sitzung["zustand"] != "angehalten":
        fehler("Es ist gerade nichts angehalten.")
    name, ordner, datei = aktiv
    typ = datei.sitzung["typ"]
    fortsetzen(ordner, datei)
    if typ == "timer":
        print(f"▶ {name} / {datei.laeuft[0]} — läuft wieder")
    else:
        _stand_zeigen(datei.sitzung)


def _bericht_ausgeben(name, ordner, datei, ende, args):
    """Beendet, was läuft, und zeigt, was eingetragen wurde — im Terminal und,
    mit --fenster (so ruft die Menüleiste auf), zusätzlich als macOS-Fenster."""
    phase = datei.sitzung["phase"] if datei.sitzung else datei.laeuft[0]
    grund = _warum_kein_eintrag(datei)
    b = beenden_mit_bericht(name, ordner, datei, ende)
    if not b:
        print(f"■ {name} / {phase} beendet — kein Eintrag ({grund}).")
        return
    zeilen = bericht_zeilen(b)
    print("\n".join(zeilen))
    if getattr(args, "fenster", False):
        feedback_fenster(zeilen, ordner, b["ziel"])
    elif sys.stdin.isatty() and not ANNAHME_JA:
        feedback_terminal(ordner, b["ziel"])


def befehl_stop(args):
    projekte, _ = lade_config()
    laufend = finde_aktiv(projekte)
    if not laufend:
        print("Es läuft gerade kein Timer.")
        return
    name, ordner, datei = laufend
    ende = None
    if datei.laeuft:
        start = datei.laeuft[1]
        if args.um:
            ende = _endzeit(args.um, start)
        elif not datei.sitzung:
            pruefe_vergessen(start, _jetzt())
    _bericht_ausgeben(name, ordner, datei, ende, args)


def befehl_status(args):
    projekte, _ = lade_config()
    laufend = finde_aktiv(projekte)
    if not laufend:
        print("Es läuft gerade kein Timer.")
        return
    name, ordner, datei = laufend
    z = datei.sitzung
    if z:
        symbol, was, rest = sitzung_text(z)
        print(f"{symbol} {SITZUNGSNAMEN[z['typ']]} — {name} / {z['phase']}")
        print(f"  {was} · {rest}")
        if z["typ"] == "pomodoro":
            print(f"  Einstellungen: Fokus {z['fokus']} · kurze Pause {z['kurz']} · "
                  f"lange Pause {z['lang']} nach {z['nach']}")
        if z["typ"] == "countdown" and z["zustand"] == "laeuft":
            print(f"  Ende um {sitzung_ende(z):%H:%M}")
        if not datei.laeuft:
            print("  (es wird gerade keine Zeit erfasst"
                  + (" — weiter mit: zeit fortsetzen)" if z["zustand"] == "angehalten" else ")"))
            return
    phase, start = datei.laeuft
    jetzt = datetime.now()
    print(f"▶ {name} / {phase}")
    print(f"  gestartet {start:%d.%m.%Y %H:%M} — läuft seit {dauer_text(jetzt - start)} h")
    print(f"  {zeitdatei_pfad(ordner)}")
    if not z:
        pruefe_vergessen(start, jetzt)


def befehl_abbrechen(args):
    """Verwirft den laufenden Abschnitt (kein Eintrag) und beendet alles.
    Bereits eingetragene Abschnitte (z. B. fertige Pomodoros) bleiben stehen."""
    projekte, _ = lade_config()
    laufend = finde_aktiv(projekte)
    if not laufend:
        print("Es läuft gerade kein Timer.")
        return
    name, ordner, datei = laufend
    print(f"Laufend: {_sitzung_beschreiben(name, datei)}")
    if datei.laeuft:
        frage = "   Wirklich verwerfen? Der laufende Abschnitt wird NICHT eingetragen."
    else:
        frage = "   Beenden? (Gerade läuft keine Zeit — es gibt nichts einzutragen.)"
    if not frage_ja_nein(frage, standard=False):
        print("Abgebrochen — es läuft weiter.")
        return
    datei.laeuft = None
    datei.sitzung = None
    schreibe_zeitdatei(zeitdatei_pfad(ordner), datei)
    print("✓ Verworfen, nichts eingetragen.")


def _jetzt():
    """Aktueller Zeitpunkt auf ganze Minuten gekürzt — Sekunden sind hier nur Rauschen."""
    return datetime.now().replace(second=0, microsecond=0)


# ===========================================================================
# Kommandozeile
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="zeit",
        description="Zeiterfassung, die alles in lesbaren Markdown-Dateien speichert.",
    )
    # required=False: `zeit` ganz ohne Argumente öffnet die Oberfläche
    parser.add_argument("--fenster", action="store_true",
                        help="nach dem Beenden den Bericht zusätzlich als macOS-Fenster zeigen "
                             "(so ruft die Menüleiste auf)")
    parser.add_argument("-j", "--ja", action="store_true",
                        help="alle Ja/Nein-Rückfragen automatisch mit Ja beantworten "
                             "(für Aufrufe ohne Terminal, z. B. aus der Menüleiste)")
    unter = parser.add_subparsers(dest="befehl")

    p = unter.add_parser("start", help="Timer für ein Projekt und eine Phase starten")
    p.add_argument("projekt", help='z. B. "baeckerei-mueller"')
    p.add_argument("phase", help='z. B. "design-phase"')
    p.set_defaults(funktion=befehl_start)

    p = unter.add_parser("stop", help="laufenden Timer stoppen")
    p.add_argument("--um", metavar="HH:MM",
                   help="Endzeit korrigieren; HH:MM gilt als Uhrzeit am Starttag")
    p.set_defaults(funktion=befehl_stop)

    p = unter.add_parser("status", help="zeigt, ob und seit wann ein Timer läuft")
    p.set_defaults(funktion=befehl_status)

    p = unter.add_parser("abbrechen", help="laufenden Timer verwerfen, ohne Eintrag")
    p.set_defaults(funktion=befehl_abbrechen)

    p = unter.add_parser("nachtragen", help="Zeit nachträglich eintragen")
    p.add_argument("projekt")
    p.add_argument("phase")
    p.add_argument("wann", nargs="+",
                   help='z. B. "gestern 9:00-11:30", "2h ab 14:00", "1,5h bis 17", '
                        '"gestern 3h" (nur Tag)')
    p.set_defaults(funktion=befehl_nachtragen)

    p = unter.add_parser("pomodoro", help="Pomodoro-Sitzung starten und steuern")
    pu = p.add_subparsers(dest="aktion", required=True)
    s = pu.add_parser("start", help="Sitzung für ein Projekt und eine Phase starten")
    s.add_argument("projekt")
    s.add_argument("phase")
    s.add_argument("--fokus", type=int, help="Minuten Fokus (Vorgabe: zuletzt benutzt)")
    s.add_argument("--kurz", type=int, help="Minuten kurze Pause")
    s.add_argument("--lang", type=int, help="Minuten lange Pause")
    s.add_argument("--nach", type=int, help="lange Pause nach so vielen Pomodoros")
    pu.add_parser("pause", help="Fokus beenden (wird eingetragen), Pause beginnen")
    pu.add_parser("weiter", help="Pause beenden, nächsten Fokus beginnen")
    m = pu.add_parser("mehr", help='"Noch X min": den jetzigen Abschnitt verlängern')
    m.add_argument("minuten", nargs="?", type=int, help="Vorgabe: aus den Einstellungen")
    pu.add_parser("ende", help="Sitzung beenden (ein laufender Fokus wird eingetragen)")
    p.set_defaults(funktion=befehl_pomodoro)

    p = unter.add_parser("countdown", help="Countdown: Timer mit festgelegter Dauer oder Ende")
    cu = p.add_subparsers(dest="aktion", required=True)
    s = cu.add_parser("start", help='z. B. "2h", "1:30", "90min" oder "bis 17:00"')
    s.add_argument("projekt")
    s.add_argument("phase")
    s.add_argument("wann", nargs="+")
    m = cu.add_parser("mehr", help='"Noch X min": den Countdown verlängern')
    m.add_argument("minuten", nargs="?", type=int, help="Vorgabe: aus den Einstellungen")
    cu.add_parser("ende", help="Countdown beenden (die bisherige Zeit wird eingetragen)")
    p.set_defaults(funktion=befehl_countdown)

    p = unter.add_parser("anhalten", help="laufenden Timer/Countdown/Pomodoro-Fokus anhalten")
    p.set_defaults(funktion=befehl_anhalten)
    p = unter.add_parser("fortsetzen", help="angehaltenen Timer fortsetzen")
    p.set_defaults(funktion=befehl_fortsetzen)

    p = unter.add_parser("tutorial", help="die geführte Tour durch zeit (noch einmal) starten")
    p.set_defaults(funktion=lambda args: _starte_tui(tutorial_starten=True))

    global ANNAHME_JA
    args = parser.parse_args()
    ANNAHME_JA = args.ja
    if args.befehl is None:
        _starte_tui()
        return
    args.funktion(args)


def _starte_tui(tutorial_starten=False):
    """Startet die Oberfläche aus tui.py (liegt neben diesem Skript)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    # Dieses Skript läuft als "__main__". Damit Module wie kalender.py beim
    # `import zeit` genau dieses bekommen (und keine zweite Kopie laden),
    # wird es auch unter seinem Namen eingetragen.
    sys.modules.setdefault("zeit", sys.modules[__name__])
    import tui
    # Das TUI bekommt dieses Modul übergeben, statt selbst `import zeit` zu
    # machen: sonst läge zeit.py zweimal im Speicher (einmal als "__main__",
    # einmal als "zeit") und es gäbe zwei Kopien aller Einstellungen.
    tui.starte(sys.modules[__name__], tutorial_starten)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(130)
