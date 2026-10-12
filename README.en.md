# zeit — time tracking in plain Markdown

A small time tracker for macOS, inspired by [Watson](https://github.com/jazzband/Watson),
with one difference: there is **no database**. Every entry is a row in an
ordinary Markdown table, in a file called `Zeiterfassung.md` inside each
project's folder. What's in those files is everything the tool knows — you can
read them, edit them by hand, or hand them to an AI assistant for analysis.

Runs entirely local and offline. No account, no cloud, no dependencies beyond
Python's standard library.

> **Note:** the user interface (terminal, menu bar, GUI) is in **German**.
> *(zeit is German for "time".)* The commands are short and the
> [German README](README.md) has every detail.

## Install

Requirements: **macOS** and **Python 3.9+**. Python comes with Apple's command
line tools (`xcode-select --install` if you don't have them yet).

```bash
curl -fsSL https://raw.githubusercontent.com/keyanthx/zeit/main/install.sh | bash
```

This downloads zeit to `~/.local/share/zeit`, sets up the `zeit` command in
`~/.local/bin` (adding it to your PATH if needed) and, if
[SwiftBar](https://swiftbar.app) is installed, the menu bar plugin.

Prefer to do it yourself?

```bash
git clone https://github.com/keyanthx/zeit.git
cd zeit && ./install.sh
```

**Update:** run the install script again. **Uninstall:**
`~/.local/share/zeit/uninstall.sh` — your data is kept.

**Menu bar (optional):** `brew install --cask swiftbar`, open SwiftBar once and
choose a plugin folder, then run `install.sh` again.

## First steps

The first time you run `zeit`, a **guided tutorial** walks you through setup
(project folder, phases, menu bar) and hands-on exercises for the timer,
logging time later, Pomodoro and the calendar — using a practice project that is
removed afterwards. Esc ends it any time; run it again with `zeit tutorial`.
Or jump right in:

```bash
zeit start my-project planung    # asks first, creates the project + folder, starts the timer
zeit status                      # what's running?
zeit stop                        # stop and write the entry
zeit                             # open the terminal UI
```

New projects and phases are created on first use (after a confirmation, so a
typo never becomes a new category). New installs start with three neutral
phases — `planung` (planning), `umsetzung` (doing), `abstimmung` (alignment) —
add your own any time.

## Features

| | |
|---|---|
| **Timer** | `zeit start <project> <phase>`, `zeit stop`, `zeit anhalten` (pause), `zeit fortsetzen` (resume), `zeit abbrechen` (discard) |
| **Countdown** | `zeit countdown start <project> <phase> 2h` or `… bis 17:00` (until 5 pm) |
| **Pomodoro** | `zeit pomodoro start <project> <phase> --fokus 50 --kurz 10`; focus blocks are tracked, breaks are not |
| **Log time later** | `zeit nachtragen <project> <phase> gestern 9:00-11:30` (yesterday), `2h ab 14:00`, or just a day + duration |
| **Terminal UI** | `zeit` — arrow keys, Enter, Esc |
| **Calendar & stats** | day and week views, statistics per week/month/year |
| **macOS Calendar** | adopt past events from selected calendars as entries (with rules for project/phase), optionally write tracked time to a calendar called „zeit“ |
| **Feedback** | after each block: how focused were you (😄 😐 ☹️) + a note, stored in the table |
| **Menu bar** | via SwiftBar: dropdown menu, a popup with the terminal UI or a graphical UI, or a terminal window |

`zeit --help` lists all commands.

## Where things live

- **Your entries:** `<project folder>/Zeiterfassung.md` — a Markdown table:

  ```markdown
  ## Läuft gerade

  _(nichts)_

  ## Einträge

  | Datum      | Start | Ende  | Dauer | Phase    | Art | Fokus | Notiz |
  |------------|-------|-------|-------|----------|-----|-------|-------|
  | 2026-10-12 | 09:00 | 11:30 | 2:30  | planung  |     | 😄    |       |
  ```

  (Datum = date, Dauer = duration, Art = kind: 🍅 pomodoro, ⏳ countdown,
  ✎ logged later, 📅 from calendar.) Anything below `<!-- zeit-ende -->` is
  yours and never touched.
- **Your projects, phases and settings:** `~/.config/zeit/projekte.md` — also
  Markdown, also hand-editable.
- **The program:** `~/.local/share/zeit/` (after `install.sh`).
- **Cache:** `~/Library/Caches/zeit/` — safe to delete.

## Contributing

Issues and pull requests are welcome. Please run the tests first:

```bash
python3 -m unittest discover tests
```

They run in a temporary, empty home folder, so your real data is never touched.
zeit deliberately has no dependencies (Python standard library only); xterm.js
is vendored in `web/`. The code, comments and UI are in German.

## License

[MIT](LICENSE). xterm.js is MIT as well ([web/LICENSE-xterm.txt](web/LICENSE-xterm.txt)).
