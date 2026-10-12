#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webterm.py — der lokale Dienst für das Popup unter dem Menüleisten-Symbol
(und das Fenster): zeigt entweder das TUI oder die GUI (Einstellung „Anzeige“).

GUI: Die Seite (web/gui.html) fragt über /api den Dienst, der gui_api.py
aufruft. Der Rest dieser Beschreibung gilt dem TUI:

SwiftBar kann beim Klick aufs Symbol eine Webseite als Popup zeigen. Damit
darin das echte TUI läuft, braucht es zwei Teile:

  1. xterm.js (in ~/zeit/web/, MIT-Lizenz) — ein Terminal-Emulator, der im
     Browser läuft; dieselbe Technik steckt im Terminal von VS Code.
  2. Dieser kleine Dienst: Er startet `zeit` in einem Pseudo-Terminal (pty)
     und reicht Tastendrücke und Bildschirmausgabe per WebSocket zwischen
     xterm.js und dem TUI hin und her.

Sicherheit: Der Dienst lauscht nur auf 127.0.0.1 (von außen unerreichbar)
und verlangt ein zufälliges Kennwort in der Adresse — sonst könnte jede
Webseite in deinem Browser versuchen, sich mit dem lokalen zeit zu verbinden.
Kennwort und Port stehen in ~/Library/Caches/zeit/webterm.json.

Nur Python-Standardbibliothek; WebSocket ist hier von Hand umgesetzt (RFC 6455,
nur das, was gebraucht wird).

Aufruf:  webterm.py sicherstellen   (startet den Dienst, falls er nicht läuft)
         webterm.py dienst          (der Dienst selbst — läuft im Hintergrund)
         webterm.py fenster         (TUI als normales Fenster öffnen)
"""

import base64
import fcntl
import hashlib
import http.server
import json
import os
import pty
import secrets
import select
import signal
import socket
import struct
import subprocess
import sys
import termios
import threading
import urllib.parse
from pathlib import Path

import farbschemata

ORDNER = Path(__file__).resolve().parent
WEB = ORDNER / "web"
ZUSTAND = Path.home() / "Library" / "Caches" / "zeit" / "webterm.json"
PORT = int(os.environ.get("ZEIT_PORT", 47816))   # anderer Port nur für Tests


# ===========================================================================
# Zustand: Port, Kennwort, Prozessnummer
# ===========================================================================

def zustand():
    try:
        return json.loads(ZUSTAND.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def adresse(fenster=False):
    """Die Adresse fürs Popup (bzw. Fenster) — mit Kennwort."""
    z = zustand() or {}
    return (f"http://127.0.0.1:{z.get('port', PORT)}/?t={z.get('kennwort', '')}"
            + ("&fenster=1" if fenster else ""))


POPUP = ZUSTAND.with_name("popup.html")


def seite_fuer(popup):
    """Die Seite mit eingesetzten Platzhaltern (Kennwort, Port, Leiste, Farben).

    Das Popup bekommt das eingestellte Farbschema, das abgelöste Fenster
    („⧉ Als Fenster öffnen“) behält das dunkle Standard-Aussehen.
    """
    z = zustand() or {}
    return (SEITE.replace("__LEISTE__", "flex" if popup else "none")
            .replace("__OBEN__", "30" if popup else "4")
            .replace("__KENNWORT__", z.get("kennwort", "")).replace("__PORT__", str(z.get("port", PORT)))
            .replace("__POPUP__", "true" if popup else "false")
            .replace("__THEMA__", json.dumps(aktuelles_thema() if popup else farbschemata.xterm_thema("Standard"))))


def gui_seite(fenster, eingebaut):
    """Die GUI-Seite mit eingesetzten Platzhaltern.
    eingebaut=True: gui.css und gui.js direkt in der Seite (für die Popup-Datei)."""
    z = zustand() or {}
    seite = ((WEB / "gui.html").read_text(encoding="utf-8")
             .replace("__KENNWORT__", z.get("kennwort", "")).replace("__PORT__", str(z.get("port", PORT)))
             .replace("__FENSTER__", "true" if fenster else "false"))
    if eingebaut:
        seite = seite.replace('<link rel="stylesheet" href="/web/gui.css">',
                              "<style>" + (WEB / "gui.css").read_text(encoding="utf-8") + "</style>")
        seite = seite.replace('<script src="/web/gui.js"></script>',
                              "<script>" + (WEB / "gui.js").read_text(encoding="utf-8") + "</script>")
    return seite


def anzeige():
    import zeit
    return zeit.lade_einstellungen()["anzeige"]


def aktuelles_thema():
    """Das eingestellte Farbschema als xterm.js-Thema."""
    import zeit
    return farbschemata.xterm_thema(zeit.lade_einstellungen()["farbschema"])


def popup_datei():
    """Schreibt die Popup-Seite als lokale Datei und gibt ihre file://-Adresse zurück.

    Warum eine Datei? SwiftBar zeigt im Popup Seiten über http:// nicht an (sie
    laden, bleiben aber leer) — lokale Dateien dagegen schon. Die Seite verbindet
    sich dann selbst per WebSocket mit dem Dienst. xterm.js steht direkt mit in
    der Datei, weil unklar ist, ob SwiftBar einer lokalen Seite das Nachladen
    weiterer Dateien erlaubt. Weil das Kennwort darin steht, ist die Datei nur
    für dich lesbar.
    """
    if anzeige() == "gui":
        return _datei_schreiben(POPUP.with_name("gui-popup.html"), gui_seite(fenster=False, eingebaut=True))
    seite = seite_fuer(popup=True).replace('<link rel="stylesheet" href="/web/xterm.css">',
                          "<style>" + (WEB / "xterm.css").read_text(encoding="utf-8") + "</style>")
    seite = seite.replace('<script src="/web/xterm.js"></script><script src="/web/addon-fit.js"></script>',
                          "<script>" + (WEB / "xterm.js").read_text(encoding="utf-8") + "</script><script>"
                          + (WEB / "addon-fit.js").read_text(encoding="utf-8") + "</script>")
    return _datei_schreiben(POPUP, seite)


def _datei_schreiben(pfad, seite):
    """Nur schreiben, wenn sich etwas geändert hat; nur für dich lesbar (Kennwort!)."""
    if not pfad.exists() or pfad.read_text(encoding="utf-8") != seite:
        pfad.write_text(seite, encoding="utf-8")
        os.chmod(pfad, 0o600)
    return pfad.as_uri()


def laeuft():
    z = zustand()
    if not z:
        return False
    try:
        with socket.create_connection(("127.0.0.1", z["port"]), timeout=0.3):
            return True
    except OSError:
        return False


def _stand():
    """Woran man erkennt, ob der laufende Dienst den aktuellen Code hat: der
    jüngste Änderungszeitpunkt aller Python-Dateien (der Dienst lädt auch
    zeit.py, gui_api.py …)."""
    return int(max(f.stat().st_mtime for f in ORDNER.glob("*.py")))


def sicherstellen():
    """Startet den Dienst im Hintergrund, falls er nicht läuft — oder ersetzt
    ihn, falls er noch mit einem älteren Stand dieser Datei läuft. (Ein alter
    Prozess läuft sonst einfach weiter, auch wenn der Code längst korrigiert ist.)"""
    z = zustand() or {}
    if laeuft() and z.get("stand") == _stand():
        return
    # Veralteten Dienst beenden — gefunden über den belegten Port (nicht über
    # die Datei: die kann von einer älteren Version stammen oder fehlen).
    belegt = subprocess.run(["lsof", "-t", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN"],
                            capture_output=True, text=True).stdout.split()
    for pid in belegt:
        befehl = subprocess.run(["ps", "-p", pid, "-o", "command="], capture_output=True, text=True).stdout
        if "webterm.py" in befehl:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                pass
    for _ in range(20):                              # warten, bis der Port frei ist
        if not laeuft():
            break
        select.select([], [], [], 0.1)
    ZUSTAND.parent.mkdir(parents=True, exist_ok=True)
    prozess = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "dienst"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    # Neues Kennwort -> neue Popup-Adresse -> SwiftBar lädt das Popup neu
    ZUSTAND.write_text(json.dumps({"port": PORT, "kennwort": secrets.token_urlsafe(24),
                                   "pid": prozess.pid, "stand": _stand()}), encoding="utf-8")
    for _ in range(30):                              # kurz warten, bis er antwortet
        if laeuft():
            return
        select.select([], [], [], 0.1)


# ===========================================================================
# WebSocket (nur das Nötigste aus RFC 6455)
# ===========================================================================

def _ws_senden(verbindung, daten, art=0x2):
    """Einen Rahmen senden. art 0x1 = Text, 0x2 = Binärdaten, 0x8 = Schließen."""
    kopf = bytes([0x80 | art])
    n = len(daten)
    if n < 126:
        kopf += bytes([n])
    elif n < 65536:
        kopf += bytes([126]) + struct.pack(">H", n)
    else:
        kopf += bytes([127]) + struct.pack(">Q", n)
    verbindung.sendall(kopf + daten)


def _genau(verbindung, n):
    daten = b""
    while len(daten) < n:
        stueck = verbindung.recv(n - len(daten))
        if not stueck:
            raise ConnectionError
        daten += stueck
    return daten


def _ws_empfangen(verbindung):
    """Einen Rahmen lesen. Rückgabe: (art, nutzdaten)."""
    b1, b2 = _genau(verbindung, 2)
    art, n = b1 & 0x0F, b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", _genau(verbindung, 2))[0]
    elif n == 127:
        n = struct.unpack(">Q", _genau(verbindung, 8))[0]
    maske = _genau(verbindung, 4) if b2 & 0x80 else b"\0\0\0\0"
    daten = bytes(b ^ maske[i % 4] for i, b in enumerate(_genau(verbindung, n)))
    return art, daten


# ===========================================================================
# Der Dienst
# ===========================================================================

SEITE = r"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>zeit</title>
<link rel="stylesheet" href="/web/xterm.css">
<style>
  /* Die Farben setzt farben() unten aus dem gewählten Farbschema */
  html, body { margin:0; height:100%; background:var(--hg); overflow:hidden; }
  #leiste { display:__LEISTE__; height:28px; align-items:center; justify-content:space-between;
            padding:0 10px; font:12px -apple-system, sans-serif; color:var(--text); }
  #leiste span { opacity:.6; }
  #leiste button { font:inherit; color:var(--text); background:color-mix(in srgb, var(--text) 14%, transparent);
                   border:0; border-radius:5px; padding:3px 9px; cursor:pointer; }
  #terminal { position:absolute; top:__OBEN__px; left:6px; right:4px; bottom:4px; }
</style></head><body>
<div id="leiste"><span>zeit</span><button onclick="alsFenster()">⧉ Als Fenster öffnen</button></div>
<div id="terminal"></div>
<script src="/web/xterm.js"></script><script src="/web/addon-fit.js"></script>
<script>
const KENNWORT = "__KENNWORT__" || new URLSearchParams(location.search).get("t");
const DIENST = "127.0.0.1:__PORT__";
const kasten = document.getElementById("terminal");
// Farbschema (Einstellung „Farbschema“): beim Erzeugen der Seite eingesetzt.
// Ändert es sich, schickt der Dienst es sofort über die WebSocket-Verbindung;
// beim Öffnen des Popups fragt die Seite zur Sicherheit noch einmal nach.
const POPUP = __POPUP__;
let thema = __THEMA__;
function farben() {
  document.documentElement.style.setProperty("--hg", thema.background);
  document.documentElement.style.setProperty("--text", thema.foreground);
  if (term) term.options.theme = thema;
}
function themaNachfragen() {
  if (!POPUP || document.hidden) return;
  fetch(`http://${DIENST}/thema?t=${KENNWORT}`).then(a => a.json()).then(neu => {
    if (JSON.stringify(neu) !== JSON.stringify(thema)) { thema = neu; farben(); }
  }).catch(() => {});
}
// JavaScript-Fehler an den Dienst melden (landen in ~/Library/Caches/zeit/webterm.log)
function melde(text) { fetch(`http://${DIENST}/log?t=${KENNWORT}&m=${encodeURIComponent(text)}`,
                               { method: "POST", mode: "no-cors" }).catch(() => {}); }
window.onerror = (m, q, z) => melde(`JS-Fehler: ${m} (Zeile ${z})`);

// SwiftBar baut das Popup schon unsichtbar und ohne Größe auf. Ein Terminal,
// das in einem Kasten der Größe 0 entsteht, misst seine Schrift mit 0 und
// zeichnet danach nie etwas. Darum: erst erzeugen, wenn der Kasten Platz hat —
// und bei jeder Größenänderung neu einpassen.
let term = null, passend = null, ws = null;
farben();
function erzeugen() {
  term = new Terminal({ fontFamily: "SF Mono, Menlo, monospace", fontSize: 12.5,
    theme: thema, cursorBlink: false, macOptionIsMeta: true });
  passend = new FitAddon.FitAddon();
  term.loadAddon(passend);
  term.open(kasten);
  passend.fit();
  term.onData(d => { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ t: "e", d })); });
  verbinden();
}
function verbinden() {
  ws = new WebSocket(`ws://${DIENST}/pty?t=${KENNWORT}${POPUP ? "&popup=1" : ""}`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { groesse(); term.focus(); };
  ws.onmessage = e => {
    // Text = neues Farbschema vom Dienst, Binärdaten = Bildschirmausgabe des TUI
    // (danach groesse(): das schickt dem TUI ein Signal, so dass es sich sofort
    // neu zeichnet und die Akzentfarbe „Standard“ dem neuen Schema anpasst)
    if (typeof e.data === "string") { thema = JSON.parse(e.data); farben(); groesse(); }
    else term.write(new Uint8Array(e.data));
  };
  // Wird das TUI beendet (q), startet sofort ein frisches — das Popup ist nie leer
  ws.onclose = () => { term.reset(); setTimeout(verbinden, 300); };
}
function groesse() {
  if (!term || !kasten.clientWidth || !kasten.clientHeight) return;
  passend.fit();
  term.refresh(0, term.rows - 1);
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ t: "r", c: term.cols, r: term.rows }));
}
new ResizeObserver(() => {
  if (!term && kasten.clientWidth > 0 && kasten.clientHeight > 0) erzeugen();
  else groesse();
}).observe(kasten);
document.addEventListener("visibilitychange", () => { groesse(); themaNachfragen(); });
window.addEventListener("focus", () => { groesse(); themaNachfragen(); if (term) term.focus(); });
function alsFenster() { fetch(`http://${DIENST}/fenster?t=${KENNWORT}`, { method: "POST", mode: "no-cors" }); }
</script></body></html>
"""


class Anfrage(http.server.BaseHTTPRequestHandler):
    # WebSockets verlangen HTTP/1.1 (sonst verweigern Browser die Verbindung)
    protocol_version = "HTTP/1.1"

    def log_request(self, code="-", size="-"):
        pass                     # normale Abrufe nicht protokollieren, nur Auffälliges

    def log_message(self, format, *argumente):
        # Kurzes Protokoll (ohne Kennwort): Fehler der Seite, falsches Kennwort
        try:
            zeile = (format % argumente).split("?t=")[0]
            with open(ZUSTAND.with_name("webterm.log"), "a", encoding="utf-8") as log:
                log.write(f"{self.log_date_time_string()}  {self.headers.get('User-Agent', '-')[:60]}  {zeile}\n")
        except Exception:
            pass

    def _erlaubt(self):
        kennwort = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("t", [""])[0]
        return secrets.compare_digest(kennwort, (zustand() or {}).get("kennwort", "-"))

    def _antwort(self, code, inhalt=b"", art="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", art)
        self.send_header("Content-Length", str(len(inhalt)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(inhalt)

    def _json(self, daten):
        # Die Popup-Seite ist eine lokale Datei (Herkunft "null") — ohne diese
        # Freigabe dürfte sie die Antwort nicht lesen. Geschützt ist trotzdem
        # alles durch das Kennwort.
        inhalt = json.dumps(daten, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(inhalt)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(inhalt)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        pfad = urllib.parse.urlparse(self.path).path
        if pfad.startswith("/web/"):                  # xterm.js & Co. (öffentlich, keine Daten)
            datei = WEB / Path(pfad).name
            if datei.is_file() and datei.suffix in (".css", ".js"):
                art = "text/css" if datei.suffix == ".css" else "application/javascript"
                return self._antwort(200, datei.read_bytes(), art + "; charset=utf-8")
            return self._antwort(404)
        if not self._erlaubt():
            self.log_message("KENNWORT PASST NICHT für %s (Anfrage: %s)", pfad,
                             "mit ?t=" if "t=" in self.path else "ganz ohne ?t=")
            return self._antwort(403, "Falsches Kennwort.".encode())
        if pfad == "/pty":
            return self._terminal()
        if pfad == "/api/zustand":
            import gui_api, zeit
            if "sichtbar=1" in self.path:                 # die GUI ist gerade vor deinen Augen
                zeit.GUI_SICHTBAR.parent.mkdir(parents=True, exist_ok=True)
                zeit.GUI_SICHTBAR.touch()
            try:
                return self._json(gui_api.zustand())
            except Exception as grund:
                return self._json({"fehler": f"{type(grund).__name__}: {grund}"})
        if pfad == "/thema":
            # Die Popup-Seite ist eine lokale Datei (Herkunft "null") — ohne
            # diese Freigabe dürfte sie die Antwort nicht lesen
            inhalt = json.dumps(aktuelles_thema()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(inhalt)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return self.wfile.write(inhalt)
        if anzeige() == "gui":
            seite = gui_seite(fenster="fenster=1" in self.path, eingebaut=False)
        else:
            seite = seite_fuer(popup="fenster=1" not in self.path)
        return self._antwort(200, seite.encode(), "text/html; charset=utf-8")

    def do_POST(self):
        teile = urllib.parse.urlparse(self.path)
        if teile.path == "/log" and self._erlaubt():
            self.log_message("Seite meldet: %s", urllib.parse.parse_qs(teile.query).get("m", [""])[0])
            return self._antwort(204)
        if teile.path == "/api" and self._erlaubt():
            import gui_api
            laenge = int(self.headers.get("Content-Length", 0) or 0)
            try:
                auftrag = json.loads(self.rfile.read(laenge).decode("utf-8") or "{}")
                return self._json(gui_api.ausfuehren(auftrag))
            except Exception as grund:
                self.log_message("GUI-Fehler: %s", grund)
                return self._json({"fehler": f"{type(grund).__name__}: {grund}"})
        if teile.path == "/fenster" and self._erlaubt():
            fenster_oeffnen()
            return self._antwort(204)
        return self._antwort(403)

    def _terminal(self):
        """WebSocket-Verbindung: zeit in einem Pseudo-Terminal, Ein-/Ausgabe hin und her."""
        schluessel = self.headers.get("Sec-WebSocket-Key", "")
        antwort = base64.b64encode(hashlib.sha1(
            (schluessel + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", antwort)
        self.end_headers()
        verbindung = self.connection
        schloss = threading.Lock()

        def senden(daten, art=0x2):
            # Zwei Threads (Bildschirmausgabe, Farbschema) schreiben in dieselbe
            # Verbindung — das Schloss sorgt dafür, dass sich ihre Rahmen nicht mischen
            with schloss:
                _ws_senden(verbindung, daten, art)

        pid, fd = pty.fork()
        if pid == 0:                                  # Kindprozess: hier läuft das TUI
            umgebung = dict(os.environ, TERM="xterm-256color", LANG="de_DE.UTF-8",
                            LC_ALL="de_DE.UTF-8", ZEIT_FARBSCHEMA="1")
            os.execve(sys.executable, [sys.executable, str(ORDNER / "zeit.py")], umgebung)

        def ausgabe():
            try:
                while True:
                    daten = os.read(fd, 65536)
                    if not daten:
                        break
                    senden(daten)
            except OSError:
                pass
            try:
                senden(b"", 0x8)       # TUI beendet -> Verbindung schließen
            except OSError:
                pass

        threading.Thread(target=ausgabe, daemon=True).start()
        if "popup=1" in self.path:
            threading.Thread(target=farbschema_waechter, args=(verbindung, senden), daemon=True).start()
        try:
            while True:
                art, daten = _ws_empfangen(verbindung)
                if art == 0x8:
                    break
                if art in (0x1, 0x2):
                    nachricht = json.loads(daten.decode("utf-8"))
                    if nachricht["t"] == "e":
                        os.write(fd, nachricht["d"].encode("utf-8"))
                    elif nachricht["t"] == "r":
                        fcntl.ioctl(fd, termios.TIOCSWINSZ,
                                    struct.pack("HHHH", nachricht["r"], nachricht["c"], 0, 0))
                        os.kill(pid, signal.SIGWINCH)
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            try:
                os.kill(pid, signal.SIGTERM)
                os.waitpid(pid, 0)
            except OSError:
                pass
            os.close(fd)


def farbschema_waechter(verbindung, senden):
    """Schaut fünfmal pro Sekunde, ob projekte.md sich geändert hat (dort stehen die
    Einstellungen). Hat sich dabei das Farbschema geändert, bekommt das Popup es
    sofort als Textnachricht — ohne dass die Seite selbst nachfragen muss."""
    import zeit
    zuletzt_stand, zuletzt_thema = None, None
    while True:
        try:
            stand = zeit.CONFIG_DATEI.stat().st_mtime_ns
        except OSError:
            stand = None
        if stand != zuletzt_stand:
            zuletzt_stand = stand
            thema = aktuelles_thema()
            if zuletzt_thema is not None and thema != zuletzt_thema:
                try:
                    senden(json.dumps(thema).encode("utf-8"), 0x1)
                except OSError:
                    return                                # Popup-Verbindung ist zu
            zuletzt_thema = thema
        if verbindung.fileno() == -1:
            return
        threading.Event().wait(0.2)


def dienst():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", zustand()["port"]), Anfrage)
    server.daemon_threads = True
    server.serve_forever()


# ===========================================================================
# Als normales Fenster
# ===========================================================================

_FENSTER_JXA = r"""
ObjC.import('Cocoa'); ObjC.import('WebKit');
ObjC.registerSubclass({ name: 'ZeitTerminalZiel', protocols: ['NSWindowDelegate'], methods: {
    'windowWillClose:': { types: ['void', ['id']], implementation: function (_) {
        $.NSApplication.sharedApplication.terminate(null); } } } });
function run(argv) {
    var app = $.NSApplication.sharedApplication;
    app.setActivationPolicy($.NSApplicationActivationPolicyRegular);
    var leiste = $.NSMenu.alloc.init, punkt = $.NSMenuItem.alloc.init;
    leiste.addItem(punkt);
    var menue = $.NSMenu.alloc.initWithTitle('zeit');
    menue.addItem($.NSMenuItem.alloc.initWithTitleActionKeyEquivalent('Fenster schließen', 'performClose:', 'w'));
    menue.addItem($.NSMenuItem.alloc.initWithTitleActionKeyEquivalent('Beenden', 'terminate:', 'q'));
    punkt.submenu = menue; app.mainMenu = leiste;
    var rahmen = $.NSMakeRect(0, 0, Number(argv[1]), Number(argv[2]));
    var fenster = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(rahmen, 15, 2, false);
    fenster.title = 'zeit'; fenster.center; fenster.releasedWhenClosed = false;
    fenster.delegate = $.ZeitTerminalZiel.alloc.init;
    var web = $.WKWebView.alloc.initWithFrameConfiguration(rahmen, $.WKWebViewConfiguration.alloc.init);
    web.loadRequest($.NSURLRequest.requestWithURL($.NSURL.URLWithString(argv[0])));
    fenster.contentView = web;
    fenster.makeKeyAndOrderFront(null);
    app.activateIgnoringOtherApps(true);
    app.run;
}
"""


def fenster_oeffnen():
    """TUI oder GUI als normales, frei verschiebbares Fenster."""
    sicherstellen()
    breite, hoehe = (560, 720) if anzeige() == "gui" else (820, 560)
    prozess = subprocess.Popen(["osascript", "-l", "JavaScript", "-", adresse(fenster=True),
                                str(breite), str(hoehe)],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True, text=True)
    prozess.stdin.write(_FENSTER_JXA)
    prozess.stdin.close()


if __name__ == "__main__":
    befehl = sys.argv[1:2]
    if befehl == ["dienst"]:
        dienst()
    elif befehl == ["sicherstellen"]:
        sicherstellen()
        print(adresse())
    elif befehl == ["fenster"]:
        fenster_oeffnen()
