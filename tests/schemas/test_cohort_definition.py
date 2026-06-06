"""W1.3 — ExpectedShape.cohort_definitions promoted to list[CohortDefinition].

Pre-W1.3 the field was list[str], forcing callers to flatten dict cohorts
to "name: definition" strings at seal time (DIAGNOSTIC §B.2 #6). The
structured form lets the analyzer match cohort definitions against
warehouse rows at open time without lossy round-tripping.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentxp.schemas.brief_seal import CohortDefinition, ExpectedShape


def test_cohort_definition_requires_name_and_definition() -> None:
    with pytest.raises(ValidationError):
        CohortDefinition(name="")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        CohortDefinition(name="all", definition="")
    cd = CohortDefinition(name="all", definition="all assigned users")
    assert cd.name == "all"
    assert cd.definition == "all assigned users"


def test_expected_shape_accepts_structured_cohorts() -> None:
    es = ExpectedShape(
        assignment_unit="user_id",
        arms=["control", "treatment"],
        expected_arm_count_ratio={"control": 0.5, "treatment": 0.5},
        cohort_definitions=[
            CohortDefinition(
                name="all_assigned",
                definition=(
                    "Users in assignment with experiment_id = 'exp_X' and "
                    "arm in ('control', 'treatment'); first exposure at "
                    "first page_event event_name = 'product_view'."
                ),
            ),
        ],
    )
    assert len(es.cohort_definitions) == 1
    assert es.cohort_definitions[0].name == "all_assigned"


def test_expected_shape_rejects_bare_string_cohorts() -> None:
    """Post-W1.3 the bare-string convention is gone; callers must pass CohortDefinitions."""
    with pytest.raises(ValidationError):
        ExpectedShape(
            assignment_unit="user_id",
            arms=["control", "treatment"],
            expected_arm_count_ratio={"control": 0.5, "treatment": 0.5},
            cohort_definitions=["a stringified cohort"],  # type: ignore[list-item]
        )


def test_expected_shape_forbids_extra_fields_on_cohort() -> None:
    """R10 — extra="forbid" prevents the orchestrator from sneaking fields through."""
    with pytest.raises(ValidationError):
        CohortDefinition(
            name="all", definition="all assigned",
            comment="some extra prose",  # type: ignore[call-arg]
        )
