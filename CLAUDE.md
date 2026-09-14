# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

retro-tools organizes retro game ROMs on a handheld's SD card: groups
multi-disc games (Disc 1/2/3 ...) and writes the `.m3u` playlists needed to
launch them as one game and share saves across discs. Pure Python standard
library, no runtime dependencies, Python >= 3.9.

Two target layouts, picked with `--layout`:

- `nextui` (default) — for NextUI/MinUI: each game's files move into their
  own folder, since those frontends launch a folder directly when it
  contains a matching playlist.
- `flat` — for RetroArch and other libretro-based frontends: the `.m3u` is
  written next to the existing disc files, nothing gets moved.
  `--single-disc-folders` (NextUI-only) is rejected in this layout.

There's also a `cheats` subcommand: it matches ROMs against a local checkout
of the [libretro-database](https://github.com/libretro/libretro-database)
`cht/` folder and writes NextUI/MinUI-format `.cht` files under a separate
`--cheats-root`. See `cheats.py` below.

A Qt GUI (`gui.py`) covers `scan`/`m3u`/`cheats` in one window. It needs
PySide6, an optional dependency (`pip install -e ".[gui]"`); nothing else in
the package imports it, so a CLI-only install is unaffected.

## Commands

Run tests:
```
python -m unittest discover -v
```

Run a single test file / case:
```
python -m unittest tests.test_discs -v
python -m unittest tests.test_discs.ParseDiscTests.test_variants -v
```

Run the CLI from source (no install needed):
```
python -m retro_tools scan E:\Roms
python -m retro_tools m3u  E:\Roms
python -m retro_tools m3u  E:\Roms --apply
```

Editable install (exposes the `retro-tools` command):
```
pip install -e .
```

Run the GUI (needs the optional `gui` extra):
```
pip install -e ".[gui]"
python -m retro_tools gui
```

There is no lint/format tooling configured in this repo.

## Architecture

Everything is a **dry run by default** — `--apply` is the only thing that
touches the filesystem. This is implemented as a strict plan/execute split
across seven modules with a one-directional dependency chain:

```
discs.py -> plan.py -> m3u.py -> cli.py -> gui.py
                     -> cheats.py -> cli.py     ^
                                gui_configs.py --+
```

- **`discs.py`** — pure parsing/grouping, no filesystem writes. `parse_disc()`
  pulls a `DiscName(base, number)` out of a filename stem using
  `DISC_TOKEN_RE`, matching the right-most disc token (so "Sega CD Game
  (Disc 2)" doesn't misparse "Sega CD" as the token). `group_discs()` groups
  files into `DiscGroup`s by casefolded base title; `DiscGroup.playlist_entry()`
  picks the best loadable file per disc via `PLAYLIST_PRIORITY` (`.cue` beats
  `.bin`, etc). `is_candidate_file()` is the single gate for "does retro-tools
  touch this file" (skips dotfiles, `IGNORED_NAMES`, `IGNORED_EXTS`).

- **`plan.py`** — filesystem-agnostic `Action`/`Plan` types (`mkdir`, `move`,
  `write`) plus `validate()` and `execute()`. Nothing outside this module
  calls `Path.mkdir`, `shutil.move`, or opens a file for writing. `validate()`
  is run again inside `execute()` before anything happens: no move may
  overwrite an existing file or collide with another planned target, no
  `.m3u` write clobbers an existing file without `force=True`. If any check
  fails, the whole plan is rejected via `PlanError` — nothing partial ever
  gets applied. This module is the intended seam for a future GUI: build a
  `Plan`, render it, call `execute()`.

- **`m3u.py`** — the layout-aware planners, built on top of `discs.py` and
  `plan.py`. `system_tag()` recognizes NextUI/MinUI's uppercase `(TAG)`
  folder suffix convention (e.g. `PlayStation (PS)`); `looks_like_roms_root()`
  tells a `Roms` root apart from a single system folder by whether it
  *contains* tagged folders vs. *is* one. `plan_path()` is the public entry
  point and dispatches to `plan_system_folder()` for one folder or all of
  them under a root; both take a `layout` arg (`"nextui"` default, or
  `"flat"`). Multi-disc groups go through `_plan_group()` (NextUI: new
  folder + moves + playlist) or `_plan_group_flat()` (flat: playlist only,
  written beside the untouched files, skipped on rerun once its content
  already matches) — both share their warning/validation logic via
  `_validated_playlist_lines()`. `_plan_single_disc_folders()` (opt-in via
  `--single-disc-folders`, NextUI layout only) tucks loose single-disc
  releases into their own folder, carrying along and path-correcting any
  matching sibling `.m3u`. `_plan_existing_folder()` (folders the user
  already made by hand, either layout — writes only the missing `.m3u`,
  named after the *folder*, not the game title) also calls
  `_adopt_orphaned_playlist()` to pull in and fix a stray same-named `.m3u`
  left in the parent by an earlier run. Path-prefix fixes in both go through
  `_relocated_playlist_lines()`, which only rewrites an entry when its
  filename still matches a real file — anything else is a warning, not a
  guess.

- **`cheats.py`** — matches ROMs against a local libretro-database `cht/`
  checkout and plans NextUI/MinUI `.cht` files. `TAG_TO_CHT_CONSOLE` maps a
  NextUI `(TAG)` to a cht console folder name; only confident, unambiguous
  mappings are listed, everything else is reported as unmapped rather than
  guessed. `iter_launch_targets()` enumerates what NextUI's menu actually
  shows for a system folder — reusing `m3u.py`'s exact convention: a
  subfolder counts only if it holds a `<folder-name>.m3u` (this is true for
  *any* folder-launched game, not just multi-disc ones — confirmed from
  NextUI's own `Game_open()` C source, which always re-derives the cheat
  lookup name from that sibling m3u when present). `plan_cheats_for_system()`
  matches each target's title against the cht folder's index
  (`_load_cht_index()`, keyed by title with any trailing device tag —
  `(Game Genie)`, `(GameShark)`, etc., stripped via `_strip_device_suffix()`)
  and writes whichever `.cht` file `_variant_rank()` ranks best: a plain
  (unsuffixed) file always wins outright; when only device-specific variants
  exist, the pick is still automatic but comes with a `plan.warn()`, since
  NextUI only ever loads one `.cht` per game and there's no plain file to
  fall back on. No match at all is not warned about (expected at this scale,
  e.g. romhacks/translations with no upstream cheat entry) — only summarized
  via a per-system `plan.note()` of matched-vs-total.

- **`cli.py`** — argparse front end (`scan`, `m3u`, `cheats`, `gui`
  subcommands). Thin: builds a plan, prints it, and only calls
  `plan.execute()` when `--apply` is passed. `render_plan()`/
  `render_cheats_plan()` format the same thing `_print_plan()`/
  `_print_cheats_plan()` print, as a `List[str]`, so an `--apply` run can
  also hand it to `write_run_log()` — every applied `m3u`/`cheats` run
  writes a `.retro-tools-<command>-log-<timestamp>.txt` next to what it
  touched (the scanned folder for `m3u`, `--cheats-root` for `cheats`),
  recording a `command` string (the literal CLI argv, or an equivalent
  string the GUI synthesizes) and everything that was printed, including a
  failed apply's `PlanError`. The dotfile name keeps it invisible to every
  scanner in this repo (`is_candidate_file()` excludes dotfiles). Dry runs
  are never logged — writing a log is itself a filesystem write, and the
  dry-run-by-default guarantee above requires `--apply` to be the only thing
  that touches disk. `cheats` renders compactly (target paths + notes, never
  write content) for the same reason `render_cheats_plan()` differs from
  `render_plan()`: `.cht` files can run to dozens of long code lines each.
  These render/log functions (plus `render_scan_report()`, extracted from
  `cmd_scan()`) are exported specifically so `gui.py` can reuse them rather
  than re-implementing output formatting. `cmd_gui()` imports `gui.py` lazily
  so a CLI-only install (no PySide6) never fails just from importing `cli.py`.

- **`gui.py`** — a PySide6 window with one tab per subcommand (`scan`,
  `m3u`, `cheats`), sitting on the same plan/execute seam as the CLI: each
  tab's Preview button builds a `Plan` via the same `m3u.py`/`cheats.py`
  planners the CLI uses and renders it with `cli.py`'s `render_plan()`/
  `render_cheats_plan()`, so the two frontends describe a plan identically.
  Apply only stays enabled while the on-screen options still match what was
  last previewed (`_form_state()` snapshots path/options and is compared on
  every Apply click) — changing anything after Preview disables Apply again,
  same spirit as the CLI needing a fresh dry-run read before `--apply`.
  `MainWindow` also owns a "device config" bar above the tabs (two
  `QComboBox`es — Device, then OS — plus Save As…/Delete) built on
  `gui_configs.py`: **Save As…** snapshots the M3U tab's Roms path plus every
  tab's own options into one `DeviceConfig` saved under a device name and an
  OS name (so a TrimUI Brick running NextUI and the same TrimUI Brick running
  Spruce OS are two leaves under one device, not one flat name); picking a
  saved Device then OS pushes its fields back into Scan/M3U/Cheats. Picking a
  device alone just repopulates the OS dropdown for that device — nothing
  loads until an OS is also picked. Optional dependency:
  `pip install -e ".[gui]"`; nothing else in the package imports PySide6.

- **`gui_configs.py`** — persistence for `gui.py`'s device configs: a
  `DeviceConfig` dataclass plus `load_configs()`/`save_configs()` reading and
  writing `{device: {os: DeviceConfig}}` as plain JSON at
  `~/.retro-tools/configs.json`. Deliberately has no Qt import, unlike the
  rest of the GUI, specifically so it's covered by `tests/test_gui_configs.py`
  without PySide6 installed — the one piece of `gui.py`'s logic that has
  automated test coverage. `load_configs()` drops unknown `DeviceConfig`
  fields and fills missing ones from its defaults, so a config saved by an
  older or newer version of this tool still loads; a device or OS entry
  that isn't shaped like a nested mapping is skipped, and a device left with
  no valid OS entries is dropped entirely.

Ambiguous or unsafe-to-silently-resolve situations (multiple cue sheets for
one disc, a folder mixing several games, a playlist whose name doesn't match
its folder, a disc group missing a loadable file) become `plan.warn()`
entries — printed, never acted on automatically.
