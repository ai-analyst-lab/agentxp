"""Tests for openxp.orchestrator.conversation — ConversationStore."""
from __future__ import annotations

import json
import logging
import multiprocessing as mp
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from openxp.orchestrator.conversation import (
    CONTENT_MAX_BYTES,
    SIZE_REFUSE_BYTES,
    SIZE_WARN_BYTES,
    ConversationStore,
    ConversationTurn,
)


# ─── Helpers ──────────────────────────────────────────────────────────


def _read_lines(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


# ─── Tests ────────────────────────────────────────────────────────────


def test_append_writes_jsonl_line(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    turn_id = store.append(
        actor="user", agent_name=None, content="hello world"
    )
    lines = _read_lines(store.path)
    assert len(lines) == 1
    assert lines[0]["turn_id"] == turn_id
    assert lines[0]["actor"] == "user"
    assert lines[0]["content"] == "hello world"
    assert lines[0]["schema_version"] == 1


def test_append_returns_turn_id_ulid_shaped(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    turn_id = store.append(actor="system", agent_name=None, content="x")
    # ULID-ish: at least 16 chars, Crockford base32 alphabet (or uppercase hex)
    assert len(turn_id) >= 16
    assert all(c in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for c in turn_id)


def test_append_below_warn_no_log(tmp_path: Path, caplog):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    with caplog.at_level(logging.WARNING):
        store.append(actor="user", agent_name=None, content="hi")
    # Tiny append, far below 50MB; no warn-level log expected.
    assert not any(
        "50" in rec.message or "rotation" in rec.message.lower()
        for rec in caplog.records
        if rec.levelno >= logging.WARNING
    )


def test_append_crosses_warn_threshold_emits_warning(tmp_path: Path, caplog, monkeypatch):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    # Stub size to return just over SIZE_WARN_BYTES after write.
    real_size = [0, SIZE_WARN_BYTES + 1000]  # before-write, after-write
    monkeypatch.setattr(store, "_size_locked", lambda: real_size.pop(0) if real_size else SIZE_WARN_BYTES + 1000)
    with caplog.at_level(logging.WARNING):
        store.append(actor="user", agent_name=None, content="warn-trigger")
    warn_msgs = [rec.message for rec in caplog.records if rec.levelno >= logging.WARNING]
    assert warn_msgs, f"Expected a warn-level log, got: {[r.message for r in caplog.records]}"
    assert any("50" in m or "warn" in m.lower() or "rotation" in m.lower() for m in warn_msgs)


def test_append_at_refuse_threshold_rotates(tmp_path: Path, monkeypatch):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    # Seed the live file with one turn so rotation produces a non-empty rotated file.
    store.append(actor="user", agent_name=None, content="before-rotate")
    # Force the next size check to return >= REFUSE so rotate fires.
    sizes = iter([SIZE_REFUSE_BYTES + 1, 0, 0, 0, 0])
    monkeypatch.setattr(store, "_size_locked", lambda: next(sizes, 0))
    store.append(actor="user", agent_name=None, content="after-rotate")
    # The live file should now have rotation marker + after-rotate (and possibly before).
    # The pre-rotate content moved to a renamed file.
    rotated = list(tmp_path.glob("conversation.*.jsonl"))
    assert rotated, "Expected a rotated file with timestamp suffix"


def test_oversize_content_truncated(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    big = "x" * (CONTENT_MAX_BYTES + 1000)
    store.append(actor="agent", agent_name="profiler", content=big)
    lines = _read_lines(store.path)
    assert len(lines) == 1
    assert lines[0]["content_truncated"] is True
    assert lines[0]["content_original_size_bytes"] == CONTENT_MAX_BYTES + 1000
    assert len(lines[0]["content"].encode("utf-8")) <= CONTENT_MAX_BYTES


def test_read_all_round_trip(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    ids = [
        store.append(actor="user", agent_name=None, content=f"turn-{i}")
        for i in range(3)
    ]
    turns = store.read_all()
    assert [t.turn_id for t in turns] == ids
    assert [t.content for t in turns] == ["turn-0", "turn-1", "turn-2"]
    assert all(isinstance(t, ConversationTurn) for t in turns)
    assert all(t.ts.tzinfo is not None for t in turns)


def test_read_since_filters_correctly(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    ids = [
        store.append(actor="user", agent_name=None, content=f"turn-{i}")
        for i in range(5)
    ]
    rest = store.read_since(ids[1])
    assert [t.turn_id for t in rest] == ids[2:]
    assert [t.content for t in rest] == ["turn-2", "turn-3", "turn-4"]


def _concurrent_writer(path_str: str, count: int):
    store = ConversationStore(Path(path_str))
    for i in range(count):
        store.append(actor="user", agent_name=None, content=f"pid-{os.getpid()}-i-{i}")


def test_concurrent_appends_serialize(tmp_path: Path):
    path = tmp_path / "conversation.jsonl"
    # Initialize the file before forking workers.
    ConversationStore(path)
    procs = [
        mp.Process(target=_concurrent_writer, args=(str(path), 5))
        for _ in range(2)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0, f"Worker failed with {p.exitcode}"
    lines = _read_lines(path)
    assert len(lines) == 10
    # Every line is well-formed JSON with all expected keys.
    for line in lines:
        assert "turn_id" in line
        assert "actor" in line
        assert "content" in line


def test_rotate_explicit(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    store.append(actor="user", agent_name=None, content="pre")
    rotated_path = store.rotate()
    assert rotated_path.exists()
    assert rotated_path.name != "conversation.jsonl"
    # Live file exists and has at least the rotation marker.
    assert store.path.exists()
    lines = _read_lines(store.path)
    assert len(lines) >= 1
    assert lines[0]["actor"] == "system"


def test_rotation_marker_metadata_subtype_is_log_rotation(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    store.append(actor="user", agent_name=None, content="seed")
    store.rotate()
    lines = _read_lines(store.path)
    assert lines, "Expected at least the rotation marker line"
    marker = lines[0]
    assert marker["actor"] == "system"
    assert marker.get("metadata", {}).get("subtype") == "log_rotation"


def test_chmod_600_on_create(tmp_path: Path):
    path = tmp_path / "conversation.jsonl"
    ConversationStore(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"
