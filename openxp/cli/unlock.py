"""openxp unlock — break a stale .state.lock for an experiment (W5.7).

Probes ``experiments/{exp_id}/.state.lock`` for liveness via ``os.kill(pid, 0)``
and either deletes the lock (dead PID, or ``--force``) or refuses with a
user-facing message naming the holder. Emits a ``stage.committed`` audit
event with ``metadata.subtype="lock.stale_reclaimed"`` per §10.5 / §1.8.5
so the unlock action is itself replayable.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10.6.3, §1.8.5.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from openxp.audit.events import StageCommittedPayload
from openxp.audit.storage import append_event
from openxp.cli.exit_codes import EXIT_FATAL, EXIT_OK, EXIT_USER_ERROR

__all__ = ["main"]


# ──────────────────────────────────────────────────────────────────────────
# argparse setup
# ──────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openxp unlock",
        description=(
            "Release a stale .state.lock for an experiment. Refuses to break "
            "a lock held by a live PID unless --force is passed."
        ),
    )
    parser.add_argument(
        "exp_id",
        help="Experiment id (directory name under {project}/experiments/).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Break the lock even if the holder PID is alive.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Project root containing experiments/ (default: cwd).",
    )
    return parser


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _resolve_exp_dir(project: Optional[Path], exp_id: str) -> Path:
    root = (project if project is not None else Path.cwd()).resolve()
    return root / "experiments" / exp_id


def _read_lock_metadata(lock_path: Path) -> Optional[dict[str, Any]]:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _pid_is_alive(pid: int) -> bool:
    """POSIX: ``os.kill(pid, 0)`` raises ProcessLookupError if dead."""
    if sys.platform == "win32":  # pragma: no cover — Windows
        try:
            import psutil  # type: ignore[import]
            return bool(psutil.pid_exists(pid))
        except ImportError:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but owned by another user.
        return True
    except OSError:
        return True


def _new_action_id() -> str:
    return uuid.uuid4().hex.upper()


def _emit_stale_reclaimed(
    exp_dir: Path, exp_id: str, reclaimed_pid: Optional[int]
) -> None:
    """Append a stage.committed event with subtype="lock.stale_reclaimed"
    so the audit chain records the break. metadata.reclaimed_pid carries
    the PID we evicted.
    """
    metadata: dict[str, Any] = {"subtype": "lock.stale_reclaimed"}
    if reclaimed_pid is not None:
        metadata["reclaimed_pid"] = reclaimed_pid
    # We deliberately do not advance the stage; the bundle_hash is None.
    # This is the audit-only signal that an external operator broke the lock.
    # The closest event is stage.committed (subtype reserved for this case in
    # §1.8.5). The stage value is intentionally a sentinel — we read it off
    # state.yaml if present so the chain stays internally consistent.
    from openxp.schemas.state import Stage  # local import to avoid cycle at top

    stage_value: Stage = Stage.DATA_LOADED
    state_path = exp_dir / "state.yaml"
    if state_path.exists():
        try:
            import yaml

            data = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
            raw_stage = data.get("current_stage") if isinstance(data, dict) else None
            if isinstance(raw_stage, str):
                try:
                    stage_value = Stage(raw_stage)
                except ValueError:
                    pass
        except OSError:
            pass

    payload = StageCommittedPayload(
        timestamp=datetime.now(timezone.utc),
        action_id=_new_action_id(),
        parent_action_id=None,
        actor_kind="user",
        actor_name="openxp unlock",
        experiment_id=exp_id,
        stage=stage_value,
        bundle_hash=None,
        metadata=metadata,
    )
    append_event(exp_dir, payload)


# ──────────────────────────────────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Break a .state.lock if dead or --force; emit the audit event."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    exp_dir = _resolve_exp_dir(args.project, args.exp_id)
    if not exp_dir.exists():
        print(f"unknown experiment: {args.exp_id}", file=sys.stderr)
        return EXIT_USER_ERROR

    lock_path = exp_dir / ".state.lock"
    if not lock_path.exists():
        print(f"no .state.lock at {lock_path}; nothing to release", file=sys.stderr)
        return EXIT_USER_ERROR

    meta = _read_lock_metadata(lock_path)
    holder_pid: Optional[int] = None
    started_at: Optional[str] = None
    if isinstance(meta, dict):
        raw_pid = meta.get("pid")
        if isinstance(raw_pid, int):
            holder_pid = raw_pid
        started_at = meta.get("started_at") if isinstance(meta.get("started_at"), str) else None

    if holder_pid is not None and _pid_is_alive(holder_pid) and not args.force:
        print(
            f"Lock held by PID {holder_pid}"
            + (f", started {started_at}" if started_at else "")
            + ". Use --force to break.",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    try:
        lock_path.unlink()
    except FileNotFoundError:
        # Race: someone else released it.
        pass
    except OSError as exc:
        print(f"failed to remove {lock_path}: {exc}", file=sys.stderr)
        return EXIT_FATAL

    try:
        _emit_stale_reclaimed(exp_dir, args.exp_id, holder_pid)
    except Exception as exc:  # noqa: BLE001 — audit failure is non-fatal
        print(
            f"warning: lock released but audit event emission failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

    print(f"Lock released for {args.exp_id}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
