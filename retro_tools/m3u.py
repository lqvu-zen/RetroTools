"""Planners for NextUI multi-disc layout and .m3u playlists.

NextUI launches a folder directly (instead of navigating into it) when the
folder contains a playlist or cue sheet matching the folder's own name::

    Roms/PlayStation (PS)/Final Fantasy VII (USA)/
        Final Fantasy VII (USA).m3u
        Final Fantasy VII (USA) (Disc 1).cue
        ...

That is what these planners produce. All discs launched through one .m3u
share a memory card and save-state slot, and can be swapped in-game.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from retro_tools.discs import (
    SHEET_EXTS,
    DiscGroup,
    group_by_stem,
    group_discs,
    is_candidate_file,
)
from retro_tools.plan import Plan

#: A NextUI system folder keeps its uppercase emulator tag in parentheses,
#: e.g. "Game Boy Advance (GBA)" or "Arcade (FBN)".
SYSTEM_TAG_RE = re.compile(r"\(([A-Z0-9]{2,10})\)\s*$")


def system_tag(directory: Path) -> Optional[str]:
    """Return the emulator tag of a system folder, or None."""
    match = SYSTEM_TAG_RE.search(directory.name)
    return match.group(1) if match else None


def find_system_folders(root: Path) -> List[Path]:
    """All tagged system folders directly under *root* (a Roms directory)."""
    if not root.is_dir():
        return []
    return sorted(
        (child for child in root.iterdir() if child.is_dir() and system_tag(child)),
        key=lambda p: p.name.lower(),
    )


def looks_like_roms_root(directory: Path) -> bool:
    """True when *directory* holds tagged system folders rather than ROMs."""
    return system_tag(directory) is None and bool(find_system_folders(directory))


# --------------------------------------------------------------------------
# Planners
# --------------------------------------------------------------------------


def _plan_group(group: DiscGroup, plan: Plan, label: str) -> None:
    """Plan folder + moves + playlist for one loose multi-disc group."""
    lines = group.playlist_lines()
    if len(lines) < 2:
        plan.warn(
            "{}: '{}' has disc files but no loadable file for every disc; skipped".format(
                label, group.base
            )
        )
        return

    for number in group.numbers:
        entry = group.playlist_entry(number)
        if entry is None:
            plan.warn(
                "{}: '{}' disc {} has no loadable file; it will be moved but "
                "left out of the playlist".format(label, group.base, number)
            )
            continue
        sheets = [p for p in group.discs[number] if p.suffix.lower() in SHEET_EXTS]
        if len(sheets) > 1:
            plan.warn(
                "{}: '{}' disc {} has several cue sheets ({}); using '{}'".format(
                    label,
                    group.base,
                    number,
                    ", ".join(sorted(p.name for p in sheets)),
                    entry.name,
                )
            )

    target_dir = group.directory / group.base
    if target_dir.exists() and target_dir.is_dir():
        plan.note("{}: reusing existing folder '{}'".format(label, group.base))
    else:
        plan.mkdir(target_dir)

    for path in group.files:
        plan.move(path, target_dir / path.name)

    plan.write(target_dir / group.m3u_name, "\n".join(lines) + "\n")


def _plan_single_disc_folders(directory: Path, plan: Plan, label: str) -> None:
    """Tuck loose single-disc bin/cue sets into their own folder."""
    candidates = [p for p in directory.iterdir() if is_candidate_file(p)]
    for stem, files in group_by_stem(candidates).items():
        sheets = [p for p in files if p.suffix.lower() in SHEET_EXTS]
        if not sheets or len(files) < 2:
            continue
        target_dir = directory / stem
        if target_dir.exists() and target_dir.is_dir():
            plan.note("{}: reusing existing folder '{}'".format(label, stem))
        else:
            plan.mkdir(target_dir)
        for path in files:
            plan.move(path, target_dir / path.name)


def _plan_existing_folder(folder: Path, plan: Plan, label: str) -> None:
    """Write a missing .m3u for a game already sitting in its own folder."""
    candidates = [p for p in folder.iterdir() if is_candidate_file(p)]
    if not candidates:
        return

    existing_m3u = sorted(folder.glob("*.m3u"))
    groups = group_discs(candidates)
    if not groups:
        return
    if len(groups) > 1:
        plan.warn(
            "{}: folder '{}' mixes several games ({}); skipped".format(
                label, folder.name, ", ".join(g.base for g in groups)
            )
        )
        return

    group = groups[0]
    if len(group.numbers) < 2:
        return

    if existing_m3u:
        wanted = folder.name.casefold() + ".m3u"
        if not any(p.name.casefold() == wanted for p in existing_m3u):
            plan.warn(
                "{}: folder '{}' has '{}' but NextUI expects '{}.m3u'".format(
                    label, folder.name, existing_m3u[0].name, folder.name
                )
            )
        return

    lines = group.playlist_lines()
    if len(lines) < 2:
        plan.warn(
            "{}: folder '{}' has no loadable file for every disc; skipped".format(
                label, folder.name
            )
        )
        return

    # NextUI matches the playlist against the folder name, not the game title.
    plan.write(folder / (folder.name + ".m3u"), "\n".join(lines) + "\n")


def plan_system_folder(
    directory: Path,
    single_disc_folders: bool = False,
    recurse: bool = True,
) -> Plan:
    """Build the plan for one system folder, e.g. ``Roms/PlayStation (PS)``."""
    plan = Plan()
    if not directory.is_dir():
        plan.warn("not a folder: {}".format(directory))
        return plan

    label = directory.name

    loose = [p for p in directory.iterdir() if is_candidate_file(p)]
    for group in group_discs(loose):
        if len(group.numbers) < 2:
            plan.note(
                "{}: '{}' looks like a single-disc release; left alone".format(
                    label, group.base
                )
            )
            continue
        _plan_group(group, plan, label)

    if single_disc_folders:
        _plan_single_disc_folders(directory, plan, label)

    if recurse:
        for child in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir() and not child.name.startswith("."):
                _plan_existing_folder(child, plan, label)

    return plan


def plan_path(
    path: Path,
    single_disc_folders: bool = False,
) -> Plan:
    """Plan for either a Roms root or a single system folder."""
    plan = Plan()
    if not path.is_dir():
        plan.warn("not a folder: {}".format(path))
        return plan

    if looks_like_roms_root(path):
        folders = find_system_folders(path)
        plan.note(
            "treating '{}' as a Roms root ({} system folders)".format(
                path.name or str(path), len(folders)
            )
        )
        for folder in folders:
            plan.extend(
                plan_system_folder(folder, single_disc_folders=single_disc_folders)
            )
        return plan

    if system_tag(path) is None:
        plan.note(
            "'{}' has no (TAG) suffix; scanning it as a plain folder anyway".format(
                path.name or str(path)
            )
        )
    plan.extend(plan_system_folder(path, single_disc_folders=single_disc_folders))
    return plan
