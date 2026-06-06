"""W0.1 — commit_artifact cwd / path resolution regression test.

The pre-W0 bug: commit_artifact ran `git add <root-relative-path>` with
`cwd=exp_dir`, so git resolved every artifact path as
`experiments/<id>/experiments/<id>/file`. Every audited write failed with
exit 128 and skills had to bypass with manual `git add` from the project
root. This test guards against the regression: a freshly allocated
experiment dir commits its first artifact through commit_artifact and the
file appears in `git ls-files`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentxp.orchestrator.tools import commit_artifact
from agentxp.workflows.design import allocate_experiment


def _run(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def project_repo(tmp_path: Path) -> Path:
    """Fresh git repo with the minimum layout commit_artifact needs."""
    root = tmp_path / "agentxp"
    root.mkdir()
    (root / "experiments").mkdir()
    _run(["git", "init", "-q", "-b", "main"], cwd=root)
    _run(["git", "config", "user.email", "ci@agentxp.test"], cwd=root)
    _run(["git", "config", "user.name", "CI"], cwd=root)
    # Mirror the .gitignore glob we ship so allocate_experiment's dir is admitted.
    (root / ".gitignore").write_text("experiments/*\n!experiments/exp_*/\n")
    _run(["git", "add", ".gitignore"], cwd=root)
    _run(["git", "commit", "-q", "-m", "init"], cwd=root)
    return root


def test_commit_artifact_lands_from_fresh_exp(project_repo: Path) -> None:
    """A freshly allocated experiment's first artifact reaches git history."""
    exp_dir = allocate_experiment(project_repo)
    sha = commit_artifact(
        exp_dir=exp_dir,
        artifact_name="hypothesis.yaml",
        content="schema_version: 1\nhypothesis: |\n  pre-W0 sanity check.\n",
        log_entry="hypothesis drafted (test)",
        git_message="test: first artifact via commit_artifact",
    )
    assert sha and len(sha) == 40, f"expected a full SHA, got {sha!r}"

    tracked = _run(["git", "ls-files"], cwd=project_repo).splitlines()
    rel = exp_dir.relative_to(project_repo)
    assert f"{rel}/hypothesis.yaml" in tracked, (
        f"{rel}/hypothesis.yaml missing from git ls-files; got {tracked!r}"
    )
    assert f"{rel}/log.md" in tracked, (
        f"{rel}/log.md missing from git ls-files; got {tracked!r}"
    )

    status = _run(["git", "status", "--porcelain"], cwd=project_repo)
    assert status == "", f"working tree dirty after commit_artifact: {status!r}"


def test_gitignore_admits_any_exp_prefix(project_repo: Path) -> None:
    """`.gitignore` whitelists every `exp_*` dir under experiments/."""
    exp_dir = allocate_experiment(project_repo)
    assert exp_dir.name.startswith("exp_"), (
        f"allocate_experiment should produce an exp_-prefixed dir; got {exp_dir.name}"
    )
    # The dir exists but is empty — `git check-ignore` should not flag any file
    # under it as ignored by the project gitignore.
    result = subprocess.run(
        ["git", "check-ignore", "-v", f"{exp_dir.relative_to(project_repo)}/.data_path"],
        cwd=project_repo, capture_output=True, text=True,
    )
    # check-ignore returns exit 1 when the path is *not* ignored — that's what
    # we want post-W0.
    assert result.returncode == 1, (
        f"freshly allocated experiment dir is still gitignored: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
