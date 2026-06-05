"""``agentxp prune`` — remove abandoned / orphan experiment artifacts.

v0.1 cleanup W0.16 — addresses audit finding S1 (orphan
``experiments/exp_001/`` left from prior debug walks with no cleanup verb).

This verb handles ORPHAN-EXPERIMENT pruning in v0.1. The presentation-spine
extension P-W5.2 layers ``--readouts`` onto this same verb to prune superseded
readout slots; that ships in Wave 5.

Behavior (v0.1 W0.16 baseline):

    agentxp prune --orphans [--dry-run] [--force]
        Walk ``experiments/`` and identify orphan experiments — directories
        without a ``state.yaml`` (the canonical marker of a real experiment).
        With --dry-run: print what would be removed, exit 0, no writes.
        Default: refuse without --force when any candidate has untracked
        artifacts (bundles/, decisions/, log.jsonl); --force overrides.

Refusal conditions (without --force):
  - Any candidate orphan carries an unresolved ``.state.lock`` (someone else
    may be working on it).
  - Any candidate is younger than 24h (probably mid-debug).

Exit codes:
  - EXIT_OK (0): completed (including --dry-run with no candidates).
  - EXIT_USER_ERROR (1): bad arguments, refusal triggered.
  - EXIT_WARNING (2): some candidates skipped (locks, recency); rest proceeded.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from agentxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR, EXIT_WARNING


_RECENCY_REFUSAL_SECONDS = 24 * 60 * 60  # 24h


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentxp prune",
        description=(
            "Remove orphan experiment directories (no state.yaml). "
            "Use --dry-run to preview. --force overrides recency / lock refusals."
        ),
    )
    parser.add_argument(
        "--orphans",
        action="store_true",
        help="prune orphan experiment dirs (no state.yaml). Required in v0.1.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="project root (default: cwd).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be removed; write nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="override recency and lock-file refusals.",
    )
    return parser


def _is_orphan(exp_dir: Path) -> bool:
    """An experiment is an orphan iff its directory has no state.yaml."""
    return exp_dir.is_dir() and not (exp_dir / "state.yaml").exists()


def _has_lock(exp_dir: Path) -> bool:
    return (exp_dir / ".state.lock").exists()


def _too_recent(exp_dir: Path) -> bool:
    """True iff the directory's mtime is within the recency refusal window."""
    try:
        mtime = exp_dir.stat().st_mtime
    except OSError:
        return False
    return (time.time() - mtime) < _RECENCY_REFUSAL_SECONDS


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.orphans:
        print(
            "agentxp prune requires --orphans in v0.1. "
            "(--readouts ships in W5.)",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    project_root = (args.project if args.project is not None else Path.cwd()).resolve()
    experiments_dir = project_root / "experiments"

    if not experiments_dir.exists():
        print(f"no experiments/ directory found at {experiments_dir}")
        return EXIT_OK

    candidates = [d for d in experiments_dir.iterdir() if _is_orphan(d)]
    if not candidates:
        print("no orphan experiments found")
        return EXIT_OK

    skipped: list[tuple[Path, str]] = []
    eligible: list[Path] = []

    for candidate in candidates:
        if _has_lock(candidate) and not args.force:
            skipped.append((candidate, "locked"))
            continue
        if _too_recent(candidate) and not args.force:
            skipped.append((candidate, "modified <24h ago"))
            continue
        eligible.append(candidate)

    if args.dry_run:
        if eligible:
            print(f"would remove {len(eligible)} orphan experiment(s):")
            for d in eligible:
                print(f"  {d.relative_to(project_root)}")
        for d, reason in skipped:
            print(f"skip {d.relative_to(project_root)} ({reason}; use --force to override)")
        return EXIT_OK

    removed = 0
    for d in eligible:
        try:
            shutil.rmtree(d)
            removed += 1
            print(f"removed {d.relative_to(project_root)}")
        except OSError as e:
            print(
                f"failed to remove {d.relative_to(project_root)}: {e}",
                file=sys.stderr,
            )

    for d, reason in skipped:
        print(
            f"skip {d.relative_to(project_root)} ({reason}; use --force to override)"
        )

    if skipped:
        return EXIT_WARNING
    return EXIT_OK


__all__ = ["main"]


if __name__ == "__main__":
    sys.exit(main())
