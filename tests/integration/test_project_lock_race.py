"""Smoke test for ``openxp.orchestrator.project_lock``.

Fires concurrent writes against the same project YAML (via multiprocessing
to get real OS-level lock semantics — threading would not exercise the
``fcntl.flock`` per-file-description path correctly) and asserts no
corruption.

Covers:
  1. Shared (read) locks coexist — multiple readers ok.
  2. Exclusive (write) locks serialize concurrent writers; no exitcode != 0.
  3. Concurrent YAML writes produce a single complete document at the end
     (one of the writers wins; no interleaved bytes).
  4. ``ProjectLockTimeout`` is raised when contention exceeds ``timeout_s``.
  5. Lock file is chmod 600 per §1.7.3.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10.9.
"""
from __future__ import annotations

import multiprocessing
import os
import stat
import sys
import time
from pathlib import Path

import pytest
import yaml

from openxp.orchestrator.project_lock import (
    ProjectLockTimeout,
    project_read_lock,
    project_write_lock,
)


# ─────────────────────────────────────────────────────────────────────────
# Multiprocessing helpers (must be module-level for picklability on macOS
# where the default "spawn" start method requires importable targets).
# ─────────────────────────────────────────────────────────────────────────


def _writer_worker(project_root: str, content: str, hold_seconds: float = 0.1) -> None:
    """Acquire write lock, write the file, hold (to force contention), release.

    Mirrors what ``metric_drafter`` does at stage commit.
    """
    project_root_p = Path(project_root)
    target = project_root_p / "metrics" / "test_metric.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    with project_write_lock(project_root_p, timeout_s=10.0):
        target.write_text(content)
        time.sleep(hold_seconds)


def _long_holder(
    project_root: str, ready_sentinel: str, hold_seconds: float = 3.0
) -> None:
    """Hold an exclusive lock for ``hold_seconds`` so a sibling can time out.

    Touches ``ready_sentinel`` *after* the lock is acquired so the parent
    test can synchronize on it instead of guessing a sleep duration
    (subprocess startup is slow under ``spawn`` on macOS).
    """
    with project_write_lock(Path(project_root), timeout_s=5.0):
        Path(ready_sentinel).touch()
        time.sleep(hold_seconds)


# ─────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────


def test_shared_lock_allows_concurrent_reads(tmp_path: Path) -> None:
    """Two shared (read) locks coexist in the same process.

    On POSIX, each ``os.open`` returns a distinct file description, so
    ``fcntl.flock`` treats them as independent holders — both LOCK_SH
    acquisitions succeed without blocking.
    """
    with project_read_lock(tmp_path, timeout_s=2.0):
        with project_read_lock(tmp_path, timeout_s=2.0):
            pass  # both held simultaneously — must not block or time out


def test_exclusive_lock_excludes_others(tmp_path: Path) -> None:
    """Concurrent exclusive writers all complete without error; the lock
    serializes them rather than letting them collide.
    """
    procs = []
    for content in ("v1", "v2", "v3"):
        p = multiprocessing.Process(
            target=_writer_worker, args=(str(tmp_path), content, 0.2)
        )
        procs.append(p)
        p.start()
    for p in procs:
        p.join(timeout=15)
        assert p.exitcode == 0, f"Worker failed with exitcode {p.exitcode}"

    # Final content is exactly one of v1/v2/v3 — not corrupted, not interleaved.
    target = tmp_path / "metrics" / "test_metric.yaml"
    assert target.exists(), "Workers should have created the target file"
    final = target.read_text()
    assert final in ("v1", "v2", "v3"), (
        f"Expected one clean writer to win; got corrupted content: {final!r}"
    )


def test_write_lock_yaml_no_corruption(tmp_path: Path) -> None:
    """Concurrent writes of full YAML documents yield one valid YAML at the
    end — never interleaved bytes from two writers.
    """
    payload_a = yaml.safe_dump({"name": "metric_a", "value": 1})
    payload_b = yaml.safe_dump({"name": "metric_b", "value": 2})

    procs = [
        multiprocessing.Process(
            target=_writer_worker, args=(str(tmp_path), payload_a, 0.1)
        ),
        multiprocessing.Process(
            target=_writer_worker, args=(str(tmp_path), payload_b, 0.1)
        ),
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=15)
        assert p.exitcode == 0, f"Worker failed with exitcode {p.exitcode}"

    target = tmp_path / "metrics" / "test_metric.yaml"
    parsed = yaml.safe_load(target.read_text())
    assert isinstance(parsed, dict), f"Got non-dict YAML (corrupted?): {parsed!r}"
    assert parsed["name"] in ("metric_a", "metric_b")
    # Cross-check value matches the name we read — confirms no field-level interleave.
    assert (parsed["name"], parsed["value"]) in (("metric_a", 1), ("metric_b", 2))


def test_timeout_raises_project_lock_timeout(tmp_path: Path) -> None:
    """If a sibling holds the exclusive lock longer than ``timeout_s``,
    the contender raises :class:`ProjectLockTimeout` rather than blocking
    forever or returning corrupted state.
    """
    ready_sentinel = tmp_path / ".holder_ready"
    holder = multiprocessing.Process(
        target=_long_holder, args=(str(tmp_path), str(ready_sentinel), 3.0)
    )
    holder.start()
    try:
        # Synchronize on the sentinel so we know the holder *actually* holds
        # the lock before we try to acquire (spawn-mode subprocess startup
        # on macOS can take >0.3s, making naive sleeps flaky).
        deadline = time.monotonic() + 5.0
        while not ready_sentinel.exists():
            if time.monotonic() >= deadline:
                pytest.fail("Holder process never acquired the lock")
            time.sleep(0.02)

        with pytest.raises(ProjectLockTimeout):
            with project_write_lock(tmp_path, timeout_s=0.5):
                pass
    finally:
        holder.join(timeout=10)
        assert holder.exitcode == 0, (
            f"Holder process should complete cleanly; exitcode={holder.exitcode}"
        )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="chmod 600 semantics differ on Windows; §1.7.3 targets POSIX",
)
def test_lock_file_is_chmod_600(tmp_path: Path) -> None:
    """Lock file is created with chmod 600 per §1.7.3 secrets policy."""
    with project_read_lock(tmp_path, timeout_s=2.0):
        pass

    lock = tmp_path / ".openxp" / ".project.lock"
    assert lock.exists(), "Lock file must be auto-created on first acquisition"
    mode = stat.S_IMODE(lock.stat().st_mode)
    assert mode == 0o600, (
        f"Lock file mode is {oct(mode)}, expected 0o600 (§1.7.3 secrets policy)"
    )
    # Sanity: file should also be inside the .openxp/ directory.
    assert lock.parent.name == ".openxp"
    assert os.access(str(lock), os.R_OK | os.W_OK), "Owner must retain rw access"
