"""Command line entry point for retro-tools."""

from __future__ import annotations

import argparse
import datetime
import shlex
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from retro_tools import __version__
from retro_tools.cheats import plan_cheats
from retro_tools.discs import is_candidate_file
from retro_tools.m3u import (
    find_system_folders,
    looks_like_roms_root,
    plan_path,
    system_tag,
)
from retro_tools.plan import Plan, PlanError, execute


def render_plan(plan: Plan, root: Optional[Path], apply: bool) -> List[str]:
    lines = []
    for note in plan.notes:
        lines.append("  note: {}".format(note))
    if plan.notes:
        lines.append("")

    if plan.is_empty:
        lines.append("Nothing to do.")
    else:
        header = "Actions" if apply else "Planned actions (dry run)"
        lines.append("{}:".format(header))
        for action in plan.actions:
            lines.append("  " + action.describe(root))
        counts = plan.counts()
        lines.append(
            "\n{} folder(s), {} move(s), {} playlist(s).".format(
                counts["mkdir"], counts["move"], counts["write"]
            )
        )

    if plan.warnings:
        lines.append("\nWarnings:")
        for warning in plan.warnings:
            lines.append("  ! {}".format(warning))
    return lines


def _print_plan(plan: Plan, root: Optional[Path], apply: bool) -> List[str]:
    lines = render_plan(plan, root, apply)
    print("\n".join(lines))
    return lines


def write_run_log(directory: Path, prefix: str, lines: List[str], command: str) -> Path:
    """Record what an --apply run did. Never called for a dry run -- writing
    a log is itself a filesystem write, and dry runs must touch nothing.

    *command* is the invocation that produced this run: the literal argv for
    the CLI, or an equivalent CLI-style string synthesized by the GUI, so the
    log stays a useful, reproducible record regardless of which frontend
    triggered it."""
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now()
    log_path = directory / ".retro-tools-{}-log-{}.txt".format(
        prefix, timestamp.strftime("%Y%m%d-%H%M%S")
    )
    header = [
        "retro-tools {} run log".format(prefix),
        "when: {}".format(timestamp.isoformat(timespec="seconds")),
        "command: {}".format(command),
        "",
    ]
    with open(log_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(header + lines) + "\n")
    return log_path


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
    lines = _print_plan(plan, root, apply=args.apply)

    if plan.is_empty:
        return 0

    if not args.apply:
        print("\nNothing was changed. Re-run with --apply to make it so.")
        return 0

    command = shlex.join(sys.argv)
    try:
        execute(plan, force=args.force)
    except PlanError as exc:
        print("\nerror: refusing to apply:\n{}".format(exc), file=sys.stderr)
        lines = lines + ["", "ERROR: refusing to apply:", str(exc)]
        print("\nLog written to: {}".format(write_run_log(root, "m3u", lines, command)))
        return 1

    print("\nApplied.")
    print("Log written to: {}".format(write_run_log(root, "m3u", lines, command)))
    return 0


def render_cheats_plan(plan: Plan, root: Path, apply: bool) -> List[str]:
    # .cht files can run to dozens of long code lines each, so unlike
    # render_plan(), this deliberately never echoes write content -- just
    # target paths, plus the per-system match-count notes which are what
    # actually matters for reviewing coverage.
    lines = []
    for note in plan.notes:
        lines.append("  note: {}".format(note))
    if plan.notes:
        lines.append("")

    if plan.is_empty:
        lines.append("Nothing to do.")
    else:
        header = "Cheat files to write" if apply else "Planned cheat files (dry run)"
        lines.append("{}:".format(header))
        for action in plan.actions:
            try:
                rel = action.target.relative_to(root)
            except ValueError:
                rel = action.target
            lines.append("  write  {}".format(rel))
        lines.append("\n{} cheat file(s).".format(plan.counts()["write"]))

    if plan.warnings:
        lines.append("\nWarnings:")
        for warning in plan.warnings:
            lines.append("  ! {}".format(warning))
    return lines


def _print_cheats_plan(plan: Plan, root: Path, apply: bool) -> List[str]:
    lines = render_cheats_plan(plan, root, apply)
    print("\n".join(lines))
    return lines


def cmd_cheats(args: argparse.Namespace) -> int:
    roms_root = Path(args.path).expanduser()
    cheats_root = Path(args.cheats_root).expanduser()
    cht_root = Path(args.cht_db).expanduser()

    if not roms_root.exists():
        print("error: path does not exist: {}".format(roms_root), file=sys.stderr)
        return 2
    if not cht_root.is_dir():
        print(
            "error: cht database folder not found: {}".format(cht_root),
            file=sys.stderr,
        )
        return 2

    plan = plan_cheats(roms_root, cheats_root, cht_root)
    lines = _print_cheats_plan(plan, cheats_root, apply=args.apply)

    if plan.is_empty:
        return 0

    if not args.apply:
        print("\nNothing was changed. Re-run with --apply to make it so.")
        return 0

    command = shlex.join(sys.argv)
    try:
        execute(plan, force=args.force)
    except PlanError as exc:
        print("\nerror: refusing to apply:\n{}".format(exc), file=sys.stderr)
        lines = lines + ["", "ERROR: refusing to apply:", str(exc)]
        print(
            "\nLog written to: {}".format(
                write_run_log(cheats_root, "cheats", lines, command)
            )
        )
        return 1

    print("\nApplied.")
    print(
        "Log written to: {}".format(
            write_run_log(cheats_root, "cheats", lines, command)
        )
    )
    return 0


def render_scan_report(root: Path) -> List[str]:
    """Build the lines describing one folder's system folders/tags/counts.

    Assumes *root* is already a real directory -- callers (CLI, GUI) check
    that first so each can report a "not a folder" error their own way.
    """
    lines: List[str] = []
    if looks_like_roms_root(root):
        folders = find_system_folders(root)
        lines.append("Roms root: {}".format(root))
        lines.append("{} tagged system folder(s):\n".format(len(folders)))
        for folder in folders:
            roms = sum(1 for p in folder.rglob("*") if is_candidate_file(p))
            subs = sum(1 for p in folder.iterdir() if p.is_dir())
            lines.append(
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
            lines.append("\nUntagged folders (NextUI will ignore these):")
            for folder in untagged:
                lines.append("  {}".format(folder.name))
        return lines

    tag = system_tag(root)
    lines.append("System folder: {} (tag={})".format(root.name, tag or "MISSING"))
    if tag is None:
        lines.append(
            "  ! No uppercase (TAG) suffix. NextUI needs one, e.g. 'NES (FC)',\n"
            "    otherwise the folder will not appear in the menu."
        )
    files = sum(1 for p in root.rglob("*") if is_candidate_file(p))
    lines.append("  {} candidate file(s)".format(files))
    return lines


def cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    if not root.is_dir():
        print("error: not a folder: {}".format(root), file=sys.stderr)
        return 2
    print("\n".join(render_scan_report(root)))
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from retro_tools.gui import main as gui_main
    except ImportError:
        print(
            "error: the GUI needs PySide6, which isn't installed.\n"
            "Install it with: pip install retro-tools[gui]",
            file=sys.stderr,
        )
        return 2
    return gui_main()


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

    cheats = subparsers.add_parser(
        "cheats",
        help="Match ROMs against a libretro cheat database and write .cht files.",
        description=(
            "Matches each game in your Roms folder (or a single system "
            "folder) against a local checkout of the libretro-database cht/ "
            "folder, and writes a NextUI/MinUI-format .cht file for every "
            "match under --cheats-root/<TAG>/. Systems with no known mapping "
            "to a cht console folder are skipped and reported. Dry run "
            "unless --apply is given. See TAG_TO_CHT_CONSOLE in "
            "retro_tools/cheats.py for the current system mapping."
        ),
    )
    cheats.add_argument("path", help="Your Roms folder, or a single system folder.")
    cheats.add_argument(
        "--cheats-root",
        required=True,
        help="Where to write <TAG>/<name>.cht files, e.g. SDCARD/Cheats.",
    )
    cheats.add_argument(
        "--cht-db",
        required=True,
        help="Local checkout of libretro-database's cht/ folder.",
    )
    cheats.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the .cht files.",
    )
    cheats.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .cht files that don't already match.",
    )
    cheats.set_defaults(func=cmd_cheats)

    gui = subparsers.add_parser(
        "gui", help="Launch the graphical interface (needs PySide6)."
    )
    gui.set_defaults(func=cmd_gui)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
