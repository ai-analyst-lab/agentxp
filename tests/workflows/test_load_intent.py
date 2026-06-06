"""Smoke-test follow-up — load_intent() projects on-disk YAML to bundle shape.

The post-W6 smoke test (experiments/exp_1f51bcf6) surfaced that
``IntentText(**yaml.safe_load(intent.yaml))`` fails with
``Extra inputs are not permitted`` on ``schema_version`` and
``captured_by`` — the bundle type is narrower than the on-disk artifact
(R10: the specialist sees only declared fields; audit metadata stays on
disk). ``load_intent`` does the projection.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from agentxp.schemas.bundles import IntentText
from agentxp.workflows.design import allocate_experiment, load_intent, record_intent


def test_load_intent_produces_valid_bundle_and_audit(tmp_path: Path) -> None:
    exp_dir = allocate_experiment(tmp_path)
    intent_path = record_intent(
        exp_dir,
        intent_text="A clean intent for the projection test.",
        captured_by="shane@aieval.ai",
    )

    bundle, audit = load_intent(intent_path)

    # Bundle is the right type with the right fields
    assert isinstance(bundle, IntentText)
    assert bundle.text.startswith("A clean intent")
    assert isinstance(bundle.captured_at, datetime)
    assert bundle.captured_at.tzinfo is not None

    # Audit dict carries the on-disk metadata the bundle deliberately omits
    assert audit["schema_version"] == 1
    assert audit["captured_by"] == "shane@aieval.ai"


def test_load_intent_round_trips_through_recorded_yaml(tmp_path: Path) -> None:
    """A clean record → load round-trip preserves the text + timestamp."""
    exp_dir = allocate_experiment(tmp_path)
    record_intent(exp_dir, "text content here", "u@e.com")
    bundle, _ = load_intent(exp_dir / "intent.yaml")
    assert bundle.text.strip() == "text content here"


def test_naive_load_via_yaml_splat_still_fails_extra_fields(tmp_path: Path) -> None:
    """Regression assertion: the bundle stays narrow on purpose (R10).

    If a future change widens ``IntentText`` to admit ``schema_version`` and
    ``captured_by``, this test fails to prompt a deliberate review. The
    projection helper exists specifically so the bundle does not have to
    widen.
    """
    import yaml
    from pydantic import ValidationError

    exp_dir = allocate_experiment(tmp_path)
    intent_path = record_intent(exp_dir, "t", "u@e.com")
    raw = yaml.safe_load(intent_path.read_text())
    with pytest.raises(ValidationError):
        IntentText(**raw)


def test_load_intent_raises_on_non_mapping(tmp_path: Path) -> None:
    bad = tmp_path / "intent.yaml"
    bad.write_text("- just a list\n- not a mapping\n")
    with pytest.raises(ValueError):
        load_intent(bad)
