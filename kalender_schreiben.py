#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kalender_schreiben.py — erfasste Zeiten in den macOS-Kalender "zeit" spiegeln.

Einschalten unter Einstellungen ("In Kalender schreiben"). Dann gilt:

  - zeit legt einen eigenen Kalender "zeit" an (in iCloud, falls vorhanden) —
    deine anderen Kalender werden nie angefasst.
  - Nach jedem Schreiben in eine Zeiterfassungs-Datei stößt zeit.py im
    Hintergrund einen Abgleich an: Was in den Markdown-Dateien steht, soll als
    Termin im Kalender "zeit" stehen. Fehlendes wird angelegt, was es in den
    Dateien nicht mehr gibt (korrigiert oder gelöscht), wird entfernt.
  - Jeder Termin trägt in seinen Notizen eine Kennung ("zeit-schlüssel: …").
    Nur Termine mit dieser Kennung werden je verändert — trägst du selbst etwas
    in den Kalender "zeit" ein, bleibt es unberührt.
  - Nicht gespiegelt: aus Kalenderterminen übernommene Einträge (📅) — die
    stehen ja schon in deinem Kalender — und der gerade laufende Timer.
  - Einträge, die es beim Einschalten schon gab, kommen nur hinein, wenn du
    das beim Einschalten bestätigt hast. Sonst merkt sich zeit ihre Kennungen
    in ~/Library/Caches/zeit/kalender-ausnahmen.json und lässt sie aus.

Aufruf:  kalender_schreiben.py abgleich
"""

import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zeit  # noqa: E402

KALENDER = os.environ.get("ZEIT_TEST_KALENDER", "zeit")    # Tests: eigener Name
ORDNER = Path.home() / "Library" / "Caches" / "zeit"
AUSNAHMEN = ORDNER / "kalender-ausnahmen.json"
SPERRE = ORDNER / "kalender-abgleich.sperre"


def ist_an(einstellungen=None):
    return (einstellungen or zeit.lade_einstellungen())["kalender-schreiben"] == "an"


# ===========================================================================
# Was im Kalender stehen soll
# ===========================================================================

def soll():
    """Alle Einträge, die als Termin im Kalender stehen sollen — mit Kennung."""
    projekte, _ = zeit.lade_config()
    ergebnis = []
    for name, ordner in projekte.items():
        pfad = zeit.zeitdatei_pfad(ordner)
        if not pfad.exists() or zeit.ist_fremde_datei(pfad):
            continue
        for zellen in zeit.lese_zeitdatei(pfad, ordner.name).eintraege:
            datum, start, ende, dauer, phase, art = zellen[:6]   # Feedback zählt nicht zur Kennung
            if art == zeit.ART_KALENDER:
                continue                          # steht schon in deinem Kalender
            schluessel = "|".join([name, datum, start, ende, phase, art])
            eintrag = {"schluessel": schluessel, "titel": f"{name} · {phase} {art}".strip(),
                       "notiz": f"Erfasst mit zeit ({dauer} h).\nzeit-schlüssel: {schluessel}"}
            zeitraum = zeit._zeitraum_aus(zellen)
            if zeitraum:
                eintrag.update(start=zeitraum[0].timestamp(), ende=zeitraum[1].timestamp(), ganztag=False)
            else:                                 # Nachtrag ohne Uhrzeit -> ganztägig
                tag = zeit._datum_aus(datum)
                if not tag:
                    continue
                eintrag.update(titel=f"{eintrag['titel']} ({dauer} h)",
                               start=datetime.combine(tag, time(0)).timestamp(),
                               ende=datetime.combine(tag, time(23, 59)).timestamp(), ganztag=True)
            ergebnis.append(eintrag)
    return ergebnis


def ausnahmen_merken():
    """Beim Einschalten ohne "Bisherige übernehmen": alles, was es jetzt gibt, auslassen."""
    ORDNER.mkdir(parents=True, exist_ok=True)
    AUSNAHMEN.write_text(json.dumps([e["schluessel"] for e in soll()], ensure_ascii=False),
                         encoding="utf-8")


def ausnahmen_vergessen():
    AUSNAHMEN.unlink(missing_ok=True)


# ===========================================================================
# Schreiben (EventKit per JavaScript for Automation)
# ===========================================================================

_JXA = r"""
ObjC.import('EventKit');
ObjC.import('Foundation');
function status() { return $.EKEventStore.authorizationStatusForEntityType(0); }

function run(argv) {
    var auftrag = JSON.parse(argv[0]);
    if (status() == 0) {                                  // noch nie gefragt
        var l = $.EKEventStore.alloc.init, egal = function (a, b) {};
        if (l.respondsToSelector('requestFullAccessToEventsWithCompletion:')) l.requestFullAccessToEventsWithCompletion(egal);
        else l.requestAccessToEntityTypeCompletion(0, egal);
        var bis = Date.now() + 60000;
        while (status() == 0 && Date.now() < bis)
            $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.5));
    }
    if (status() != 3) return JSON.stringify({ fehler: 'berechtigung' });
    var laden = $.EKEventStore.alloc.init;

    // Kalender "zeit" finden oder anlegen (bevorzugt in iCloud)
    var alle = laden.calendarsForEntityType(0), kal = null;
    for (var i = 0; i < alle.count; i++) if (alle.objectAtIndex(i).title.js === auftrag.kalender) kal = alle.objectAtIndex(i);
    if (auftrag.loeschen_kalender) {
        if (kal) laden.removeCalendarCommitError(kal, true, null);
        return JSON.stringify({ geloescht: !!kal });
    }
    if (!kal) {
        var quelle = null, quellen = laden.sources;
        for (var q = 0; q < quellen.count; q++) if (quellen.objectAtIndex(q).title.js === 'iCloud') quelle = quellen.objectAtIndex(q);
        if (!quelle) quelle = laden.defaultCalendarForNewEvents.source;
        kal = $.EKCalendar.calendarForEntityTypeEventStore(0, laden);
        kal.title = auftrag.kalender;
        kal.source = quelle;
        if (!laden.saveCalendarCommitError(kal, true, null)) return JSON.stringify({ fehler: 'kalender-anlegen' });
    }

    // Was steht schon drin? (nur Termine mit Kennung zählen)
    var vorhanden = {};
    var abfrage = laden.predicateForEventsWithStartDateEndDateCalendars(
        $.NSDate.dateWithTimeIntervalSince1970(auftrag.von), $.NSDate.dateWithTimeIntervalSince1970(auftrag.bis), $([kal]));
    var termine = laden.eventsMatchingPredicate(abfrage);
    for (var j = 0; j < termine.count; j++) {
        var t = termine.objectAtIndex(j), notiz = t.notes.isNil() ? '' : t.notes.js;
        var m = notiz.match(/zeit-schlüssel: (.+)$/m);
        if (m) vorhanden[m[1]] = t;
    }
    var soll = {}, neu = 0, weg = 0;
    auftrag.soll.forEach(function (e) {
        soll[e.schluessel] = true;
        if (vorhanden[e.schluessel]) return;
        var t = $.EKEvent.eventWithEventStore(laden);
        t.calendar = kal; t.title = e.titel; t.notes = e.notiz; t.allDay = e.ganztag;
        t.startDate = $.NSDate.dateWithTimeIntervalSince1970(e.start);
        t.endDate = $.NSDate.dateWithTimeIntervalSince1970(e.ende);
        if (laden.saveEventSpanCommitError(t, 0, false, null)) neu++;
    });
    for (var s in vorhanden) {
        // Ausnahmen ("beim Einschalten nicht übernehmen"): nie anlegen, aber auch nie löschen
        if (!soll[s] && auftrag.entfernen && auftrag.behalten.indexOf(s) < 0) { if (laden.removeEventSpanCommitError(vorhanden[s], 0, false, null)) weg++; }
    }
    laden.commit(null);
    return JSON.stringify({ neu: neu, entfernt: weg, vorhanden: Object.keys(vorhanden).length });
}
"""


def _ausfuehren(auftrag):
    ergebnis = subprocess.run(["osascript", "-l", "JavaScript", "-", json.dumps(auftrag)],
                              input=_JXA, capture_output=True, text=True, timeout=120)
    if ergebnis.returncode != 0:
        raise RuntimeError(ergebnis.stderr.strip())
    return json.loads(ergebnis.stdout)


def abgleich():
    """Kalender "zeit" an die Markdown-Dateien angleichen. Rückgabe: dict mit Zahlen."""
    if not ist_an():
        return {"aus": True}
    ORDNER.mkdir(parents=True, exist_ok=True)
    with open(SPERRE, "w") as sperre:
        fcntl.flock(sperre, fcntl.LOCK_EX)        # nie zwei Abgleiche gleichzeitig
        ausnahmen = set(json.loads(AUSNAHMEN.read_text(encoding="utf-8"))) if AUSNAHMEN.exists() else set()
        liste = [e for e in soll() if e["schluessel"] not in ausnahmen]
        zeiten = [e["start"] for e in liste] + [e["ende"] for e in liste]
        jetzt = datetime.now().timestamp()
        return _ausfuehren({
            "kalender": KALENDER, "soll": liste, "entfernen": True, "behalten": sorted(ausnahmen),
            # Zeitraum, in dem gesucht wird: alles, was je erfasst wurde (+ Puffer)
            "von": min(zeiten, default=jetzt) - 86400 * 2, "bis": max(zeiten, default=jetzt) + 86400 * 2})


def anstossen():
    """Von zeit.py nach jedem Schreiben aufgerufen: Abgleich im Hintergrund,
    damit niemand warten muss. In Tests schaltet ZEIT_KEIN_KALENDER=1 das ab."""
    if os.environ.get("ZEIT_KEIN_KALENDER") or not ist_an():
        return
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "abgleich"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def einschalten(bisherige_uebernehmen):
    """Schaltet das Spiegeln ein. bisherige_uebernehmen=False: alles, was es
    schon gibt, bleibt draußen — nur Neues kommt in den Kalender."""
    if bisherige_uebernehmen:
        ausnahmen_vergessen()
    else:
        ausnahmen_merken()
    e = zeit.lade_einstellungen()
    e["kalender-schreiben"] = "an"
    zeit.speichere_einstellungen(e)
    anstossen()                                   # erster Abgleich sofort


def ausschalten():
    """Schaltet das Spiegeln aus. Der Kalender "zeit" bleibt, wie er ist —
    löschen kannst du ihn in der Kalender-App, wenn du ihn nicht mehr brauchst."""
    e = zeit.lade_einstellungen()
    e["kalender-schreiben"] = "aus"
    zeit.speichere_einstellungen(e)


def anzahl_eintraege():
    return len(soll())


def kalender_loeschen():
    """Nur für Tests: den Testkalender wieder entfernen."""
    return _ausfuehren({"kalender": KALENDER, "loeschen_kalender": True, "soll": [], "behalten": [],
                        "von": 0, "bis": 0})


if __name__ == "__main__":
    if sys.argv[1:] == ["abgleich"]:
        try:
            print(abgleich())
        except Exception as grund:
            print(f"Abgleich fehlgeschlagen: {grund}", file=sys.stderr)
            sys.exit(1)
