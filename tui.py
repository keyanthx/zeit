#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tui.py — die Terminal-Oberfläche für `zeit`, gestartet mit `zeit` ohne Argumente.

Hier steht ausschließlich Darstellung und Tastensteuerung. Alles, was Dateien
liest oder schreibt, liegt in zeit.py und wird über die Variable `zeit`
aufgerufen (das Modul wird beim Start hereingereicht).

Gebaut mit `curses` aus der Python-Standardbibliothek — damit bleibt das Tool
installationsfrei.
"""

import curses
import locale
import os
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

# Wird von starte() gesetzt: das Modul zeit.py mit der gesamten Logik.
zeit = None


# ===========================================================================
# Farben und feste Texte
# ===========================================================================

FARBE_TITEL = 1
FARBE_AKTIV = 2
FARBE_WARNUNG = 3
FARBE_LAEUFT = 4

# Projektfarben im Kalender: Farbpaar PROJEKT_FARBEN_AB + Nummer des Projekts
PROJEKT_FARBEN_AB = 10
PROJEKT_FARBEN = [curses.COLOR_BLUE, curses.COLOR_MAGENTA, curses.COLOR_YELLOW,
                  curses.COLOR_GREEN, curses.COLOR_CYAN, curses.COLOR_RED]
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

NEU = "\x00neu"  # Kennzeichen für den Listeneintrag "… neu anlegen"


def _farben():
    try:
        curses.start_color()
        curses.use_default_colors()
        # Akzentfarbe aus den Einstellungen; Orange (208) gibt es nur mit 256 Farben
        akzent = zeit.akzentfarbe()[0]
        if akzent >= curses.COLORS:
            akzent = curses.COLOR_YELLOW
        curses.init_pair(FARBE_TITEL, akzent, -1)
        schrift = curses.COLOR_BLACK
        if os.environ.get("ZEIT_FARBSCHEMA") and curses.COLORS >= 16:
            # Im Popup/zeit-Terminalfenster kennen wir die Farben: bei dunkler
            # Akzentfarbe weiße statt schwarzer Schrift in der markierten Zeile
            import farbschemata
            schrift = farbschemata.schrift_auf_akzent(zeit.lade_einstellungen()["farbschema"], akzent)
        curses.init_pair(FARBE_AKTIV, schrift, akzent)
        curses.init_pair(FARBE_WARNUNG, curses.COLOR_YELLOW, -1)
        curses.init_pair(FARBE_LAEUFT, curses.COLOR_GREEN, -1)
        for i, farbe in enumerate(PROJEKT_FARBEN):
            curses.init_pair(PROJEKT_FARBEN_AB + i, farbe, -1)
    except curses.error:
        pass  # Terminal ohne Farben — dann eben schwarzweiß


_EINSTELLUNGEN_STAND = [None]


def _farben_pruefen():
    """Setzt die Farben neu, wenn sich projekte.md (die Einstellungen) geändert hat —
    etwa weil im Menüleisten-Formular das Farbschema umgestellt wurde."""
    try:
        stand = zeit.CONFIG_DATEI.stat().st_mtime_ns
    except OSError:
        return
    if stand != _EINSTELLUNGEN_STAND[0]:
        if _EINSTELLUNGEN_STAND[0] is not None:
            _farben()
        _EINSTELLUNGEN_STAND[0] = stand


# Läuft gerade das Tutorial (tutorial.py)? Dann steht hier, was die Übung
# verlangt — {"hinweis": [Zeilen], "ziel": Funktion -> True wenn geschafft,
# "zuletzt": Name des zuletzt im Hauptmenü geöffneten Bildschirms}.
TUTORIAL = None


def _auffrischen(fenster):
    """Statt fenster.refresh(): zeichnet vorher den Tutorial-Hinweis (falls eine
    Übung läuft) in die vorletzten Zeilen — so bleibt er in jedem Bildschirm
    sichtbar, auch in den echten, die die Übung benutzt."""
    if TUTORIAL and TUTORIAL.get("hinweis"):
        hoehe, breite = fenster.getmaxyx()
        zeilen = TUTORIAL["hinweis"]
        for i, text in enumerate(zeilen):
            y = hoehe - 1 - len(zeilen) + i
            if y > 0:
                _schreibe(fenster, y, 0, (" 👉 " if i == 0 else "    ") + text.ljust(breite),
                          curses.color_pair(FARBE_AKTIV) | curses.A_BOLD)
    fenster.refresh()


def _warn():
    return curses.color_pair(FARBE_WARNUNG)


# ===========================================================================
# Bausteine: schreiben, Tasten lesen, Liste anzeigen, Dialoge
# ===========================================================================

def _schreibe(fenster, y, x, text, attr=0):
    """Schreibt Text und schneidet ihn am Rand ab.

    curses wirft einen Fehler, sobald man über den Bildschirmrand hinaus
    schreibt. Das hier fängt es ab, damit ein zu schmales Fenster nicht das
    ganze Programm beendet.
    """
    hoehe, breite = fenster.getmaxyx()
    if y < 0 or y >= hoehe or x >= breite:
        return
    try:
        fenster.addstr(y, x, text[: max(0, breite - x - 1)], attr)
    except curses.error:
        pass


# Rohe Escape-Folgen, falls das Terminal seine Pfeiltasten anders kodiert,
# als die terminfo-Datenbank erwartet (kommt bei tmux, ssh und manchen
# Terminal-Apps vor). Dann liest curses die Zeichen einzeln aus.
_FOLGEN = {"A": curses.KEY_UP, "B": curses.KEY_DOWN, "C": curses.KEY_RIGHT,
           "D": curses.KEY_LEFT, "H": curses.KEY_HOME, "F": curses.KEY_END}


def _folge_deuten(rest):
    """['[', 'A'] -> curses.KEY_UP. None, wenn die Folge unbekannt ist."""
    if len(rest) >= 2 and rest[0] in ("[", "O") and rest[-1] in _FOLGEN:
        return _FOLGEN[rest[-1]]
    return None


def _taste(fenster):
    """Liest eine Taste. Ergebnis ist ein Zeichen (str) oder ein curses-Code (int).

    get_wch() statt getch(), damit Umlaute richtig ankommen.

    Sonderfall Escape: kommt direkt danach noch etwas, war es in Wahrheit eine
    Tastenfolge (meist eine Pfeiltaste) und nicht die Escape-Taste. Ohne diese
    Unterscheidung würde eine Taste, die dieses Terminal anders kodiert, den
    Bildschirm verlassen — und man wüsste nicht, warum.
    """
    try:
        t = fenster.get_wch()
    except (curses.error, KeyboardInterrupt):
        return None
    if t != "\x1b":
        return t

    rest = []
    fenster.nodelay(True)
    try:
        while True:
            weiter = fenster.get_wch()
            if weiter is None:
                break
            rest.append(weiter)
    except curses.error:
        pass  # nichts mehr da — es war wirklich die Escape-Taste
    finally:
        fenster.nodelay(False)
    return "\x1b" if not rest else _folge_deuten(rest)


def _ist_enter(t):
    return t in ("\n", "\r", curses.KEY_ENTER)


def _ist_escape(t):
    return t == "\x1b"


def _ist_rueckwaerts(t):
    return t in ("\x7f", "\b", curses.KEY_BACKSPACE)


def waehle(fenster, titel, kopfzeilen, eintraege, hilfe,
           zusatztasten="", start=0, auswaehlbar=True, links_zurueck=True,
           blaettern=False):
    """Zeichnet Titel, Kopfzeilen und eine scrollbare Liste; wartet auf eine Taste.

    kopfzeilen und eintraege sind jeweils Listen von (text, attr).
    Rückgabe:
        ("wahl",    index)              Enter auf einem Eintrag
        ("taste",   (zeichen, index))   eine der zusatztasten wurde gedrückt
        ("zurueck", None)               q, Esc oder ← (eine Ebene zurück)

    blaettern=True: ← → werden als ("taste", ("←"/"→", index)) gemeldet, statt
    zurück bzw. weiter zu bedeuten (für Kalender und Statistik).

    links_zurueck=False schaltet die Links-Taste ab. Das braucht das
    Hauptmenü: dort gibt es keine Ebene mehr, in die man zurückgehen könnte,
    und ein versehentliches ← soll nicht das ganze Programm schließen.
    """
    pos = max(0, min(start, len(eintraege) - 1)) if eintraege else 0
    oben = 0
    while True:
        _farben_pruefen()
        fenster.erase()
        hoehe, breite = fenster.getmaxyx()
        y = 0
        _schreibe(fenster, y, 2, titel, curses.color_pair(FARBE_TITEL) | curses.A_BOLD)
        y += 2
        for text, attr in kopfzeilen:
            _schreibe(fenster, y, 2, text, attr)
            y += 1
        if kopfzeilen:
            y += 1

        platz = max(1, hoehe - y - 2)
        if pos < oben:
            oben = pos
        if pos >= oben + platz:
            oben = pos - platz + 1

        for i in range(oben, min(len(eintraege), oben + platz)):
            text, attr = eintraege[i]
            markiert = auswaehlbar and i == pos
            zeiger = "▸ " if markiert else "  "
            if markiert:
                attr = curses.color_pair(FARBE_AKTIV) | curses.A_BOLD
                text = text.ljust(max(0, breite - 6))
            _schreibe(fenster, y + i - oben, 2, zeiger + text, attr)

        if len(eintraege) > platz:
            hilfe = f"{hilfe}    [{pos + 1}/{len(eintraege)}]"
        _schreibe(fenster, hoehe - 1, 2, hilfe, curses.A_DIM)
        _auffrischen(fenster)

        t = _taste(fenster)
        if blaettern and t in (curses.KEY_LEFT, curses.KEY_RIGHT):
            return "taste", ("←" if t == curses.KEY_LEFT else "→", pos)
        if t in (curses.KEY_UP,) or t == "k":
            pos = max(0, pos - 1)
        elif t in (curses.KEY_DOWN,) or t == "j":
            pos = min(len(eintraege) - 1, pos + 1) if eintraege else 0
        elif t == curses.KEY_PPAGE:
            pos = max(0, pos - platz)
        elif t == curses.KEY_NPAGE:
            pos = min(len(eintraege) - 1, pos + platz) if eintraege else 0
        elif t == curses.KEY_HOME:
            pos = 0
        elif t == curses.KEY_END:
            pos = max(0, len(eintraege) - 1)
        elif (_ist_enter(t) or t == curses.KEY_RIGHT) and auswaehlbar and eintraege:
            return "wahl", pos
        elif _ist_escape(t) or t == "q" or (links_zurueck and t == curses.KEY_LEFT):
            return "zurueck", None
        elif isinstance(t, str) and t in zusatztasten:
            return "taste", (t, pos)


def dialog(fenster, zeilen, hilfe):
    """Zeichnet ein zentriertes Kästchen über den aktuellen Bildschirm.

    Rückgabe: (oben, links, breite, hoehe) — damit der Aufrufer noch etwas
    hineinschreiben kann, etwa ein Eingabefeld.
    """
    hoehe, breite = fenster.getmaxyx()
    inhalt = max((len(z) for z in zeilen + [hilfe]), default=0)
    b = max(40, min(breite - 4, inhalt + 6))
    h = min(hoehe, len(zeilen) + 4)
    o = max(0, (hoehe - h) // 2)
    l = max(0, (breite - b) // 2)
    _schreibe(fenster, o, l, "┌" + "─" * (b - 2) + "┐")
    for i in range(1, h - 1):
        _schreibe(fenster, o + i, l, "│" + " " * (b - 2) + "│")
    _schreibe(fenster, o + h - 1, l, "└" + "─" * (b - 2) + "┘")
    for i, z in enumerate(zeilen):
        _schreibe(fenster, o + 1 + i, l + 2, z)
    _schreibe(fenster, o + h - 2, l + 2, hilfe, curses.A_DIM)
    return o, l, b, h


def meldung(fenster, zeilen):
    """Zeigt einen Hinweis und wartet auf einen Tastendruck."""
    dialog(fenster, list(zeilen) + [""], "beliebige Taste")
    _auffrischen(fenster)
    _taste(fenster)


def frage_ja_nein(fenster, zeilen, standard=True):
    vorgabe = "ja" if standard else "nein"
    while True:
        dialog(fenster, list(zeilen) + [""],
               f"j ja · n nein · ⏎ oder → = {vorgabe} · ← abbrechen")
        _auffrischen(fenster)
        t = _taste(fenster)
        if t in ("j", "J", "y", "Y"):
            return True
        # ← bricht immer ab, nie zu. So bleibt "nach hinten" überall harmlos,
        # auch wenn der Dialog gerade nach einem Löschen fragt.
        if t in ("n", "N") or _ist_escape(t) or t == "q" or t == curses.KEY_LEFT:
            return False
        if _ist_enter(t) or t == curses.KEY_RIGHT:
            return standard


def frage_text(fenster, zeilen, vorgabe=""):
    """Textabfrage im Kästchen. Rückgabe: der Text, oder None bei Abbruch."""
    puffer = vorgabe
    while True:
        o, l, b, h = dialog(fenster, list(zeilen) + ["", ""], "⏎ übernehmen   Esc abbrechen")
        sicht = puffer[-(b - 8):]
        _schreibe(fenster, o + len(zeilen) + 1, l + 2, "> " + sicht + "▌", curses.A_BOLD)
        _auffrischen(fenster)
        t = _taste(fenster)
        if _ist_enter(t):
            return puffer.strip()
        if _ist_escape(t):
            return None
        if _ist_rueckwaerts(t):
            puffer = puffer[:-1]
        elif isinstance(t, str) and t >= " ":
            puffer += t


# ===========================================================================
# Auswertung — reine Rechenarbeit, ohne curses
# ===========================================================================

def _std(minuten):
    """150 -> '2:30'"""
    return f"{minuten // 60}:{minuten % 60:02d}"


def _zeile(links, rechts, einzug=0):
    return " " * einzug + links.ljust(30 - einzug) + rechts.rjust(8)


# ===========================================================================
# Bildschirme
# ===========================================================================

def _endzeit_parsen(text, start):
    """'17:30' -> Zeitpunkt am Starttag. None, wenn unlesbar."""
    text = text.strip()
    try:
        if re.fullmatch(r"\d{1,2}:\d{2}", text):
            stunde, minute = (int(x) for x in text.split(":"))
            return start.replace(hour=stunde, minute=minute, second=0, microsecond=0)
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _verdaechtig(start, jetzt=None):
    """Läuft der Timer über Nacht oder über der Warnschwelle?"""
    jetzt = jetzt or datetime.now()
    return (start.date() != jetzt.date()
            or (jetzt - start) >= timedelta(hours=zeit.WARNUNG_AB_STUNDEN))


def _laufend(projekte):
    """Laufender Timer oder Pomodoro-Sitzung (auch in der Pause) — wie
    zeit.finde_aktiv, aber ohne Ausgabe auf den Bildschirm."""
    gemeldet = []
    return zeit.finde_aktiv(projekte, warner=gemeldet.append), gemeldet


def _vorher_beenden(fenster, projekte):
    """Läuft schon etwas (Timer, Countdown, Pomodoro — auch angehalten)? Dann
    Umschalten anbieten — es darf immer nur eins laufen. False = abgebrochen."""
    aktiv, _ = _laufend(projekte)
    if not aktiv:
        return True
    name, ordner, datei = aktiv
    zeilen = [f"Es läuft bereits: {zeit._sitzung_beschreiben(name, datei)}", ""]
    if datei.laeuft and not datei.sitzung and _verdaechtig(datei.laeuft[1]):
        zeilen += ["⚠  Vermutlich vergessen zu stoppen.",
                   "   Dann lieber erst über 'Timer stoppen' korrigieren.", ""]
    if not frage_ja_nein(fenster, zeilen + ["Beenden und umschalten?"]):
        return False
    zeit.sitzung_beenden(ordner, datei)
    return True


def _liste_waehlen(fenster, titel, namen, neu_text, vorschlag=None):
    """Zeigt eine Namensliste plus 'neu anlegen'. Gibt Name, NEU oder None zurück.
    vorschlag: dieser Name ist schon ausgewählt (Enter übernimmt ihn)."""
    eintraege = [(n, 0) for n in namen] + [(neu_text, curses.A_DIM)]
    start = namen.index(vorschlag) if vorschlag in namen else 0
    art, idx = waehle(fenster, titel, [], eintraege, "↑↓ wählen · →/⏎ weiter · ←/q zurück",
                      start=start)
    if art != "wahl":
        return None
    return NEU if idx == len(namen) else namen[idx]


def _neues_projekt(fenster, projekte, phasen):
    """Legt ein Projekt an und speichert es. Gibt den Kurznamen zurück oder None."""
    name = frage_text(fenster, ["Wie heißt das neue Projekt?"])
    if not name:
        return None
    kurz = zeit.slug(name)
    if kurz in projekte:
        meldung(fenster, [f"'{kurz}' steht schon in der Liste."])
        return None
    vorschlag = zeit._ordner_vorschlag(kurz) or (zeit.projekt_suchordner() / name)
    text = frage_text(fenster, ["In welchem Ordner soll die Zeiterfassung liegen?"],
                      str(vorschlag))
    if not text:
        return None
    ordner = Path(text).expanduser().resolve()
    if not ordner.exists():
        if not frage_ja_nein(fenster, [str(ordner), "", "Dieser Ordner existiert nicht. Anlegen?"]):
            return None
        ordner.mkdir(parents=True)
    projekte[kurz] = ordner
    zeit.speichere_config(projekte, phasen)
    return kurz


def _neue_phase(fenster, projekte, phasen):
    name = frage_text(fenster, ["Wie heißt die neue Phase?"])
    if not name:
        return None
    kurz = zeit.slug(name)
    if kurz in phasen:
        meldung(fenster, [f"'{kurz}' steht schon in der Liste."])
        return None
    phasen.append(kurz)
    zeit.speichere_config(projekte, phasen)
    return kurz


def bildschirm_starten(fenster):
    projekte, phasen = zeit.lade_config()

    projekt = _liste_waehlen(fenster, "Timer starten — Projekt", list(projekte),
                             "+ neues Projekt anlegen …")
    if projekt is None:
        return
    if projekt is NEU:
        projekt = _neues_projekt(fenster, projekte, phasen)
        if projekt is None:
            return

    phase = _liste_waehlen(fenster, f"Timer starten — Phase für {projekt}", phasen,
                           "+ neue Phase anlegen …")
    if phase is None:
        return
    if phase is NEU:
        phase = _neue_phase(fenster, projekte, phasen)
        if phase is None:
            return

    ordner = projekte[projekt]
    pfad = zeit.zeitdatei_pfad(ordner)
    if zeit.ist_fremde_datei(pfad):
        meldung(fenster, ["In diesem Ordner liegt bereits eine Zeiterfassung.md,",
                          "die nicht von `zeit` stammt.", "",
                          "Sie wird nicht angefasst — bitte umbenennen."])
        return

    if not _vorher_beenden(fenster, projekte):
        return

    datei = zeit.lese_zeitdatei(pfad, ordner.name)
    jetzt = zeit._jetzt()
    datei.laeuft = (phase, jetzt)
    zeit.schreibe_zeitdatei(pfad, datei)
    meldung(fenster, [f"▶  {projekt} / {phase}", f"   gestartet um {jetzt:%H:%M}"])


def _projekt_und_phase_waehlen(fenster, titel):
    """Projekt- und Phasenauswahl inkl. "neu anlegen". Gibt (projekt, phase) oder None."""
    projekte, phasen = zeit.lade_config()
    projekt = _liste_waehlen(fenster, f"{titel} — Projekt", list(projekte),
                             "+ neues Projekt anlegen …")
    if projekt is NEU:
        projekt = _neues_projekt(fenster, projekte, phasen)
    if projekt is None:
        return None
    phase = _liste_waehlen(fenster, f"{titel} — Phase für {projekt}", phasen,
                           "+ neue Phase anlegen …")
    if phase is NEU:
        phase = _neue_phase(fenster, projekte, phasen)
    if phase is None:
        return None
    return projekt, phase


# ===========================================================================
# Nachtrag-Formular (dieselben Felder wie in der Menüleiste)
# ===========================================================================
#
# Die Felder sind verknüpft — genau wie im Menüleisten-Formular:
#   Von ändern    -> Bis wandert mit (die Dauer bleibt)
#   Bis ändern    -> die Dauer wird neu berechnet
#   Dauer ändern  -> je nach Schalter wandert das Ende oder der Anfang
# Uhrzeiten werden intern als "Minuten seit Mitternacht" geführt (0–1439);
# liegt Bis vor Von, ist das über Mitternacht — das klärt beim Eintragen
# zeit.nachtrag_parsen mit denselben Regeln wie überall.

# Die Felder des Formulars, in Anzeigereihenfolge: (Schlüssel, Beschriftung)
FELDER = [("datum", "Datum"), ("art", "Uhrzeiten"), ("von", "Von"), ("bis", "Bis"),
          ("dauer", "Dauer"), ("modus", "Dauer verschiebt"), ("knopf", "")]
NUR_MIT_UHRZEIT = {"von", "bis", "modus"}   # ausgegraut bei "nur Tag"


def _norm(m):
    return m % 1440


def _hhmm(m):
    m = _norm(m)
    return f"{m // 60:02d}:{m % 60:02d}"


def _schritt(m, richtung):
    """±15 Minuten, dabei aufs Viertelstunden-Raster einrasten (11:47 -> 12:00 / 11:45)."""
    return (m // 15 + 1) * 15 if richtung > 0 else ((m - 1) // 15) * 15


def _uhrzeit_lesen(text):
    treffer = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?", text.strip())
    if not treffer:
        raise ValueError(f"'{text}' ist keine Uhrzeit (z. B. 14:30).")
    zeitpunkt = zeit._uhrzeit(treffer[1], treffer[2])
    return zeitpunkt.hour * 60 + zeitpunkt.minute


def _dauer_lesen(text):
    text = text.strip().lower().replace(",", ".")
    minuten = zeit._dauer_parsen(text)
    if minuten is None and re.fullmatch(r"\d+(?:\.\d+)?", text):
        minuten = int(round(float(text) * 60))      # nackte Zahl = Stunden
    if minuten is None or not 0 < minuten < 1440:
        raise ValueError(f"'{text}' ist keine Dauer (z. B. 1:30, 1,5h, 90min).")
    return minuten


def _datum_lesen(text):
    heute = date.today()
    tag, rest = zeit._datum_herausloesen(f" {text.strip().lower()} ", None, heute)
    if tag is None or rest.strip():
        raise ValueError(f"'{text}' ist kein Datum (z. B. 23.9. oder gestern).")
    if tag > heute:
        raise ValueError("Das Datum liegt in der Zukunft.")
    return tag


def formular_nachtragen(fenster, projekt, phase):
    """Zeigt das Formular. Rückgabe: ein zeit.Nachtrag oder None bei Abbruch."""
    # Vorgaben: die letzte Stunde bis jetzt, auf 15 Minuten abgerundet
    jetzt = datetime.now()
    bis_zp = jetzt.replace(minute=jetzt.minute - jetzt.minute % 15, second=0, microsecond=0)
    von_zp = bis_zp - timedelta(hours=1)
    s = {"tag": von_zp.date(), "von": von_zp.hour * 60 + von_zp.minute,
         "bis": bis_zp.hour * 60 + bis_zp.minute, "dauer": 60, "ende": True,
         "nur_tag": False}
    feld, puffer, fehler = 2, None, ""      # startet auf "Von"

    def schluessel(i):
        return FELDER[i][0]

    def aktiv(i):
        """Felder, die bei "nur Tag" nichts bedeuten, werden übersprungen."""
        return not (s["nur_tag"] and schluessel(i) in NUR_MIT_UHRZEIT)

    def setze_von(m):
        s["von"] = _norm(m)
        s["bis"] = _norm(s["von"] + s["dauer"])

    def setze_bis(m):
        s["bis"] = _norm(m)
        s["dauer"] = _norm(s["bis"] - s["von"])

    def setze_dauer(m):
        s["dauer"] = max(15, min(m, 1439))
        if s["nur_tag"]:
            return                          # ohne Uhrzeiten wandert nichts mit
        if s["ende"]:
            s["bis"] = _norm(s["von"] + s["dauer"])
        else:
            s["von"] = _norm(s["bis"] - s["dauer"])

    def anzeige(k):
        if k == "datum":
            return f"{WOCHENTAGE[s['tag'].weekday()]} {s['tag']:%d.%m.%Y}"
        if k == "art":
            return "( ) mit   (•) ohne (nur Tag)" if s["nur_tag"] else "(•) mit   ( ) ohne (nur Tag)"
        if k == "von":
            return _hhmm(s["von"])
        if k == "bis":
            return _hhmm(s["bis"]) + ("  (+1 Tag)" if s["bis"] < s["von"] else "")
        if k == "dauer":
            return _std(s["dauer"])
        return "(•) Ende   ( ) Anfang" if s["ende"] else "( ) Ende   (•) Anfang"

    def puffer_uebernehmen():
        """Getippten Text ins Feld übernehmen. Ungültig -> alter Wert bleibt."""
        nonlocal puffer, fehler
        if puffer is None:
            return True
        text, puffer = puffer, None
        if not text.strip():
            return True
        try:
            k = schluessel(feld)
            if k == "datum":
                s["tag"] = _datum_lesen(text)
            elif k == "von":
                setze_von(_uhrzeit_lesen(text))
            elif k == "bis":
                setze_bis(_uhrzeit_lesen(text))
            elif k == "dauer":
                setze_dauer(_dauer_lesen(text))
            return True
        except ValueError as grund:
            fehler = str(grund)
            return False

    def springe(richtung):
        """Zum nächsten Feld, das gerade aktiv ist."""
        nonlocal feld
        ziel = feld + richtung
        while 0 <= ziel < len(FELDER) and not aktiv(ziel):
            ziel += richtung
        if 0 <= ziel < len(FELDER):
            feld = ziel

    def umschalten(k):
        if k == "art":
            s["nur_tag"] = not s["nur_tag"]
        elif k == "modus":
            s["ende"] = not s["ende"]

    while True:
        fenster.erase()
        _schreibe(fenster, 0, 2, f"Zeit nachtragen — {projekt} / {phase}",
                  curses.color_pair(FARBE_TITEL) | curses.A_BOLD)
        for i, (k, name) in enumerate(FELDER):
            y = 2 + i
            gewaehlt = i == feld
            _schreibe(fenster, y, 2, "▸ " if gewaehlt else "  ")
            if k == "knopf":
                attr = curses.color_pair(FARBE_AKTIV) | curses.A_BOLD if gewaehlt else curses.A_BOLD
                _schreibe(fenster, y + 1, 2, "▸ " if gewaehlt else "  ")
                _schreibe(fenster, y + 1, 4, " Eintragen ", attr)
                continue
            if not aktiv(i):
                _schreibe(fenster, y, 4, f"{name:<18}  —", curses.A_DIM)
                continue
            wert = (puffer + "▌") if (gewaehlt and puffer is not None) else anzeige(k)
            if k in ("art", "modus"):
                wert = f"  {wert}"
            else:
                wert = f"◂ {wert} ▸" if (gewaehlt and puffer is None) else f"  {wert}"
            attr = curses.color_pair(FARBE_AKTIV) | curses.A_BOLD if gewaehlt else 0
            _schreibe(fenster, y, 4, f"{name:<18}", curses.A_BOLD if gewaehlt else 0)
            _schreibe(fenster, y, 22, f" {wert} ", attr)
        if fehler:
            _schreibe(fenster, 11, 4, f"⚠  {fehler}", _warn())
        hoehe, _ = fenster.getmaxyx()
        _schreibe(fenster, hoehe - 2, 2,
                  "↑↓ Feld · ←→ ändern (±15 min, ±1 Tag) · tippen überschreibt das Feld",
                  curses.A_DIM)
        _schreibe(fenster, hoehe - 1, 2, "⏎ eintragen · Esc abbrechen", curses.A_DIM)
        _auffrischen(fenster)

        t = _taste(fenster)
        k = schluessel(feld)
        if t is None:
            continue
        if _ist_escape(t):
            if puffer is not None:          # erst die Eingabe verwerfen …
                puffer = None
                continue
            return None                     # … dann das Formular
        if t in (curses.KEY_UP, curses.KEY_DOWN, "\t", curses.KEY_BTAB):
            if puffer_uebernehmen():
                fehler = ""
                springe(-1 if t in (curses.KEY_UP, curses.KEY_BTAB) else 1)
            continue
        if _ist_enter(t):
            if not puffer_uebernehmen():
                continue
            if s["nur_tag"]:
                text = f"{s['tag']:%Y-%m-%d} {s['dauer']}min"
            else:
                text = f"{s['tag']:%Y-%m-%d} {_hhmm(s['von'])}-{_hhmm(s['bis'])}"
            try:
                return zeit.nachtrag_parsen(text)
            except ValueError as grund:
                fehler = str(grund).replace("\n", " ")
                continue
        if t in (curses.KEY_LEFT, curses.KEY_RIGHT) and puffer is None:
            r = 1 if t == curses.KEY_RIGHT else -1
            fehler = ""
            if k == "datum":
                neu = s["tag"] + timedelta(days=r)
                if neu <= date.today():
                    s["tag"] = neu
            elif k == "von":
                setze_von(_schritt(s["von"], r))
            elif k == "bis":
                setze_bis(_schritt(s["bis"], r))
            elif k == "dauer":
                setze_dauer(_schritt(s["dauer"], r))
            else:
                umschalten(k)
            continue
        if k in ("art", "modus") and t == " ":
            umschalten(k)
            continue
        if puffer is not None and _ist_rueckwaerts(t):
            puffer = puffer[:-1]
            continue
        if isinstance(t, str) and t.isprintable() and k in ("datum", "von", "bis", "dauer"):
            puffer = t if puffer is None else puffer + t   # erster Tastendruck ersetzt
            fehler = ""


def bildschirm_nachtragen(fenster):
    auswahl = _projekt_und_phase_waehlen(fenster, "Zeit nachtragen")
    if auswahl is None:
        return
    projekt, phase = auswahl
    projekte, _ = zeit.lade_config()
    ordner = projekte[projekt]
    if zeit.ist_fremde_datei(zeit.zeitdatei_pfad(ordner)):
        meldung(fenster, ["In diesem Ordner liegt eine Zeiterfassung.md,",
                          "die nicht von `zeit` stammt. Sie wird nicht angefasst."])
        return

    n = formular_nachtragen(fenster, projekt, phase)
    if n is None:
        return

    # Nachgefragt wird nur bei Überschneidung — "Eintragen" im Formular war
    # schon die Bestätigung. Vorgabe dann "nein": Enter trägt nicht ein.
    konflikte = zeit.konflikte_fuer(projekte, n)
    if konflikte:
        zeilen = [f"{projekt} / {phase}", zeit.beschreibe_nachtrag(n), "",
                  "⚠  Überschneidet sich mit:"] + [f"   {k}" for k in konflikte[:5]]
        if not frage_ja_nein(fenster, zeilen + ["", "Trotzdem eintragen?"], standard=False):
            return
    zeit.nachtragen(ordner, phase, n)
    meldung(fenster, ["✓ Nachgetragen", "", f"{projekt} / {phase}",
                      zeit.beschreibe_nachtrag(n)])


def feedback_tui(fenster, zeilen, ordner, ziel):
    """Bericht oben, darunter das freiwillige Feedback: Fokus und Notiz."""
    auswahl = [(f"{f}  {zeit.FOKUS_NAMEN[f]}", 0) for f in zeit.FOKUS_WERTE]
    auswahl += [("✎  nur eine Notiz", 0), ("Überspringen", curses.A_DIM)]
    art, idx = waehle(fenster, "Erfasst — wie fokussiert warst du? (freiwillig)",
                      [(z, curses.A_BOLD if i == 0 else 0) for i, z in enumerate(zeilen)],
                      auswahl, "↑↓ wählen · →/⏎ weiter · q/Esc überspringen", start=len(auswahl) - 1)
    if art != "wahl" or idx == len(auswahl) - 1:
        return
    fokus = zeit.FOKUS_WERTE[idx] if idx < 3 else ""
    notiz = frage_text(fenster, [f"Notiz {fokus}".strip() + " (freiwillig)",
                                 "Enter ohne Text = keine Notiz"]) or ""
    if fokus or notiz:
        zeit.feedback_setzen(ordner, ziel[0], ziel[1], fokus, notiz)


def bericht_zeigen(fenster, name, ordner, datei, ende=None):
    """Beendet, was läuft, zeigt, was eingetragen wurde, und fragt freiwillig
    nach Feedback."""
    phase = datei.sitzung["phase"] if datei.sitzung else datei.laeuft[0]
    grund = zeit._warum_kein_eintrag(datei)
    b = zeit.beenden_mit_bericht(name, ordner, datei, ende)
    if b:
        feedback_tui(fenster, zeit.bericht_zeilen(b), ordner, b["ziel"])
    else:
        meldung(fenster, [f"■ {name} / {phase} beendet", f"Kein Eintrag ({grund})."])


def bildschirm_stoppen(fenster):
    """Beendet, was läuft — Timer, Countdown oder Pomodoro-Sitzung — und zeigt
    den Bericht."""
    projekte, _ = zeit.lade_config()
    laufend, _ = _laufend(projekte)
    if not laufend:
        meldung(fenster, ["Es läuft gerade kein Timer."])
        return
    name, ordner, datei = laufend
    ende = None
    # Normaler Timer, der nach vergessenem Stoppen aussieht? Dann Endzeit
    # anbieten — aber nie selbst korrigieren, das war deine ausdrückliche Vorgabe.
    if datei.laeuft and not datei.sitzung and _verdaechtig(datei.laeuft[1]):
        phase, start = datei.laeuft
        jetzt = zeit._jetzt()
        if frage_ja_nein(fenster, [
                f"{name} / {phase}",
                f"läuft seit {start:%d.%m.%Y %H:%M}"
                f" — das sind {zeit.dauer_text(jetzt - start)} Stunden.", "",
                "Sieht nach vergessenem Stoppen aus.",
                "Endzeit von Hand eingeben?"]):
            text = frage_text(fenster, [f"Endzeit am {start:%d.%m.%Y}",
                                        "Format HH:MM, z. B. 17:30"], f"{start:%H:%M}")
            if text is None:
                return
            ende = _endzeit_parsen(text, start)
            if ende is None:
                meldung(fenster, ["Das konnte ich nicht lesen.", "Erwartet: HH:MM, z. B. 17:30"])
                return
            if ende < start:
                meldung(fenster, ["Diese Endzeit liegt vor dem Start."])
                return
    bericht_zeigen(fenster, name, ordner, datei, ende)


def bildschirm_abbrechen(fenster):
    """Verwirft den laufenden Abschnitt (kein Eintrag) und beendet alles.
    Bereits eingetragene Abschnitte bleiben stehen."""
    projekte, _ = zeit.lade_config()
    laufend, _ = _laufend(projekte)
    if not laufend:
        meldung(fenster, ["Es läuft gerade kein Timer."])
        return
    name, ordner, datei = laufend
    zeilen = [zeit._sitzung_beschreiben(name, datei), ""]
    if datei.laeuft:
        zeilen += ["Wirklich abbrechen?", "Der laufende Abschnitt wird NICHT eingetragen."]
    else:
        zeilen += ["Beenden? Gerade läuft keine Zeit —", "es gibt nichts einzutragen."]
    if not frage_ja_nein(fenster, zeilen, standard=False):
        return
    datei.laeuft = None
    datei.sitzung = None
    zeit.schreibe_zeitdatei(zeit.zeitdatei_pfad(ordner), datei)
    meldung(fenster, ["Abgebrochen, nichts eingetragen."])


def bildschirm_anhalten(fenster):
    projekte, _ = zeit.lade_config()
    laufend, _ = _laufend(projekte)
    if laufend and laufend[2].laeuft:
        zeit.anhalten(laufend[1], laufend[2])


def bildschirm_fortsetzen(fenster):
    projekte, _ = zeit.lade_config()
    laufend, _ = _laufend(projekte)
    if laufend and laufend[2].sitzung and laufend[2].sitzung["zustand"] == "angehalten":
        zeit.fortsetzen(laufend[1], laufend[2])


def _verschoben(liste, index, richtung):
    """Tauscht zwei Listenelemente. Rückgabe: (neue Liste, neuer Index)."""
    ziel = index + richtung
    if 0 <= ziel < len(liste):
        liste = list(liste)
        liste[index], liste[ziel] = liste[ziel], liste[index]
        return liste, ziel
    return liste, index


def _phase_verwendungen(projekte, phase):
    return sum(1 for e in zeit.alle_eintraege(projekte, warner=lambda _: None)
               if e[3] == phase)


def bildschirm_projekte(fenster):
    pos = 0
    while True:
        projekte, phasen = zeit.lade_config()
        namen = list(projekte)
        eintraege = [(f"{n:<22}{projekte[n]}", 0) for n in namen]
        if not eintraege:
            eintraege = [("(noch keine Projekte — mit n anlegen)", curses.A_DIM)]

        art, wert = waehle(
            fenster, "Übersicht — Projekte",
            [("n neu   r umbenennen   o Ordner wechseln   d entfernen   K/J verschieben",
              curses.A_DIM)],
            eintraege, "↑↓ wählen · ←/q zurück",
            zusatztasten="nrodKJ", start=pos, auswaehlbar=bool(namen))
        if art == "zurueck":
            return
        if art != "taste":
            continue
        zeichen, pos = wert

        if zeichen == "n":
            _neues_projekt(fenster, projekte, phasen)
            continue
        if not namen:
            continue
        name = namen[pos]

        if zeichen == "r":
            text = frage_text(fenster, [f"Projekt '{name}' umbenennen in:"], name)
            if not text:
                continue
            neu = zeit.slug(text)
            if neu != name and neu in projekte:
                meldung(fenster, [f"'{neu}' steht schon in der Liste."])
                continue
            zeit.speichere_config({(neu if k == name else k): v
                                   for k, v in projekte.items()}, phasen)

        elif zeichen == "o":
            text = frage_text(fenster, [f"Neuer Ordner für '{name}'"], str(projekte[name]))
            if not text:
                continue
            neu_ordner = Path(text).expanduser().resolve()
            if neu_ordner == projekte[name]:
                continue
            if not neu_ordner.exists():
                if not frage_ja_nein(fenster, [str(neu_ordner), "",
                                               "Dieser Ordner existiert nicht. Anlegen?"]):
                    continue
                neu_ordner.mkdir(parents=True)
            alt_datei = zeit.zeitdatei_pfad(projekte[name])
            neu_datei = zeit.zeitdatei_pfad(neu_ordner)
            if alt_datei.exists() and not neu_datei.exists():
                if frage_ja_nein(fenster, ["Vorhandene Zeiterfassung.md mitnehmen?", "",
                                           f"von  {alt_datei.parent}",
                                           f"nach {neu_ordner}"]):
                    shutil.move(str(alt_datei), str(neu_datei))
            projekte[name] = neu_ordner
            zeit.speichere_config(projekte, phasen)

        elif zeichen == "d":
            if frage_ja_nein(fenster, [f"Projekt '{name}' aus der Liste entfernen?", "",
                                       "Die Datei Zeiterfassung.md bleibt erhalten —",
                                       "entfernt wird nur der Eintrag in der Registry."],
                             standard=False):
                del projekte[name]
                zeit.speichere_config(projekte, phasen)
                pos = max(0, pos - 1)

        elif zeichen in "KJ":
            reihenfolge, pos = _verschoben(namen, pos, -1 if zeichen == "K" else 1)
            zeit.speichere_config({n: projekte[n] for n in reihenfolge}, phasen)


def bildschirm_phasen(fenster):
    pos = 0
    while True:
        projekte, phasen = zeit.lade_config()
        eintraege = [(p, 0) for p in phasen] or [("(keine Phasen — mit n anlegen)", curses.A_DIM)]

        art, wert = waehle(
            fenster, "Übersicht — Phasen",
            [("n neu   r umbenennen   d entfernen   K/J verschieben", curses.A_DIM)],
            eintraege, "↑↓ wählen · ←/q zurück",
            zusatztasten="nrdKJ", start=pos, auswaehlbar=bool(phasen))
        if art == "zurueck":
            return
        if art != "taste":
            continue
        zeichen, pos = wert

        if zeichen == "n":
            _neue_phase(fenster, projekte, phasen)
            continue
        if not phasen:
            continue
        alt = phasen[pos]

        if zeichen == "r":
            text = frage_text(fenster, [f"Phase '{alt}' umbenennen in:"], alt)
            if not text:
                continue
            neu = zeit.slug(text)
            if neu == alt:
                continue
            if neu in phasen:
                meldung(fenster, [f"'{neu}' steht schon in der Liste."])
                continue
            # Wichtig: sonst zerfällt die Phase in zwei Kategorien und die
            # Auswertung wäre still falsch.
            anzahl = _phase_verwendungen(projekte, alt)
            mitziehen = anzahl and frage_ja_nein(fenster, [
                f"'{alt}' kommt in {anzahl} bereits erfassten Einträgen vor.", "",
                "Dort ebenfalls umbenennen?", "",
                "Nein lässt die Einträge stehen — die Auswertung",
                "zählt die Phase dann getrennt."])
            phasen[pos] = neu
            zeit.speichere_config(projekte, phasen)
            if mitziehen:
                geaendert = zeit.phase_umbenennen(projekte, alt, neu)
                meldung(fenster, [f"Umbenannt. {geaendert} Einträge angepasst."])

        elif zeichen == "d":
            anzahl = _phase_verwendungen(projekte, alt)
            zeilen = [f"Phase '{alt}' aus der Liste entfernen?"]
            if anzahl:
                zeilen += ["", f"⚠  Sie kommt in {anzahl} erfassten Einträgen vor.",
                           "Die Einträge bleiben unverändert stehen —",
                           "entfernt wird nur der Listeneintrag."]
            if frage_ja_nein(fenster, zeilen, standard=False):
                phasen.pop(pos)
                zeit.speichere_config(projekte, phasen)
                pos = max(0, pos - 1)

        elif zeichen in "KJ":
            phasen, pos = _verschoben(phasen, pos, -1 if zeichen == "K" else 1)
            zeit.speichere_config(projekte, phasen)


def bildschirm_uebersicht(fenster):
    pos = 0
    while True:
        art, idx = waehle(fenster, "Übersicht", [],
                          [("Projekte", 0), ("Phasen", 0)],
                          "↑↓ wählen · →/⏎ öffnen · ←/q zurück", start=pos)
        if art != "wahl":
            return
        pos = idx
        (bildschirm_projekte if idx == 0 else bildschirm_phasen)(fenster)


# ===========================================================================
# Kalender
# ===========================================================================
#
# Die Rechnungen stehen in kalender.py (gemeinsam mit dem Menüleisten-Fenster);
# hier wird nur gezeichnet. Ein Kästchen im Raster ist ein Zeitabschnitt
# (15, 30 oder 60 Minuten — je nachdem, was auf den Bildschirm passt):
#   █  der Abschnitt ist mindestens zur Hälfte belegt
#   ▒  er ist nur zum Teil belegt
# Die Farbe gehört zum Projekt; unten steht die Legende.

def _projektfarbe(farben, projekt):
    return curses.color_pair(PROJEKT_FARBEN_AB + farben.get(projekt, 0) % len(PROJEKT_FARBEN))


def _kaestchen(k, bloecke_liste, tag, von, schritt):
    """Zeichen und Block für einen Rasterabschnitt, oder (None, None) wenn leer."""
    belegt = k.belegung(bloecke_liste, tag, von, von + schritt)
    if not belegt:
        return None, None
    block, minuten = max(belegt, key=lambda x: x[1])
    return ("█" if minuten >= schritt / 2 else "▒"), block


def _legende(fenster, y, farben, bloecke_liste, x=2):
    namen = []
    for b in bloecke_liste:
        if b.projekt not in namen:
            namen.append(b.projekt)
    for name in namen:
        _schreibe(fenster, y, x, "██", _projektfarbe(farben, name))
        _schreibe(fenster, y, x + 3, name)
        x += len(name) + 6


def _termine_lesen(fenster, k, projekte, von, bis, liste):
    """Termine für die Ansicht — mit Hinweis, falls macOS gerade nach der
    Berechtigung fragt (das kann beim ersten Mal ein paar Sekunden dauern)."""
    if not zeit.kalender_quellen():
        return [], None
    hoehe, _ = fenster.getmaxyx()
    _schreibe(fenster, hoehe - 1, 2, "Kalender werden gelesen … (beim ersten Mal fragt macOS nach "
                                     "der Berechtigung)", curses.A_DIM)
    _auffrischen(fenster)
    return k.termine_im_zeitraum(projekte, von, bis, liste)


def _termin_belegt(termine_liste, tag, von, bis):
    """Liegt in diesem Rasterabschnitt ein Termin? -> (Zeichen, schon übernommen)."""
    beginn = datetime.combine(tag, datetime.min.time()) + timedelta(minutes=von)
    schluss = beginn + timedelta(minutes=bis - von)
    for a in termine_liste:
        if a.termin.start < schluss and beginn < a.termin.ende and a.termin.start.date() == tag:
            return "░", a.uebernommen
    return None, None


def _zeichne_tag(fenster, k, farben, tag, oben):
    """Tagesansicht: eine vertikale Leiste. Rückgabe: wie viele Zeilen nicht passen."""
    hoehe, breite = fenster.getmaxyx()
    projekte = zeit.lade_config()[0]
    liste = k.bloecke(projekte, tag, tag)
    termine_liste, hinweis = _termine_lesen(fenster, k, projekte, tag, tag, liste)
    summe = sum(b.minuten for b in liste)
    tomaten = sum(1 for b in liste if b.art == zeit.ART_POMODORO)
    kopf = f"{k.WOCHENTAGE_LANG[tag.weekday()]}, {tag:%d.%m.%Y}   ·   gesamt {k.std(summe)}"
    if tomaten:
        kopf += f"   ·   🍅 {tomaten}"
    _schreibe(fenster, 2, 2, kopf, curses.A_BOLD)

    y = 4
    ohne = [b for b in liste if not b.start]
    for b in ohne:
        _schreibe(fenster, y, 2, "ohne Uhrzeit │", curses.A_DIM)
        _schreibe(fenster, y, 17, "██", _projektfarbe(farben, b.projekt))
        _schreibe(fenster, y, 20, f"{k.std(b.minuten)}  {b.projekt} · {b.phase} {b.art}")
        y += 1
    if ohne:
        y += 1

    if hinweis:
        _schreibe(fenster, y, 2, f"⚠  {hinweis}", _warn())
        y += 2

    # Termine zählen beim Zeitfenster mit — sonst läge ein Termin um 8 Uhr
    # außerhalb, wenn die erste erfasste Zeit erst um 10 beginnt
    termin_bloecke = [k.Block("", "", "", a.termin.start.date(), a.termin.start,
                              min(a.termin.ende, datetime.combine(tag, datetime.max.time())), 0, False)
                      for a in termine_liste]
    if not any(b.start for b in liste) and not termin_bloecke:
        _schreibe(fenster, y, 4, "Keine Einträge mit Uhrzeit an diesem Tag.", curses.A_DIM)
        _legende(fenster, hoehe - 2, farben, liste)
        return 0
    von, bis = k.zeitfenster(liste + termin_bloecke)
    platz = max(1, hoehe - y - 4)
    schritt = k.feinheit(bis - von, platz)
    zeilen = list(range(von, bis, schritt))
    oben = max(0, min(oben, len(zeilen) - platz))
    for i, minute in enumerate(zeilen[oben:oben + platz]):
        zy = y + i
        _schreibe(fenster, zy, 2, f"{k.uhrzeit(minute)} │", curses.A_DIM)
        zeichen, block = _kaestchen(k, liste, tag, minute, schritt)
        if zeichen:
            _schreibe(fenster, zy, 10, zeichen * 18, _projektfarbe(farben, block.projekt)
                      | (curses.A_BOLD if block.laufend else 0))
        tz, fertig = _termin_belegt(termine_liste, tag, minute, minute + schritt)
        if tz:
            _schreibe(fenster, zy, 29, tz * 3, curses.A_DIM)
        # Beschriftung in der Zeile, in der ein Block oder Termin beginnt
        texte = []
        for a in termine_liste:
            s = a.termin.start
            if s.date() == tag and minute <= s.hour * 60 + s.minute < minute + schritt:
                texte.append(f"📅 {s:%H:%M}–{a.termin.ende:%H:%M} {a.termin.titel}"
                             + (" ✓" if a.uebernommen else ""))
        for b in liste:
            if b.start and minute <= b.start.hour * 60 + b.start.minute < minute + schritt:
                ende = "jetzt" if b.laufend else f"{b.ende:%H:%M}"
                texte.append(f"{b.start:%H:%M}–{ende}  {b.projekt} · {b.phase} {b.art}{b.fokus}"
                             f"{'  ▶ läuft' if b.laufend else ''}  ({k.std(b.minuten)})")
        if texte:
            _schreibe(fenster, zy, 34, "  ·  ".join(texte))
    if len(zeilen) > platz:
        _schreibe(fenster, y + platz, 2, f"↑↓ blättern ({oben + 1}–{oben + platz}"
                                         f" von {len(zeilen)} Zeilen)", curses.A_DIM)
    _legende(fenster, hoehe - 2, farben, liste)
    if termine_liste:
        _schreibe(fenster, hoehe - 2, breite - 34, "░ Termin (📅)   ✓ = übernommen", curses.A_DIM)
    return len(zeilen) - platz


def _zeichne_woche(fenster, k, farben, tag, oben):
    """Wochenansicht: sieben Tagesleisten nebeneinander."""
    hoehe, breite = fenster.getmaxyx()
    von_tag = k.montag(tag)
    tage = [von_tag + timedelta(days=i) for i in range(7)]
    projekte = zeit.lade_config()[0]
    liste = k.bloecke(projekte, tage[0], tage[-1])
    termine_liste, hinweis = _termine_lesen(fenster, k, projekte, tage[0], tage[-1], liste)
    summe = sum(b.minuten for b in liste)
    kw = von_tag.isocalendar()[1]
    _schreibe(fenster, 2, 2, f"KW {kw} · {tage[0]:%d.%m.} – {tage[-1]:%d.%m.%Y}   ·   "
                             f"gesamt {k.std(summe)}", curses.A_BOLD)
    spalte = max(5, min(12, (breite - 10) // 7))
    heute = date.today()
    for i, t in enumerate(tage):
        attr = curses.A_BOLD | curses.color_pair(FARBE_TITEL) if t == heute else curses.A_BOLD
        _schreibe(fenster, 4, 9 + i * spalte, f"{k.WOCHENTAGE[i]} {t:%d.}"[:spalte - 1], attr)
    y = 5
    ohne = {t: sum(b.minuten for b in liste if b.datum == t and not b.start) for t in tage}
    if any(ohne.values()):
        _schreibe(fenster, y, 2, "o.Uhr │", curses.A_DIM)
        for i, t in enumerate(tage):
            if ohne[t]:
                _schreibe(fenster, y, 9 + i * spalte, f"✎{k.std(ohne[t])}"[:spalte - 1], curses.A_DIM)
        y += 1

    if hinweis:
        _schreibe(fenster, 3, 2, f"⚠  {hinweis}"[:breite - 4], _warn())
    termin_bloecke = [k.Block("", "", "", a.termin.start.date(), a.termin.start, a.termin.ende, 0, False)
                      for a in termine_liste if a.termin.start.date() == a.termin.ende.date()]
    von, bis = k.zeitfenster(liste + termin_bloecke)
    platz = max(1, hoehe - y - 5)
    schritt = k.feinheit(bis - von, platz)
    zeilen = list(range(von, bis, schritt))
    oben = max(0, min(oben, len(zeilen) - platz))
    for r, minute in enumerate(zeilen[oben:oben + platz]):
        zy = y + r
        beschriftung = f"{k.uhrzeit(minute)} │" if minute % 60 == 0 else "      │"
        _schreibe(fenster, zy, 2, beschriftung, curses.A_DIM)
        for i, t in enumerate(tage):
            zeichen, block = _kaestchen(k, liste, t, minute, schritt)
            breit = spalte - 3 if termine_liste else spalte - 1   # rechts Platz für Termine
            if zeichen:
                _schreibe(fenster, zy, 9 + i * spalte, zeichen * breit,
                          _projektfarbe(farben, block.projekt) | (curses.A_BOLD if block.laufend else 0))
            tz, fertig = _termin_belegt(termine_liste, t, minute, minute + schritt)
            if tz:
                _schreibe(fenster, zy, 9 + i * spalte + breit, "✓" if fertig else tz, curses.A_DIM)
    fuss = y + min(platz, len(zeilen))
    for i, t in enumerate(tage):
        m = sum(b.minuten for b in liste if b.datum == t)
        _schreibe(fenster, fuss, 9 + i * spalte, (k.std(m) if m else "–")[:spalte - 1],
                  curses.A_BOLD if m else curses.A_DIM)
    if len(zeilen) > platz:
        _schreibe(fenster, fuss + 1, 2, f"↑↓ blättern ({oben + 1}–{oben + platz} von {len(zeilen)})",
                  curses.A_DIM)
    _legende(fenster, hoehe - 2, farben, liste)
    if termine_liste:
        offen = sum(1 for a in termine_liste if not a.uebernommen)
        _schreibe(fenster, hoehe - 2, breite - 44,
                  f"░ Termin · ✓ übernommen · {offen} offen (a)", curses.A_DIM)
    return len(zeilen) - platz


def bildschirm_kalender(fenster):
    import kalender as k
    modus, tag, oben = "tag", date.today(), 0
    farben = k.projektfarben(zeit.lade_config()[0])
    fenster.timeout(30000)          # alle 30 s neu zeichnen, falls ein Timer läuft
    try:
        while True:
            fenster.erase()
            reiter = "[Tag]  Woche" if modus == "tag" else " Tag  [Woche]"
            _schreibe(fenster, 0, 2, f"Kalender   {reiter}",
                      curses.color_pair(FARBE_TITEL) | curses.A_BOLD)
            zeichne = _zeichne_tag if modus == "tag" else _zeichne_woche
            ueberstand = zeichne(fenster, k, farben, tag, oben)
            hoehe, _ = fenster.getmaxyx()
            einheit = "Tag" if modus == "tag" else "Woche"
            _schreibe(fenster, hoehe - 1, 2,
                      f"← → {einheit} davor/danach · t Tag · w Woche · h heute · ↑↓ blättern"
                      + (" · a Termin übernehmen" if zeit.kalender_quellen() else "")
                      + " · Esc/q zurück", curses.A_DIM)
            _auffrischen(fenster)

            taste = _taste(fenster)
            schritt = timedelta(days=1 if modus == "tag" else 7)
            if taste is None:
                continue
            if _ist_escape(taste) or taste == "q":
                return
            if taste == curses.KEY_LEFT:
                tag, oben = tag - schritt, 0
            elif taste == curses.KEY_RIGHT:
                tag, oben = tag + schritt, 0
            elif taste in ("t", "w", "\t"):
                modus = {"t": "tag", "w": "woche"}.get(taste, "woche" if modus == "tag" else "tag")
                oben = 0
            elif taste == "h":
                tag, oben = date.today(), 0
            elif taste == "a" and zeit.kalender_quellen():
                von = tag if modus == "tag" else k.montag(tag)
                fenster.timeout(-1)
                bildschirm_termine(fenster, k, von, von + timedelta(days=0 if modus == "tag" else 6))
                fenster.timeout(30000)
            elif taste == curses.KEY_DOWN:
                oben = min(oben + 1, max(0, ueberstand))
            elif taste == curses.KEY_UP:
                oben = max(0, oben - 1)
    finally:
        fenster.timeout(-1)


def bildschirm_termine(fenster, k, von, bis):
    """Liste der Termine im Zeitraum; Enter übernimmt einen als 📅-Eintrag."""
    pos = 0
    while True:
        projekte, phasen = zeit.lade_config()
        liste, hinweis = k.termine_im_zeitraum(projekte, von, bis)
        if hinweis:
            meldung(fenster, hinweis.split(". ", 1))
            return
        if not liste:
            meldung(fenster, ["Keine Termine in diesem Zeitraum."])
            return
        eintraege = []
        for a in liste:
            t = a.termin
            text = (f"{'✓' if a.uebernommen else ' '} {k.WOCHENTAGE[t.start.weekday()]} "
                    f"{t.start:%d.%m. %H:%M}–{t.ende:%H:%M}  {t.titel}  [{t.kalender}]")
            eintraege.append((text, curses.A_DIM if a.uebernommen else 0))
        art, pos = waehle(fenster, f"Termine übernehmen — {von:%d.%m.}"
                          + (f" – {bis:%d.%m.%Y}" if bis != von else f"{von:%Y}"),
                          [("✓ = schon übernommen", curses.A_DIM)], eintraege,
                          "↑↓ wählen · →/⏎ übernehmen · ←/q zurück", start=pos)
        if art != "wahl":
            return
        _termin_uebernehmen(fenster, k, projekte, phasen, liste[pos])


def _termin_uebernehmen(fenster, k, projekte, phasen, a):
    t = a.termin
    wann = f"{k.WOCHENTAGE[t.start.weekday()]} {t.start:%d.%m.%Y}, {t.start:%H:%M}–{t.ende:%H:%M}"
    if a.uebernommen:
        meldung(fenster, [t.titel, wann, "", "Dieser Termin ist schon übernommen."])
        return
    projekt, phase = a.projekt, a.phase
    vollstaendig = projekt in projekte and phase in phasen

    # Regel vollständig? Dann reicht ein Enter — oder man wählt etwas anderes.
    if vollstaendig:
        art, idx = waehle(fenster, f"Termin übernehmen — {t.titel}", [(wann, 0)],
                          [(f"Übernehmen als {projekt} / {phase}", 0),
                           ("Anderes Projekt / andere Phase wählen …", 0),
                           ("Abbrechen", curses.A_DIM)],
                          "↑↓ wählen · →/⏎ bestätigen · ←/q zurück")
        if art != "wahl" or idx == 2:
            return
        vollstaendig = idx == 0
    if not vollstaendig:
        projekt = _liste_waehlen(fenster, f"{t.titel} — Projekt", list(projekte),
                                 "+ neues Projekt anlegen …", vorschlag=projekt)
        if projekt is NEU:
            projekt = _neues_projekt(fenster, projekte, phasen)
        if projekt is None:
            return
        projekte, phasen = zeit.lade_config()
        phase = _liste_waehlen(fenster, f"{t.titel} — Phase", phasen,
                               "+ neue Phase anlegen …", vorschlag=phase)
        if phase is NEU:
            phase = _neue_phase(fenster, projekte, phasen)
        if phase is None:
            return

    if a.konflikte:
        if not frage_ja_nein(fenster, [t.titel, wann, f"→ {projekt} / {phase}", "",
                                       "⚠  Überschneidet sich mit:"]
                             + [f"   {x}" for x in a.konflikte[:5]] + ["", "Trotzdem übernehmen?"],
                             standard=False):
            return
    try:
        k.termin_uebernehmen(zeit.lade_config()[0], t, projekt, phase)
    except ValueError as grund:
        meldung(fenster, [t.titel, "", str(grund)])
        return
    import termine
    termine._ZWISCHENSPEICHER.clear()           # ✓ soll sofort erscheinen
    meldung(fenster, ["✓ Übernommen", "", t.titel, wann, f"→ {projekt} / {phase}  (📅)"])


# ===========================================================================
# Statistik
# ===========================================================================

def _balken(anteil, breite=24):
    voll = int(round(anteil * breite))
    return "█" * voll + "·" * (breite - voll)


def statistik_zeilen(k, s, farben, art):
    """Das Statistik-Board als Liste von (text, attr) — zum Blättern in waehle."""
    z = []

    def ueber(text):
        z.extend([("", 0), (f"── {text} " + "─" * max(0, 50 - len(text)),
                            curses.color_pair(FARBE_TITEL) | curses.A_BOLD)])

    z.append((f"Gesamt {k.std(s['gesamt'])}   ·   {s['arbeitstage']} Arbeitstag"
              f"{'e' if s['arbeitstage'] != 1 else ''}   ·   Ø {k.std(s['schnitt'])} pro Arbeitstag",
              curses.A_BOLD))
    if s["laengster"]:
        tag, m = s["laengster"]
        z.append((f"Längster Tag: {k.WOCHENTAGE[tag.weekday()]} {tag:%d.%m.%Y} ({k.std(m)})"
                  + (f"   ·   🍅 {s['pomodoros']} Pomodoros" if s["pomodoros"] else ""), 0))

    # --- Verlauf: je nach Zeitraum pro Tag, pro Woche oder pro Monat ------------
    werte = s["pro_tag"]
    if art in ("jahr", "alles"):
        gruppen = {}
        for tag, m in werte:
            schluessel = (tag.year, tag.month) if art == "alles" else k.montag(tag)
            gruppen[schluessel] = gruppen.get(schluessel, 0) + m
        if art == "alles":
            werte = [(f"{k.MONATE[mo - 1][:3]} {j}", m) for (j, mo), m in sorted(gruppen.items())]
            ueber("Verlauf pro Monat")
        else:
            werte = [(f"KW {t.isocalendar()[1]:>2} ({t:%d.%m.})", m) for t, m in sorted(gruppen.items())]
            ueber("Verlauf pro Woche")
    else:
        werte = [(f"{k.WOCHENTAGE[t.weekday()]} {t:%d.%m.}", m) for t, m in werte]
        ueber("Verlauf pro Tag")
    groesster = max((m for _, m in werte), default=0) or 1
    for name, m in werte:
        z.append((f"{name:<16}{_balken(m / groesster)}  {k.std(m) if m else '–'}",
                  0 if m else curses.A_DIM))

    # --- Verteilung ----------------------------------------------------------------
    gesamt = s["gesamt"] or 1
    ueber("Projekte")
    for name, m in s["pro_projekt"]:
        tomaten = s["pomodoros_projekt"].get(name, 0)
        z.append((f"{name:<22}{_balken(m / gesamt)} {k.std(m):>6}  {round(m * 100 / gesamt):>3} %"
                  + (f"   🍅 {tomaten}" if tomaten else ""), _projektfarbe(farben, name)))
    ueber("Phasen")
    for name, m in s["pro_phase"]:
        tomaten = s["pomodoros_phase"].get(name, 0)
        z.append((f"{name:<22}{_balken(m / gesamt)} {k.std(m):>6}  {round(m * 100 / gesamt):>3} %"
                  + (f"   🍅 {tomaten}" if tomaten else ""), 0))
    ueber("Projekt × Phase")
    for projekt, phasen in sorted(s["projekt_phase"].items(), key=lambda x: -sum(m for _, m in x[1])):
        z.append((f"{projekt:<22}{k.std(sum(m for _, m in phasen)):>6}",
                  _projektfarbe(farben, projekt) | curses.A_BOLD))
        for phase, m in phasen:
            z.append((f"   {phase:<19}{k.std(m):>6}", 0))

    # --- Fokus & Notizen (freiwilliges Feedback nach jedem Block) --------------------
    ueber("Fokus & Notizen")
    bewertet = sum(s["fokus"][f]["anzahl"] for f in zeit.FOKUS_WERTE)
    if bewertet:
        for f in zeit.FOKUS_WERTE:
            n, m = s["fokus"][f]["anzahl"], s["fokus"][f]["minuten"]
            z.append((f"{f} {zeit.FOKUS_NAMEN[f]:<12}{_balken(n / bewertet, 20)} {n:>3}×  "
                      f"{round(n * 100 / bewertet):>3} %  ·  {k.std(m)} h", 0))
        ohne = s["fokus"][""]["anzahl"]
        if ohne:
            z.append((f"   ohne Bewertung: {ohne}×", curses.A_DIM))
        if s["fokus_phase"]:
            z.append(("", 0))
            for phase, werte in sorted(s["fokus_phase"].items()):
                z.append((f"   {phase:<20}" + "   ".join(f"{f} {werte[f]}" for f in zeit.FOKUS_WERTE), 0))
    else:
        z.append(("(noch keine Fokus-Bewertungen in diesem Zeitraum)", curses.A_DIM))
    if s["notizen"]:
        z.append(("", 0))
        for tag, start, projekt, phase, f, notiz in s["notizen"]:
            wann = f"{k.WOCHENTAGE[tag.weekday()]} {tag:%d.%m.}" + (f" {start:%H:%M}" if start else "")
            z.append((f"   {wann:<16}{projekt} / {phase}  {f}".rstrip(), curses.A_DIM))
            z.append((f"      „{notiz}“", 0))

    # --- Arbeitsrhythmus -------------------------------------------------------------
    rhythmus = s["rhythmus"]
    stunden = [h for h in range(24) if any(rhythmus[w][h] for w in range(7))]
    ueber("Arbeitsrhythmus")
    if stunden:
        von, bis = min(stunden), max(stunden) + 1
        hoechster = max(rhythmus[w][h] for w in range(7) for h in range(24)) or 1
        stufen = " ░▒▓█"
        z.append(("      " + "".join(f"{h:<3}" if h % 3 == 0 else "   " for h in range(von, bis)),
                  curses.A_DIM))
        for w in range(7):
            zeile = "".join(stufen[max(1, min(4, int(round(rhythmus[w][h] / hoechster * 4))))] * 3
                            if rhythmus[w][h] else " · " for h in range(von, bis))
            z.append((f"  {k.WOCHENTAGE[w]}  {zeile}", 0))
        z.append(("", 0))
        z.append((f"Typischer Tagesbeginn {k.uhrzeit(s['beginn'])} Uhr · Tagesende "
                  f"{k.uhrzeit(s['ende'])} Uhr", 0))
        groesster = max(s["wochentage"]) or 1
        for w, m in enumerate(s["wochentage"]):
            z.append((f"  {k.WOCHENTAGE_LANG[w]:<12}{_balken(m / groesster, 20)} "
                      f"{k.std(m) if m else '–'}", 0 if m else curses.A_DIM))
    else:
        z.append(("(keine Einträge mit Uhrzeit)", curses.A_DIM))
    return z


def bildschirm_statistik(fenster):
    import kalender as k
    art, schritt, pos = "woche", 0, 0
    projekte, _ = zeit.lade_config()
    farben = k.projektfarben(projekte)
    fruehester = k.fruehestes_datum(projekte)
    while True:
        von, bis, titel = k.zeitraum(art, date.today(), schritt, fruehester)
        s = k.statistik(projekte, von, bis)
        zeilen = statistik_zeilen(k, s, farben, art)
        reiter = "  ".join(f"[{k.ZEITRAUM_NAMEN[a]}]" if a == art else f" {k.ZEITRAUM_NAMEN[a]} "
                           for a in k.ZEITRAUM_ARTEN)
        ergebnis, wert = waehle(
            fenster, f"Statistik — {titel}", [(reiter, curses.A_DIM)], zeilen,
            "z Zeitraum · ← → davor/danach · h aktuell · ↑↓ blättern · Esc/q zurück",
            zusatztasten="zh", start=pos, auswaehlbar=False, links_zurueck=False, blaettern=True)
        if ergebnis == "zurueck":
            return
        taste, pos = wert
        if taste == "z":
            art, schritt, pos = k.ZEITRAUM_ARTEN[(k.ZEITRAUM_ARTEN.index(art) + 1) % 4], 0, 0
        elif taste == "h":
            schritt, pos = 0, 0
        elif art != "alles":
            schritt += -1 if taste == "←" else 1
            pos = 0


# ===========================================================================
# Pomodoro
# ===========================================================================

def formular_zahlen(fenster, titel, felder, hinweis=""):
    """Kleines Formular aus Zahlenfeldern.

    felder: Liste von dicts mit schluessel, name, wert, min, max, einheit.
    Bedienung wie im Nachtrag-Formular: ↑↓ Feld, ←→ ±1, tippen überschreibt,
    ⏎ bestätigt, Esc bricht ab. Rückgabe: {schluessel: wert} oder None.
    """
    werte = {f["schluessel"]: int(f["wert"]) for f in felder}
    feld, puffer, fehler = 0, None, ""
    knopf = len(felder)

    def uebernehmen():
        nonlocal puffer, fehler
        if puffer is None or not puffer.strip():
            puffer = None
            return True
        f = felder[feld]
        text, puffer = puffer, None
        if not text.strip().isdigit() or not f["min"] <= int(text) <= f["max"]:
            fehler = f"{f['name']}: bitte eine Zahl von {f['min']} bis {f['max']}."
            return False
        werte[f["schluessel"]] = int(text)
        return True

    while True:
        fenster.erase()
        _schreibe(fenster, 0, 2, titel, curses.color_pair(FARBE_TITEL) | curses.A_BOLD)
        if hinweis:
            _schreibe(fenster, 1, 4, hinweis, curses.A_DIM)
        for i, f in enumerate(felder):
            gewaehlt = i == feld
            wert = (puffer + "▌") if (gewaehlt and puffer is not None) else str(werte[f["schluessel"]])
            wert = f"◂ {wert} ▸" if (gewaehlt and puffer is None) else f"  {wert}"
            _schreibe(fenster, 3 + i, 2, "▸ " if gewaehlt else "  ")
            _schreibe(fenster, 3 + i, 4, f"{f['name']:<20}", curses.A_BOLD if gewaehlt else 0)
            _schreibe(fenster, 3 + i, 24, f" {wert} ",
                      curses.color_pair(FARBE_AKTIV) | curses.A_BOLD if gewaehlt else 0)
            _schreibe(fenster, 3 + i, 38, f["einheit"], curses.A_DIM)
        _schreibe(fenster, 4 + len(felder), 2, "▸ " if feld == knopf else "  ")
        _schreibe(fenster, 4 + len(felder), 4, " OK ",
                  curses.color_pair(FARBE_AKTIV) | curses.A_BOLD if feld == knopf else curses.A_BOLD)
        if fehler:
            _schreibe(fenster, 6 + len(felder), 4, f"⚠  {fehler}", _warn())
        hoehe, _ = fenster.getmaxyx()
        _schreibe(fenster, hoehe - 1, 2,
                  "↑↓ Feld · ←→ ±1 · Zahl tippen · ⏎ OK · Esc abbrechen", curses.A_DIM)
        _auffrischen(fenster)

        t = _taste(fenster)
        if t is None:
            continue
        if _ist_escape(t):
            if puffer is not None:
                puffer = None
                continue
            return None
        if t in (curses.KEY_UP, curses.KEY_DOWN, "\t", curses.KEY_BTAB):
            if uebernehmen():
                fehler = ""
                feld = max(0, min(knopf, feld + (-1 if t in (curses.KEY_UP, curses.KEY_BTAB) else 1)))
            continue
        if _ist_enter(t):
            if uebernehmen():
                return werte
            continue
        if t in (curses.KEY_LEFT, curses.KEY_RIGHT) and puffer is None and feld < knopf:
            f = felder[feld]
            neu = werte[f["schluessel"]] + (1 if t == curses.KEY_RIGHT else -1)
            werte[f["schluessel"]] = max(f["min"], min(f["max"], neu))
            fehler = ""
            continue
        if puffer is not None and _ist_rueckwaerts(t):
            puffer = puffer[:-1]
            continue
        if isinstance(t, str) and t.isdigit() and feld < knopf:
            puffer = t if puffer is None else puffer + t
            fehler = ""


def bildschirm_pomodoro_starten(fenster):
    auswahl = _projekt_und_phase_waehlen(fenster, "Pomodoro starten")
    if auswahl is None:
        return
    projekt, phase = auswahl
    projekte, _ = zeit.lade_config()
    ordner = projekte[projekt]
    if zeit.ist_fremde_datei(zeit.zeitdatei_pfad(ordner)):
        meldung(fenster, ["In diesem Ordner liegt eine Zeiterfassung.md,",
                          "die nicht von `zeit` stammt. Sie wird nicht angefasst."])
        return

    # Vorgeschlagen werden die zuletzt benutzten Werte
    e = zeit.lade_einstellungen()
    g = zeit.POMODORO_GRENZEN
    werte = formular_zahlen(fenster, f"Pomodoro starten — {projekt} / {phase}", [
        {"schluessel": "fokus", "name": "Fokus", "wert": e["pomodoro-fokus"],
         "min": g["fokus"][0], "max": g["fokus"][1], "einheit": "Minuten"},
        {"schluessel": "kurz", "name": "Kurze Pause", "wert": e["pomodoro-kurze-pause"],
         "min": g["kurz"][0], "max": g["kurz"][1], "einheit": "Minuten"},
        {"schluessel": "lang", "name": "Lange Pause", "wert": e["pomodoro-lange-pause"],
         "min": g["lang"][0], "max": g["lang"][1], "einheit": "Minuten"},
        {"schluessel": "nach", "name": "Lange Pause nach", "wert": e["pomodoro-lange-pause-nach"],
         "min": g["nach"][0], "max": g["nach"][1], "einheit": "Pomodoros"},
    ], hinweis="Vorgeschlagen: die zuletzt benutzten Werte.")
    if werte is None:
        return
    if not _vorher_beenden(fenster, zeit.lade_config()[0]):
        return
    zeit.pomodoro_starten(ordner, phase, werte)
    bildschirm_pomodoro(fenster)


def _heute_pomodoros(projekte):
    heute = date.today()
    return sum(1 for e in zeit.alle_eintraege(projekte, warner=lambda _: None)
               if e.datum == heute and e.art == zeit.ART_POMODORO)


def bildschirm_sitzung(fenster):
    """Live-Ansicht für Pomodoro und Countdown: sekundengenaue Restzeit,
    Fortschritt, Aktionen per Taste. Mit ← zurück ins Menü — es läuft weiter."""
    zeit.wecker_sicherstellen(zeit.lade_config()[0])

    def blockierend(funktion, *argumente):
        """Dialoge brauchen echtes Warten auf eine Taste, nicht den 1-s-Takt."""
        fenster.timeout(-1)
        try:
            return funktion(fenster, *argumente)
        finally:
            fenster.timeout(1000)

    fenster.timeout(1000)            # jede Sekunde neu zeichnen
    try:
        heute, zuletzt_gezaehlt = 0, 0
        while True:
            projekte, _ = zeit.lade_config()
            aktiv, _ = _laufend(projekte)
            if not aktiv or not aktiv[2].sitzung or aktiv[2].sitzung["typ"] == "timer":
                return                                   # beendet (oder nur Timer)
            name, ordner, datei = aktiv
            z = datei.sitzung
            pomodoro = z["typ"] == "pomodoro"
            angehalten = z["zustand"] == "angehalten"
            if pomodoro and time_now() - zuletzt_gezaehlt > 10:
                heute, zuletzt_gezaehlt = _heute_pomodoros(projekte), time_now()

            jetzt = datetime.now()
            if angehalten:
                rest, vergangen, gesamt = z["rest"], None, None
            else:
                gesamt = z["plan"] * 60
                vergangen = (jetzt - z["seit"]).total_seconds()
                rest = gesamt - vergangen
            symbol, was, info = zeit.sitzung_text(z, jetzt)

            fenster.erase()
            art = "Pomodoro" if pomodoro else "Countdown"
            _schreibe(fenster, 0, 2, f"{art} — {name} / {z['phase']}",
                      curses.color_pair(FARBE_TITEL) | curses.A_BOLD)
            titel = (f"{symbol} Fokus {zeit.satz_position(z)} von {z['nach']}"
                     if pomodoro and z["zustand"] == "fokus" else f"{symbol} {was}")
            _schreibe(fenster, 2, 5, titel, curses.A_BOLD)

            sekunden = int(abs(rest))
            stunden = f"{sekunden // 3600}:" if sekunden >= 3600 else ""
            uhr = (f"{'+' if rest < 0 else ''}{stunden}"
                   f"{(sekunden % 3600) // 60:02d}:{sekunden % 60:02d}")
            farbe = (curses.A_DIM if angehalten else
                     _warn() if rest < 0 else curses.color_pair(FARBE_LAEUFT))
            _schreibe(fenster, 4, 12, uhr, farbe | curses.A_BOLD)

            if angehalten:
                _schreibe(fenster, 5, 5, f"⏸  angehalten {info}", _warn())
            else:
                breite = 30
                voll = min(breite, int(breite * vergangen / gesamt)) if gesamt > 0 else breite
                balken = "█" * voll + "░" * (breite - voll)
                text = (f"noch {int(rest // 60) + 1} min" if rest > 0
                        else f"{int(-rest // 60)} min überzogen")
                if z["typ"] == "countdown" and rest > 0:
                    text += f" · Ende {zeit.sitzung_ende(z):%H:%M}"
                _schreibe(fenster, 5, 5, f"{balken}  {text}", farbe if rest < 0 else 0)

            if pomodoro:
                position = zeit.satz_position(z)
                fertig = position if z["zustand"] == "pause" else position - 1
                punkte = "".join("●" if i < fertig else ("◐" if i == fertig and
                                                          z["zustand"] != "pause" else "○")
                                 for i in range(z["nach"]))
                _schreibe(fenster, 7, 5, f"{punkte}   heute: {heute} Pomodoro"
                                         f"{'s' if heute != 1 else ''}")
                _schreibe(fenster, 8, 5, f"Fokus {z['fokus']} · Pause {z['kurz']} / {z['lang']} min"
                                         f" · lange Pause nach {z['nach']}", curses.A_DIM)
            if not datei.laeuft:
                _schreibe(fenster, 9, 5, "Es wird gerade keine Zeit erfasst.", curses.A_DIM)

            x = zeit.lade_einstellungen()["pomodoro-verlaengern"]
            tasten = []
            if angehalten:
                tasten.append("f fortsetzen")
            else:
                if pomodoro:
                    tasten.append("p Pause starten" if z["zustand"] == "fokus" else "w weiter mit Fokus")
                tasten.append(f"n noch {x} min")
                if datei.laeuft:
                    tasten.append("h anhalten")
            tasten += ["s beenden", "a abbrechen", "← Menü"]
            hoehe, _ = fenster.getmaxyx()
            _schreibe(fenster, hoehe - 1, 2, " · ".join(tasten), curses.A_DIM)
            _auffrischen(fenster)

            t = _taste(fenster)
            if t is None:
                continue
            if t == curses.KEY_LEFT or _ist_escape(t) or t == "q":
                return
            if angehalten:
                if t == "f":
                    zeit.fortsetzen(ordner, datei)
            elif t == "p" and pomodoro and z["zustand"] == "fokus":
                ergebnis = zeit.pomodoro_pause(ordner, datei)
                if ergebnis:                           # Fokusblock fertig -> Feedback
                    blockierend(feedback_tui, zeit.fokusblock_bericht(name, ergebnis), ordner,
                                (f"{ergebnis[2]:%Y-%m-%d}", f"{ergebnis[2]:%H:%M}"))
            elif t == "w" and pomodoro and z["zustand"] == "pause":
                zeit.pomodoro_weiter(ordner, datei)
            elif t == "n":
                zeit.verlaengern(ordner, datei, x)
            elif t == "h" and datei.laeuft:
                zeit.anhalten(ordner, datei)
            if t == "s":
                if blockierend(frage_ja_nein, [
                        f"{art} beenden?", "",
                        "Die laufende Zeit wird bis jetzt eingetragen." if datei.laeuft
                        else "Gerade läuft keine Zeit — nichts einzutragen."], True):
                    blockierend(bericht_zeigen, name, ordner, datei)
                    return
            elif t == "a":
                blockierend(lambda f: bildschirm_abbrechen(f))
                if not _laufend(zeit.lade_config()[0])[0]:
                    return
    finally:
        fenster.timeout(-1)


bildschirm_pomodoro = bildschirm_sitzung     # älterer Name


def formular_countdown(fenster, projekt, phase):
    """Art (Dauer / Bis) und Wert. Rückgabe: (minuten, art) oder None."""
    e = zeit.lade_einstellungen()
    art = e["countdown-art"] if e["countdown-art"] in ("dauer", "bis") else "dauer"
    dauer = e["countdown-dauer"]
    bis_zp = datetime.now() + timedelta(minutes=dauer)
    bis_zp = (bis_zp + timedelta(minutes=7)).replace(second=0, microsecond=0)
    bis_zp = bis_zp.replace(minute=bis_zp.minute - bis_zp.minute % 15)     # auf 15 min
    texte = {"dauer": f"{dauer // 60}:{dauer % 60:02d}", "bis": f"{bis_zp:%H:%M}"}
    feld, puffer, fehler = 1, None, ""

    while True:
        fenster.erase()
        _schreibe(fenster, 0, 2, f"Countdown starten — {projekt} / {phase}",
                  curses.color_pair(FARBE_TITEL) | curses.A_BOLD)
        _schreibe(fenster, 1, 4, "Vorgeschlagen: wie beim letzten Mal.", curses.A_DIM)
        schalter = "(•) Dauer   ( ) Bis Uhrzeit" if art == "dauer" else "( ) Dauer   (•) Bis Uhrzeit"
        zeilen = [("Art", schalter), ("Dauer" if art == "dauer" else "Bis", None)]
        for i, (name, wert) in enumerate(zeilen):
            gewaehlt = i == feld
            if wert is None:
                wert = (puffer + "▌") if (gewaehlt and puffer is not None) else texte[art]
                beispiel = "z. B. 2h, 1:30, 90min" if art == "dauer" else "z. B. 17:00"
            else:
                beispiel = ""
            _schreibe(fenster, 3 + i, 2, "▸ " if gewaehlt else "  ")
            _schreibe(fenster, 3 + i, 4, f"{name:<10}", curses.A_BOLD if gewaehlt else 0)
            _schreibe(fenster, 3 + i, 14, f" {wert} ",
                      curses.color_pair(FARBE_AKTIV) | curses.A_BOLD if gewaehlt else 0)
            _schreibe(fenster, 3 + i, 46, beispiel, curses.A_DIM)
        _schreibe(fenster, 6, 2, "▸ " if feld == 2 else "  ")
        _schreibe(fenster, 6, 4, " Starten ",
                  curses.color_pair(FARBE_AKTIV) | curses.A_BOLD if feld == 2 else curses.A_BOLD)
        if fehler:
            _schreibe(fenster, 8, 4, f"⚠  {fehler}", _warn())
        hoehe, _ = fenster.getmaxyx()
        _schreibe(fenster, hoehe - 1, 2,
                  "↑↓ Feld · ←→ Art umschalten · tippen überschreibt · ⏎ starten · Esc abbrechen",
                  curses.A_DIM)
        _auffrischen(fenster)

        t = _taste(fenster)
        if t is None:
            continue
        if _ist_escape(t):
            if puffer is not None:
                puffer = None
                continue
            return None
        if puffer is not None and (t in (curses.KEY_UP, curses.KEY_DOWN, "\t") or _ist_enter(t)):
            if puffer.strip():
                texte[art] = puffer.strip()
            puffer = None
        if t in (curses.KEY_UP, curses.KEY_DOWN, "\t"):
            feld = max(0, min(2, feld + (-1 if t == curses.KEY_UP else 1)))
            continue
        if _ist_enter(t):
            try:
                return zeit.countdown_minuten(art, texte[art]), art
            except ValueError as grund:
                fehler = str(grund)
                continue
        if feld == 0 and (t in (curses.KEY_LEFT, curses.KEY_RIGHT) or t == " "):
            art = "bis" if art == "dauer" else "dauer"
            fehler = ""
            continue
        if puffer is not None and _ist_rueckwaerts(t):
            puffer = puffer[:-1]
            continue
        if feld == 1 and isinstance(t, str) and t.isprintable():
            puffer = t if puffer is None else puffer + t
            fehler = ""


def bildschirm_countdown_starten(fenster):
    auswahl = _projekt_und_phase_waehlen(fenster, "Countdown starten")
    if auswahl is None:
        return
    projekt, phase = auswahl
    projekte, _ = zeit.lade_config()
    ordner = projekte[projekt]
    if zeit.ist_fremde_datei(zeit.zeitdatei_pfad(ordner)):
        meldung(fenster, ["In diesem Ordner liegt eine Zeiterfassung.md,",
                          "die nicht von `zeit` stammt. Sie wird nicht angefasst."])
        return
    ergebnis = formular_countdown(fenster, projekt, phase)
    if ergebnis is None:
        return
    if not _vorher_beenden(fenster, zeit.lade_config()[0]):
        return
    zeit.countdown_starten(ordner, phase, *ergebnis)
    bildschirm_sitzung(fenster)


def time_now():
    return datetime.now().timestamp()


def _ton_abspielen(ton):
    """Kurze Hörprobe, im Hintergrund, damit das TUI nicht wartet."""
    if ton != zeit.KEIN_TON:
        subprocess.Popen(["afplay", f"/System/Library/Sounds/{ton}.aiff"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def bildschirm_kalenderwahl(fenster):
    """Welche Kalender der Kalender-App in zeit erscheinen — an- und abhaken."""
    import termine
    hoehe, _ = fenster.getmaxyx()
    _schreibe(fenster, hoehe - 1, 2, "Kalender werden gelesen … (beim ersten Mal fragt macOS "
                                     "nach der Berechtigung)", curses.A_DIM)
    _auffrischen(fenster)
    try:
        namen = termine.kalender_namen()
    except termine.KeineBerechtigung as grund:
        meldung(fenster, str(grund).split(". ", 1))
        return
    except Exception as grund:
        meldung(fenster, ["Kalender konnten nicht gelesen werden:", str(grund)[:70]])
        return
    pos = 0
    while True:
        e = zeit.lade_einstellungen()
        gewaehlt = zeit.kalender_quellen(e)
        art, pos = waehle(fenster, "Einstellungen — Kalender",
                          [("Termine aus diesen Kalendern erscheinen im Kalender von zeit.", curses.A_DIM),
                           ("Nur lesen: an deinen Kalendern ändert zeit nie etwas.", curses.A_DIM)],
                          [(f"[{'✓' if n in gewaehlt else ' '}] {n}", 0) for n in namen],
                          "↑↓ wählen · ⏎ an/aus · ←/q fertig", start=pos)
        if art != "wahl":
            return
        name = namen[pos]
        gewaehlt = [n for n in gewaehlt if n != name] if name in gewaehlt else gewaehlt + [name]
        e["kalender-quellen"] = "; ".join(gewaehlt)
        zeit.speichere_einstellungen(e)


def _regel_anlegen(fenster):
    """Fragt eine neue Regel ab. Rückgabe: zeit.Regel oder None."""
    art, idx = waehle(fenster, "Neue Kalender-Regel — wenn …", [],
                      [("… der Titel einen Text enthält", 0), ("… der Termin in einem bestimmten Kalender ist", 0)],
                      "↑↓ wählen · →/⏎ weiter · ←/q zurück")
    if art != "wahl":
        return None
    if idx == 0:
        wert = frage_text(fenster, ["Welcher Text im Titel?", "(Groß-/Kleinschreibung egal, z. B. Hotel Seeblick)"])
    else:
        quellen = zeit.kalender_quellen()
        if not quellen:
            meldung(fenster, ["Erst unter Einstellungen → Kalender", "Kalender auswählen."])
            return None
        wahl, i = waehle(fenster, "Neue Kalender-Regel — welcher Kalender?", [],
                         [(n, 0) for n in quellen], "↑↓ wählen · →/⏎ weiter · ←/q zurück")
        wert = quellen[i] if wahl == "wahl" else None
    if not wert:
        return None
    projekte, phasen = zeit.lade_config()
    fragen = "? — jedes Mal nachfragen"
    wahl, i = waehle(fenster, "Neue Kalender-Regel — Projekt", [],
                     [(fragen, curses.A_DIM)] + [(p, 0) for p in projekte],
                     "↑↓ wählen · →/⏎ weiter · ←/q zurück")
    if wahl != "wahl":
        return None
    projekt = zeit.FRAGEN if i == 0 else list(projekte)[i - 1]
    wahl, i = waehle(fenster, "Neue Kalender-Regel — Phase", [],
                     [(fragen, curses.A_DIM)] + [(p, 0) for p in phasen],
                     "↑↓ wählen · →/⏎ weiter · ←/q zurück")
    if wahl != "wahl":
        return None
    phase = zeit.FRAGEN if i == 0 else phasen[i - 1]
    return zeit.Regel("titel" if idx == 0 else "kalender", wert.strip(), projekt, phase)


def bildschirm_regeln(fenster):
    """Kalender-Regeln: welcher Termin zu welchem Projekt/welcher Phase gehört."""
    pos = 0
    while True:
        regeln = zeit.lade_regeln()
        eintraege = [(f"{zeit.regel_text(r):<32} → {r.projekt} / {r.phase}", 0) for r in regeln]
        if not eintraege:
            eintraege = [("(noch keine Regeln — mit n anlegen)", curses.A_DIM)]
        art, wert = waehle(
            fenster, "Einstellungen — Kalender-Regeln",
            [("Die erste passende Regel gilt. „?“ = beim Übernehmen nachfragen.", curses.A_DIM),
             ("n neu   d löschen   K/J verschieben", curses.A_DIM)],
            eintraege, "↑↓ wählen · ←/q zurück", zusatztasten="ndKJ", start=pos,
            auswaehlbar=bool(regeln))
        if art == "zurueck":
            return
        if art != "taste":
            continue
        zeichen, pos = wert
        if zeichen == "n":
            regel = _regel_anlegen(fenster)
            if regel:
                zeit.speichere_regeln(regeln + [regel])
                pos = len(regeln)
        elif not regeln:
            continue
        elif zeichen == "d":
            if frage_ja_nein(fenster, [f"Regel „{zeit.regel_text(regeln[pos])}“ löschen?"], standard=False):
                zeit.speichere_regeln(regeln[:pos] + regeln[pos + 1:])
                pos = max(0, pos - 1)
        elif zeichen in "KJ":
            regeln, pos = _verschoben(regeln, pos, -1 if zeichen == "K" else 1)
            zeit.speichere_regeln(regeln)


def bildschirm_einstellungen(fenster):
    pos = 0
    while True:
        e = zeit.lade_einstellungen()
        quellen = zeit.kalender_quellen(e)
        punkte = [f"{'Ton':<22}{e['pomodoro-ton']}",
                  f"{'„Noch X min“':<22}{e['pomodoro-verlaengern']} min",
                  f"{'Kalender':<22}{', '.join(quellen) if quellen else '(keine — Termine aus)'}",
                  f"{'Kalender-Regeln':<22}{len(zeit.lade_regeln())} Regel(n)",
                  f"{'Akzentfarbe':<22}{e['akzentfarbe']}",
                  f"{'In Kalender schreiben':<22}"
                  f"{'an — Kalender „zeit“' if e['kalender-schreiben'] == 'an' else 'aus'}",
                  f"{'Klick auf Menüleiste':<22}{zeit.KLICK_ARTEN.get(e['menueleiste-klick'], '?')}",
                  f"{'Farbschema':<22}{e['farbschema']}",
                  f"{'Anzeige':<22}{zeit.ANZEIGEN.get(e['anzeige'], '?')}",
                  f"{'Popup-Größe (GUI)':<22}{zeit.POPUP_GROESSEN.get(e['popup-groesse'], ('?',))[0]}",
                  f"{'Projektordner':<22}{e['projektordner']}",
                  f"{'Tutorial':<22}noch einmal durchgehen"]
        art, idx = waehle(fenster, "Einstellungen",
                          [("Fokus- und Pausenlängen stellst du bei jedem Pomodoro-Start ein.",
                            curses.A_DIM)],
                          [(x, 0) for x in punkte], "↑↓ wählen · →/⏎ ändern · ←/q zurück",
                          start=pos)
        if art != "wahl":
            return
        pos = idx
        if idx == 0:
            toene = zeit.TOENE + [zeit.KEIN_TON]
            aktuell = toene.index(e["pomodoro-ton"]) if e["pomodoro-ton"] in toene else 0
            art2, wahl = waehle(fenster, "Einstellungen — Ton", [],
                                [(x, 0) for x in toene], "↑↓ wählen · →/⏎ übernehmen · ←/q zurück",
                                start=aktuell)
            if art2 == "wahl":
                e["pomodoro-ton"] = toene[wahl]
                zeit.speichere_einstellungen(e)
                _ton_abspielen(toene[wahl])
        elif idx == 2:
            bildschirm_kalenderwahl(fenster)
        elif idx == 3:
            bildschirm_regeln(fenster)
        elif idx == 6:
            arten = list(zeit.KLICK_ARTEN)
            art2, wahl = waehle(fenster, "Einstellungen — Klick auf das Menüleisten-Symbol",
                                [("Klappmenü: wie bisher. Popup: TUI oder GUI (Einstellung „Anzeige“)",
                                  curses.A_DIM),
                                 ("klappt unter dem Symbol auf. Terminalfenster: öffnet direkt eins.",
                                  curses.A_DIM),
                                 ("Die Menüleiste zeigt in jedem Fall weiter den aktuellen Stand.",
                                  curses.A_DIM)],
                                [(zeit.KLICK_ARTEN[a], 0) for a in arten],
                                "↑↓ wählen · →/⏎ übernehmen · ←/q zurück",
                                start=arten.index(e["menueleiste-klick"]))
            if art2 == "wahl":
                e["menueleiste-klick"] = arten[wahl]
                zeit.speichere_einstellungen(e)
        elif idx == 11:
            import tutorial
            tutorial.starten(fenster)
            return                              # danach ins Hauptmenü
        elif idx == 10:
            text = frage_text(fenster, ["Projektordner — hier schlägt zeit Ordner für neue",
                                        "Projekte vor (oder findet passende vorhandene):"],
                              e["projektordner"])
            if text:
                ordner = Path(text).expanduser()
                if ordner.is_dir():
                    e["projektordner"] = text
                    zeit.speichere_einstellungen(e)
                else:
                    meldung(fenster, [f"Den Ordner {ordner} gibt es nicht."])
        elif idx in (8, 9):
            # Anzeige (TUI/GUI) bzw. Größe des GUI-Popups
            if idx == 8:
                werte, titel, hinweis = zeit.ANZEIGEN, "Anzeige", [
                    "Was im Popup unter dem Menüleisten-Symbol und im Fenster", "„⧉ Als Fenster öffnen“ zu sehen ist."]
                werte = {k_: v for k_, v in werte.items()}
                schluessel = "anzeige"
            else:
                werte = {k_: f"{g[0]} ({g[1]}×{g[2]})" for k_, g in zeit.POPUP_GROESSEN.items()}
                titel, hinweis, schluessel = "Popup-Größe (GUI)", ["Gilt nur für die GUI — das TUI braucht",
                                                                   "seine feste Breite."], "popup-groesse"
            namen = list(werte)
            art2, wahl = waehle(fenster, f"Einstellungen — {titel}", [(z, curses.A_DIM) for z in hinweis],
                                [(werte[n], 0) for n in namen], "↑↓ wählen · →/⏎ übernehmen · ←/q zurück",
                                start=namen.index(e[schluessel]) if e[schluessel] in namen else 0)
            if art2 == "wahl":
                e[schluessel] = namen[wahl]
                zeit.speichere_einstellungen(e)
                subprocess.run(["open", "-g", "swiftbar://refreshallplugins"], capture_output=True)
        elif idx == 7:
            import farbschemata
            namen = list(farbschemata.SCHEMATA)
            art2, wahl = waehle(fenster, "Einstellungen — Farbschema",
                                [("Die Profile des macOS-Terminals. Gilt für das Popup unter dem",
                                  curses.A_DIM),
                                 ("Menüleisten-Symbol und für das zeit-Terminalfenster.", curses.A_DIM),
                                 ("Standard = das dunkle zeit-Aussehen bzw. dein Terminal-Profil.",
                                  curses.A_DIM),
                                 ("Akzentfarbe „Standard“ passt sich dem Schema an.", curses.A_DIM)],
                                [(n, 0) for n in namen], "↑↓ wählen · →/⏎ übernehmen · ←/q zurück",
                                start=namen.index(e["farbschema"]) if e["farbschema"] in namen else 0)
            if art2 == "wahl":
                e["farbschema"] = namen[wahl]
                zeit.speichere_einstellungen(e)
                _farben()                       # Akzentfarbe „Standard“ passt sich an
        elif idx == 5:
            import kalender_schreiben as ks
            if e["kalender-schreiben"] == "an":
                if frage_ja_nein(fenster, ["In den Kalender schreiben ausschalten?", "",
                                           "Der Kalender „zeit“ bleibt, wie er ist —",
                                           "löschen kannst du ihn in der Kalender-App."], standard=False):
                    ks.ausschalten()
                continue
            if not frage_ja_nein(fenster, [
                    "Erfasste Zeiten in den macOS-Kalender schreiben?", "",
                    "zeit legt dafür einen eigenen Kalender „zeit“ an (in iCloud).",
                    "Deine anderen Kalender werden nie angefasst.",
                    "Korrigierst oder löschst du einen Eintrag, passt sich der Termin an."]):
                continue
            anzahl = ks.anzahl_eintraege()
            bisherige = anzahl > 0 and frage_ja_nein(fenster, [
                f"Auch die {anzahl} bisherigen Einträge eintragen?", "",
                "Nein = nur, was ab jetzt dazukommt."], standard=False)
            ks.einschalten(bisherige)
            meldung(fenster, ["Eingeschaltet.", "Der Kalender „zeit“ wird im Hintergrund",
                              "angelegt bzw. abgeglichen (beim ersten Mal fragt macOS",
                              "evtl. nach der Berechtigung)."])
        elif idx == 4:
            namen = list(zeit.AKZENTFARBEN)
            art2, wahl = waehle(fenster, "Einstellungen — Akzentfarbe",
                                [("Gilt für TUI, Menüleiste und Kalenderfenster.", curses.A_DIM)],
                                [(n, 0) for n in namen], "↑↓ wählen · →/⏎ übernehmen · ←/q zurück",
                                start=namen.index(e["akzentfarbe"]) if e["akzentfarbe"] in namen else 0)
            if art2 == "wahl":
                e["akzentfarbe"] = namen[wahl]
                zeit.speichere_einstellungen(e)
                _farben()                       # sofort sichtbar, ohne Neustart
        else:
            werte = formular_zahlen(fenster, "Einstellungen — „Noch X min“", [
                {"schluessel": "x", "name": "Verlängern um", "wert": e["pomodoro-verlaengern"],
                 "min": 1, "max": 60, "einheit": "Minuten"}],
                hinweis="So lange verlängert der Knopf „Noch X min“ Fokus oder Pause.")
            if werte:
                e["pomodoro-verlaengern"] = werte["x"]
                zeit.speichere_einstellungen(e)


def _hauptmenue(fenster):
    pos = 0
    while True:
        if TUTORIAL and TUTORIAL["ziel"]():          # Übung geschafft -> zurück ins Tutorial
            return
        projekte, _ = zeit.lade_config()
        laufend, probleme = _laufend(projekte)

        kopf = []
        z = laufend[2].sitzung if laufend else None
        if z:
            symbol, was, rest = zeit.sitzung_text(z)
            kopf.append((f"{symbol}  {zeit.SITZUNGSNAMEN[z['typ']]} — {laufend[0]} / {z['phase']}",
                         (_warn() if z["zustand"] == "angehalten" else
                          curses.color_pair(FARBE_LAEUFT)) | curses.A_BOLD))
            kopf.append((f"   {was} · {rest}", _warn() if rest.startswith("+") else 0))
        elif laufend:
            name, _, datei = laufend
            phase, start = datei.laeuft
            kopf.append((f"▶  {name} / {phase}",
                         curses.color_pair(FARBE_LAEUFT) | curses.A_BOLD))
            kopf.append((f"   seit {start:%d.%m.%Y %H:%M} — "
                         f"{zeit.dauer_text(datetime.now() - start)} Stunden", 0))
            if _verdaechtig(start):
                kopf.append(("⚠  Über acht Stunden oder über Nacht — Stoppen vergessen?",
                             _warn()))
        else:
            kopf.append(("Kein Timer läuft.", curses.A_DIM))
        for text in probleme[:2]:
            kopf.append((f"⚠  {text}", _warn()))

        # Was gerade läuft, steht oben; darunter das Starten von Neuem
        punkte = []
        if z and z["typ"] != "timer":
            punkte.append((f"{zeit.SITZUNGSNAMEN[z['typ']].split('-')[0]}-Ansicht",
                           bildschirm_sitzung))
        if laufend:
            name = zeit.SITZUNGSNAMEN[z["typ"]] if z else "Timer"
            if z and z["zustand"] == "angehalten":
                punkte.append((f"{name} fortsetzen", bildschirm_fortsetzen))
            elif laufend[2].laeuft:
                punkte.append((f"{name} anhalten", bildschirm_anhalten))
            punkte.append((f"{name} beenden", bildschirm_stoppen))
            punkte.append((f"{name} abbrechen", bildschirm_abbrechen))
        punkte.append(("Timer starten", bildschirm_starten))
        punkte.append(("Countdown starten", bildschirm_countdown_starten))
        punkte.append(("Pomodoro starten", bildschirm_pomodoro_starten))
        punkte.append(("Zeit nachtragen", bildschirm_nachtragen))
        punkte.append(("Übersicht — Projekte und Phasen", bildschirm_uebersicht))
        punkte.append(("Kalender", bildschirm_kalender))
        punkte.append(("Statistik", bildschirm_statistik))
        punkte.append(("Einstellungen", bildschirm_einstellungen))
        punkte.append(("Beenden", None))

        art, idx = waehle(fenster, "zeit — Zeiterfassung", kopf,
                          [(text, 0) for text, _ in punkte],
                          "↑↓ wählen · →/⏎ öffnen · q oder Esc beenden",
                          start=pos, links_zurueck=False)
        if art != "wahl":
            return
        pos = idx
        aktion = punkte[idx][1]
        if aktion is None:
            return
        if TUTORIAL:
            TUTORIAL["zuletzt"] = aktion.__name__
        aktion(fenster)


def starte(zeit_modul, tutorial_starten=False):
    """Einstiegspunkt, aufgerufen von zeit.py. tutorial_starten: `zeit tutorial`."""
    global zeit
    zeit = zeit_modul
    # Ohne das kennt curses die Umlaute nicht und zerlegt sie in Kästchen.
    locale.setlocale(locale.LC_ALL, "")

    def lauf(fenster):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        try:
            curses.set_escdelay(25)  # Esc soll sofort reagieren, nicht nach 1 s
        except AttributeError:
            pass
        _farben()
        fenster.keypad(True)
        # Erster Start (noch nie abgeschlossen und noch keine Projekte) -> Tutorial
        erster_start = (zeit.lade_einstellungen()["tutorial"] != "fertig"
                        and not zeit.lade_config()[0])
        if tutorial_starten or erster_start:
            import tutorial
            tutorial.starten(fenster)
        _hauptmenue(fenster)

    try:
        curses.wrapper(lauf)
    except KeyboardInterrupt:
        pass
