"""Tests for agentxp.orchestrator.store — StateStore + OrchestratorStore.

Covers:

- §10 OrchestratorStore Python API spec (init, attribute wiring, dispatch
  delegation, dispatch_sql v0.1 stub).
- §10.5.2 SIGINT deferral around ``_commit_stage`` critical section.
- §10.5.3 disk-full pre-flight: ``gate.blocked(reason="disk_full")`` with no
  state mutation.
- §10.5.8 validate_chain rollback: ``ok=False`` rolls state.yaml back, emits
  ``gate.blocked(reason="chain_validation_failed")``, raises CommitRollback.
- §10.6.3 stale-lock detection: dead PID in ``.state.lock`` surfaces
  StaleLockError.
- Atomic + chmod-600 writes; pending-decision gate plumbing.

Source spec: OPENXP_V01_PLAN.md §10, §10.5, §10.6.3.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import signal
import stat
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from pydantic import BaseModel

from agentxp.orchestrator import store as store_mod
from agentxp.orchestrator.store import (
    ArtifactLocked,
    CommitRollback,
    InsufficientDiskSpace,
    OrchestratorStore,
    StaleLockError,
    StateStore,
    _check_disk_space,
)
from agentxp.schemas.report import ChainValidation, Violation
from agentxp.schemas.state import (
    LockMetadata,
    PendingDecisionKind,
    Stage,
    StateYaml,
)


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    for sub in ("semantic_models", "fact_sources", "metrics", "assignments"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def orchestrator(project_root: Path) -> OrchestratorStore:
    return OrchestratorStore(project_root, "exp_001")


def _initial_state(exp_id: str = "exp_001") -> StateYaml:
    return StateYaml(
        experiment_id=exp_id,
        current_stage=Stage.DATA_LOADED,
    )


def _ok_chain(*_args, **_kwargs) -> ChainValidation:
    return ChainValidation(
        ok=True,
        invariants_checked=[1, 2, 3, 4, 5],
        violations=[],
        ms=1.0,
        perf_warning=False,
    )


# ──────────────────────────────────────────────────────────────────────────
# StateStore (5)
# ──────────────────────────────────────────────────────────────────────────


def test_state_store_read_round_trip(tmp_path: Path) -> None:
    """Writing a StateYaml then reading it back yields equivalent fields."""
    state_path = tmp_path / "state.yaml"
    store = StateStore(state_path)
    s = _initial_state()
    store.write(s)
    loaded = store.read()
    assert loaded.experiment_id == s.experiment_id
    assert loaded.current_stage == s.current_stage
    assert loaded.schema_version == 3


def test_state_store_write_atomic(tmp_path: Path) -> None:
    """Writes land with chmod 600 and the file exists at the canonical path."""
    state_path = tmp_path / "state.yaml"
    store = StateStore(state_path)
    store.write(_initial_state())
    assert state_path.exists()
    mode = stat.S_IMODE(state_path.stat().st_mode)
    assert mode == 0o600


def test_state_store_concurrent_writes_serialize(tmp_path: Path) -> None:
    """Successive writes through StateStore — each lands atomically.

    StateStore itself does not promise concurrency safety (the
    orchestrator's `.state.lock` is the lock); but each individual
    write through ``_atomic_write_bytes`` is atomic (tmp + os.replace)
    so a long sequence of writes never leaves the file half-written.
    """
    state_path = tmp_path / "state.yaml"
    store = StateStore(state_path)

    for i in range(40):
        s = _initial_state()
        s.current_stage = (
            Stage.DATA_LOADED if i % 2 == 0 else Stage.SEMANTIC_MODELS_DRAFTED
        )
        store.write(s)

    loaded = store.read()
    assert loaded.current_stage == Stage.SEMANTIC_MODELS_DRAFTED


def test_state_store_read_raises_for_missing(tmp_path: Path) -> None:
    """Reading a non-existent state.yaml raises FileNotFoundError."""
    store = StateStore(tmp_path / "missing.yaml")
    with pytest.raises(FileNotFoundError):
        store.read()


def test_state_store_lock_path(tmp_path: Path) -> None:
    """lock_path is the sidecar `.state.lock` in the same directory."""
    state_path = tmp_path / "exp_dir" / "state.yaml"
    store = StateStore(state_path)
    assert store.lock_path == tmp_path / "exp_dir" / ".state.lock"


# ──────────────────────────────────────────────────────────────────────────
# OrchestratorStore basics (5)
# ──────────────────────────────────────────────────────────────────────────


def test_orchestrator_init_creates_experiment_dir(project_root: Path) -> None:
    orc = OrchestratorStore(project_root, "exp_777")
    exp_dir = project_root / "experiments" / "exp_777"
    assert exp_dir.exists() and exp_dir.is_dir()
    assert orc.exp_id == "exp_777"


def test_orchestrator_state_attribute_is_state_store(orchestrator: OrchestratorStore) -> None:
    assert isinstance(orchestrator.state, StateStore)


def test_orchestrator_bundles_attribute_is_bundle_store(orchestrator: OrchestratorStore) -> None:
    from agentxp.orchestrator.bundle import BundleStore
    assert isinstance(orchestrator.bundles, BundleStore)


def test_orchestrator_conversation_attribute_is_conversation_store(orchestrator: OrchestratorStore) -> None:
    from agentxp.orchestrator.conversation import ConversationStore
    assert isinstance(orchestrator.conversation, ConversationStore)


def test_orchestrator_locks_path_under_exp_dir(orchestrator: OrchestratorStore, project_root: Path) -> None:
    expected = project_root / "experiments" / "exp_001" / ".state.lock"
    assert orchestrator.lock_path == expected


# ──────────────────────────────────────────────────────────────────────────
# _commit_stage (10)
# ──────────────────────────────────────────────────────────────────────────


def test_commit_stage_happy_path_writes_state_and_emits_event(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful commit advances state.yaml and emits stage.committed."""
    monkeypatch.setattr(store_mod, "validate_chain", _ok_chain)

    orchestrator._commit_stage(Stage.SEMANTIC_MODELS_DRAFTED)

    state = orchestrator.state.read()
    assert state.current_stage == Stage.SEMANTIC_MODELS_DRAFTED
    assert state.last_committed_stage == Stage.SEMANTIC_MODELS_DRAFTED
    assert len(state.stage_history) == 1

    log_path = orchestrator._exp_dir() / "log.jsonl"
    assert log_path.exists()
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    committed = [e for e in events if e.get("event_name") == "stage.committed"]
    assert len(committed) == 1
    assert committed[0]["stage"] == Stage.SEMANTIC_MODELS_DRAFTED.value


def test_commit_stage_chmods_state_yaml_to_600(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_mod, "validate_chain", _ok_chain)
    orchestrator._commit_stage(Stage.SEMANTIC_MODELS_DRAFTED)
    mode = stat.S_IMODE(orchestrator.state.path.stat().st_mode)
    assert mode == 0o600


def test_commit_stage_pre_flight_disk_full_emits_gate_blocked(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patch shutil.disk_usage to report 0 free bytes — commit aborts cleanly."""
    import shutil as _shutil

    DiskUsage = type("DU", (), {})

    def fake_disk_usage(_path):
        du = DiskUsage()
        du.total = 100_000_000
        du.used = 100_000_000
        du.free = 0
        return du

    monkeypatch.setattr(store_mod.shutil, "disk_usage", fake_disk_usage)
    monkeypatch.setattr(store_mod, "validate_chain", _ok_chain)

    # State.yaml does not exist beforehand.
    assert not orchestrator.state.path.exists()
    orchestrator._commit_stage(Stage.SEMANTIC_MODELS_DRAFTED)

    # No state mutation.
    assert not orchestrator.state.path.exists()

    # gate.blocked was emitted with reason=disk_full.
    log_path = orchestrator._exp_dir() / "log.jsonl"
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    blocked = [e for e in events if e.get("event_name") == "gate.blocked"]
    assert len(blocked) == 1
    assert blocked[0]["reason"] == "disk_full"
    assert blocked[0]["metadata"]["subtype"] == "disk_full"


def test_commit_stage_validate_chain_failure_rolls_back(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """validate_chain returning ok=False rolls state.yaml back to its prior contents."""
    # Seed state.yaml at INTENT_CAPTURED so we can detect a successful rollback.
    seed = StateYaml(experiment_id="exp_001", current_stage=Stage.INTENT_CAPTURED)
    orchestrator.state.write(seed)
    pre_bytes = orchestrator.state.path.read_bytes()

    def failing_chain(*_args, **_kwargs) -> ChainValidation:
        return ChainValidation(
            ok=False,
            invariants_checked=[1, 2, 3, 4, 5],
            violations=[Violation(invariant_id=1, description="synthetic")],
            ms=2.0,
            perf_warning=False,
        )

    monkeypatch.setattr(store_mod, "validate_chain", failing_chain)

    with pytest.raises(CommitRollback):
        orchestrator._commit_stage(Stage.HYPOTHESIS_DRAFTED)

    # Bytes restored to the pre-attempt snapshot.
    post_bytes = orchestrator.state.path.read_bytes()
    assert post_bytes == pre_bytes

    # gate.blocked emitted with reason=chain_validation_failed.
    log_path = orchestrator._exp_dir() / "log.jsonl"
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    blocked = [e for e in events if e.get("event_name") == "gate.blocked"]
    assert any(b["reason"] == "chain_validation_failed" for b in blocked)


def test_commit_stage_acquires_state_lock(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chokepoint must call _file_lock exactly once per commit."""
    monkeypatch.setattr(store_mod, "validate_chain", _ok_chain)

    calls: list[None] = []
    real_lock = orchestrator._file_lock

    from contextlib import contextmanager as _cm

    @_cm
    def spy_lock(*args, **kwargs):
        calls.append(None)
        with real_lock(*args, **kwargs):
            yield

    monkeypatch.setattr(orchestrator, "_file_lock", spy_lock)
    orchestrator._commit_stage(Stage.SEMANTIC_MODELS_DRAFTED)
    assert len(calls) == 1


def test_commit_stage_appends_stage_history(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_mod, "validate_chain", _ok_chain)

    orchestrator._commit_stage(Stage.SEMANTIC_MODELS_DRAFTED)
    s1 = orchestrator.state.read()
    assert len(s1.stage_history) == 1
    assert s1.stage_history[0].stage == Stage.SEMANTIC_MODELS_DRAFTED

    orchestrator._commit_stage(Stage.METRICS_BOOTSTRAPPED)
    s2 = orchestrator.state.read()
    assert len(s2.stage_history) == 2
    assert s2.stage_history[-1].stage == Stage.METRICS_BOOTSTRAPPED


def test_commit_stage_event_emitted_once(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_mod, "validate_chain", _ok_chain)
    orchestrator._commit_stage(Stage.SEMANTIC_MODELS_DRAFTED)
    log_path = orchestrator._exp_dir() / "log.jsonl"
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    committed = [e for e in events if e.get("event_name") == "stage.committed"]
    assert len(committed) == 1


def test_commit_stage_writes_artifacts_atomically(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Artifacts in the dict land at the right paths with chmod 600."""
    monkeypatch.setattr(store_mod, "validate_chain", _ok_chain)

    class Artifact(BaseModel):
        name: str
        value: int

    artifact = Artifact(name="thing", value=42)
    orchestrator._commit_stage(
        Stage.SEMANTIC_MODELS_DRAFTED,
        artifacts={"decisions/00-thing.yaml": artifact},
    )

    target = orchestrator._exp_dir() / "decisions" / "00-thing.yaml"
    assert target.exists()
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600
    loaded = yaml.safe_load(target.read_text())
    assert loaded == {"name": "thing", "value": 42}


def test_write_artifact_refuses_to_overwrite_committed_artifact(
    orchestrator: OrchestratorStore,
) -> None:
    """G9 integrity wall: a second write to an existing artifact path is refused.

    Every artifact reaches disk through _commit_stage, so a file already on
    disk is committed. _write_artifact must refuse a silent overwrite.
    """
    class Artifact(BaseModel):
        name: str
        value: int

    orchestrator._write_artifact("brief.yaml", Artifact(name="locked", value=1))

    with pytest.raises(ArtifactLocked) as exc_info:
        orchestrator._write_artifact("brief.yaml", Artifact(name="loosened", value=2))
    assert "brief.yaml" in str(exc_info.value)

    # The on-disk artifact is unchanged — the loosening write never landed.
    target = orchestrator._exp_dir() / "brief.yaml"
    assert yaml.safe_load(target.read_text()) == {"name": "locked", "value": 1}


def test_write_artifact_amend_allows_explicit_overwrite(
    orchestrator: OrchestratorStore,
) -> None:
    """The amendments seam: amend=True permits an explicit, logged overwrite."""
    class Artifact(BaseModel):
        name: str
        value: int

    orchestrator._write_artifact("brief.yaml", Artifact(name="locked", value=1))
    orchestrator._write_artifact(
        "brief.yaml", Artifact(name="amended", value=2), amend=True
    )

    target = orchestrator._exp_dir() / "brief.yaml"
    assert yaml.safe_load(target.read_text()) == {"name": "amended", "value": 2}


def test_commit_stage_sigint_during_critical_section_deferred(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SIGINT raised mid-critical-section is deferred until block exit.

    We patch validate_chain to fire SIGINT at the current process, then
    assert that (a) the commit completed (state.yaml advanced, event
    emitted) AND (b) KeyboardInterrupt was raised at block exit.
    """
    def sigint_then_ok(*_args, **_kwargs) -> ChainValidation:
        os.kill(os.getpid(), signal.SIGINT)
        return _ok_chain()

    monkeypatch.setattr(store_mod, "validate_chain", sigint_then_ok)

    with pytest.raises(KeyboardInterrupt):
        orchestrator._commit_stage(Stage.SEMANTIC_MODELS_DRAFTED)

    # Commit landed despite the interrupt.
    state = orchestrator.state.read()
    assert state.current_stage == Stage.SEMANTIC_MODELS_DRAFTED
    log_path = orchestrator._exp_dir() / "log.jsonl"
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    assert any(e.get("event_name") == "stage.committed" for e in events)


def test_commit_stage_subtype_recorded_on_event(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_mod, "validate_chain", _ok_chain)
    orchestrator._commit_stage(
        Stage.SEMANTIC_MODELS_DRAFTED,
        subtype="recovered_from_state_yaml",
    )
    log_path = orchestrator._exp_dir() / "log.jsonl"
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    committed = [e for e in events if e.get("event_name") == "stage.committed"]
    assert committed[0]["metadata"]["subtype"] == "recovered_from_state_yaml"


# ──────────────────────────────────────────────────────────────────────────
# Dispatch + gates (5)
# ──────────────────────────────────────────────────────────────────────────


def test_dispatch_agent_delegates_to_dispatch_module(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OrchestratorStore.dispatch_agent passes through to dispatch.dispatch_agent."""
    from agentxp.orchestrator.dispatch import DispatchResult

    class OutSchema(BaseModel):
        ok: bool = True

    sentinel = DispatchResult(
        out=OutSchema(),
        action_id="ACTID",
        attempts=1,
        raw_response="{}",
    )

    captured: dict[str, Any] = {}

    def fake_impl(req):
        captured["req"] = req
        return sentinel

    monkeypatch.setattr(store_mod, "_dispatch_agent_impl", fake_impl)

    result = orchestrator.dispatch_agent(
        "profiler",
        bundle={"foo": "bar"},
        out_schema=OutSchema,
    )
    assert result is sentinel
    assert captured["req"].agent_name == "profiler"
    assert captured["req"].experiment_id == "exp_001"
    assert captured["req"].ctx_bundle == {"foo": "bar"}


def test_dispatch_sql_raises_not_implemented_in_v01(
    orchestrator: OrchestratorStore,
) -> None:
    with pytest.raises(NotImplementedError, match="W_sql"):
        orchestrator.dispatch_sql({"sql": "SELECT 1"}, {})


def test_set_pending_writes_state_and_emits_gate_opened(
    orchestrator: OrchestratorStore,
) -> None:
    orchestrator.set_pending(
        kind=PendingDecisionKind.CONFIRM_BRIEF,
        options=["accept", "edit"],
        prompt="Confirm the brief?",
    )
    state = orchestrator.state.read()
    assert state.pending_decision is not None
    assert state.pending_decision.kind == PendingDecisionKind.CONFIRM_BRIEF

    log_path = orchestrator._exp_dir() / "log.jsonl"
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    opened = [e for e in events if e.get("event_name") == "gate.opened"]
    assert len(opened) == 1
    assert opened[0]["kind"] == "confirm_brief"


def test_resolve_decision_clears_pending_and_emits_gate_resolved(
    orchestrator: OrchestratorStore,
) -> None:
    orchestrator.set_pending(
        kind=PendingDecisionKind.CONFIRM_BRIEF,
        options=["accept", "edit"],
        prompt="Confirm the brief?",
    )
    orchestrator.resolve_decision(choice="accept", rationale="looks good")
    state = orchestrator.state.read()
    assert state.pending_decision is None

    log_path = orchestrator._exp_dir() / "log.jsonl"
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    resolved = [e for e in events if e.get("event_name") == "gate.resolved"]
    assert len(resolved) == 1
    assert resolved[0]["choice"] == "accept"
    assert resolved[0]["rationale"] == "looks good"


def test_override_emits_gate_resolved_with_subtype(
    orchestrator: OrchestratorStore,
) -> None:
    orchestrator.set_pending(
        kind=PendingDecisionKind.SRM_OVERRIDE,
        options=["override", "abort"],
        prompt="Override SRM yellow halt?",
    )
    orchestrator.override(
        reason="external imbalance acknowledged",
        reason_code="known_imbalance",
    )
    state = orchestrator.state.read()
    assert state.pending_decision is None

    log_path = orchestrator._exp_dir() / "log.jsonl"
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    resolved = [e for e in events if e.get("event_name") == "gate.resolved"]
    assert len(resolved) == 1
    assert resolved[0]["choice"] == "override"
    assert resolved[0]["metadata"]["subtype"] == "known_imbalance"


# ──────────────────────────────────────────────────────────────────────────
# Stale lock (2)
# ──────────────────────────────────────────────────────────────────────────


def test_stale_lock_detected_with_dead_pid(
    orchestrator: OrchestratorStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `.state.lock` whose envelope PID is dead surfaces StaleLockError."""
    # Pre-create the lock file with a known-dead PID envelope.
    lock_path = orchestrator.lock_path
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    meta = LockMetadata(
        pid=999_999_999,  # vanishingly unlikely to exist
        started_at=datetime.now(timezone.utc),
        hostname=None,
    )
    lock_path.write_text(json.dumps(meta.model_dump(mode="json")))

    # Pin the lock from another fd to force contention.
    contender_fd = os.open(str(lock_path), os.O_RDWR)
    try:
        import fcntl as _fcntl
        _fcntl.flock(contender_fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
    except Exception:
        os.close(contender_fd)
        pytest.skip("fcntl flock unavailable in this environment")

    # Force the PID-aliveness probe to return False.
    monkeypatch.setattr(
        OrchestratorStore, "_pid_is_alive", lambda self, pid: False
    )

    try:
        with pytest.raises(StaleLockError):
            with orchestrator._file_lock(timeout_s=0.5):
                pass
    finally:
        try:
            import fcntl as _fcntl
            _fcntl.flock(contender_fd, _fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(contender_fd)


def test_fresh_lock_blocks_then_acquires(
    orchestrator: OrchestratorStore, tmp_path: Path
) -> None:
    """A live lock holder blocks until released; second acquirer waits.

    Uses an in-process thread holding a separate fd. On POSIX, flock is
    per-open-file-description, so a sibling fd opened in the same process
    contends just like a sibling process would. The stale-check is
    short-circuited by writing the current PID into the envelope (alive
    by definition).
    """
    if os.name == "nt":  # pragma: no cover
        pytest.skip("POSIX flock semantics required for this test")
    import fcntl as _fcntl

    lock_path = orchestrator.lock_path
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    meta = LockMetadata(
        pid=os.getpid(),
        started_at=datetime.now(timezone.utc),
        hostname=None,
    )
    lock_path.write_text(json.dumps(meta.model_dump(mode="json")))

    # Ensure the lock file exists for the contender fd.
    if not lock_path.exists():
        lock_path.touch()
        os.chmod(lock_path, 0o600)

    contender_fd = os.open(str(lock_path), os.O_RDWR)
    _fcntl.flock(contender_fd, _fcntl.LOCK_EX)

    released = threading.Event()

    def releaser() -> None:
        time.sleep(0.6)
        try:
            _fcntl.flock(contender_fd, _fcntl.LOCK_UN)
        except OSError:
            pass
        released.set()

    t = threading.Thread(target=releaser)
    t.start()
    try:
        start = time.monotonic()
        with orchestrator._file_lock(timeout_s=5.0):
            elapsed = time.monotonic() - start
        assert elapsed >= 0.2, (
            f"expected to wait for the lock, only waited {elapsed:.2f}s"
        )
    finally:
        released.wait(timeout=5)
        t.join(timeout=2)
        os.close(contender_fd)


# ──────────────────────────────────────────────────────────────────────────
# Disk-space helper (sanity)
# ──────────────────────────────────────────────────────────────────────────


def test_check_disk_space_raises_when_below_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    DiskUsage = type("DU", (), {})

    def fake_usage(_p):
        du = DiskUsage()
        du.total = 100
        du.used = 100
        du.free = 0
        return du

    monkeypatch.setattr(store_mod.shutil, "disk_usage", fake_usage)
    with pytest.raises(InsufficientDiskSpace):
        _check_disk_space(tmp_path)
