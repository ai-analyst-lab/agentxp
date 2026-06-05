"""Tests for agentxp.workflows.resume (V14)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from agentxp.workflows.resume import classify, list_in_flight


def test_list_in_flight_returns_empty_when_no_experiments_dir():
    with tempfile.TemporaryDirectory() as tmp:
        assert list_in_flight(Path(tmp)) == []


def test_list_in_flight_skips_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "experiments").mkdir()
        (root / "experiments" / "exp_001").mkdir()
        # Stray file under experiments/ should be skipped
        (root / "experiments" / "not_a_dir.txt").write_text("x")
        snapshots = list_in_flight(root)
        assert len(snapshots) == 1
        assert snapshots[0].experiment_id == "exp_001"


def _snapshot(exp_dir: Path, **flags) -> "ExperimentSnapshot":
    """Build a minimal snapshot manually."""
    from agentxp.orchestrator.tools import ExperimentSnapshot
    defaults = dict(
        experiment_id=exp_dir.name,
        exp_dir=exp_dir,
        has_intent=False,
        has_brief=False,
        brief_sealed=False,
        has_analysis=False,
        has_interpretation=False,
        has_report=False,
    )
    defaults.update(flags)
    return ExperimentSnapshot(**defaults)


def test_classify_intent_only():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp)
        snap = _snapshot(exp, has_intent=True)
        assert classify(snap) == "intent_only"


def test_classify_hypothesis_drafted():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp)
        (exp / "hypothesis.yaml").write_text("x")
        snap = _snapshot(exp, has_intent=True)
        assert classify(snap) == "hypothesis_drafted"


def test_classify_brief_drafted():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp)
        snap = _snapshot(exp, has_intent=True, has_brief=True)
        assert classify(snap) == "brief_drafted"


def test_classify_brief_sealed():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp)
        snap = _snapshot(exp, has_intent=True, has_brief=True, brief_sealed=True)
        assert classify(snap) == "brief_sealed"


def test_classify_analysis_in_progress():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp)
        snap = _snapshot(
            exp, has_intent=True, has_brief=True,
            brief_sealed=True, has_analysis=True,
        )
        assert classify(snap) == "analysis_in_progress"


def test_classify_complete():
    with tempfile.TemporaryDirectory() as tmp:
        exp = Path(tmp)
        snap = _snapshot(
            exp, has_intent=True, has_brief=True,
            brief_sealed=True, has_analysis=True, has_report=True,
        )
        assert classify(snap) == "complete"
