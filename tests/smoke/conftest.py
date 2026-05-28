"""Shared fixtures for the W7 smoke-test suite (tests/smoke/).

These tests verify PLUMBING — file layout, chmod 600 sweep, state-machine
transitions, audit-chain wiring, resume classification. They do NOT run a
real LLM and they do NOT hit a real warehouse; ``dispatch._invoke_llm`` is
stubbed in v0.1.

Fixtures here are intentionally tiny:
  - ``fake_project_root`` — a ``tmp_path`` directory with the project layout
    AgentXP expects (``experiments/``, ``metrics/``, ``semantic_models/``).
  - ``fake_exp_dir`` — a per-experiment directory under ``fake_project_root``.
  - ``tiny_csv`` — a 50-row sample CSV the profiler can chew through.
  - ``tiny_duckdb`` — a freshly-built DuckDB file with a ``users`` table that
    Track B uses as a stand-in for a real warehouse.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10.5, §10.6.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def fake_project_root(tmp_path: Path) -> Path:
    """A bare agentxp project layout under ``tmp_path``."""
    root = tmp_path / "project"
    (root / "experiments").mkdir(parents=True)
    (root / "metrics").mkdir()
    (root / "semantic_models").mkdir()
    (root / "fact_sources").mkdir()
    return root


@pytest.fixture
def fake_exp_dir(fake_project_root: Path) -> Path:
    """An empty experiment directory ready for state.yaml + log.jsonl."""
    exp_dir = fake_project_root / "experiments" / "smoke_exp_001"
    exp_dir.mkdir(parents=True)
    return exp_dir


@pytest.fixture
def tiny_csv(tmp_path: Path) -> Path:
    """50-row CSV with two columns; small enough for profiler to handle fast."""
    csv = tmp_path / "tiny.csv"
    rows = ["user_id,converted"]
    for i in range(50):
        rows.append(f"u{i:04d},{i % 2}")
    csv.write_text("\n".join(rows) + "\n")
    return csv


@pytest.fixture
def tiny_duckdb(tmp_path: Path) -> Path:
    """A DuckDB file with a single ``users`` table (50 rows).

    Stand-in for a real warehouse — Track B uses this for adapter dispatch.
    Skips the test if ``duckdb`` is not installed in the environment.
    """
    duckdb = pytest.importorskip("duckdb")
    db_path = tmp_path / "warehouse.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE users (user_id VARCHAR, converted INTEGER)")
        rows = [(f"u{i:04d}", i % 2) for i in range(50)]
        conn.executemany("INSERT INTO users VALUES (?, ?)", rows)
    finally:
        conn.close()
    return db_path


@pytest.fixture
def chdir_to(monkeypatch: pytest.MonkeyPatch) -> Iterator[callable]:
    """Helper: ``chdir_to(path)`` issues ``monkeypatch.chdir(path)``."""
    yield monkeypatch.chdir


@pytest.fixture
def utcnow() -> datetime:
    """A single UTC timestamp the test can re-use across emissions."""
    return datetime.now(timezone.utc)


def mode_of(path: Path) -> int:
    """Return the octal POSIX mode bits of ``path``. Helper, not a fixture."""
    import stat as _stat

    return _stat.S_IMODE(path.stat().st_mode)
