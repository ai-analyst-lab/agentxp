"""Track F — reconstruct in-flight state from the append-only log (W4.2 / J3.3).

``_commit_stage`` emits ``stage.committed`` to ``log.jsonl`` BEFORE writing
``state.yaml`` (append-then-advance, G11), so a crash between the two leaves
the log ahead of state: the durable log records a commit the state file never
caught up to. ``OrchestratorStore.reconstruct_from_log`` closes that window by
rolling ``state.yaml`` forward to the last committed stage in the log.

These tests simulate the crash by committing cleanly and then rewinding only
``state.yaml`` (the log is untouched, exactly as a crash before the state write
would leave it), then assert reconstruction recovers the lost advance.

Exit criterion (REMEDIATION_PLAN W4.2): an interrupted run can be resumed from
the log.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10.6.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agentxp.audit.chain import validate_chain
from agentxp.orchestrator.store import OrchestratorStore
from agentxp.schemas.state import Stage

_FIXED = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# A short happy-path prefix: Stage 0 → Stage 4.
_COMMITTED = [
    Stage.DATA_LOADED,
    Stage.SEMANTIC_MODELS_DRAFTED,
    Stage.METRICS_BOOTSTRAPPED,
    Stage.INTENT_CAPTURED,
    Stage.HYPOTHESIS_DRAFTED,
    Stage.BRIEF_DRAFTED,
    Stage.DATA_PLAN_CONFIRMED,
]


def _commit_prefix(tmp_path: Path, exp_id: str) -> OrchestratorStore:
    store = OrchestratorStore(
        project_root=tmp_path, experiment_id=exp_id, clock=lambda: _FIXED
    )
    for stage in _COMMITTED:
        store._commit_stage(stage)
    return store


def test_reconstruct_rolls_state_forward_to_log(tmp_path: Path) -> None:
    """Crash window: log has the last commit, state.yaml does not → roll forward."""
    store = _commit_prefix(tmp_path, "exp-resume")

    # Emulate the W2.2 crash: the final commit reached the log but the
    # state.yaml write never happened. Rewind ONLY state.yaml one stage, and
    # mirror a content field to prove reconstruction preserves non-stage state.
    state = store.state.read()
    lost_stage = state.stage_history[-1].stage  # DATA_PLAN_CONFIRMED
    state.stage_history = state.stage_history[:-1]
    prev = state.stage_history[-1].stage
    state.current_stage = prev
    state.last_committed_stage = prev
    state.intent = "ship the new checkout button"
    store.state.write(state)

    # A fresh store instance resumes the experiment.
    resumed = OrchestratorStore(
        project_root=tmp_path, experiment_id="exp-resume", clock=lambda: _FIXED
    )
    rolled = resumed.reconstruct_from_log()

    assert rolled == lost_stage
    recovered = resumed.state.read()
    assert recovered.current_stage == lost_stage
    assert recovered.last_committed_stage == lost_stage
    # stage_history is rebuilt from the authoritative log — full prefix back.
    assert [e.stage for e in recovered.stage_history] == _COMMITTED
    # Non-stage state is preserved, not clobbered.
    assert recovered.intent == "ship the new checkout button"

    # Idempotent: a second reconstruction is a no-op now that state matches.
    assert resumed.reconstruct_from_log() is None

    # The chain is still valid after reconstruction (state.yaml is off-chain).
    result = validate_chain("exp-resume", _root=tmp_path / "experiments")
    assert result.ok is True, result.violations


def test_reconstruct_is_noop_on_a_clean_in_sync_run(tmp_path: Path) -> None:
    """No crash: state already matches the log → reconstruction changes nothing."""
    store = _commit_prefix(tmp_path, "exp-clean")
    before = store.state.read()

    resumed = OrchestratorStore(
        project_root=tmp_path, experiment_id="exp-clean", clock=lambda: _FIXED
    )
    assert resumed.reconstruct_from_log() is None

    after = resumed.state.read()
    assert after.current_stage == before.current_stage == Stage.DATA_PLAN_CONFIRMED
    assert [e.stage for e in after.stage_history] == _COMMITTED


def test_reconstruct_bootstraps_when_state_yaml_absent(tmp_path: Path) -> None:
    """Crash before the very first state write: log exists, state.yaml does not."""
    store = _commit_prefix(tmp_path, "exp-nostate")
    last = _COMMITTED[-1]

    # Delete state.yaml entirely — the log is the only surviving record.
    state_path = store.state.path
    state_path.unlink()
    assert not state_path.exists()

    resumed = OrchestratorStore(
        project_root=tmp_path, experiment_id="exp-nostate", clock=lambda: _FIXED
    )
    rolled = resumed.reconstruct_from_log()

    assert rolled == last
    recovered = resumed.state.read()
    assert recovered.current_stage == last
    assert recovered.last_committed_stage == last
    assert [e.stage for e in recovered.stage_history] == _COMMITTED


def test_reconstruct_returns_none_when_no_committed_stage(tmp_path: Path) -> None:
    """A log with no stage.committed event has nothing to roll forward to."""
    store = OrchestratorStore(
        project_root=tmp_path, experiment_id="exp-empty", clock=lambda: _FIXED
    )
    # No commits at all — empty experiment dir, no log.jsonl.
    assert store.reconstruct_from_log() is None
