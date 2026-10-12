#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui_api.py — was die grafische Oberfläche (GUI) wissen will und tun darf.

Die GUI ist eine Webseite (web/gui.html, gui.css, gui.js). Sie rechnet und
speichert nichts selbst, sondern fragt den kleinen Dienst in webterm.py, und
der ruft die Funktionen hier auf. Die wiederum benutzen dieselben Funktionen aus
zeit.py wie Terminal, TUI und Menüleiste. So gibt es keine zweite Logik und
keinen zweiten Datenstand: alles steht weiter nur in den Markdown-Dateien.

Zwei Aufrufe:
    zustand()          Was gerade läuft, Projekte, Phasen, Einstellungen …
                       Die GUI fragt das alle zwei Sekunden ab.
    ausfuehren(auftrag)
                       Eine Aktion, z. B. {"aktion": "start", "projekt": "a",
                       "phase": "design"}. Rückgabe ist ein dict, das als JSON
                       zur GUI zurückgeht.

Rückfragen („Gerade läuft X — umschalten?“) stellt nicht Python, sondern die
GUI: Braucht eine Aktion eine Bestätigung, antwortet sie mit
{"frage": "…", "knopf": "Umschalten"}. Die GUI zeigt das an und schickt den
Auftrag bei „Ja“ noch einmal, dann mit "ok": true.
"""

import contextlib
import io
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import farbschemata
import kalender as k
import zeit


class Frage(Exception):
    """Die Aktion braucht eine Bestätigung (text, Beschriftung des Ja-Knopfs)."""

    def __init__(self, text, knopf):
        super().__init__(text)
        self.text, self.knopf = text, knopf


def _iso(zeitpunkt):
    return zeitpunkt.isoformat(timespec="seconds") if zeitpunkt else None


def _still(_):
    """Hinweise über fremde Dateien: in der GUI unwichtig (im Terminal siehst du sie)."""


# ===========================================================================
# Zustand
# ===========================================================================

def _laufend(aktiv):
    """Was gerade läuft, so aufbereitet, dass die GUI nur noch anzeigen muss."""
    if not aktiv:
        return None
    name, _, datei = aktiv
    z = datei.sitzung
    lauf = {"projekt": name,
            "phase": z["phase"] if z else datei.laeuft[0],
            "typ": z["typ"] if z else "timer",
            "zustand": z["zustand"] if z else "laeuft",
            # seit wann gerade Zeit erfasst wird (None = gerade nicht, z. B. Pause)
            "erfasst_seit": _iso(datei.laeuft[1]) if datei.laeuft else None}
    if not z:
        start = datei.laeuft[1]
        jetzt = datetime.now()
        lauf["vergessen"] = (start.date() != jetzt.date()
                             or jetzt - start >= timedelta(hours=zeit.WARNUNG_AB_STUNDEN))
        return lauf
    symbol, was, rest = zeit.sitzung_text(z)
    lauf.update(symbol=symbol, was=was, rest_text=rest, seit=_iso(z["seit"]),
                beginn=_iso(z.get("beginn")))
    if z["zustand"] == "angehalten":
        lauf["rest"] = z.get("rest", 0)                # Sekunden, die noch übrig waren
    else:
        lauf["ende"] = _iso(zeit.sitzung_ende(z))
        lauf["ueberfaellig"] = zeit.sitzung_ende(z) <= datetime.now()
    if z["typ"] == "pomodoro":
        lauf.update(nr=z["nr"], nach=z["nach"], position=zeit.satz_position(z),
                    lange_pause=zeit.ist_lange_pause(z))
    return lauf


def _zuletzt(eintraege):
    """Projekt und Phase des jüngsten Eintrags — als Vorschlag zum Starten."""
    mit_zeit = [e for e in eintraege if e.start and e.start != zeit.NUR_TAG]
    if not mit_zeit:
        return None
    e = max(mit_zeit, key=lambda e: (e.datum, e.start))
    return {"projekt": e.projekt, "phase": e.phase}


def _vorgaben_nachtrag(jetzt=None):
    """Bis = jetzt, abgerundet auf 15 Minuten; Von = eine Stunde davor
    (wie im Formular der Menüleiste)."""
    jetzt = jetzt or datetime.now()
    bis = jetzt.replace(minute=jetzt.minute - jetzt.minute % 15, second=0, microsecond=0)
    von = bis - timedelta(hours=1)
    return {"datum": f"{von:%Y-%m-%d}", "von": f"{von:%H:%M}", "bis": f"{bis:%H:%M}"}


def zustand():
    projekte, phasen = zeit.lade_config()
    zeit.wecker_sicherstellen(projekte)     # wie Menüleiste und TUI: Wecker notfalls nachstarten
    e = zeit.lade_einstellungen()
    eintraege = zeit.alle_eintraege(projekte, warner=_still)
    heute = date.today()
    return {
        "jetzt": _iso(datetime.now()),
        "laufend": _laufend(zeit.finde_aktiv(projekte, warner=_still)),
        "projekte": list(projekte),
        "phasen": phasen,
        "heute_minuten": sum(x.minuten for x in eintraege if x.datum == heute),
        "zuletzt": _zuletzt(eintraege),
        "akzent": zeit.akzentfarbe(e)[1],
        "einstellungen": e,
        "vorgaben": {"nachtrag": _vorgaben_nachtrag(),
                     "pomodoro": {"fokus": e["pomodoro-fokus"], "kurz": e["pomodoro-kurze-pause"],
                                  "lang": e["pomodoro-lange-pause"], "nach": e["pomodoro-lange-pause-nach"]},
                     "countdown": {"art": e["countdown-art"], "dauer": e["countdown-dauer"]}},
        # Auswahllisten für die Einstellungen
        "optionen": {"toene": zeit.TOENE + [zeit.KEIN_TON],
                     "akzentfarben": list(zeit.AKZENTFARBEN),
                     "farbschemata": list(farbschemata.SCHEMATA),
                     "klick": zeit.KLICK_ARTEN, "anzeige": zeit.ANZEIGEN,
                     "groessen": {k_: v[0] for k_, v in zeit.POPUP_GROESSEN.items()},
                     "pomodoro_grenzen": zeit.POMODORO_GRENZEN},
    }


# ===========================================================================
# Hilfen
# ===========================================================================

def _projekt(projekte, name):
    """Der Ordner eines Projekts — mit verständlichem Fehler, wenn es nicht passt."""
    if name not in projekte:
        raise ValueError(f"Das Projekt '{name}' gibt es nicht (mehr).")
    ordner = projekte[name]
    if zeit.ist_fremde_datei(zeit.zeitdatei_pfad(ordner)):
        raise ValueError("In diesem Projektordner liegt eine Zeiterfassung.md, die nicht "
                         "von zeit stammt. Sie wird nicht angefasst.")
    return ordner


def _aktiv():
    projekte, _ = zeit.lade_config()
    aktiv = zeit.finde_aktiv(projekte, warner=_still)
    if not aktiv:
        raise ValueError("Gerade läuft nichts.")
    return aktiv


def _vorher_beenden(auftrag, was_neu):
    """Läuft schon etwas? Ohne "ok" erst nachfragen, mit "ok" beenden."""
    projekte, _ = zeit.lade_config()
    aktiv = zeit.finde_aktiv(projekte, warner=_still)
    if not aktiv:
        return
    name, ordner, datei = aktiv
    if not auftrag.get("ok"):
        raise Frage(f"Gerade läuft: {zeit._sitzung_beschreiben(name, datei)}\n\n"
                    f"Beenden und {was_neu} starten?", "Umschalten")
    zeit.sitzung_beenden(ordner, datei)


def _dauer_minuten(text):
    """'1:30', '1,5h', '90min', '2' (nackte Zahl = Stunden) -> Minuten, sonst ValueError."""
    t = text.strip().lower().replace(",", ".")
    minuten = zeit._dauer_parsen(t)
    if minuten is None:
        try:
            minuten = int(round(float(t) * 60))
        except ValueError:
            raise ValueError(f"'{text}' ist keine Dauer (z. B. 1:30, 1,5h oder 90min).")
    if not 1 <= minuten < 24 * 60:
        raise ValueError("Die Dauer muss zwischen 1 Minute und 24 Stunden liegen.")
    return minuten


def _bericht(b):
    """Bericht für die GUI: Zeilen zum Anzeigen + wo das Feedback hingehört."""
    if not b:
        return None
    return {"zeilen": zeit.bericht_zeilen(b), "projekt": b["projekt"],
            "datum": b["ziel"][0], "start": b["ziel"][1]}


# ===========================================================================
# Aktionen: Timer und Sitzungen
# ===========================================================================

def a_start(auftrag):
    projekte, _ = zeit.lade_config()
    ordner = _projekt(projekte, auftrag["projekt"])
    _vorher_beenden(auftrag, "den Timer")
    pfad = zeit.zeitdatei_pfad(ordner)
    datei = zeit.lese_zeitdatei(pfad, ordner.name)
    datei.laeuft = (auftrag["phase"], zeit._jetzt())
    zeit.schreibe_zeitdatei(pfad, datei)
    return {"meldung": f"▶ {auftrag['projekt']} / {auftrag['phase']} gestartet"}


def a_stop(auftrag):
    name, ordner, datei = _aktiv()
    b = zeit.beenden_mit_bericht(name, ordner, datei)
    if not b:
        return {"meldung": f"Beendet — nichts eingetragen ({zeit._warum_kein_eintrag(datei)})."}
    return {"bericht": _bericht(b)}


def a_abbrechen(auftrag):
    name, ordner, datei = _aktiv()
    if not auftrag.get("ok"):
        raise Frage("Wirklich verwerfen? Der laufende Abschnitt wird NICHT eingetragen."
                    if datei.laeuft else "Beenden? Gerade läuft keine Zeit — es gibt nichts einzutragen.",
                    "Verwerfen" if datei.laeuft else "Beenden")
    datei.laeuft = None
    datei.sitzung = None
    zeit.schreibe_zeitdatei(zeit.zeitdatei_pfad(ordner), datei)
    return {"meldung": "Verworfen, nichts eingetragen."}


def a_anhalten(auftrag):
    name, ordner, datei = _aktiv()
    if not datei.laeuft:
        raise ValueError("Gerade läuft keine Zeit, die man anhalten könnte.")
    zeit.anhalten(ordner, datei)
    return {"meldung": "⏸ Angehalten"}


def a_fortsetzen(auftrag):
    name, ordner, datei = _aktiv()
    if not datei.sitzung or datei.sitzung["zustand"] != "angehalten":
        raise ValueError("Es ist nichts angehalten.")
    zeit.fortsetzen(ordner, datei)
    return {"meldung": "▶ Fortgesetzt"}


def a_pause(auftrag):
    """Pomodoro: Fokus beenden, Pause beginnen — mit Kurzbericht fürs Feedback."""
    name, ordner, datei = _aktiv()
    if not datei.sitzung or datei.sitzung["typ"] != "pomodoro" or datei.sitzung["zustand"] != "fokus":
        raise ValueError("Gerade läuft kein Pomodoro-Fokus.")
    ergebnis = zeit.pomodoro_pause(ordner, datei)
    if not ergebnis:
        return {"meldung": "☕ Pause"}
    return {"bericht": {"zeilen": zeit.fokusblock_bericht(name, ergebnis), "projekt": name,
                        "datum": f"{ergebnis[2]:%Y-%m-%d}", "start": f"{ergebnis[2]:%H:%M}"}}


def a_weiter(auftrag):
    name, ordner, datei = _aktiv()
    if not datei.sitzung or datei.sitzung["typ"] != "pomodoro" or datei.sitzung["zustand"] != "pause":
        raise ValueError("Gerade ist keine Pomodoro-Pause.")
    zeit.pomodoro_weiter(ordner, datei)
    return {"meldung": "🍅 Weiter mit Fokus"}


def a_mehr(auftrag):
    name, ordner, datei = _aktiv()
    if not datei.sitzung or datei.sitzung["zustand"] == "angehalten" or datei.sitzung["typ"] == "timer":
        raise ValueError("Verlängern geht nur bei laufendem Pomodoro oder Countdown.")
    x = zeit.lade_einstellungen()["pomodoro-verlaengern"]
    zeit.verlaengern(ordner, datei, x)
    return {"meldung": f"+{x} min"}


def a_countdown(auftrag):
    projekte, _ = zeit.lade_config()
    ordner = _projekt(projekte, auftrag["projekt"])
    art = "bis" if auftrag.get("art") == "bis" else "dauer"
    minuten = zeit.countdown_minuten(art, str(auftrag.get("wert", "")))
    _vorher_beenden(auftrag, "den Countdown")
    z = zeit.countdown_starten(ordner, auftrag["phase"], minuten, art)
    return {"meldung": f"⏳ Countdown bis {zeit.sitzung_ende(z):%H:%M}"}


def a_pomodoro(auftrag):
    projekte, _ = zeit.lade_config()
    ordner = _projekt(projekte, auftrag["projekt"])
    try:
        werte = {k_: int(str(auftrag[k_]).strip()) for k_ in ("fokus", "kurz", "lang", "nach")}
    except (KeyError, ValueError):
        raise ValueError("Bitte bei allen vier Werten ganze Zahlen eintragen.")
    zeit.pomodoro_werte_pruefen(werte)
    _vorher_beenden(auftrag, "den Pomodoro")
    zeit.pomodoro_starten(ordner, auftrag["phase"], werte)
    return {"meldung": f"🍅 Pomodoro gestartet, {werte['fokus']} min Fokus"}


# ===========================================================================
# Aktionen: Nachtragen, Termine
# ===========================================================================

def _nachtrag_aus(auftrag):
    """Die Felder der GUI -> ein geprüfter Nachtrag (dieselben Regeln wie überall)."""
    if auftrag.get("nur_tag"):
        text = f"{auftrag['datum']} {_dauer_minuten(str(auftrag.get('dauer', '')))}min"
    else:
        text = f"{auftrag['datum']} {auftrag['von']}-{auftrag['bis']}"
    return zeit.nachtrag_parsen(text)


def a_nachtragen(auftrag):
    projekte, _ = zeit.lade_config()
    ordner = _projekt(projekte, auftrag["projekt"])
    n = _nachtrag_aus(auftrag)
    konflikte = zeit.konflikte_fuer(projekte, n)
    if konflikte and not auftrag.get("ok"):
        raise Frage(f"{zeit.beschreibe_nachtrag(n)}\n\n⚠ Überschneidet sich mit:\n"
                    + "\n".join(konflikte[:5]), "Trotzdem eintragen")
    zeit.nachtragen(ordner, auftrag["phase"], n)
    return {"meldung": f"✓ Nachgetragen: {zeit.beschreibe_nachtrag(n)}"}


def a_termine(auftrag):
    """Kalendertermine eines Tages, mit Vorschlag (Regeln) und ob schon übernommen."""
    tag = date.fromisoformat(auftrag.get("datum") or date.today().isoformat())
    projekte, _ = zeit.lade_config()
    liste, hinweis = k.termine_im_zeitraum(projekte, tag, tag)
    jetzt = datetime.now()
    return {"datum": tag.isoformat(), "hinweis": hinweis,
            "quellen": [q for q in zeit.kalender_quellen() if q != "zeit"],
            "termine": [{"kennung": a.termin.kennung, "titel": a.termin.titel,
                         "kalender": a.termin.kalender,
                         "von": f"{a.termin.start:%H:%M}", "bis": f"{a.termin.ende:%H:%M}",
                         "uebernommen": a.uebernommen, "vorbei": a.termin.ende <= jetzt,
                         "projekt": a.projekt if a.projekt != zeit.FRAGEN else None,
                         "phase": a.phase if a.phase != zeit.FRAGEN else None,
                         "konflikte": a.konflikte} for a in liste]}


def a_termin_uebernehmen(auftrag):
    import termine
    projekte, _ = zeit.lade_config()
    start = datetime.fromtimestamp(int(auftrag["kennung"].rsplit("@", 1)[1]))
    treffer = [t for t in termine.lesen(start.date(), start.date(), zeit.kalender_quellen())
               if t.kennung == auftrag["kennung"]]
    if not treffer:
        raise ValueError("Den Termin gibt es nicht mehr (verschoben oder gelöscht?).")
    k.termin_uebernehmen(projekte, treffer[0], auftrag["projekt"], auftrag["phase"])
    termine._ZWISCHENSPEICHER.clear()
    return {"meldung": f"✓ Übernommen: {treffer[0].titel}"}


# ===========================================================================
# Aktionen: Projekte und Phasen anlegen
# ===========================================================================

def a_ordner_vorschlag(auftrag):
    """Vorschlag für den Ordner eines neuen Projekts: ein passender, vorhandener
    Ordner im Projektordner (Einstellung) — sonst ein neuer mit diesem Namen."""
    name = auftrag.get("name", "").strip()
    vorhanden = zeit._ordner_vorschlag(zeit.slug(name)) if name else None
    return {"ordner": str(vorhanden or zeit.projekt_suchordner() / name) if name else "",
            "vorhanden": bool(vorhanden)}


def a_ordner_waehlen(auftrag):
    """Öffnet den macOS-Ordnerdialog. Rückgabe: der Pfad, oder None (abgebrochen)."""
    start = auftrag.get("start") or str(zeit.projekt_suchordner())
    skript = ('on run argv\n  activate\n  set f to choose folder with prompt "Ordner für die '
              'Zeiterfassung wählen" default location (POSIX file (item 1 of argv))\n'
              '  return POSIX path of f\nend run')
    if not Path(start).is_dir():
        start = str(Path.home())
    ergebnis = subprocess.run(["osascript", "-", start], input=skript, capture_output=True, text=True)
    pfad = ergebnis.stdout.strip()
    return {"ordner": pfad.rstrip("/") if ergebnis.returncode == 0 and pfad else None}


def a_projekt_anlegen(auftrag):
    projekte, phasen = zeit.lade_config()
    kurz = zeit.slug(auftrag.get("name", ""))
    if not kurz:
        raise ValueError("Bitte einen Namen eingeben.")
    if kurz in projekte:
        raise ValueError(f"'{kurz}' gibt es schon.")
    text = str(auftrag.get("ordner", "")).strip()
    if not text:
        raise ValueError("Ohne Ordner kann das Projekt nicht angelegt werden.")
    ordner = Path(text).expanduser().resolve()
    if not ordner.exists():
        ordner.mkdir(parents=True)                  # der Vorschlag wird angelegt
    projekte[kurz] = ordner
    zeit.speichere_config(projekte, phasen)
    return {"projekt": kurz, "meldung": f"✓ Projekt '{kurz}' angelegt"}


def a_phase_anlegen(auftrag):
    projekte, phasen = zeit.lade_config()
    kurz = zeit.slug(auftrag.get("name", ""))
    if not kurz:
        raise ValueError("Bitte einen Namen eingeben.")
    if kurz in phasen:
        raise ValueError(f"'{kurz}' steht schon in der Liste.")
    phasen.append(kurz)
    zeit.speichere_config(projekte, phasen)
    return {"phase": kurz, "meldung": f"✓ Phase '{kurz}' angelegt"}


# ===========================================================================
# Aktionen: Übersicht und Einträge
# ===========================================================================

def a_uebersicht(auftrag):
    """Je Projekt: Summe, Summen je Phase, Anzahl Einträge, letzter Tag."""
    projekte, phasen = zeit.lade_config()
    alle = zeit.alle_eintraege(projekte, warner=_still)
    liste = []
    for name, ordner in projekte.items():
        eigene = [e for e in alle if e.projekt == name]
        je_phase = {}
        for e in eigene:
            je_phase[e.phase] = je_phase.get(e.phase, 0) + e.minuten
        liste.append({"projekt": name, "ordner": str(ordner),
                      "minuten": sum(e.minuten for e in eigene), "anzahl": len(eigene),
                      "letzter": max((e.datum for e in eigene), default=None) and
                                 max(e.datum for e in eigene).isoformat(),
                      "phasen": sorted(je_phase.items(), key=lambda x: -x[1])})
    return {"projekte": liste}


def a_eintraege(auftrag):
    """Alle Zeilen eines Projekts, neueste zuerst. i = Position in der Datei."""
    projekte, _ = zeit.lade_config()
    ordner = _projekt(projekte, auftrag["projekt"])
    pfad = zeit.zeitdatei_pfad(ordner)
    if not pfad.exists():
        return {"eintraege": []}
    zeilen = zeit.lese_zeitdatei(pfad, ordner.name).eintraege
    return {"eintraege": [{"i": i, "zellen": z} for i, z in reversed(list(enumerate(zeilen)))]}


def _zeile_finden(auftrag):
    """Die Zeile, die die GUI meint — nur wenn sie sich seitdem nicht verändert hat."""
    projekte, _ = zeit.lade_config()
    ordner = _projekt(projekte, auftrag["projekt"])
    pfad = zeit.zeitdatei_pfad(ordner)
    datei = zeit.lese_zeitdatei(pfad, ordner.name)
    i = int(auftrag["i"])
    if not 0 <= i < len(datei.eintraege) or datei.eintraege[i] != auftrag["zellen"]:
        raise ValueError("Die Zeile hat sich inzwischen geändert — bitte neu laden.")
    return projekte, pfad, datei, i


def a_eintrag_loeschen(auftrag):
    _, pfad, datei, i = _zeile_finden(auftrag)
    if not auftrag.get("ok"):
        z = datei.eintraege[i]
        raise Frage(f"Diesen Eintrag löschen?\n\n{z[0]}  {z[1]}–{z[2]}  ({z[3]} h, {z[4]})", "Löschen")
    del datei.eintraege[i]
    zeit.schreibe_zeitdatei(pfad, datei)
    return {"meldung": "Eintrag gelöscht"}


def a_eintrag_aendern(auftrag):
    """Datum, Zeiten (oder nur Dauer), Phase und Feedback (Fokus, Notiz) ändern.
    Die Art (🍅, ✎ …) bleibt, wie sie ist."""
    projekte, pfad, datei, i = _zeile_finden(auftrag)
    alt = datei.eintraege[i]
    n = _nachtrag_aus(auftrag)
    if n.start is None:
        neu = [f"{n.datum:%Y-%m-%d}", zeit.NUR_TAG, zeit.NUR_TAG,
               zeit.dauer_text(timedelta(minutes=n.minuten)), auftrag["phase"]]
    else:
        neu = zeit._eintragszeile(n.start, n.ende, auftrag["phase"])[:5]
        # Überschneidungen — außer mit der Zeile selbst
        selbst = f"{auftrag['projekt']} / {alt[4]}: {alt[0]} {alt[1]}–{alt[2]}"
        konflikte = [x for x in zeit.ueberschneidungen(projekte, n.start, n.ende) if x != selbst]
        if konflikte and not auftrag.get("ok"):
            raise Frage("⚠ Überschneidet sich mit:\n" + "\n".join(konflikte[:5]), "Trotzdem speichern")
    fokus = auftrag.get("fokus", alt[6])
    if fokus and fokus not in zeit.FOKUS_WERTE:
        raise ValueError("Unbekannter Fokus-Wert.")
    zeile = neu + [alt[5], fokus, zeit.notiz_saeubern(auftrag.get("notiz", alt[7]))]
    del datei.eintraege[i]
    # chronologisch wieder einsortieren (wie beim Nachtragen)
    pos = len(datei.eintraege)
    while pos > 0 and (datei.eintraege[pos - 1][0], datei.eintraege[pos - 1][1]) > (zeile[0], zeile[1]):
        pos -= 1
    datei.eintraege.insert(pos, zeile)
    zeit.schreibe_zeitdatei(pfad, datei)
    return {"meldung": "✓ Eintrag geändert"}


def a_feedback(auftrag):
    projekte, _ = zeit.lade_config()
    ordner = _projekt(projekte, auftrag["projekt"])
    if not zeit.feedback_setzen(ordner, auftrag["datum"], auftrag["start"],
                                auftrag.get("fokus", ""), auftrag.get("notiz", "")):
        raise ValueError("Die Zeile für das Feedback wurde nicht gefunden.")
    return {"meldung": "✓ Feedback gespeichert"}


# ===========================================================================
# Aktionen: Einstellungen
# ===========================================================================

def a_kalender_namen(auftrag):
    """Die Kalender aus der Kalender-App (für die Auswahl in den Einstellungen)."""
    import termine
    try:
        return {"kalender": termine.kalender_namen(), "problem": None}
    except termine.KeineBerechtigung:
        return {"kalender": [], "problem": "zeit darf deine Kalender nicht lesen. Erlauben unter "
                "Systemeinstellungen → Datenschutz & Sicherheit → Kalender."}
    except Exception as grund:
        return {"kalender": [], "problem": f"Kalender konnten nicht gelesen werden: {grund}"}


def a_ton_probe(auftrag):
    ton = auftrag.get("ton", "")
    if ton in zeit.TOENE:
        subprocess.Popen(["afplay", f"/System/Library/Sounds/{ton}.aiff"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {}


# Welche Einstellung welche Werte haben darf (alles andere wird abgelehnt)
_ERLAUBT = {
    "pomodoro-ton": lambda: zeit.TOENE + [zeit.KEIN_TON],
    "akzentfarbe": lambda: list(zeit.AKZENTFARBEN),
    "farbschema": lambda: list(farbschemata.SCHEMATA),
    "menueleiste-klick": lambda: list(zeit.KLICK_ARTEN),
    "anzeige": lambda: list(zeit.ANZEIGEN),
    "popup-groesse": lambda: list(zeit.POPUP_GROESSEN),
}


def a_einstellung(auftrag):
    """Eine Einstellung ändern: {"schluessel": …, "wert": …}."""
    import kalender_schreiben as ks
    e = zeit.lade_einstellungen()
    schluessel, wert = auftrag["schluessel"], auftrag.get("wert")
    if schluessel in _ERLAUBT:
        if wert not in _ERLAUBT[schluessel]():
            raise ValueError(f"'{wert}' ist hier nicht möglich.")
        e[schluessel] = wert
    elif schluessel == "pomodoro-verlaengern":
        try:
            wert = int(wert)
        except (TypeError, ValueError):
            wert = 0
        if not 1 <= wert <= 60:
            raise ValueError("„Noch X min“: bitte eine Zahl von 1 bis 60.")
        e[schluessel] = wert
    elif schluessel == "projektordner":
        ordner = Path(str(wert or "").strip()).expanduser()
        if not ordner.is_dir():
            raise ValueError(f"Den Ordner {ordner} gibt es nicht.")
        # mit ~ speichern, wenn er im Benutzerordner liegt — liest sich besser
        e[schluessel] = ("~/" + str(ordner.relative_to(Path.home()))
                         if Path.home() in ordner.parents else str(ordner))
    elif schluessel == "kalender-quellen":
        e[schluessel] = "; ".join(str(x).replace(";", ",") for x in wert)
    elif schluessel == "kalender-schreiben":
        # Einschalten: beim ersten Mal fragen, ob auch die bisherigen hinein sollen
        if wert == "an" and not ks.ist_an():
            anzahl = ks.anzahl_eintraege()
            if anzahl and "bisherige" not in auftrag:
                raise Frage(f"Erfasste Zeiten kommen ab jetzt in den Kalender „zeit“.\n\n"
                            f"Sollen auch die {anzahl} bisherigen Einträge hinein?", "Auch bisherige")
            ks.einschalten(bool(auftrag.get("bisherige")))
        elif wert == "aus" and ks.ist_an():
            ks.ausschalten()
        return {"meldung": "In den Kalender schreiben: " + ("an" if wert == "an" else "aus")}
    else:
        raise ValueError(f"Die Einstellung '{schluessel}' kenne ich nicht.")
    zeit.speichere_einstellungen(e)
    if schluessel in ("anzeige", "menueleiste-klick", "popup-groesse"):
        # Die Menüleiste soll das sofort übernehmen, nicht erst in 15 Sekunden
        subprocess.run(["open", "-g", "swiftbar://refreshallplugins"], capture_output=True)
    return {}


def a_regeln(auftrag):
    return {"regeln": [{"wenn": zeit.regel_text(r), "art": r.art, "wert": r.wert,
                        "projekt": r.projekt, "phase": r.phase} for r in zeit.lade_regeln()]}


def a_regel_hinzufuegen(auftrag):
    art = "kalender" if auftrag.get("art") == "kalender" else "titel"
    wert = " ".join(str(auftrag.get("wert", "")).replace("|", "/").split())
    if not wert:
        raise ValueError("Bitte angeben, worauf die Regel passen soll.")
    regeln = zeit.lade_regeln()
    regeln.append(zeit.Regel(art, wert, auftrag.get("projekt") or zeit.FRAGEN,
                             auftrag.get("phase") or zeit.FRAGEN))
    zeit.speichere_regeln(regeln)
    return a_regeln(auftrag)


def a_regel_loeschen(auftrag):
    regeln = zeit.lade_regeln()
    i = int(auftrag["i"])
    if 0 <= i < len(regeln):
        del regeln[i]
        zeit.speichere_regeln(regeln)
    return a_regeln(auftrag)


# ===========================================================================
# Kalender und Statistik (die Seite aus kalender_fenster.py, eingebettet)
# ===========================================================================

def a_kalender_seite(auftrag):
    """Die ganze Kalender-/Statistik-Seite mit Daten — die GUI zeigt sie eingebettet."""
    import kalender_fenster
    return {"html": kalender_fenster.eingebettet(auftrag.get("ansicht", "tag"))}


def a_kalender_daten(auftrag):
    import kalender_fenster
    return {"daten": kalender_fenster.daten()}


# ===========================================================================
# Verteiler
# ===========================================================================

AKTIONEN = {name[2:]: funktion for name, funktion in globals().items() if name.startswith("a_")}


def ausfuehren(auftrag):
    """Führt eine Aktion aus. Fehler kommen als {"fehler": "…"} zurück,
    Rückfragen als {"frage": "…", "knopf": "…"}."""
    funktion = AKTIONEN.get(auftrag.get("aktion"))
    if funktion is None:
        return {"fehler": f"Unbekannte Aktion: {auftrag.get('aktion')}"}
    # Was zeit.py sonst ins Terminal schreibt, wird aufgefangen: bei einem
    # Fehler (zeit.fehler() beendet das Programm mit SystemExit) ist das die Erklärung
    ausgabe = io.StringIO()
    try:
        with contextlib.redirect_stdout(ausgabe), contextlib.redirect_stderr(ausgabe):
            return funktion(auftrag) or {}
    except Frage as f:
        return {"frage": f.text, "knopf": f.knopf}
    except ValueError as grund:
        return {"fehler": str(grund)}
    except KeyError as grund:
        return {"fehler": f"Angabe fehlt: {grund}"}
    except SystemExit:
        text = ausgabe.getvalue().strip().splitlines()
        return {"fehler": (text[-1] if text else "Das ging nicht.").replace("Fehler: ", "")}
