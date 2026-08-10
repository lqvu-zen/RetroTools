# retro-tools

Tools for organizing retro game ROMs on a [NextUI](https://nextui.loveretro.games/)
handheld's SD card. Pure Python standard library — no dependencies.

**Everything is a dry run until you pass `--apply`.**

## Quick start

From the project folder:

```
python -m retro_tools scan  E:\Roms
python -m retro_tools m3u   E:\Roms
python -m retro_tools m3u   E:\Roms --apply
```

Or install it so `retro-tools` works anywhere:

```
pip install -e .
retro-tools m3u E:\Roms
```

Both a `Roms` root and a single system folder work as the path — the tool
detects which one you gave it by looking for the uppercase `(TAG)` suffixes.

## Commands

### `scan`

Read-only overview: which system folders exist, their emulator tags, how many
files each holds, and which folders NextUI will ignore because they have no tag.

```
Roms root: E:\Roms
3 tagged system folder(s):

  Game Boy Advance (GBA)                        tag=GBA       412 file(s),   0 subfolder(s)
  PlayStation (PS)                              tag=PS         88 file(s),  12 subfolder(s)
  Sega CD (SEGACD)                              tag=SEGACD     24 file(s),   6 subfolder(s)

Untagged folders (NextUI will ignore these):
  Screenshots
```

### `m3u`

Finds multi-disc games, gives each one its own folder, and writes the `.m3u`
playlist NextUI needs. This turns:

```
Roms/PlayStation (PS)/
  Final Fantasy VII (USA) (Disc 1).bin
  Final Fantasy VII (USA) (Disc 1).cue
  Final Fantasy VII (USA) (Disc 2).bin
  Final Fantasy VII (USA) (Disc 2).cue
  Final Fantasy VII (USA) (Disc 3).bin
  Final Fantasy VII (USA) (Disc 3).cue
```

into:

```
Roms/PlayStation (PS)/Final Fantasy VII (USA)/
  Final Fantasy VII (USA).m3u
  Final Fantasy VII (USA) (Disc 1).bin
  ...
```

with `Final Fantasy VII (USA).m3u` containing:

```
Final Fantasy VII (USA) (Disc 1).cue
Final Fantasy VII (USA) (Disc 2).cue
Final Fantasy VII (USA) (Disc 3).cue
```

NextUI then launches the folder directly, shares one memory card and save-state
slot across all three discs, and lets you swap discs in-game with left/right on
the D-pad.

It also walks folders you have *already* made by hand and writes the missing
`.m3u` for them, naming it after the folder (which is what NextUI matches on).

**Options**

| Flag | Effect |
| --- | --- |
| `--apply` | Actually move files and write playlists. Without it, nothing changes. |
| `--single-disc-folders` | Also tuck loose single-disc `bin`+`cue` sets into their own folder, so NextUI launches the cue instead of showing a folder to open. |
| `--force` | Overwrite existing `.m3u` files. |

## What it recognises

Disc tokens are matched loosely, right-most first, so all of these group
correctly:

```
Game (USA) (Disc 1).cue        Game (USA) (Disk 2).cue
Game [Disc 1 of 2].chd         Game - CD3.cue
Example Sega CD Game (Disc 2).cue     <- the "CD" in the title is not a disc token
Policenauts (Disc 1) (Rev 1).cue      <- becomes "Policenauts (Rev 1)"
```

Playlist entries prefer `.cue` over the `.bin` it points at, then `.chd`,
`.gdi`, `.ccd`, `.cdi`, `.iso`, `.pbp`.

Left alone: `map.txt`, `doom.version`, existing `.m3u` files, saves and save
states, dotfiles, and any folder without an uppercase `(TAG)` when you point it
at a `Roms` root.

## Safety

- Dry run by default; `--apply` is the only thing that writes.
- Before any change, the whole plan is validated: no move overwrites an
  existing file, no `.m3u` is clobbered without `--force`. If any single check
  fails, **nothing** is done.
- Warnings (ambiguous cue sheets, folders mixing several games, playlists whose
  name doesn't match their folder) are printed but never acted on silently.

Still — it moves files on your SD card. Read the dry run first.

## Development

```
python -m unittest discover -v
```

Layout:

```
retro_tools/
  discs.py   disc-token parsing and grouping of related files
  plan.py    Action/Plan types, validation, execution
  m3u.py     the NextUI multi-disc planners
  cli.py     argparse front end
```

`plan.py` is the seam a GUI would sit on: build a `Plan`, show it, call
`execute()`.

## Roadmap

- `map.txt` manager (arcade display names, hiding BIOS zips)
- folder tag validator (bad/missing `(TAG)`, unsupported extensions)
- Collections builder
