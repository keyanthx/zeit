#!/bin/bash
# =============================================================================
# uninstall.sh — zeit wieder entfernen
#
# Aufruf: ./uninstall.sh  (mit --ja ohne Rückfrage)
#
# Entfernt den Befehl `zeit`, das Menüleisten-Plugin, den Hintergrund-Dienst
# und den Zwischenspeicher. Das Programm selbst wird nur gelöscht, wenn es am
# Standardort ~/.local/share/zeit liegt.
#
# Deine Daten bleiben: ~/.config/zeit/ (Projekte, Einstellungen) und die
# Zeiterfassung.md in deinen Projektordnern. Den Kalender „zeit“ (falls
# eingeschaltet) löschst du bei Bedarf selbst in der Kalender-App.
# =============================================================================

set -euo pipefail

ORDNER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STANDARD="$HOME/.local/share/zeit"

# Rückfrage — außer mit --ja (z. B. aus einem anderen Skript heraus)
if [ "${1:-}" != "--ja" ]; then
  printf 'zeit entfernen? Deine Daten in ~/.config/zeit bleiben erhalten. [j/N] '
  read -r antwort < /dev/tty || antwort=""
  case "$antwort" in j|J|ja|Ja|y|Y) ;; *) echo "Abgebrochen."; exit 0 ;; esac
fi

# Nur Verknüpfungen entfernen, die wirklich auf dieses zeit zeigen
weg_wenn_unser() {
  if [ -L "$1" ] && [[ "$(readlink "$1")" == "$ORDNER"/* ]]; then rm "$1" && echo "  ✓ $1 entfernt"; fi
}
weg_wenn_unser "$HOME/.local/bin/zeit"
plugins="${ZEIT_SWIFTBAR_PLUGINS:-$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)}"
plugins="${plugins/#\~/$HOME}"
[ -n "$plugins" ] && weg_wenn_unser "$plugins/zeit.15s.py"

pkill -f "$ORDNER/webterm.py dienst" 2>/dev/null && echo "  ✓ Hintergrund-Dienst beendet" || true
pkill -f "$ORDNER/pomodoro.py wecker" 2>/dev/null || true
rm -rf "$HOME/Library/Caches/zeit" && echo "  ✓ Zwischenspeicher gelöscht"

if [ "$ORDNER" = "$STANDARD" ]; then
  rm -rf "$STANDARD" && echo "  ✓ $STANDARD gelöscht"
else
  echo "  → Das Programm liegt in $ORDNER — diesen Ordner löschst du bei Bedarf selbst."
fi
echo
echo "zeit ist entfernt. Die Zeile für ~/.local/bin in ~/.zshrc bleibt (sie schadet nicht)."
