#!/bin/bash
# =============================================================================
# install.sh — zeit installieren oder aktualisieren (macOS)
#
#   curl -fsSL https://raw.githubusercontent.com/keyanthx/zeit/main/install.sh | bash
#
# oder aus einem geklonten Repo heraus:   ./install.sh
#
# Was passiert:
#   1. Prüfen: macOS, Python 3.9 oder neuer. Fehlen Apples Entwicklerwerkzeuge
#      (sie bringen Python mit), bietet das Skript an, sie zu installieren.
#   2. zeit nach ~/.local/share/zeit laden (bzw. dort aktualisieren).
#      Aus einem geklonten Repo heraus bleibt zeit, wo es ist.
#   3. Den Befehl `zeit` einrichten: ~/.local/bin/zeit (eine Verknüpfung)
#   4. Falls nötig ~/.local/bin in den PATH deiner Shell eintragen
#   5. Menüleiste: SwiftBar — fehlt es, bietet das Skript an, es von
#      github.com/swiftbar zu laden; dann den Plugin-Ordner einrichten
#
# Vor jeder Installation fragt das Skript nach (Enter = ja). ZEIT_JA=1
# beantwortet alle Fragen mit Ja.
#
# Deine Daten (~/.config/zeit/ und die Zeiterfassung.md in deinen Projekt-
# ordnern) fasst das Skript nie an. Erneut ausführen = aktualisieren.
# =============================================================================

set -euo pipefail

REPO="keyanthx/zeit"
ZIEL="${ZEIT_ZIEL:-$HOME/.local/share/zeit}"
BIN="$HOME/.local/bin"

schritt() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }
ok()      { printf '  ✓ %s\n' "$1"; }
hinweis() { printf '  → %s\n' "$1"; }
abbruch() { printf '\n\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

# Ja/Nein-Frage, Enter = ja. Bei `curl … | bash` kommt das Skript über die
# normale Eingabe — die Antwort wird deshalb direkt vom Terminal gelesen.
# Gibt es kein Terminal (z. B. in einem anderen Skript), gilt „nein“.
fragen() {
  [ -n "${ZEIT_JA:-}" ] && return 0
  local antwort
  printf '  ? %s [J/n] ' "$1"
  if ! { read -r antwort </dev/tty; } 2>/dev/null; then echo; return 1; fi
  case "$antwort" in ""|j|J|ja|Ja|y|Y|yes) return 0 ;; *) return 1 ;; esac
}

# --- 1. Voraussetzungen -------------------------------------------------------
schritt "Voraussetzungen prüfen"
[ "$(uname)" = "Darwin" ] || abbruch "zeit läuft nur auf macOS (es nutzt Kalender, Mitteilungen und Fenster von macOS)."

# Auf einem frischen Mac ist /usr/bin/python3 nur ein Platzhalter, der die
# Entwicklerwerkzeuge nachinstallieren will. Darum zuerst danach schauen.
if ! command -v python3 >/dev/null 2>&1 || { [ "$(command -v python3)" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; }; then
  hinweis "Apples Entwicklerwerkzeuge fehlen noch — sie bringen Python mit, das zeit braucht."
  fragen "Jetzt installieren? (ein paar Minuten, ca. 1 GB)" \
    || abbruch "Ohne Python geht es nicht. Später einfach dieses Skript erneut starten."
  xcode-select --install >/dev/null 2>&1 || true
  hinweis "Es öffnet sich ein Fenster: dort auf „Installieren“ klicken."
  printf '  … warte auf die Installation '
  # Fertig ist sie, sobald xcode-select einen Ordner kennt (höchstens 1 Stunde)
  for _ in $(seq 1 720); do
    xcode-select -p >/dev/null 2>&1 && break
    printf '.'; sleep 5
  done
  echo
  xcode-select -p >/dev/null 2>&1 \
    || abbruch "Die Entwicklerwerkzeuge sind noch nicht da. Wenn die Installation fertig ist, dieses Skript erneut starten."
  ok "Entwicklerwerkzeuge installiert"
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || abbruch "zeit braucht Python 3.9 oder neuer (gefunden: $(python3 --version 2>&1))."
ok "macOS, $(python3 --version)"

# --- 2. Programm laden oder aktualisieren ------------------------------------
# Wird das Skript aus einem geklonten Repo gestartet, wird genau dieses benutzt.
HIER="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$HIER" ] && [ -f "$HIER/zeit.py" ] && [ -f "$HIER/install.sh" ]; then
  ZIEL="$HIER"
  schritt "zeit aus diesem Ordner benutzen"
  ok "$ZIEL"
elif [ -d "$ZIEL/.git" ] && command -v git >/dev/null 2>&1; then
  schritt "zeit aktualisieren"
  git -C "$ZIEL" pull --ff-only --quiet
  ok "$ZIEL ist auf dem neuesten Stand"
else
  schritt "zeit herunterladen"
  mkdir -p "$(dirname "$ZIEL")"
  if command -v git >/dev/null 2>&1 && xcode-select -p >/dev/null 2>&1; then
    rm -rf "$ZIEL"
    git clone --quiet --depth 1 "https://github.com/$REPO.git" "$ZIEL"
  else
    # Ohne git: das Archiv des main-Zweigs entpacken
    tmp="$(mktemp -d)"
    curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar -xz -C "$tmp"
    rm -rf "$ZIEL"
    mv "$tmp"/zeit-main "$ZIEL"
    rm -rf "$tmp"
  fi
  ok "nach $ZIEL"
fi
chmod +x "$ZIEL/zeit.py" "$ZIEL/swiftbar/zeit.15s.py"

# --- 3. Der Befehl `zeit` -----------------------------------------------------
schritt "Befehl \`zeit\` einrichten"
mkdir -p "$BIN"
ln -sf "$ZIEL/zeit.py" "$BIN/zeit"
ok "$BIN/zeit → $ZIEL/zeit.py"

# --- 4. PATH ------------------------------------------------------------------
# PATH ist die Liste der Ordner, in denen die Shell nach Befehlen sucht.
case ":$PATH:" in
  *":$BIN:"*) ok "$BIN ist schon im PATH" ;;
  *)
    case "$(basename "${SHELL:-zsh}")" in
      bash) profil="$HOME/.bash_profile" ;;
      *)    profil="$HOME/.zshrc" ;;
    esac
    if ! grep -qs 'zeit: ~/.local/bin' "$profil"; then
      printf '\n# zeit: ~/.local/bin in den PATH (eingetragen von zeit/install.sh)\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$profil"
    fi
    ok "$BIN in $profil eingetragen"
    hinweis "Gilt ab dem nächsten Terminalfenster (oder jetzt: source $profil)"
    ;;
esac

# --- 5. Menüleiste (optional, mit SwiftBar) ----------------------------------
schritt "Menüleiste (SwiftBar)"
# ZEIT_PROGRAMME: anderer Programme-Ordner (nur für Tests)
PROGRAMME="${ZEIT_PROGRAMME:-/Applications}"
swiftbar_app() {
  for a in "$PROGRAMME/SwiftBar.app" "$HOME/Applications/SwiftBar.app"; do
    [ -d "$a" ] && { echo "$a"; return 0; }
  done
  return 1
}

# SwiftBar fehlt? Die neueste Version von der offiziellen GitHub-Seite laden.
if ! swiftbar_app >/dev/null; then
  hinweis "SwiftBar fehlt — damit erscheint zeit oben in der Menüleiste (optional)."
  if fragen "SwiftBar jetzt installieren? (ca. 3 MB von github.com/swiftbar)"; then
    url="$(curl -fsSL https://api.github.com/repos/swiftbar/SwiftBar/releases/latest | python3 -c '
import json, sys
for a in json.load(sys.stdin)["assets"]:
    if a["name"].endswith(".zip"):
        print(a["browser_download_url"]); break')" || url=""
    if [ -n "$url" ]; then
      tmp="$(mktemp -d)"
      curl -fsSL "$url" -o "$tmp/SwiftBar.zip" && ditto -x -k "$tmp/SwiftBar.zip" "$tmp"
      ziel_ordner="$PROGRAMME"
      [ -w "$ziel_ordner" ] || { ziel_ordner="$HOME/Applications"; mkdir -p "$ziel_ordner"; }
      if [ -d "$tmp/SwiftBar.app" ]; then
        mv "$tmp/SwiftBar.app" "$ziel_ordner/"
        ok "SwiftBar installiert: $ziel_ordner/SwiftBar.app"
      else
        hinweis "Das Herunterladen hat nicht geklappt — SwiftBar gibt es auch auf https://swiftbar.app"
      fi
      rm -rf "$tmp"
    else
      hinweis "Die SwiftBar-Seite war nicht erreichbar — später erneut versuchen oder https://swiftbar.app"
    fi
  fi
fi

# SwiftBar da, aber noch kein Plugin-Ordner? Dann ~/SwiftBar anlegen und eintragen.
if app="$(swiftbar_app)" && [ -z "${ZEIT_SWIFTBAR_PLUGINS:-}" ] \
   && [ -z "$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)" ]; then
  mkdir -p "$HOME/SwiftBar"
  defaults write com.ameba.SwiftBar PluginDirectory "$HOME/SwiftBar"
  ok "Plugin-Ordner für SwiftBar: ~/SwiftBar"
  # Läuft SwiftBar schon, muss es neu starten, um den Ordner zu übernehmen
  osascript -e 'quit app "SwiftBar"' >/dev/null 2>&1 || true
  sleep 1
fi

if app="$(swiftbar_app)"; then
  # ZEIT_SWIFTBAR_PLUGINS: anderer Plugin-Ordner (nur für Tests)
  plugins="${ZEIT_SWIFTBAR_PLUGINS:-$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)}"
  plugins="${plugins/#\~/$HOME}"
  if [ -n "$plugins" ] && [ -d "$plugins" ]; then
    if [ "$plugins" -ef "$ZIEL/swiftbar" ]; then
      ok "SwiftBar liest das Plugin direkt aus $plugins"
    elif [ -e "$plugins/zeit.15s.py" ] && [ ! -L "$plugins/zeit.15s.py" ]; then
      # Eine echte Datei (keine Verknüpfung) gehört nicht uns — nie überschreiben
      hinweis "In $plugins liegt schon eine eigene zeit.15s.py — nicht angefasst."
    else
      ln -sf "$ZIEL/swiftbar/zeit.15s.py" "$plugins/zeit.15s.py"
      ok "Plugin verknüpft: $plugins/zeit.15s.py"
    fi
    # SwiftBar starten (falls es noch nicht läuft) und das Menü neu laden
    [ -z "${ZEIT_SWIFTBAR_PLUGINS:-}" ] && { pgrep -x SwiftBar >/dev/null || open -a "$app"; }
    open -g "swiftbar://refreshallplugins" 2>/dev/null || true
  else
    hinweis "SwiftBar ist installiert, hat aber noch keinen Plugin-Ordner."
    hinweis "Öffne SwiftBar einmal, wähle einen Ordner (z. B. ~/SwiftBar) und starte dieses Skript erneut."
  fi
else
  hinweis "Ohne SwiftBar — zeit läuft im Terminal. Für die Menüleiste später dieses Skript erneut starten."
fi

# --- Fertig -------------------------------------------------------------------
printf '\n\033[1;32m✓ zeit ist bereit.\033[0m\n\n'
echo "  zeit                 Oberfläche im Terminal öffnen"
echo "  zeit start <projekt> <phase>   Timer starten (legt Neues nach Rückfrage an)"
echo "  zeit tutorial        die geführte Tour (noch einmal) starten"
echo "  zeit --help          alle Befehle"
echo
echo "  Aktualisieren: dieses Skript erneut ausführen."
echo "  Entfernen:     $ZIEL/uninstall.sh"

# --- Beim ersten Mal: gleich mit dem Tutorial starten ---------------------------
# „Erstes Mal“ heißt: Das Tutorial wurde noch nie abgeschlossen. Bei einem
# Update passiert hier also nichts. ZEIT_NICHT_STARTEN=1 schaltet das ab.
# Bei `curl … | bash` ist die Tastatur nicht die Standardeingabe (dort kommt
# das Skript an) — deshalb liest das TUI ausdrücklich vom Terminal /dev/tty.
config="$HOME/.config/zeit/projekte.md"
if [ -z "${ZEIT_NICHT_STARTEN:-}" ] && ! grep -qs '^- tutorial: fertig' "$config" \
   && { exec 3</dev/tty; } 2>/dev/null; then
  exec 3<&-
  echo
  echo "  Gleich startet das Tutorial (Esc beendet es jederzeit) …"
  sleep 2
  "$ZIEL/zeit.py" tutorial </dev/tty >/dev/tty 2>&1 || true
fi
