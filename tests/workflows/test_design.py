"""Tests for agentxp.workflows.design (V10)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agentxp.workflows.design import (
    allocate_experiment,
    record_intent,
)


def test_allocate_creates_dir_and_log():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        exp_dir = allocate_experiment(root)
        assert exp_dir.exists()
        assert exp_dir.is_dir()
        assert exp_dir.parent.name == "experiments"
        assert (exp_dir / "log.md").exists()
        # Seeded with the "design verb opened" line.
        assert "design verb opened" in (exp_dir / "log.md").read_text()


def test_allocate_with_data_path_stashes_resolved_path():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fake_data = root / "data.duckdb"
        fake_data.write_text("placeholder")
        exp_dir = allocate_experiment(root, data_path=fake_data)
        stashed = (exp_dir / ".data_path").read_text()
        assert stashed == str(fake_data.resolve())


def test_allocate_with_explicit_experiment_id_uses_it():
    with tempfile.TemporaryDirectory() as tmp:
        exp_dir = allocate_experiment(Path(tmp), experiment_id="exp_custom")
        assert exp_dir.name == "exp_custom"


def test_allocate_collision_raises():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        allocate_experiment(root, experiment_id="exp_a")
        with pytest.raises(FileExistsError):
            allocate_experiment(root, experiment_id="exp_a")


def test_record_intent_writes_yaml_and_logs():
    with tempfile.TemporaryDirectory() as tmp:
        exp_dir = allocate_experiment(Path(tmp))
        intent_path = record_intent(
            exp_dir, "test whether X improves conversion", "shane"
        )
        assert intent_path.exists()
        content = intent_path.read_text()
        assert "test whether X improves conversion" in content
        assert "shane" in content
        # log.md was appended to
        log_content = (exp_dir / "log.md").read_text()
        assert "intent captured by shane" in log_content


def test_record_intent_rejects_empty():
    with tempfile.TemporaryDirectory() as tmp:
        exp_dir = allocate_experiment(Path(tmp))
        with pytest.raises(ValueError):
            record_intent(exp_dir, "", "shane")
        with pytest.raises(ValueError):
            record_intent(exp_dir, "ok", "")
