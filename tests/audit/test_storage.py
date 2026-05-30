"""Tests for agentxp.audit.storage — log.jsonl writer + chmod 600 enforcement.

Covers acceptance criteria for W_pre1.5:
  1. File creation is chmod 600 (no world-readable window).
  2. Oversize lines (> 4096 bytes) raise ValueError.
  3. Multiple atomic appends preserve order and one-line-per-call shape.
  4. _atomic_write_bytes lands with chmod 600.
  5. Naive datetimes inside event payloads raise ValueError via _json_default.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §1.7.3, §1.7.2, §10.5.6, §9.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentxp.audit.storage import (
    _AtomicJsonlWriter,
    _atomic_write_bytes,
    _json_default,
    append_conversation_turn,
    append_event,
)


def _mode_of(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_append_event_creates_file_chmod_600(tmp_path: Path) -> None:
    """§1.7.3 / B9: newly created log.jsonl must be mode 0o600."""
    event = {
        "event_name": "stage.entered",
        "ts": datetime.now(timezone.utc).isoformat(),
        "stage": "design",
    }
    append_event(tmp_path, event)
    log_path = tmp_path / "log.jsonl"
    assert log_path.exists(), "log.jsonl should be created on first append"
    assert _mode_of(log_path) == 0o600, (
        f"log.jsonl must be chmod 600; got {oct(_mode_of(log_path))}"
    )
    # And the line was actually written.
    line = log_path.read_text().strip()
    assert json.loads(line)["event_name"] == "stage.entered"


def test_append_event_rejects_oversize(tmp_path: Path) -> None:
    """Lines > 4096 bytes must raise ValueError (PIPE_BUF interleave protection)."""
    huge_payload = {
        "event_name": "agent.completed",
        "ts": datetime.now(timezone.utc).isoformat(),
        "filler": "x" * 5000,
    }
    with pytest.raises(ValueError, match="exceeds 4096 bytes"):
        append_event(tmp_path, huge_payload)
    # No partial line should have been written. File may exist (created chmod
    # 600 on first call) but must be empty.
    log_path = tmp_path / "log.jsonl"
    if log_path.exists():
        assert log_path.read_text() == "", "no bytes should have been appended"


def test_append_event_appends_multiple_lines(tmp_path: Path) -> None:
    """Append-only semantics: N calls produce N newline-terminated JSON lines, in order."""
    for i in range(5):
        append_event(
            tmp_path,
            {
                "event_name": "stage.committed",
                "ts": datetime.now(timezone.utc).isoformat(),
                "i": i,
            },
        )
    log_path = tmp_path / "log.jsonl"
    lines = log_path.read_text().splitlines()
    assert len(lines) == 5, f"expected 5 lines, got {len(lines)}"
    indices = [json.loads(ln)["i"] for ln in lines]
    assert indices == [0, 1, 2, 3, 4], "append order must match call order"
    # chmod 600 preserved across appends.
    assert _mode_of(log_path) == 0o600


def test_append_conversation_turn_chmod_600(tmp_path: Path) -> None:
    """conversation.jsonl gets the same chmod-600 treatment as log.jsonl."""
    append_conversation_turn(tmp_path, {"role": "user", "content": "hi"})
    conv_path = tmp_path / "conversation.jsonl"
    assert conv_path.exists()
    assert _mode_of(conv_path) == 0o600


def test_atomic_write_bytes_chmod_600(tmp_path: Path) -> None:
    """_atomic_write_bytes lands the file with chmod 600 after rename."""
    target = tmp_path / "state.yaml"
    _atomic_write_bytes(target, b"name: example\n")
    assert target.exists()
    assert target.read_bytes() == b"name: example\n"
    assert _mode_of(target) == 0o600, (
        f"state.yaml must be chmod 600; got {oct(_mode_of(target))}"
    )
    # Tmp sibling should have been renamed away.
    assert not (tmp_path / "state.yaml.tmp").exists()


def test_naive_datetime_rejected_by_json_default() -> None:
    """§1.7.2: naive datetime in a payload must raise ValueError on serialization."""
    naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
    assert naive.tzinfo is None  # sanity
    with pytest.raises(ValueError, match="timezone-naive"):
        _json_default(naive)


def test_aware_datetime_serialized_by_json_default() -> None:
    """Aware UTC datetime should serialize to ISO 8601."""
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    out = _json_default(aware)
    assert isinstance(out, str)
    assert "2026-01-01T12:00:00" in out


def test_chmod_drift_refused(tmp_path: Path) -> None:
    """§1.7.3: if log.jsonl mode drifts off 0o600, next append must refuse."""
    append_event(
        tmp_path,
        {"event_name": "stage.entered", "ts": datetime.now(timezone.utc).isoformat()},
    )
    log_path = tmp_path / "log.jsonl"
    os.chmod(log_path, 0o644)  # simulate drift
    with pytest.raises(PermissionError, match="mode"):
        append_event(
            tmp_path,
            {"event_name": "stage.entered", "ts": datetime.now(timezone.utc).isoformat()},
        )
