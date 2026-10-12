"""Farbschemata für das TUI im Menüleisten-Popup (und im Modus „Terminalfenster“).

Die Farben stammen aus den Standard-Profilen des macOS-Terminals. Sie stehen in
/System/Applications/Utilities/Terminal.app/Contents/Resources/Initial Settings/*.terminal
und wurden einmalig von dort ausgelesen. Durchsichtige Hintergründe (z. B. „Pro“
mit 85 % Deckkraft) sind hier deckend, weil das Popup nicht durchscheinen kann.

Jedes Schema hat:
    hintergrund, text, cursor, auswahl   Hex-Farben
    ansi                                  (optional) eigene 16 Grundfarben;
                                          sonst gelten die Terminal-Standardfarben
    akzent                                die Terminalfarbe (Nummer wie in
                                          zeit.AKZENTFARBEN), die bei Akzentfarbe
                                          „Standard“ genommen wird — so gewählt, dass
                                          sie zum Schema passt und gut lesbar ist
                                          (z. B. Türkis auf Weiß wäre kaum zu sehen)

"Standard" ist das dunkle Aussehen, das das Popup von Anfang an hatte, und ist
kein Terminal-Profil. Im Modus „Terminalfenster“ bleibt dann dein eigenes
Standardprofil des Terminals, wie es ist.
"""

# Die 16 Grundfarben des macOS-Terminals, in der Reihenfolge
# Schwarz, Rot, Grün, Gelb, Blau, Magenta, Cyan, Weiß, danach die hellen Varianten
TERMINAL_ANSI = ["#000000", "#990000", "#00a600", "#999900", "#0000b2", "#b200b2", "#00a6b2", "#bfbfbf",
                 "#666666", "#e50000", "#00d900", "#e5e500", "#0000ff", "#e500e5", "#00e5e5", "#e5e5e5"]

SCHEMATA = {
    "Standard":       {"akzent": 6, "hintergrund": "#1c1c1e", "text": "#f2f2f7", "cursor": "#f2f2f7", "auswahl": "#48484a",
                       "ansi": None},
    "Basic":          {"akzent": 4, "hintergrund": "#ffffff", "text": "#000000", "cursor": "#7f7f7f", "auswahl": "#b4d5fe"},
    "Pro":            {"akzent": 6, "hintergrund": "#000000", "text": "#f4f4f4", "cursor": "#606060", "auswahl": "#525252"},
    "Homebrew":       {"akzent": 2, "hintergrund": "#000000", "text": "#28fe14", "cursor": "#38fe27", "auswahl": "#0c2eee"},
    "Ocean":          {"akzent": 7, "hintergrund": "#2b66c9", "text": "#ffffff", "cursor": "#ffffff", "auswahl": "#2986ff"},
    "Grass":          {"akzent": 208, "hintergrund": "#13773d", "text": "#fff0a5", "cursor": "#8e2800", "auswahl": "#b64926"},
    "Red Sands":      {"akzent": 208, "hintergrund": "#8e3527", "text": "#d7c9a7", "cursor": "#ffffff", "auswahl": "#3d1916"},
    "Man Page":       {"akzent": 1, "hintergrund": "#fef49c", "text": "#000000", "cursor": "#7f7f7f", "auswahl": "#bfb875"},
    "Novel":          {"akzent": 1, "hintergrund": "#dfdbc3", "text": "#4d2f2d", "cursor": "#3a2322", "auswahl": "#878563"},
    "Silver Aerogel": {"akzent": 4, "hintergrund": "#929292", "text": "#000000", "cursor": "#e0e0e0", "auswahl": "#787a9c"},
    "Solid Colors":   {"akzent": 4, "hintergrund": "#ffffff", "text": "#000000", "cursor": "#cbcbcb", "auswahl": "#b4d5fe"},
    "Clear Dark":     {"akzent": 6, "hintergrund": "#212734", "text": "#e6e6e6", "cursor": "#e6e6e6", "auswahl": "#334e5e",
                       "ansi": ["#35424c", "#b45648", "#6caa71", "#c4ac62", "#6d96b4", "#bd7bcd", "#7ccbcd",
                                "#dee5eb", "#465c6d", "#df6c5a", "#79be7e", "#e5c872", "#67b5ed", "#d389e5",
                                "#84dde0", "#e5eff5"]},
    "Clear Light":    {"akzent": 4, "hintergrund": "#ffffff", "text": "#3a4851", "cursor": "#919191", "auswahl": "#e5ecf1",
                       "ansi": ["#2d3840", "#b45648", "#6caa71", "#c4ac62", "#5685a8", "#ad64be", "#69c6c9",
                                "#c1c8cc", "#506573", "#df6c5a", "#79be7e", "#e5c872", "#49a2e1", "#d389e5",
                                "#77e1e5", "#d8e1e7"]},
}

# Namen, unter denen xterm.js die 16 Grundfarben erwartet
_ANSI_NAMEN = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
               "brightBlack", "brightRed", "brightGreen", "brightYellow", "brightBlue",
               "brightMagenta", "brightCyan", "brightWhite"]


def schema(name):
    """Das Schema mit diesem Namen, unbekannte Namen ergeben „Standard“."""
    return SCHEMATA.get(name, SCHEMATA["Standard"])


def xterm_thema(name):
    """Das Schema als „theme“-Objekt für xterm.js (wird als JSON in die Seite geschrieben)."""
    s = schema(name)
    thema = {"background": s["hintergrund"], "foreground": s["text"], "cursor": s["cursor"],
             "cursorAccent": s["hintergrund"], "selectionBackground": s["auswahl"]}
    if name != "Standard":                    # "Standard" behält die xterm-eigenen Grundfarben
        thema.update(zip(_ANSI_NAMEN, s.get("ansi") or TERMINAL_ANSI))
    return thema


def schrift_auf_akzent(name, nummer):
    """Schriftfarbe (0 = Schwarz, 15 = helles Weiß) für die markierte Zeile, deren
    Hintergrund die Akzentfarbe ist. Schwarz auf dunklem Blau wäre unlesbar —
    darum wird hier nachgerechnet, wie hell die Akzentfarbe in diesem Schema ist."""
    palette = schema(name).get("ansi") or TERMINAL_ANSI
    farbe = palette[nummer] if nummer < 16 else "#ff8700"          # 208 = Orange
    r, g, b = (int(farbe[i:i + 2], 16) for i in (1, 3, 5))
    helligkeit = 0.299 * r + 0.587 * g + 0.114 * b                  # 0 (schwarz) … 255 (weiß)
    return 0 if helligkeit > 110 else 15
