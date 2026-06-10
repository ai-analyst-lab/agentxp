"""Tests for agentxp.workflows.design (V10)."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

import yaml

from agentxp.workflows.design import (
    allocate_experiment,
    check_power_feasibility,
    finalize_brief,
    record_intent,
    seal_and_commit_brief,
)


def _seed_brief(exp_dir: Path, **overrides) -> Path:
    """Write a minimal valid brief.yaml for finalize_brief tests."""
    brief = {
        "schema_version": 1,
        "primary_metric": "conversion_rate",
        "primary_metric_type": "proportion",
        "primary_direction": "higher_is_better",
        "baseline": 0.10,
        "mde_pct": 5.0,
        "primary_decision_rule": {
            "metric_name": "conversion_rate",
            "applies_to": "ci_lower_95",
            "threshold": 0.0,
            "direction": "above",
            "severity": "primary",
        },
    }
    brief.update(overrides)
    path = exp_dir / "brief.yaml"
    path.write_text(yaml.safe_dump(brief, sort_keys=False))
    return path


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


# ─────────────────────────────────────────────────────────────────────────────
# finalize_brief — stamps deterministic n_required + validates structured rule
# ─────────────────────────────────────────────────────────────────────────────


def test_finalize_brief_stamps_n_required_deterministically():
    """Two finalize_brief calls on the same baseline+mde must yield the same n."""
    with tempfile.TemporaryDirectory() as tmp:
        exp_a = allocate_experiment(Path(tmp), experiment_id="exp_a")
        exp_b = allocate_experiment(Path(tmp), experiment_id="exp_b")
        _seed_brief(exp_a, baseline=0.10, mde_pct=4.6)
        _seed_brief(exp_b, baseline=0.10, mde_pct=4.6)

        a = finalize_brief(exp_a)
        b = finalize_brief(exp_b)

        assert a["n_required"] == b["n_required"]
        assert a["n_required_total"] == b["n_required_total"]
        # Sanity: should be the order of magnitude the Run 1 critic verified.
        assert 50_000 < a["n_required"] < 200_000


def test_finalize_brief_stamps_default_alpha_and_power():
    with tempfile.TemporaryDirectory() as tmp:
        exp_dir = allocate_experiment(Path(tmp))
        _seed_brief(exp_dir)
        brief = finalize_brief(exp_dir)
        assert brief["alpha"] == 0.05
        assert brief["power"] == 0.80
        assert brief["n_required_computed_by"].endswith("power_proportion")


def test_finalize_brief_rejects_prose_decision_rule():
    """Free-text decision rules are no longer accepted."""
    with tempfile.TemporaryDirectory() as tmp:
        exp_dir = allocate_experiment(Path(tmp))
        _seed_brief(exp_dir, primary_decision_rule="ci_low > 0")
        with pytest.raises(ValueError, match="structured mapping"):
            finalize_brief(exp_dir)


def test_finalize_brief_rejects_malformed_decision_rule():
    with tempfile.TemporaryDirectory() as tmp:
        exp_dir = allocate_experiment(Path(tmp))
        _seed_brief(
            exp_dir,
            primary_decision_rule={
                "metric_name": "conversion_rate",
                # missing applies_to + direction + severity
                "threshold": 0.0,
            },
        )
        with pytest.raises(ValueError, match="DecisionRule validation"):
            finalize_brief(exp_dir)


def test_finalize_brief_rejects_missing_judgment_fields():
    with tempfile.TemporaryDirectory() as tmp:
        exp_dir = allocate_experiment(Path(tmp))
        brief_path = exp_dir / "brief.yaml"
        brief_path.write_text("primary_metric: x\nprimary_metric_type: proportion\n")
        with pytest.raises(ValueError, match="baseline"):
            finalize_brief(exp_dir)


def test_finalize_brief_supports_mean_metric():
    with tempfile.TemporaryDirectory() as tmp:
        exp_dir = allocate_experiment(Path(tmp))
        _seed_brief(
            exp_dir,
            primary_metric="revenue_per_user",
            primary_metric_type="mean",
            baseline=20.0,
            baseline_std=15.0,
            mde_pct=5.0,
        )
        brief = finalize_brief(exp_dir)
        assert brief["n_required"] > 0
        assert brief["n_required_computed_by"].endswith("power_mean")


def test_finalize_brief_overwrites_stale_n_required():
    """If the LLM left an n_required value behind, finalize overwrites it."""
    with tempfile.TemporaryDirectory() as tmp:
        exp_dir = allocate_experiment(Path(tmp))
        _seed_brief(exp_dir, n_required=42, n_required_total=84)
        brief = finalize_brief(exp_dir)
        assert brief["n_required"] != 42  # overwritten


# ─────────────────────────────────────────────────────────────────────────────
# seal_and_commit_brief — log-row-before-hash ordering + power feasibility
# ─────────────────────────────────────────────────────────────────────────────


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)


def _seal_fixture(root: Path):
    """git repo + finalized brief + metric YAML; returns (exp_dir, kwargs)."""
    from agentxp.schemas.brief_seal import ExpectedShape

    _git_init(root)
    exp_dir = allocate_experiment(root)
    _seed_brief(exp_dir)
    finalize_brief(exp_dir)
    metric_path = root / "metrics" / "conversion_rate.yaml"
    metric_path.parent.mkdir()
    metric_path.write_text("name: conversion_rate\ntype: proportion\n")
    kwargs = dict(
        metric_paths={"conversion_rate": metric_path},
        expected_shape=ExpectedShape(
            assignment_unit="user_id",
            arms=["control", "treatment"],
            expected_arm_count_ratio={"control": 0.5, "treatment": 0.5},
        ),
        sealed_by="test@test",
    )
    return exp_dir, kwargs


def test_seal_and_commit_brief_yields_verified_provenance():
    """The committed seal must verify — the log row lands BEFORE hashing."""
    from agentxp.render.provenance import RenderStatus, build_provenance_for_brief

    with tempfile.TemporaryDirectory() as tmp:
        exp_dir, kwargs = _seal_fixture(Path(tmp))
        seal_and_commit_brief(exp_dir, units_available=1_000_000, **kwargs)

        assert (exp_dir / "brief.sealed.yaml").exists()
        # The seal row is in log.md and included in design_chain_hash.
        assert "brief sealed by test@test" in (exp_dir / "log.md").read_text()
        status = build_provenance_for_brief(exp_dir, "design_brief")
        assert status == RenderStatus.VERIFIED


def test_seal_and_commit_brief_creates_git_commit():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        exp_dir, kwargs = _seal_fixture(root)
        seal_and_commit_brief(exp_dir, units_available=1_000_000, **kwargs)
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=root,
            check=True, capture_output=True, text=True,
        ).stdout
        assert "brief sealed" in log


def test_seal_refuses_infeasible_power_with_no_side_effects():
    with tempfile.TemporaryDirectory() as tmp:
        exp_dir, kwargs = _seal_fixture(Path(tmp))
        log_before = (exp_dir / "log.md").read_text()
        with pytest.raises(ValueError, match="power-feasibility"):
            seal_and_commit_brief(exp_dir, units_available=100, **kwargs)
        assert not (exp_dir / "brief.sealed.yaml").exists()
        assert (exp_dir / "log.md").read_text() == log_before


def test_check_power_feasibility_requires_finalized_brief():
    with pytest.raises(ValueError, match="finalize_brief"):
        check_power_feasibility({"baseline": 0.10, "mde_pct": 5.0}, 1_000_000)


def test_check_power_feasibility_message_is_math_rich():
    brief = {
        "n_required": 68_121, "n_required_total": 136_242,
        "alpha": 0.05, "power": 0.80, "mde_pct": 5.0,
    }
    with pytest.raises(ValueError) as exc:
        check_power_feasibility(brief, 50_000)
    msg = str(exc.value)
    assert "136,242" in msg
    assert "50,000" in msg
    assert "mde_pct" in msg  # suggests the feasible MDE
