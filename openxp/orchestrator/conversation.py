"""ConversationStore — append-only conversation log for OpenXP v0.1.

Per-experiment ``conversation.jsonl`` writer with:

- Atomic line append via ``O_APPEND`` + ``fsync`` (POSIX) under an exclusive
  cross-platform file lock (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on
  Windows). Mirrors the ``audit/storage._AtomicJsonlWriter`` pattern but adds
  whole-file locking so concurrent writers serialise even when individual
  lines exceed ``PIPE_BUF``.
- Size-aware rotation. ``SIZE_WARN_BYTES`` (50MB) emits a single stderr +
  ``logging.warning`` per session; ``SIZE_REFUSE_BYTES`` (100MB) triggers
  rotation *before* the append.
- Content guard: any turn whose ``content`` would exceed
  ``CONTENT_MAX_BYTES`` (1MB) is truncated at a UTF-8-safe byte boundary,
  ``content_truncated=True`` and ``content_original_size_bytes=<original>``
  are recorded.
- ``chmod 600`` on file creation, re-verified on every append (defence in
  depth, matching ``audit/storage.py``).

NOTE — rotation strategy deviation from §10.5.6:
  The plan's §10.5.6 specifies gzip rotation with an integer index
  (``conversation.{N}.jsonl.gz``). This module implements the caller's
  builder-supplied spec instead: a plain rename to
  ``{stem}.{timestamp}.jsonl`` followed by a system-actor rotation-marker
  turn written as the first line of the fresh log. Both shapes preserve the
  §10.5.6 invariants the rest of the orchestrator depends on (rotated files
  remain on disk; the live log path is reusable; the rotation event has
  ``metadata.subtype="log_rotation"``).

Source spec: OPENXP_V01_PLAN.md §1.7.2, §1.8.5, §1.8.12, §10.5.6, §10.5.7.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import stat
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

# Cross-platform whole-file locking. POSIX uses fcntl.flock; Windows uses
# msvcrt.locking (byte-range lock on a sentinel byte). Both are advisory.
try:
    import fcntl  # type: ignore[import]

    _HAS_FCNTL = True
except ImportError:  # pragma: no cover — Windows path
    _HAS_FCNTL = False
    try:
        import msvcrt  # type: ignore[import]
    except ImportError:  # pragma: no cover — defensive
        msvcrt = None  # type: ignore[assignment]


# ──────────────────────────────────────────────────────────────────────────
# Constants — sized per builder spec.
# ──────────────────────────────────────────────────────────────────────────

SIZE_WARN_BYTES: int = 50 * 1024 * 1024
"""Soft threshold — log a stderr warning if a write would cross this size."""

SIZE_REFUSE_BYTES: int = 100 * 1024 * 1024
"""Hard threshold — rotate before the next append when the live file
exceeds this size. Mirrors §1.8.12's 100MB cap and §10.5.6's H43 trigger."""

CONTENT_MAX_BYTES: int = 1 * 1024 * 1024
"""Single-turn content cap. Larger content is truncated and flagged via
``content_truncated`` + ``content_original_size_bytes``."""


# ──────────────────────────────────────────────────────────────────────────
# UTC enforcement — local copy to avoid coupling to schemas.state.
# ──────────────────────────────────────────────────────────────────────────


def _enforce_utc(v: datetime) -> datetime:
    """Reject naive datetimes and non-UTC tzinfo (§1.7.2).

    Mirrors the ``schemas.state._enforce_utc`` semantics so this module can
    stay free of upward imports into the schemas layer (which itself does
    not import the orchestrator).
    """
    if v.tzinfo is None:
        raise ValueError("datetime must be timezone-aware; got a naive datetime")
    offset = v.tzinfo.utcoffset(v)
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(
            f"datetime must be UTC (offset 0); got tzinfo={v.tzinfo!r} "
            f"with offset={offset}"
        )
    return v


# ──────────────────────────────────────────────────────────────────────────
# Model — one row of conversation.jsonl.
# ──────────────────────────────────────────────────────────────────────────


class ConversationTurn(BaseModel):
    """One conversation turn (§1.8.12, §10.8.1).

    Per-line schema_version=1 (§1.8.6 table). ``extra="forbid"`` so unknown
    fields surface immediately during JSON-line round-trip in tests.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    turn_id: str
    ts: datetime
    actor: Literal["user", "agent", "system"]
    agent_name: Optional[str] = None
    content: str
    content_truncated: bool = False
    content_original_size_bytes: int
    action_id: Optional[str] = None
    parent_action_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None

    @field_validator("ts")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)


# ──────────────────────────────────────────────────────────────────────────
# Turn-ID generator — Crockford base32 ULID-ish.
# ──────────────────────────────────────────────────────────────────────────


# Crockford base32 alphabet (no I, L, O, U — collision-resistant for humans).
_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_crockford(data: bytes) -> str:
    """Encode 16 bytes (128 bits) as 26 Crockford-base32 chars.

    Standard ULID encoding — 5-bit groups, big-endian, MSB first. Pads the
    128-bit input to 130 bits so the leading char fits in 2 bits (matches
    the canonical ULID layout where the first char is 0-7).
    """
    if len(data) != 16:
        raise ValueError(f"Crockford encode expects 16 bytes, got {len(data)}")
    n = int.from_bytes(data, "big")
    # 16 bytes = 128 bits → pad to 130 (26 × 5) by left-shifting 2.
    n <<= 2
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD_ALPHABET[n & 0b11111])
        n >>= 5
    return "".join(reversed(chars))


_turn_id_lock = threading.Lock()
_last_ms = 0
_last_random = 0


def _new_turn_id(now_ms: Optional[int] = None) -> str:
    """Generate a 26-char ULID-shaped turn ID (48-bit ms + 80-bit random).

    Monotonicity guarantee within a process: if two turn IDs are generated
    in the same millisecond, the random component of the second is
    incremented from the first rather than freshly drawn. This keeps
    ``read_since`` ordering stable when callers batch-append.
    """
    global _last_ms, _last_random
    with _turn_id_lock:
        ms = now_ms if now_ms is not None else int(time.time() * 1000)
        if ms == _last_ms:
            _last_random += 1
            rnd = _last_random
        else:
            _last_ms = ms
            rnd = int.from_bytes(secrets.token_bytes(10), "big")
            _last_random = rnd
        # 48-bit ms + 80-bit random = 128 bits, packed big-endian.
        packed = ms.to_bytes(6, "big") + (rnd & ((1 << 80) - 1)).to_bytes(10, "big")
    return _encode_crockford(packed)


# ──────────────────────────────────────────────────────────────────────────
# JSON helpers — shared with audit/storage.
# ──────────────────────────────────────────────────────────────────────────


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            raise ValueError(f"datetime {obj!r} is timezone-naive; reject per §1.7.2")
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "value"):
        return obj.value
    raise TypeError(f"Object of type {type(obj).__name__} not JSON serializable")


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """Truncate ``text`` so its UTF-8 encoding is ≤ ``max_bytes``.

    Cuts at the largest prefix that decodes cleanly — never splits a
    multibyte codepoint. If the input is already within budget, returned
    unchanged.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # Cut at max_bytes, then back off until we land on a codepoint boundary.
    trimmed = encoded[:max_bytes]
    while trimmed:
        try:
            return trimmed.decode("utf-8")
        except UnicodeDecodeError:
            trimmed = trimmed[:-1]
    return ""


# ──────────────────────────────────────────────────────────────────────────
# File lock helpers — cross-platform whole-file exclusive lock.
# ──────────────────────────────────────────────────────────────────────────


class _FileLock:
    """Context manager: hold an OS-level exclusive lock on ``lock_path``.

    Uses ``fcntl.flock`` on POSIX (whole-file lock) and ``msvcrt.locking``
    on Windows (byte-range lock on byte 0). The lock file is a separate
    sidecar so we can lock-then-open-O_APPEND on the live jsonl without
    fighting `O_EXCL` semantics.
    """

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fd: Optional[int] = None

    def __enter__(self) -> "_FileLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # O_CREAT (no O_EXCL) so multiple callers can open the same sentinel.
        self._fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        if _HAS_FCNTL:
            fcntl.flock(self._fd, fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover — Windows path
            # Lock 1 byte at offset 0; block until acquired.
            os.lseek(self._fd, 0, os.SEEK_SET)
            while True:
                try:
                    msvcrt.locking(self._fd, msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.01)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is None:
            return
        try:
            if _HAS_FCNTL:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover — Windows path
                os.lseek(self._fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        finally:
            os.close(self._fd)
            self._fd = None


# ──────────────────────────────────────────────────────────────────────────
# ConversationStore.
# ──────────────────────────────────────────────────────────────────────────


_logger = logging.getLogger(__name__)


class ConversationStore:
    """Append-only ``conversation.jsonl`` writer with size-aware rotation.

    One instance per ``conversation.jsonl`` path. Safe for use from multiple
    threads within a process (turn-id generator is locked) and from multiple
    processes on the same machine (whole-file flock around every append +
    rotate). Cross-machine safety is out of scope per §1.8.12.
    """

    CREATE_MODE: int = 0o600

    def __init__(self, jsonl_path: Path):
        self.path = Path(jsonl_path)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._warned_session = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._create_with_chmod()

    # ─── Public API ──────────────────────────────────────────────────

    def append(
        self,
        actor: Literal["user", "agent", "system"],
        agent_name: Optional[str],
        content: str,
        action_id: Optional[str] = None,
        parent_action_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Append one turn. Returns the generated turn_id.

        Behaviour:
        - Content over ``CONTENT_MAX_BYTES`` is truncated (UTF-8 safe);
          ``content_truncated=True`` and the original byte-size are recorded.
        - If the live file already exceeds ``SIZE_REFUSE_BYTES`` rotation
          fires before the append (the new turn lands in the fresh file).
        - If the post-write size would cross ``SIZE_WARN_BYTES`` for the
          first time this session, a warning is logged to stderr exactly
          once.
        """
        original_size = len(content.encode("utf-8"))
        truncated = False
        if original_size > CONTENT_MAX_BYTES:
            content = _truncate_utf8(content, CONTENT_MAX_BYTES)
            truncated = True

        with _FileLock(self._lock_path):
            # Rotation: re-check size under lock to avoid racing rotators.
            if self._size_locked() >= SIZE_REFUSE_BYTES:
                self._rotate_locked()

            turn = ConversationTurn(
                schema_version=1,
                turn_id=_new_turn_id(),
                ts=datetime.now(timezone.utc),
                actor=actor,
                agent_name=agent_name,
                content=content,
                content_truncated=truncated,
                content_original_size_bytes=original_size,
                action_id=action_id,
                parent_action_id=parent_action_id,
                metadata=metadata,
            )
            self._write_turn_locked(turn)

            # Warn-once if we just crossed the 50MB soft threshold.
            new_size = self._size_locked()
            if (
                not self._warned_session
                and new_size >= SIZE_WARN_BYTES
                and new_size < SIZE_REFUSE_BYTES
            ):
                msg = (
                    f"conversation.jsonl at {self.path} is {new_size} bytes "
                    f"(>= {SIZE_WARN_BYTES}); rotation triggers at {SIZE_REFUSE_BYTES}."
                )
                print(f"WARNING: {msg}", file=sys.stderr)
                _logger.warning(msg)
                self._warned_session = True

        return turn.turn_id

    def read_all(self) -> list[ConversationTurn]:
        """Read every turn currently in the live file. Rotated files are
        not read here — use ``openxp audit --replay`` for full history."""
        if not self.path.exists():
            return []
        turns: list[ConversationTurn] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                turns.append(ConversationTurn.model_validate_json(line))
        return turns

    def read_since(self, after_turn_id: str) -> list[ConversationTurn] :
        """Return all turns whose ``turn_id`` sorts strictly after
        ``after_turn_id``. Crockford base32 is sort-compatible with the
        underlying ms timestamp, so lexicographic compare on the string is
        equivalent to chronological compare."""
        return [t for t in self.read_all() if t.turn_id > after_turn_id]

    def rotate(self) -> Path:
        """Force a rotation; return the path of the rotated file."""
        with _FileLock(self._lock_path):
            return self._rotate_locked()

    def current_size_bytes(self) -> int:
        """Current size of the live jsonl file (0 if missing)."""
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    # ─── Internals (must be called under _FileLock) ──────────────────

    def _size_locked(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    def _create_with_chmod(self) -> None:
        """Create the live jsonl with chmod 600 (no world-readable window)."""
        fd = os.open(
            str(self.path),
            os.O_CREAT | os.O_WRONLY | os.O_EXCL,
            self.CREATE_MODE,
        )
        os.close(fd)

    def _verify_mode(self) -> None:
        current_mode = stat.S_IMODE(self.path.stat().st_mode)
        if current_mode != self.CREATE_MODE:
            raise PermissionError(
                f"Refusing to write to {self.path}: mode is "
                f"{oct(current_mode)}, expected {oct(self.CREATE_MODE)}."
            )

    def _write_turn_locked(self, turn: ConversationTurn) -> None:
        payload = turn.model_dump(mode="json")
        line = json.dumps(payload, separators=(",", ":"), default=_json_default) + "\n"
        encoded = line.encode("utf-8")
        if not self.path.exists():
            # Rotation just happened or the file was deleted externally;
            # re-create with the right mode.
            self._create_with_chmod()
        self._verify_mode()
        fd = os.open(str(self.path), os.O_APPEND | os.O_WRONLY)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)

    def _rotate_locked(self) -> Path:
        """Rename the live file to ``{stem}.{timestamp}.jsonl``, create a
        fresh empty file, and write the rotation-marker turn as line 1.

        Returns the path of the rotated (archived) file. The caller is
        already holding ``_FileLock``.
        """
        # Reset the warn-once flag — the new file starts at 0 bytes.
        self._warned_session = False

        if not self.path.exists():
            # Nothing to rotate; just ensure a live file exists for downstream.
            self._create_with_chmod()
            return self.path

        # Use a UTC timestamp with microseconds + a short nonce to avoid
        # filename collisions across rapid back-to-back rotations.
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        nonce = secrets.token_hex(2)
        stem = self.path.stem  # "conversation" for ".../conversation.jsonl"
        rotated_name = f"{stem}.{ts}.{nonce}.jsonl"
        rotated_path = self.path.parent / rotated_name
        os.rename(self.path, rotated_path)

        # Fresh file, chmod 600 from creation.
        self._create_with_chmod()

        # First line: the rotation marker. This is a system-actor turn so
        # downstream `read_all`/`read_since` still see well-typed rows.
        marker = ConversationTurn(
            schema_version=1,
            turn_id=_new_turn_id(),
            ts=datetime.now(timezone.utc),
            actor="system",
            agent_name=None,
            content=f"log rotated from {rotated_path}",
            content_truncated=False,
            content_original_size_bytes=len(
                f"log rotated from {rotated_path}".encode("utf-8")
            ),
            action_id=None,
            parent_action_id=None,
            metadata={
                "subtype": "log_rotation",
                "rotated_to": rotated_path.name,
                "bytes_rotated": rotated_path.stat().st_size,
            },
        )
        self._write_turn_locked(marker)
        return rotated_path


__all__ = [
    "SIZE_WARN_BYTES",
    "SIZE_REFUSE_BYTES",
    "CONTENT_MAX_BYTES",
    "ConversationTurn",
    "ConversationStore",
]
