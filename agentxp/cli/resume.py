"""agentxp resume — recovery / resumption CLI for an experiment (W5.3).

Implements the v0.1 surface for §10.6's 8 recovery cases: detect which case
applies to ``experiments/{exp_id}/state.yaml`` + ``log.jsonl`` and surface
the recommended next action on stderr. v0.1 does not auto-fix — that is
W7 smoke tests' job; this command tells the user what state the experiment
is in and what to run next.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10.6.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from agentxp.cli.exit_codes import EXIT_FATAL, EXIT_OK, EXIT_USER_ERROR

__all__ = ["main"]


# ──────────────────────────────────────────────────────────────────────────
# argparse setup
# ──────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentxp resume",
        description=(
            "Detect the §10.6 recovery case for an experiment and surface "
            "the recommended next command. v0.1 does not auto-fix."
        ),
    )
    parser.add_argument(
        "exp_id",
        help="Experiment id (directory name under {project}/experiments/).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Acknowledge an inconsistent-state warning and proceed.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Project root containing experiments/ (default: cwd).",
    )
    return parser


# ──────────────────────────────────────────────────────────────────────────
# Disk helpers
# ──────────────────────────────────────────────────────────────────────────


def _resolve_exp_dir(project: Optional[Path], experiment_id: str) -> Path:
    root = (project if project is not None else Path.cwd()).resolve()
    return root / "experiments" / experiment_id


def _load_state(exp_dir: Path) -> Optional[dict[str, Any]]:
    state_path = exp_dir / "state.yaml"
    if not state_path.exists():
        return None
    try:
        raw = state_path.read_text(encoding="utf-8")
    except OSError:
        return None
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        return None
    return data


def _load_log_events(exp_dir: Path) -> list[dict]:
    log_path = exp_dir / "log.jsonl"
    if not log_path.exists():
        return []
    events: list[dict] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


# ──────────────────────────────────────────────────────────────────────────
# Recovery-case detector
# ──────────────────────────────────────────────────────────────────────────


def _detect_case(
    state: dict[str, Any], events: list[dict], exp_dir: Path
) -> tuple[int, str]:
    """Return (case_number, human_message).

    The 8 cases follow §10.6. v0.1 surfaces all of them but only auto-acts
    on Case 1 (nothing to do). The rest return a user-facing message.
    """
    schema_version = state.get("schema_version")
    current_stage = state.get("current_stage")
    last_committed = state.get("last_committed_stage")
    stage_history = state.get("stage_history") or []
    pending = state.get("pending_decision")
    session = state.get("session") or {}
    last_action_id = session.get("last_action_id") if isinstance(session, dict) else None

    # Case 8: schema_version drift (v0.1 wants 3).
    if isinstance(schema_version, int) and schema_version < 3:
        return (
            8,
            f"Schema migration needed; state.yaml schema_version={schema_version}. "
            "Run `agentxp migrate state` to upgrade.",
        )

    # Case 2: a gate is open and waiting for the user.
    if pending:
        kind = pending.get("kind") if isinstance(pending, dict) else None
        stage = current_stage or "<unknown>"
        return (
            2,
            f"Stage {stage} paused on gate.kind={kind!r}; user input required. "
            "Open this experiment in Claude Code and respond to the gate.",
        )

    # Case 3: stage_history has 2+ entries with the same stage.
    if isinstance(stage_history, list):
        seen: set[str] = set()
        dup_stage: Optional[str] = None
        for entry in stage_history:
            if isinstance(entry, dict):
                s = entry.get("stage")
                if isinstance(s, str):
                    if s in seen:
                        dup_stage = s
                        break
                    seen.add(s)
        if dup_stage is not None:
            return (
                3,
                f"Inconsistent state: stage {dup_stage!r} appears 2+ times in "
                "stage_history. Recommend `agentxp resume <exp_id> --force` after "
                "auditing the chain (`agentxp audit <exp_id>`).",
            )

    # Case 7: a bundle file exists for an agent, but no completed event for it.
    bundles_dir = exp_dir / "bundles"
    if bundles_dir.exists():
        completed_agents = {
            ev.get("agent_name")
            for ev in events
            if ev.get("event_name") == "agent.completed"
            and ev.get("agent_name")
        }
        for bundle_path in bundles_dir.glob("*.out.yaml"):
            agent_name = bundle_path.name[: -len(".out.yaml")]
            if agent_name and agent_name not in completed_agents:
                return (
                    7,
                    f"Agent-crash recovery: bundle {bundle_path.name} present "
                    "but no agent.completed event recorded. The agent crashed "
                    "between writing the bundle and emitting completion.",
                )

    # Case 4: last_action_id has no corresponding stage.committed event.
    if last_action_id:
        action_ids = {ev.get("action_id") for ev in events}
        if last_action_id not in action_ids:
            return (
                4,
                f"Last commit incomplete: session.last_action_id={last_action_id!r} "
                "has no matching event in log.jsonl. Rolling forward from "
                f"stage={current_stage!r} on next dispatch.",
            )

    # Case 5: log.jsonl has events newer than session.last_action_id but state
    # didn't advance. v0.1 heuristic: count events after the last_action_id
    # position and check whether their stage matches current_stage.
    if last_action_id and events:
        try:
            idx = next(
                i for i, ev in enumerate(events) if ev.get("action_id") == last_action_id
            )
            tail = events[idx + 1 :]
        except StopIteration:
            tail = []
        if tail and current_stage:
            stage_events_after = [
                ev for ev in tail if ev.get("stage") and ev.get("stage") != current_stage
            ]
            if stage_events_after:
                return (
                    5,
                    "Lock died mid-commit: log.jsonl has events after "
                    f"session.last_action_id={last_action_id!r}. Reconstructing "
                    f"from log; current_stage={current_stage!r} may advance on resume.",
                )

    # Case 6: conversation has turns after last_action_id but state didn't move.
    conv_path = exp_dir / "conversation.jsonl"
    if conv_path.exists() and last_action_id:
        try:
            tail_lines = [
                ln for ln in conv_path.read_text(encoding="utf-8").splitlines() if ln.strip()
            ]
        except OSError:
            tail_lines = []
        # Heuristic: if there are conversation turns whose action_id != last_action_id
        # and the parent_action_id chain has drifted past last_committed.
        orphan = 0
        for ln in tail_lines[-50:]:
            try:
                row = json.loads(ln)
            except (json.JSONDecodeError, ValueError):
                continue
            tid = row.get("action_id")
            if tid and tid != last_action_id:
                orphan += 1
        if orphan > 5 and current_stage == last_committed:
            return (
                6,
                f"Conversation drift: {orphan} turns recorded after "
                "session.last_action_id but state.yaml did not advance. Orphan "
                "turns will be marked on next commit.",
            )

    # Case 1: nothing to resume — current_stage matches last_committed and no gate.
    if current_stage and current_stage == last_committed:
        return (
            1,
            f"Nothing to resume; experiment is already at stage={current_stage!r}.",
        )

    # Fallback — not one of the canonical cases; tell the user nothing is broken.
    return (
        1,
        f"Nothing to resume; experiment is at stage={current_stage!r}.",
    )


# ──────────────────────────────────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Detect a §10.6 recovery case and surface it on stderr. Returns EXIT_*."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    exp_dir = _resolve_exp_dir(args.project, args.exp_id)
    if not exp_dir.exists():
        print(f"unknown experiment: {args.exp_id}", file=sys.stderr)
        return EXIT_USER_ERROR

    state = _load_state(exp_dir)
    if state is None:
        print(
            f"no state.yaml found under {exp_dir}; nothing to resume",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    try:
        events = _load_log_events(exp_dir)
    except OSError as exc:
        print(f"failed to read log.jsonl: {exc}", file=sys.stderr)
        return EXIT_FATAL

    case, message = _detect_case(state, events, exp_dir)
    print(f"resume case {case}: {message}", file=sys.stderr)

    # Case 1 is a clean no-op; everything else needs user attention or --force.
    if case == 1:
        return EXIT_OK
    if case in (2, 4, 5, 6, 7, 8) and not args.force:
        return EXIT_USER_ERROR
    if case == 3 and not args.force:
        return EXIT_USER_ERROR
    # --force acknowledges the warning.
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
