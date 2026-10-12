#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kalender.py — die Rechnungen hinter Kalender und Statistik.

Hier wird nur gerechnet, nichts gezeichnet. Das TUI (tui.py) und das Fenster
der Menüleiste (kalender_fenster.py) bauen beide auf diesen Funktionen auf —
so können sie nie unterschiedliche Zahlen zeigen.

Grundbaustein ist der "Block": ein Stück erfasster Zeit an genau einem Tag.
Ein Eintrag über Mitternacht (Ende "00:45 (+1)") wird dafür in zwei Blöcke
geteilt, einen pro Tag. Nachträge ohne Uhrzeit ("nur Tag") sind Blöcke ohne
start/ende — sie zählen in allen Summen mit, stehen im Kalender aber nicht im
Zeitraster, sondern in einer eigenen Zeile "ohne Uhrzeit".
"""

from collections import namedtuple
from datetime import date, datetime, time, timedelta

import zeit

Block = namedtuple("Block", "projekt phase art datum start ende minuten laufend fokus notiz",
                   defaults=("", ""))

WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WOCHENTAGE_LANG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
                   "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


# ===========================================================================
# Blöcke
# ===========================================================================

def _teilen(projekt, phase, art, start, ende, laufend=False):
    """Zerlegt einen Zeitraum in Blöcke, einen pro Kalendertag."""
    teile = []
    while start < ende:
        mitternacht = datetime.combine(start.date() + timedelta(days=1), time(0))
        stueck_ende = min(ende, mitternacht)
        minuten = int(round((stueck_ende - start).total_seconds() / 60))
        teile.append(Block(projekt, phase, art, start.date(), start, stueck_ende,
                           minuten, laufend))
        start = stueck_ende
    return teile


def bloecke(projekte, von, bis, jetzt=None):
    """Alle Blöcke zwischen den Tagen `von` und `bis` (beide eingeschlossen),
    aus allen Projekten, inklusive eines gerade laufenden Timers (bis jetzt)."""
    jetzt = jetzt or datetime.now().replace(microsecond=0)
    ergebnis = []
    for name, ordner in projekte.items():
        pfad = zeit.zeitdatei_pfad(ordner)
        if not pfad.exists() or zeit.ist_fremde_datei(pfad):
            continue
        datei = zeit.lese_zeitdatei(pfad, ordner.name)
        for zellen in datei.eintraege:
            phase, art, fokus, notiz = zellen[4], zellen[5], zellen[6], zellen[7]
            zeitraum = zeit._zeitraum_aus(zellen)
            if zeitraum:
                ergebnis += [b._replace(fokus=fokus, notiz=notiz)
                             for b in _teilen(name, phase, art, *zeitraum)]
                continue
            tag, minuten = zeit._datum_aus(zellen[0]), zeit._minuten_aus(zellen[3])
            if tag and minuten is not None:                     # "nur Tag"
                ergebnis.append(Block(name, phase, art, tag, None, None, minuten, False,
                                      fokus, notiz))
        if datei.laeuft:
            phase, start = datei.laeuft
            ergebnis += _teilen(name, phase, zeit._grundart(datei.sitzung),
                                start, max(jetzt, start), laufend=True)
    return sorted((b for b in ergebnis if von <= b.datum <= bis),
                  key=lambda b: (b.datum, b.start or datetime.max, b.projekt))


def zeitfenster(bloecke_liste, vorgabe=(9 * 60, 17 * 60)):
    """Der Bereich des Tages, in dem überhaupt etwas erfasst wurde — in Minuten
    seit Mitternacht, auf volle Stunden erweitert. So zeigt der Kalender nur
    die Stunden, die dich interessieren (z. B. 9–16 statt 0–24)."""
    mit_zeit = [b for b in bloecke_liste if b.start]
    if not mit_zeit:
        return vorgabe
    anfang = min(b.start.hour * 60 + b.start.minute for b in mit_zeit)
    ende = max((b.ende - datetime.combine(b.datum, time(0))).total_seconds() / 60
               for b in mit_zeit)
    anfang = anfang // 60 * 60
    ende = min(24 * 60, -(-int(ende) // 60) * 60)          # aufrunden
    return anfang, max(ende, anfang + 60)


def feinheit(fenster_minuten, zeilen_verfuegbar):
    """Die feinste Rasterung (15, 30 oder 60 Minuten je Zeile), bei der der
    Bereich auf den Bildschirm passt. Passt nicht einmal 60, wird geblättert."""
    for schritt in (15, 30, 60):
        if fenster_minuten / schritt <= zeilen_verfuegbar:
            return schritt
    return 60


def belegung(bloecke_liste, datum, von_min, bis_min):
    """Für einen Tag: wie viele Minuten jedes Projekts in [von_min, bis_min) liegen.
    Rückgabe: Liste von (block, minuten) mit Überlappung > 0."""
    beginn = datetime.combine(datum, time(0)) + timedelta(minutes=von_min)
    schluss = datetime.combine(datum, time(0)) + timedelta(minutes=bis_min)
    treffer = []
    for b in bloecke_liste:
        if b.datum != datum or not b.start:
            continue
        ueberlappung = (min(b.ende, schluss) - max(b.start, beginn)).total_seconds() / 60
        if ueberlappung > 0:
            treffer.append((b, ueberlappung))
    return treffer


def projektfarben(projekte):
    """Projekt -> Farbnummer 0, 1, 2 … — in der Reihenfolge deiner Projektliste,
    damit ein Projekt überall dieselbe Farbe hat."""
    return {name: i for i, name in enumerate(projekte)}


# ===========================================================================
# Kalendertermine (aus der macOS-Kalender-App, siehe termine.py)
# ===========================================================================

# Ein Termin, wie Kalender und Fenster ihn brauchen:
#   uebernommen  schon als 📅-Eintrag mit genau dieser Start- und Endzeit erfasst
#   projekt, phase  Vorschlag aus den Kalender-Regeln ("?" = nachfragen, None = keine Regel)
#   konflikte    erfasste Zeit, mit der sich der Termin überschneidet
TerminAnzeige = namedtuple("TerminAnzeige", "termin uebernommen projekt phase konflikte")


def termine_im_zeitraum(projekte, von, bis, bloecke_liste=None, fragen=True):
    """Termine der ausgewählten Kalender zwischen `von` und `bis`.

    Rückgabe: (liste, hinweis). hinweis ist None, oder ein Satz, warum keine
    Termine gezeigt werden können (keine Berechtigung, Kalender nicht lesbar).
    Sind gar keine Kalender ausgewählt, ist die Liste einfach leer.
    """
    import termine
    # Der eigene Kalender "zeit" (erfasste Zeiten) ist keine Terminquelle —
    # sonst stünde jede erfasste Zeit noch einmal als Termin daneben
    quellen = [q for q in zeit.kalender_quellen() if q != "zeit"]
    if not quellen:
        return [], None
    try:
        gefunden = termine.lesen(von, bis, quellen, fragen)
    except termine.KeineBerechtigung as grund:
        return [], str(grund)
    except Exception as grund:                      # z. B. Kalender-App hängt
        return [], f"Kalender konnten nicht gelesen werden: {grund}"

    if bloecke_liste is None:
        bloecke_liste = bloecke(projekte, von, bis)
    schon = {(b.start, b.ende) for b in bloecke_liste if b.art == zeit.ART_KALENDER and b.start}
    regeln = zeit.lade_regeln()
    ergebnis = []
    for t in gefunden:
        regel = zeit.regel_fuer(t.titel, t.kalender, regeln)
        uebernommen = (t.start, t.ende) in schon
        konflikte = [] if uebernommen else [
            f"{b.projekt} / {b.phase}: {b.start:%H:%M}–{'jetzt' if b.laufend else f'{b.ende:%H:%M}'}"
            for b in bloecke_liste if b.start and b.start < t.ende and t.start < b.ende]
        ergebnis.append(TerminAnzeige(t, uebernommen,
                                      regel.projekt if regel else None,
                                      regel.phase if regel else None, konflikte))
    return ergebnis, None


def termin_uebernehmen(projekte, termin, projekt, phase):
    """Trägt einen Termin als 📅-Eintrag ein (Projekt und Phase müssen existieren).
    Wirft ValueError mit Erklärung, wenn das nicht geht."""
    if projekt not in projekte:
        raise ValueError(f"Das Projekt '{projekt}' gibt es nicht.")
    if termin.ende <= termin.start:
        raise ValueError("Der Termin hat keine Dauer.")
    if termin.ende > datetime.now():
        raise ValueError("Der Termin ist noch nicht vorbei — übernehmen geht erst danach.")
    minuten = int(round((termin.ende - termin.start).total_seconds() / 60))
    n = zeit.Nachtrag(termin.start.date(), termin.start, termin.ende, minuten)
    return zeit.nachtragen(projekte[projekt], phase, n, art=zeit.ART_KALENDER)


# ===========================================================================
# Zeiträume
# ===========================================================================

ZEITRAUM_ARTEN = ["woche", "monat", "jahr", "alles"]
ZEITRAUM_NAMEN = {"woche": "Woche", "monat": "Monat", "jahr": "Jahr", "alles": "Alles"}


def montag(tag):
    return tag - timedelta(days=tag.weekday())


def zeitraum(art, bezug, schritt=0, fruehester=None):
    """(von, bis, titel) für die Woche/den Monat/das Jahr um `bezug`,
    um `schritt` Einheiten verschoben (−1 = davor)."""
    if art == "woche":
        von = montag(bezug) + timedelta(weeks=schritt)
        bis = von + timedelta(days=6)
        kw = von.isocalendar()[1]
        return von, bis, f"KW {kw} · {von:%d.%m.} – {bis:%d.%m.%Y}"
    if art == "monat":
        monat = bezug.year * 12 + bezug.month - 1 + schritt
        von = date(monat // 12, monat % 12 + 1, 1)
        naechster = date(von.year + (von.month == 12), von.month % 12 + 1, 1)
        return von, naechster - timedelta(days=1), f"{MONATE[von.month - 1]} {von.year}"
    if art == "jahr":
        jahr = bezug.year + schritt
        return date(jahr, 1, 1), date(jahr, 12, 31), str(jahr)
    von = fruehester or bezug
    return von, bezug, f"Alles · seit {von:%d.%m.%Y}"


def fruehestes_datum(projekte):
    daten = [e.datum for e in zeit.alle_eintraege(projekte, warner=lambda _: None)]
    return min(daten) if daten else date.today()


# ===========================================================================
# Statistik
# ===========================================================================

def statistik(projekte, von, bis, jetzt=None, alle_bloecke=None):
    """Alle Zahlen für das Statistik-Board, als dict.

    gesamt, arbeitstage, schnitt (pro Arbeitstag), laengster (datum, min),
    pro_tag [(datum, min)] für jeden Tag des Zeitraums (bis heute),
    pro_projekt / pro_phase [(name, min)] absteigend,
    projekt_phase {projekt: [(phase, min)]},
    rhythmus [wochentag][stunde] -> Minuten (nur Blöcke mit Uhrzeit),
    wochentage [min] Mo..So, beginn / ende: typischer Tagesbeginn/-schluss
    (Median über die Arbeitstage, in Minuten seit Mitternacht), pomodoros.

    alle_bloecke: schon eingelesene Blöcke (z. B. für viele Zeiträume nacheinander);
    sonst werden die Dateien gelesen.
    """
    heute = (jetzt or datetime.now()).date()
    liste = (bloecke(projekte, von, bis, jetzt) if alle_bloecke is None
             else [b for b in alle_bloecke if von <= b.datum <= bis])
    tage, projekt, phase, pp = {}, {}, {}, {}
    rhythmus = [[0.0] * 24 for _ in range(7)]
    erster, letzter = {}, {}
    for b in liste:
        tage[b.datum] = tage.get(b.datum, 0) + b.minuten
        projekt[b.projekt] = projekt.get(b.projekt, 0) + b.minuten
        phase[b.phase] = phase.get(b.phase, 0) + b.minuten
        pp.setdefault(b.projekt, {})
        pp[b.projekt][b.phase] = pp[b.projekt].get(b.phase, 0) + b.minuten
        if b.start:
            s = b.start.hour * 60 + b.start.minute
            e = s + b.minuten
            erster[b.datum] = min(erster.get(b.datum, s), s)
            letzter[b.datum] = max(letzter.get(b.datum, e), e)
            # Minuten auf die Stunden des Tages verteilen (Heatmap)
            minute = s
            while minute < e:
                naechste = min(e, (minute // 60 + 1) * 60)
                rhythmus[b.datum.weekday()][min(23, minute // 60)] += naechste - minute
                minute = naechste

    gesamt = sum(tage.values())
    arbeitstage = sum(1 for m in tage.values() if m > 0)
    pro_tag, tag = [], von
    while tag <= min(bis, heute):
        pro_tag.append((tag, tage.get(tag, 0)))
        tag += timedelta(days=1)
    wochentage = [0] * 7
    for t, m in tage.items():
        wochentage[t.weekday()] += m

    def median(werte):
        werte = sorted(werte)
        return werte[len(werte) // 2] if werte else None

    # Ein Pomodoro über Mitternacht ist in zwei Blöcke geteilt; der zweite
    # beginnt genau um 0:00 und wird nicht noch einmal gezählt. "🍅⏸" (angehalten)
    # ist nur ein Teil eines Pomodoros und zählt ebenfalls nicht extra.
    ganze_pomodoros = [b for b in liste if b.art == zeit.ART_POMODORO
                       and not (b.start and b.start.time() == time(0))]

    # Feedback: Fokus-Verteilung, Fokus je Phase, Notizen. Wie bei den Pomodoros
    # zählt ein über Mitternacht geteilter Eintrag nur einmal (Minuten aber ganz).
    fokus = {f: {"anzahl": 0, "minuten": 0} for f in zeit.FOKUS_WERTE + [""]}
    fokus_phase, notizen = {}, []
    for b in liste:
        fortsetzung = b.start is not None and b.start.time() == time(0)
        fokus[b.fokus if b.fokus in fokus else ""]["minuten"] += b.minuten
        if fortsetzung:
            continue
        fokus[b.fokus if b.fokus in fokus else ""]["anzahl"] += 1
        if b.fokus in zeit.FOKUS_WERTE:
            fokus_phase.setdefault(b.phase, {f: 0 for f in zeit.FOKUS_WERTE})[b.fokus] += 1
        if b.notiz:
            notizen.append((b.datum, b.start, b.projekt, b.phase, b.fokus, b.notiz))
    notizen.sort(key=lambda n: (n[0], n[1] or datetime.min), reverse=True)

    absteigend = lambda d: sorted(d.items(), key=lambda x: -x[1])
    return {
        "von": von, "bis": bis,
        "gesamt": gesamt,
        "arbeitstage": arbeitstage,
        "schnitt": gesamt // arbeitstage if arbeitstage else 0,
        "laengster": max(tage.items(), key=lambda x: x[1]) if tage else None,
        "pro_tag": pro_tag,
        "pro_projekt": absteigend(projekt),
        "pro_phase": absteigend(phase),
        "projekt_phase": {p: absteigend(ph) for p, ph in pp.items()},
        "rhythmus": rhythmus,
        "wochentage": wochentage,
        "beginn": median(erster.values()),
        "ende": median(letzter.values()),
        "fokus": fokus, "fokus_phase": fokus_phase, "notizen": notizen[:40],
        "pomodoros": len(ganze_pomodoros),
        "pomodoros_projekt": _zaehlen(b.projekt for b in ganze_pomodoros),
        "pomodoros_phase": _zaehlen(b.phase for b in ganze_pomodoros),
    }


def _zaehlen(namen):
    zaehler = {}
    for n in namen:
        zaehler[n] = zaehler.get(n, 0) + 1
    return zaehler


def std(minuten):
    """150 -> '2:30'"""
    minuten = int(round(minuten))
    return f"{minuten // 60}:{minuten % 60:02d}"


def uhrzeit(minuten):
    return f"{int(minuten) // 60:02d}:{int(minuten) % 60:02d}" if minuten is not None else "–"
