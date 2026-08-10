"""Command line entry point for retro-tools."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from retro_tools import __version__
from retro_tools.discs import is_candidate_file
from retro_tools.m3u import (
    find_system_folders,
    looks_like_roms_root,
    plan_path,
    system_tag,
)
from retro_tools.plan import Plan, PlanError, execute


def _print_plan(plan: Plan, root: Optional[Path], apply: bool) -> None:
    for note in plan.notes:
        print("  note: {}".format(note))
    if plan.notes:
        print()

    if plan.is_empty:
        print("Nothing to do.")
    else:
        header = "Actions" if apply else "Planned actions (dry run)"
        print("{}:".format(header))
        for action in plan.actions:
            print("  " + action.describe(root))
        counts = plan.counts()
        print(
            "\n{} folder(s), {} move(s), {} playlist(s).".format(
                counts["mkdir"], counts["move"], counts["write"]
            )
        )

    if plan.warnings:
        print("\nWarnings:")
        for warning in plan.warnings:
            print("  ! {}".format(warning))


def cmd_m3u(args: argparse.Namespace) -> int:
    if args.layout == "flat" and args.single_disc_folders:
        print(
            "error: --single-disc-folders has no effect with --layout flat "
            "(nothing gets moved into folders in that layout)",
            file=sys.stderr,
        )
        return 2

    root = Path(args.path).expanduser()
    if not root.exists():
        print("error: path does not exist: {}".format(root), file=sys.stderr)
        return 2

    plan = plan_path(
        root, single_disc_folders=args.single_disc_folders, layout=args.layout
    )
    _print_plan(plan, root, apply=args.apply)

    if plan.is_empty:
        return 0

    if not args.apply:
        print("\nNothing was changed. Re-run with --apply to make it so.")
        return 0

    try:
        execute(plan, force=args.force)
    except PlanError as exc:
        print("\nerror: refusing to apply:\n{}".format(exc), file=sys.stderr)
        return 1

    print("\nApplied.")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    if not root.is_dir():
        print("error: not a folder: {}".format(root), file=sys.stderr)
        return 2

    if looks_like_roms_root(root):
        folders = find_system_folders(root)
        print("Roms root: {}".format(root))
        print("{} tagged system folder(s):\n".format(len(folders)))
        for folder in folders:
            roms = sum(1 for p in folder.rglob("*") if is_candidate_file(p))
            subs = sum(1 for p in folder.iterdir() if p.is_dir())
            print(
                "  {:<45} tag={:<8} {:>4} file(s), {:>3} subfolder(s)".format(
                    folder.name, system_tag(folder), roms, subs
                )
            )
        untagged = [
            p
            for p in sorted(root.iterdir(), key=lambda p: p.name.lower())
            if p.is_dir() and not system_tag(p) and not p.name.startswith(".")
        ]
        if untagged:
            print("\nUntagged folders (NextUI will ignore these):")
            for folder in untagged:
                print("  {}".format(folder.name))
        return 0

    tag = system_tag(root)
    print("System folder: {} (tag={})".format(root.name, tag or "MISSING"))
    if tag is None:
        print(
            "  ! No uppercase (TAG) suffix. NextUI needs one, e.g. 'NES (FC)',\n"
            "    otherwise the folder will not appear in the menu."
        )
    files = sum(1 for p in root.rglob("*") if is_candidate_file(p))
    print("  {} candidate file(s)".format(files))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retro-tools",
        description="Organize retro game ROMs for handheld frontends.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser(
        "scan", help="Show system folders, tags and file counts."
    )
    scan.add_argument("path", help="Your Roms folder, or a single system folder.")
    scan.set_defaults(func=cmd_scan)

    m3u = subparsers.add_parser(
        "m3u",
        help="Group multi-disc games and write .m3u playlists.",
        description=(
            "Finds multi-disc games (Disc 1 / Disc 2 / ...) and writes a "
            "matching .m3u playlist so discs launch as one game and share "
            "saves. With --layout nextui (the default), each game's files "
            "also move into a folder named after the game, so NextUI/MinUI "
            "launch the folder directly. With --layout flat, the playlist is "
            "written next to the disc files and nothing is moved, for "
            "RetroArch and other libretro-based frontends. Dry run unless "
            "--apply is given."
        ),
    )
    m3u.add_argument("path", help="Your Roms folder, or a single system folder.")
    m3u.add_argument(
        "--layout",
        choices=("nextui", "flat"),
        default="nextui",
        help=(
            "Target frontend convention: 'nextui' (default) groups each game "
            "into its own folder for NextUI/MinUI; 'flat' just writes the "
            ".m3u beside the existing files, for RetroArch/libretro."
        ),
    )
    m3u.add_argument(
        "--apply",
        action="store_true",
        help="Actually move files and write playlists.",
    )
    m3u.add_argument(
        "--single-disc-folders",
        action="store_true",
        help=(
            "Also tuck loose single-disc releases into their own folder, "
            "so NextUI/MinUI launches the game directly instead of showing "
            "the folder. Only valid with --layout nextui."
        ),
    )
    m3u.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .m3u files.",
    )
    m3u.set_defaults(func=cmd_m3u)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
