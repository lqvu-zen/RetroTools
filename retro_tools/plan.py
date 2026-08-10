"""A tiny plan/execute layer so every command can run dry by default.

Nothing in retro-tools touches the filesystem directly. Commands build a
:class:`Plan` of :class:`Action` objects, the CLI prints it, and only an
explicit ``--apply`` calls :func:`execute`.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

MKDIR = "mkdir"
MOVE = "move"
WRITE = "write"


@dataclass
class Action:
    kind: str
    target: Path
    source: Optional[Path] = None
    content: Optional[str] = None

    def describe(self, root: Optional[Path] = None) -> str:
        def rel(path: Path) -> str:
            if root is None:
                return str(path)
            try:
                return str(path.relative_to(root))
            except ValueError:
                return str(path)

        if self.kind == MKDIR:
            return "mkdir  {}/".format(rel(self.target))
        if self.kind == MOVE:
            assert self.source is not None
            return "move   {}  ->  {}".format(rel(self.source), rel(self.target))
        if self.kind == WRITE:
            lines = (self.content or "").splitlines()
            preview = ", ".join(lines) if lines else "(empty)"
            return "write  {}  [{}]".format(rel(self.target), preview)
        return "{}  {}".format(self.kind, rel(self.target))


@dataclass
class Plan:
    actions: List[Action] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def mkdir(self, target: Path) -> None:
        self.actions.append(Action(MKDIR, target))

    def move(self, source: Path, target: Path) -> None:
        self.actions.append(Action(MOVE, target, source=source))

    def write(self, target: Path, content: str) -> None:
        self.actions.append(Action(WRITE, target, content=content))

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def extend(self, other: "Plan") -> None:
        self.actions.extend(other.actions)
        self.warnings.extend(other.warnings)
        self.notes.extend(other.notes)

    @property
    def is_empty(self) -> bool:
        return not self.actions

    def counts(self):
        return {
            MKDIR: sum(1 for a in self.actions if a.kind == MKDIR),
            MOVE: sum(1 for a in self.actions if a.kind == MOVE),
            WRITE: sum(1 for a in self.actions if a.kind == WRITE),
        }


class PlanError(RuntimeError):
    """Raised when a plan cannot be executed safely."""


def validate(plan: Plan, force: bool = False) -> List[str]:
    """Return a list of blocking problems without touching the filesystem."""
    problems: List[str] = []
    created_dirs = {a.target for a in plan.actions if a.kind == MKDIR}
    produced = set()

    for action in plan.actions:
        if action.kind == MKDIR:
            if action.target.exists() and not action.target.is_dir():
                problems.append(
                    "cannot create folder, a file already exists: {}".format(action.target)
                )
        elif action.kind == MOVE:
            assert action.source is not None
            if not action.source.exists():
                problems.append("source has gone missing: {}".format(action.source))
            if action.target.exists() or action.target in produced:
                problems.append("target already exists: {}".format(action.target))
            parent = action.target.parent
            if not parent.exists() and parent not in created_dirs:
                problems.append("target folder does not exist: {}".format(parent))
            produced.add(action.target)
        elif action.kind == WRITE:
            if action.target.exists() and not force:
                problems.append(
                    "refusing to overwrite {} (use --force)".format(action.target)
                )
            produced.add(action.target)
    return problems


def execute(plan: Plan, force: bool = False) -> List[str]:
    """Run the plan. Returns the list of performed action descriptions."""
    problems = validate(plan, force=force)
    if problems:
        raise PlanError("\n".join(problems))

    done: List[str] = []
    for action in plan.actions:
        if action.kind == MKDIR:
            action.target.mkdir(parents=True, exist_ok=True)
        elif action.kind == MOVE:
            assert action.source is not None
            action.target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(action.source), str(action.target))
        elif action.kind == WRITE:
            action.target.parent.mkdir(parents=True, exist_ok=True)
            # NextUI reads these as plain text; keep LF endings.
            with open(action.target, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(action.content or "")
        else:  # pragma: no cover - defensive
            raise PlanError("unknown action kind: {}".format(action.kind))
        done.append(action.describe())
    return done
