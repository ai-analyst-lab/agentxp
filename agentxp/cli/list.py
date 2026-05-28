"""agentxp list — enumerate experiments in a project (W5.6).

Walks ``{project}/experiments/*/state.yaml`` and renders a one-row-per-
experiment summary (exp_id, current_stage, last_committed_at, intent).
Supports ``--status`` (filter by stage), ``--since N`` (last N days), and
``--json`` (machine-readable output).

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10 / W5.6.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from agentxp.cli.exit_codes import EXIT_OK

__all__ = ["main"]


# ──────────────────────────────────────────────────────────────────────────
# argparse setup
# ──────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentxp list",
        description=(
            "List experiments under {project}/experiments/, with exp_id, "
            "current_stage, last commit timestamp, and intent summary."
        ),
    )
    parser.add_argument(
        "--status",
        default=None,
        help="Filter rows by Stage value (e.g. brief_drafted, monitor).",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=None,
        help="Only show experiments with a commit in the last N days.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of a markdown table.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Project root containing experiments/ (default: cwd).",
    )
    return parser


# ──────────────────────────────────────────────────────────────────────────
# Per-experiment row extraction
# ──────────────────────────────────────────────────────────────────────────


def _resolve_experiments_root(project: Optional[Path]) -> Path:
    root = (project if project is not None else Path.cwd()).resolve()
    return root / "experiments"


def _load_state(state_path: Path) -> Optional[dict[str, Any]]:
    try:
        raw = state_path.read_text(encoding="utf-8")
    except OSError:
        return None
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        return None
    return data


def _last_committed_at(state: dict[str, Any]) -> Optional[str]:
    history = state.get("stage_history") or []
    if isinstance(history, list) and history:
        last = history[-1]
        if isinstance(last, dict):
            ts = last.get("committed_at")
            if isinstance(ts, str):
                return ts
    return None


def _summarize_intent(state: dict[str, Any], max_chars: int = 80) -> str:
    intent = state.get("intent")
    if not isinstance(intent, str) or not intent:
        return ""
    flat = " ".join(intent.split())
    if len(flat) <= max_chars:
        return flat
    return flat[: max_chars - 1] + "…"


def _row(exp_dir: Path) -> Optional[dict[str, Any]]:
    state_path = exp_dir / "state.yaml"
    if not state_path.exists():
        return None
    state = _load_state(state_path)
    if state is None:
        return None
    return {
        "exp_id": state.get("experiment_id") or exp_dir.name,
        "stage": state.get("current_stage"),
        "committed_at": _last_committed_at(state),
        "intent": _summarize_intent(state),
    }


# ──────────────────────────────────────────────────────────────────────────
# Filters
# ──────────────────────────────────────────────────────────────────────────


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        # Handle "2026-05-27T15:30:00+00:00" and "...Z".
        s = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _apply_filters(
    rows: list[dict[str, Any]], status: Optional[str], since_days: Optional[int]
) -> list[dict[str, Any]]:
    out = rows
    if status:
        out = [r for r in out if r.get("stage") == status]
    if since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        filtered: list[dict[str, Any]] = []
        for r in out:
            ts = r.get("committed_at")
            if isinstance(ts, str):
                parsed = _parse_iso(ts)
                if parsed is not None and parsed >= cutoff:
                    filtered.append(r)
        out = filtered
    return out


# ──────────────────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────────────────


def _render_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| exp_id | stage | committed_at | intent |",
        "|--------|-------|--------------|--------|",
    ]
    for r in rows:
        exp_id = str(r.get("exp_id") or "")
        stage = str(r.get("stage") or "")
        ts = str(r.get("committed_at") or "")
        intent = str(r.get("intent") or "").replace("|", "\\|")
        lines.append(f"| {exp_id} | {stage} | {ts} | {intent} |")
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Render the experiments table to stdout. Always returns EXIT_OK."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    experiments_root = _resolve_experiments_root(args.project)

    if not experiments_root.exists():
        print(
            f"No experiments found in {experiments_root}/. "
            "Start one with `agentxp /experiment`."
        )
        return EXIT_OK

    rows: list[dict[str, Any]] = []
    for child in sorted(experiments_root.iterdir()):
        if not child.is_dir():
            continue
        row = _row(child)
        if row is not None:
            rows.append(row)

    rows = _apply_filters(rows, args.status, args.since)

    if not rows:
        if args.json:
            sys.stdout.write(json.dumps([]) + "\n")
        else:
            print(
                f"No experiments found in {experiments_root}/. "
                "Start one with `agentxp /experiment`."
            )
        return EXIT_OK

    if args.json:
        sys.stdout.write(json.dumps(rows, indent=2) + "\n")
    else:
        sys.stdout.write(_render_table(rows))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
