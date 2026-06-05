"""Tests for agentxp.workflows.analyze (V11)."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from agentxp.schemas.brief_seal import (
    BriefSealMismatch,
    ExpectedShape,
    seal_brief,
)
from agentxp.workflows.analyze import verify_and_open


def _setup_sealed_brief(tmp: Path) -> tuple[Path, Path]:
    """Create a project_root + exp_dir with a sealed brief. Returns (project_root, brief_path)."""
    project_root = tmp
    exp_dir = project_root / "experiments" / "exp_test"
    exp_dir.mkdir(parents=True)
    chain = exp_dir / "log.md"
    chain.write_text("# log\n\n- entry\n")
    metrics_dir = project_root / "metrics"
    metrics_dir.mkdir()
    metric_a = metrics_dir / "conversion_rate.yaml"
    metric_a.write_text("name: conversion_rate\ntype: proportion\n")

    expected = ExpectedShape(
        assignment_unit="user_id",
        arms=["control", "treatment"],
        expected_arm_count_ratio={"control": 0.5, "treatment": 0.5},
    )

    sealed = seal_brief(
        brief_content={"hypothesis": "X", "primary_metric": "conversion_rate"},
        design_chain_path=chain,
        metric_paths={"conversion_rate": metric_a},
        expected_shape=expected,
        sealed_by="shane",
        agentxp_version="0.2.0",
        sealed_at=datetime.now(timezone.utc),
    )

    brief_path = exp_dir / "brief.sealed.yaml"
    # SealedBrief.model_dump_json + yaml.safe_load round-trip for storage.
    dumped = sealed.model_dump(mode="json")
    brief_path.write_text(yaml.safe_dump(dumped))
    return project_root, brief_path


def test_verify_and_open_returns_sealed_brief():
    with tempfile.TemporaryDirectory() as tmp:
        project_root, brief_path = _setup_sealed_brief(Path(tmp))
        sealed = verify_and_open(brief_path, project_root)
        assert sealed.sealed_by == "shane"
        assert "conversion_rate" in sealed.metric_snapshot


def test_verify_and_open_raises_on_chain_drift():
    with tempfile.TemporaryDirectory() as tmp:
        project_root, brief_path = _setup_sealed_brief(Path(tmp))
        # Drift the chain
        exp_dir = brief_path.parent
        (exp_dir / "log.md").write_text("# log\n\n- ENTRY CHANGED\n")
        with pytest.raises(BriefSealMismatch):
            verify_and_open(brief_path, project_root)


def test_verify_and_open_raises_on_metric_drift():
    with tempfile.TemporaryDirectory() as tmp:
        project_root, brief_path = _setup_sealed_brief(Path(tmp))
        # Drift the metric YAML
        (project_root / "metrics" / "conversion_rate.yaml").write_text(
            "name: conversion_rate\ntype: proportion\ndescription: edited\n"
        )
        with pytest.raises(BriefSealMismatch):
            verify_and_open(brief_path, project_root)


def test_verify_and_open_missing_brief_raises_file_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(FileNotFoundError):
            verify_and_open(Path(tmp) / "nope.yaml", Path(tmp))
