"""Detection and grouping of multi-disc ROM files.

The naming conventions here follow the No-Intro / Redump style that NextUI
users typically have, e.g.::

    Final Fantasy VII (USA) (Disc 1).cue
    Final Fantasy VII (USA) (Disc 2).cue

but the parser is deliberately loose and also handles ``Disk 2``, ``CD3``,
``[Disc 1 of 3]``, ``- disc 2`` and similar variants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# --------------------------------------------------------------------------
# Extensions
# --------------------------------------------------------------------------

#: Extensions that can be referenced from an .m3u playlist, best first.
#: A .cue always wins over the .bin it points at.
PLAYLIST_PRIORITY = (
    ".cue",
    ".chd",
    ".gdi",
    ".ccd",
    ".cdi",
    ".iso",
    ".pbp",
    ".img",
    ".bin",
)

#: "Sheet" formats that point at separate data files sitting next to them.
#: A single-disc game in one of these formats is more than one file on disk,
#: which is why NextUI wants it tucked into its own folder.
SHEET_EXTS = frozenset({".cue", ".gdi", ".ccd", ".mds"})

#: Never touched by any planner.
IGNORED_NAMES = frozenset({"map.txt", "doom.version", ".ds_store", "thumbs.db"})

IGNORED_EXTS = frozenset({".m3u", ".txt", ".srm", ".sav", ".state"})


def is_candidate_file(path: Path) -> bool:
    """True if *path* is a file retro-tools is willing to move or list."""
    if not path.is_file():
        return False
    if path.name.startswith("."):
        return False
    if path.name.lower() in IGNORED_NAMES:
        return False
    if path.suffix.lower() in IGNORED_EXTS:
        return False
    return True


def playlist_rank(path: Path) -> int:
    """Lower is better. Unknown extensions sort last."""
    ext = path.suffix.lower()
    try:
        return PLAYLIST_PRIORITY.index(ext)
    except ValueError:
        return len(PLAYLIST_PRIORITY)


# --------------------------------------------------------------------------
# Disc token parsing
# --------------------------------------------------------------------------

DISC_TOKEN_RE = re.compile(
    r"""
    [\s._\-]*                                   # separator before the token
    [\(\[]?                                     # optional ( or [
    (?:disc|disk|cd)                            # the keyword
    [\s._\-]*
    (?P<num>\d{1,2})                            # disc number
    (?:[\s._\-]*(?:of|/)[\s._\-]*\d{1,2})?      # optional "of 3"
    [\)\]]?                                     # optional ) or ]
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class DiscName:
    """A filename stem split into its base title and disc number."""

    base: str
    number: int


def _tidy(text: str) -> str:
    """Clean up a base title after the disc token has been cut out."""
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" ._-")


def parse_disc(stem: str) -> Optional[DiscName]:
    """Split a filename stem into base title + disc number.

    Returns ``None`` when the stem carries no disc token, or when removing it
    would leave nothing behind (e.g. a file literally named ``Disc 1``).
    """
    matches = list(DISC_TOKEN_RE.finditer(stem))
    if not matches:
        return None
    match = matches[-1]  # right-most wins: "Sega CD Game (Disc 2)"
    if match.start() == 0:
        return None
    base = _tidy(stem[: match.start()] + stem[match.end() :])
    if not base:
        return None
    return DiscName(base, int(match.group("num")))


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------


@dataclass
class DiscGroup:
    """All files on disk that belong to one multi-disc game."""

    base: str
    directory: Path
    discs: Dict[int, List[Path]] = field(default_factory=dict)

    def add(self, number: int, path: Path) -> None:
        self.discs.setdefault(number, []).append(path)

    @property
    def numbers(self) -> List[int]:
        return sorted(self.discs)

    @property
    def files(self) -> List[Path]:
        out: List[Path] = []
        for number in self.numbers:
            out.extend(sorted(self.discs[number]))
        return out

    def playlist_entry(self, number: int) -> Optional[Path]:
        """The file that should represent disc *number* inside the .m3u."""
        candidates = sorted(self.discs[number], key=lambda p: (playlist_rank(p), p.name))
        if not candidates:
            return None
        best = candidates[0]
        if playlist_rank(best) == len(PLAYLIST_PRIORITY):
            return None  # nothing loadable, only companions
        return best

    def playlist_lines(self) -> List[str]:
        """The .m3u body, one relative filename per disc, in disc order."""
        lines = []
        for number in self.numbers:
            entry = self.playlist_entry(number)
            if entry is not None:
                lines.append(entry.name)
        return lines

    @property
    def m3u_name(self) -> str:
        return self.base + ".m3u"


def group_discs(paths: Iterable[Path]) -> List[DiscGroup]:
    """Group *paths* into multi-disc games, keyed by their base title."""
    groups: Dict[str, DiscGroup] = {}
    order: List[str] = []
    for path in sorted(paths, key=lambda p: p.name.lower()):
        parsed = parse_disc(path.stem)
        if parsed is None:
            continue
        key = parsed.base.casefold()
        if key not in groups:
            groups[key] = DiscGroup(base=parsed.base, directory=path.parent)
            order.append(key)
        groups[key].add(parsed.number, path)
    return [groups[key] for key in order]


def group_by_stem(paths: Iterable[Path]) -> Dict[str, List[Path]]:
    """Group non-disc files by their filename stem (for single-disc bin/cue)."""
    out: Dict[str, List[Path]] = {}
    for path in sorted(paths, key=lambda p: p.name.lower()):
        if parse_disc(path.stem) is not None:
            continue
        out.setdefault(path.stem, []).append(path)
    return out
