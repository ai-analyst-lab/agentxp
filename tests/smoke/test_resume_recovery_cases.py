"""Track F — ``openxp resume`` 8-case smoke tests.

For each of the eight §10.6 recovery cases we build a fake experiment
directory in the shape the case's classifier expects, run
``openxp.cli.resume.main([exp_id])``, and assert the case number it
detects + the exit-code semantics from §10.6.5.

These are SHALLOW: we exercise the classifier, not the full handler
behaviour. The handler bodies ship in later waves; here we only need
to know the wiring routes each precondition to the right case.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10.6.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from openxp.cli import resume as resume_cli


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_state(exp_dir: Path, **overrides: Any) -> None:
    base: dict[str, Any] = {
        "schema_version": 3,
        "experiment_id": exp_dir.name,
        "current_stage": "brief_drafted",
        "last_committed_stage": "brief_drafted",
        "stage_history": [],
        "pending_decision": None,
        "session": {
            "started_at": _utc_iso(),
            "last_action_id": None,
        },
    }
    base.update(overrides)
    (exp_dir / "state.yaml").write_text(yaml.safe_dump(base, sort_keys=False))


def _write_log(exp_dir: Path, events: list[dict]) -> None:
    log = exp_dir / "log.jsonl"
    log.write_text("\n".join(json.dumps(ev) for ev in events) + "\n")


def _run_resume(exp_dir: Path, *, force: bool = False) -> tuple[int, str]:
    project = exp_dir.parent.parent  # exp_dir = <project>/experiments/<exp_id>
    argv = [exp_dir.name, "--project", str(project)]
    if force:
        argv.append("--force")
    # Capture stderr via pytest's capsys outside; here we just return rc.
    rc = resume_cli.main(argv)
    return rc, ""


# ──────────────────────────────────────────────────────────────────────────
# Case 1 — RESUME_AT_CLEAN_END (terminal no-op)
# ──────────────────────────────────────────────────────────────────────────


def test_case_1_clean_end_exits_ok(
    fake_exp_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """current_stage == last_committed_stage AND no pending_decision."""
    _write_state(
        fake_exp_dir,
        current_stage="readout",
        last_committed_stage="readout",
    )
    _write_log(fake_exp_dir, [])
    rc, _ = _run_resume(fake_exp_dir)
    captured = capsys.readouterr()
    assert rc == 0, f"Case 1 must exit 0; got {rc} ({captured.err!r})"
    assert "resume case 1" in captured.err


# ──────────────────────────────────────────────────────────────────────────
# Case 2 — RESUME_AT_PENDING_DECISION (re-present the gate)
# ──────────────────────────────────────────────────────────────────────────


def test_case_2_pending_decision_surfaces_gate_kind(
    fake_exp_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """state.pending_decision is set → Case 2 with the gate kind in stderr."""
    _write_state(
        fake_exp_dir,
        pending_decision={
            "schema_version": 1,
            "kind": "confirm_brief",
            "opened_at": _utc_iso(),
            "prompt_to_user": "smoke",
            "options": ["yes", "no"],
            "metadata": {},
        },
    )
    _write_log(fake_exp_dir, [])
    rc, _ = _run_resume(fake_exp_dir)
    captured = capsys.readouterr()
    assert rc != 0, "Case 2 must signal user-required (non-zero)"
    assert "resume case 2" in captured.err
    assert "confirm_brief" in captured.err


# ──────────────────────────────────────────────────────────────────────────
# Case 3 — RESUME_AT_MID_COMMIT (duplicate stage in stage_history)
# ──────────────────────────────────────────────────────────────────────────


def test_case_3_duplicate_stage_history_detected(
    fake_exp_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """stage_history with a repeated stage triggers Case 3."""
    _write_state(
        fake_exp_dir,
        stage_history=[
            {"stage": "brief_drafted", "committed_at": _utc_iso()},
            {"stage": "brief_drafted", "committed_at": _utc_iso()},
        ],
    )
    _write_log(fake_exp_dir, [])
    rc, _ = _run_resume(fake_exp_dir)
    captured = capsys.readouterr()
    assert rc != 0
    assert "resume case 3" in captured.err


# ──────────────────────────────────────────────────────────────────────────
# Case 4 — RESUME_AT_AGENT_DISPATCH (orphan agent.dispatched)
# ──────────────────────────────────────────────────────────────────────────


def test_case_4_orphan_session_action_id(
    fake_exp_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """session.last_action_id has no matching row in log.jsonl."""
    _write_state(
        fake_exp_dir,
        session={
            "started_at": _utc_iso(),
            "last_action_id": "01HKZ_ORPHAN_ACTION_ID",
        },
    )
    # Log has events, but NONE with the orphan action_id.
    _write_log(
        fake_exp_dir,
        [{"event_name": "stage.entered", "action_id": "other", "stage": "brief_drafted"}],
    )
    rc, _ = _run_resume(fake_exp_dir)
    captured = capsys.readouterr()
    assert rc != 0
    assert "resume case 4" in captured.err


# ──────────────────────────────────────────────────────────────────────────
# Case 5 — RESUME_AT_QUERY_DISPATCH (log advanced past last_action_id)
# ──────────────────────────────────────────────────────────────────────────


def test_case_5_log_advanced_past_session_action(
    fake_exp_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """log.jsonl has stage events after last_action_id that diverge from current_stage."""
    _write_state(
        fake_exp_dir,
        current_stage="brief_drafted",
        last_committed_stage="brief_drafted",
        session={
            "started_at": _utc_iso(),
            "last_action_id": "01HKZ_LAST_COMMIT_ACTION_ID",
        },
    )
    _write_log(
        fake_exp_dir,
        [
            {
                "event_name": "stage.committed",
                "action_id": "01HKZ_LAST_COMMIT_ACTION_ID",
                "stage": "brief_drafted",
            },
            {
                "event_name": "stage.entered",
                "action_id": "01HKZ_LATER",
                "stage": "data_plan_confirmed",
            },
        ],
    )
    rc, _ = _run_resume(fake_exp_dir)
    captured = capsys.readouterr()
    assert rc != 0
    assert "resume case 5" in captured.err


# ──────────────────────────────────────────────────────────────────────────
# Case 6 — RESUME_AT_STAGE_3B (conversation drift past last_action_id)
# ──────────────────────────────────────────────────────────────────────────


def test_case_6_conversation_drift_detected(
    fake_exp_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """Many conversation turns past session.last_action_id with state stuck."""
    _write_state(
        fake_exp_dir,
        current_stage="brief_drafted",
        last_committed_stage="brief_drafted",
        session={
            "started_at": _utc_iso(),
            "last_action_id": "01HKZ_BASELINE",
        },
    )
    # No log advancement beyond baseline action — just baseline row, no drift.
    _write_log(
        fake_exp_dir,
        [
            {
                "event_name": "stage.committed",
                "action_id": "01HKZ_BASELINE",
                "stage": "brief_drafted",
            }
        ],
    )
    # >5 conversation turns whose action_id != baseline.
    conv = fake_exp_dir / "conversation.jsonl"
    conv.write_text(
        "\n".join(
            json.dumps({"action_id": f"DRIFT_{i}", "role": "assistant", "content": "x"})
            for i in range(8)
        )
        + "\n"
    )
    rc, _ = _run_resume(fake_exp_dir)
    captured = capsys.readouterr()
    assert rc != 0
    assert "resume case 6" in captured.err


# ──────────────────────────────────────────────────────────────────────────
# Case 7 — RESUME_AT_GATE_BLOCKED (orphan bundle on disk)
# ──────────────────────────────────────────────────────────────────────────


def test_case_7_orphan_out_yaml_bundle_detected(
    fake_exp_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """bundles/<agent>.out.yaml present but no agent.completed event."""
    _write_state(
        fake_exp_dir,
        current_stage="brief_drafted",
        last_committed_stage="brief_drafted",
    )
    _write_log(fake_exp_dir, [])
    bundles = fake_exp_dir / "bundles"
    bundles.mkdir()
    (bundles / "designer.out.yaml").write_text("schema_version: 1\n")
    rc, _ = _run_resume(fake_exp_dir)
    captured = capsys.readouterr()
    assert rc != 0
    assert "resume case 7" in captured.err


# ──────────────────────────────────────────────────────────────────────────
# Case 8 — RESUME_AT_UNRECOVERABLE (schema_version drift)
# ──────────────────────────────────────────────────────────────────────────


def test_case_8_schema_version_drift_detected(
    fake_exp_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    """schema_version < 3 → Case 8 (corruption / migration needed)."""
    _write_state(
        fake_exp_dir,
        schema_version=1,
        current_stage="brief_drafted",
        last_committed_stage="brief_drafted",
    )
    _write_log(fake_exp_dir, [])
    rc, _ = _run_resume(fake_exp_dir)
    captured = capsys.readouterr()
    assert rc != 0
    assert "resume case 8" in captured.err
