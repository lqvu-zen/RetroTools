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

There is no lint/format tooling configured in this repo.

## Architecture

Everything is a **dry run by default** — `--apply` is the only thing that
touches the filesystem. This is implemented as a strict plan/execute split
across four modules with a one-directional dependency chain:

```
discs.py -> plan.py -> m3u.py -> cli.py
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

- **`cli.py`** — argparse front end (`scan`, `m3u` subcommands). Thin: builds
  a plan, prints it via `_print_plan()`, and only calls `plan.execute()` when
  `--apply` is passed.

Ambiguous or unsafe-to-silently-resolve situations (multiple cue sheets for
one disc, a folder mixing several games, a playlist whose name doesn't match
its folder, a disc group missing a loadable file) become `plan.warn()`
entries — printed, never acted on automatically.
