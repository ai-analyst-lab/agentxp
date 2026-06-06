"""W5.4 — batched commit_artifacts overload.

One commit, one log.md entry, every artifact landed. Used by W6.4's
fan_out helper to land all six render variants (3 audiences × 2 formats)
in a single audit-chain event.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentxp.orchestrator.errors import ToolRefusal
from agentxp.orchestrator.tools import commit_artifacts
from agentxp.workflows.design import allocate_experiment


def _run(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def project_repo(tmp_path: Path) -> Path:
    root = tmp_path / "agentxp"
    root.mkdir()
    (root / "experiments").mkdir()
    _run(["git", "init", "-q", "-b", "main"], cwd=root)
    _run(["git", "config", "user.email", "ci@agentxp.test"], cwd=root)
    _run(["git", "config", "user.name", "CI"], cwd=root)
    (root / ".gitignore").write_text("experiments/*\n!experiments/exp_*/\n")
    _run(["git", "add", ".gitignore"], cwd=root)
    _run(["git", "commit", "-q", "-m", "init"], cwd=root)
    return root


def test_batched_commit_lands_six_files_in_one_commit(project_repo: Path) -> None:
    """Six readout files, one commit, one log row."""
    exp_dir = allocate_experiment(project_repo)
    artifacts = [
        (f"readouts/intent/01/{audience}.{fmt}", f"# {audience}.{fmt}\n")
        for audience in ("exec", "operator", "engineer")
        for fmt in ("html", "md")
    ]
    assert len(artifacts) == 6

    pre_log_count = sum(1 for _ in _run(["git", "log", "--oneline"], cwd=project_repo).splitlines())

    sha = commit_artifacts(
        exp_dir=exp_dir,
        artifacts=artifacts,
        log_entry="intent share-tail fan-out × 6",
        git_message="W5.4 batched commit smoke test",
    )
    assert len(sha) == 40

    post_log_count = sum(1 for _ in _run(["git", "log", "--oneline"], cwd=project_repo).splitlines())
    assert post_log_count - pre_log_count == 1, (
        f"expected one new commit, got {post_log_count - pre_log_count}"
    )

    tracked = _run(["git", "ls-files"], cwd=project_repo).splitlines()
    rel = exp_dir.relative_to(project_repo)
    for name, _ in artifacts:
        assert f"{rel}/{name}" in tracked

    # One log.md row appended
    log_lines = (exp_dir / "log.md").read_text().strip().split("\n")
    fan_out_lines = [ln for ln in log_lines if "fan-out × 6" in ln]
    assert len(fan_out_lines) == 1


def test_empty_artifacts_list_refused(project_repo: Path) -> None:
    """ToolRefusal — every batched commit must include at least one file."""
    exp_dir = allocate_experiment(project_repo)
    with pytest.raises(ToolRefusal):
        commit_artifacts(
            exp_dir=exp_dir,
            artifacts=[],
            log_entry="empty",
            git_message="should refuse",
        )
