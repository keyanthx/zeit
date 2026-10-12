#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# <bitbar.title>zeit</bitbar.title>
# <bitbar.version>v1.1</bitbar.version>
# <bitbar.desc>Zeigt den laufenden Timer in der Menüleiste, startet/stoppt ihn und trägt Zeit nach.</bitbar.desc>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
"""
Menüleisten-Anzeige für `zeit` (SwiftBar-Plugin).

Es liest dieselben Markdown-Dateien wie das Terminal-Tool — es gibt keinen
zweiten Datenstand und keine Synchronisation.

Das Skript hat zwei Betriebsarten:

  ohne Argumente      SwiftBar ruft es alle 15 Sekunden so auf (die "15s" im
                      Dateinamen) und baut aus der Ausgabe das Menü:
                        - alles vor der ersten Zeile "---" steht in der Menüleiste
                        - danach folgen die Einträge des Klappmenüs
                        - "--" davor macht ein Untermenü, "----" eine weitere Ebene

  nachtragen P F      Wird von einem Menüpunkt aufgerufen und öffnet ein
                      macOS-Formular mit Datum, Von, Bis und Dauer.
                      (SwiftBar selbst kann keine Texteingabe.)
  pomodoro P F        Formular für Fokus, Pausen und "lange Pause nach N",
                      dann startet die Sitzung.
  countdown P F       Formular für Dauer oder Ende, dann startet der Countdown.
  einstellungen       Formular für Ton und "Noch X min".
  kalender A          Öffnet das Kalender-Fenster (A = tag, woche oder statistik).
  terminal            Öffnet das TUI in einem kleinen Terminal-Fenster oben rechts
                      (oder holt ein schon offenes nach vorn).
"""

import json
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

# Das Plugin liegt in ~/zeit/swiftbar/, die Logik eine Ebene darüber. Beides
# wird aus dem eigenen Dateipfad abgeleitet: dann funktioniert das Plugin auch,
# wenn der Ordner mal woanders liegt. Aufgerufen wird direkt zeit.py und nicht
# der Symlink ~/.local/bin/zeit — fehlt der, täten die Menüpunkte sonst
# stillschweigend nichts.
ZEIT_ORDNER = Path(__file__).resolve().parent.parent
ZEIT_BEFEHL = str(ZEIT_ORDNER / "zeit.py")
DIESES_SKRIPT = str(Path(__file__).resolve())

sys.path.insert(0, str(ZEIT_ORDNER))


# ===========================================================================
# Menü zeichnen
# ===========================================================================

def aktion(*argumente, befehl=ZEIT_BEFEHL):
    """Baut die SwiftBar-Parameter, die beim Klick einen Befehl ausführen.

    terminal=false  -> läuft unsichtbar im Hintergrund, kein Terminalfenster
    refresh=true    -> danach wird das Menü sofort neu aufgebaut
    """
    teile = [f"bash={befehl}"]
    teile += [f"param{i}={wert}" for i, wert in enumerate(argumente, start=1)]
    return " ".join(teile + ["terminal=false", "refresh=true"])


def menue(zeit):
    projekte, phasen = zeit.lade_config()
    # warner=... schluckt Hinweise über fremde Dateien: in der Menüleiste
    # wäre so eine Zeile nur störend, im Terminal siehst du sie weiterhin.
    # Läuft eine Sitzung, aber ihr Wecker nicht mehr (Neustart, Absturz)?
    # Dann hier nachstarten — dieses Skript läuft ohnehin alle 15 Sekunden.
    zeit.wecker_sicherstellen(projekte)
    laufend = zeit.finde_aktiv(projekte, warner=lambda _: None)

    if laufend and laufend[2].sitzung:
        sitzung_menue(zeit, laufend)
    elif laufend:
        name, _, datei = laufend
        phase, start = datei.laeuft
        jetzt = datetime.now()
        vergessen = (start.date() != jetzt.date()
                     or (jetzt - start) >= timedelta(hours=zeit.WARNUNG_AB_STUNDEN))
        print(f"▶ {phase} {zeit.dauer_text(jetzt - start)}{' ⚠' if vergessen else ''}")
        print("---")
        print(f"{name} | color=gray")
        print(f"läuft seit {start:%d.%m. %H:%M} Uhr | color=gray")
        if vergessen:
            print("⚠ Über acht Stunden oder über Nacht | color=orange")
            print("Endzeit korrigieren: zeit stop --um 17:30 | color=orange")
        print("---")
        # --ja: hier kann niemand eine Rückfrage beantworten
        print(f"Anhalten | {aktion('--ja', 'anhalten')}")
        print(f"Stoppen | {aktion('--ja', '--fenster', 'stop')}")
        print(f"Abbrechen (ohne Eintrag) | {aktion('--ja', 'abbrechen')}")
    else:
        print("⏱")
        print("---")
        print("Kein Timer läuft | color=gray")

    print("---")
    if not projekte:
        print("Noch keine Projekte angelegt | color=gray")
        return
    print("Starten")
    for projekt in projekte:
        print(f"--{projekt}")
        for phase in phasen:
            print(f"----{phase} | {aktion('--ja', 'start', projekt, phase)}")
    print("Countdown starten …")
    for projekt in projekte:
        print(f"--{projekt}")
        for phase in phasen:
            print(f"----{phase} | "
                  f"{aktion('countdown', projekt, phase, befehl=DIESES_SKRIPT)}")
    print("Pomodoro starten …")
    for projekt in projekte:
        print(f"--{projekt}")
        for phase in phasen:
            print(f"----{phase} | "
                  f"{aktion('pomodoro', projekt, phase, befehl=DIESES_SKRIPT)}")
    print("Zeit nachtragen …")
    for projekt in projekte:
        print(f"--{projekt}")
        for phase in phasen:
            print(f"----{phase} | "
                  f"{aktion('nachtragen', projekt, phase, befehl=DIESES_SKRIPT)}")
    print("---")
    print(f"Kalender … | {aktion('kalender', 'tag', befehl=DIESES_SKRIPT)}")
    print(f"Statistik … | {aktion('kalender', 'statistik', befehl=DIESES_SKRIPT)}")
    print(f"Einstellungen … | {aktion('einstellungen', befehl=DIESES_SKRIPT)}")


def sitzung_menue(zeit, laufend):
    """Titel und Aktionen während einer Sitzung: Pomodoro, Countdown oder
    angehaltener Timer."""
    name, _, datei = laufend
    z = datei.sitzung
    symbol, was, rest = zeit.sitzung_text(z)
    angehalten = z["zustand"] == "angehalten"

    # --- Titel in der Menüleiste ---------------------------------------------
    if z["typ"] == "timer":
        print(f"⏸ {z['phase']}")
    elif angehalten:
        uebrig = zeit._rest_text(z["rest"]).replace("noch ", "")
        print(f"⏸ {'🍅' if z['typ'] == 'pomodoro' else '⏳'} {uebrig}")
    elif z["typ"] == "countdown":
        print(f"⏳ {rest.replace('noch ', '')}")
    elif z["zustand"] == "fokus":
        print(f"🍅 {zeit.satz_position(z)}/{z['nach']} · {rest.replace('noch ', '')}")
    else:
        print(f"☕ {rest.replace('noch ', '')}")

    # --- Klappmenü -----------------------------------------------------------
    print("---")
    farbe = "orange" if rest.startswith("+") or angehalten else "gray"
    print(f"{symbol} {was} · {rest} | color={farbe}")
    print(f"{name} / {z['phase']} | color=gray")
    if z["typ"] == "countdown" and not angehalten:
        print(f"Ende um {zeit.sitzung_ende(z):%H:%M} | color=gray")
    if not datei.laeuft:
        print("Gerade wird keine Zeit erfasst | color=gray")
    print("---")
    x = zeit.lade_einstellungen()["pomodoro-verlaengern"]
    wort = {"pomodoro": "Sitzung", "countdown": "Countdown", "timer": "Timer"}[z["typ"]]
    if angehalten:
        print(f"Fortsetzen | {aktion('--ja', 'fortsetzen')}")
    elif z["typ"] == "pomodoro" and z["zustand"] == "fokus":
        print(f"Pause starten | {aktion('--ja', '--fenster', 'pomodoro', 'pause')}")
        print(f"Noch {x} min | {aktion('--ja', 'pomodoro', 'mehr')}")
        print(f"Anhalten | {aktion('--ja', 'anhalten')}")
    elif z["typ"] == "pomodoro":
        print(f"Weiter mit Fokus | {aktion('--ja', 'pomodoro', 'weiter')}")
        print(f"Noch {x} min Pause | {aktion('--ja', 'pomodoro', 'mehr')}")
    else:                                               # Countdown läuft
        print(f"Noch {x} min | {aktion('--ja', 'countdown', 'mehr')}")
        print(f"Anhalten | {aktion('--ja', 'anhalten')}")
    print(f"{wort} beenden | {aktion('--ja', '--fenster', 'stop')}")
    print(f"Abbrechen (ohne Eintrag) | {aktion('--ja', 'abbrechen')}")


# ===========================================================================
# Nachtragen mit einem macOS-Formular
# ===========================================================================
#
# Das Formular ist in JavaScript for Automation (JXA) geschrieben — das bringt
# macOS mit, es muss nichts installiert werden. JXA darf die echten macOS-
# Bausteine benutzen (Datumsauswahl, Textfelder, Optionsknöpfe), die ein
# einfaches AppleScript-Dialogfenster nicht hat.
#
# Es steht hier als Text und nicht als eigene Datei, weil SwiftBar jede
# Datei in seinem Ordner als Plugin ausführen würde.
#
# Die vier Felder sind verknüpft:
#   Von ändern    -> Bis wandert mit (die Dauer bleibt)
#   Bis ändern    -> die Dauer wird neu berechnet
#   Dauer ändern  -> je nach Schalter wandert das Ende oder der Anfang
#   "Nur Tag"     -> Von, Bis und Schalter werden ausgegraut; eingetragen
#                    werden nur Datum und Dauer (Start/Ende in der Tabelle: –)
# Geprüft wird am Ende trotzdem in Python (zeit.nachtrag_parsen) — dieselben
# Regeln wie im Terminal und im TUI, nichts doppelt.

_FORMULAR_JXA = r"""
ObjC.import('Cocoa');

var S = {};   // Zustand: von, bis, dauer (Minuten), modusEnde, Bedienelemente
var TAGE = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];

function pad(n) { return (n < 10 ? '0' : '') + n; }
function norm(m) { return ((m % 1440) + 1440) % 1440; }
function hhmm(m) { m = norm(m); return pad(Math.floor(m / 60)) + ':' + pad(m % 60); }
function dauerText(m) { return Math.floor(m / 60) + ':' + pad(m % 60); }
function jsDatum(ns) { return new Date(ns.timeIntervalSince1970 * 1000); }
function nsZeit(m) {
    m = norm(m);
    return $.NSDate.dateWithTimeIntervalSince1970(
        new Date(2001, 0, 1, Math.floor(m / 60), m % 60).getTime() / 1000);
}
function pickerMinuten(p) { var d = jsDatum(p.dateValue); return d.getHours() * 60 + d.getMinutes(); }

// "1:30", "1,5h", "1.5", "2h30", "90min" -> Minuten; unlesbar -> null
function dauerParsen(s) {
    s = s.trim().toLowerCase().replace(',', '.');
    var t;
    if ((t = s.match(/^(\d+):(\d{1,2})$/))) return +t[1] * 60 + +t[2];
    if ((t = s.match(/^(\d+)\s*h\s*(\d{1,2})\s*(m|min)?$/))) return +t[1] * 60 + +t[2];
    if ((t = s.match(/^(\d+)\s*(m|min|minuten)$/))) return +t[1];
    if ((t = s.match(/^(\d+(?:\.\d+)?)\s*(h|std|stunden?)?$/))) return Math.round(parseFloat(t[1]) * 60);
    return null;
}

function nurTagGeaendert() {
    S.nurTag = (S.nurTagK.state == 1);
    [S.vonP, S.bisP, S.endeK, S.anfangK].forEach(function (v) { v.enabled = !S.nurTag; });
}

function vonGeaendert() {
    S.von = pickerMinuten(S.vonP);
    S.bis = norm(S.von + S.dauer);
    S.bisP.dateValue = nsZeit(S.bis);
    S.dauerF.stringValue = dauerText(S.dauer);   // falls dort noch Halbfertiges stand
}
function bisGeaendert() {
    S.bis = pickerMinuten(S.bisP);
    S.dauer = norm(S.bis - S.von);
    S.dauerF.stringValue = dauerText(S.dauer);
}
function dauerGeaendert() {
    var d = dauerParsen(S.dauerF.stringValue.js);
    if (d === null || d <= 0 || d >= 1440) return;   // unfertige Eingabe: abwarten
    S.dauer = d;
    if (S.nurTag) return;                             // ohne Uhrzeiten wandert nichts mit
    if (S.modusEnde) { S.bis = norm(S.von + d); S.bisP.dateValue = nsZeit(S.bis); }
    else             { S.von = norm(S.bis - d); S.vonP.dateValue = nsZeit(S.von); }
}
function datumGeaendert() { S.tagL.stringValue = TAGE[jsDatum(S.datumP.dateValue).getDay()]; }

ObjC.registerSubclass({
    name: 'ZeitFormularZiel',
    protocols: ['NSTextFieldDelegate'],
    methods: {
        'von:':   { types: ['void', ['id']], implementation: function (_) { vonGeaendert(); } },
        'bis:':   { types: ['void', ['id']], implementation: function (_) { bisGeaendert(); } },
        'datum:': { types: ['void', ['id']], implementation: function (_) { datumGeaendert(); } },
        'nurTag:': { types: ['void', ['id']], implementation: function (_) { nurTagGeaendert(); } },
        'modus:': { types: ['void', ['id']], implementation: function (knopf) {
            S.modusEnde = (knopf.title.js === 'Ende'); } },
        'controlTextDidChange:': { types: ['void', ['id']], implementation: function (_) {
            dauerGeaendert(); } }
    }
});

function beschriftung(text, x, y, breite, klein) {
    var l = $.NSTextField.labelWithString(text);
    l.frame = $.NSMakeRect(x, y + 4, breite, 17);
    if (klein) { l.font = $.NSFont.systemFontOfSize(11); l.textColor = $.NSColor.secondaryLabelColor; }
    return l;
}
function auswahl(elemente, x, y, breite, aktion) {
    var p = $.NSDatePicker.alloc.initWithFrame($.NSMakeRect(x, y, breite, 24));
    p.datePickerStyle = $.NSTextFieldAndStepperDatePickerStyle;
    p.datePickerElements = elemente;
    p.locale = $.NSLocale.alloc.initWithLocaleIdentifier('de_DE');
    p.target = S.ziel;
    p.action = aktion;
    return p;
}

function run(argv) {
    var cfg = JSON.parse(argv[0]);
    S.ziel = $.ZeitFormularZiel.alloc.init;
    S.modusEnde = true;
    S.nurTag = false;
    S.von = +cfg.von.split(':')[0] * 60 + +cfg.von.split(':')[1];
    S.bis = +cfg.bis.split(':')[0] * 60 + +cfg.bis.split(':')[1];
    S.dauer = norm(S.bis - S.von);

    var ansicht = $.NSView.alloc.initWithFrame($.NSMakeRect(0, 0, 330, 190));
    var d = cfg.datum.split('-');

    S.datumP = auswahl(0x00e0, 70, 160, 120, 'datum:');            // Tag, Monat, Jahr
    S.datumP.dateValue = $.NSDate.dateWithTimeIntervalSince1970(
        new Date(+d[0], +d[1] - 1, +d[2], 12, 0).getTime() / 1000);
    S.datumP.maxDate = $.NSDate.date;                               // nichts in der Zukunft
    S.tagL = beschriftung('', 198, 160, 120, true);
    datumGeaendert();

    S.vonP = auswahl(0x000c, 70, 96, 80, 'von:');                  // Stunde, Minute
    S.vonP.dateValue = nsZeit(S.von);
    S.bisP = auswahl(0x000c, 70, 64, 80, 'bis:');
    S.bisP.dateValue = nsZeit(S.bis);

    S.dauerF = $.NSTextField.alloc.initWithFrame($.NSMakeRect(70, 32, 80, 24));
    S.dauerF.stringValue = dauerText(S.dauer);
    S.dauerF.delegate = S.ziel;

    S.nurTagK = $.NSButton.checkboxWithTitleTargetAction('Nur Tag (ohne Uhrzeiten)', S.ziel, 'nurTag:');
    S.nurTagK.frame = $.NSMakeRect(68, 130, 250, 20);

    S.endeK = $.NSButton.radioButtonWithTitleTargetAction('Ende', S.ziel, 'modus:');
    S.endeK.frame = $.NSMakeRect(150, 2, 70, 20);
    S.endeK.state = 1;
    S.anfangK = $.NSButton.radioButtonWithTitleTargetAction('Anfang', S.ziel, 'modus:');
    S.anfangK.frame = $.NSMakeRect(220, 2, 90, 20);

    [beschriftung('Datum', 0, 160, 65), S.datumP, S.tagL, S.nurTagK,
     beschriftung('Von', 0, 96, 65), S.vonP,
     beschriftung('Bis', 0, 64, 65), S.bisP,
     beschriftung('Dauer', 0, 32, 65), S.dauerF,
     beschriftung('z. B. 1:30 · 1,5h · 90min', 158, 32, 170, true),
     beschriftung('Dauer verschiebt:', 0, -2, 150, true), S.endeK, S.anfangK
    ].forEach(function (v) { ansicht.addSubview(v); });

    // Testmodus: Felder programmatisch bedienen, ohne ein Fenster zu zeigen
    if (cfg.test) {
        var protokoll = [];
        cfg.test.forEach(function (schritt) {
            var feld = schritt[0], wert = schritt[1];
            if (feld === 'modus') S.modusEnde = (wert === 'ende');
            if (feld === 'nurtag') { S.nurTagK.state = (wert === 'an') ? 1 : 0; nurTagGeaendert(); }
            if (feld === 'von')   { S.vonP.dateValue = nsZeit(+wert.split(':')[0] * 60 + +wert.split(':')[1]); vonGeaendert(); }
            if (feld === 'bis')   { S.bisP.dateValue = nsZeit(+wert.split(':')[0] * 60 + +wert.split(':')[1]); bisGeaendert(); }
            if (feld === 'dauer') { S.dauerF.stringValue = wert; dauerGeaendert(); }
            protokoll.push(schritt.join('=') + ' -> ' + hhmm(pickerMinuten(S.vonP)) + '-'
                           + hhmm(pickerMinuten(S.bisP)) + ' (' + S.dauerF.stringValue.js + ')'
                           + (S.vonP.enabled ? '' : ' [Von/Bis ausgegraut]'));
        });
        return JSON.stringify(protokoll);
    }

    var app = $.NSApplication.sharedApplication;
    app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
    var alert = $.NSAlert.alloc.init;
    alert.messageText = 'Zeit nachtragen';
    alert.informativeText = cfg.titel + (cfg.fehler ? '\n\n⚠ ' + cfg.fehler : '');
    alert.addButtonWithTitle('Eintragen');
    alert.addButtonWithTitle('Abbrechen').keyEquivalent = '\u001b';   // Esc
    alert.accessoryView = ansicht;
    alert.window.level = $.NSFloatingWindowLevel;
    app.activateIgnoringOtherApps(true);
    if (alert.runModal != $.NSAlertFirstButtonReturn) return '';

    var tag = jsDatum(S.datumP.dateValue);
    return JSON.stringify({
        datum: tag.getFullYear() + '-' + pad(tag.getMonth() + 1) + '-' + pad(tag.getDate()),
        von: hhmm(pickerMinuten(S.vonP)),       // aus den Feldern gelesen, nicht
        bis: hhmm(pickerMinuten(S.bisP)),       // aus dem Zwischenstand
        nurTag: S.nurTag,
        dauer: dauerParsen(S.dauerF.stringValue.js)   // null, wenn unlesbar
    });
}
"""


def _formular(titel, werte, fehler="", test=None):
    """Öffnet das Formular. Rückgabe: {"datum", "von", "bis"} oder None (Abbrechen)."""
    cfg = dict(werte, titel=titel, fehler=fehler)
    if test:
        cfg["test"] = test
    ergebnis = subprocess.run(["osascript", "-l", "JavaScript", "-", json.dumps(cfg)],
                              input=_FORMULAR_JXA, capture_output=True, text=True)
    if ergebnis.returncode != 0:
        raise RuntimeError(ergebnis.stderr.strip() or "Formular konnte nicht geöffnet werden")
    ausgabe = ergebnis.stdout.strip()
    return json.loads(ausgabe) if ausgabe else None


# Ein zweites, allgemeineres Formular: eine Reihe von Zahlenfeldern (mit
# ▲▼-Pfeilen) und Auswahllisten. Gebraucht für "Pomodoro starten" und die
# Einstellungen. Wählt man in der Ton-Liste etwas aus, erklingt eine Hörprobe.
_FELDER_JXA = r"""
ObjC.import('Cocoa');

var F = { eintraege: [] };   // je Feld: {cfg, eingabe, pfeile}

ObjC.registerSubclass({
    name: 'ZeitFelderZiel',
    methods: {
        'pfeil:': { types: ['void', ['id']], implementation: function (pfeile) {
            F.eintraege.forEach(function (e) {
                if (e.pfeile && e.pfeile.isEqual(pfeile))
                    e.eingabe.stringValue = String(Number(pfeile.integerValue));
            });
        } },
        'ton:': { types: ['void', ['id']], implementation: function (liste) {
            var name = liste.titleOfSelectedItem.js;
            var ton = $.NSSound.soundNamed(name);
            if (!ton.isNil()) ton.play;
        } }
    }
});

function beschriftung(text, x, y, breite, klein) {
    var l = $.NSTextField.labelWithString(text);
    l.frame = $.NSMakeRect(x, y + 4, breite, 17);
    if (klein) { l.font = $.NSFont.systemFontOfSize(11); l.textColor = $.NSColor.secondaryLabelColor; }
    return l;
}

function run(argv) {
    var cfg = JSON.parse(argv[0]);
    var ziel = $.ZeitFelderZiel.alloc.init;
    // Häkchen-Felder brauchen je Option eine Zeile
    var extra = cfg.felder.reduce(function (s, f) { return s + (f.art === 'haken' ? (f.optionen.length - 1) * 22 : 0); }, 0);
    var hoehe = cfg.felder.length * 32 + 4 + extra;
    var ansicht = $.NSView.alloc.initWithFrame($.NSMakeRect(0, 0, 340, hoehe));

    var versatz = 0;
    cfg.felder.forEach(function (f, i) {
        var y = hoehe - 30 - i * 32 - versatz;
        if (f.art === 'haken') versatz += (f.optionen.length - 1) * 22;
        var e = { cfg: f };
        ansicht.addSubview(beschriftung(f.name, 0, y, 130));
        if (f.art === 'haken') {                    // mehrere Häkchen untereinander
            e.haken = f.optionen.map(function (o, j) {
                var h = $.NSButton.checkboxWithTitleTargetAction(o, null, null);
                h.frame = $.NSMakeRect(135, y - j * 22, 200, 20);
                h.state = f.wert.indexOf(o) >= 0 ? 1 : 0;
                ansicht.addSubview(h);
                return h;
            });
            e.eingabe = e.haken[0];
            F.eintraege.push(e);
            return;
        }
        if (f.art === 'text') {
            e.eingabe = $.NSTextField.alloc.initWithFrame($.NSMakeRect(135, y, 80, 24));
            e.eingabe.stringValue = String(f.wert);
            ansicht.addSubview(beschriftung(f.einheit || '', 222, y, 110, true));
        } else if (f.art === 'auswahl') {
            e.eingabe = $.NSPopUpButton.alloc.initWithFramePullsDown($.NSMakeRect(135, y, 170, 26), false);
            f.optionen.forEach(function (o) { e.eingabe.addItemWithTitle(o); });
            e.eingabe.selectItemWithTitle(f.wert);
            if (f.hoerprobe) { e.eingabe.target = ziel; e.eingabe.action = 'ton:'; }
        } else {
            e.eingabe = $.NSTextField.alloc.initWithFrame($.NSMakeRect(135, y, 60, 24));
            e.eingabe.stringValue = String(f.wert);
            e.pfeile = $.NSStepper.alloc.initWithFrame($.NSMakeRect(197, y, 19, 26));
            e.pfeile.minValue = f.min; e.pfeile.maxValue = f.max;
            e.pfeile.integerValue = Number(f.wert);
            e.pfeile.target = ziel; e.pfeile.action = 'pfeil:';
            ansicht.addSubview(e.pfeile);
            ansicht.addSubview(beschriftung(f.einheit || '', 222, y, 110, true));
        }
        ansicht.addSubview(e.eingabe);
        F.eintraege.push(e);
    });

    function werte() {
        var w = {};
        F.eintraege.forEach(function (e) {
            w[e.cfg.schluessel] = e.cfg.art === 'haken'
                ? e.haken.filter(function (h) { return h.state == 1; }).map(function (h) { return h.title.js; })
                : e.cfg.art === 'auswahl' ? e.eingabe.titleOfSelectedItem.js : e.eingabe.stringValue.js;
        });
        return JSON.stringify(w);
    }

    if (cfg.test) {   // Testmodus: Pfeil einmal drücken, Werte zurückgeben — ohne Fenster
        var e0 = F.eintraege[0];
        // Number(): JXA liefert den Wert hier als Text — "25" + 1 wäre "251"
        if (e0.pfeile) { e0.pfeile.integerValue = Number(e0.pfeile.integerValue) + 1; ziel.pfeil(e0.pfeile); }
        return werte();
    }

    var app = $.NSApplication.sharedApplication;
    app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
    var alert = $.NSAlert.alloc.init;
    alert.messageText = cfg.titel;
    alert.informativeText = cfg.text + (cfg.fehler ? '\n\n⚠ ' + cfg.fehler : '');
    alert.addButtonWithTitle(cfg.knopf);
    alert.addButtonWithTitle('Abbrechen').keyEquivalent = '\u001b';
    alert.accessoryView = ansicht;
    alert.window.level = $.NSFloatingWindowLevel;
    app.activateIgnoringOtherApps(true);
    if (alert.runModal != $.NSAlertFirstButtonReturn) return '';
    return werte();
}
"""


def _felder_formular(titel, text, felder, knopf, fehler="", test=False):
    """Öffnet das Felder-Formular. Rückgabe: {schluessel: text} oder None."""
    cfg = {"titel": titel, "text": text, "felder": felder, "knopf": knopf,
           "fehler": fehler, "test": test}
    ergebnis = subprocess.run(["osascript", "-l", "JavaScript", "-", json.dumps(cfg)],
                              input=_FELDER_JXA, capture_output=True, text=True)
    if ergebnis.returncode != 0:
        raise RuntimeError(ergebnis.stderr.strip() or "Formular konnte nicht geöffnet werden")
    ausgabe = ergebnis.stdout.strip()
    return json.loads(ausgabe) if ausgabe else None


def pomodoro_dialog(zeit, projekt, phase):
    projekte, _ = zeit.lade_config()
    ordner = projekte.get(projekt)
    if ordner is None:
        frage_ok(f"Das Projekt '{projekt}' gibt es nicht mehr.", "OK")
        return
    if zeit.ist_fremde_datei(zeit.zeitdatei_pfad(ordner)):
        frage_ok("In diesem Projektordner liegt eine Zeiterfassung.md, "
                 "die nicht von `zeit` stammt. Sie wird nicht angefasst.", "OK")
        return

    e = zeit.lade_einstellungen()
    werte = {"fokus": e["pomodoro-fokus"], "kurz": e["pomodoro-kurze-pause"],
             "lang": e["pomodoro-lange-pause"], "nach": e["pomodoro-lange-pause-nach"]}
    g, fehler = zeit.POMODORO_GRENZEN, ""
    while True:
        felder = [{"art": "zahl", "schluessel": k, "name": zeit.POMODORO_NAMEN[k],
                   "wert": werte[k], "min": g[k][0], "max": g[k][1],
                   "einheit": "Pomodoros" if k == "nach" else "Minuten"}
                  for k in ("fokus", "kurz", "lang", "nach")]
        ergebnis = _felder_formular(
            "Pomodoro starten", f"{projekt} / {phase}\nVorgeschlagen: die zuletzt benutzten Werte.",
            felder, "Starten", fehler)
        if ergebnis is None:
            return
        try:
            werte = {k: int(str(v).strip()) for k, v in ergebnis.items()}
            zeit.pomodoro_werte_pruefen(werte)
            break
        except ValueError as grund:
            fehler = str(grund) if "invalid literal" not in str(grund) else "Bitte nur ganze Zahlen."

    # Läuft schon etwas? Es darf immer nur eins laufen.
    if not _vorher_beenden(zeit, projekte, "den Pomodoro"):
        return
    zeit.pomodoro_starten(ordner, phase, werte)
    mitteilung(f"🍅 Pomodoro gestartet: {projekt} / {phase}, {werte['fokus']} min Fokus")


def _vorher_beenden(zeit, projekte, was_neu):
    """Läuft schon etwas? Dann fragen, ob es beendet werden soll. False = nein."""
    aktiv = zeit.finde_aktiv(projekte, warner=lambda _: None)
    if not aktiv:
        return True
    name, ordner, datei = aktiv
    if not frage_ok(f"Gerade läuft: {zeit._sitzung_beschreiben(name, datei)}\n\n"
                    f"Beenden und {was_neu} starten?", "Umschalten"):
        return False
    zeit.sitzung_beenden(ordner, datei)
    return True


def countdown_dialog(zeit, projekt, phase):
    projekte, _ = zeit.lade_config()
    ordner = projekte.get(projekt)
    if ordner is None:
        frage_ok(f"Das Projekt '{projekt}' gibt es nicht mehr.", "OK")
        return
    if zeit.ist_fremde_datei(zeit.zeitdatei_pfad(ordner)):
        frage_ok("In diesem Projektordner liegt eine Zeiterfassung.md, "
                 "die nicht von `zeit` stammt. Sie wird nicht angefasst.", "OK")
        return

    # Vorschlag: wie beim letzten Mal; "Bis" = jetzt + letzte Dauer, auf 15 min
    e = zeit.lade_einstellungen()
    dauer = e["countdown-dauer"]
    bis = datetime.now() + timedelta(minutes=dauer + 7)
    bis = bis.replace(minute=bis.minute - bis.minute % 15)
    arten = {"Dauer": "dauer", "Bis Uhrzeit": "bis"}
    werte = {"art": "Bis Uhrzeit" if e["countdown-art"] == "bis" else "Dauer",
             "dauer": f"{dauer // 60}:{dauer % 60:02d}", "bis": f"{bis:%H:%M}"}
    fehler = ""
    while True:
        felder = [
            {"art": "auswahl", "schluessel": "art", "name": "Art", "wert": werte["art"],
             "optionen": list(arten)},
            {"art": "text", "schluessel": "dauer", "name": "Dauer", "wert": werte["dauer"],
             "einheit": "z. B. 2h, 1:30, 90min"},
            {"art": "text", "schluessel": "bis", "name": "Bis", "wert": werte["bis"],
             "einheit": "z. B. 17:00"},
        ]
        ergebnis = _felder_formular(
            "Countdown starten", f"{projekt} / {phase}\n"
            "Bei „Dauer\" zählt das Feld Dauer, bei „Bis Uhrzeit\" das Feld Bis.",
            felder, "Starten", fehler)
        if ergebnis is None:
            return
        werte = ergebnis
        art = arten.get(ergebnis["art"], "dauer")
        try:
            minuten = zeit.countdown_minuten(art, ergebnis[art])
            break
        except ValueError as grund:
            fehler = str(grund)

    if not _vorher_beenden(zeit, projekte, "den Countdown"):
        return
    z = zeit.countdown_starten(ordner, phase, minuten, art)
    mitteilung(f"⏳ Countdown gestartet: {projekt} / {phase}, "
               f"Ende um {zeit.sitzung_ende(z):%H:%M}")


# Das TUI in einem kleinen Terminal-Fenster. Gesteuert wird die Terminal-App
# per JavaScript for Automation (beim ersten Mal fragt macOS, ob SwiftBar das
# Terminal steuern darf). Der Tab bekommt den Titel "zeit" — daran wird ein
# schon offenes Fenster wiedererkannt und nur nach vorn geholt.
# "exec": das TUI ersetzt die Shell; beendest du es, schließt das Terminal das
# Fenster (Standardeinstellung "Schließen, wenn die Shell sauber beendet wurde").
_TERMINAL_JXA = r"""
ObjC.import('AppKit');
function run(argv) {
    var befehl = argv[0], profil = argv[1], spalten = 100, zeilen = 34;
    var T = Application('Terminal');
    // Farbschema = Terminal-Profil gleichen Namens; "Standard" = dein Standardprofil.
    // Fehlt das Profil (umbenannt/gelöscht), bleibt das Fenster einfach, wie es ist.
    function faerben(tab) {
        try {
            tab.currentSettings = profil === 'Standard' ? T.defaultSettings() : T.settingsSets.byName(profil)();
        } catch (e) {}
    }
    var fenster = T.windows();
    for (var i = 0; i < fenster.length; i++) {
        try {
            if (fenster[i].tabs[0].customTitle() === 'zeit' && fenster[i].tabs[0].busy()) {
                faerben(fenster[i].tabs[0]);
                fenster[i].index = 1;                       // nach vorn holen
                T.activate();
                return 'vorhanden';
            }
        } catch (e) {}
    }
    // ZEIT_FARBSCHEMA=1: die Akzentfarbe „Standard“ passt sich dem Profil an
    var tab = T.doScript('clear; exec env ZEIT_FARBSCHEMA=1 ' + befehl);
    tab.customTitle = 'zeit';
    tab.titleDisplaysCustomTitle = true;
    faerben(tab);
    tab.numberOfColumns = spalten;
    tab.numberOfRows = zeilen;
    // oben rechts unter die Menüleiste schieben
    var bildschirm = $.NSScreen.mainScreen.frame, sichtbar = $.NSScreen.mainScreen.visibleFrame;
    var w = T.windows[0], b = w.bounds();
    var breite = b.x !== undefined ? b.width : 0;
    var oben = bildschirm.size.height - (sichtbar.origin.y + sichtbar.size.height) + 6;
    w.bounds = { x: sichtbar.origin.x + sichtbar.size.width - breite - 10, y: oben,
                 width: breite, height: b.height };
    T.activate();
    return 'geoeffnet';
}
"""


def terminal_oeffnen():
    befehl = str(ZEIT_ORDNER / "zeit.py")
    import zeit
    profil = zeit.lade_einstellungen()["farbschema"]
    ergebnis = subprocess.run(["osascript", "-l", "JavaScript", "-", befehl, profil],
                              input=_TERMINAL_JXA, capture_output=True, text=True)
    if ergebnis.returncode != 0:
        frage_ok("Das Terminal-Fenster konnte nicht geöffnet werden:\n\n"
                 + ergebnis.stderr.strip()[-300:] + "\n\nFalls macOS gefragt hat: SwiftBar muss das "
                 "Terminal steuern dürfen (Systemeinstellungen → Datenschutz & Sicherheit → "
                 "Automation → SwiftBar → Terminal).", "OK")


def einstellungen_dialog(zeit):
    e, fehler = zeit.lade_einstellungen(), ""
    # Kalendernamen aus der Kalender-App (beim ersten Mal fragt macOS nach der
    # Berechtigung — dann für SwiftBar). Klappt das nicht, steht im Formular,
    # warum — das Feld soll nie einfach kommentarlos fehlen.
    import termine
    kalender, kalender_problem = [], ""
    try:
        kalender = termine.kalender_namen()
    except termine.KeineBerechtigung:
        kalender_problem = ("Kalender: SwiftBar darf deine Kalender nicht lesen. Erlauben unter "
                            "Systemeinstellungen → Datenschutz & Sicherheit → Kalender → SwiftBar, "
                            "danach Einstellungen neu öffnen.")
    except Exception as grund:
        kalender_problem = f"Kalender konnten nicht gelesen werden: {grund}"
    if not kalender and not kalender_problem:
        kalender_problem = "In der Kalender-App gibt es keine Kalender."
    while True:
        felder = [
            {"art": "auswahl", "schluessel": "ton", "name": "Ton",
             "wert": e["pomodoro-ton"], "optionen": zeit.TOENE + [zeit.KEIN_TON], "hoerprobe": True},
            {"art": "zahl", "schluessel": "verlaengern", "name": "„Noch X min“",
             "wert": e["pomodoro-verlaengern"], "min": 1, "max": 60, "einheit": "Minuten"},
        ]
        felder.append({"art": "auswahl", "schluessel": "schreiben", "name": "In Kalender schreiben",
                       "wert": "An" if e["kalender-schreiben"] == "an" else "Aus",
                       "optionen": ["Aus", "An"]})
        felder.append({"art": "auswahl", "schluessel": "klick", "name": "Klick auf Symbol",
                       "wert": zeit.KLICK_ARTEN.get(e["menueleiste-klick"], "Klappmenü"),
                       "optionen": list(zeit.KLICK_ARTEN.values())})
        felder.append({"art": "text", "schluessel": "projektordner", "name": "Projektordner",
                       "wert": e["projektordner"], "einheit": "neue Projekte"})
        felder.append({"art": "auswahl", "schluessel": "anzeige", "name": "Anzeige",
                       "wert": zeit.ANZEIGEN.get(e["anzeige"], zeit.ANZEIGEN["tui"]),
                       "optionen": list(zeit.ANZEIGEN.values())})
        felder.append({"art": "auswahl", "schluessel": "groesse", "name": "Popup-Größe (GUI)",
                       "wert": zeit.POPUP_GROESSEN.get(e["popup-groesse"], zeit.POPUP_GROESSEN["mittel"])[0],
                       "optionen": [g[0] for g in zeit.POPUP_GROESSEN.values()]})
        import farbschemata
        felder.append({"art": "auswahl", "schluessel": "schema", "name": "Farbschema",
                       "wert": e["farbschema"], "optionen": list(farbschemata.SCHEMATA)})
        felder.append({"art": "auswahl", "schluessel": "akzent", "name": "Akzentfarbe",
                       "wert": e["akzentfarbe"], "optionen": list(zeit.AKZENTFARBEN)})
        if kalender:
            felder.append({"art": "haken", "schluessel": "kalender", "name": "Kalender",
                           "wert": zeit.kalender_quellen(e), "optionen": kalender})
        ergebnis = _felder_formular(
            "Einstellungen", "Pomodoro-Ton, wie lange „Noch X min“ verlängert, ob erfasste Zeiten "
            "in den Kalender „zeit“ geschrieben werden, und aus welchen "
            "Kalendern Termine erscheinen (Häkchen = wird angezeigt).\nKalender-Regeln: im TUI "
            "unter Einstellungen oder in ~/zeit/projekte.md."
            + (f"\n\n⚠ {kalender_problem}" if kalender_problem else ""), felder, "Sichern", fehler)
        if ergebnis is None:
            return
        try:
            x = int(ergebnis["verlaengern"].strip())
            if not 1 <= x <= 60:
                raise ValueError
        except ValueError:
            fehler = "„Noch X min“: bitte eine Zahl von 1 bis 60."
            continue
        e["pomodoro-ton"], e["pomodoro-verlaengern"] = ergebnis["ton"], x
        e["akzentfarbe"] = ergebnis.get("akzent", e["akzentfarbe"])
        e["farbschema"] = ergebnis.get("schema", e["farbschema"])
        ordner = str(ergebnis.get("projektordner", e["projektordner"])).strip()
        if not Path(ordner).expanduser().is_dir():
            fehler = f"Projektordner: den Ordner {ordner} gibt es nicht."
            continue
        e["projektordner"] = ordner
        e["anzeige"] = {v: k for k, v in zeit.ANZEIGEN.items()}.get(ergebnis.get("anzeige"), e["anzeige"])
        e["popup-groesse"] = {g[0]: k for k, g in zeit.POPUP_GROESSEN.items()}.get(
            ergebnis.get("groesse"), e["popup-groesse"])
        e["menueleiste-klick"] = {v: k for k, v in zeit.KLICK_ARTEN.items()}.get(
            ergebnis.get("klick"), e["menueleiste-klick"])
        schreiben_neu = ergebnis.get("schreiben") == "An"
        schreiben_alt = e["kalender-schreiben"] == "an"
        if "kalender" in ergebnis:
            e["kalender-quellen"] = "; ".join(ergebnis["kalender"])
        zeit.speichere_einstellungen(e)
        # In den Kalender schreiben: beim Einschalten einmal nach den bisherigen fragen
        import kalender_schreiben as ks
        if schreiben_neu and not schreiben_alt:
            anzahl = ks.anzahl_eintraege()
            bisherige = anzahl > 0 and frage_ok(
                f"Erfasste Zeiten kommen ab jetzt in den Kalender „zeit“.\n\n"
                f"Sollen auch die {anzahl} bisherigen Einträge hinein?", "Auch bisherige",
                vorgabe_ist_knopf=False)
            ks.einschalten(bisherige)
            mitteilung("In den Kalender schreiben: eingeschaltet (Kalender „zeit“)")
        elif schreiben_alt and not schreiben_neu:
            ks.ausschalten()
        return


_FRAGE_DIALOG = """on run argv
    activate
    display dialog (item 1 of argv) with title "zeit — nachtragen" ¬
        buttons {"Abbrechen", (item 2 of argv)} default button (item 3 of argv) ¬
        cancel button "Abbrechen"
end run"""

_MITTEILUNG = """on run argv
    display notification (item 1 of argv) with title "zeit"
end run"""


def _osascript(skript, *argumente):
    ergebnis = subprocess.run(["osascript", "-", *argumente], input=skript,
                              capture_output=True, text=True)
    return ergebnis.returncode == 0, ergebnis.stdout.strip()


def frage_ok(text, knopf, vorgabe_ist_knopf=True):
    """Dialog mit Abbrechen/<knopf>. Rückgabe: True, wenn <knopf> gedrückt wurde.
    vorgabe_ist_knopf=False macht "Abbrechen" zur Enter-Taste."""
    ok, _ = _osascript(_FRAGE_DIALOG, text, knopf, knopf if vorgabe_ist_knopf else "Abbrechen")
    return ok


def mitteilung(text):
    _osascript(_MITTEILUNG, text)


def vorgaben(jetzt=None):
    """Bis = jetzt, abgerundet auf 15 Minuten; Von = eine Stunde davor."""
    jetzt = jetzt or datetime.now()
    bis = jetzt.replace(minute=jetzt.minute - jetzt.minute % 15, second=0, microsecond=0)
    von = bis - timedelta(hours=1)
    return {"datum": f"{von:%Y-%m-%d}", "von": f"{von:%H:%M}", "bis": f"{bis:%H:%M}"}


def nachtragen_dialog(zeit, projekt, phase):
    projekte, _ = zeit.lade_config()
    ordner = projekte.get(projekt)
    if ordner is None:
        frage_ok(f"Das Projekt '{projekt}' gibt es nicht mehr.", "OK")
        return
    if zeit.ist_fremde_datei(zeit.zeitdatei_pfad(ordner)):
        frage_ok("In diesem Projektordner liegt eine Zeiterfassung.md, "
                 "die nicht von `zeit` stammt. Sie wird nicht angefasst.", "OK")
        return

    werte, fehler = vorgaben(), ""
    while True:
        ergebnis = _formular(f"{projekt} / {phase}", werte, fehler)
        if ergebnis is None:
            return
        werte = {k: ergebnis[k] for k in ("datum", "von", "bis")}  # fürs erneute Öffnen
        if ergebnis.get("nurTag") and ergebnis.get("dauer") is None:
            fehler = "Die Dauer kann ich nicht lesen (z. B. 1:30, 1,5h oder 90min)."
            continue
        if ergebnis.get("nurTag"):
            text = f"{ergebnis['datum']} {ergebnis['dauer']}min"
        else:
            text = f"{ergebnis['datum']} {ergebnis['von']}-{ergebnis['bis']}"
        try:
            # Dieselbe Prüfung wie im Terminal: Zukunft, Dauer null,
            # "Ende vor Anfang", über Mitternacht …
            n = zeit.nachtrag_parsen(text)
            break
        except ValueError as grund:
            fehler = str(grund).replace("\n", " ")

    konflikte = zeit.konflikte_fuer(projekte, n)
    if konflikte:
        frage = (f"{projekt} / {phase}\n{zeit.beschreibe_nachtrag(n)}\n\n"
                 "⚠ Überschneidet sich mit:\n" + "\n".join(konflikte[:5]))
        # Enter = Abbrechen: bei Überschneidung nur bewusst eintragen
        if not frage_ok(frage, "Trotzdem eintragen", vorgabe_ist_knopf=False):
            return
    zeit.nachtragen(ordner, phase, n)
    mitteilung(f"Nachgetragen: {projekt} / {phase}, {zeit.beschreibe_nachtrag(n)}")


# ===========================================================================
# Einstieg
# ===========================================================================

def main():
    import zeit as zeit_modul
    aufgaben = {
        "nachtragen": ("Nachtragen", lambda: nachtragen_dialog(zeit_modul, sys.argv[2], sys.argv[3])),
        "pomodoro": ("Pomodoro starten", lambda: pomodoro_dialog(zeit_modul, sys.argv[2], sys.argv[3])),
        "countdown": ("Countdown starten", lambda: countdown_dialog(zeit_modul, sys.argv[2], sys.argv[3])),
        "einstellungen": ("Einstellungen", lambda: einstellungen_dialog(zeit_modul)),
        "terminal": ("Terminal öffnen", terminal_oeffnen),
        # Das Fenster lebt in kalender_fenster.py (liegt bei zeit.py, nicht hier —
        # sonst hielte SwiftBar es für ein zweites Plugin)
        "kalender": ("Kalender", lambda: __import__("kalender_fenster").oeffnen(
            sys.argv[2] if len(sys.argv) > 2 else "tag")),
    }
    if len(sys.argv) >= 2 and sys.argv[1] in aufgaben:
        name, aufgabe = aufgaben[sys.argv[1]]
        try:
            aufgabe()
        except Exception:
            # Läuft unsichtbar im Hintergrund — ein Fehler muss also sichtbar
            # gemacht werden, sonst passiert beim Klick scheinbar einfach nichts.
            frage_ok(f"{name} ist fehlgeschlagen:\n\n"
                     + traceback.format_exc().strip().splitlines()[-1], "OK")
        return
    # Das Menü erst einsammeln, dann die erste Zeile (der Text in der
    # Menüleiste) in der Akzentfarbe ausgeben
    import io, contextlib
    puffer = io.StringIO()
    with contextlib.redirect_stdout(puffer):
        menue(zeit_modul)
    zeilen = puffer.getvalue().splitlines()
    if zeilen and "|" not in zeilen[0] and zeit_modul.akzentfarbe()[1]:
        zeilen[0] += f" | color={zeit_modul.akzentfarbe()[1]}"
    # Was ein Klick aufs Symbol tut (Einstellung "Klick auf die Menüleiste"):
    #   menue     das Klappmenü, wie bisher
    #   popup     SwiftBar zeigt statt des Menüs eine Webseite als Popup — darin
    #             läuft das TUI oder die GUI (Einstellung „Anzeige“, webterm.py);
    #             die Menüleiste zeigt weiter den Stand
    #   terminal  der Klick öffnet direkt ein Terminalfenster mit dem TUI
    klick = zeit_modul.lade_einstellungen()["menueleiste-klick"]
    if zeilen and klick in ("popup", "terminal"):
        titel = zeilen[0].split(" | ")
        parameter = titel[1] if len(titel) > 1 else ""
        if klick == "popup":
            import webterm
            webterm.sicherstellen()                  # Dienst läuft? sonst starten
            # Lokale Datei statt http:// — SwiftBar zeigt http-Seiten im Popup nicht an
            e = zeit_modul.lade_einstellungen()
            if e["anzeige"] == "gui":                # GUI: Größe nach Einstellung
                _, breite, hoehe = zeit_modul.POPUP_GROESSEN.get(e["popup-groesse"],
                                                                 zeit_modul.POPUP_GROESSEN["mittel"])
            else:                                    # TUI braucht seine Breite
                breite, hoehe = 800, 540
            parameter += f" href={webterm.popup_datei()} webview=true webvieww={breite} webviewh={hoehe}"
            # SwiftBar zeigt das Popup leer an, sobald der Titel "color=" hat
            # (ausprobiert) — im Popup-Modus bleibt das Symbol deshalb ungefärbt.
            parameter = " ".join(x for x in parameter.split() if not x.startswith("color="))
        else:
            parameter += " " + aktion("terminal", befehl=DIESES_SKRIPT).replace(" refresh=true", "")
        zeilen = [f"{titel[0]} | {parameter.strip()}"]     # kein Klappmenü mehr
    print("\n".join(zeilen))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Ein Absturz darf nicht als leeres Symbol enden — sonst sucht man ewig.
        print("zeit ⚠")
        print("---")
        print("Das Plugin konnte nicht laufen | color=red")
        for zeile in traceback.format_exc().strip().splitlines()[-6:]:
            print(zeile.replace("|", "¦") + " | font=Menlo size=11")
