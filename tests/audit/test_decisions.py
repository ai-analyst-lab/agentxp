"""Tests for agentxp.audit.decisions — per-stage decision artifact writer.

Covers acceptance criteria for the AgentXP v0.1 decisions writer (§22.5, §10,
§1.8.12):

  1. Round-trip: write a Decision, read it back, fields equal.
  2. Atomic write lands chmod 600 (no world-readable window).
  3. Non-existent decisions/ directory gets created on first write.
  4. Filename format: ``{ordinal:02d}-{stage}.yaml``.
  5. Zero-padding for ordinals 0-99.
  6. ``next_ordinal`` on an empty / missing directory returns 0.
  7. ``next_ordinal`` after N writes returns N (max + 1).
  8. ``read_decision`` resolves the stage suffix automatically.
  9. ``read_all_decisions`` returns ordinal-sorted list regardless of write order.
 10. ``decided_at`` UTC validator rejects naive datetimes.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §22.5, §10, §1.8.12.
"""
from __future__ import annotations

import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentxp.audit.decisions import (
    Decision,
    next_ordinal,
    read_all_decisions,
    read_decision,
    write_decision,
)


def _make_decision(
    ordinal: int = 0,
    stage: str = "data_loaded",
    *,
    action_id: str = "01HXAAAA0000000000000000A0",
    artifacts: list[str] | None = None,
    user_input: str | None = None,
    agent_outputs: list[dict] | None = None,
    gate_resolved: dict | None = None,
) -> Decision:
    return Decision(
        ordinal=ordinal,
        stage=stage,
        decided_at=datetime.now(timezone.utc),
        action_id=action_id,
        artifacts_written=artifacts or [],
        user_input=user_input,
        agent_outputs=agent_outputs or [],
        gate_resolved=gate_resolved,
    )


def _mode_of(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_write_decision_round_trip(tmp_path: Path) -> None:
    """Write a Decision, read it back; every field round-trips."""
    decision = _make_decision(
        ordinal=3,
        stage="brief_drafted",
        action_id="01HXBBBB0000000000000000B0",
        artifacts=["brief.yaml", "hypothesis.yaml"],
        user_input="Run an experiment on checkout conversion.",
        agent_outputs=[
            {
                "agent_name": "brief_drafter",
                "action_id": "01HXBBBB0000000000000000B1",
                "bundle_out_path": "bundles/brief_drafter.out.yaml",
            }
        ],
        gate_resolved={
            "kind": "confirm_brief",
            "choice": "confirm",
            "rationale": "Looks good.",
            "reason_code": None,
        },
    )
    write_decision(tmp_path, decision)
    loaded = read_decision(tmp_path, 3)
    assert loaded == decision


def test_write_decision_atomic(tmp_path: Path) -> None:
    """Written file lands with chmod 0o600; no .tmp left behind."""
    decision = _make_decision(ordinal=0, stage="data_loaded")
    path = write_decision(tmp_path, decision)
    assert path.exists()
    assert _mode_of(path) == 0o600, (
        f"decisions/*.yaml must be chmod 600; got {oct(_mode_of(path))}"
    )
    # No tempfile leftover.
    leftovers = list(path.parent.glob("*.tmp"))
    assert leftovers == [], f"unexpected .tmp leftover: {leftovers}"


def test_write_decision_creates_decisions_dir(tmp_path: Path) -> None:
    """First write into a fresh experiment dir auto-creates decisions/."""
    decisions_dir = tmp_path / "decisions"
    assert not decisions_dir.exists()
    decision = _make_decision(ordinal=0, stage="data_loaded")
    write_decision(tmp_path, decision)
    assert decisions_dir.is_dir()


def test_filename_format(tmp_path: Path) -> None:
    """ordinal=0 + stage='data_loaded' → '00-data_loaded.yaml'."""
    decision = _make_decision(ordinal=0, stage="data_loaded")
    path = write_decision(tmp_path, decision)
    assert path.name == "00-data_loaded.yaml"


def test_filename_zero_padding(tmp_path: Path) -> None:
    """Ordinals 7 and 12 zero-pad to width 2."""
    write_decision(tmp_path, _make_decision(ordinal=7, stage="monitor"))
    write_decision(tmp_path, _make_decision(ordinal=12, stage="analyze"))
    names = sorted(p.name for p in (tmp_path / "decisions").glob("*.yaml"))
    assert "07-monitor.yaml" in names
    assert "12-analyze.yaml" in names


def test_next_ordinal_empty_dir(tmp_path: Path) -> None:
    """No decisions/ directory → next_ordinal returns 0."""
    assert next_ordinal(tmp_path) == 0
    # Also true once the dir exists but is empty.
    (tmp_path / "decisions").mkdir()
    assert next_ordinal(tmp_path) == 0


def test_next_ordinal_with_existing(tmp_path: Path) -> None:
    """Write 3 decisions (ordinals 0, 1, 2); next_ordinal returns 3."""
    for i, stage in enumerate(["data_loaded", "semantic_models_drafted", "metrics_bootstrapped"]):
        write_decision(tmp_path, _make_decision(ordinal=i, stage=stage))
    assert next_ordinal(tmp_path) == 3


def test_read_decision_round_trip(tmp_path: Path) -> None:
    """write + read by ordinal returns an equivalent Decision."""
    decision = _make_decision(
        ordinal=5,
        stage="data_plan_confirmed",
        artifacts=["data_plan.yaml"],
    )
    write_decision(tmp_path, decision)
    loaded = read_decision(tmp_path, 5)
    assert loaded.ordinal == 5
    assert loaded.stage == "data_plan_confirmed"
    assert loaded.artifacts_written == ["data_plan.yaml"]
    assert loaded.action_id == decision.action_id


def test_read_decision_missing_raises(tmp_path: Path) -> None:
    """No file for the requested ordinal → FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        read_decision(tmp_path, 0)


def test_read_all_decisions_in_order(tmp_path: Path) -> None:
    """Write 5 decisions out of order; read_all_decisions returns ordinal-sorted."""
    stages = [
        "data_loaded",
        "semantic_models_drafted",
        "metrics_bootstrapped",
        "intent_captured",
        "hypothesis_drafted",
    ]
    # Write in jumbled order.
    write_order = [3, 0, 4, 1, 2]
    for i in write_order:
        write_decision(tmp_path, _make_decision(ordinal=i, stage=stages[i]))
    loaded = read_all_decisions(tmp_path)
    assert [d.ordinal for d in loaded] == [0, 1, 2, 3, 4]
    assert [d.stage for d in loaded] == stages


def test_read_all_decisions_empty(tmp_path: Path) -> None:
    """Missing decisions/ dir → read_all returns []."""
    assert read_all_decisions(tmp_path) == []


def test_decision_utc_validator() -> None:
    """Naive datetime on decided_at raises ValidationError."""
    naive = datetime(2026, 5, 28, 12, 0, 0)  # no tzinfo
    with pytest.raises(ValidationError):
        Decision(
            ordinal=0,
            stage="data_loaded",
            decided_at=naive,
            action_id="01HXAAAA0000000000000000A0",
        )


def test_decision_non_utc_offset_rejected() -> None:
    """Non-zero UTC offset on decided_at raises ValidationError (§1.7.2)."""
    pst = timezone(timedelta(hours=-8))
    with pytest.raises(ValidationError):
        Decision(
            ordinal=0,
            stage="data_loaded",
            decided_at=datetime(2026, 5, 28, 12, 0, 0, tzinfo=pst),
            action_id="01HXAAAA0000000000000000A0",
        )


def test_decision_extra_fields_forbidden() -> None:
    """ConfigDict(extra='forbid') rejects unknown fields."""
    with pytest.raises(ValidationError):
        Decision(
            ordinal=0,
            stage="data_loaded",
            decided_at=datetime.now(timezone.utc),
            action_id="01HXAAAA0000000000000000A0",
            unexpected_field="nope",
        )
