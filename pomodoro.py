#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pomodoro.py — der Wecker für Pomodoro, Countdown und angehaltene Timer.

(Der Name stammt aus der Zeit, als es nur den Pomodoro gab.)

zeit.py startet ihn als eigenen, kleinen Prozess, sobald ein Abschnitt mit
Zeitplan beginnt — ein Fokus, eine Pause, ein Countdown — oder etwas
angehalten wird. Er tut genau eins: warten, bis es Zeit ist, dann melden —
und die Antwort ausführen.

  Zeit um          macOS-Mitteilung mit Ton + ein Dialog mit Knöpfen;
                   ohne Reaktion nach 5 Minuten erneut, danach alle 15
  angehalten       nach 15 Minuten „Noch angehalten — [Beenden] [Fortsetzen]",
                   danach alle 15 Minuten

Wie findet er heraus, ob er noch gebraucht wird? Er liest regelmäßig die
Zeiterfassungs-Datei (dieselbe, die du auch lesen kannst):

  - steht dort keine Sitzung mehr     -> beendet, er endet auch
  - steht dort eine andere Wecker-Nr. -> ein neuerer Wecker ist zuständig
                                         (nach jedem Wechsel startet zeit.py
                                         einen frischen), er endet

Es gibt also keinen Dienst, der dauerhaft läuft, und nichts zu installieren.
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zeit  # noqa: E402

ERSTE_ERINNERUNG = 5        # Minuten nach "Zeit um", wenn niemand reagiert
WEITERE_ERINNERUNG = 15     # danach in diesem Abstand
ANGEHALTEN_ERINNERUNG = 15  # so lange darf etwas angehalten sein, bis er fragt
ANLAUF = 10                 # Sekunden, die ein frischer Wecker auf seine Nummer
                            # in der Datei wartet (zeit.py schreibt sie erst,
                            # nachdem es ihn gestartet hat)
TAKT = 5                    # Sekunden zwischen zwei Blicken in die Datei.
                            # Kurze Schritte statt eines langen Schlafs: so
                            # stimmt die Zeit auch nach dem Ruhezustand des Macs.


# ===========================================================================
# macOS: Mitteilung und Dialog
# ===========================================================================
#
# Die Texte kommen als Argumente (argv) ins AppleScript, statt in den
# Skripttext eingebaut zu werden — so kann kein Anführungszeichen etwas
# kaputtmachen. argv: Text, Titel, Knopf 1 … Knopf n, Sekunden bis zum Schließen.
# Der letzte Knopf ist der, den Enter auslöst.

_DIALOG = """on run argv
    activate
    set anzahl to count of argv
    set knoepfe to items 3 thru (anzahl - 1) of argv
    set antwort to display dialog (item 1 of argv) with title (item 2 of argv) ¬
        buttons knoepfe default button (count of knoepfe) ¬
        giving up after ((item anzahl of argv) as integer)
    if gave up of antwort then return ""
    return button returned of antwort
end run"""

_MITTEILUNG_MIT_TON = """on run argv
    display notification (item 1 of argv) with title (item 2 of argv) sound name (item 3 of argv)
end run"""

_MITTEILUNG = """on run argv
    display notification (item 1 of argv) with title (item 2 of argv)
end run"""


def mitteilung(titel, text, ton):
    if ton and ton != zeit.KEIN_TON:
        skript, argumente = _MITTEILUNG_MIT_TON, [text, titel, ton]
    else:
        skript, argumente = _MITTEILUNG, [text, titel]
    subprocess.run(["osascript", "-", *argumente], input=skript,
                   capture_output=True, text=True)


def dialog_zeigen(titel, text, knoepfe, sekunden, noch_gueltig):
    """Zeigt den Dialog höchstens `sekunden` lang.

    Rückgabe: Index des gedrückten Knopfs, oder None, wenn niemand geklickt
    hat oder die Lage sich inzwischen geändert hat (dann wird der Dialog
    geschlossen — z. B. weil du im TUI schon auf "Pause" gedrückt hast).
    """
    prozess = subprocess.Popen(
        ["osascript", "-", text, titel, *knoepfe, str(max(1, int(sekunden)))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    prozess.stdin.write(_DIALOG)
    prozess.stdin.close()
    while prozess.poll() is None:
        time.sleep(1)
        if not noch_gueltig():
            prozess.kill()
            return None
    antwort = prozess.stdout.read().strip()
    return knoepfe.index(antwort) if antwort in knoepfe else None


def fragen(titel, text, knoepfe, faellig_bis, noch_gueltig):
    """Wie dialog_zeigen — aber ist die GUI gerade offen, fragt sie selbst: Sie
    sieht, dass die Zeit um ist, und zeigt dieselben Knöpfe. Der Wecker wartet
    dann nur. Wird die GUI geschlossen, bevor jemand reagiert hat, kommt doch
    noch der Dialog (für die restliche Zeit bis zur nächsten Erinnerung)."""
    while zeit.gui_offen():
        if not noch_gueltig() or datetime.now() >= faellig_bis:
            return None
        time.sleep(1)
    rest = (faellig_bis - datetime.now()).total_seconds()
    if rest <= 0 or not noch_gueltig():
        return None
    return dialog_zeigen(titel, text, knoepfe, rest, noch_gueltig)


# ===========================================================================
# Was gemeldet wird
# ===========================================================================

def lage():
    """(name, ordner, datei) der laufenden Sitzung, oder None."""
    projekte, _ = zeit.lade_config()
    aktiv = zeit.finde_aktiv(projekte, warner=lambda _: None)
    return aktiv if aktiv and aktiv[2].sitzung else None


def meldung(name, z, gemeldet, verlaengern):
    """Titel, Text und Knöpfe für die jetzige Meldung (gemeldet = 1, 2, …).
    Knöpfe sind (Beschriftung, Aktion); der letzte ist die Vorgabe (Enter)."""
    minuten = int((datetime.now() - z["seit"]).total_seconds() // 60)
    wo = f"{name} / {z['phase']}"

    if z["zustand"] == "angehalten":
        was = {"pomodoro": "Der Pomodoro-Fokus", "countdown": "Der Countdown",
               "timer": "Der Timer"}[z["typ"]]
        return ("zeit — noch angehalten",
                f"{was} ist seit {minuten} min angehalten.\n{wo}",
                [("Beenden", "beenden"), ("Fortsetzen", "fortsetzen")])

    ueber = minuten - int(z["plan"])
    if z["typ"] == "countdown":
        text = (f"Zeit um — {wo}" if gemeldet == 1 else
                f"Der Countdown ist seit {ueber} min vorbei.\n{wo}")
        return ("zeit — Countdown", text,
                [("Countdown beenden", "beenden"), (f"Noch {verlaengern} min", "mehr")])

    if z["zustand"] == "fokus":
        text = (f"Fokus vorbei — {wo}\n{zeit.sitzung_text(z)[1]}." if gemeldet == 1 else
                f"Der Fokus läuft schon {minuten} min — {ueber} min länger als geplant.\n{wo}")
        return (f"zeit — Pomodoro {zeit.satz_position(z)}/{z['nach']}", text,
                [("Sitzung beenden", "beenden"), (f"Noch {verlaengern} min", "mehr"),
                 ("Pause starten", "pause")])

    art = "lange Pause" if zeit.ist_lange_pause(z) else "Pause"
    text = (f"Die {art} ist vorbei — weiter mit {wo}?" if gemeldet == 1 else
            f"Die {art} dauert schon {minuten} min.\nWeiter mit {wo}?")
    return ("zeit — Pause vorbei", text,
            [("Sitzung beenden", "beenden"), (f"Noch {verlaengern} min Pause", "mehr"),
             ("Weiter mit Fokus", "weiter")])


def ausfuehren(aktion, erwartet, verlaengern):
    """Führt den gedrückten Knopf aus — aber nur, wenn die Lage noch dieselbe
    ist wie beim Öffnen des Dialogs. Sonst wäre ein alter Klick gefährlich."""
    aktuell = lage()
    if not aktuell or _schluessel(aktuell[2].sitzung) != erwartet:
        return
    name, ordner, datei = aktuell
    if aktion == "beenden":                          # mit Bericht, was erfasst wurde
        b = zeit.beenden_mit_bericht(name, ordner, datei)
        if b:
            zeit.feedback_fenster(zeit.bericht_zeilen(b), ordner, b["ziel"])
        return
    if aktion == "pause":                            # Fokusblock fertig -> Feedback
        ergebnis = zeit.pomodoro_pause(ordner, datei)
        if ergebnis:
            zeit.feedback_fenster(zeit.fokusblock_bericht(name, ergebnis), ordner,
                                  (f"{ergebnis[2]:%Y-%m-%d}", f"{ergebnis[2]:%H:%M}"))
        return
    {
     "mehr": lambda: zeit.verlaengern(ordner, datei, verlaengern),
     "pause": lambda: zeit.pomodoro_pause(ordner, datei),
     "weiter": lambda: zeit.pomodoro_weiter(ordner, datei),
     "fortsetzen": lambda: zeit.fortsetzen(ordner, datei)}[aktion]()


def _schluessel(z):
    """Woran man erkennt, dass sich nichts geändert hat."""
    return (z["typ"], z["zustand"], z.get("nr"), z["seit"], z.get("plan"), z["wecker"])


def _faellig(z, gemeldet):
    """Wann die (gemeldet+1)-te Meldung fällig ist."""
    if z["zustand"] == "angehalten":
        return z["seit"] + timedelta(minutes=ANGEHALTEN_ERINNERUNG * (gemeldet + 1))
    ende = zeit.sitzung_ende(z)
    if gemeldet == 0:
        return ende
    return ende + timedelta(minutes=ERSTE_ERINNERUNG + WEITERE_ERINNERUNG * (gemeldet - 1))


# ===========================================================================
# Die Schleife
# ===========================================================================

def wecker(ich=None):
    ich = ich or os.getpid()
    geboren = time.time()
    bestaetigt = False          # schon einmal die eigene Nummer in der Datei gesehen?
    stand, gemeldet = None, 0
    while True:
        aktuell = lage()
        if aktuell is None:
            return                                   # Sitzung beendet
        name, _, datei = aktuell
        z = datei.sitzung
        if z["wecker"] != ich:
            # Nur ein frischer Wecker, der seine Nummer noch nie gesehen hat,
            # wartet kurz darauf. Wer sie schon hatte und jetzt eine fremde
            # sieht, wurde abgelöst und geht sofort — sonst liefen kurz zwei.
            if not bestaetigt and time.time() - geboren < ANLAUF:
                time.sleep(1)
                continue
            return                                   # ein neuerer ist zuständig
        bestaetigt = True

        if _schluessel(z) != stand:                  # neuer Abschnitt oder verlängert
            stand, gemeldet = _schluessel(z), 0

        warten = (_faellig(z, gemeldet) - datetime.now()).total_seconds()
        if warten > 0:
            time.sleep(min(TAKT, warten))
            continue

        gemeldet += 1
        einstellungen = zeit.lade_einstellungen()
        verlaengern = einstellungen["pomodoro-verlaengern"]
        titel, text, knoepfe = meldung(name, z, gemeldet, verlaengern)
        mitteilung(titel, text.replace("\n", " "), einstellungen["pomodoro-ton"])
        erwartet = stand
        index = fragen(
            titel, text, [k for k, _ in knoepfe], _faellig(z, gemeldet),
            noch_gueltig=lambda: (lage() is not None
                                  and _schluessel(lage()[2].sitzung) == erwartet))
        if index is not None:
            ausfuehren(knoepfe[index][1], erwartet, verlaengern)


if __name__ == "__main__":
    if sys.argv[1:] == ["wecker"]:
        try:
            wecker()
        except Exception:
            pass    # ein Wecker darf nie mit einer Fehlermeldung hängen bleiben;
                    # Menüleiste und TUI starten notfalls einen neuen
