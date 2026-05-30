"""Track E — end-to-end stage progression on the ship_demo seed (W4.1).

Drives one experiment through all eleven stages (Stage 0 DATA_LOADED →
Stage 8 READOUT) against the real ``OrchestratorStore`` chokepoint with the
audit-chain integrity check ENABLED on every commit. The headless LLM-dispatch
spine is stubbed in v0.1, so this exercises the parts that are live today:
Stage-0 profiling of the DuckDB-readable ship_demo seed, the stage-commit
chokepoint, gate open/resolve pairing, and ``validate_chain`` running on each
commit without halting a clean run.

Exit criterion (REMEDIATION_PLAN W4.1): one experiment runs Stage 0→8
end-to-end on the ship_demo seed with validate_chain enabled.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10.5, §10.7.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentxp.audit.chain import validate_chain
from agentxp.orchestrator.store import OrchestratorStore
from agentxp.profiler.driver import profile_dataset
from agentxp.schemas.state import PendingDecisionKind, Stage

SHIP_DEMO = Path(__file__).resolve().parents[2] / "sample-data" / "ship_demo.csv"


# The eleven main stages in journey order. The Stage 3b substate
# BRIEF_CONTRADICTED is a failure branch, not part of the happy path.
_STAGES = [
    Stage.DATA_LOADED,
    Stage.SEMANTIC_MODELS_DRAFTED,
    Stage.METRICS_BOOTSTRAPPED,
    Stage.INTENT_CAPTURED,
    Stage.HYPOTHESIS_DRAFTED,
    Stage.BRIEF_DRAFTED,
    Stage.DATA_PLAN_CONFIRMED,
    Stage.MONITOR,
    Stage.ANALYZE,
    Stage.INTERPRET,
    Stage.READOUT,
]

# A representative confirmation gate to open+resolve before a few commits, so
# the run exercises gate-pairing (Invariants 4/5) under validate_chain rather
# than a gate-free straight line.
_GATE_BEFORE = {
    Stage.SEMANTIC_MODELS_DRAFTED: PendingDecisionKind.CONFIRM_SEMANTIC_MODEL,
    Stage.BRIEF_DRAFTED: PendingDecisionKind.CONFIRM_BRIEF,
    Stage.READOUT: PendingDecisionKind.CONFIRM_READOUT,
}


def test_stage_0_profiles_the_ship_demo_seed() -> None:
    """Stage 0 profiling reads the DuckDB-backed ship_demo seed (real, not mocked)."""
    pytest.importorskip("duckdb")
    assert SHIP_DEMO.exists(), f"ship_demo seed missing at {SHIP_DEMO}"

    report = profile_dataset("ship_demo", adapter_type="duckdb", file_path=SHIP_DEMO)

    assert report.row_count > 0
    colnames = {c.name for c in report.columns}
    # The seed is an A/B table: a variant column, a conversion outcome, revenue.
    assert {"variant", "converted", "revenue"} <= colnames, colnames


def test_e2e_stage_0_to_8_with_validate_chain(tmp_path: Path) -> None:
    """Drive Stage 0→8 through the chokepoint with the integrity check ON.

    Every ``_commit_stage`` runs ``validate_chain`` internally; the run must
    reach READOUT without a single ``CommitRollback``, proving the validator
    guards the chain without false-positiving across a full clean progression
    (W1 made the validator real — this proves it does not halt a good run).
    """
    pytest.importorskip("duckdb")

    fixed = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    store = OrchestratorStore(
        project_root=tmp_path,
        experiment_id="exp-e2e",
        clock=lambda: fixed,
    )

    for stage in _STAGES:
        gate_kind = _GATE_BEFORE.get(stage)
        if gate_kind is not None:
            store.set_pending(
                gate_kind, options=["proceed", "revise"], prompt=f"Confirm {stage.value}?"
            )
            store.resolve_decision("proceed")
        # No exception means validate_chain returned ok=True at commit time.
        store._commit_stage(stage)

    state = store.state.read()
    assert state.current_stage == Stage.READOUT
    assert state.last_committed_stage == Stage.READOUT
    assert [e.stage for e in state.stage_history] == _STAGES

    # The whole chain validates clean after the full run.
    result = validate_chain("exp-e2e", _root=tmp_path / "experiments")
    assert result.ok is True, f"end-to-end chain failed validation: {result.violations}"
    assert result.violations == []

    rows = [
        json.loads(line)
        for line in (tmp_path / "experiments" / "exp-e2e" / "log.jsonl")
        .read_text()
        .splitlines()
        if line
    ]
    # Exactly one root event; every other event links to a prior action_id.
    roots = [r for r in rows if r.get("parent_action_id") is None]
    assert len(roots) == 1, f"expected exactly one root event, got {len(roots)}"
    # One stage.committed per stage.
    committed = [r for r in rows if r.get("event_name") == "stage.committed"]
    assert len(committed) == len(_STAGES)
