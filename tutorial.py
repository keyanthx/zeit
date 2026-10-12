# -*- coding: utf-8 -*-
"""
tutorial.py — die geführte Tour durch zeit (im TUI).

Erscheint beim ersten Start von `zeit` (solange es noch keine Projekte gibt)
und lässt sich jederzeit wieder starten: `zeit tutorial` oder im TUI unter
Einstellungen → Tutorial. Esc beendet es zu jedem Zeitpunkt.

Aufbau:
  1. Begrüßung
  2. Einrichtung: Projektordner, eigene Phasen, Menüleiste
  3. Vier Kapitel — jeweils Erklärseiten, dann eine Übung:
       Timer · Nachtragen · Countdown & Pomodoro · Kalender, Statistik, Datei
  4. Abschluss: Übungsprojekt entfernen oder behalten

Die Übungen benutzen die *echten* Bildschirme von zeit. Das Tutorial setzt nur
eine Hinweiszeile (tui.TUTORIAL), öffnet das echte Hauptmenü und prüft nach
jeder Aktion, ob das Ziel der Übung erreicht ist. Geübt wird mit einem eigenen
Projekt „beispiel“ in einem Übungsordner — deine echten Projekte bleiben unberührt.

Damit niemand 25 Minuten warten muss, „spult“ das Tutorial an zwei Stellen vor:
Es verschiebt die Startzeit des Übungs-Timers in die Vergangenheit.
"""

import curses
import os
import shutil
import subprocess
import textwrap
from datetime import timedelta
from pathlib import Path

import tui

UEBUNGSORDNER = Path.home() / "Library" / "Caches" / "zeit" / "tutorial" / "Beispiel"


class Beenden(Exception):
    """Wird geworfen, wenn du das Tutorial mit Esc beendest."""


def _zeit():
    return tui.zeit          # das zeit-Modul, das tui.starte() bekommen hat


# ===========================================================================
# Erklärseiten
# ===========================================================================

def _umbrechen(zeilen, breite):
    """Zeilen für den Bildschirm vorbereiten. Kennzeichen am Zeilenanfang:
       "$ "  ein Befehl (wird hervorgehoben, nicht umbrochen)
       "  "  vorformatiert (nicht umbrochen)
       "• "  Aufzählung (umbrochen, mit Einzug)
       "# "  Zwischenüberschrift
    Rückgabe: Liste von (text, art)."""
    ergebnis = []
    for z in zeilen:
        if z.startswith("$ "):
            ergebnis.append(("  " + z, "befehl"))
        elif z.startswith("  ") or not z:
            ergebnis.append((z, "normal"))
        elif z.startswith("# "):
            ergebnis.append((z[2:], "ueberschrift"))
        elif z.startswith("• "):
            teile = textwrap.wrap(z[2:], breite - 2) or [""]
            ergebnis.append(("• " + teile[0], "normal"))
            ergebnis += [("  " + t, "normal") for t in teile[1:]]
        else:
            ergebnis += [(t, "normal") for t in textwrap.wrap(z, breite) or [""]]
    return ergebnis


def seite(fenster, titel, zeilen, fortschritt="", weiter="→/⏎ weiter"):
    """Eine Erklärseite. Rückgabe: "weiter" oder "zurueck". Esc fragt, ob das
    Tutorial beendet werden soll (dann wird Beenden geworfen)."""
    oben = 0
    while True:
        hoehe, breite = fenster.getmaxyx()
        textbreite = max(30, min(76, breite - 6))
        inhalt = _umbrechen(zeilen, textbreite)
        platz = max(1, hoehe - 5)
        oben = max(0, min(oben, len(inhalt) - platz))
        fenster.erase()
        tui._schreibe(fenster, 0, 2, titel, curses.color_pair(tui.FARBE_TITEL) | curses.A_BOLD)
        if fortschritt:
            tui._schreibe(fenster, 0, max(2, breite - len(fortschritt) - 2), fortschritt, curses.A_DIM)
        for i, (text, art) in enumerate(inhalt[oben:oben + platz]):
            attr = {"befehl": curses.color_pair(tui.FARBE_TITEL),
                    "ueberschrift": curses.A_BOLD}.get(art, 0)
            tui._schreibe(fenster, 2 + i, 3, text, attr)
        mehr = " · ↑↓ blättern" if len(inhalt) > platz else ""
        tui._schreibe(fenster, hoehe - 1, 2, f"{weiter} · ← zurück{mehr} · Esc Tutorial beenden",
                      curses.A_DIM)
        tui._auffrischen(fenster)
        t = tui._taste(fenster)
        if tui._ist_enter(t) or t == curses.KEY_RIGHT or t == " ":
            return "weiter"
        if t == curses.KEY_LEFT:
            return "zurueck"
        if t == curses.KEY_DOWN:
            oben += 1
        elif t == curses.KEY_UP:
            oben -= 1
        elif tui._ist_escape(t) or t == "q":
            _beenden_fragen(fenster)


def seiten(fenster, titel, liste, kapitel=""):
    """Mehrere Erklärseiten hintereinander; ← blättert zurück."""
    i = 0
    while i < len(liste):
        fortschritt = f"{kapitel}  {i + 1}/{len(liste)}" if len(liste) > 1 else kapitel
        if seite(fenster, titel, liste[i], fortschritt) == "zurueck":
            i = max(0, i - 1)
        else:
            i += 1


def _beenden_fragen(fenster):
    if tui.frage_ja_nein(fenster, ["Tutorial beenden?", "",
                                   "Du kannst es jederzeit wieder starten:",
                                   "Einstellungen → Tutorial  oder  zeit tutorial"], standard=False):
        raise Beenden


# ===========================================================================
# Übungen
# ===========================================================================

def uebung(fenster, hinweis, ziel):
    """Öffnet das echte Hauptmenü mit einer Hinweiszeile und wartet, bis
    ziel() wahr ist. Verlässt du das Menü vorher, kannst du es nochmal
    versuchen, die Übung überspringen oder das Tutorial beenden.
    Rückgabe: True = geschafft, False = übersprungen."""
    while True:
        tui.TUTORIAL = {"hinweis": hinweis, "ziel": ziel, "zuletzt": None}
        try:
            tui._hauptmenue(fenster)
        finally:
            erreicht = ziel()
            tui.TUTORIAL = None
        if erreicht:
            return True
        art, idx = tui.waehle(fenster, "Übung noch nicht geschafft",
                              [(z, curses.A_DIM) for z in ["Die Aufgabe war:"] + ["   " + h for h in hinweis]],
                              [("Nochmal versuchen", 0), ("Übung überspringen", 0),
                               ("Tutorial beenden", 0)], "↑↓ wählen · ⏎ weiter")
        if art == "wahl" and idx == 1:
            return False
        if art == "wahl" and idx == 2:
            raise Beenden


# ===========================================================================
# Das Übungsprojekt
# ===========================================================================

class Uebung:
    """Alles rund um das Übungsprojekt: anlegen, Zustand prüfen, vorspulen, aufräumen."""

    def __init__(self):
        zeit = _zeit()
        projekte, phasen = zeit.lade_config()
        self.name = "beispiel" if "beispiel" not in projekte else "beispiel-tutorial"
        self.phase1 = phasen[0]
        self.phase2 = phasen[1] if len(phasen) > 1 else phasen[0]
        self.alte_pomodoro = None

    # --- anlegen / aufräumen ---------------------------------------------
    def anlegen(self):
        zeit = _zeit()
        if UEBUNGSORDNER.exists():
            shutil.rmtree(UEBUNGSORDNER)
        UEBUNGSORDNER.mkdir(parents=True)
        projekte, phasen = zeit.lade_config()
        projekte[self.name] = UEBUNGSORDNER
        zeit.speichere_config(projekte, phasen)

    def aufraeumen(self, behalten_in=None):
        """Laufendes verwerfen, Pomodoro-Werte zurück; dann das Projekt entfernen
        oder (behalten_in) samt Datei in diesen Ordner umziehen."""
        zeit = _zeit()
        self.pomodoro_zurueck()
        projekte, phasen = zeit.lade_config()
        if self.name not in projekte:
            return
        datei = self.datei()
        if datei and (datei.laeuft or datei.sitzung):
            datei.laeuft = datei.sitzung = None
            zeit.schreibe_zeitdatei(zeit.zeitdatei_pfad(projekte[self.name]), datei)
        if behalten_in:
            behalten_in.mkdir(parents=True, exist_ok=True)
            quelle = zeit.zeitdatei_pfad(UEBUNGSORDNER)
            if quelle.exists():
                shutil.move(str(quelle), str(zeit.zeitdatei_pfad(behalten_in)))
            projekte[self.name] = behalten_in
        else:
            del projekte[self.name]
        zeit.speichere_config(projekte, phasen)
        shutil.rmtree(UEBUNGSORDNER.parent, ignore_errors=True)
        # Schreibt zeit in den Kalender, verschwinden die Übungseinträge dort auch
        import kalender_schreiben
        if kalender_schreiben.ist_an():
            kalender_schreiben.anstossen()

    # --- Zustand -------------------------------------------------------------
    def datei(self):
        zeit = _zeit()
        pfad = zeit.zeitdatei_pfad(UEBUNGSORDNER)
        return zeit.lese_zeitdatei(pfad, UEBUNGSORDNER.name) if pfad.exists() else None

    def schreiben(self, datei):
        _zeit().schreibe_zeitdatei(_zeit().zeitdatei_pfad(UEBUNGSORDNER), datei)

    def laeuft_timer(self):
        d = self.datei()
        return bool(d and d.laeuft and not d.sitzung)

    def angehalten(self):
        d = self.datei()
        return bool(d and d.sitzung and d.sitzung["zustand"] == "angehalten")

    def eintraege(self, art=None):
        d = self.datei()
        return [e for e in (d.eintraege if d else []) if art is None or e[5] == art]

    def nichts_laeuft(self):
        d = self.datei()
        return not (d and (d.laeuft or d.sitzung))

    # --- vorspulen -------------------------------------------------------------
    def vorspulen(self, minuten):
        """Den laufenden Übungs-Timer so verschieben, als liefe er schon `minuten`."""
        d = self.datei()
        phase, _ = d.laeuft
        d.laeuft = (phase, _zeit()._jetzt() - timedelta(minutes=minuten))
        self.schreiben(d)

    def angehalten_vorspulen(self, minuten):
        """Nach dem Anhalten: den eingetragenen Abschnitt und den Beginn der
        Unterbrechung `minuten` früher legen — als wäre die Pause schon so lang."""
        zeit = _zeit()
        d = self.datei()
        zeile = d.eintraege[-1]
        start, ende = zeit._zeitraum_aus(zeile)
        neu = zeit._eintragszeile(start - timedelta(minutes=minuten),
                                  ende - timedelta(minutes=minuten), zeile[4], zeile[5])
        d.eintraege[-1] = neu[:6] + zeile[6:]
        d.sitzung["seit"] -= timedelta(minutes=minuten)
        self.schreiben(d)

    # --- Pomodoro-Übungswerte (1 Minute) -----------------------------------
    def pomodoro_kurz(self):
        zeit = _zeit()
        e = zeit.lade_einstellungen()
        schluessel = ("pomodoro-fokus", "pomodoro-kurze-pause", "pomodoro-lange-pause",
                      "pomodoro-lange-pause-nach")
        self.alte_pomodoro = {k: e[k] for k in schluessel}
        e.update({"pomodoro-fokus": 1, "pomodoro-kurze-pause": 1, "pomodoro-lange-pause": 1,
                  "pomodoro-lange-pause-nach": 2})
        zeit.speichere_einstellungen(e)

    def pomodoro_zurueck(self):
        if self.alte_pomodoro:
            zeit = _zeit()
            e = zeit.lade_einstellungen()
            e.update(self.alte_pomodoro)
            zeit.speichere_einstellungen(e)
            self.alte_pomodoro = None


# ===========================================================================
# 1. Begrüßung
# ===========================================================================

def begruessung(fenster):
    seiten(fenster, "Willkommen bei zeit", [[
        "zeit misst, wie lange du an deinen Projekten arbeitest — und schreibt alles in "
        "ganz normale Markdown-Dateien, die du jederzeit lesen und von Hand ändern kannst. "
        "Keine Datenbank, kein Konto, keine Cloud.",
        "",
        "# So ist zeit aufgebaut",
        "• Ein Projekt ist ein Ordner auf deinem Mac. Darin legt zeit die Datei "
        "Zeiterfassung.md an.",
        "• Eine Phase sagt, woran du gerade arbeitest, z. B. planung oder umsetzung. "
        "So siehst du später, wie lange welcher Teil eines Projekts gedauert hat.",
        "• Ein Eintrag ist eine Zeile in der Tabelle: Datum, Start, Ende, Dauer, Phase.",
        "",
        "# Was dich erwartet (etwa 10 Minuten)",
        "  1. Einrichten: Projektordner, Phasen, Menüleiste",
        "  2. Timer starten, anhalten, stoppen",
        "  3. Zeit nachtragen",
        "  4. Countdown und Pomodoro",
        "  5. Kalender, Statistik und die Datei selbst",
        "",
        "Zu jedem Thema gibt es eine kurze Erklärung und dann eine Übung mit den echten "
        "Bildschirmen. Geübt wird mit einem Übungsprojekt, das am Ende wieder verschwindet.",
        "",
        "Bedienung überall: ↑↓ wählen · → oder ⏎ weiter · ← zurück · Esc beendet das "
        "Tutorial jederzeit.",
    ]])


# ===========================================================================
# 2. Einrichtung
# ===========================================================================

def einrichten_projektordner(fenster):
    zeit = _zeit()
    seite(fenster, "Einrichten — Projektordner", [
        "Wenn du ein neues Projekt anlegst, schlägt zeit einen Ordner dafür vor. "
        "Gibt es im Projektordner schon einen Ordner mit passendem Namen, nimmt zeit "
        "den; sonst legt es dort einen neuen an.",
        "",
        "Projekte dürfen trotzdem überall liegen — das ist nur der Vorschlag.",
        "",
        f"Gerade eingestellt: {zeit.lade_einstellungen()['projektordner']}",
        "",
        "Auf der nächsten Seite kannst du ihn ändern (⏎ übernimmt den Vorschlag).",
    ], "Einrichten 1/3")
    while True:
        e = zeit.lade_einstellungen()
        text = tui.frage_text(fenster, ["In welchem Ordner liegen deine Projekte?",
                                        "(z. B. ~/Documents/Projekte)"], e["projektordner"])
        if not text:
            return
        ordner = Path(text).expanduser()
        if not ordner.is_dir():
            if not tui.frage_ja_nein(fenster, [str(ordner), "", "Diesen Ordner gibt es noch nicht. Anlegen?"]):
                continue
            ordner.mkdir(parents=True)
        e["projektordner"] = text
        zeit.speichere_einstellungen(e)
        return


def einrichten_phasen(fenster):
    zeit = _zeit()
    seite(fenster, "Einrichten — Phasen", [
        "Phasen teilen ein Projekt in Abschnitte. Welche du brauchst, hängt von deiner "
        "Arbeit ab, zum Beispiel:",
        "",
        "  Webdesign:   anfrage · angebot · design · umsetzung · launch",
        "  Studium:     recherche · schreiben · korrektur",
        "  Allgemein:   planung · umsetzung · abstimmung",
        "",
        "Zum Start gibt es die drei allgemeinen. Auf der nächsten Seite kannst du eigene "
        "hinzufügen und nicht benötigte entfernen. Später geht das jederzeit wieder: "
        "beim Starten eines Timers mit „+ neue Phase anlegen …“ oder in der Übersicht.",
    ], "Einrichten 2/3")
    pos = 0
    while True:
        projekte, phasen = zeit.lade_config()
        eintraege = [("✓ So lassen und weiter", curses.A_BOLD), ("+ Phase hinzufügen …", 0)]
        eintraege += [(f"   {p}", 0) for p in phasen]
        art, idx = tui.waehle(fenster, "Einrichten — deine Phasen",
                              [("Wähle eine Phase, um sie zu entfernen.", curses.A_DIM)],
                              eintraege, "↑↓ wählen · ⏎ ausführen · Esc Tutorial beenden",
                              start=pos, links_zurueck=False)
        if art != "wahl":
            _beenden_fragen(fenster)
            continue
        pos = idx
        if idx == 0:
            return
        if idx == 1:
            name = tui.frage_text(fenster, ["Wie heißt die neue Phase?"])
            kurz = zeit.slug(name or "")
            if kurz and kurz not in phasen:
                phasen.append(kurz)
                zeit.speichere_config(projekte, phasen)
            continue
        phase = phasen[idx - 2]
        if len(phasen) == 1:
            tui.meldung(fenster, ["Eine Phase muss mindestens bleiben."])
        elif tui.frage_ja_nein(fenster, [f"Phase „{phase}“ entfernen?"], standard=False):
            phasen.remove(phase)
            zeit.speichere_config(projekte, phasen)
            pos = min(pos, len(phasen) + 1)


def _swiftbar():
    """(installiert?, Plugin-Ordner oder None, Plugin verbunden?)"""
    installiert = any(Path(p).is_dir() for p in ("/Applications/SwiftBar.app",
                                                 str(Path.home() / "Applications/SwiftBar.app")))
    # ZEIT_SWIFTBAR_PLUGINS: anderer Plugin-Ordner (nur für Tests, wie in install.sh)
    ordner = os.environ.get("ZEIT_SWIFTBAR_PLUGINS") or subprocess.run(
        ["defaults", "read", "com.ameba.SwiftBar", "PluginDirectory"],
        capture_output=True, text=True).stdout.strip()
    ordner = Path(ordner).expanduser() if ordner else None
    plugin = Path(__file__).resolve().parent / "swiftbar" / "zeit.15s.py"
    verbunden = bool(ordner and ordner.is_dir() and (
        ordner.resolve() == plugin.parent or (ordner / plugin.name).resolve() == plugin))
    return installiert, ordner if ordner and ordner.is_dir() else None, verbunden


def einrichten_menueleiste(fenster):
    zeit = _zeit()
    installiert, ordner, verbunden = _swiftbar()
    plugin = Path(__file__).resolve().parent / "swiftbar" / "zeit.15s.py"
    text = [
        "zeit kann oben in der Menüleiste anzeigen, was gerade läuft (z. B. ▶ planung 0:42), "
        "und von dort gestartet und gestoppt werden. Dafür braucht es die kostenlose App "
        "SwiftBar.",
        "",
    ]
    if not installiert:
        seite(fenster, "Einrichten — Menüleiste", text + [
            "# SwiftBar ist noch nicht installiert",
            "Das ist optional — zeit funktioniert auch ohne. Wenn du die Menüleiste "
            "möchtest, später im Terminal:",
            "",
            "$ brew install --cask swiftbar",
            "",
            "(oder von swiftbar.app laden). SwiftBar einmal öffnen, einen Plugin-Ordner "
            "wählen und dann das Install-Skript von zeit erneut ausführen — es verbindet "
            "alles.",
        ], "Einrichten 3/3")
        return
    if not ordner:
        seite(fenster, "Einrichten — Menüleiste", text + [
            "# SwiftBar ist installiert, aber noch nicht eingerichtet",
            "Öffne SwiftBar einmal und wähle einen Plugin-Ordner (z. B. ~/SwiftBar). "
            "Danach das Install-Skript von zeit erneut ausführen — oder dieses Tutorial "
            "noch einmal starten.",
        ], "Einrichten 3/3")
        return
    if not verbunden:
        seite(fenster, "Einrichten — Menüleiste", text + [
            f"SwiftBar ist da (Plugin-Ordner: {ordner}), zeit ist aber noch nicht "
            "verbunden. Auf der nächsten Seite kannst du das gleich erledigen.",
        ], "Einrichten 3/3")
        if tui.frage_ja_nein(fenster, ["zeit jetzt mit SwiftBar verbinden?", "",
                                       f"Es entsteht eine Verknüpfung in {ordner}."]):
            ziel = ordner / plugin.name
            if ziel.exists() and not ziel.is_symlink():
                tui.meldung(fenster, ["Dort liegt schon eine eigene zeit.15s.py —",
                                      "die wird nicht überschrieben."])
                return
            if ziel.is_symlink():
                ziel.unlink()
            ziel.symlink_to(plugin)
            subprocess.run(["open", "-g", "swiftbar://refreshallplugins"], capture_output=True)
            verbunden = True
        else:
            return
    # Verbunden: wie soll sich ein Klick aufs Symbol verhalten?
    seite(fenster, "Einrichten — Menüleiste", text + [
        "✓ zeit ist mit SwiftBar verbunden — oben rechts steht jetzt ⏱.",
        "",
        "Was soll ein Klick auf das Symbol öffnen?",
        "• Klappmenü — eine Liste wie in jeder Menüleisten-App",
        "• Popup — ein kleines Fenster unter dem Symbol, darin das TUI oder eine "
        "grafische Oberfläche (GUI)",
        "• Terminalfenster — öffnet direkt das TUI",
    ], "Einrichten 3/3")
    e = zeit.lade_einstellungen()
    arten = list(zeit.KLICK_ARTEN)
    art, idx = tui.waehle(fenster, "Klick auf das Menüleisten-Symbol", [],
                          [(zeit.KLICK_ARTEN[a], 0) for a in arten], "↑↓ wählen · ⏎ übernehmen",
                          start=arten.index(e["menueleiste-klick"]) if e["menueleiste-klick"] in arten else 0)
    if art == "wahl":
        e["menueleiste-klick"] = arten[idx]
    if e["menueleiste-klick"] == "popup":
        anzeigen = list(zeit.ANZEIGEN)
        art, idx = tui.waehle(fenster, "Was soll das Popup zeigen?", [],
                              [(zeit.ANZEIGEN[a], 0) for a in anzeigen], "↑↓ wählen · ⏎ übernehmen",
                              start=anzeigen.index(e["anzeige"]) if e["anzeige"] in anzeigen else 0)
        if art == "wahl":
            e["anzeige"] = anzeigen[idx]
    zeit.speichere_einstellungen(e)
    subprocess.run(["open", "-g", "swiftbar://refreshallplugins"], capture_output=True)


# ===========================================================================
# 3. Die Kapitel
# ===========================================================================

def kapitel_timer(fenster, u):
    k = "Kapitel 1/4"
    seiten(fenster, "Timer: starten, anhalten, stoppen", [[
        "Der Timer ist das Herz von zeit: Du startest ihn, wenn du mit einer Arbeit "
        "anfängst, und stoppst ihn, wenn du fertig bist. Beim Stoppen schreibt zeit "
        "eine Zeile in die Zeiterfassung.md des Projekts.",
        "",
        "# Gut zu wissen",
        "• Es läuft immer nur ein Timer. Startest du einen neuen, bietet zeit an, den "
        "alten zu beenden — so wird keine Stunde doppelt gezählt.",
        "• Unter einer Minute wird nichts eingetragen (meist nur ein Vertipper).",
        "• Anhalten: Die Zeit bis jetzt wird eingetragen, danach läuft nichts. "
        "Fortsetzen macht weiter — beim Stoppen siehst du alles zusammen.",
        "• Vergessen zu stoppen? zeit warnt nach acht Stunden oder über Nacht und "
        "lässt dich die Endzeit korrigieren.",
        "",
        "Im Terminal geht das auch ohne Oberfläche:",
        f"$ zeit start {u.name} {u.phase1}",
        "$ zeit stop",
    ], [
        "# Übung",
        f"Für die Übungen gibt es jetzt ein Projekt „{u.name}“.",
        "",
        "Gleich siehst du das echte Hauptmenü. Unten steht in einer farbigen Zeile, "
        "was zu tun ist. Ist die Aufgabe erledigt, geht es hier automatisch weiter.",
        "",
        f"Aufgabe: Starte einen Timer für das Projekt „{u.name}“ und die Phase „{u.phase1}“.",
    ]], k)
    if not uebung(fenster, ["Wähle „Timer starten“, dann das Projekt " f"„{u.name}“ und die Phase „{u.phase1}“."],
                  u.laeuft_timer):
        return
    zeile = next(iter(_laeuft_zeilen(u)), "")
    u.vorspulen(45)
    seite(fenster, "Der Timer läuft", [
        "Gut gemacht! In der Datei des Projekts steht jetzt unter „Läuft gerade“:",
        "",
        f"  {zeile.strip() or '- **' + u.phase1 + '** — gestartet …'}",
        "",
        "Deshalb weiß zeit auch nach einem Neustart des Macs, was läuft.",
        "",
        "Damit du nicht warten musst, spulen wir vor: Wir tun so, als liefe der Timer "
        "schon 45 Minuten.",
        "",
        "Aufgabe: Halte den Timer jetzt an.",
    ], k)
    if not uebung(fenster, ["Wähle „Timer anhalten“."], u.angehalten):
        return
    u.angehalten_vorspulen(40)
    seite(fenster, "Angehalten", [
        "Die 45 Minuten bis zum Anhalten sind schon eingetragen — mit ⏸ in der Spalte "
        "„Art“, damit man sieht, dass es danach weiterging.",
        "",
        "Wieder vorgespult: Die Pause dauert jetzt schon 40 Minuten. (Nach 15 Minuten "
        "Anhalten erinnert dich zeit übrigens mit einer Mitteilung.)",
        "",
        "Aufgabe: Setze den Timer fort.",
    ], k)
    if not uebung(fenster, ["Wähle „Timer fortsetzen“."], u.laeuft_timer):
        return
    u.vorspulen(25)
    seite(fenster, "Weiter geht's", [
        "Der Timer läuft wieder — vorgespult auf 25 Minuten.",
        "",
        "Aufgabe: Beende den Timer. Danach zeigt zeit einen Bericht, was erfasst wurde, "
        "und fragt (freiwillig), wie fokussiert du warst. Probier es ruhig aus — die "
        "Antwort landet in der Spalte „Fokus“, eine Notiz in „Notiz“.",
    ], k)
    if not uebung(fenster, ["Wähle „Timer beenden“ und schau dir den Bericht an."],
                  lambda: u.nichts_laeuft() and len(u.eintraege()) >= 2):
        return
    seite(fenster, "Geschafft", [
        "Im Bericht stand: zwei Abschnitte (45 + 25 Minuten), dazwischen 40 Minuten "
        "Unterbrechung, die nicht erfasst wurden.",
        "",
        "Fehlt dir der Bericht später einmal: Unter „Kalender“ siehst du jeden Tag mit "
        "allen Einträgen.",
    ], k)


def _laeuft_zeilen(u):
    """Die Zeile unter „Läuft gerade“ aus der echten Datei."""
    text = _zeit().zeitdatei_pfad(UEBUNGSORDNER).read_text(encoding="utf-8")
    return [z for z in text.splitlines() if z.startswith("- **")]


def kapitel_nachtragen(fenster, u):
    k = "Kapitel 2/4"
    seiten(fenster, "Zeit nachtragen", [[
        "Den Timer vergessen? Kein Problem: Zeit lässt sich jederzeit nachtragen. "
        "Nachgetragene Einträge bekommen ✎ in der Spalte „Art“.",
        "",
        "# Im Formular",
        "Datum, Von und Bis — mit ↑↓ stellst du Uhrzeiten in 15-Minuten-Schritten ein. "
        "„Nur Tag“ trägt eine Dauer ohne Uhrzeiten ein, z. B. „3 Stunden am Dienstag“.",
        "",
        "# Im Terminal versteht zeit auch freie Eingaben",
        f"$ zeit nachtragen {u.name} {u.phase2} gestern 9:00-11:30",
        f"$ zeit nachtragen {u.name} {u.phase2} 2h ab 14:00",
        f"$ zeit nachtragen {u.name} {u.phase2} montag 3h",
        "",
        "Überschneidet sich ein Nachtrag mit einem vorhandenen Eintrag, fragt zeit "
        "nach — so zählt keine Stunde doppelt.",
    ], [
        "# Übung",
        f"Aufgabe: Trage für „{u.name}“ / „{u.phase2}“ gestern von 9:00 bis 10:30 nach.",
        "",
        "Tipp: Im Formular wechselst du mit ↑↓ zwischen den Feldern und änderst Werte "
        "mit ← →; unten steht, welche Tasten gelten.",
    ]], k)
    if not uebung(fenster, ["Wähle „Zeit nachtragen“, Projekt " f"„{u.name}“, Phase „{u.phase2}“,",
                            "und trage gestern 9:00–10:30 ein (andere Zeiten gehen auch)."],
                  lambda: bool(u.eintraege(_zeit().ART_NACHTRAG))):
        return
    seite(fenster, "Nachgetragen", [
        "Der Eintrag steht in der Datei — chronologisch einsortiert, nicht einfach "
        "unten angehängt. So bleibt die Tabelle lesbar.",
    ], k)


def kapitel_pomodoro(fenster, u):
    k = "Kapitel 3/4"
    seiten(fenster, "Countdown und Pomodoro", [[
        "# Countdown",
        "Ein Timer mit festem Ende: „2 Stunden“ oder „bis 17:00“. Ist die Zeit um, "
        "meldet sich zeit mit Ton und Mitteilung — du entscheidest dann: beenden oder "
        "noch ein paar Minuten dranhängen.",
        "",
        "# Pomodoro",
        "Arbeiten in Blöcken: z. B. 25 Minuten Fokus, 5 Minuten Pause, nach vier "
        "Blöcken eine lange Pause. Die Längen stellst du bei jedem Start ein.",
        "• Erfasst werden nur die Fokus-Blöcke (🍅 in der Spalte „Art“), Pausen nicht.",
        "• Jeder Wechsel passiert auf Klick bzw. Taste — zeit wechselt nie von selbst. "
        "Es meldet sich nur, wenn die Zeit um ist (und erinnert, falls du nicht reagierst).",
        "• Nach jedem Fokus-Block kannst du kurz sagen, wie fokussiert du warst.",
        "",
        "Countdown und Pomodoro lassen sich anhalten und fortsetzen wie der Timer.",
    ], [
        "# Übung (dauert gut eine Minute)",
        "Für die Übung sind Fokus und Pausen schon auf 1 Minute gestellt — die Werte "
        "im Formular also einfach mit ⏎ bestätigen.",
        "",
        "1. Starte einen Pomodoro.",
        "2. Du siehst die Live-Ansicht. Warte, bis die Minute um ist — es kommt eine "
        "Mitteilung (vielleicht auch ein Dialog: den kannst du benutzen oder ignorieren).",
        "3. Drücke p für die Pause. Der Fokus-Block wird eingetragen.",
        "4. Drücke s, um die Sitzung zu beenden.",
        "",
        "Danach stellt das Tutorial deine eigenen Pomodoro-Werte wieder her.",
    ]], k)
    u.pomodoro_kurz()
    try:
        geschafft = uebung(fenster, [f"„Pomodoro starten“ → {u.name} / {u.phase1}, Werte bestätigen.",
                                     "Nach 1 Minute: p (Pause), dann s (beenden)."],
                           lambda: u.nichts_laeuft() and bool(u.eintraege(_zeit().ART_POMODORO)))
    finally:
        u.pomodoro_zurueck()
    if geschafft:
        seite(fenster, "Dein erster Pomodoro", [
            "Der Fokus-Block steht mit 🍅 in der Datei. Die Pause nicht — sie zählt "
            "nicht als Arbeitszeit.",
            "",
            "In der Statistik siehst du später, wie viele Pomodoros du pro Tag schaffst.",
        ], k)


def kapitel_ueberblick(fenster, u):
    k = "Kapitel 4/4"
    seite(fenster, "Kalender, Statistik und die Datei", [
        "# Kalender",
        "Tag für Tag (oder als Woche) siehst du, wann du woran gearbeitet hast — als "
        "farbige Blöcke. Termine aus deinem macOS-Kalender kannst du dort übernehmen "
        "(Einstellungen → Kalender).",
        "",
        "# Statistik",
        "Summen pro Woche, Monat, Jahr: welche Projekte, welche Phasen, zu welcher "
        "Tageszeit, wie fokussiert.",
        "",
        "# Übung",
        "Aufgabe: Öffne den Kalender und schau dir deine Übungseinträge an. Mit w "
        "wechselst du zur Woche, mit ← → blätterst du. Esc führt zurück.",
    ], k)
    if not uebung(fenster, ["Wähle „Kalender“, schau dich um, dann Esc."],
                  lambda: tui.TUTORIAL is not None and tui.TUTORIAL.get("zuletzt") == "bildschirm_kalender"):
        return
    pfad = _zeit().zeitdatei_pfad(UEBUNGSORDNER)
    inhalt = pfad.read_text(encoding="utf-8").splitlines() if pfad.exists() else []
    seite(fenster, "Die Datei selbst", [
        "Alles, was zeit weiß, steht in einer ganz normalen Markdown-Datei. So sieht "
        "die deines Übungsprojekts gerade aus:",
        "",
    ] + ["  " + z for z in inhalt] + [
        "",
        "Du darfst sie von Hand bearbeiten. Drei Regeln:",
        "• Die Zeile <!-- zeit-format: … --> muss bleiben — ohne sie fasst zeit die "
        "Datei nicht an.",
        "• Unter „Läuft gerade“ steht, was gerade läuft.",
        "• Alles nach <!-- zeit-ende --> gehört dir: eigene Notizen bleiben unberührt.",
        "",
        "Deine Projektliste und Einstellungen stehen genauso lesbar in "
        "~/.config/zeit/projekte.md.",
    ], k)


# ===========================================================================
# 4. Abschluss
# ===========================================================================

def abschluss(fenster, u):
    zeit = _zeit()
    seite(fenster, "Fertig!", [
        "Du kennst jetzt alles Wichtige. Noch ein paar Tipps:",
        "",
        "• Im Hauptmenü unter „Übersicht“ verwaltest du Projekte und Phasen "
        "(umbenennen, Ordner wechseln, Reihenfolge).",
        "• Unter „Einstellungen“: Töne, Kalender, Farben, Menüleiste.",
        "• Alle Befehle fürs Terminal:",
        "$ zeit --help",
        "• Dieses Tutorial noch einmal:",
        "$ zeit tutorial",
        "",
        "Zum Schluss: Was soll mit dem Übungsprojekt passieren?",
    ], "", weiter="→/⏎ weiter")
    art, idx = tui.waehle(fenster, f"Übungsprojekt „{u.name}“", [],
                          [("Entfernen (empfohlen)", 0), ("Behalten", 0)],
                          "↑↓ wählen · ⏎ übernehmen", links_zurueck=False)
    if art == "wahl" and idx == 1:
        ziel = zeit.projekt_suchordner() / "Beispiel (zeit)"
        u.aufraeumen(behalten_in=ziel)
        tui.meldung(fenster, [f"Behalten: {u.name}", f"liegt jetzt in {ziel}"])
    else:
        u.aufraeumen()


# ===========================================================================
# Einstieg
# ===========================================================================

def starten(fenster):
    """Das ganze Tutorial. Endet immer aufgeräumt — auch bei Esc oder Fehlern."""
    zeit = _zeit()
    projekte, _ = zeit.lade_config()
    if zeit.finde_aktiv(projekte, warner=lambda _: None):
        tui.meldung(fenster, ["Gerade läuft ein Timer oder eine Sitzung.",
                              "Bitte zuerst beenden — dann das Tutorial starten",
                              "(Einstellungen → Tutorial oder zeit tutorial)."])
        return
    u = None
    try:
        begruessung(fenster)
        einrichten_projektordner(fenster)
        einrichten_phasen(fenster)
        einrichten_menueleiste(fenster)
        u = Uebung()
        u.anlegen()
        kapitel_timer(fenster, u)
        kapitel_nachtragen(fenster, u)
        kapitel_pomodoro(fenster, u)
        kapitel_ueberblick(fenster, u)
        abschluss(fenster, u)
    except Beenden:
        if u:
            u.aufraeumen()
    except Exception:
        if u:
            u.aufraeumen()
        raise
    finally:
        tui.TUTORIAL = None
        e = zeit.lade_einstellungen()
        if e["tutorial"] != "fertig":
            e["tutorial"] = "fertig"
            zeit.speichere_einstellungen(e)
