"""Project-level YAML concurrency for OpenXP v0.1.

Wraps reads of project-level YAML (semantic_models/, fact_sources/, metrics/,
assignments/) in a shared lock; writes in an exclusive lock. Without this,
concurrent orchestrator runs corrupt shared YAML silently — an orchestrator
reading mid-write by `metric_drafter` or `semantic_modeler` gets partial state
and silent downstream errors (wrong fact source, missing metric, broken
bundle).

POSIX uses ``fcntl.flock`` (true shared/exclusive semantics).
Windows uses ``msvcrt.locking`` (byte-range; no shared/exclusive distinction,
so we approximate exclusive-everywhere with non-blocking retry — acceptable
for OpenXP's expected concurrency profile of <10 simultaneous orchestrators).

Lock file at ``{project}/.openxp/.project.lock``; gitignored, auto-created
on first lock with chmod 600 per §1.7.3 secrets policy. On acquisition
timeout, raises :class:`ProjectLockTimeout` so the orchestrator can surface
``gate.blocked(reason="project_locked")`` (the canonical
``EventMetadata.subtype`` per §1.8.5) rather than corrupting state silently.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10.9, §1.7.3,
§1.7.4, §1.8.5. Resolves NDS-2 / D16.
"""
from __future__ import annotations

import os
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


# ─────────────────────────────────────────────────────────────────────────
# Public surface
# ─────────────────────────────────────────────────────────────────────────


class ProjectLockTimeout(Exception):
    """Raised when project_lock acquisition exceeds ``timeout_s``.

    The orchestrator catches this and emits a ``gate.blocked`` event with
    ``reason="project_locked"`` per §10.9 / §1.8.5 so the user sees a clean
    error rather than a corrupted YAML downstream.
    """

    pass


# ─────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 0.05
_LOCK_DIR = ".openxp"
_LOCK_FILE = ".project.lock"
_LOCK_MODE = 0o600  # §1.7.3: secrets policy — owner read/write only


# ─────────────────────────────────────────────────────────────────────────
# Lock file helpers
# ─────────────────────────────────────────────────────────────────────────


def _lock_path(project_root: Path) -> Path:
    """Return the project lock-file path; create parent dirs and the file
    itself (with chmod 600) if missing.

    The file is touched on first lock; subsequent acquisitions reuse it.
    Idempotent.
    """
    lock_dir = project_root / _LOCK_DIR
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = lock_dir / _LOCK_FILE
    if not lock.exists():
        # Create exclusively with chmod 600 so a concurrent process doesn't
        # race us into creating it with default umask.
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_WRONLY | os.O_EXCL, _LOCK_MODE)
            os.close(fd)
        except FileExistsError:
            # Lost the race — another process created it; that's fine.
            pass
    # Defensive: re-apply chmod 600 in case the file pre-existed with
    # different permissions (e.g., upgraded from a pre-§10.9 install).
    # No-op on Windows where chmod semantics differ.
    if sys.platform != "win32":
        try:
            current_mode = stat.S_IMODE(lock.stat().st_mode)
            if current_mode != _LOCK_MODE:
                os.chmod(str(lock), _LOCK_MODE)
        except OSError:
            pass
    return lock


# ─────────────────────────────────────────────────────────────────────────
# Platform-specific lock primitives
# ─────────────────────────────────────────────────────────────────────────


if sys.platform == "win32":  # pragma: no cover - Windows-only branch
    import msvcrt

    def _acquire_shared_with_timeout(fd: int, timeout_s: float) -> None:
        """Windows shared-lock acquisition with timeout.

        ``msvcrt.locking`` is byte-range and does NOT distinguish shared
        from exclusive — every lock is effectively exclusive. We use
        non-blocking ``LK_NBLCK`` with retry-until-deadline. This is
        coarser than POSIX (concurrent readers serialize) but correct.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise ProjectLockTimeout(
                        f"Failed to acquire shared project lock within {timeout_s}s"
                    )
                time.sleep(_POLL_INTERVAL_S)

    def _acquire_exclusive_with_timeout(fd: int, timeout_s: float) -> None:
        """Windows exclusive-lock acquisition with timeout.

        Same primitive as shared on Windows (see above).
        """
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise ProjectLockTimeout(
                        f"Failed to acquire exclusive project lock within {timeout_s}s"
                    )
                time.sleep(_POLL_INTERVAL_S)

    def _release(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            # Best-effort release; closing the fd drops the lock anyway.
            pass

else:
    import fcntl

    def _acquire_shared_with_timeout(fd: int, timeout_s: float) -> None:
        """POSIX shared (LOCK_SH) acquisition with timeout via non-blocking
        retry. Multiple shared holders coexist.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ProjectLockTimeout(
                        f"Failed to acquire shared project lock within {timeout_s}s"
                    )
                time.sleep(_POLL_INTERVAL_S)

    def _acquire_exclusive_with_timeout(fd: int, timeout_s: float) -> None:
        """POSIX exclusive (LOCK_EX) acquisition with timeout via
        non-blocking retry. Excludes both other writers and any readers.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ProjectLockTimeout(
                        f"Failed to acquire exclusive project lock within {timeout_s}s"
                    )
                time.sleep(_POLL_INTERVAL_S)

    def _release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            # Best-effort release; closing the fd drops the lock anyway.
            pass


# ─────────────────────────────────────────────────────────────────────────
# Public context managers
# ─────────────────────────────────────────────────────────────────────────


@contextmanager
def project_read_lock(
    project_root: Path, *, timeout_s: float = _DEFAULT_TIMEOUT_S
) -> Iterator[None]:
    """Acquire a shared (read) lock on the project.

    Wrap every read of project-level YAML (semantic_models/, fact_sources/,
    metrics/, assignments/) in this context manager. Multiple readers may
    coexist; a concurrent exclusive write lock blocks until all readers
    release.

    Raises:
        ProjectLockTimeout: if the lock cannot be acquired within
            ``timeout_s`` seconds. The orchestrator should catch this and
            emit ``gate.blocked(reason="project_locked")`` per §10.9.
    """
    lock = _lock_path(project_root)
    fd = os.open(str(lock), os.O_RDWR)
    try:
        _acquire_shared_with_timeout(fd, timeout_s)
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)


@contextmanager
def project_write_lock(
    project_root: Path, *, timeout_s: float = _DEFAULT_TIMEOUT_S
) -> Iterator[None]:
    """Acquire an exclusive (write) lock on the project.

    Used by ``metric_drafter`` and ``semantic_modeler`` at stage commit,
    and by any ``OrchestratorStore.write_project_yaml()`` call. Excludes
    both other writers and any in-flight readers.

    The atomic-write helper (``tmp + os.replace``) still applies on top of
    this lock; the lock prevents readers from seeing partial state, and
    the atomic write prevents partial-file existence.

    Raises:
        ProjectLockTimeout: if the lock cannot be acquired within
            ``timeout_s`` seconds. The orchestrator should catch this and
            emit ``gate.blocked(reason="project_locked")`` per §10.9.
    """
    lock = _lock_path(project_root)
    fd = os.open(str(lock), os.O_RDWR)
    try:
        _acquire_exclusive_with_timeout(fd, timeout_s)
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)


__all__ = [
    "ProjectLockTimeout",
    "project_read_lock",
    "project_write_lock",
]
