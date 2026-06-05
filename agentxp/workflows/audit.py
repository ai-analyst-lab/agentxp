"""Audit helpers — called by .claude/skills/audit/SKILL.md.

Walks ``experiments/<id>/log.md`` and yields parsed entries. The audit
surface in v2 is git (every commit_artifact runs a git commit) + the
human-readable log.md. There is no separate event log.

Public surface:
  - walk_log(exp_dir) -> Iterator[LogEntry]
  - diff_logs(exp_a, exp_b) -> Iterator[Diff]
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, Literal, Optional

from pydantic import BaseModel, ConfigDict


# log.md entries look like: `- \`<iso>\` — <message>\n`
_LOG_LINE = re.compile(
    r"^-\s+`(?P<ts>[^`]+)`\s+—\s+(?P<message>.+)$"
)


class LogEntry(BaseModel):
    """One row parsed from ``log.md``."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str  # ISO-8601 UTC as stored
    message: str
    line_no: int


class DiffOp(BaseModel):
    """One difference between two logs."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["only_in_a", "only_in_b", "changed"]
    line_no: int
    a: Optional[LogEntry] = None
    b: Optional[LogEntry] = None


def walk_log(exp_dir: Path) -> Iterator[LogEntry]:
    """Yield each parseable entry from ``exp_dir/log.md``.

    Skips header lines + blanks + lines that don't match the expected
    shape. Empty / missing log yields nothing (no raise).
    """
    log_path = Path(exp_dir) / "log.md"
    if not log_path.exists():
        return
    for i, line in enumerate(log_path.read_text().splitlines(), start=1):
        m = _LOG_LINE.match(line)
        if m:
            yield LogEntry(
                timestamp=m.group("ts"),
                message=m.group("message"),
                line_no=i,
            )


def diff_logs(exp_a: Path, exp_b: Path) -> Iterator[DiffOp]:
    """Pairwise diff of two experiments' log.md by line number.

    Simple line-by-line — sufficient for the audit surface. Two real
    experiments rarely have matching numbers of entries, so most diffs
    surface as ``only_in_a`` / ``only_in_b`` past the common prefix.
    """
    entries_a = list(walk_log(exp_a))
    entries_b = list(walk_log(exp_b))
    n = max(len(entries_a), len(entries_b))
    for i in range(n):
        a = entries_a[i] if i < len(entries_a) else None
        b = entries_b[i] if i < len(entries_b) else None
        if a is None:
            yield DiffOp(kind="only_in_b", line_no=i + 1, b=b)
        elif b is None:
            yield DiffOp(kind="only_in_a", line_no=i + 1, a=a)
        elif a.message != b.message:
            yield DiffOp(kind="changed", line_no=i + 1, a=a, b=b)


__all__ = ["LogEntry", "DiffOp", "walk_log", "diff_logs"]
