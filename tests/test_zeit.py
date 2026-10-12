"""
Tests für zeit — nur Python-Standardbibliothek.

Ausführen (im Programmordner):   python3 -m unittest discover tests

Die Tests laufen in einem leeren, vorübergehenden Benutzerordner (HOME wird
umgebogen), deine echten Daten werden also nie angefasst. Der Wecker und alle
macOS-Fenster sind dabei abgeschaltet (ZEIT_KEIN_WECKER=1).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

# --- Vor dem Import von zeit: eigener, leerer Benutzerordner -----------------
TESTHOME = Path(tempfile.mkdtemp(prefix="zeit-test-"))
os.environ["HOME"] = str(TESTHOME)
os.environ["ZEIT_KEIN_WECKER"] = "1"
os.environ["ZEIT_PORT"] = "47999"            # nie der Port des echten Dienstes

ORDNER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ORDNER))

import gui_api  # noqa: E402
import zeit  # noqa: E402

ZEIT = [sys.executable, str(ORDNER / "zeit.py")]


def cli(*argumente):
    """zeit als Befehl ausführen (mit --ja: keine Rückfragen)."""
    return subprocess.run([*ZEIT, "--ja", *argumente], capture_output=True, text=True,
                          env=dict(os.environ), timeout=30)


class Grundlage(unittest.TestCase):
    """Jeder Test beginnt mit leerem Benutzerordner und einem Projekt „test“."""

    def setUp(self):
        for teil in TESTHOME.iterdir():
            shutil.rmtree(teil) if teil.is_dir() else teil.unlink()
        self.projektordner = TESTHOME / "Projekte" / "Test"
        self.projektordner.mkdir(parents=True)
        zeit.speichere_config({"test": self.projektordner}, list(zeit.STANDARD_PHASEN))

    def datei(self):
        return zeit.lese_zeitdatei(zeit.zeitdatei_pfad(self.projektordner), "Test")

    def laeuft_seit(self, minuten):
        """Den laufenden Timer so verschieben, als liefe er schon so lange."""
        d = self.datei()
        phase, _ = d.laeuft
        d.laeuft = (phase, zeit._jetzt() - timedelta(minutes=minuten))
        zeit.schreibe_zeitdatei(zeit.zeitdatei_pfad(self.projektordner), d)


class Befehle(Grundlage):

    def test_start_und_stop(self):
        self.assertEqual(cli("start", "test", "planung").returncode, 0)
        self.assertIn("planung", cli("status").stdout)
        self.laeuft_seit(30)
        self.assertEqual(cli("stop").returncode, 0)
        eintraege = self.datei().eintraege
        self.assertEqual(len(eintraege), 1)
        self.assertEqual(eintraege[0][3], "0:30")
        self.assertEqual(eintraege[0][4], "planung")

    def test_unter_einer_minute_kein_eintrag(self):
        cli("start", "test", "planung")
        cli("stop")
        self.assertEqual(self.datei().eintraege, [])

    def test_abbrechen(self):
        cli("start", "test", "planung")
        self.laeuft_seit(20)
        cli("abbrechen")
        d = self.datei()
        self.assertIsNone(d.laeuft)
        self.assertEqual(d.eintraege, [])

    def test_neue_phase_beim_start(self):
        cli("start", "test", "eigene-phase")
        self.assertIn("eigene-phase", zeit.lade_config()[1])

    def test_nachtragen_sortiert(self):
        cli("nachtragen", "test", "planung", "2026-01-06 10:00-11:00")
        cli("nachtragen", "test", "planung", "2026-01-05 09:00-11:30")
        eintraege = self.datei().eintraege
        self.assertEqual([e[0] for e in eintraege], ["2026-01-05", "2026-01-06"])
        self.assertEqual(eintraege[0][3], "2:30")
        self.assertEqual(eintraege[0][5], zeit.ART_NACHTRAG)

    def test_datei_ist_lesbares_markdown(self):
        cli("nachtragen", "test", "planung", "2026-01-05 09:00-10:00")
        text = zeit.zeitdatei_pfad(self.projektordner).read_text(encoding="utf-8")
        self.assertIn(zeit.FORMAT_MARKER, text)
        self.assertIn("| 2026-01-05 | 09:00 | 10:00 | 1:00", text)

    def test_anhalten_und_fortsetzen(self):
        cli("start", "test", "planung")
        self.laeuft_seit(15)
        cli("anhalten")
        d = self.datei()
        self.assertEqual(d.sitzung["zustand"], "angehalten")
        self.assertTrue(d.eintraege[-1][5].endswith(zeit.ANGEHALTEN))
        cli("fortsetzen")
        self.assertIsNotNone(self.datei().laeuft)


class Nachtrag(unittest.TestCase):

    def test_zeitraum(self):
        n = zeit.nachtrag_parsen("2026-01-05 9:00-11:30")
        self.assertEqual(n.minuten, 150)
        self.assertEqual(n.start, datetime(2026, 1, 5, 9, 0))

    def test_nur_tag(self):
        n = zeit.nachtrag_parsen("gestern 3h")
        self.assertIsNone(n.start)
        self.assertEqual(n.minuten, 180)
        self.assertEqual(n.datum, date.today() - timedelta(days=1))

    def test_zukunft_geht_nicht(self):
        with self.assertRaises(ValueError):
            zeit.nachtrag_parsen(f"{date.today() + timedelta(days=2)} 9:00-10:00")

    def test_countdown_dauer(self):
        self.assertEqual(zeit.countdown_minuten("dauer", "1:30"), 90)
        self.assertEqual(zeit.countdown_minuten("dauer", "2h"), 120)
        with self.assertRaises(ValueError):
            zeit.countdown_minuten("dauer", "quatsch")


class Sitzungen(Grundlage):

    def test_pomodoro_ablauf(self):
        zeit.pomodoro_starten(self.projektordner, "planung", {"fokus": 25, "kurz": 5, "lang": 15, "nach": 4})
        self.laeuft_seit(25)
        zeit.pomodoro_pause(self.projektordner, self.datei())
        d = self.datei()
        self.assertEqual(d.sitzung["zustand"], "pause")
        self.assertEqual(d.eintraege[-1][5], zeit.ART_POMODORO)
        zeit.pomodoro_weiter(self.projektordner, d)
        d = self.datei()
        self.assertEqual((d.sitzung["zustand"], d.sitzung["nr"]), ("fokus", 2))
        zeit.sitzung_beenden(self.projektordner, d)
        self.assertIsNone(self.datei().sitzung)

    def test_countdown_bericht(self):
        zeit.countdown_starten(self.projektordner, "planung", 60)
        d = self.datei()
        d.sitzung["beginn"] = d.sitzung["seit"] = datetime.now().replace(microsecond=0) - timedelta(minutes=40)
        zeit.schreibe_zeitdatei(zeit.zeitdatei_pfad(self.projektordner), d)
        self.laeuft_seit(40)
        b = zeit.beenden_mit_bericht("test", self.projektordner, self.datei())
        self.assertEqual(b["minuten"], 40)
        self.assertTrue(any("Countdown" in z for z in zeit.bericht_zeilen(b)))

    def test_feedback(self):
        zeit.nachtragen(self.projektordner, "planung", zeit.nachtrag_parsen("2026-01-05 9:00-10:00"))
        self.assertTrue(zeit.feedback_setzen(self.projektordner, "2026-01-05", "09:00", "😄", "gut | klar"))
        zeile = self.datei().eintraege[0]
        self.assertEqual((zeile[6], zeile[7]), ("😄", "gut / klar"))


class Konfiguration(Grundlage):

    def test_umzug_aus_altem_ort(self):
        zeit.CONFIG_DATEI.unlink()
        alt = TESTHOME / "zeit" / "projekte.md"
        alt.parent.mkdir()
        alt.write_text("## Projekte\n\n| Kurzname | Ordner |\n|---|---|\n| alt | /tmp |\n\n## Phasen\n\n- x\n",
                       encoding="utf-8")
        projekte, phasen = zeit.lade_config()
        self.assertEqual(list(projekte), ["alt"])
        self.assertTrue(zeit.CONFIG_DATEI.exists())
        self.assertFalse(alt.exists())

    def test_einstellungen_bleiben_erhalten(self):
        e = zeit.lade_einstellungen()
        e["pomodoro-ton"] = "Ping"
        zeit.speichere_einstellungen(e)
        self.assertEqual(zeit.lade_einstellungen()["pomodoro-ton"], "Ping")
        self.assertEqual(list(zeit.lade_config()[0]), ["test"])


class GUI(Grundlage):
    """Die Schnittstelle, über die die grafische Oberfläche arbeitet."""

    def a(self, **auftrag):
        return gui_api.ausfuehren(auftrag)

    def test_zustand(self):
        z = gui_api.zustand()
        self.assertEqual(z["projekte"], ["test"])
        self.assertIsNone(z["laufend"])

    def test_umschalten_braucht_bestaetigung(self):
        self.assertIn("meldung", self.a(aktion="start", projekt="test", phase="planung"))
        frage = self.a(aktion="start", projekt="test", phase="umsetzung")
        self.assertIn("frage", frage)
        self.a(aktion="start", projekt="test", phase="umsetzung", ok=True)
        self.assertEqual(gui_api.zustand()["laufend"]["phase"], "umsetzung")

    def test_ueberschneidung_fragt_nach(self):
        self.a(aktion="nachtragen", projekt="test", phase="planung", datum="2026-01-05", von="09:00", bis="10:00")
        r = self.a(aktion="nachtragen", projekt="test", phase="planung", datum="2026-01-05", von="09:30", bis="10:30")
        self.assertIn("frage", r)

    def test_eintrag_aendern_und_loeschen(self):
        self.a(aktion="nachtragen", projekt="test", phase="planung", datum="2026-01-05", von="09:00", bis="10:00")
        e = self.a(aktion="eintraege", projekt="test")["eintraege"][0]
        self.a(aktion="eintrag_aendern", projekt="test", i=e["i"], zellen=e["zellen"], datum="2026-01-05",
               von="09:00", bis="10:30", phase="umsetzung", fokus="😐", notiz="ok")
        zeile = self.datei().eintraege[0]
        self.assertEqual(zeile[2:5] + zeile[6:], ["10:30", "1:30", "umsetzung", "😐", "ok"])
        e = self.a(aktion="eintraege", projekt="test")["eintraege"][0]
        self.assertIn("frage", self.a(aktion="eintrag_loeschen", projekt="test", i=e["i"], zellen=e["zellen"]))
        self.a(aktion="eintrag_loeschen", projekt="test", i=e["i"], zellen=e["zellen"], ok=True)
        self.assertEqual(self.datei().eintraege, [])

    def test_einstellungen_werden_geprueft(self):
        self.assertIn("fehler", self.a(aktion="einstellung", schluessel="anzeige", wert="quatsch"))
        self.assertIn("fehler", self.a(aktion="einstellung", schluessel="projektordner", wert="/gibt/es/nicht"))
        self.a(aktion="einstellung", schluessel="projektordner", wert=str(TESTHOME / "Projekte"))
        self.assertEqual(zeit.lade_einstellungen()["projektordner"], "~/Projekte")

    def test_projekt_anlegen_mit_vorschlag(self):
        self.a(aktion="einstellung", schluessel="projektordner", wert=str(TESTHOME / "Projekte"))
        vorschlag = self.a(aktion="ordner_vorschlag", name="Neues Ding")["ordner"]
        self.assertEqual(Path(vorschlag), TESTHOME / "Projekte" / "Neues Ding")
        self.a(aktion="projekt_anlegen", name="Neues Ding", ordner=vorschlag)
        self.assertIn("neues-ding", zeit.lade_config()[0])
        self.assertTrue(Path(vorschlag).is_dir())


class Oberflaechen(Grundlage):

    def test_menueleiste(self):
        ausgabe = subprocess.run([sys.executable, str(ORDNER / "swiftbar" / "zeit.15s.py")],
                                 capture_output=True, text=True, env=dict(os.environ), timeout=30).stdout
        self.assertTrue(ausgabe.startswith("⏱"))
        self.assertIn("Starten", ausgabe)

    def test_tui_startet_und_endet(self):
        """Das TUI in einem Pseudo-Terminal öffnen und mit q beenden."""
        ausgabe, status = tui_bedienen([b"q"], warten_auf=b"Zeiterfassung")
        self.assertIn("Zeiterfassung", ausgabe)
        self.assertEqual(status, 0)


class Tutorial(unittest.TestCase):

    def setUp(self):
        for teil in TESTHOME.iterdir():
            shutil.rmtree(teil) if teil.is_dir() else teil.unlink()

    def test_erster_start_zeigt_tutorial_und_esc_beendet(self):
        # Noch keine Projekte -> Tutorial; Esc + j beendet es, dann kommt das Hauptmenü
        ausgabe, status = tui_bedienen([b"\x1b", b"j", b"q"], warten_auf=b"Willkommen")
        self.assertIn("Willkommen bei zeit", ausgabe)
        self.assertIn("Kein Timer", ausgabe)
        self.assertEqual(status, 0)
        self.assertEqual(zeit.lade_einstellungen()["tutorial"], "fertig")

    def test_kein_tutorial_wenn_es_projekte_gibt(self):
        ordner = TESTHOME / "P"
        ordner.mkdir()
        zeit.speichere_config({"p": ordner}, ["a"])
        ausgabe, _ = tui_bedienen([b"q"], warten_auf=b"Zeiterfassung")
        self.assertNotIn("Willkommen", ausgabe)

    def test_uebungsprojekt_wird_aufgeraeumt(self):
        import tui
        import tutorial
        tui.zeit = zeit
        zeit.speichere_config({}, ["planung", "umsetzung"])
        u = tutorial.Uebung()
        u.anlegen()
        self.assertIn("beispiel", zeit.lade_config()[0])
        u.pomodoro_kurz()
        self.assertEqual(zeit.lade_einstellungen()["pomodoro-fokus"], 1)
        u.aufraeumen()
        self.assertNotIn("beispiel", zeit.lade_config()[0])
        self.assertEqual(zeit.lade_einstellungen()["pomodoro-fokus"], 25)
        self.assertFalse(tutorial.UEBUNGSORDNER.exists())


def tui_bedienen(tasten, warten_auf):
    """Startet das TUI in einem Pseudo-Terminal (100×30), wartet auf einen Text,
    schickt die Tasten (je eine halbe Sekunde Abstand) und wartet aufs Ende.
    Rückgabe: (gesamte Ausgabe als Text, Exit-Code)."""
    import fcntl
    import pty
    import select
    import struct
    import termios
    import time
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, ZEIT, dict(os.environ, TERM="xterm-256color", LANG="de_DE.UTF-8"))
    # Ein echtes Terminal hat eine Größe — ohne die gerät curses durcheinander
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    ausgabe = b""

    def lesen(sekunden):
        nonlocal ausgabe
        ende = time.time() + sekunden
        while time.time() < ende:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    ausgabe += os.read(fd, 65536)
                except OSError:
                    return

    ende = time.time() + 5
    while time.time() < ende and warten_auf not in ausgabe:
        lesen(0.2)
    for taste in tasten:
        os.write(fd, taste)
        lesen(0.5)
    for _ in range(50):                          # höchstens 5 Sekunden aufs Ende warten
        lesen(0.1)
        fertig, status = os.waitpid(pid, os.WNOHANG)
        if fertig:
            break
    else:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
        raise AssertionError("Das TUI hat sich nicht beenden lassen.")
    os.close(fd)
    code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else status
    return ausgabe.decode("utf-8", "replace"), code

if __name__ == "__main__":
    unittest.main()
