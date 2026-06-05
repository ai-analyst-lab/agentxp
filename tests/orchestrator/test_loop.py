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

from agentxp.orchestrator.bundle_assembler import BundleAssemblyError
from agentxp.orchestrator.loop import (
    dispatch_critic,
    dispatch_specialist,
    require_critic_pass,
)
from agentxp.orchestrator.tools import (
    ExperimentNotFound,
    ToolRefusal,
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
        assert not snap.has_report


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


# ─────────────────────────────────────────────────────────────────────────────
# dispatch_specialist — bundle validation + LLM caller is invoked
# ─────────────────────────────────────────────────────────────────────────────


def test_dispatch_specialist_assembles_bundle_and_calls_llm():
    with tempfile.TemporaryDirectory() as tmp:
        project_root = Path(tmp)
        agents_dir = project_root / "agents"
        agents_dir.mkdir()
        (agents_dir / "understander.md").write_text("# Understander\n")

        captured = {}

        def mock_llm(*, role, system_prompt_path, bundle):
            captured["role"] = role
            captured["bundle_role"] = bundle.role
            captured["sha256"] = bundle.sha256
            return {"semantic_models": [], "metrics": []}

        from agentxp.schemas.bundles import WarehouseProfile
        sources = {
            "warehouse_profile": WarehouseProfile(tables={}, flags=[]),
            "existing_semantic_models": [],
            "existing_metrics": [],
            "task": "draft_semantic_models",
        }
        result = dispatch_specialist(
            role="understander",
            sources=sources,
            project_root=project_root,
            llm_caller=mock_llm,
        )
        assert result == {"semantic_models": [], "metrics": []}
        assert captured["role"] == "understander"
        assert captured["bundle_role"] == "understander"
        assert len(captured["sha256"]) == 64


def test_dispatch_specialist_refuses_unauthorized_field():
    """R10 enforcement: source dict with an extra field fails at the
    assembler boundary, before the LLM is called."""
    with tempfile.TemporaryDirectory() as tmp:
        project_root = Path(tmp)
        (project_root / "agents").mkdir()
        (project_root / "agents" / "understander.md").write_text("# x\n")

        from agentxp.schemas.bundles import WarehouseProfile

        called = []
        def mock_llm(**kw):
            called.append(kw)
            return {}

        sources = {
            "warehouse_profile": WarehouseProfile(tables={}, flags=[]),
            "existing_semantic_models": [],
            "existing_metrics": [],
            "task": "draft_metrics",
            "intent": "test something",   # FORBIDDEN for understander
        }
        with pytest.raises(BundleAssemblyError):
            dispatch_specialist(
                role="understander",
                sources=sources,
                project_root=project_root,
                llm_caller=mock_llm,
            )
        assert called == []  # LLM was never invoked


def test_dispatch_specialist_raises_for_missing_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        project_root = Path(tmp)
        (project_root / "agents").mkdir()
        # No understander.md
        from agentxp.schemas.bundles import WarehouseProfile
        sources = {
            "warehouse_profile": WarehouseProfile(tables={}, flags=[]),
            "existing_semantic_models": [],
            "existing_metrics": [],
            "task": "draft_metrics",
        }
        with pytest.raises(FileNotFoundError):
            dispatch_specialist(
                role="understander",
                sources=sources,
                project_root=project_root,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Critic gate — require_critic_pass
# ─────────────────────────────────────────────────────────────────────────────


def test_require_critic_pass_allows_passing_judgment():
    require_critic_pass(judgment={"passed": True, "reasons": []})


def test_require_critic_pass_blocks_on_severity_block():
    with pytest.raises(ToolRefusal) as excinfo:
        require_critic_pass(judgment={
            "passed": False,
            "severity": "block",
            "reasons": [
                {"what": "no primary metric", "rule_violated": "R1"},
            ],
        })
    assert "R6" in str(excinfo.value)
    assert "R1" in str(excinfo.value)


def test_require_critic_pass_warn_does_not_raise():
    """warn severity surfaces to the user but does not block the commit
    at the tool layer — the orchestrator decides."""
    require_critic_pass(judgment={
        "passed": False,
        "severity": "warn",
        "reasons": [{"what": "MDE is unusually small but defensible"}],
    })


# ─────────────────────────────────────────────────────────────────────────────
# dispatch_critic — uses CriticBundle structure
# ─────────────────────────────────────────────────────────────────────────────


def test_dispatch_critic_blind_bundle_structure():
    """The critic dispatch assembles a CriticBundle (no producer_reasoning)."""
    with tempfile.TemporaryDirectory() as tmp:
        project_root = Path(tmp)
        (project_root / "agents").mkdir()
        (project_root / "agents" / "critic.md").write_text("# Critic\n")

        captured = {}

        def mock_llm(*, role, system_prompt_path, bundle):
            captured["bundle_fields"] = set(bundle.bundle.model_fields_set)
            return {"passed": True, "reasons": []}

        result = dispatch_critic(
            artifact_ref={"path": "brief.yaml", "sha256": "a" * 64, "kind": "brief"},
            artifact_payload={"hypothesis": "X"},
            claimed_scope={"claim": "tests X", "cites": []},
            cited_inputs=[],
            judging_mode="brief_consistency",
            project_root=project_root,
            llm_caller=mock_llm,
        )
        assert result["passed"] is True
        # The bundle contains exactly the fields the schema declares.
        assert "producer_reasoning" not in captured["bundle_fields"]
        assert "conversation_history" not in captured["bundle_fields"]
