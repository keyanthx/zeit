#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kalender_fenster.py — Kalender und Statistik als eigenes macOS-Fenster.

Die Menüleiste ruft das auf ("Kalender …", "Statistik …"). Drei Teile:

  1. Python rechnet alles mit kalender.py — genau dieselben Rechnungen wie im
     TUI — und schreibt das Ergebnis als Datei `daten.js`.
  2. Eine HTML-Seite (`kalender.html`) zeigt diese Daten nur an: Tag, Woche,
     Statistik. Sie rechnet nichts Eigenes, außer wo Blöcke hingezeichnet werden.
  3. Ein kleines Programm in JavaScript for Automation (macOS-Bordmittel)
     öffnet ein Fenster mit dieser Seite. Solange es offen ist, lässt es die
     Daten jede Minute neu erzeugen (⌘R: sofort), damit ein laufender Timer
     mitwächst — ohne dass die Ansicht zurückspringt.

Beide Dateien liegen in ~/Library/Caches/zeit/ — ein Zwischenspeicher, der
jederzeit gelöscht werden darf; deine Daten bleiben in den Markdown-Dateien.

Termine aus der Kalender-App erscheinen blass neben der erfassten Zeit. Ein
Klick darauf öffnet ein Dialogfeld; "Übernehmen" meldet die Seite an das
Fenster (WebKit-Nachricht), das dann `kalender_fenster.py uebernehmen …`
aufruft, den Eintrag schreiben lässt und die Daten neu erzeugt.

Aufruf:  kalender_fenster.py oeffnen [tag|woche|statistik]
         kalender_fenster.py erzeugen        (nur daten.js neu schreiben)
         kalender_fenster.py uebernehmen '<json>'   (vom Fenster benutzt)
"""

import json
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zeit  # noqa: E402
import kalender as k  # noqa: E402

ORDNER = Path.home() / "Library" / "Caches" / "zeit"
SEITE = ORDNER / "kalender.html"
DATEN = ORDNER / "daten.js"


# ===========================================================================
# 1. Daten erzeugen
# ===========================================================================

def _statistik_als_json(s, titel):
    """Die Statistik aus kalender.py in eine Form, die JSON versteht."""
    return {
        "titel": titel,
        "gesamt": s["gesamt"], "arbeitstage": s["arbeitstage"], "schnitt": s["schnitt"],
        "laengster": [s["laengster"][0].isoformat(), s["laengster"][1]] if s["laengster"] else None,
        "pro_tag": [[t.isoformat(), m] for t, m in s["pro_tag"]],
        "pro_projekt": s["pro_projekt"], "pro_phase": s["pro_phase"],
        "projekt_phase": s["projekt_phase"],
        "rhythmus": s["rhythmus"], "wochentage": s["wochentage"],
        "beginn": s["beginn"], "ende": s["ende"],
        "fokus": s["fokus"], "fokus_phase": s["fokus_phase"],
        "notizen": [[t.isoformat(), f"{st:%H:%M}" if st else None, p, ph, f, n]
                    for t, st, p, ph, f, n in s["notizen"]],
        "pomodoros": s["pomodoros"], "pomodoros_projekt": s["pomodoros_projekt"],
        "pomodoros_phase": s["pomodoros_phase"],
    }


def _termine_als_json(projekte, von, bis, alle, jetzt):
    liste, hinweis = k.termine_im_zeitraum(projekte, von, bis, alle)
    termine = []
    for a in liste:
        t = a.termin
        mitternacht = datetime.combine(t.start.date(), time(0))
        termine.append({
            "kennung": t.kennung, "titel": t.titel, "kalender": t.kalender,
            "d": t.start.date().isoformat(),
            "s": int((t.start - mitternacht).total_seconds() // 60),
            "e": min(1440, int((t.ende - mitternacht).total_seconds() // 60)),
            "uebernommen": a.uebernommen, "vorbei": t.ende <= jetzt,
            "projekt": a.projekt, "phase": a.phase, "konflikte": a.konflikte})
    return termine, hinweis


def daten(jetzt=None, meldung=None):
    """Alles, was die Seite braucht, als dict."""
    jetzt = jetzt or datetime.now().replace(microsecond=0)
    heute = jetzt.date()
    projekte, phasen = zeit.lade_config()
    frueh = k.fruehestes_datum(projekte)
    alle = k.bloecke(projekte, frueh, heute + timedelta(days=1), jetzt)

    bloecke = []
    for b in alle:
        mitternacht = datetime.combine(b.datum, time(0))
        bloecke.append({
            "p": b.projekt, "ph": b.phase, "art": b.art, "d": b.datum.isoformat(),
            "s": int((b.start - mitternacht).total_seconds() // 60) if b.start else None,
            "e": int((b.ende - mitternacht).total_seconds() // 60) if b.ende else None,
            "m": b.minuten, "lauf": b.laufend, "fokus": b.fokus, "notiz": b.notiz,
        })

    # Statistik für jeden Zeitraum, den es gibt — vom aktuellen rückwärts bis
    # zum frühesten Eintrag. Index 0 ist immer der aktuelle Zeitraum.
    statistik = {}
    for art in ("woche", "monat", "jahr"):
        liste, schritt = [], 0
        while True:
            von, bis, titel = k.zeitraum(art, heute, schritt)
            if bis < frueh and schritt < 0:
                break
            liste.append(_statistik_als_json(k.statistik(projekte, von, bis, jetzt, alle), titel))
            schritt -= 1
        statistik[art] = liste
    von, bis, titel = k.zeitraum("alles", heute, fruehester=frueh)
    statistik["alles"] = [_statistik_als_json(k.statistik(projekte, von, bis, jetzt, alle), titel)]

    # Termine: ein Jahr zurück bis zwei Wochen voraus
    termine, hinweis = _termine_als_json(projekte, min(frueh, heute - timedelta(days=365)),
                                         heute + timedelta(days=14), alle, jetzt)

    return {"heute": heute.isoformat(), "erzeugt": f"{jetzt:%H:%M}",
            "farben": k.projektfarben(projekte), "bloecke": bloecke, "statistik": statistik,
            "projekte": list(projekte), "phasen": phasen, "akzent": zeit.akzentfarbe()[1],
            "termine": termine, "hinweis": hinweis,
            # Ergebnis der letzten Übernahme, einmal als Hinweis eingeblendet
            "meldung": meldung, "meldung_nr": datetime.now().timestamp() if meldung else None}


def erzeugen(meldung=None):
    ORDNER.mkdir(parents=True, exist_ok=True)
    DATEN.write_text("window.DATEN = " + json.dumps(daten(meldung=meldung), ensure_ascii=False)
                     + ";\n", encoding="utf-8")


def uebernehmen(auftrag):
    """Vom Fenster aufgerufen: {"kennung", "projekt", "phase"}. Schreibt den
    Eintrag und erzeugt die Daten neu — mit einer Meldung, was passiert ist."""
    import termine
    projekte, _ = zeit.lade_config()
    start = datetime.fromtimestamp(int(auftrag["kennung"].rsplit("@", 1)[1]))
    try:
        treffer = [t for t in termine.lesen(start.date(), start.date(), zeit.kalender_quellen())
                   if t.kennung == auftrag["kennung"]]
        if not treffer:
            raise ValueError("Den Termin gibt es nicht mehr (verschoben oder gelöscht?).")
        t = treffer[0]
        k.termin_uebernehmen(projekte, t, auftrag["projekt"], auftrag["phase"])
        meldung = f"✓ Übernommen: {t.titel} → {auftrag['projekt']} / {auftrag['phase']}"
    except ValueError as grund:
        meldung = f"⚠ Nicht übernommen: {grund}"
    termine._ZWISCHENSPEICHER.clear()
    erzeugen(meldung)


# ===========================================================================
# 2. Die Seite
# ===========================================================================

HTML = r"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>zeit — Kalender</title>
<style>
  :root { --grund:#f6f6f4; --karte:#fff; --text:#1d1d1f; --leise:#86868b; --linie:#e3e3e0;
          --akzent:#0a84ff; }
  @media (prefers-color-scheme: dark) {
    :root { --grund:#1c1c1e; --karte:#2c2c2e; --text:#f2f2f7; --leise:#8e8e93; --linie:#3a3a3c; }
  }
  * { box-sizing:border-box; }
  body { margin:0; font:13px -apple-system, BlinkMacSystemFont, sans-serif; background:var(--grund);
         color:var(--text); user-select:none; -webkit-user-select:none; }
  header { position:sticky; top:0; z-index:5; display:flex; flex-wrap:wrap; align-items:center; gap:10px 14px;
           padding:12px 18px; background:var(--grund); border-bottom:1px solid var(--linie); }
  .reiter { display:flex; background:var(--linie); border-radius:8px; padding:2px; }
  .reiter button, .knopf { border:0; background:none; color:var(--text); font:inherit;
                           padding:5px 12px; border-radius:6px; cursor:pointer; }
  .reiter button.an { background:var(--karte); box-shadow:0 1px 2px rgba(0,0,0,.15); font-weight:600; }
  .knopf { background:var(--karte); border:1px solid var(--linie); }
  h1 { font-size:15px; margin:0; font-weight:600; }
  .rechts { margin-left:auto; color:var(--leise); font-size:12px; }
  main { padding:16px 18px 28px; }
  .leise { color:var(--leise); }
  /* Kalender */
  .raster { position:relative; display:grid; }
  .achse { position:relative; }
  .achse div { position:absolute; right:8px; font-size:11px; color:var(--leise); transform:translateY(-50%); }
  .spalte { position:relative; border-left:1px solid var(--linie); }
  .linie { position:absolute; left:0; right:0; border-top:1px solid var(--linie); }
  .linie.halb { border-top-style:dotted; opacity:.6; }
  .block { position:absolute; left:3px; right:3px; border-radius:5px; padding:3px 6px; overflow:hidden;
           color:#fff; font-size:11.5px; line-height:1.3; box-shadow:0 1px 2px rgba(0,0,0,.2); }
  .block b { font-weight:600; }
  .block.lauf { background-image:repeating-linear-gradient(45deg, rgba(255,255,255,.18) 0 6px, transparent 6px 12px); }
  .block.halb { right:32%; }
  .termin { position:absolute; left:69%; right:3px; border-radius:5px; padding:2px 5px; overflow:hidden;
            font-size:11px; line-height:1.25; border:1.5px dashed var(--leise); color:var(--text);
            background:color-mix(in srgb, var(--karte) 70%, transparent); cursor:pointer; }
  .termin:hover { border-color:var(--akzent); }
  .termin.fertig { border-style:solid; opacity:.55; cursor:default; }
  .hinweis { background:#fff3cd; color:#664d03; border-radius:8px; padding:8px 12px; margin-bottom:10px; }
  @media (prefers-color-scheme: dark) { .hinweis { background:#4d3d00; color:#ffe69c; } }
  .meldung { position:fixed; right:18px; bottom:18px; background:var(--text); color:var(--grund);
             padding:10px 14px; border-radius:8px; font-weight:600; z-index:30; }
  .schleier { position:fixed; inset:0; background:rgba(0,0,0,.35); display:flex; align-items:center;
              justify-content:center; z-index:20; }
  .dialog { background:var(--karte); border-radius:12px; padding:18px 20px; width:420px;
            box-shadow:0 10px 40px rgba(0,0,0,.3); }
  .dialog h3 { margin:0 0 4px; font-size:15px; }
  .dialog label { display:block; margin-top:12px; font-size:12px; color:var(--leise); }
  .dialog select { width:100%; font:inherit; padding:4px; margin-top:3px; }
  .dialog .knoepfe { display:flex; justify-content:flex-end; gap:8px; margin-top:18px; }
  .dialog .haupt { background:var(--akzent); color:#fff; border-color:var(--akzent); }
  .dialog .haupt:disabled { opacity:.4; }
  .kopfzeile { display:grid; margin-bottom:6px; }
  .kopfzeile div { text-align:center; font-weight:600; font-size:12px; }
  .kopfzeile .heute { color:var(--akzent); }
  .ohne { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 10px; }
  .chip { border-radius:10px; padding:2px 8px; color:#fff; font-size:11.5px; }
  .fuss { display:grid; margin-top:6px; }
  .fuss div { text-align:center; font-weight:600; }
  .legende { display:flex; gap:14px; margin-top:14px; flex-wrap:wrap; }
  .legende span::before { content:""; display:inline-block; width:10px; height:10px; border-radius:3px;
                          margin-right:5px; background:var(--f); vertical-align:-1px; }
  /* Statistik */
  .karten { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; }
  .karte { background:var(--karte); border-radius:10px; padding:12px 14px; box-shadow:0 1px 2px rgba(0,0,0,.06); }
  .karte .zahl { font-size:22px; font-weight:600; margin-top:2px; }
  section { background:var(--karte); border-radius:10px; padding:14px 16px; margin-top:14px;
            box-shadow:0 1px 2px rgba(0,0,0,.06); }
  section h2 { font-size:13px; margin:0 0 10px; }
  .zweispaltig { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  .zweispaltig section { margin-top:14px; }
  .zeile { display:grid; grid-template-columns:130px 1fr 52px 40px; gap:8px; align-items:center; margin:5px 0; }
  .bahn { height:10px; background:var(--linie); border-radius:5px; overflow:hidden; }
  .bahn div { height:100%; border-radius:5px; }
  .saeulen { display:flex; align-items:flex-end; gap:3px; height:130px; border-bottom:1px solid var(--linie); }
  .saeulen div { flex:1; background:var(--akzent); border-radius:3px 3px 0 0; min-height:0; position:relative; }
  .saeulen div:hover::after { content:attr(data-t); position:absolute; bottom:100%; left:50%;
      transform:translateX(-50%); white-space:nowrap; background:var(--text); color:var(--grund);
      font-size:11px; padding:2px 5px; border-radius:4px; }
  .beschriftung { display:flex; gap:3px; font-size:10px; color:var(--leise); }
  .beschriftung span { flex:1; text-align:center; overflow:hidden; white-space:nowrap; }
  .heat { display:grid; gap:2px; font-size:10px; }
  .heat .z { height:16px; border-radius:3px; background:var(--akzent); }
  .heat .k { color:var(--leise); text-align:center; }
  table { border-collapse:collapse; width:100%; }
  td { padding:3px 0; } td.z { text-align:right; font-variant-numeric:tabular-nums; }
  tr.projekt td { font-weight:600; padding-top:8px; }
  .leer { padding:40px; text-align:center; color:var(--leise); }
  /* Schmal (z. B. eingebettet im GUI-Popup): alles untereinander */
  @media (max-width: 600px) {
    header { padding:10px 12px; } main { padding:12px 12px 20px; }
    .zweispaltig { grid-template-columns:1fr; }
    .zeile { grid-template-columns:90px 1fr 46px 34px; }
    .dialog { width:calc(100vw - 32px); }
    .rechts { display:none; }
  }
</style></head>
<body>
<header>
  <div class="reiter" id="reiter"></div>
  <div id="navigation" style="display:flex; gap:6px; align-items:center"></div>
  <h1 id="titel"></h1>
  <div class="rechts" id="stand"></div>
</header>
<main id="inhalt"></main>
<script id="daten" src="daten.js"></script>
<script>
const FARBEN = ["#3b82f6", "#d946ef", "#eab308", "#22c55e", "#06b6d4", "#ef4444"];
const WT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const WT_LANG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
const START = "__START__";
let Z = { ansicht: START, tag: null, statArt: "woche", statIndex: 0 };

const D = () => window.DATEN;
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const std = m => { m = Math.round(m); return Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0"); };
const uhr = m => String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");
const iso = d => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
const vonIso = s => { const [j, m, t] = s.split("-").map(Number); return new Date(j, m - 1, t); };
const plusTage = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const wtag = d => (d.getDay() + 6) % 7;                 // Montag = 0
const montag = d => plusTage(d, -wtag(d));
const farbe = p => FARBEN[(D().farben[p] ?? 0) % FARBEN.length];
const tagesBloecke = d => D().bloecke.filter(b => b.d === iso(d));
const tagesTermine = d => (D().termine || []).filter(t => t.d === iso(d));
const datum = d => String(d.getDate()).padStart(2, "0") + "." + String(d.getMonth() + 1).padStart(2, "0") + "." + d.getFullYear();

function fenster(liste) {
  // Nur die Stunden, in denen etwas erfasst wurde (auf volle Stunden erweitert)
  const mit = liste.filter(b => b.s !== null);
  if (!mit.length) return [9 * 60, 17 * 60];
  const von = Math.floor(Math.min(...mit.map(b => b.s)) / 60) * 60;
  const bis = Math.min(1440, Math.ceil(Math.max(...mit.map(b => b.e)) / 60) * 60);
  return [von, Math.max(bis, von + 60)];
}

function kalender(tage) {
  const liste = tage.flatMap(tagesBloecke);
  const termine = tage.flatMap(tagesTermine);
  const [von, bis] = fenster(liste.concat(termine));   // Termine zählen fürs Zeitfenster mit
  const hoehe = Math.max(320, window.innerHeight - 250);
  const ppm = Math.max(0.9, hoehe / (bis - von));       // Pixel pro Minute
  const spalten = `58px repeat(${tage.length}, 1fr)`;
  const heute = D().heute;
  let h = D().hinweis ? `<div class="hinweis">⚠ ${esc(D().hinweis)}</div>` : "";

  if (tage.length > 1)
    h += `<div class="kopfzeile" style="grid-template-columns:${spalten}"><div></div>` +
         tage.map(d => `<div class="${iso(d) === heute ? "heute" : ""}">${WT[wtag(d)]} ${d.getDate()}.</div>`).join("") + "</div>";

  const ohne = liste.filter(b => b.s === null);
  if (ohne.length)
    h += `<div class="ohne"><span class="leise">ohne Uhrzeit:</span>` + ohne.map(b =>
      `<span class="chip" style="background:${farbe(b.p)}">${tage.length > 1 ? WT[wtag(vonIso(b.d))] + " · " : ""}${std(b.m)} ${esc(b.p)} · ${esc(b.ph)} ${esc(b.art)}</span>`).join("") + "</div>";

  if (!liste.some(b => b.s !== null) && !termine.length) {
    h += `<div class="leer">Keine Einträge mit Uhrzeit ${tage.length > 1 ? "in dieser Woche" : "an diesem Tag"}.</div>`;
  } else {
    h += `<div class="raster" style="grid-template-columns:${spalten}; height:${(bis - von) * ppm}px">`;
    h += `<div class="achse">`;
    for (let m = von; m <= bis; m += 60) h += `<div style="top:${(m - von) * ppm}px">${uhr(m)}</div>`;
    h += "</div>";
    for (const d of tage) {
      h += `<div class="spalte">`;
      for (let m = von; m < bis; m += 30)
        h += `<div class="linie ${m % 60 ? "halb" : ""}" style="top:${(m - von) * ppm}px"></div>`;
      for (const b of tagesBloecke(d).filter(b => b.s !== null)) {
        const hoch = Math.max(3, (b.e - b.s) * ppm - 2);
        const text = `<b>${esc(b.p)}</b> · ${esc(b.ph)} ${esc(b.art)} ${esc(b.fokus || "")}` +
          (hoch > 30 ? `<br>${uhr(b.s)}–${b.lauf ? "jetzt ▶" : uhr(b.e)} · ${std(b.m)}` : "");
        h += `<div class="block ${b.lauf ? "lauf" : ""} ${termine.length ? "halb" : ""}" style="top:${(b.s - von) * ppm + 1}px; height:${hoch}px; background:${farbe(b.p)}"
               title="${esc(b.p)} · ${esc(b.ph)} ${esc(b.art)} ${esc(b.fokus || "")}\n${uhr(b.s)}–${b.lauf ? "jetzt" : uhr(b.e)} (${std(b.m)})${b.notiz ? "\n„" + esc(b.notiz) + "“" : ""}">${hoch > 14 ? text : ""}</div>`;
      }
      for (const t of tagesTermine(d)) {
        const hoch = Math.max(3, (t.e - t.s) * ppm - 2);
        h += `<div class="termin ${t.uebernommen ? "fertig" : ""}" style="top:${(t.s - von) * ppm + 1}px; height:${hoch}px"
               ${t.uebernommen ? "" : `onclick="terminDialog('${esc(t.kennung)}')"`}
               title="📅 ${esc(t.titel)} [${esc(t.kalender)}]\n${uhr(t.s)}–${uhr(t.e)}${t.uebernommen ? " · übernommen" : " · klicken zum Übernehmen"}">${
               hoch > 14 ? `${t.uebernommen ? "✓ " : "📅 "}${esc(t.titel)}` : ""}</div>`;
      }
      h += "</div>";
    }
    h += "</div>";
  }
  if (tage.length > 1)
    h += `<div class="fuss" style="grid-template-columns:${spalten}"><div></div>` + tage.map(d => {
      const m = tagesBloecke(d).reduce((s, b) => s + b.m, 0);
      return `<div class="${m ? "" : "leise"}">${m ? std(m) : "–"}</div>`; }).join("") + "</div>";
  const namen = [...new Set(liste.map(b => b.p))];
  h += `<div class="legende">` + namen.map(p => `<span style="--f:${farbe(p)}">${esc(p)}</span>`).join("") + "</div>";
  return [h, liste.reduce((s, b) => s + b.m, 0), liste.filter(b => b.art === "🍅").length];
}

function balkenZeilen(werte, gesamt, zaehler, mitFarbe) {
  return werte.map(([name, m]) => `<div class="zeile"><span>${esc(name)}${zaehler[name] ? ` <span class="leise">🍅 ${zaehler[name]}</span>` : ""}</span>
    <div class="bahn"><div style="width:${gesamt ? m / gesamt * 100 : 0}%; background:${mitFarbe ? farbe(name) : "var(--akzent)"}"></div></div>
    <span style="text-align:right">${std(m)}</span><span class="leise" style="text-align:right">${gesamt ? Math.round(m / gesamt * 100) : 0} %</span></div>`).join("");
}

function statistik() {
  const s = D().statistik[Z.statArt][Z.statIndex];
  let h = `<div class="karten">
    <div class="karte"><div class="leise">Gesamt</div><div class="zahl">${std(s.gesamt)}</div></div>
    <div class="karte"><div class="leise">Arbeitstage</div><div class="zahl">${s.arbeitstage}</div></div>
    <div class="karte"><div class="leise">Ø pro Arbeitstag</div><div class="zahl">${std(s.schnitt)}</div></div>
    <div class="karte"><div class="leise">Längster Tag</div><div class="zahl">${s.laengster ? std(s.laengster[1]) : "–"}</div>
      <div class="leise">${s.laengster ? WT[wtag(vonIso(s.laengster[0]))] + " " + datum(vonIso(s.laengster[0])) : ""}</div></div>
    <div class="karte"><div class="leise">Pomodoros</div><div class="zahl">🍅 ${s.pomodoros}</div></div>
  </div>`;

  // Verlauf: pro Tag, bei Jahr pro Woche, bei "Alles" pro Monat
  let werte = s.pro_tag.map(([t, m]) => [vonIso(t), m]);
  let titel = "Verlauf pro Tag", name = d => d.getDate() + ".";
  if (Z.statArt === "jahr" || Z.statArt === "alles") {
    const gruppen = new Map();
    for (const [d, m] of werte) {
      const schl = Z.statArt === "jahr" ? iso(montag(d)) : d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
      gruppen.set(schl, (gruppen.get(schl) || 0) + m);
    }
    werte = [...gruppen.entries()];
    titel = Z.statArt === "jahr" ? "Verlauf pro Woche" : "Verlauf pro Monat";
    name = s => Z.statArt === "jahr" ? vonIso(s).getDate() + "." + (vonIso(s).getMonth() + 1) + "." : s.slice(5) + "/" + s.slice(2, 4);
  }
  const hoechster = Math.max(1, ...werte.map(w => w[1]));
  h += `<section><h2>${titel}</h2><div class="saeulen">` + werte.map(([n, m]) =>
    `<div style="height:${m / hoechster * 100}%" data-t="${esc(typeof n === "string" ? n : datum(n))}: ${std(m)}"></div>`).join("") +
    `</div><div class="beschriftung">` + werte.map(([n]) => `<span>${werte.length <= 31 ? name(n) : ""}</span>`).join("") + "</div></section>";

  h += `<div class="zweispaltig"><section><h2>Projekte</h2>${balkenZeilen(s.pro_projekt, s.gesamt, s.pomodoros_projekt, true) || '<span class="leise">–</span>'}</section>
        <section><h2>Phasen</h2>${balkenZeilen(s.pro_phase, s.gesamt, s.pomodoros_phase, false) || '<span class="leise">–</span>'}</section></div>`;

  h += `<section><h2>Projekt × Phase</h2><table>` + Object.entries(s.projekt_phase)
    .sort((a, b) => b[1].reduce((x, y) => x + y[1], 0) - a[1].reduce((x, y) => x + y[1], 0))
    .map(([p, phasen]) => `<tr class="projekt"><td style="color:${farbe(p)}">${esc(p)}</td><td class="z">${std(phasen.reduce((x, y) => x + y[1], 0))}</td></tr>` +
      phasen.map(([ph, m]) => `<tr><td>&nbsp;&nbsp;&nbsp;${esc(ph)}</td><td class="z">${std(m)}</td></tr>`).join("")).join("") + "</table></section>";

  // Fokus & Notizen (freiwilliges Feedback nach jedem Block)
  const FOKUS = [["😄", "fokussiert"], ["😐", "so lala"], ["☹️", "abgelenkt"]];
  const bewertet = FOKUS.reduce((x, [f]) => x + s.fokus[f].anzahl, 0);
  h += `<section><h2>Fokus &amp; Notizen</h2>`;
  if (bewertet) {
    h += FOKUS.map(([f, name]) => `<div class="zeile"><span>${f} ${name}</span>
      <div class="bahn"><div style="width:${s.fokus[f].anzahl / bewertet * 100}%; background:var(--akzent)"></div></div>
      <span style="text-align:right">${s.fokus[f].anzahl}×</span><span class="leise" style="text-align:right">${Math.round(s.fokus[f].anzahl / bewertet * 100)} %</span></div>`).join("");
    if (s.fokus[""].anzahl) h += `<p class="leise">ohne Bewertung: ${s.fokus[""].anzahl}×</p>`;
    const phasen = Object.entries(s.fokus_phase);
    if (phasen.length) h += `<table>` + phasen.map(([ph, w]) =>
      `<tr><td>${esc(ph)}</td>${FOKUS.map(([f]) => `<td class="z">${f} ${w[f]}</td>`).join("")}</tr>`).join("") + "</table>";
  } else h += `<span class="leise">Noch keine Fokus-Bewertungen in diesem Zeitraum.</span>`;
  if (s.notizen.length) h += `<div style="margin-top:12px">` + s.notizen.map(([t, st, p, ph, f, n]) =>
    `<p style="margin:8px 0"><span class="leise">${WT[wtag(vonIso(t))]} ${datum(vonIso(t)).slice(0, 6)}${st ? " " + st : ""} · ${esc(p)} / ${esc(ph)} ${esc(f)}</span><br>„${esc(n)}“</p>`).join("") + "</div>";
  h += "</section>";

  // Arbeitsrhythmus: Heatmap Wochentag × Stunde
  const stunden = [...Array(24).keys()].filter(st => s.rhythmus.some(w => w[st] > 0));
  h += `<section><h2>Arbeitsrhythmus</h2>`;
  if (stunden.length) {
    const von = Math.min(...stunden), bis = Math.max(...stunden) + 1;
    const max = Math.max(...s.rhythmus.flat());
    h += `<div class="heat" style="grid-template-columns:28px repeat(${bis - von}, 1fr)"><div></div>` +
      [...Array(bis - von).keys()].map(i => `<div class="k">${von + i}</div>`).join("");
    for (let w = 0; w < 7; w++) {
      h += `<div class="k">${WT[w]}</div>`;
      for (let st = von; st < bis; st++) {
        const wert = s.rhythmus[w][st];
        h += `<div class="z" style="opacity:${wert ? 0.15 + 0.85 * wert / max : 0.05}" title="${WT_LANG[w]} ${st}–${st + 1} Uhr: ${Math.round(wert)} min"></div>`;
      }
    }
    h += `</div><p class="leise">Typischer Tagesbeginn <b>${s.beginn === null ? "–" : uhr(s.beginn)}</b> · Tagesende <b>${s.ende === null ? "–" : uhr(s.ende)}</b></p>`;
    const maxWt = Math.max(1, ...s.wochentage);
    h += s.wochentage.map((m, w) => `<div class="zeile"><span>${WT_LANG[w]}</span><div class="bahn"><div style="width:${m / maxWt * 100}%; background:var(--akzent)"></div></div><span style="text-align:right">${m ? std(m) : "–"}</span><span></span></div>`).join("");
  } else h += `<span class="leise">Keine Einträge mit Uhrzeit.</span>`;
  h += "</section>";
  return [h, s.titel];
}

function zeichne() {
  if (!D()) return;
  if (!Z.tag) Z.tag = vonIso(D().heute);
  document.documentElement.style.setProperty("--akzent", D().akzent || "#0a84ff");
  document.getElementById("reiter").innerHTML = ["tag", "woche", "statistik"].map(a =>
    `<button class="${Z.ansicht === a ? "an" : ""}" onclick="Z.ansicht='${a}'; zeichne()">${{ tag: "Tag", woche: "Woche", statistik: "Statistik" }[a]}</button>`).join("");
  let html, titel, nav;
  if (Z.ansicht === "statistik") {
    [html, titel] = statistik();
    nav = `<div class="reiter">` + ["woche", "monat", "jahr", "alles"].map(a =>
      `<button class="${Z.statArt === a ? "an" : ""}" onclick="Z.statArt='${a}'; Z.statIndex=0; zeichne()">${{ woche: "Woche", monat: "Monat", jahr: "Jahr", alles: "Alles" }[a]}</button>`).join("") + "</div>" +
      (Z.statArt === "alles" ? "" : `<button class="knopf" onclick="blaettern(-1)">◀</button><button class="knopf" onclick="Z.statIndex=0; zeichne()">Aktuell</button><button class="knopf" onclick="blaettern(1)">▶</button>`);
  } else {
    const tage = Z.ansicht === "tag" ? [Z.tag] : [...Array(7).keys()].map(i => plusTage(montag(Z.tag), i));
    const [h, summe, tomaten] = kalender(tage);
    html = h;
    const kw = d => { const t = new Date(d); t.setDate(t.getDate() + 3 - wtag(t)); const j = new Date(t.getFullYear(), 0, 4);
                      return 1 + Math.round(((t - j) / 864e5 - 3 + wtag(j)) / 7); };
    titel = (Z.ansicht === "tag"
      ? `${WT_LANG[wtag(Z.tag)]}, ${datum(Z.tag)}`
      : `KW ${kw(tage[0])} · ${datum(tage[0]).slice(0, 6)} – ${datum(tage[6])}`)
      + ` <span class="leise">· gesamt ${std(summe)}${tomaten ? " · 🍅 " + tomaten : ""}</span>`;
    nav = `<button class="knopf" onclick="blaettern(-1)">◀</button><button class="knopf" onclick="Z.tag=vonIso(D().heute); zeichne()">Heute</button><button class="knopf" onclick="blaettern(1)">▶</button>`;
  }
  document.getElementById("navigation").innerHTML = nav;
  document.getElementById("titel").innerHTML = titel;
  document.getElementById("inhalt").innerHTML = html;
  document.getElementById("stand").textContent = "Stand " + D().erzeugt + " · ⌘R neu laden";
  meldungZeigen();
}

function terminDialog(kennung) {
  const t = D().termine.find(x => x.kennung === kennung);
  if (!t) return;
  const auswahl = (namen, vorschlag) => namen.map(n =>
    `<option ${n === vorschlag ? "selected" : ""}>${esc(n)}</option>`).join("");
  const gesperrt = !t.vorbei ? "Der Termin ist noch nicht vorbei — übernehmen geht erst danach." : "";
  const d = document.createElement("div");
  d.className = "schleier"; d.id = "dialog";
  d.innerHTML = `<div class="dialog">
    <h3>📅 ${esc(t.titel)}</h3>
    <div class="leise">${WT[wtag(vonIso(t.d))]} ${datum(vonIso(t.d))}, ${uhr(t.s)}–${uhr(t.e)} · ${std(t.e - t.s)} · ${esc(t.kalender)}</div>
    <label>Projekt<select id="d_projekt">${auswahl(D().projekte, t.projekt)}</select></label>
    <label>Phase<select id="d_phase">${auswahl(D().phasen, t.phase)}</select></label>
    ${t.projekt === "?" || t.phase === "?" || t.projekt === null ? `<p class="leise">Bitte prüfen — ${t.projekt === null ? "keine Regel passt" : "die Regel sagt „nachfragen“"}.</p>` : `<p class="leise">Vorschlag aus deinen Kalender-Regeln.</p>`}
    ${t.konflikte.length ? `<div class="hinweis">⚠ Überschneidet sich mit:<br>${t.konflikte.map(esc).join("<br>")}
       <label style="color:inherit"><input type="checkbox" id="d_trotzdem" onchange="document.getElementById('d_ok').disabled=!this.checked"> trotzdem übernehmen</label></div>` : ""}
    ${gesperrt ? `<div class="hinweis">${gesperrt}</div>` : ""}
    <div class="knoepfe"><button class="knopf" onclick="dialogZu()">Abbrechen</button>
      <button class="knopf haupt" id="d_ok" ${t.konflikte.length || gesperrt ? "disabled" : ""} onclick="terminUebernehmen('${esc(t.kennung)}')">Übernehmen</button></div>
  </div>`;
  d.onclick = e => { if (e.target === d) dialogZu(); };
  document.body.appendChild(d);
}
function dialogZu() { const d = document.getElementById("dialog"); if (d) d.remove(); }
function terminUebernehmen(kennung) {
  const nachricht = JSON.stringify({ kennung, projekt: document.getElementById("d_projekt").value,
                                     phase: document.getElementById("d_phase").value });
  dialogZu();
  // An das Fenster melden — es lässt Python den Eintrag schreiben und lädt neu
  if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.zeit)
    window.webkit.messageHandlers.zeit.postMessage(nachricht);
  else if (window.parent !== window)                    // eingebettet in der GUI
    window.parent.postMessage({ zeit: "uebernehmen", nachricht }, "*");
  else alert("Übernehmen geht nur im Fenster aus der Menüleiste.");
}
let gezeigteMeldung = null;
function meldungZeigen() {
  if (!D().meldung || D().meldung_nr === gezeigteMeldung) return;
  gezeigteMeldung = D().meldung_nr;
  const m = document.createElement("div");
  m.className = "meldung"; m.textContent = D().meldung;
  document.body.appendChild(m);
  setTimeout(() => m.remove(), 4000);
}

function blaettern(r) {
  if (Z.ansicht === "statistik") {
    const n = D().statistik[Z.statArt].length;
    Z.statIndex = Math.max(0, Math.min(n - 1, Z.statIndex - r));   // Index 0 = aktuell
  } else Z.tag = plusTage(Z.tag, r * (Z.ansicht === "tag" ? 1 : 7));
  zeichne();
}

// Das Fenster ruft das auf, nachdem daten.js neu erzeugt wurde:
// Skript austauschen, danach mit den neuen Daten neu zeichnen — die Ansicht bleibt.
function neuLaden() {
  const alt = document.getElementById("daten");
  const neu = document.createElement("script");
  neu.id = "daten"; neu.src = "daten.js?" + Date.now(); neu.onload = zeichne;
  alt.replaceWith(neu);
}

document.addEventListener("keydown", e => {
  if (e.metaKey) return;
  if (document.getElementById("dialog")) { if (e.key === "Escape") dialogZu(); return; }
  const t = { ArrowLeft: () => blaettern(-1), ArrowRight: () => blaettern(1),
    t: () => { Z.ansicht = "tag"; zeichne(); }, w: () => { Z.ansicht = "woche"; zeichne(); },
    s: () => { Z.ansicht = "statistik"; zeichne(); },
    h: () => { Z.tag = vonIso(D().heute); Z.statIndex = 0; zeichne(); },
    z: () => { if (Z.ansicht === "statistik") { const a = ["woche", "monat", "jahr", "alles"];
               Z.statArt = a[(a.indexOf(Z.statArt) + 1) % 4]; Z.statIndex = 0; zeichne(); } } }[e.key];
  if (t) { e.preventDefault(); t(); }
});
window.addEventListener("resize", zeichne);
// Eingebettet in der GUI: die GUI schickt frische Daten als Nachricht
window.addEventListener("message", e => {
  if (e.data && e.data.zeit === "daten") { window.DATEN = e.data.daten; zeichne(); }
});
document.getElementById("daten").onload = zeichne;
if (window.DATEN) zeichne();
</script></body></html>
"""


# ===========================================================================
# 3. Das Fenster
# ===========================================================================
#
# argv: 1 Pfad der Seite, 2 Programm, das daten.js neu erzeugt (Python),
#       3 dieses Skript. Das Fenster läuft, bis es geschlossen wird.

FENSTER_JXA = r"""
ObjC.import('Cocoa');
ObjC.import('WebKit');

var S = {};

function neuErzeugen() {
    var aufgabe = $.NSTask.launchedTaskWithLaunchPathArguments(S.python, $([S.skript, 'erzeugen']));
    aufgabe.waitUntilExit;
    S.web.evaluateJavaScriptCompletionHandler('neuLaden()', leer);
}

// Eine Rückmeldefunktion, die nichts tut. Nicht einfach null übergeben: JXA ruft
// die Rückmeldung trotzdem auf und stürzt dann ab (so beim Testen passiert).
function leer(ergebnis, fehler) {}

function uebernehmen(nachricht) {
    // Python schreibt den Eintrag und erzeugt die Daten neu (mit Meldung)
    var aufgabe = $.NSTask.launchedTaskWithLaunchPathArguments(S.python, $([S.skript, 'uebernehmen', nachricht]));
    aufgabe.waitUntilExit;
    S.web.evaluateJavaScriptCompletionHandler('neuLaden()', leer);
}

ObjC.registerSubclass({
    name: 'ZeitKalenderZiel',
    // Keine "protocols"-Angabe: JXA kennt WKScriptMessageHandler beim Registrieren
    // nicht und bricht sonst ab. WebKit stellt die Nachricht auch so zu.
    methods: {
        'neuLaden:': { types: ['void', ['id']], implementation: function (_) { neuErzeugen(); } },
        'userContentController:didReceiveScriptMessage:': { types: ['void', ['id', 'id']],
            implementation: function (_, nachricht) { uebernehmen(ObjC.unwrap(nachricht.body)); } },
        'windowWillClose:': { types: ['void', ['id']], implementation: function (_) {
            $.NSApplication.sharedApplication.terminate(null); } }
    }
});

function menuePunkt(titel, aktion, taste, ziel) {
    var punkt = $.NSMenuItem.alloc.initWithTitleActionKeyEquivalent(titel, aktion, taste);
    if (ziel) punkt.target = ziel;
    return punkt;
}

function run(argv) {
    S.python = argv[1]; S.skript = argv[2];
    var app = $.NSApplication.sharedApplication;
    app.setActivationPolicy($.NSApplicationActivationPolicyRegular);
    var ziel = $.ZeitKalenderZiel.alloc.init;

    // Menü, damit ⌘R, ⌘W und ⌘Q funktionieren
    var leiste = $.NSMenu.alloc.init;
    var appPunkt = $.NSMenuItem.alloc.init;
    leiste.addItem(appPunkt);
    var appMenue = $.NSMenu.alloc.initWithTitle('zeit');
    appMenue.addItem(menuePunkt('Neu laden', 'neuLaden:', 'r', ziel));
    appMenue.addItem(menuePunkt('Fenster schließen', 'performClose:', 'w', null));
    appMenue.addItem(menuePunkt('Beenden', 'terminate:', 'q', null));
    appPunkt.submenu = appMenue;
    app.mainMenu = leiste;

    var bildschirm = $.NSScreen.mainScreen.visibleFrame;
    var breite = Math.min(1180, bildschirm.size.width - 80), hoehe = Math.min(820, bildschirm.size.height - 60);
    var rahmen = $.NSMakeRect(0, 0, breite, hoehe);
    var fenster = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(rahmen, 15, 2, false);
    fenster.title = 'zeit — Kalender';
    fenster.center;
    fenster.delegate = ziel;
    fenster.releasedWhenClosed = false;

    // "zeit" ist der Kanal, über den die Seite Klicks ("übernehmen") meldet
    var einstellungen = $.WKWebViewConfiguration.alloc.init;
    einstellungen.userContentController.addScriptMessageHandlerName(ziel, 'zeit');
    S.web = $.WKWebView.alloc.initWithFrameConfiguration(rahmen, einstellungen);
    var url = $.NSURL.fileURLWithPath(argv[0]);
    S.web.loadFileURLAllowingReadAccessToURL(url, url.URLByDeletingLastPathComponent);
    fenster.contentView = S.web;

    // Jede Minute frische Daten — ein laufender Timer soll mitwachsen
    $.NSTimer.scheduledTimerWithTimeIntervalTargetSelectorUserInfoRepeats(60, ziel, 'neuLaden:', null, true);

    fenster.makeKeyAndOrderFront(null);
    app.activateIgnoringOtherApps(true);
    app.run;
}
"""


def eingebettet(ansicht="tag"):
    """Die Seite mit den Daten direkt darin — für die GUI, die sie als
    eingebettete Seite (iframe) zeigt. Dort gibt es keine Datei daten.js."""
    ansicht = ansicht if ansicht in ("tag", "woche", "statistik") else "tag"
    daten_js = "window.DATEN = " + json.dumps(daten(), ensure_ascii=False).replace("</", "<\\/") + ";"
    return (HTML.replace("__START__", ansicht)
            .replace('<script id="daten" src="daten.js"></script>', f'<script id="daten">{daten_js}</script>'))


def seite_schreiben(ansicht="tag"):
    """Schreibt Daten und Seite (die Startansicht steckt in der Seite)."""
    erzeugen()
    ansicht = ansicht if ansicht in ("tag", "woche", "statistik") else "tag"
    SEITE.write_text(HTML.replace("__START__", ansicht), encoding="utf-8")


def oeffnen(ansicht="tag"):
    """Öffnet das Fenster in einem eigenen Prozess und kehrt sofort zurück."""
    seite_schreiben(ansicht)
    prozess = subprocess.Popen(
        ["osascript", "-l", "JavaScript", "-", str(SEITE), sys.executable,
         str(Path(__file__).resolve())],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, text=True)
    prozess.stdin.write(FENSTER_JXA)
    prozess.stdin.close()          # erst jetzt weiß osascript, dass das Skript komplett ist


if __name__ == "__main__":
    if sys.argv[1:2] == ["erzeugen"]:
        erzeugen()
    elif sys.argv[1:2] == ["uebernehmen"]:
        uebernehmen(json.loads(sys.argv[2]))
    elif sys.argv[1:2] == ["oeffnen"]:
        oeffnen(sys.argv[2] if len(sys.argv) > 2 else "tag")
