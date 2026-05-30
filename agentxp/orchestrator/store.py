"""StateStore + OrchestratorStore — the v0.1 stage-commit chokepoint.

Wraps ``experiments/{exp_id}/state.yaml`` with an atomic, file-locked,
SIGINT-deferred writer and exposes ``OrchestratorStore`` — the single
chokepoint through which every stage commit, gate transition, and agent
dispatch flows. Implements §10 (Python API), §10.5 (nine failure-mode
wirings, with the SIGINT guard from §10.5.2, the disk pre-flight from
§10.5.3, the AuthExpired surface from §10.5.5, and the validate_chain
rollback from §10.5.8), and §10.7 (validate_chain contract).

State writes:
- ``state.yaml`` lands atomically via ``_atomic_write_bytes`` (chmod 600).
- The ``.state.lock`` sidecar holds a JSON ``LockMetadata`` envelope so
  ``agentxp resume`` can detect a stale-lock PID per §10.6.3 / §1.8.12.
- The SIGINT-deferred critical section (§10.5.2) defers Ctrl-C until the
  write + audit emission both land, then re-raises ``KeyboardInterrupt``
  at block exit.

All wall-clock timestamps are UTC per §1.7.2 (``_enforce_utc`` from
``agentxp.schemas.state``); error messages crossing into the audit log
are passed through ``redact_message`` per §1.7.3.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import yaml
from pydantic import BaseModel

from agentxp.audit.chain import PerfBudgetExceeded, validate_chain
from agentxp.audit.events import (
    GateBlockedPayload,
    GateOpenedPayload,
    GateResolvedPayload,
    StageCommittedPayload,
)
from agentxp.audit.redactor import redact_message
from agentxp.audit.storage import _atomic_write_bytes, append_event
from agentxp.orchestrator.bundle import BundleStore
from agentxp.orchestrator.conversation import ConversationStore
from agentxp.orchestrator.dispatch import (
    AuthExpiredError,
    DispatchRequest,
    DispatchResult,
    FailedAfterRetriesError,
    RetryPolicy,
    dispatch_agent as _dispatch_agent_impl,
)
from agentxp.schemas.state import (
    LockMetadata,
    PendingDecision,
    PendingDecisionKind,
    Stage,
    StageHistoryEntry,
    StateYaml,
    _enforce_utc,
)
from agentxp.storage.store import ExperimentStore


# ─────────────────────────────────────────────────────────────────────────
# Cross-platform whole-file lock primitives (matches conversation.py pattern)
# ─────────────────────────────────────────────────────────────────────────

try:
    import fcntl  # type: ignore[import]

    _HAS_FCNTL = True
except ImportError:  # pragma: no cover — Windows
    _HAS_FCNTL = False
    try:
        import msvcrt  # type: ignore[import]
    except ImportError:  # pragma: no cover — defensive
        msvcrt = None  # type: ignore[assignment]


# ─────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────

_FILE_MODE = 0o600  # §1.7.3 secrets policy
_REQUIRED_FREE_BYTES = 100 * 1024 * 1024  # §10.5.3 100MB pre-flight margin
_DEFAULT_LOCK_TIMEOUT_S = 30.0
_LOCK_POLL_S = 0.05


# ─────────────────────────────────────────────────────────────────────────
# Public errors
# ─────────────────────────────────────────────────────────────────────────


class InsufficientDiskSpace(Exception):
    """Raised by ``_check_disk_space`` when free bytes < required."""


class StaleLockError(Exception):
    """Raised when ``.state.lock`` is held by a dead PID (B4).

    The user runs ``agentxp unlock <exp_id>`` (W5) to break the lock; this
    error carries the offending PID and the lock's age so the dialog can
    surface both.
    """


class CommitRollback(Exception):
    """Raised internally by ``_commit_stage`` when ``validate_chain`` returns
    ``ok=False`` and the on-disk state.yaml had to be rolled back to its
    pre-attempt snapshot. Surfaces to the caller so resume can re-route
    through Case 8 (§10.6) or the §10.5.8 chain-validation-failed gate."""


class ArtifactLocked(Exception):
    """Raised by ``_write_artifact`` when a caller tries to silently overwrite
    an artifact that is already committed on disk (the G9 integrity wall).

    Every artifact reaches disk through ``_commit_stage``, so a file already
    present under ``experiments/{exp_id}/`` is a committed artifact. Rewriting
    it would let a locked rule (guardrail, success criterion, brief) be
    loosened after the fact. A legitimate post-lock change must go through the
    ``amendments/`` flow, which calls ``_write_artifact(..., amend=True)`` so
    the override is explicit, logged, and attributed — never silent."""


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _check_disk_space(
    exp_dir: Path, required_bytes: int = _REQUIRED_FREE_BYTES
) -> None:
    """Pre-flight disk-space check per §10.5.3.

    Raises ``InsufficientDiskSpace`` if the filesystem containing
    ``exp_dir`` has fewer than ``required_bytes`` free. Uses
    ``shutil.disk_usage`` which works on both POSIX and Windows.
    """
    probe = exp_dir if exp_dir.exists() else exp_dir.parent
    if not probe.exists():
        probe = probe.parent
    try:
        usage = shutil.disk_usage(str(probe))
    except OSError:
        # If we cannot probe (rare), let the caller proceed — the
        # downstream write will surface the real failure.
        return
    if usage.free < required_bytes:
        raise InsufficientDiskSpace(
            f"free disk space {usage.free} bytes on {probe} is below required "
            f"{required_bytes} bytes (§10.5.3)"
        )


# ─────────────────────────────────────────────────────────────────────────
# SIGINT deferral (§10.5.2)
# ─────────────────────────────────────────────────────────────────────────


@contextmanager
def _defer_sigint() -> Iterator[dict[str, bool]]:
    """Defer SIGINT until the block exits.

    Per §10.5.2: while inside the block, SIGINT just sets a flag; the
    original handler is restored on exit and ``KeyboardInterrupt`` is
    raised then if a signal was received. The yielded dict has key
    ``"sig"`` (bool) so callers can inspect whether an interrupt arrived
    during the section before the block actually exits.

    Falls back to a no-op outside the main thread, where
    ``signal.signal`` would raise.
    """
    received: dict[str, bool] = {"sig": False}

    def _handler(signum, frame):  # noqa: ARG001 — signal API
        received["sig"] = True

    installed = False
    prior = None
    try:
        try:
            prior = signal.signal(signal.SIGINT, _handler)
            installed = True
        except (ValueError, OSError):  # pragma: no cover — non-main thread
            prior = None
            installed = False
        yield received
    finally:
        if installed:
            try:
                signal.signal(signal.SIGINT, prior)
            except (ValueError, OSError):  # pragma: no cover
                pass
        if received["sig"]:
            raise KeyboardInterrupt()


# ─────────────────────────────────────────────────────────────────────────
# StateStore — owns experiments/{exp_id}/state.yaml
# ─────────────────────────────────────────────────────────────────────────


class StateStore:
    """Atomic, chmod-600 reader/writer for a single ``state.yaml``.

    Holds no internal cache; every ``read()`` re-parses from disk so the
    file is always the source of truth. Writes go through
    ``_atomic_write_bytes`` (tmp + os.replace) so a crashed mid-write
    never produces a half-file. A sibling ``.state.lock`` sidecar carries
    a JSON ``LockMetadata`` envelope (§6, §1.8.12) — that file is owned
    by ``OrchestratorStore`` and ignored by this class beyond exposing
    its canonical path.
    """

    def __init__(self, state_path: Path):
        self.path = Path(state_path)

    @property
    def lock_path(self) -> Path:
        """Canonical sidecar path: ``<state.yaml dir>/.state.lock``."""
        return self.path.parent / ".state.lock"

    def read(self) -> StateYaml:
        """Parse ``state.yaml`` from disk. Raises ``FileNotFoundError``
        if the file does not exist (the caller's job to bootstrap)."""
        if not self.path.exists():
            raise FileNotFoundError(
                f"state.yaml not found at {self.path}; bootstrap a StateYaml first"
            )
        raw = self.path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
        return StateYaml.model_validate(data)

    def write(self, state: StateYaml) -> None:
        """Atomically write ``state`` to disk with chmod 600.

        Caller is responsible for holding the orchestrator's file lock
        across the read-modify-write cycle; this method only guarantees
        that the *file* lands atomically (tmp + os.replace).
        """
        payload = state.model_dump(mode="json")
        text = yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
        _atomic_write_bytes(self.path, text.encode("utf-8"), mode=_FILE_MODE)


# ─────────────────────────────────────────────────────────────────────────
# OrchestratorStore
# ─────────────────────────────────────────────────────────────────────────


class OrchestratorStore:
    """The single stage-commit chokepoint for AgentXP v0.1.

    Wraps an ``ExperimentStore`` (project root + experiment directory
    layout) and owns ``state.yaml``, ``bundles/``, ``conversation.jsonl``,
    and ``log.jsonl`` for one experiment. All commits flow through
    :meth:`_commit_stage` which acquires ``.state.lock``, defers SIGINT
    (§10.5.2), pre-flights disk space (§10.5.3), writes artifacts +
    state.yaml atomically, validates the audit chain (§10.7), and emits
    ``stage.committed`` after every on-disk write has succeeded.

    Stage routing (the ``advance()`` entry point) is a v0.1 stub — the
    full DAG wiring lands in W6; this class ships the chokepoint and the
    failure-mode plumbing W2/W3/etc. will sit on top of.
    """

    LOCK_TIMEOUT_S: float = _DEFAULT_LOCK_TIMEOUT_S

    def __init__(
        self,
        project_root: Path,
        experiment_id: str,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.exp_id = experiment_id
        self.project_root = Path(project_root)
        self.store = ExperimentStore(self.project_root)

        # Ensure the experiment dir exists (the chokepoint owns this).
        exp_dir = self._exp_dir()
        exp_dir.mkdir(parents=True, exist_ok=True)

        self.state = StateStore(exp_dir / "state.yaml")
        self.bundles = BundleStore(exp_dir / "bundles", self.project_root)
        self.conversation = ConversationStore(exp_dir / "conversation.jsonl")
        self._lock_path = exp_dir / ".state.lock"

        # Replay determinism (G3 / W2.1): the audit log must be reproducible.
        # ``clock`` is the injectable now()-source for every event timestamp
        # that lands in log.jsonl (and the paired state.yaml writes). Defaults
        # to wall-clock UTC; a replay driver supplies the recorded timestamps
        # so re-emitting a log reproduces it byte-for-byte (same chain hash).
        # Operational timestamps (the .state.lock envelope) stay wall-clock.
        self._clock: Callable[[], datetime] = clock or _utcnow

        # Linear parent-linkage for Invariant 1 + deterministic action ids:
        # each emitted event's ``action_id`` is a per-experiment monotonic
        # sequence (``{exp_id}#{seq:06d}``) and its ``parent_action_id`` is
        # the prior event's id. Both are lazily recovered from the log on
        # first use (count of rows → next seq; last id → parent) so a resumed
        # session continues the same chain instead of starting a second root.
        self._last_action_id: Optional[str] = None
        self._seq: int = 0
        self._chain_tail_loaded = False

    # ── path helpers ────────────────────────────────────────────────────

    def _exp_dir(self) -> Path:
        return self.project_root / "experiments" / self.exp_id

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    # ── lock primitives ─────────────────────────────────────────────────

    def _read_lock_metadata(self) -> Optional[LockMetadata]:
        """Read the JSON envelope sitting inside ``.state.lock``; return
        ``None`` if the file is missing or the envelope is empty/unreadable.
        """
        try:
            raw = self._lock_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
        try:
            return LockMetadata.model_validate(data)
        except Exception:  # noqa: BLE001 — malformed envelope is not fatal
            return None

    def _write_lock_metadata(self) -> None:
        """Stamp the lock sidecar with the current PID + UTC timestamp.

        Called immediately after the OS-level flock is acquired so a
        concurrent stale-lock checker can correlate the live holder.
        """
        meta = LockMetadata(
            pid=os.getpid(),
            started_at=_utcnow(),
            hostname=None,
        )
        payload = json.dumps(meta.model_dump(mode="json"), separators=(",", ":")) + "\n"
        try:
            _atomic_write_bytes(self._lock_path, payload.encode("utf-8"), mode=_FILE_MODE)
        except OSError:
            # Non-fatal — the OS flock is the real lock; the envelope is
            # advisory metadata for stale-lock detection.
            pass

    def _pid_is_alive(self, pid: int) -> bool:
        """POSIX: ``os.kill(pid, 0)`` raises ProcessLookupError if dead.

        Windows / non-POSIX: best-effort — return True so we never
        falsely declare a lock stale on a platform we cannot probe.
        """
        if sys.platform == "win32":  # pragma: no cover — Windows path
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
            # PID exists but owned by another user — treat as alive.
            return True
        except OSError:
            return True

    @contextmanager
    def _file_lock(self, timeout_s: Optional[float] = None) -> Iterator[None]:
        """Acquire an exclusive whole-file lock on ``.state.lock``.

        Implementation parity with ``project_lock.py``: non-blocking
        retry against ``fcntl.flock(LOCK_EX|LOCK_NB)`` (POSIX) or
        ``msvcrt.locking`` (Windows) until ``timeout_s`` elapses. On the
        first contention, run the §10.6.3 stale-lock probe: if the
        envelope's PID is dead, surface ``StaleLockError`` so the caller
        can route to ``agentxp unlock``. The sidecar JSON envelope is
        written right after acquisition.
        """
        timeout = self.LOCK_TIMEOUT_S if timeout_s is None else timeout_s
        self._exp_dir().mkdir(parents=True, exist_ok=True)

        # Ensure the lock file exists with chmod 600 from creation.
        if not self._lock_path.exists():
            try:
                fd_init = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_WRONLY | os.O_EXCL,
                    _FILE_MODE,
                )
                os.close(fd_init)
            except FileExistsError:
                pass

        fd = os.open(str(self._lock_path), os.O_RDWR)
        deadline = time.monotonic() + timeout
        stale_checked = False
        try:
            while True:
                acquired = False
                try:
                    if _HAS_FCNTL:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    elif msvcrt is not None:  # pragma: no cover — Windows
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    acquired = True
                except (BlockingIOError, OSError):
                    if not stale_checked:
                        meta = self._read_lock_metadata()
                        if meta is not None and not self._pid_is_alive(meta.pid):
                            age_s = (_utcnow() - meta.started_at).total_seconds()
                            raise StaleLockError(
                                f".state.lock at {self._lock_path} held by dead "
                                f"PID {meta.pid} (age {age_s:.1f}s); "
                                "run 'agentxp unlock <exp_id>' to break"
                            )
                        stale_checked = True
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"failed to acquire {self._lock_path} within {timeout}s"
                        )
                    time.sleep(_LOCK_POLL_S)

                if acquired:
                    break

            # Stamp the envelope with our PID for the next contender's
            # stale-lock probe.
            self._write_lock_metadata()
            try:
                yield
            finally:
                if _HAS_FCNTL:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                elif msvcrt is not None:  # pragma: no cover — Windows
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    # ── audit emission ──────────────────────────────────────────────────

    def _now(self) -> datetime:
        """Injectable now()-source for every audit timestamp (W2.1).

        Defaults to wall-clock UTC; a replay driver injects a clock that
        returns the recorded timestamps so re-emitting a log reproduces it.
        """
        return self._clock()

    def _next_action_id(self) -> str:
        """Return the next deterministic per-experiment action id (W2.1).

        Format ``{exp_id}#{seq:06d}`` where ``seq`` is the count of events
        already in log.jsonl. Deterministic given event order, so a replay
        on the same seed reproduces the same ids — and the chain hash.
        """
        self._ensure_chain_tail_loaded()
        aid = f"{self.exp_id}#{self._seq:06d}"
        self._seq += 1
        return aid

    def _emit(self, event: BaseModel) -> None:
        """Append an audit event under the experiment dir.

        Single seam for every emission. Stamps Invariant-1 parent linkage:
        when a caller leaves ``parent_action_id`` unset, this fills it with
        the prior event's ``action_id`` so log.jsonl forms one cycle-free
        chain (the very first event stays root with ``parent_action_id=None``).
        A caller that sets ``parent_action_id`` explicitly (e.g. agent
        dispatch fan-out) is left untouched.
        """
        self._ensure_chain_tail_loaded()

        if (
            hasattr(event, "parent_action_id")
            and getattr(event, "parent_action_id") is None
            and self._last_action_id is not None
        ):
            event.parent_action_id = self._last_action_id

        append_event(self._exp_dir(), event)

        new_id = getattr(event, "action_id", None)
        if isinstance(new_id, str):
            self._last_action_id = new_id

    def _ensure_chain_tail_loaded(self) -> None:
        """Lazily recover the chain tail from log.jsonl in a single scan.

        Sets ``_last_action_id`` (the last event's id → parent linkage) and
        ``_seq`` (the row count → next deterministic action id). Lets a
        resumed session (new store instance over an existing experiment)
        continue the same chain instead of starting a second root — which
        Invariant 1 would otherwise flag.
        """
        if self._chain_tail_loaded:
            return
        log_path = self._exp_dir() / "log.jsonl"
        last_id: Optional[str] = None
        count = 0
        if log_path.exists():
            with log_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    count += 1
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    aid = row.get("action_id") if isinstance(row, dict) else None
                    if isinstance(aid, str):
                        last_id = aid
        self._last_action_id = last_id
        self._seq = count
        self._chain_tail_loaded = True

    # ── high-level entry: advance() ─────────────────────────────────────

    def advance(self, user_input: Optional[str] = None) -> None:
        """High-level stage advance (W6 wires the real DAG routing).

        v0.1 stub: read state.yaml so callers get a fast feedback signal
        if the experiment directory is corrupt, then return. The full
        stage-routing table lands when the per-agent stage handlers ship
        in W2/W3/W4.
        """
        # Touch the state so a missing/corrupt file surfaces early.
        if self.state.path.exists():
            self.state.read()
        return None

    # ── resume: reconstruct state from the log (J3.3 / W4.2) ─────────────

    def reconstruct_from_log(self) -> Optional[Stage]:
        """Roll ``state.yaml`` forward to match the append-only log (J3.3).

        Closes the W2.2 crash window. ``_commit_stage`` emits
        ``stage.committed`` to ``log.jsonl`` *before* writing ``state.yaml``
        (append-then-advance, G11), so a crash between the two leaves the log
        ahead of state: the durable log records a commit the state file never
        caught up to. The log is the source of truth for resume, so this
        rebuilds the stage fields of ``state.yaml`` from the ordered
        ``stage.committed`` events in the log:

          - ``current_stage`` / ``last_committed_stage`` ← the last committed
            stage in the log;
          - ``stage_history`` ← one entry per ``stage.committed`` event, in
            log order, stamped with each event's recorded timestamp.

        Every other state field (intent, hypothesis, pending_decision, …) is
        preserved. If ``state.yaml`` is absent (crash before the very first
        state write) it is bootstrapped from the log. Idempotent: returns
        ``None`` when state already matches the log (the common, no-crash
        case); otherwise returns the :class:`Stage` it rolled forward to.
        Holds ``.state.lock`` across the read-modify-write like every other
        state mutation.
        """
        committed: list[tuple[Stage, datetime]] = []
        log_path = self._exp_dir() / "log.jsonl"
        if log_path.exists():
            with log_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    if row.get("event_name") != "stage.committed":
                        continue
                    stage_val = row.get("stage")
                    ts_val = row.get("timestamp")
                    if not isinstance(stage_val, str) or not isinstance(ts_val, str):
                        continue
                    committed.append((Stage(stage_val), datetime.fromisoformat(ts_val)))

        # No committed stage in the log → nothing the log can roll forward to.
        if not committed:
            return None

        target_stage = committed[-1][0]
        new_history = [
            StageHistoryEntry(stage=s, committed_at=ts) for s, ts in committed
        ]

        def _key(history: list[StageHistoryEntry]) -> list[tuple[str, str]]:
            return [(e.stage.value, e.committed_at.isoformat()) for e in history]

        with self._file_lock():
            with _defer_sigint():
                if self.state.path.exists():
                    state = self.state.read()
                else:
                    state = StateYaml(
                        experiment_id=self.exp_id,
                        current_stage=target_stage,
                    )

                already_synced = (
                    self.state.path.exists()
                    and state.current_stage == target_stage
                    and state.last_committed_stage == target_stage
                    and _key(state.stage_history) == _key(new_history)
                )
                if already_synced:
                    return None

                state.current_stage = target_stage
                state.last_committed_stage = target_stage
                state.stage_history = new_history
                self.state.write(state)
                return target_stage

    # ── the chokepoint: _commit_stage ───────────────────────────────────

    def _commit_stage(
        self,
        stage: Stage,
        artifacts: Optional[dict[str, BaseModel]] = None,
        dag_transition: Optional[str] = None,
        subtype: Optional[str] = None,
    ) -> None:
        """Atomically commit a stage transition.

        Per §10.5.2: holds ``.state.lock`` for the entire critical
        section, defers SIGINT, writes every artifact through
        ``_atomic_write_bytes``, validates the audit chain (§10.7), then
        commits in append-then-advance order: emit exactly one
        ``stage.committed`` event to the append-only log *before* writing
        the advanced ``state.yaml`` to disk.

        Append-then-advance ordering (G11): the log is the source of truth
        for resume. By emitting ``stage.committed`` before advancing
        ``state.yaml`` we guarantee a crash can only leave the log ahead of
        (or equal to) state — never state ahead of the log. A crash between
        the two leaves a committed event whose state advance is replayable
        from the log; the reverse (state advanced, no log record) would be
        an unverifiable chain and is now impossible.

        Rollback (§10.5.8): if ``validate_chain`` returns ``ok=False`` or
        raises ``PerfBudgetExceeded``, emit ``gate.blocked`` with
        ``reason="chain_validation_failed"`` and raise ``CommitRollback``.
        Validation runs before either the commit event or the state
        advance, so on failure no on-disk state has moved — there is
        nothing to roll back.

        Disk pre-flight (§10.5.3): when free bytes < 100MB, emit
        ``gate.blocked(reason="disk_full")`` and return without mutating
        any on-disk state.
        """
        artifacts = artifacts or {}
        exp_dir = self._exp_dir()

        # Pre-flight outside the lock so a disk-full state surfaces fast
        # and we never even create the lock file on a doomed write.
        try:
            _check_disk_space(exp_dir)
        except InsufficientDiskSpace as exc:
            self._emit_gate_blocked(
                reason="disk_full",
                subtype="disk_full",
                metadata={
                    "required_bytes": _REQUIRED_FREE_BYTES,
                    "message": redact_message(exc),
                },
            )
            return

        with self._file_lock():
            with _defer_sigint():
                # 1. Write artifacts atomically (per the §10.5.2 ordering:
                #    experiment.yaml → decisions/*.yaml → state.yaml).
                for filename, payload in artifacts.items():
                    self._write_artifact(filename, payload)

                # 2. Read current state (or bootstrap a minimal one).
                if self.state.path.exists():
                    current = self.state.read()
                else:
                    current = StateYaml(
                        experiment_id=self.exp_id,
                        current_stage=stage,
                    )

                # 3. Mutate in memory only: advance stage + append history.
                #    state.yaml is NOT written to disk until step 6, after
                #    the commit event lands (append-then-advance, G11).
                committed_at = self._now()
                current.current_stage = stage
                current.last_committed_stage = stage
                current.stage_history.append(
                    StageHistoryEntry(stage=stage, committed_at=committed_at)
                )

                # 4. validate_chain (§10.7). Runs before any on-disk commit
                #    or state advance, so a failure leaves disk untouched —
                #    no rollback is needed, only a gate.blocked breadcrumb.
                try:
                    result = validate_chain(
                        self.exp_id,
                        _root=self.project_root / "experiments",
                    )
                except PerfBudgetExceeded as exc:
                    self._emit_gate_blocked(
                        reason="chain_validation_failed",
                        subtype="chain_validation_perf",
                        metadata={"message": redact_message(exc)},
                    )
                    raise CommitRollback(
                        f"validate_chain hit perf hard cap: {exc}"
                    ) from exc

                if not result.ok:
                    self._emit_gate_blocked(
                        reason="chain_validation_failed",
                        subtype="chain_validation_failed",
                        metadata={
                            "ms": result.ms,
                            "violations": [v.model_dump(mode="json") for v in result.violations],
                        },
                    )
                    raise CommitRollback(
                        f"validate_chain returned ok=False: "
                        f"{[v.description for v in result.violations]}"
                    )

                # 5. Emit stage.committed exactly once — the durable commit
                #    record lands in the append-only log BEFORE state.yaml
                #    advances on disk (append-then-advance, G11).
                metadata: dict[str, Any] = {}
                if subtype:
                    metadata["subtype"] = subtype
                if dag_transition:
                    metadata["dag_transition"] = dag_transition
                if result.perf_warning:
                    # Soft-cap drift — the stage still commits; record
                    # the warning per §10.7.3.
                    metadata.setdefault("subtype", "chain_validation_slow")
                    metadata["ms"] = result.ms

                self._emit(
                    StageCommittedPayload(
                        timestamp=self._now(),
                        action_id=self._next_action_id(),
                        parent_action_id=None,
                        actor_kind="orchestrator",
                        actor_name="_commit_stage",
                        experiment_id=self.exp_id,
                        stage=stage,
                        bundle_hash=None,
                        metadata=metadata,
                    )
                )

                # 6. Advance state.yaml on disk — last, after the commit
                #    event is durable. A crash here leaves the log ahead of
                #    state (replayable), never state ahead of the log.
                self.state.write(current)

    # ── artifact helpers ────────────────────────────────────────────────

    def _write_artifact(
        self, filename: str, payload: BaseModel, *, amend: bool = False
    ) -> Path:
        """Atomically write one artifact under the experiment dir.

        ``filename`` is interpreted as a path relative to
        ``experiments/{exp_id}/``. Pydantic models are serialised through
        YAML (sorted=False to preserve declaration order). The file lands
        chmod 600 per §1.7.3.

        Integrity wall (§10.7 / G9): refuses to silently overwrite an
        artifact that already exists on disk. Every artifact reaches disk
        through ``_commit_stage``, so a file already present is a committed
        artifact; rewriting it would loosen a locked rule after the fact.
        A caller may force the overwrite with ``amend=True`` so the override
        is explicit, never silent. Raises ``ArtifactLocked`` otherwise.

        v0.1 boundary (G14): ``amend=True`` is the *write seam* for a future
        chain-aware amendment flow, but that flow is NOT wired into this store
        in v0.1. The ``amendments/`` package (``record_amendment``) operates on
        the legacy ``ExperimentStore`` — a different root (``~/.agentxp``) with
        a non-chained ``log.jsonl`` — so routing it here would either write to
        the wrong directory or append an unchained event that breaks Invariant
        1 of ``validate_chain``. Until an amendment event is made chain-aware
        on this store, the supported way to change a locked pre-registration is
        a new experiment. See ``docs/USER_JOURNEYS.md`` gap G14.
        """
        exp_dir = self._exp_dir()
        target = (exp_dir / filename).resolve()
        # Defensive: never let a caller escape the experiment dir.
        try:
            target.relative_to(exp_dir.resolve())
        except ValueError as exc:
            raise ValueError(
                f"artifact path {filename!r} escapes experiment dir {exp_dir}"
            ) from exc
        if target.exists() and not amend:
            raise ArtifactLocked(
                f"artifact {filename!r} is already committed for experiment "
                f"{self.exp_id!r}; refusing to overwrite a locked artifact. "
                f"v0.1 does not auto-apply post-commit amendments through this "
                f"store (G14); to change a locked pre-registration, start a new "
                f"experiment. The amend=True override is reserved for the "
                f"future chain-aware amendment flow."
            )
        data = payload.model_dump(mode="json")
        text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
        _atomic_write_bytes(target, text.encode("utf-8"), mode=_FILE_MODE)
        return target

    def _emit_gate_blocked(
        self,
        reason: str,
        subtype: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Emit a ``gate.blocked`` event with the canonical metadata shape.

        ``reason`` lands on the top-level field; ``subtype`` is mirrored
        into ``metadata.subtype`` per §10.5.3 (the dual recording rule
        F.COHERENCE.02 binds).
        """
        meta = dict(metadata or {})
        if subtype:
            meta["subtype"] = subtype
        self._emit(
            GateBlockedPayload(
                timestamp=self._now(),
                action_id=self._next_action_id(),
                parent_action_id=None,
                actor_kind="orchestrator",
                actor_name="_commit_stage",
                experiment_id=self.exp_id,
                reason=reason,
                metadata=meta,
            )
        )

    # ── dispatch_agent ──────────────────────────────────────────────────

    def dispatch_agent(
        self,
        agent_name: str,
        bundle: Any,
        retry_policy: Optional[RetryPolicy] = None,
        out_schema: Optional[type[BaseModel]] = None,
        parent_action_id: Optional[str] = None,
    ) -> DispatchResult:
        """Dispatch an agent through ``orchestrator.dispatch.dispatch_agent``.

        Surfaces both ``AuthExpiredError`` (per §10.5.5 — caller opens
        the re-auth gate) and ``FailedAfterRetriesError`` (per §10.5.1 —
        caller opens the r/a/s dialog). The bundle argument accepts
        either an ``AgentBundle`` (the in-memory view returned by
        ``BundleStore.assemble``) or a plain ctx-dict (test harness
        convenience).
        """
        policy = retry_policy or RetryPolicy()

        if hasattr(bundle, "ctx_inputs"):
            ctx_bundle = dict(getattr(bundle, "ctx_inputs"))
        elif isinstance(bundle, dict):
            ctx_bundle = bundle
        else:
            raise TypeError(
                f"dispatch_agent: bundle must be an AgentBundle or dict; "
                f"got {type(bundle).__name__}"
            )

        if out_schema is None:
            raise ValueError(
                "dispatch_agent: out_schema is required so dispatch can "
                "validate the LLM response"
            )

        req = DispatchRequest(
            agent_name=agent_name,
            experiment_id=self.exp_id,
            project_root=self.project_root,
            ctx_bundle=ctx_bundle,
            out_schema=out_schema,
            retry_policy=policy,
            parent_action_id=parent_action_id,
        )
        return _dispatch_agent_impl(req)

    # ── dispatch_sql (W_sql) ────────────────────────────────────────────

    def dispatch_sql(self, sql_intent: Any, context: Any) -> Any:
        """SYNC ONLY in v0.1 — full impl ships in W_sql.

        v0.1 stub: raise ``NotImplementedError`` with a clear hint so
        early callers fail loudly rather than silently no-op.
        """
        raise NotImplementedError(
            "dispatch_sql lands in W_sql; v0.1 store ships the chokepoint only"
        )

    # ── gate management: set_pending / resolve_decision / override ──────

    def set_pending(
        self,
        kind: PendingDecisionKind,
        options: list[str],
        prompt: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Open a user-facing gate.

        Writes ``state.yaml.pending_decision`` (atomic, under
        ``.state.lock``) and emits the matching ``gate.opened`` event.
        Per §10.5: the emit happens AFTER the on-disk write succeeds so
        a crash mid-gate leaves the orchestrator in the gate-open state.
        """
        opened_at = self._now()
        with self._file_lock():
            current = self.state.read() if self.state.path.exists() else StateYaml(
                experiment_id=self.exp_id,
                current_stage=Stage.DATA_LOADED,
            )
            current.pending_decision = PendingDecision(
                kind=kind,
                opened_at=opened_at,
                prompt_to_user=prompt,
                options=list(options),
                metadata=dict(metadata or {}),
            )
            self.state.write(current)
            self._emit(
                GateOpenedPayload(
                    timestamp=opened_at,
                    action_id=self._next_action_id(),
                    parent_action_id=None,
                    actor_kind="orchestrator",
                    actor_name="set_pending",
                    experiment_id=self.exp_id,
                    kind=kind.value,
                    options=list(options),
                    prompt_to_user=prompt,
                    metadata=dict(metadata or {}),
                )
            )

    def resolve_decision(
        self,
        choice: str,
        rationale: Optional[str] = None,
        reason_code: Optional[str] = None,
    ) -> None:
        """Resolve the currently-open pending decision.

        Clears ``state.yaml.pending_decision`` and emits
        ``gate.resolved`` with the user's choice + (optional) rationale +
        (optional) reason_code. Raises ``ValueError`` if no gate is open.
        """
        with self._file_lock():
            if not self.state.path.exists():
                raise ValueError("no state.yaml exists; cannot resolve")
            current = self.state.read()
            pending = current.pending_decision
            if pending is None:
                raise ValueError("no pending_decision to resolve")

            kind = pending.kind
            metadata: dict[str, Any] = {}
            if reason_code:
                metadata["reason_code"] = reason_code

            current.pending_decision = None
            self.state.write(current)

            self._emit(
                GateResolvedPayload(
                    timestamp=self._now(),
                    action_id=self._next_action_id(),
                    parent_action_id=None,
                    actor_kind="user",
                    actor_name="resolve_decision",
                    experiment_id=self.exp_id,
                    kind=kind.value,
                    choice=choice,
                    rationale=rationale,
                    metadata=metadata,
                )
            )

    def override(self, reason: str, reason_code: str) -> None:
        """Resolve the currently-open pending decision with override
        semantics — the user accepted the gate despite the system's
        recommendation against it. The ``reason_code`` (e.g. one of
        ``SrmOverrideReasonCode``) lands on both the rationale field and
        the metadata ``subtype`` so audit replay can correlate.
        """
        with self._file_lock():
            if not self.state.path.exists():
                raise ValueError("no state.yaml exists; cannot override")
            current = self.state.read()
            pending = current.pending_decision
            if pending is None:
                raise ValueError("no pending_decision to override")

            kind = pending.kind
            current.pending_decision = None
            self.state.write(current)

            self._emit(
                GateResolvedPayload(
                    timestamp=self._now(),
                    action_id=self._next_action_id(),
                    parent_action_id=None,
                    actor_kind="user",
                    actor_name="override",
                    experiment_id=self.exp_id,
                    kind=kind.value,
                    choice="override",
                    rationale=reason,
                    metadata={"subtype": reason_code, "reason_code": reason_code},
                )
            )


__all__ = [
    "ArtifactLocked",
    "CommitRollback",
    "InsufficientDiskSpace",
    "OrchestratorStore",
    "StaleLockError",
    "StateStore",
    "_check_disk_space",
    "_defer_sigint",
]
