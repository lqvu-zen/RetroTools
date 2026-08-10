"""Match ROMs against a libretro cheat database and write NextUI/MinUI .cht files.

NextUI resolves a game's cheat file as ``<Cheats root>/<TAG>/<name>.cht``,
where ``<name>`` is the exact basename NextUI loads for that game:

- the ROM's own filename, extension included, for a normal game
  (``Super Mario Land (World).zip`` -> ``Super Mario Land (World).zip.cht``)
- ``<folder>.m3u`` for a game folder NextUI folder-launches -- *any* folder
  containing a ``<folder-name>.m3u``, not just multi-disc ones. NextUI's
  ``Game_open()`` always re-checks for a sibling m3u named after the parent
  folder and substitutes it for the actual file that was opened, so a
  single-disc game tucked into its own folder (see ``m3u.py``'s
  ``--single-disc-folders``) needs a cheat named after its ``.m3u`` too, not
  its ``.chd``/``.cue``.

Source cheats come from a local checkout of the libretro cheat database
(https://github.com/libretro/libretro-database, the ``cht/`` folder), which
is organized by console into one ``.cht`` per game, sometimes with several
device-specific variants of the same game (``(Game Genie)``, ``(GameShark)``,
``(Xploder)``, ``(Game Buster)``, ``(Action Replay)``...). NextUI only ever
loads one ``.cht`` per game, so where several variants exist we pick the
plain (unsuffixed) one when there is one, and otherwise the best-ranked
device variant per ``DEVICE_PRIORITY`` -- flagged with a warning, since it's
a real judgment call, not a certainty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from retro_tools.discs import is_candidate_file
from retro_tools.m3u import find_system_folders, looks_like_roms_root, system_tag
from retro_tools.plan import Plan

#: NextUI system tag -> libretro-database cht/ console folder name.
#: Only systems with a confident, unambiguous match are listed; everything
#: else has no cheat coverage upstream (or the mapping is genuinely
#: ambiguous, e.g. a system with more than one same-named core) and is
#: skipped with a note instead of guessed.
TAG_TO_CHT_CONSOLE: Dict[str, str] = {
    "FBN": "FBNeo - Arcade Games",  # covers both Arcade (FBN) and Neo Geo (FBN)
    "A2600": "Atari - 2600",
    "A5200": "Atari - 5200",
    "A7800": "Atari - 7800",
    "LYNX": "Atari - Lynx",
    "COLECO": "Coleco - ColecoVision",
    "PRBOOM": "PrBoom",
    "FDS": "Nintendo - Family Computer Disk System",
    "GB": "Nintendo - Game Boy",
    "GBA": "Nintendo - Game Boy Advance",
    "MGBA": "Nintendo - Game Boy Advance",
    "GBC": "Nintendo - Game Boy Color",
    "FC": "Nintendo - Nintendo Entertainment System",
    "32X": "Sega - 32X",
    "SEGACD": "Sega - Mega-CD - Sega CD",
    "GG": "Sega - Game Gear",
    "MD": "Sega - Mega Drive - Genesis",
    "SMS": "Sega - Master System - Mark III",
    "PS": "Sony - PlayStation",
    "SFC": "Nintendo - Super Nintendo Entertainment System",
    "SUPA": "Nintendo - Super Nintendo Entertainment System",
    "PCE": "NEC - PC Engine - TurboGrafx 16",
}

#: Device-specific cheat variants, best first, used only when a game has no
#: plain (unsuffixed) cheat file to prefer.
DEVICE_PRIORITY = (
    "game buster",
    "gameshark",
    "action replay",
    "pro action replay",
    "game genie",
    "xploder",
)

_DEVICE_SUFFIX_RE = re.compile(
    r"\s*\((Game Genie|GameShark|Xploder|Game Buster|Action Replay|"
    r"Pro Action Replay|diff)\)\s*$",
    re.IGNORECASE,
)


def _strip_device_suffix(stem: str) -> str:
    """Peel trailing device/variant tags off a .cht filename stem."""
    prev = None
    while prev != stem:
        prev = stem
        stem = _DEVICE_SUFFIX_RE.sub("", stem)
    return stem.strip()


def _variant_rank(cht_path: Path, base_title: str) -> Tuple[int, ...]:
    """Lower is better. The plain (unsuffixed) file always wins."""
    suffix = cht_path.stem[len(base_title) :].strip().casefold()
    if not suffix:
        return (0,)
    if "diff" in suffix:
        return (2, suffix)
    for index, device in enumerate(DEVICE_PRIORITY):
        if device in suffix:
            return (1, index)
    return (1, len(DEVICE_PRIORITY))


def _load_cht_index(cht_dir: Path) -> Dict[str, List[Path]]:
    """base title (casefolded) -> every .cht variant on disk for it."""
    index: Dict[str, List[Path]] = {}
    for path in sorted(cht_dir.glob("*.cht")):
        base = _strip_device_suffix(path.stem)
        index.setdefault(base.casefold(), []).append(path)
    return index


@dataclass(frozen=True)
class LaunchTarget:
    """One entry NextUI's menu would show as a launchable game."""

    #: Title to look up in the cht database.
    title: str
    #: The exact basename NextUI loads -- what the cheat file must be named
    #: after (plus ``.cht``).
    cheat_name: str


def iter_launch_targets(directory: Path) -> List[LaunchTarget]:
    """Every game NextUI would list directly under *directory*.

    A subfolder counts only when it folder-launches, i.e. it holds a
    ``<folder-name>.m3u`` -- which covers both multi-disc groups and
    single-disc games tucked into their own folder. A subfolder without a
    matching playlist isn't something NextUI launches as one game, so it's
    left alone here (nothing to match cheats against).
    """
    targets = []
    for entry in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir():
            if entry.name.startswith("."):
                continue
            m3u = entry / (entry.name + ".m3u")
            if m3u.is_file():
                targets.append(
                    LaunchTarget(title=entry.name, cheat_name=m3u.name)
                )
            continue
        if is_candidate_file(entry):
            targets.append(LaunchTarget(title=entry.stem, cheat_name=entry.name))
    return targets


def plan_cheats_for_system(
    rom_dir: Path, cheats_root: Path, cht_dir: Path, tag: str
) -> Plan:
    """Match every game in one system folder against one cht console folder."""
    plan = Plan()
    if not rom_dir.is_dir():
        plan.warn("not a folder: {}".format(rom_dir))
        return plan
    if not cht_dir.is_dir():
        plan.note(
            "{}: no cheat database folder found at '{}'; skipped".format(
                rom_dir.name, cht_dir
            )
        )
        return plan

    index = _load_cht_index(cht_dir)
    targets = iter_launch_targets(rom_dir)

    matched = 0
    for target in targets:
        candidates = index.get(target.title.casefold())
        if not candidates:
            continue

        best = min(candidates, key=lambda p: _variant_rank(p, target.title))
        if len(candidates) > 1 and _variant_rank(best, target.title)[0] != 0:
            plan.warn(
                "{}: '{}' has {} cheat variants and no plain one ({}); "
                "using '{}'".format(
                    rom_dir.name,
                    target.title,
                    len(candidates),
                    ", ".join(sorted(p.name for p in candidates)),
                    best.name,
                )
            )

        target_path = cheats_root / tag / (target.cheat_name + ".cht")
        content = best.read_text(encoding="utf-8")
        if target_path.is_file() and target_path.read_text(encoding="utf-8") == content:
            matched += 1
            continue
        plan.write(target_path, content)
        matched += 1

    plan.note(
        "{}: matched {}/{} game(s) against '{}'".format(
            rom_dir.name, matched, len(targets), cht_dir.name
        )
    )
    return plan


def plan_cheats(
    roms_root: Path,
    cheats_root: Path,
    cht_root: Path,
    tag_to_console: Optional[Dict[str, str]] = None,
) -> Plan:
    """Plan cheat files for a Roms root or a single system folder."""
    if tag_to_console is None:
        tag_to_console = TAG_TO_CHT_CONSOLE

    plan = Plan()
    if not roms_root.is_dir():
        plan.warn("not a folder: {}".format(roms_root))
        return plan
    if not cht_root.is_dir():
        plan.warn("cht database folder not found: {}".format(cht_root))
        return plan

    if looks_like_roms_root(roms_root):
        folders = find_system_folders(roms_root)
    else:
        folders = [roms_root]

    unmapped = []
    for folder in folders:
        tag = system_tag(folder)
        if tag is None:
            plan.note("'{}' has no (TAG) suffix; skipped".format(folder.name))
            continue
        console = tag_to_console.get(tag)
        if console is None:
            unmapped.append(folder.name)
            continue
        cht_dir = cht_root / console
        plan.extend(plan_cheats_for_system(folder, cheats_root, cht_dir, tag))

    if unmapped:
        plan.note(
            "no cheat database mapping for: {}".format(", ".join(sorted(unmapped)))
        )

    return plan
