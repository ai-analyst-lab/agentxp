"""Audit storage primitives for AgentXP v0.1.

Writes the 9-field action receipt to log.jsonl. Append-only, atomic per-line writes,
chmod 600 on file creation (per §1.7.3). Also exposes a similar writer for
conversation.jsonl that downstream code uses.

POSIX semantics primary:
  - `O_APPEND` guarantees concurrent writers do not interleave when each write
    is <= PIPE_BUF (4096 bytes on Linux/macOS). We cap line size at 4096 bytes
    and raise ValueError above that to preserve the atomicity guarantee.
  - File is created with chmod 600 via `os.open(... O_EXCL, mode=0o600)` so
    no window exists where the file is world-readable.
  - Every append re-verifies mode == 0o600 and raises PermissionError if drift
    is detected (§1.7.3 / B9).

Windows fallback: chmod semantics are weaker on Windows; we still call
`os.chmod` but tolerate failures. (The pre-flight disk-space check lives in
``orchestrator.store._check_disk_space``, which raises ``InsufficientDiskSpace``;
this module no longer carries a parallel copy.)

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §1.7.3, §10.5.6, §9.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from agentxp.audit.events import EventPayload


class _AtomicJsonlWriter:
    """Append a single JSON line to a file atomically.

    Atomic only at the line level: we open with O_APPEND and write+fsync the
    full line in one syscall. Concurrent writers on POSIX will not interleave
    line content (kernel guarantees atomic write up to PIPE_BUF=4096 bytes;
    larger lines may interleave, so we cap line size).
    """

    MAX_LINE_BYTES = 4096  # PIPE_BUF on Linux/macOS

    def __init__(self, path: Path, *, create_mode: int = 0o600):
        self.path = path
        self.create_mode = create_mode
        self._ensure_parent_and_perms()

    def _ensure_parent_and_perms(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            # Create with chmod 600 from the start (no world-readable window).
            # O_EXCL races a concurrent appender; if a peer wins the create we
            # treat the file as already-present and fall through to the shared
            # mode check (the appends themselves stay atomic via O_APPEND).
            try:
                fd = os.open(
                    str(self.path),
                    os.O_CREAT | os.O_WRONLY | os.O_EXCL,
                    self.create_mode,
                )
                os.close(fd)
            except FileExistsError:
                pass
        # Verify mode (B9 / §1.7.3 enforcement). Refuse to write if drifted.
        current_mode = stat.S_IMODE(self.path.stat().st_mode)
        if current_mode != self.create_mode:
            raise PermissionError(
                f"Refusing to write to {self.path}: mode is {oct(current_mode)}, "
                f"expected {oct(self.create_mode)}. "
                f"Run: chmod {oct(self.create_mode)[2:]} {self.path}"
            )

    def append(self, payload: dict) -> None:
        """Append one JSON-line entry. Raises ValueError if line > MAX_LINE_BYTES."""
        line = json.dumps(payload, separators=(",", ":"), default=_json_default) + "\n"
        encoded = line.encode("utf-8")
        if len(encoded) > self.MAX_LINE_BYTES:
            raise ValueError(
                f"log.jsonl line exceeds {self.MAX_LINE_BYTES} bytes "
                f"(got {len(encoded)}); refusing to write to avoid interleaving. "
                f"Truncate metadata or use bundle attachment instead."
            )
        # Re-verify chmod 600 on every write (defense in depth per §1.7.3).
        current_mode = stat.S_IMODE(self.path.stat().st_mode)
        if current_mode != self.create_mode:
            raise PermissionError(
                f"Refusing to write to {self.path}: mode drifted to {oct(current_mode)}, "
                f"expected {oct(self.create_mode)}."
            )
        fd = os.open(str(self.path), os.O_APPEND | os.O_WRONLY)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)


def _json_default(obj: Any) -> Any:
    """JSON encoder for datetime + enum + pydantic models. Rejects naive datetimes."""
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            raise ValueError(
                f"datetime {obj!r} is timezone-naive; reject per §1.7.2"
            )
        return obj.isoformat()
    # Pydantic v2 model
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    # Enum (str-enum, IntEnum, etc.)
    if hasattr(obj, "value"):
        return obj.value
    raise TypeError(f"Object of type {type(obj).__name__} not JSON serializable")


def append_event(experiment_dir: Path, event: Union[EventPayload, dict]) -> None:
    """Append one event to ``<experiment_dir>/log.jsonl`` in atomic, append-only fashion.

    Accepts either a pydantic EventPayload model or a pre-serialized dict.
    Creates log.jsonl with chmod 600 if missing; refuses to write if mode drifts.
    """
    if hasattr(event, "model_dump"):
        payload = event.model_dump(mode="json")
    else:
        payload = event  # type: ignore[assignment]
    log_path = experiment_dir / "log.jsonl"
    writer = _AtomicJsonlWriter(log_path, create_mode=0o600)
    writer.append(payload)


def canonical_chain_hash(
    experiment_dir: Path,
    *,
    from_event: int = 0,
    to_event: Optional[int] = None,
) -> str:
    """Stable sha256 over the canonical serialization of log.jsonl (W2.1).

    The hash is the credibility anchor for replay: two reviewers who replay
    the same experiment (deterministic per-experiment action ids + recorded
    timestamps, per ``OrchestratorStore``) reach the *same* chain hash.

    Canonicalization rules (so the hash binds content, not formatting):
      - parse each JSON line, then re-serialize with ``sort_keys=True`` and
        no whitespace, so key ordering / spacing never moves the hash;
      - hash the ordered list of event objects, so event order is bound;
      - an absent or empty log hashes to the sha256 of ``b""`` (vacuously
        consistent — mirrors ``validate_chain`` on a missing log).

    ``from_event`` / ``to_event`` slice the event list (half-open) so a
    caller can hash a prefix — e.g. to compare two runs up to a checkpoint.
    """
    log_path = experiment_dir / "log.jsonl"
    if not log_path.exists():
        return hashlib.sha256(b"").hexdigest()
    rows: list[Any] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    rows = rows[from_event:to_event]
    canonical = json.dumps(
        rows, sort_keys=True, separators=(",", ":"), default=_json_default
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_conversation_turn(experiment_dir: Path, turn: dict) -> None:
    """Append one conversation turn to conversation.jsonl, same atomic+chmod600 pattern.

    Per §10.5.6, conversation.jsonl is rotated when size > 5MB; rotation is
    handled by the conversation-writer module, not here — this primitive only
    handles the atomic append.
    """
    conv_path = experiment_dir / "conversation.jsonl"
    writer = _AtomicJsonlWriter(conv_path, create_mode=0o600)
    writer.append(turn)


def _atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Atomic full-file write: write to tmp, fsync, then rename.

    The single shared atomic-write helper (also used by ExperimentStore). The
    rename is atomic on POSIX; we re-chmod after rename in case umask
    interfered. If any step before the rename completes fails (e.g. an
    interrupt mid-write), the partial tmp sibling is unlinked so an aborted
    write never leaves a ``*.tmp`` leftover behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        fd = os.open(str(tmp_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    # Enforce mode on the final path (rename may have inherited a different mode).
    try:
        os.chmod(path, mode)
    except OSError:
        pass  # Tolerate on Windows / restricted filesystems.


__all__ = [
    "append_event",
    "append_conversation_turn",
    "canonical_chain_hash",
    "_atomic_write_bytes",
]
