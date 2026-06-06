"""W1.8 — outcome_columns required-not-optional + completeness validator.

Layer 3d of the SQL safety pipeline (R11) consults
``BundleSemanticModel.outcome_columns`` to decide whether a query touches
outcome surfaces in design mode. Pre-W1.8 the field had a default of
``[]``, so a YAML author who forgot to declare it would silently fall
through to "no outcomes" and Layer 3d would admit queries it should
refuse. Post-W1.8 the field is required; missing it raises
ValidationError at load time, before the SQL safety pipeline ever runs.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agentxp.schemas.bundles import BundleSemanticModel


def test_missing_outcome_columns_refused() -> None:
    """A YAML without outcome_columns cannot construct a BundleSemanticModel."""
    with pytest.raises(ValidationError) as exc_info:
        BundleSemanticModel(name="x", primary_key="id", source_table="t")
    assert "outcome_columns" in str(exc_info.value)


def test_empty_outcome_columns_accepted() -> None:
    """Explicit empty list = "entity has no outcomes" is the safe declaration."""
    sm = BundleSemanticModel(
        name="user", primary_key="user_id", source_table="users", outcome_columns=[]
    )
    assert sm.outcome_columns == []


def test_outcome_columns_accepts_arm_style_declaration() -> None:
    sm = BundleSemanticModel(
        name="assignment",
        primary_key=["user_id", "experiment_id"],
        source_table="assignments",
        outcome_columns=["arm"],
    )
    assert sm.outcome_columns == ["arm"]


@pytest.mark.parametrize(
    "yaml_path",
    sorted(p for p in Path("semantic_models").glob("*.yaml") if not p.stem.startswith("_")),
    ids=lambda p: p.stem,
)
def test_every_on_disk_semantic_model_declares_outcome_columns(yaml_path: Path) -> None:
    """Repo-wide invariant: every shipped semantic model carries the field."""
    raw = yaml.safe_load(yaml_path.read_text())
    assert "outcome_columns" in raw, (
        f"{yaml_path.name} omits outcome_columns; Layer 3d cannot decide "
        f"whether queries against this entity touch outcomes (W1.8/R11)."
    )
    # And the schema accepts it.
    BundleSemanticModel(**raw)


def test_none_outcome_columns_refused() -> None:
    """Explicit None must also raise — only an empty list expresses "no outcomes"."""
    with pytest.raises(ValidationError):
        BundleSemanticModel(
            name="x", primary_key="id", source_table="t", outcome_columns=None  # type: ignore[arg-type]
        )
