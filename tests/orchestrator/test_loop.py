"""T84 — orchestrator loop tests with mock LLM caller.

Tests the orchestrator's discipline at the Python layer:
  - dispatch_specialist assembles a validated bundle and calls the LLM
  - dispatch_critic uses CriticBundle structure (blind)
  - require_critic_pass blocks on severity="block", allows on "warn"
  - read_experiment_dir tracks state across turn boundaries
  - commit_artifact writes file + log + git in one step

The actual specialist outputs are mocked here. Real LLM dispatch is
exercised when the orchestrator runs inside a Claude Code session
against the DuckDB demo warehouse (Phase 10 E2E walks).
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from agentxp.orchestrator.tools import (
    ExperimentNotFound,
    commit_artifact,
    read_experiment_dir,
)


def _init_git_repo(path: Path) -> None:
    """Initialize a tiny git repo at path so commit_artifact works in tests."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path, check=True, capture_output=True,
    )
    # Initial commit so subsequent commits don't trip on the empty-tree edge case.
    (path / "README.md").write_text("test\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"],
        cwd=path, check=True, capture_output=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# read_experiment_dir
# ─────────────────────────────────────────────────────────────────────────────


def test_read_experiment_dir_returns_empty_state_for_fresh_dir():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp) / "exp_001"
        exp.mkdir()
        snap = read_experiment_dir(exp)
        assert snap.experiment_id == "exp_001"
        assert not snap.has_intent
        assert not snap.has_brief
        assert not snap.brief_sealed
        assert not snap.has_analysis
        assert not snap.has_verdict


def test_read_experiment_dir_detects_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp) / "exp_001"
        exp.mkdir()
        (exp / "intent.yaml").write_text("text: x\n")
        (exp / "brief.yaml").write_text("hypothesis: y\n")
        (exp / "brief.sealed.yaml").write_text("sealed: true\n")
        snap = read_experiment_dir(exp)
        assert snap.has_intent
        assert snap.has_brief
        assert snap.brief_sealed
        assert not snap.has_analysis


def test_read_experiment_dir_raises_for_missing():
    with pytest.raises(ExperimentNotFound):
        read_experiment_dir(Path("/no/such/path/exp_001"))


# ─────────────────────────────────────────────────────────────────────────────
# commit_artifact — file + log + git
# ─────────────────────────────────────────────────────────────────────────────


def test_commit_artifact_writes_file_log_and_git_commit():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        _init_git_repo(repo)

        sha = commit_artifact(
            exp_dir=repo,
            artifact_name="brief.yaml",
            content="hypothesis: treatment improves X\n",
            log_entry="brief drafted by designer",
        )
        assert len(sha) == 40  # full sha
        assert (repo / "brief.yaml").read_text().startswith("hypothesis:")
        assert "brief drafted" in (repo / "log.md").read_text()


# NOTE: dispatch_specialist / dispatch_critic / require_critic_pass tests
# were removed by audit removal Round 2 (see
# working/audits/2026-06-08-system-and-code-audit.md S4.A). The bridge
# replaced this path in W5; tests live in tests/orchestrator/test_bridge.py.
