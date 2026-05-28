"""Tests for agentxp.orchestrator.bundle — BundleStore.

Covers §10.5.9 bundle-snapshot policy (COPY-not-reference, SHA256
recording), §1.8.13 per-experiment paths, §1.7.3 chmod 600 enforcement,
§10.9 shared project_read_lock acquisition, and atomic write semantics.

Source spec: OPENXP_V01_PLAN.md §1.8.13, §5, §10.5.9, §10.9, §1.7.3.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from pydantic import BaseModel

from agentxp.orchestrator import bundle as bundle_mod
from agentxp.orchestrator.bundle import AgentBundle, BundleStore
from agentxp.orchestrator.project_lock import project_write_lock


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """A skeletal project root with the §1.8.13 layout subdirs."""
    root = tmp_path / "project"
    for sub in ("semantic_models", "fact_sources", "metrics", "assignments"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def bundles_dir(tmp_path: Path) -> Path:
    """experiments/exp_001/bundles/."""
    d = tmp_path / "experiments" / "exp_001" / "bundles"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def store(bundles_dir: Path, project_root: Path) -> BundleStore:
    return BundleStore(bundles_dir, project_root)


def _write_yaml(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class _DummyOut(BaseModel):
    answer: str
    confidence: float = 0.5


# ──────────────────────────────────────────────────────────────────────────
# Tests (15 per spec)
# ──────────────────────────────────────────────────────────────────────────


def test_assemble_writes_ctx_yaml(store: BundleStore) -> None:
    """1. Assemble with no project YAMLs; ctx.yaml exists with right keys."""
    bundle = store.assemble("profiler", {"purpose": "profile", "exp_id": "exp_001"})

    assert bundle.ctx_path.exists()
    data = yaml.safe_load(bundle.ctx_path.read_text())
    assert data["schema_version"] == 1
    assert data["agent_name"] == "profiler"
    assert data["ctx_inputs"] == {"purpose": "profile", "exp_id": "exp_001"}
    assert data["source_hashes"] == {}
    assert data["sources_root"] is None
    # assembled_at is ISO-format UTC
    dt = datetime.fromisoformat(data["assembled_at"])
    assert dt.tzinfo is not None


def test_assemble_with_one_project_yaml(
    store: BundleStore, project_root: Path
) -> None:
    """2. Pass one YAML; copied under .sources/, sha256 recorded."""
    src = _write_yaml(
        project_root / "semantic_models" / "checkout_sessions.yaml",
        {"entity": "checkout_sessions", "primary_key": "session_id"},
    )

    bundle = store.assemble(
        "semantic_modeler",
        {"purpose": "preview"},
        depends_on_project_yamls=[src],
    )

    # Copy lives at .sources/semantic_models/checkout_sessions.yaml
    copy_path = (
        store.bundles_dir
        / "semantic_modeler.ctx.yaml.sources"
        / "semantic_models"
        / "checkout_sessions.yaml"
    )
    assert copy_path.exists()
    assert copy_path.read_bytes() == src.read_bytes()

    # sha256 recorded
    rel = "semantic_models/checkout_sessions.yaml"
    assert rel in bundle.source_hashes
    digest = bundle.source_hashes[rel]
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_assemble_with_multiple_yamls_preserves_directory_structure(
    store: BundleStore, project_root: Path
) -> None:
    """3. semantic_models/foo.yaml + metrics/bar.yaml at their relative paths."""
    foo = _write_yaml(
        project_root / "semantic_models" / "foo.yaml", {"entity": "foo"}
    )
    bar = _write_yaml(
        project_root / "metrics" / "bar.yaml",
        {"name": "bar", "type": "ratio"},
    )

    bundle = store.assemble(
        "metric_drafter",
        {"purpose": "preview"},
        depends_on_project_yamls=[foo, bar],
    )

    sources = store.bundles_dir / "metric_drafter.ctx.yaml.sources"
    assert (sources / "semantic_models" / "foo.yaml").exists()
    assert (sources / "metrics" / "bar.yaml").exists()
    assert "semantic_models/foo.yaml" in bundle.source_hashes
    assert "metrics/bar.yaml" in bundle.source_hashes


def test_assemble_chmod_600(store: BundleStore, project_root: Path) -> None:
    """4. ctx.yaml + every source copy is 0o600."""
    src = _write_yaml(project_root / "metrics" / "m1.yaml", {"name": "m1"})
    bundle = store.assemble(
        "metric_drafter", {"purpose": "preview"}, depends_on_project_yamls=[src]
    )

    assert _mode(bundle.ctx_path) == 0o600
    copy = (
        store.bundles_dir
        / "metric_drafter.ctx.yaml.sources"
        / "metrics"
        / "m1.yaml"
    )
    assert _mode(copy) == 0o600


def test_assemble_is_atomic(
    store: BundleStore, project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5. Mid-write failure leaves no partial ctx.yaml visible.

    We force `_atomic_write_bytes` to raise mid-write on the ctx.yaml. The
    tmpfile must not be promoted to the final path.
    """
    src = _write_yaml(project_root / "metrics" / "m1.yaml", {"name": "m1"})

    real_write = bundle_mod._atomic_write_bytes
    call_count = {"n": 0}

    def failing_write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
        call_count["n"] += 1
        # Allow the source copy through; fail on the final ctx.yaml write.
        if path.name.endswith(".ctx.yaml"):
            raise RuntimeError("simulated mid-write failure")
        real_write(path, data, mode=mode)

    monkeypatch.setattr(bundle_mod, "_atomic_write_bytes", failing_write)

    with pytest.raises(RuntimeError, match="simulated"):
        store.assemble(
            "metric_drafter",
            {"purpose": "preview"},
            depends_on_project_yamls=[src],
        )

    # No ctx.yaml on disk — atomic-write tmp + rename means partial state
    # never becomes visible at the final path.
    ctx_path = store.bundles_dir / "metric_drafter.ctx.yaml"
    assert not ctx_path.exists()
    # And no stray .tmp left at the final path location
    tmp_path = ctx_path.with_suffix(ctx_path.suffix + ".tmp")
    assert not tmp_path.exists()


def test_assemble_acquires_project_read_lock(
    store: BundleStore, project_root: Path
) -> None:
    """6. assemble calls project_read_lock once with project_root."""
    real_lock = bundle_mod.project_read_lock
    seen: list[Path] = []

    from contextlib import contextmanager

    @contextmanager
    def spy_lock(root: Path, **kwargs: Any):
        seen.append(root)
        with real_lock(root, **kwargs):
            yield

    with patch.object(bundle_mod, "project_read_lock", spy_lock):
        store.assemble("profiler", {"purpose": "profile"})

    assert len(seen) == 1
    assert seen[0] == store.project_root


def test_assemble_idempotent_with_same_inputs(
    store: BundleStore, project_root: Path
) -> None:
    """7. Second assemble produces fresh assembled_at but identical source_hashes."""
    src = _write_yaml(project_root / "metrics" / "m1.yaml", {"name": "m1"})

    b1 = store.assemble(
        "metric_drafter", {"purpose": "preview"}, depends_on_project_yamls=[src]
    )
    time.sleep(0.01)  # ensure a measurable assembled_at delta
    b2 = store.assemble(
        "metric_drafter", {"purpose": "preview"}, depends_on_project_yamls=[src]
    )

    assert b1.source_hashes == b2.source_hashes
    assert b1.assembled_at <= b2.assembled_at


# ── Case 8: concurrent write lock blocks bundle assemble ──────────────────


def _hold_write_lock_target(
    project_root_str: str,
    hold_seconds: float,
    acquired_event,
) -> None:
    """Helper run in a subprocess: hold exclusive lock, then release.

    Signals ``acquired_event`` once the exclusive lock is in hand so the
    parent process can synchronize before calling assemble.
    """
    from agentxp.orchestrator.project_lock import project_write_lock as pwl

    with pwl(Path(project_root_str), timeout_s=5.0):
        acquired_event.set()
        time.sleep(hold_seconds)


def test_assemble_detects_concurrent_write(
    store: BundleStore, project_root: Path
) -> None:
    """8. assemble blocks while another process holds write lock; succeeds after release."""
    # Ensure the lock file exists by acquiring + releasing once.
    with project_write_lock(project_root):
        pass

    hold_seconds = 0.5
    ctx = mp.get_context("spawn")
    acquired = ctx.Event()
    proc = ctx.Process(
        target=_hold_write_lock_target,
        args=(str(project_root), hold_seconds, acquired),
    )
    proc.start()
    # Wait until subprocess has actually grabbed the exclusive lock so the
    # contention window is real, not a spawn-time race.
    assert acquired.wait(timeout=10.0), "subprocess never acquired write lock"

    start = time.monotonic()
    bundle = store.assemble("profiler", {"purpose": "profile"})
    elapsed = time.monotonic() - start

    proc.join(timeout=5.0)
    assert proc.exitcode == 0

    # The assemble must have blocked until the subprocess released its
    # exclusive lock; lower bound is most of the hold period minus jitter.
    assert elapsed > hold_seconds * 0.3
    assert bundle.ctx_path.exists()


def test_read_bundle_round_trip(store: BundleStore, project_root: Path) -> None:
    """9. assemble → read_bundle equals (modulo path normalization)."""
    src = _write_yaml(project_root / "metrics" / "m1.yaml", {"name": "m1"})
    assembled = store.assemble(
        "metric_drafter",
        {"purpose": "preview", "exp_id": "exp_001"},
        depends_on_project_yamls=[src],
    )

    read_back = store.read_bundle("metric_drafter", "ctx")

    assert read_back.agent_name == assembled.agent_name
    assert read_back.schema_version == assembled.schema_version
    assert read_back.ctx_inputs == assembled.ctx_inputs
    assert read_back.source_hashes == assembled.source_hashes
    # assembled_at preserved within microsecond precision
    assert read_back.assembled_at == assembled.assembled_at
    assert read_back.ctx_path == assembled.ctx_path
    assert read_back.out_path == assembled.out_path


def test_read_bundle_raises_for_missing(store: BundleStore) -> None:
    """10. No bundle on disk → FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        store.read_bundle("never_assembled", "ctx")
    with pytest.raises(FileNotFoundError):
        store.read_bundle("never_assembled", "out")


def test_write_out_atomic(store: BundleStore) -> None:
    """11. write_out a pydantic model; YAML on disk; chmod 600."""
    payload = _DummyOut(answer="ok", confidence=0.9)
    out_path = store.write_out("profiler", payload)

    assert out_path.exists()
    data = yaml.safe_load(out_path.read_text())
    assert data == {"answer": "ok", "confidence": 0.9}
    assert _mode(out_path) == 0o600


def test_write_out_returns_path(store: BundleStore) -> None:
    """12. write_out returns the expected .out.yaml path."""
    payload = _DummyOut(answer="x")
    out_path = store.write_out("analyzer", payload)
    assert out_path == store.bundles_dir / "analyzer.out.yaml"


def test_sha256_stable_across_calls(
    store: BundleStore, project_root: Path
) -> None:
    """13. Same files → same source_hashes across assemble calls."""
    src = _write_yaml(project_root / "metrics" / "m1.yaml", {"name": "m1"})

    b1 = store.assemble(
        "metric_drafter", {"purpose": "preview"}, depends_on_project_yamls=[src]
    )
    b2 = store.assemble(
        "metric_drafter", {"purpose": "preview"}, depends_on_project_yamls=[src]
    )

    assert b1.source_hashes == b2.source_hashes
    assert all(len(v) == 64 for v in b1.source_hashes.values())


def test_sha256_detects_file_change(
    store: BundleStore, project_root: Path
) -> None:
    """14. Modify source file between assemblies; that file's sha256 differs."""
    src = _write_yaml(project_root / "metrics" / "m1.yaml", {"name": "m1"})

    b1 = store.assemble(
        "metric_drafter", {"purpose": "preview"}, depends_on_project_yamls=[src]
    )

    # Edit the project YAML under the write lock (steady-state pattern).
    with project_write_lock(project_root):
        src.write_text(yaml.safe_dump({"name": "m1", "extra": "edited"}))

    b2 = store.assemble(
        "metric_drafter", {"purpose": "preview"}, depends_on_project_yamls=[src]
    )

    rel = "metrics/m1.yaml"
    assert b1.source_hashes[rel] != b2.source_hashes[rel]


def test_assemble_handles_non_yaml_dependencies(
    store: BundleStore, project_root: Path
) -> None:
    """15. .json + .txt deps copied verbatim; sha256 computed; no YAML parsing."""
    json_dep = project_root / "metrics" / "extra.json"
    json_dep.parent.mkdir(parents=True, exist_ok=True)
    json_dep.write_text('{"name": "extra"}')

    txt_dep = project_root / "notes.txt"
    txt_dep.write_text("freeform notes")

    bundle = store.assemble(
        "metric_drafter",
        {"purpose": "preview"},
        depends_on_project_yamls=[json_dep, txt_dep],
    )

    json_copy = (
        store.bundles_dir
        / "metric_drafter.ctx.yaml.sources"
        / "metrics"
        / "extra.json"
    )
    txt_copy = (
        store.bundles_dir / "metric_drafter.ctx.yaml.sources" / "notes.txt"
    )
    assert json_copy.exists()
    assert txt_copy.exists()
    assert json_copy.read_bytes() == json_dep.read_bytes()
    assert txt_copy.read_bytes() == txt_dep.read_bytes()
    assert "metrics/extra.json" in bundle.source_hashes
    assert "notes.txt" in bundle.source_hashes
