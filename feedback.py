#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feedback.py — das Feedback-Fenster nach einem Block (für Menüleiste und Wecker).

Zeigt oben den Bericht, was erfasst wurde, darunter freiwillig: wie fokussiert
(😄 😐 ☹️) und eine Notiz. "Speichern" schreibt beides in die Zeile des Blocks
(Spalten Fokus und Notiz), "Überspringen" schreibt nichts, "Kalender öffnen"
springt in die Tagesansicht.

Das Fenster ist ein macOS-Dialog aus JavaScript for Automation (Bordmittel).
zeit.py startet dieses Skript als eigenen Prozess — so wartet niemand darauf,
dass du das Fenster schließt.

Aufruf:  feedback.py '<json>'   mit bericht (Zeilen), ordner, datum, start
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zeit  # noqa: E402

_JXA = r"""
ObjC.import('Cocoa');
function run(argv) {
    var cfg = JSON.parse(argv[0]);
    var app = $.NSApplication.sharedApplication;
    app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);

    var ansicht = $.NSView.alloc.initWithFrame($.NSMakeRect(0, 0, 380, 92));
    var frage = $.NSTextField.labelWithString('Wie fokussiert warst du?  (freiwillig)');
    frage.frame = $.NSMakeRect(0, 70, 380, 18);
    // Drei Knöpfe als Segment-Schalter; keiner gewählt = keine Bewertung
    var fokus = $.NSSegmentedControl.segmentedControlWithLabelsTrackingModeTargetAction(
        $(['😄 fokussiert', '😐 so lala', '☹️ abgelenkt']), 0, null, null);
    fokus.frame = $.NSMakeRect(0, 40, 380, 26);
    var notiz = $.NSTextField.alloc.initWithFrame($.NSMakeRect(0, 4, 380, 24));
    notiz.placeholderString = 'Notiz (freiwillig) — z. B. was gut lief, was gestört hat';
    [frage, fokus, notiz].forEach(function (v) { ansicht.addSubview(v); });
    if (cfg.test) {                                 // Testmodus: nur bauen, nicht zeigen
        fokus.selectedSegment = 1; notiz.stringValue = 'Test';
        return JSON.stringify({ aktion: 'speichern', fokus: Number(fokus.selectedSegment), notiz: notiz.stringValue.js });
    }

    var alert = $.NSAlert.alloc.init;
    alert.messageText = 'zeit — erfasst';
    alert.informativeText = cfg.bericht;
    alert.addButtonWithTitle('Speichern');
    alert.addButtonWithTitle('Überspringen').keyEquivalent = '\u001b';
    alert.addButtonWithTitle('Kalender öffnen');
    alert.accessoryView = ansicht;
    alert.window.initialFirstResponder = notiz;
    alert.window.level = $.NSFloatingWindowLevel;
    app.activateIgnoringOtherApps(true);
    var knopf = alert.runModal;
    var aktion = knopf == $.NSAlertFirstButtonReturn ? 'speichern'
               : knopf == $.NSAlertThirdButtonReturn ? 'kalender' : 'ueberspringen';
    // Number(): JXA liefert die Auswahl sonst als Text ("1") — Python bräche dann ab
    return JSON.stringify({ aktion: aktion, fokus: Number(fokus.selectedSegment), notiz: notiz.stringValue.js });
}
"""


def fenster(cfg, test=False):
    """Zeigt das Fenster. Rückgabe: {"aktion", "fokus" (Index oder -1), "notiz"}."""
    ergebnis = subprocess.run(["osascript", "-l", "JavaScript", "-", json.dumps(dict(cfg, test=test))],
                              input=_JXA, capture_output=True, text=True)
    if ergebnis.returncode != 0:
        raise RuntimeError(ergebnis.stderr.strip())
    return json.loads(ergebnis.stdout)


def auswerten(cfg, antwort):
    """Speichert, was im Fenster angegeben wurde (falls überhaupt etwas)."""
    try:
        stufe = int(antwort["fokus"])              # zur Sicherheit auch hier: Text -> Zahl
    except (TypeError, ValueError):
        stufe = -1
    fokus = zeit.FOKUS_WERTE[stufe] if 0 <= stufe < 3 else ""
    notiz = antwort["notiz"].strip()
    if antwort["aktion"] == "speichern" and (fokus or notiz):
        zeit.feedback_setzen(Path(cfg["ordner"]), cfg["datum"], cfg["start"], fokus, notiz)
    if antwort["aktion"] == "kalender":
        skript = Path(__file__).resolve().parent / "kalender_fenster.py"
        subprocess.Popen([sys.executable, str(skript), "oeffnen", "tag"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    cfg = json.loads(sys.argv[1])
    try:
        auswerten(cfg, fenster(cfg))
    except Exception:
        pass        # ein Feedback-Fenster darf nie etwas kaputtmachen
