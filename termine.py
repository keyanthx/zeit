#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
termine.py — Termine aus der macOS-Kalender-App lesen.

Nur lesen, nie schreiben: an deinen Kalendern ändert zeit nichts. Übernimmst
du einen Termin, entsteht ein ganz normaler Eintrag in deiner Zeiterfassung
(Art 📅) — der Termin selbst bleibt, wie er ist.

Gelesen wird über EventKit, die Kalender-Schnittstelle von macOS, per
JavaScript for Automation (Bordmittel, nichts zu installieren). macOS fragt
beim ersten Zugriff einmal nach der Berechtigung — und zwar für das Programm,
aus dem zeit gerade läuft (Terminal für das TUI, SwiftBar für die Menüleiste).

Eine Besonderheit, die sich beim Ausprobieren gezeigt hat: Die Antwort auf die
Berechtigungsfrage kommt bei diesem Weg nicht zuverlässig beim Skript an.
Darum wird nach der Frage einfach regelmäßig nachgesehen, wie der Status ist.

Ganztägige Termine (Feiertage, Geburtstage …) werden weggelassen — sie haben
keine Uhrzeit, die man als Arbeitszeit übernehmen könnte.
"""

import json
import os
import subprocess
import time
from collections import namedtuple
from datetime import datetime

# kennung: eindeutig auch bei Serienterminen (die teilen sich bei macOS eine
# Kennung — deshalb hängt die Startzeit mit dran)
Termin = namedtuple("Termin", "kennung titel kalender start ende")


class KeineBerechtigung(Exception):
    """zeit darf (noch) nicht auf die Kalender zugreifen."""


_JXA = r"""
ObjC.import('EventKit');
ObjC.import('Foundation');

function status() { return $.EKEventStore.authorizationStatusForEntityType(0); }  // 0 = Termine

function run(argv) {
    var auftrag = JSON.parse(argv[0]);
    if (status() == 0 && auftrag.fragen) {            // 0 = noch nie gefragt
        var laden = $.EKEventStore.alloc.init;
        var egal = function (ok, fehler) {};
        if (laden.respondsToSelector('requestFullAccessToEventsWithCompletion:'))
            laden.requestFullAccessToEventsWithCompletion(egal);
        else
            laden.requestAccessToEntityTypeCompletion(0, egal);
        var bis = Date.now() + auftrag.warten * 1000;
        while (status() == 0 && Date.now() < bis)
            $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.5));
    }
    if (status() != 3)                                // 3 = voller Zugriff
        return JSON.stringify({ fehler: 'berechtigung', status: status() });

    var laden = $.EKEventStore.alloc.init;
    var alle = laden.calendarsForEntityType(0), namen = [], gewaehlt = [];
    for (var i = 0; i < alle.count; i++) {
        var k = alle.objectAtIndex(i);
        namen.push(k.title.js);
        if (auftrag.kalender.indexOf(k.title.js) >= 0) gewaehlt.push(k);
    }
    if (auftrag.nur_namen) return JSON.stringify({ kalender: namen });
    if (!gewaehlt.length) return JSON.stringify({ termine: [] });

    var abfrage = laden.predicateForEventsWithStartDateEndDateCalendars(
        $.NSDate.dateWithTimeIntervalSince1970(auftrag.von),
        $.NSDate.dateWithTimeIntervalSince1970(auftrag.bis), $(gewaehlt));
    var gefunden = laden.eventsMatchingPredicate(abfrage), termine = [];
    for (var j = 0; j < gefunden.count; j++) {
        var t = gefunden.objectAtIndex(j);
        if (t.allDay) continue;
        var start = t.startDate.timeIntervalSince1970, ende = t.endDate.timeIntervalSince1970;
        termine.push({
            kennung: (t.eventIdentifier.isNil() ? 'ohne' : t.eventIdentifier.js) + '@' + Math.round(start),
            titel: t.title.isNil() ? '(ohne Titel)' : t.title.js,
            kalender: t.calendar.title.js, start: start, ende: ende });
    }
    return JSON.stringify({ termine: termine });
}
"""

_ZWISCHENSPEICHER = {}
_GUELTIG = 60          # Sekunden: so lange werden gelesene Termine wiederverwendet


def _fragen(auftrag, warten=60):
    auftrag = dict(auftrag, warten=warten)
    ergebnis = subprocess.run(["osascript", "-l", "JavaScript", "-", json.dumps(auftrag)],
                              input=_JXA, capture_output=True, text=True, timeout=warten + 30)
    if ergebnis.returncode != 0:
        raise RuntimeError(ergebnis.stderr.strip() or "Kalender konnten nicht gelesen werden")
    antwort = json.loads(ergebnis.stdout)
    if antwort.get("fehler") == "berechtigung":
        raise KeineBerechtigung(
            "zeit darf nicht auf deine Kalender zugreifen. Erlauben unter "
            "Systemeinstellungen → Datenschutz & Sicherheit → Kalender.")
    return antwort


def kalender_namen(fragen=True):
    """Die Namen aller Kalender in der Kalender-App."""
    return _fragen({"nur_namen": True, "kalender": [], "fragen": fragen})["kalender"]


def lesen(von_datum, bis_datum, kalender, fragen=True):
    """Alle Termine mit Uhrzeit zwischen den Tagen von_datum und bis_datum
    (beide eingeschlossen) aus den genannten Kalendern, nach Beginn sortiert."""
    if not kalender:
        return []
    if os.environ.get("ZEIT_TEST_TERMINE"):         # nur für Tests: Termine aus einer Datei
        return _testtermine(os.environ["ZEIT_TEST_TERMINE"], von_datum, bis_datum, kalender)
    schluessel = (von_datum, bis_datum, tuple(kalender))
    gemerkt = _ZWISCHENSPEICHER.get(schluessel)
    if gemerkt and time.time() - gemerkt[0] < _GUELTIG:
        return gemerkt[1]
    von = datetime.combine(von_datum, datetime.min.time()).timestamp()
    bis = datetime.combine(bis_datum, datetime.max.time()).timestamp()
    antwort = _fragen({"von": von, "bis": bis, "kalender": list(kalender), "fragen": fragen})
    termine = sorted(
        (Termin(t["kennung"], t["titel"], t["kalender"],
                datetime.fromtimestamp(t["start"]).replace(microsecond=0),
                datetime.fromtimestamp(t["ende"]).replace(microsecond=0))
         for t in antwort["termine"]),
        key=lambda t: t.start)
    _ZWISCHENSPEICHER[schluessel] = (time.time(), termine)
    return termine


def _testtermine(pfad, von_datum, bis_datum, kalender):
    """Liest Termine aus einer JSON-Datei statt aus der Kalender-App — damit Tests
    nicht von deinen echten Kalendern abhängen. Format: Liste von
    {"titel", "kalender", "start": "2026-09-21 10:00", "ende": "…"}."""
    ergebnis = []
    for i, t in enumerate(json.loads(open(pfad, encoding="utf-8").read())):
        start = datetime.strptime(t["start"], "%Y-%m-%d %H:%M")
        ende = datetime.strptime(t["ende"], "%Y-%m-%d %H:%M")
        if t["kalender"] in kalender and von_datum <= start.date() <= bis_datum:
            ergebnis.append(Termin(f"test{i}@{int(start.timestamp())}", t["titel"], t["kalender"],
                                   start, ende))
    return sorted(ergebnis, key=lambda t: t.start)
