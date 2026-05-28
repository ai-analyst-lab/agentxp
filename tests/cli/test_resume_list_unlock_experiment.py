"""Tests for the W5 CLI surfaces: resume, list, unlock, /experiment."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from agentxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR


# ──────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────


def _ts(offset_min: int = 0) -> str:
    return (datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc)
            + timedelta(minutes=offset_min)).isoformat()


def _minimal_state(
    exp_id: str = "exp_001",
    stage: str = "data_loaded",
    last_committed: str | None = "data_loaded",
    intent: str | None = "Checkout button test",
    pending: dict | None = None,
    stage_history: list[dict] | None = None,
    schema_version: int = 3,
    session: dict | None = None,
) -> dict:
    state: dict = {
        "schema_version": schema_version,
        "experiment_id": exp_id,
        "current_stage": stage,
        "last_committed_stage": last_committed,
        "stage_history": stage_history if stage_history is not None else [
            {"stage": stage, "committed_at": _ts(0)},
        ],
    }
    if intent is not None:
        state["intent"] = intent
    if pending is not None:
        state["pending_decision"] = pending
    if session is not None:
        state["session"] = session
    return state


def _write_state(project_root: Path, exp_id: str, state: dict) -> Path:
    exp_dir = project_root / "experiments" / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    state_path = exp_dir / "state.yaml"
    state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
    return exp_dir


# ──────────────────────────────────────────────────────────────────────────
# list tests
# ──────────────────────────────────────────────────────────────────────────


def test_list_empty_state(tmp_path: Path, capsys):
    from agentxp.cli.list import main

    rc = main(["--project", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "No experiments found" in captured.out


def test_list_renders_table_with_one_experiment(tmp_path: Path, capsys):
    from agentxp.cli.list import main

    _write_state(tmp_path, "exp_001", _minimal_state(intent="Checkout button test"))
    rc = main(["--project", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "exp_001" in captured.out
    assert "data_loaded" in captured.out
    assert "Checkout button test" in captured.out


def test_list_json_flag(tmp_path: Path, capsys):
    from agentxp.cli.list import main

    _write_state(tmp_path, "exp_001", _minimal_state())
    rc = main(["--project", str(tmp_path), "--json"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert data[0]["exp_id"] == "exp_001"
    assert data[0]["stage"] == "data_loaded"


def test_list_filter_by_status(tmp_path: Path, capsys):
    from agentxp.cli.list import main

    _write_state(tmp_path, "exp_a", _minimal_state(exp_id="exp_a", stage="data_loaded", last_committed="data_loaded"))
    _write_state(tmp_path, "exp_b", _minimal_state(exp_id="exp_b", stage="brief_drafted", last_committed="brief_drafted"))
    _write_state(tmp_path, "exp_c", _minimal_state(exp_id="exp_c", stage="monitor", last_committed="monitor"))

    rc = main(["--project", str(tmp_path), "--status", "brief_drafted", "--json"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    rows = json.loads(captured.out)
    assert len(rows) == 1
    assert rows[0]["exp_id"] == "exp_b"


# ──────────────────────────────────────────────────────────────────────────
# unlock tests
# ──────────────────────────────────────────────────────────────────────────


def test_unlock_missing_lock_returns_user_error(tmp_path: Path, capsys):
    from agentxp.cli.unlock import main

    exp_dir = tmp_path / "experiments" / "exp_001"
    exp_dir.mkdir(parents=True)
    rc = main(["exp_001", "--project", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert ".state.lock" in captured.err


def test_unlock_releases_dead_pid_lock(tmp_path: Path, capsys):
    from agentxp.cli.unlock import main

    exp_dir = _write_state(tmp_path, "exp_001", _minimal_state())
    lock_path = exp_dir / ".state.lock"
    # PID 999999 should not exist on any sane test host.
    lock_path.write_text(
        json.dumps({
            "schema_version": 1,
            "pid": 999999,
            "started_at": _ts(0),
        }),
        encoding="utf-8",
    )
    rc = main(["exp_001", "--project", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert not lock_path.exists()
    assert "Lock released" in captured.out


def test_unlock_refuses_live_pid_without_force(tmp_path: Path, capsys):
    from agentxp.cli.unlock import main

    exp_dir = _write_state(tmp_path, "exp_001", _minimal_state())
    lock_path = exp_dir / ".state.lock"
    lock_path.write_text(
        json.dumps({
            "schema_version": 1,
            "pid": os.getpid(),
            "started_at": _ts(0),
        }),
        encoding="utf-8",
    )
    rc = main(["exp_001", "--project", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert lock_path.exists()
    assert "--force" in captured.err


def test_unlock_force_overrides_live_pid(tmp_path: Path, capsys):
    from agentxp.cli.unlock import main

    exp_dir = _write_state(tmp_path, "exp_001", _minimal_state())
    lock_path = exp_dir / ".state.lock"
    lock_path.write_text(
        json.dumps({
            "schema_version": 1,
            "pid": os.getpid(),
            "started_at": _ts(0),
        }),
        encoding="utf-8",
    )
    rc = main(["exp_001", "--force", "--project", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert not lock_path.exists()


def test_unlock_emits_audit_event(tmp_path: Path):
    from agentxp.cli.unlock import main

    exp_dir = _write_state(tmp_path, "exp_001", _minimal_state())
    lock_path = exp_dir / ".state.lock"
    lock_path.write_text(
        json.dumps({
            "schema_version": 1,
            "pid": 999999,
            "started_at": _ts(0),
        }),
        encoding="utf-8",
    )
    rc = main(["exp_001", "--project", str(tmp_path)])
    assert rc == EXIT_OK

    log_path = exp_dir / "log.jsonl"
    assert log_path.exists()
    lines = [
        json.loads(ln) for ln in log_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    stale_events = [
        ev for ev in lines
        if ev.get("metadata", {}).get("subtype") == "lock.stale_reclaimed"
    ]
    assert len(stale_events) == 1
    assert stale_events[0]["metadata"]["reclaimed_pid"] == 999999


# ──────────────────────────────────────────────────────────────────────────
# resume tests
# ──────────────────────────────────────────────────────────────────────────


def test_resume_missing_exp_returns_user_error(tmp_path: Path, capsys):
    from agentxp.cli.resume import main

    rc = main(["exp_nope", "--project", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "unknown experiment" in captured.err


def test_resume_case_1_nothing_to_resume(tmp_path: Path, capsys):
    from agentxp.cli.resume import main

    _write_state(
        tmp_path, "exp_001",
        _minimal_state(stage="data_loaded", last_committed="data_loaded"),
    )
    rc = main(["exp_001", "--project", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "Nothing to resume" in captured.err
    assert "case 1" in captured.err.lower()


def test_resume_case_2_pending_decision(tmp_path: Path, capsys):
    from agentxp.cli.resume import main

    state = _minimal_state(
        stage="brief_drafted",
        last_committed="brief_drafted",
        pending={
            "schema_version": 1,
            "kind": "brief_contradiction",
            "opened_at": _ts(0),
            "prompt_to_user": "Choose how to resolve the contradiction.",
            "options": ["revise", "explain", "override"],
            "metadata": {},
        },
    )
    _write_state(tmp_path, "exp_001", state)
    rc = main(["exp_001", "--project", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "brief_contradiction" in captured.err
    assert "case 2" in captured.err.lower()


def test_resume_case_8_old_schema(tmp_path: Path, capsys):
    from agentxp.cli.resume import main

    state = _minimal_state(schema_version=2)
    _write_state(tmp_path, "exp_001", state)
    rc = main(["exp_001", "--project", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "Schema migration" in captured.err
    assert "case 8" in captured.err.lower()


# ──────────────────────────────────────────────────────────────────────────
# experiment tests
# ──────────────────────────────────────────────────────────────────────────


def test_experiment_prints_claude_code_guidance(capsys):
    from agentxp.cli.experiment import main

    rc = main([])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "Claude Code" in captured.err


def test_experiment_with_data_flag(capsys):
    from agentxp.cli.experiment import main

    rc = main(["--data", "foo.parquet"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "foo.parquet" in captured.err
