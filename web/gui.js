/*
  gui.js — das Verhalten der zeit-GUI.

  Die GUI rechnet und speichert nichts selbst. Sie fragt den lokalen Dienst
  (webterm.py → gui_api.py), was gerade los ist, und schickt ihm Aufträge wie
  „starte den Timer“. Alles Weitere erledigt zeit.py — genau wie im Terminal.

  Aufbau dieser Datei:
    1. Verbindung zum Dienst
    2. Zustand und kleine Hilfen
    3. Reiter
    4. Seite „Timer“
    5. Blätter (Dialoge): Rückfrage, Bericht, Countdown, Pomodoro, Nachtragen …
    6. Kalender und Statistik (eingebettete Seite)
    7. Seite „Einträge“
    8. Einstellungen
    9. Tastatur
   10. Start
*/
"use strict";

// ===========================================================================
// 1. Verbindung zum Dienst
// ===========================================================================

const DIENST = `http://127.0.0.1:${ZEIT.port}`;

// Aufträge gehen als Text (nicht als "application/json") hinaus: so gilt die
// Anfrage als „einfach“ und der Browser fragt nicht erst um Erlaubnis — die
// Popup-Seite ist eine lokale Datei und hat keine eigene Web-Adresse.
async function api(auftrag) {
  try {
    const antwort = await fetch(`${DIENST}/api?t=${ZEIT.kennwort}`, {
      method: "POST", body: JSON.stringify(auftrag), headers: { "Content-Type": "text/plain" } });
    if (antwort.status === 403) return verbindungWeg();
    return await antwort.json();
  } catch (e) {
    return verbindungWeg();
  }
}

async function zustandHolen() {
  // "sichtbar": nur wenn du die GUI gerade vor dir hast. Dann überlässt der
  // Wecker ihr die Frage „Zeit um — was jetzt?“, statt einen Dialog zu öffnen.
  const sichtbar = !document.hidden && document.hasFocus() ? 1 : 0;
  try {
    const antwort = await fetch(`${DIENST}/api/zustand?t=${ZEIT.kennwort}&sichtbar=${sichtbar}`);
    if (antwort.status === 403) return verbindungWeg();
    const neu = await antwort.json();
    verbunden = true;
    zustandAnwenden(neu);
  } catch (e) {
    verbindungWeg();
  }
}

let verbunden = true;
function verbindungWeg() {
  if (verbunden) meldung("Keine Verbindung zu zeit.\nBitte das Popup bzw. Fenster neu öffnen.", true);
  verbunden = false;
  return { fehler: "Keine Verbindung zu zeit." };
}

// Einen Auftrag ausführen und das Ergebnis zeigen: Fehler, Rückfrage, Bericht
// oder eine kurze Meldung. Rückgabe: die Antwort (oder null bei Fehler/Frage).
async function aktion(auftrag, optionen = {}) {
  const r = await api(auftrag);
  if (r.fehler) {
    if (optionen.fehlerFeld) optionen.fehlerFeld.textContent = r.fehler;
    else meldung(r.fehler, true);
    return null;
  }
  if (r.frage) {
    frageBlatt(r.frage, r.knopf, auftrag, optionen);
    return null;
  }
  if (!optionen.blattBleibt) blattZu();
  if (r.bericht) berichtBlatt(r.bericht);
  else if (r.meldung) meldung(r.meldung);
  zustandHolen();
  kalenderAuffrischen();
  if (UI.reiter === "eintraege") eintraegeZeichnen();
  return r;
}


// ===========================================================================
// 2. Zustand und kleine Hilfen
// ===========================================================================

let Z = null;          // der letzte Zustand vom Dienst

// Was die Oberfläche sich merkt: welcher Reiter, was ausgewählt ist, welches
// Blatt offen ist (mit seinen Eingaben). Das Popup wird bei jedem Öffnen neu
// geladen — deshalb wird das im Browser-Speicher gesichert und wiederhergestellt.
let UI = { reiter: "timer", auswahl: { projekt: null, phase: null }, blatt: null,
           einstellungen: false, eintraegeProjekt: null };
const SPEICHER = "zeit-gui";
function merken() {
  try { localStorage.setItem(SPEICHER, JSON.stringify({ ...UI, gemerkt: Date.now() })); } catch (e) {}
}
function erinnern() {
  try {
    const alt = JSON.parse(localStorage.getItem(SPEICHER) || "null");
    if (!alt) return;
    UI.reiter = alt.reiter || "timer";
    UI.auswahl = alt.auswahl || UI.auswahl;
    UI.eintraegeProjekt = alt.eintraegeProjekt || null;
    UI.einstellungen = !!alt.einstellungen;
    // Ein offenes Blatt nur zurückholen, wenn es frisch ist (10 min)
    if (alt.blatt && Date.now() - alt.gemerkt < 10 * 60 * 1000) UI.blatt = alt.blatt;
  } catch (e) {}
}

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const zwei = n => String(n).padStart(2, "0");
const std = m => { m = Math.max(0, Math.round(m)); return Math.floor(m / 60) + ":" + zwei(m % 60); };
function uhr(sekunden) {                        // 3725 -> "1:02:05", 125 -> "2:05"
  sekunden = Math.max(0, Math.floor(sekunden));
  const h = Math.floor(sekunden / 3600), m = Math.floor(sekunden / 60) % 60, s = sekunden % 60;
  return h ? `${h}:${zwei(m)}:${zwei(s)}` : `${m}:${zwei(s)}`;
}
const zeitpunkt = iso => new Date(iso);            // "2026-09-25T14:03:00" (Ortszeit)
const hhmm = d => `${zwei(d.getHours())}:${zwei(d.getMinutes())}`;
const heuteIso = () => { const d = new Date(); return `${d.getFullYear()}-${zwei(d.getMonth() + 1)}-${zwei(d.getDate())}`; };
const WT = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
function datumLesbar(iso) {
  const [j, m, t] = iso.split("-").map(Number);
  const d = new Date(j, m - 1, t);
  return `${WT[d.getDay()]} ${zwei(t)}.${zwei(m)}.${j}`;
}

// Ein Stück HTML in echte Elemente verwandeln
function html(text) {
  const t = document.createElement("template");
  t.innerHTML = text.trim();
  return t.content.firstElementChild;
}

let meldungsUhr = null;
function meldung(text, fehler = false) {
  const m = $("meldung");
  m.textContent = text;
  m.className = "meldung" + (fehler ? " fehler-meldung" : "");
  clearTimeout(meldungsUhr);
  meldungsUhr = setTimeout(() => m.classList.add("versteckt"), fehler ? 5000 : 2600);
}

// Akzentfarbe aus den Einstellungen; die Schrift darauf wird hell oder dunkel
function akzentSetzen(farbe) {
  const f = farbe || "#0a84ff";
  document.documentElement.style.setProperty("--akzent", f);
  const [r, g, b] = [1, 3, 5].map(i => parseInt(f.slice(i, i + 2), 16));
  document.documentElement.style.setProperty("--auf-akzent", 0.299 * r + 0.587 * g + 0.114 * b > 170 ? "#1d1d1f" : "#fff");
}

// Auswahllisten für Projekt und Phase (mit „+ Neu …“ am Ende)
function projektOptionen(gewaehlt, mitNeu = true) {
  return Z.projekte.map(p => `<option ${p === gewaehlt ? "selected" : ""}>${esc(p)}</option>`).join("") +
         (mitNeu ? `<option value="__neu">+ Neues Projekt …</option>` : "");
}
function phasenOptionen(gewaehlt, mitNeu = true) {
  return Z.phasen.map(p => `<option ${p === gewaehlt ? "selected" : ""}>${esc(p)}</option>`).join("") +
         (mitNeu ? `<option value="__neu">+ Neue Phase …</option>` : "");
}
// Gewählte Werte prüfen: gibt es sie noch? Sonst Vorschlag nehmen.
function auswahlPruefen() {
  const a = UI.auswahl, l = Z.laufend, z = Z.zuletzt;
  if (!Z.projekte.includes(a.projekt)) a.projekt = (l && l.projekt) || (z && z.projekt) || Z.projekte[0] || null;
  if (!Z.phasen.includes(a.phase)) a.phase = (l && l.phase) || (z && z.phase) || Z.phasen[0] || null;
}


// ===========================================================================
// 3. Reiter
// ===========================================================================

function reiterZeigen(name) {
  UI.reiter = name;
  UI.einstellungen = false;
  merken();
  seitenUmschalten();
}

function seitenUmschalten() {
  const seite = UI.einstellungen ? "einstellungen" : UI.reiter;
  document.querySelectorAll(".seite").forEach(s => s.classList.toggle("an", s.id === "r_" + seite));
  document.querySelectorAll("#reiter button").forEach(b =>
    b.classList.toggle("an", !UI.einstellungen && b.dataset.reiter === UI.reiter));
  if (seite === "kalender" || seite === "statistik") kalenderZeigen(seite);
  if (seite === "eintraege") eintraegeZeichnen();
  if (seite === "einstellungen") einstellungenZeichnen();
}


// ===========================================================================
// 4. Seite „Timer“
// ===========================================================================

let timerSchluessel = null;     // woran man erkennt, dass neu gezeichnet werden muss

function zustandAnwenden(neu) {
  const vorher = Z;
  Z = neu;
  akzentSetzen(Z.akzent);
  auswahlPruefen();
  // rest_text („noch 12 min“) ändert sich jede Minute — dafür nicht alles neu bauen
  // (sonst klappt z. B. eine gerade geöffnete Auswahlliste zu)
  const lauf = Z.laufend && { ...Z.laufend, rest_text: null };
  const schluessel = JSON.stringify([lauf, Z.projekte, Z.phasen, UI.auswahl, Z.einstellungen["pomodoro-verlaengern"]]);
  if (schluessel !== timerSchluessel) { timerSchluessel = schluessel; timerZeichnen(); }
  if (!vorher && UI.blatt) blattZeichnen();          // nach dem Laden: Blatt zurückholen
  if (!vorher) seitenUmschalten();
  ticken();
}

// Die Knöpfe, die gerade passen — dieselben wie im Klappmenü der Menüleiste
function knoepfeFuer(l) {
  const x = Z.einstellungen["pomodoro-verlaengern"];
  const k = (text, auftrag, art = "", taste = "") =>
    `<button class="k ${art}" data-auftrag='${esc(JSON.stringify(auftrag))}'>${text}${taste ? `<span class="taste">${taste}</span>` : ""}</button>`;
  const wort = { pomodoro: "Sitzung", countdown: "Countdown", timer: "Timer" }[l.typ];
  const b = [];
  if (l.zustand === "angehalten") {
    b.push(k("▶ Fortsetzen", { aktion: "fortsetzen" }, "haupt", "␣"));
  } else if (l.typ === "pomodoro" && l.zustand === "fokus") {
    b.push(k("☕ Pause starten", { aktion: "pause" }, l.ueberfaellig ? "haupt" : ""));
    b.push(k(`Noch ${x} min`, { aktion: "mehr" }));
    b.push(k("⏸ Anhalten", { aktion: "anhalten" }, "", "␣"));
  } else if (l.typ === "pomodoro") {
    b.push(k("🍅 Weiter mit Fokus", { aktion: "weiter" }, "haupt"));
    b.push(k(`Noch ${x} min Pause`, { aktion: "mehr" }));
  } else if (l.typ === "countdown") {
    b.push(k(`Noch ${x} min`, { aktion: "mehr" }, l.ueberfaellig ? "haupt" : ""));
    b.push(k("⏸ Anhalten", { aktion: "anhalten" }, "", "␣"));
  } else {
    b.push(k("⏸ Anhalten", { aktion: "anhalten" }, "", "␣"));
  }
  b.push(k(l.typ === "timer" ? "■ Stoppen" : `■ ${wort} beenden`, { aktion: "stop" },
           l.typ === "timer" && l.zustand !== "angehalten" ? "haupt" : "", "S"));
  b.push(k("Abbrechen", { aktion: "abbrechen" }, "leise"));
  return b.join("");
}

function timerZeichnen() {
  const s = $("r_timer");
  const l = Z.laufend;
  let oben;
  if (!l) {
    oben = `<div class="karte anzeige">
      <div class="was">Kein Timer läuft</div>
      <div class="uhr ruhig">0:00</div>
      <div class="zusatz" data-heute>Heute erfasst: ${std(Z.heute_minuten)} h</div></div>`;
  } else {
    // Überschrift je nach Lage
    let was;
    if (l.typ === "timer" && l.zustand !== "angehalten") was = "▶ Timer läuft";
    else was = `${l.symbol} ${esc(l.was)}`;
    let hinweis = "";
    if (l.ueberfaellig) {
      const text = l.typ === "countdown" ? "Die Zeit ist um." :
                   l.zustand === "fokus" ? "Der Fokus ist vorbei — Pause starten?" : "Die Pause ist vorbei — weiter?";
      hinweis = `<div class="hinweis">⏰ ${text}</div>`;
    }
    if (l.vergessen) hinweis = `<div class="hinweis">⚠ Läuft seit über acht Stunden oder über Nacht. Vergessen? Dann nach dem Stoppen unter „Einträge“ die Endzeit korrigieren.</div>`;
    if (l.typ !== "timer" && !l.erfasst_seit && l.zustand !== "angehalten")
      hinweis += `<div class="klein" style="margin-top:6px">In der Pause wird keine Zeit erfasst.</div>`;
    const ende = l.ende ? `<div class="zusatz">Ende um ${hhmm(zeitpunkt(l.ende))}</div>` : "";
    oben = `<div class="karte anzeige">
      <div class="was">${was}</div>
      <div class="uhr" data-uhr></div>
      <div class="wo">${esc(l.projekt)} / ${esc(l.phase)}</div>
      <div class="zusatz" data-zusatz></div>${l.typ !== "timer" && l.ende ? ende : ""}
      ${l.ende ? `<div class="balken"><div data-balken></div></div>` : ""}
      ${hinweis}
      <div class="knoepfe">${knoepfeFuer(l)}</div></div>`;
  }
  const a = UI.auswahl;
  const neu = Z.projekte.length ? `
    <h2>${l ? "Etwas anderes starten" : "Starten"}</h2>
    <div class="karte">
      <div class="feld"><span>Projekt</span><select id="w_projekt">${projektOptionen(a.projekt)}</select></div>
      <div class="feld"><span>Phase</span><select id="w_phase">${phasenOptionen(a.phase)}</select></div>
      <div class="start-knoepfe">
        <button class="k haupt" data-start="timer">▶ Timer<span class="taste">N</span></button>
        <button class="k" data-start="countdown">⏳ Countdown …</button>
        <button class="k" data-start="pomodoro">🍅 Pomodoro …</button>
        <button class="k" data-start="nachtragen">✎ Nachtragen …</button>
      </div></div>` : `
    <div class="karte leer">Noch keine Projekte.<br><br>
      <button class="k haupt" id="erstes_projekt">+ Erstes Projekt anlegen</button></div>`;
  s.innerHTML = oben + neu;

  // Knöpfe verdrahten
  s.querySelectorAll("[data-auftrag]").forEach(b => b.onclick = () => aktion(JSON.parse(b.dataset.auftrag)));
  s.querySelectorAll("[data-start]").forEach(b => b.onclick = () => starten(b.dataset.start));
  if ($("erstes_projekt")) $("erstes_projekt").onclick = () => blattOeffnen("projekt", { name: "", ordner: "", vonHand: false });
  if ($("w_projekt")) {
    $("w_projekt").onchange = e => auswahlGeaendert("projekt", e.target);
    $("w_phase").onchange = e => auswahlGeaendert("phase", e.target);
  }
  ticken();
}

function auswahlGeaendert(was, select) {
  if (select.value === "__neu") {
    select.value = UI.auswahl[was] || "";
    blattOeffnen(was === "projekt" ? "projekt" : "phase", { name: "", ordner: "", vonHand: false });
    return;
  }
  UI.auswahl[was] = select.value;
  merken();
}

function starten(art) {
  const { projekt, phase } = UI.auswahl;
  if (!projekt || !phase) return meldung("Bitte Projekt und Phase wählen.", true);
  if (art === "timer") return aktion({ aktion: "start", projekt, phase });
  const v = Z.vorgaben;
  if (art === "countdown") {
    const dauer = v.countdown.dauer;
    const bis = new Date(Date.now() + (dauer + 7) * 60000);
    bis.setMinutes(bis.getMinutes() - bis.getMinutes() % 15);
    blattOeffnen("countdown", { projekt, phase, art: v.countdown.art, dauer: std(dauer), bis: hhmm(bis) });
  } else if (art === "pomodoro") {
    blattOeffnen("pomodoro", { projekt, phase, ...v.pomodoro });
  } else {
    blattOeffnen("nachtragen", { projekt, phase, ...v.nachtrag, nur_tag: false, dauer: "1:00" });
  }
}

// Jede Sekunde: Uhr, Balken und „Heute“ weiterzählen (ohne alles neu zu bauen)
function ticken() {
  if (!Z) return;
  const l = Z.laufend, jetzt = Date.now();
  let laufendeMinuten = 0;
  if (l && l.erfasst_seit) laufendeMinuten = (jetzt - zeitpunkt(l.erfasst_seit)) / 60000;
  $("heute").textContent = `Heute ${std(Z.heute_minuten + laufendeMinuten)} h`;
  const h = document.querySelector("[data-heute]");
  if (h) h.textContent = `Heute erfasst: ${std(Z.heute_minuten)} h`;
  const u = document.querySelector("[data-uhr]");
  if (!l || !u) return;
  const zusatz = document.querySelector("[data-zusatz]"), balken = document.querySelector("[data-balken]");
  u.style.color = "";
  if (l.zustand === "angehalten") {
    u.textContent = l.typ === "timer" ? "⏸" : uhr(Math.max(0, l.rest));
    zusatz.textContent = `angehalten seit ${uhr((jetzt - zeitpunkt(l.seit)) / 1000)}` +
                         (l.typ === "timer" ? "" : " · Rest läuft beim Fortsetzen weiter");
  } else if (l.ende) {
    const rest = (zeitpunkt(l.ende) - jetzt) / 1000;
    u.textContent = rest >= 0 ? uhr(rest) : "+" + uhr(-rest);
    if (rest < 0) u.style.color = "var(--warn)";
    zusatz.textContent = rest >= 0 ? "übrig" : "überzogen";
    if (balken) {
      const gesamt = zeitpunkt(l.ende) - zeitpunkt(l.seit);
      balken.style.width = Math.min(100, Math.max(0, (jetzt - zeitpunkt(l.seit)) / gesamt * 100)) + "%";
    }
  } else {
    u.textContent = uhr((jetzt - zeitpunkt(l.erfasst_seit)) / 1000);
    zusatz.textContent = `seit ${hhmm(zeitpunkt(l.erfasst_seit))} Uhr`;
  }
}


// ===========================================================================
// 5. Blätter (Dialoge)
// ===========================================================================
//
// Ein Blatt ist { art, d } — d sind die Eingaben. Jede Eingabe schreibt sofort
// in d und merkt sich das; so übersteht ein halb ausgefülltes Blatt auch das
// Schließen und Wiederöffnen des Popups.

const BLAETTER = {};           // art -> Funktion, die das Blatt zeichnet

function blattOeffnen(art, d, zurueck = null) {
  UI.blatt = { art, d, zurueck };
  merken();
  blattZeichnen();
}
function blattZu() {
  UI.blatt = null;
  merken();
  $("schleier").classList.add("versteckt");
  $("blatt").innerHTML = "";
}
// Zurück zum vorherigen Blatt (z. B. nach „Neues Projekt“ wieder zum Nachtragen)
function blattZurueck() {
  const z = UI.blatt && UI.blatt.zurueck;
  if (z) { UI.blatt = z; merken(); blattZeichnen(); } else blattZu();
}
function blattZeichnen() {
  if (!UI.blatt || !Z || !BLAETTER[UI.blatt.art]) return blattZu();
  const b = $("blatt");
  b.innerHTML = "";
  BLAETTER[UI.blatt.art](b, UI.blatt.d);
  $("schleier").classList.remove("versteckt");
  const erstes = b.querySelector("input:not([type=checkbox]), textarea, select");
  if (erstes && !UI.blatt.d._keinFokus) erstes.focus();
}

// Eingabefeld mit d[schluessel] verbinden (Wert rein, Änderungen zurück)
function binden(wurzel, d, neuZeichnen = false) {
  wurzel.querySelectorAll("[data-b]").forEach(feld => {
    const s = feld.dataset.b;
    if (feld.type === "checkbox") feld.checked = !!d[s];
    else feld.value = d[s] ?? "";
    feld.addEventListener(feld.type === "checkbox" || feld.tagName === "SELECT" ? "change" : "input", () => {
      d[s] = feld.type === "checkbox" ? feld.checked : feld.value;
      merken();
      if (neuZeichnen || feld.dataset.neu !== undefined) blattZeichnen();
    });
  });
}

function fuss(knoepfe) {
  return `<div class="fehler" id="b_fehler"></div><div class="fuss">${knoepfe}</div>`;
}

// ---- Rückfrage ------------------------------------------------------------
function frageBlatt(text, knopf, auftrag, optionen) {
  const vorher = UI.blatt;
  // Sonderfall „In den Kalender schreiben“: Nein heißt dort „nur neue“
  const kalender = auftrag.aktion === "einstellung" && auftrag.schluessel === "kalender-schreiben";
  blattOeffnen("frage", { text, knopf, auftrag, kalender, _keinFokus: true }, vorher);
}
BLAETTER.frage = (b, d) => {
  b.innerHTML = `<h3>Bitte bestätigen</h3><div class="frage-text">${esc(d.text)}</div>` +
    fuss(`<button class="k" id="b_nein">${d.kalender ? "Nur neue" : "Abbrechen"}</button>
          <button class="k haupt" id="b_ja">${esc(d.knopf)}</button>`);
  $("b_nein").onclick = () => {
    if (d.kalender) { UI.blatt = d.zurueck || null; aktion({ ...d.auftrag, bisherige: false }); }
    else blattZurueck();
  };
  $("b_ja").onclick = () => {
    const zurueck = UI.blatt.zurueck;
    UI.blatt = zurueck;                              // Fehler landen dann im vorherigen Blatt
    const extra = d.kalender ? { bisherige: true } : { ok: true };
    aktion({ ...d.auftrag, ...extra }).then(r => { if (!r && zurueck) blattZeichnen(); });
  };
  $("b_ja").focus();
};

// ---- Bericht + Feedback ---------------------------------------------------
function berichtBlatt(bericht) { blattOeffnen("bericht", { ...bericht, fokus: "", notiz: "" }); }
BLAETTER.bericht = (b, d) => {
  b.innerHTML = `<h3>Erfasst</h3>
    <div class="bericht">${esc(d.zeilen.join("\n"))}</div>
    <h2>Wie fokussiert warst du? <span class="leise" style="text-transform:none">(freiwillig)</span></h2>
    <div class="segmente" id="b_fokus">
      ${["😄", "😐", "☹️"].map((f, i) => `<button data-f="${f}" class="${d.fokus === f ? "an" : ""}">${f} ${["fokussiert", "so lala", "abgelenkt"][i]}</button>`).join("")}
    </div>
    <textarea data-b="notiz" placeholder="Notiz (freiwillig)" style="margin-top:8px"></textarea>` +
    fuss(`<button class="k links" id="b_kalender">Kalender öffnen</button>
          <button class="k" id="b_weg">Überspringen</button>
          <button class="k haupt" id="b_ok">Speichern</button>`);
  d._keinFokus = true;
  binden(b, d);
  b.querySelectorAll("[data-f]").forEach(k => k.onclick = () => {
    d.fokus = d.fokus === k.dataset.f ? "" : k.dataset.f;      // nochmal klicken = abwählen
    merken(); blattZeichnen();
  });
  $("b_weg").onclick = blattZu;
  $("b_kalender").onclick = () => { blattZu(); reiterZeigen("kalender"); };
  $("b_ok").onclick = () => {
    if (!d.fokus && !d.notiz.trim()) return blattZu();
    aktion({ aktion: "feedback", projekt: d.projekt, datum: d.datum, start: d.start,
             fokus: d.fokus, notiz: d.notiz }, { fehlerFeld: $("b_fehler") });
  };
};

// ---- Countdown -------------------------------------------------------------
BLAETTER.countdown = (b, d) => {
  b.innerHTML = `<h3>⏳ Countdown starten</h3><div class="unterzeile">${esc(d.projekt)} / ${esc(d.phase)}</div>
    <div class="segmente" id="b_art">
      <button data-a="dauer" class="${d.art !== "bis" ? "an" : ""}">Dauer</button>
      <button data-a="bis" class="${d.art === "bis" ? "an" : ""}">Bis Uhrzeit</button></div>
    ${d.art === "bis"
      ? `<div class="feld"><span>Bis</span><input type="time" data-b="bis"></div>`
      : `<div class="feld"><span>Dauer</span><input data-b="dauer" placeholder="z. B. 1:30, 2h, 90min"></div>`}` +
    fuss(`<button class="k" id="b_weg">Abbrechen</button><button class="k haupt" id="b_ok">Starten</button>`);
  binden(b, d);
  b.querySelectorAll("[data-a]").forEach(k => k.onclick = () => { d.art = k.dataset.a; merken(); blattZeichnen(); });
  $("b_weg").onclick = blattZu;
  $("b_ok").onclick = () => aktion({ aktion: "countdown", projekt: d.projekt, phase: d.phase, art: d.art,
                                      wert: d.art === "bis" ? d.bis : d.dauer }, { fehlerFeld: $("b_fehler") });
};

// ---- Pomodoro -----------------------------------------------------------------
BLAETTER.pomodoro = (b, d) => {
  const g = Z.optionen.pomodoro_grenzen;
  const zahl = (s, name, einheit) =>
    `<div class="feld"><span>${name}</span><div class="zeile2"><input type="number" data-b="${s}" min="${g[s][0]}" max="${g[s][1]}">
      <span class="schmal leise">${einheit}</span></div></div>`;
  b.innerHTML = `<h3>🍅 Pomodoro starten</h3><div class="unterzeile">${esc(d.projekt)} / ${esc(d.phase)}\nVorgeschlagen: die zuletzt benutzten Werte.</div>
    ${zahl("fokus", "Fokus", "Minuten")}${zahl("kurz", "Kurze Pause", "Minuten")}
    ${zahl("lang", "Lange Pause", "Minuten")}${zahl("nach", "Lange nach", "Pomodoros")}` +
    fuss(`<button class="k" id="b_weg">Abbrechen</button><button class="k haupt" id="b_ok">Starten</button>`);
  binden(b, d);
  $("b_weg").onclick = blattZu;
  $("b_ok").onclick = () => aktion({ aktion: "pomodoro", projekt: d.projekt, phase: d.phase,
    fokus: d.fokus, kurz: d.kurz, lang: d.lang, nach: d.nach }, { fehlerFeld: $("b_fehler") });
};

// ---- Nachtragen (mit Kalenderterminen des Tages) ---------------------------
BLAETTER.nachtragen = (b, d) => {
  b.innerHTML = `<h3>✎ Zeit nachtragen</h3>
    <div class="feld"><span>Projekt</span><select id="b_projekt">${projektOptionen(d.projekt)}</select></div>
    <div class="feld"><span>Phase</span><select id="b_phase">${phasenOptionen(d.phase)}</select></div>
    <div class="feld"><span>Datum</span><input type="date" data-b="datum" id="b_datum"></div>
    <div class="feld"><span></span><label class="klein"><input type="checkbox" data-b="nur_tag" data-neu> Nur Tag, ohne Uhrzeiten</label></div>
    ${d.nur_tag
      ? `<div class="feld"><span>Dauer</span><input data-b="dauer" placeholder="z. B. 1:30, 1,5h, 90min"></div>`
      : `<div class="feld"><span>Von – Bis</span><div class="zeile2"><input type="time" data-b="von"><span class="schmal">–</span><input type="time" data-b="bis"></div></div>`}` +
    fuss(`<button class="k" id="b_weg">Abbrechen</button><button class="k haupt" id="b_ok">Eintragen</button>`) +
    `<h2>Termine an diesem Tag</h2><div id="b_termine" class="liste"><div class="leer">Termine werden gelesen …</div></div>`;
  d._keinFokus = true;
  binden(b, d);
  projektPhaseVerdrahten(b, d);
  $("b_datum").addEventListener("change", () => termineLaden(d));    // anderer Tag, andere Termine
  $("b_weg").onclick = blattZu;
  $("b_ok").onclick = () => aktion({ aktion: "nachtragen", projekt: d.projekt, phase: d.phase, datum: d.datum,
    von: d.von, bis: d.bis, nur_tag: d.nur_tag, dauer: d.dauer }, { fehlerFeld: $("b_fehler") });
  termineLaden(d);
};

// Projekt/Phase im Blatt: „+ Neu …“ öffnet das passende Blatt und kehrt danach zurück
function projektPhaseVerdrahten(b, d) {
  const verbinde = (feld, was) => {
    if (!feld) return;
    feld.onchange = () => {
      if (feld.value === "__neu") {
        feld.value = d[was];
        blattOeffnen(was, { name: "", ordner: "", vonHand: false, fuer: was }, UI.blatt);
        return;
      }
      d[was] = feld.value; merken();
    };
  };
  verbinde(b.querySelector("#b_projekt"), "projekt");
  verbinde(b.querySelector("#b_phase"), "phase");
}

async function termineLaden(d) {
  const r = await api({ aktion: "termine", datum: d.datum });
  const kasten = $("b_termine");
  if (!kasten || !UI.blatt || UI.blatt.d !== d) return;        // Blatt inzwischen zu
  if (r.fehler || r.hinweis) { kasten.innerHTML = `<div class="leer">⚠ ${esc(r.fehler || r.hinweis)}</div>`; return; }
  if (!r.quellen.length) { kasten.innerHTML = `<div class="leer">Keine Kalender ausgewählt (Einstellungen → Kalender).</div>`; return; }
  if (!r.termine.length) { kasten.innerHTML = `<div class="leer">Keine Termine an diesem Tag.</div>`; return; }
  kasten.innerHTML = r.termine.map((t, i) => {
    const kopf = `<div><div class="titel">${esc(t.titel)}</div><div class="unter">${t.von}–${t.bis} · ${esc(t.kalender)}</div></div>`;
    if (t.uebernommen) return `<div class="termin fertig">${kopf}<div class="leise">✓ übernommen</div></div>`;
    if (!t.vorbei) return `<div class="termin fertig">${kopf}<div class="leise">noch nicht vorbei</div></div>`;
    const warn = t.konflikte.length ? `<div class="zeile2 klein" style="color:var(--warn)">⚠ überschneidet sich mit ${esc(t.konflikte.join(", "))}</div>` : "";
    return `<div class="termin">${kopf}<button class="k" data-t="${i}" ${t.konflikte.length ? "disabled" : ""}>✓ Übernehmen</button>
      <div class="zeile2"><select data-tp="${i}">${projektOptionen(t.projekt || d.projekt, false)}</select>
        <select data-tph="${i}">${phasenOptionen(t.phase || d.phase, false)}</select></div>${warn}</div>`;
  }).join("");
  kasten.querySelectorAll("[data-t]").forEach(k => k.onclick = () => {
    const i = k.dataset.t, t = r.termine[i];
    api({ aktion: "termin_uebernehmen", kennung: t.kennung,
          projekt: kasten.querySelector(`[data-tp="${i}"]`).value,
          phase: kasten.querySelector(`[data-tph="${i}"]`).value }).then(a => {
      if (a.fehler) meldung(a.fehler, true); else { meldung(a.meldung); zustandHolen(); kalenderAuffrischen(); }
      termineLaden(d);
    });
  });
}

// ---- Neues Projekt ---------------------------------------------------------
BLAETTER.projekt = (b, d) => {
  b.innerHTML = `<h3>Neues Projekt</h3>
    <div class="unterzeile">In den Ordner kommt die Datei Zeiterfassung.md.</div>
    <div class="feld"><span>Name</span><input id="b_name" data-b="name" placeholder="z. B. Bäckerei Müller"></div>
    <div class="feld"><span>Ordner</span><input id="b_ordner" data-b="ordner"></div>
    <div class="feld"><span></span><div><button class="k" id="b_waehlen">Ordner wählen …</button>
      <div class="klein" id="b_hinweis" style="margin-top:4px"></div></div></div>` +
    fuss(`<button class="k" id="b_weg">Abbrechen</button><button class="k haupt" id="b_ok">Anlegen</button>`);
  binden(b, d);
  const hinweis = () => $("b_hinweis").textContent = d.ordner && !d.vorhanden && !d.vonHand
    ? "Vorschlag — der Ordner wird beim Anlegen erstellt." : "";
  hinweis();
  let warte = null;
  // Solange du den Ordner nicht selbst geändert hast, folgt der Vorschlag dem Namen
  $("b_name").addEventListener("input", () => {
    if (d.vonHand) return;
    clearTimeout(warte);
    warte = setTimeout(async () => {
      const r = await api({ aktion: "ordner_vorschlag", name: d.name });
      d.ordner = r.ordner || ""; d.vorhanden = r.vorhanden; merken();
      if ($("b_ordner")) { $("b_ordner").value = d.ordner; hinweis(); }
    }, 250);
  });
  $("b_ordner").addEventListener("input", () => { d.vonHand = true; merken(); hinweis(); });
  $("b_waehlen").onclick = async () => {
    const r = await api({ aktion: "ordner_waehlen", start: d.ordner });
    if (r.ordner) { d.ordner = r.ordner; d.vonHand = true; merken(); blattZeichnen(); }
  };
  $("b_weg").onclick = blattZurueck;
  $("b_ok").onclick = async () => {
    const r = await api({ aktion: "projekt_anlegen", name: d.name, ordner: d.ordner });
    if (r.fehler) return $("b_fehler").textContent = r.fehler;
    meldung(r.meldung);
    UI.auswahl.projekt = r.projekt;
    await zustandHolen();
    const z = UI.blatt.zurueck;
    if (z) { z.d.projekt = r.projekt; }
    blattZurueck();
    timerSchluessel = null; timerZeichnen();
  };
};

// ---- Neue Phase ----------------------------------------------------------------
BLAETTER.phase = (b, d) => {
  b.innerHTML = `<h3>Neue Phase</h3>
    <div class="feld"><span>Name</span><input data-b="name" placeholder="z. B. Recherche"></div>` +
    fuss(`<button class="k" id="b_weg">Abbrechen</button><button class="k haupt" id="b_ok">Anlegen</button>`);
  binden(b, d);
  $("b_weg").onclick = blattZurueck;
  $("b_ok").onclick = async () => {
    const r = await api({ aktion: "phase_anlegen", name: d.name });
    if (r.fehler) return $("b_fehler").textContent = r.fehler;
    meldung(r.meldung);
    UI.auswahl.phase = r.phase;
    await zustandHolen();
    const z = UI.blatt.zurueck;
    if (z) { z.d.phase = r.phase; }
    blattZurueck();
    timerSchluessel = null; timerZeichnen();
  };
};

// ---- Eintrag bearbeiten ---------------------------------------------------------
BLAETTER.eintrag = (b, d) => {
  b.innerHTML = `<h3>Eintrag bearbeiten</h3><div class="unterzeile">${esc(d.projekt)} · ${esc(d.zellen[5] || "gemessen")}</div>
    <div class="feld"><span>Datum</span><input type="date" data-b="datum"></div>
    <div class="feld"><span></span><label class="klein"><input type="checkbox" data-b="nur_tag" data-neu> Nur Tag, ohne Uhrzeiten</label></div>
    ${d.nur_tag
      ? `<div class="feld"><span>Dauer</span><input data-b="dauer"></div>`
      : `<div class="feld"><span>Von – Bis</span><div class="zeile2"><input type="time" data-b="von"><span class="schmal">–</span><input type="time" data-b="bis"></div></div>`}
    <div class="feld"><span>Phase</span><select id="b_phase">${phasenOptionen(d.phase, false)}</select></div>
    <div class="feld"><span>Fokus</span><div class="segmente" id="b_fokus">
      ${["😄", "😐", "☹️"].map(f => `<button data-f="${f}" class="${d.fokus === f ? "an" : ""}">${f}</button>`).join("")}</div></div>
    <div class="feld"><span>Notiz</span><textarea data-b="notiz"></textarea></div>` +
    fuss(`<button class="k gefahr links" id="b_loeschen">Löschen</button>
          <button class="k" id="b_weg">Abbrechen</button><button class="k haupt" id="b_ok">Speichern</button>`);
  d._keinFokus = true;
  binden(b, d);
  projektPhaseVerdrahten(b, d);
  b.querySelectorAll("[data-f]").forEach(k => k.onclick = () => {
    d.fokus = d.fokus === k.dataset.f ? "" : k.dataset.f; merken(); blattZeichnen();
  });
  const zeile = { aktion: "", projekt: d.projekt, i: d.i, zellen: d.zellen };
  $("b_weg").onclick = blattZu;
  $("b_loeschen").onclick = () => aktion({ ...zeile, aktion: "eintrag_loeschen" }, { fehlerFeld: $("b_fehler") });
  $("b_ok").onclick = () => aktion({ ...zeile, aktion: "eintrag_aendern", datum: d.datum, von: d.von, bis: d.bis,
    nur_tag: d.nur_tag, dauer: d.dauer, phase: d.phase, fokus: d.fokus, notiz: d.notiz }, { fehlerFeld: $("b_fehler") });
};


// ===========================================================================
// 6. Kalender und Statistik
// ===========================================================================
//
// Das ist dieselbe Seite wie im Kalenderfenster der Menüleiste. Sie läuft als
// eingebettete Seite (iframe); frische Daten bekommt sie als Nachricht.

const rahmen = {};                 // "kalender"/"statistik" -> iframe
let kalenderStand = 0;

async function kalenderZeigen(welche) {
  if (rahmen[welche]) return kalenderAuffrischen(true);
  const r = await api({ aktion: "kalender_seite", ansicht: welche === "statistik" ? "statistik" : "tag" });
  if (r.fehler) return $("r_" + welche).innerHTML = `<div class="leer">${esc(r.fehler)}</div>`;
  const f = document.createElement("iframe");
  f.srcdoc = r.html;
  $("r_" + welche).innerHTML = "";
  $("r_" + welche).appendChild(f);
  rahmen[welche] = f;
  kalenderStand = Date.now();
}

// Neue Daten an die eingebetteten Seiten schicken (höchstens alle 5 s,
// außer es wurde gerade etwas geändert)
async function kalenderAuffrischen(nurWennAlt = false) {
  const offen = Object.values(rahmen);
  if (!offen.length || (nurWennAlt && Date.now() - kalenderStand < 60000)) return;
  kalenderStand = Date.now();
  const r = await api({ aktion: "kalender_daten" });
  if (r.daten) offen.forEach(f => f.contentWindow && f.contentWindow.postMessage({ zeit: "daten", daten: r.daten }, "*"));
}

// „Übernehmen“ in der eingebetteten Seite
window.addEventListener("message", async e => {
  if (!e.data || e.data.zeit !== "uebernehmen") return;
  const n = JSON.parse(e.data.nachricht);
  const r = await api({ aktion: "termin_uebernehmen", ...n });
  if (r.fehler) meldung(r.fehler, true); else meldung(r.meldung);
  zustandHolen();
  kalenderAuffrischen();
});


// ===========================================================================
// 7. Seite „Einträge“
// ===========================================================================

async function eintraegeZeichnen() {
  const s = $("r_eintraege");
  if (!UI.eintraegeProjekt) {
    const r = await api({ aktion: "uebersicht" });
    if (r.fehler) return s.innerHTML = `<div class="leer">${esc(r.fehler)}</div>`;
    if (!r.projekte.length) return s.innerHTML = `<div class="leer">Noch keine Projekte.</div>`;
    const max = Math.max(1, ...r.projekte.map(p => p.minuten));
    s.innerHTML = `<h2>Projekte</h2><div class="liste">` + r.projekte.map(p => `
      <div class="eintrag klickbar" data-p="${esc(p.projekt)}"><div class="haupt">
        <div class="titel">${esc(p.projekt)}</div>
        <div class="unter">${p.anzahl} ${p.anzahl === 1 ? "Eintrag" : "Einträge"}${p.letzter ? " · zuletzt " + datumLesbar(p.letzter) : ""}${p.phasen.length ? " · " + p.phasen.slice(0, 3).map(([ph, m]) => `${esc(ph)} ${std(m)}`).join(", ") : ""}</div>
        <div class="bahn"><div style="width:${p.minuten / max * 100}%"></div></div></div>
        <div class="zahl">${std(p.minuten)} h</div><div class="pfeil">›</div></div>`).join("") + `</div>`;
    s.querySelectorAll("[data-p]").forEach(z => z.onclick = () => { UI.eintraegeProjekt = z.dataset.p; merken(); eintraegeZeichnen(); });
    return;
  }
  const projekt = UI.eintraegeProjekt;
  const r = await api({ aktion: "eintraege", projekt });
  if (r.fehler) { UI.eintraegeProjekt = null; merken(); return eintraegeZeichnen(); }
  let h = `<button class="zurueck" id="e_zurueck">‹ Alle Projekte</button><h2 style="margin-top:0">${esc(projekt)}</h2>`;
  if (!r.eintraege.length) h += `<div class="karte leer">Noch keine Einträge.</div>`;
  else {
    h += `<div class="liste">`;
    let tag = null;
    for (const { i, zellen: z } of r.eintraege) {
      if (z[0] !== tag) { tag = z[0]; h += `<div class="tag-kopf">${datumLesbar(tag)}</div>`; }
      const zeit = z[1] === "–" ? "ohne Uhrzeit" : `${z[1]}–${z[2]}`;
      const extra = [z[4], z[5], z[6]].filter(Boolean).join(" · ");
      h += `<div class="eintrag klickbar" data-i="${i}"><div class="haupt">
        <div class="titel">${esc(zeit)}</div>
        <div class="unter">${esc(extra)}${z[7] ? " · " + esc(z[7]) : ""}</div></div>
        <div class="zahl">${esc(z[3])} h</div><div class="pfeil">›</div></div>`;
    }
    h += `</div>`;
  }
  s.innerHTML = h;
  $("e_zurueck").onclick = () => { UI.eintraegeProjekt = null; merken(); eintraegeZeichnen(); };
  s.querySelectorAll("[data-i]").forEach(z => z.onclick = () => {
    const e = r.eintraege.find(x => String(x.i) === z.dataset.i).zellen;
    const nurTag = e[1] === "–";
    blattOeffnen("eintrag", { projekt, i: Number(z.dataset.i), zellen: e, datum: e[0], nur_tag: nurTag,
      von: nurTag ? "09:00" : e[1], bis: nurTag ? "10:00" : e[2].replace(/\s*\(\+\d+\)/, ""),
      dauer: e[3], phase: e[4], fokus: e[6], notiz: e[7] });
  });
}


// ===========================================================================
// 8. Einstellungen
// ===========================================================================

function einstellungenUmschalten() {
  UI.einstellungen = !UI.einstellungen;
  merken();
  seitenUmschalten();
}

async function einstellung(schluessel, wert) {
  const r = await aktion({ aktion: "einstellung", schluessel, wert }, { blattBleibt: true });
  if (r) { await zustandHolen(); einstellungenZeichnen(); if (!r.meldung) meldung("Gespeichert"); }
}

async function einstellungenZeichnen() {
  const s = $("r_einstellungen");
  if (!Z) return;
  const e = Z.einstellungen, o = Z.optionen;
  const wahl = (schluessel, werte, aktuell) =>
    `<select data-e="${schluessel}">${Object.entries(werte).map(([w, n]) =>
      `<option value="${esc(w)}" ${w === aktuell ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>`;
  const liste = a => Object.fromEntries(a.map(x => [x, x]));
  s.innerHTML = `<button class="zurueck" id="s_zurueck">‹ Zurück</button>
    <h2>Darstellung</h2><div class="karte">
      <div class="feld"><span>Anzeige</span>${wahl("anzeige", o.anzeige, e.anzeige)}</div>
      <div class="feld"><span>Popup-Größe</span>${wahl("popup-groesse", o.groessen, e["popup-groesse"])}</div>
      <div class="feld"><span>Klick aufs Symbol</span>${wahl("menueleiste-klick", o.klick, e["menueleiste-klick"])}</div>
      <div class="feld"><span>Akzentfarbe</span>${wahl("akzentfarbe", liste(o.akzentfarben), e.akzentfarbe)}</div>
      <div class="feld"><span>Farbschema</span>${wahl("farbschema", liste(o.farbschemata), e.farbschema)}</div>
      <div class="klein">„Anzeige“ gilt für das Popup und das Fenster. Die Popup-Größe gilt für die GUI
        (das TUI braucht seine feste Breite). Das Farbschema gilt für das TUI.</div></div>
    <h2>Projekte</h2><div class="karte">
      <div class="feld"><span>Projektordner</span><div class="zeile2"><input id="s_ordner" value="${esc(e.projektordner)}">
        <button class="k schmal" id="s_ordner_waehlen">Wählen …</button></div></div>
      <div class="klein">Hier schlägt zeit Ordner für neue Projekte vor (oder findet passende vorhandene).</div></div>
    <h2>Pomodoro und Countdown</h2><div class="karte">
      <div class="feld"><span>Ton</span><div class="zeile2">${wahl("pomodoro-ton", liste(o.toene), e["pomodoro-ton"])}
        <button class="k schmal" id="s_probe">▶</button></div></div>
      <div class="feld"><span>„Noch X min“</span><div class="zeile2"><input type="number" min="1" max="60" id="s_mehr" value="${e["pomodoro-verlaengern"]}">
        <span class="schmal leise">Minuten</span></div></div></div>
    <h2>Kalender</h2><div class="karte">
      <div class="feld"><span>In Kalender schreiben</span><div class="zeile2">
        <label class="schalter schmal"><input type="checkbox" id="s_schreiben" ${e["kalender-schreiben"] === "an" ? "checked" : ""}><span></span></label>
        <span class="klein">erfasste Zeiten im Kalender „zeit“</span></div></div>
      <div class="feld" style="align-items:start"><span>Termine aus</span><div id="s_kalender" class="klein">Kalender werden gelesen …</div></div></div>
    <h2>Kalender-Regeln</h2><div id="s_regeln" class="liste"><div class="leer">…</div></div>
    <div class="karte">
      <div class="feld"><span>Wenn</span><div class="zeile2"><select id="r_art" class="schmal" style="width:auto">
        <option value="titel">Titel enthält</option><option value="kalender">Kalender ist</option></select>
        <input id="r_wert" placeholder="z. B. Meeting"></div></div>
      <div class="feld"><span>Dann</span><div class="zeile2">
        <select id="r_projekt"><option value="">? fragen</option>${projektOptionen(null, false)}</select>
        <select id="r_phase"><option value="">? fragen</option>${phasenOptionen(null, false)}</select></div></div>
      <div class="fuss" style="display:flex;justify-content:flex-end"><button class="k" id="r_neu">+ Regel hinzufügen</button></div></div>`;
  $("s_zurueck").onclick = einstellungenUmschalten;
  s.querySelectorAll("[data-e]").forEach(f => f.onchange = () => einstellung(f.dataset.e, f.value));
  $("s_probe").onclick = () => api({ aktion: "ton_probe", ton: s.querySelector('[data-e="pomodoro-ton"]').value });
  $("s_mehr").onchange = e2 => einstellung("pomodoro-verlaengern", Number(e2.target.value));
  $("s_ordner").onchange = e2 => einstellung("projektordner", e2.target.value);
  $("s_ordner_waehlen").onclick = async () => {
    const r = await api({ aktion: "ordner_waehlen", start: $("s_ordner").value });
    if (r.ordner) einstellung("projektordner", r.ordner);
  };
  $("s_schreiben").onchange = e2 => einstellung("kalender-schreiben", e2.target.checked ? "an" : "aus");
  $("r_neu").onclick = async () => {
    const r = await api({ aktion: "regel_hinzufuegen", art: $("r_art").value, wert: $("r_wert").value,
                          projekt: $("r_projekt").value, phase: $("r_phase").value });
    if (r.fehler) return meldung(r.fehler, true);
    $("r_wert").value = ""; regelnZeigen(r.regeln); meldung("Regel hinzugefügt");
  };
  // Kalender und Regeln kommen langsamer (die Kalender-App wird gefragt)
  api({ aktion: "regeln" }).then(r => r.regeln && regelnZeigen(r.regeln));
  const k = await api({ aktion: "kalender_namen" });
  const kasten = $("s_kalender");
  if (!kasten) return;
  if (k.problem) return kasten.textContent = "⚠ " + k.problem;
  const gewaehlt = (e["kalender-quellen"] || "").split(";").map(x => x.trim()).filter(Boolean);
  kasten.innerHTML = k.kalender.filter(n => n !== "zeit").map(n =>
    `<label style="display:block;margin:2px 0"><input type="checkbox" value="${esc(n)}" ${gewaehlt.includes(n) ? "checked" : ""}> ${esc(n)}</label>`).join("")
    || "In der Kalender-App gibt es keine Kalender.";
  kasten.querySelectorAll("input").forEach(c => c.onchange = () =>
    einstellung("kalender-quellen", [...kasten.querySelectorAll("input:checked")].map(x => x.value)));
}

function regelnZeigen(regeln) {
  const kasten = $("s_regeln");
  if (!kasten) return;
  kasten.innerHTML = regeln.length ? regeln.map((r, i) => `
    <div class="eintrag"><div class="haupt"><div class="titel">${esc(r.wenn)}</div>
      <div class="unter">→ ${esc(r.projekt)} / ${esc(r.phase)}</div></div>
      <button class="k leise" data-weg="${i}" title="Regel löschen">✕</button></div>`).join("")
    : `<div class="leer">Noch keine Regeln. Sie ordnen Termine automatisch einem Projekt zu.</div>`;
  kasten.querySelectorAll("[data-weg]").forEach(k => k.onclick = async () => {
    const r = await api({ aktion: "regel_loeschen", i: Number(k.dataset.weg) });
    if (r.regeln) regelnZeigen(r.regeln);
  });
}


// ===========================================================================
// 9. Tastatur
// ===========================================================================
//
//   Leertaste  Anhalten / Fortsetzen        S  Stoppen / beenden
//   N          Timer starten (Auswahl)      1–4  Reiter
//   ⌘,         Einstellungen                Esc  Blatt schließen / zurück

document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    if (UI.blatt) blattZurueck(); else if (UI.einstellungen) einstellungenUmschalten();
    return;
  }
  if (e.metaKey && e.key === ",") { e.preventDefault(); einstellungenUmschalten(); return; }
  if (e.metaKey || e.ctrlKey || e.altKey || UI.blatt || !Z) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  const l = Z.laufend;
  const taste = e.key.toLowerCase();
  if (taste === " " && l) {
    e.preventDefault();
    if (l.zustand === "angehalten") aktion({ aktion: "fortsetzen" });
    else if (l.erfasst_seit) aktion({ aktion: "anhalten" });
  } else if (taste === "s" && l) aktion({ aktion: "stop" });
  else if (taste === "n") starten("timer");
  else if ("1234".includes(taste) && taste !== "") reiterZeigen(["timer", "kalender", "statistik", "eintraege"][Number(taste) - 1]);
});


// ===========================================================================
// 10. Start
// ===========================================================================

erinnern();
document.querySelectorAll("#reiter button").forEach(b => b.onclick = () => reiterZeigen(b.dataset.reiter));
$("k_einstellungen").onclick = einstellungenUmschalten;
$("k_fenster").onclick = () => fetch(`${DIENST}/fenster?t=${ZEIT.kennwort}`, { method: "POST", mode: "no-cors" });
if (ZEIT.fenster) $("k_fenster").classList.add("versteckt");
$("schleier").addEventListener("mousedown", e => { if (e.target.id === "schleier") blattZurueck(); });

zustandHolen();
setInterval(ticken, 1000);
// Alle 2 Sekunden nachfragen, solange die GUI zu sehen ist (sonst alle 10)
let zaehler = 0;
setInterval(() => { zaehler++; if (!document.hidden || zaehler % 5 === 0) zustandHolen(); }, 2000);
setInterval(() => { if (!document.hidden) kalenderAuffrischen(true); }, 15000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) zustandHolen(); });
window.addEventListener("focus", zustandHolen);
