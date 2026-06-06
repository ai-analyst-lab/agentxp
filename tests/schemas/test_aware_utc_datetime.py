"""W1.1 — AwareUtcDatetime closure test.

Naive datetime → ValidationError.
Aware non-UTC datetime → ValidationError.
Aware UTC datetime → accepted.
SealedBrief.sealed_at uses the canonical type.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ValidationError

from agentxp.schemas._types import AwareUtcDatetime
from agentxp.schemas.brief_seal import SealedBrief


class _Probe(BaseModel):
    ts: AwareUtcDatetime


def test_naive_datetime_refused() -> None:
    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValidationError) as exc_info:
        _Probe(ts=naive)
    assert "timezone-aware UTC" in str(exc_info.value)


def test_aware_non_utc_refused() -> None:
    eastern = timezone(timedelta(hours=-5))
    aware_est = datetime(2026, 1, 1, 12, 0, 0, tzinfo=eastern)
    with pytest.raises(ValidationError) as exc_info:
        _Probe(ts=aware_est)
    assert "timezone-aware UTC" in str(exc_info.value)


def test_aware_utc_accepted() -> None:
    utc_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    probe = _Probe(ts=utc_now)
    assert probe.ts == utc_now


def test_sealed_brief_uses_aware_utc_datetime() -> None:
    """The brief seal's `sealed_at` migration to AwareUtcDatetime works."""
    annotation = SealedBrief.model_fields["sealed_at"].annotation
    # AwareUtcDatetime is `Annotated[datetime, AfterValidator(_enforce_utc)]`;
    # pydantic unwraps the Annotated, so the field annotation is `datetime`
    # but the validator chain includes _enforce_utc — test by behavior.
    from agentxp.schemas.brief_seal import CohortDefinition, ExpectedShape

    with pytest.raises(ValidationError) as exc_info:
        SealedBrief(
            schema_version=1,
            brief={"hypothesis": "stub", "primary_metric": "stub"},
            design_chain_hash="0" * 64,
            metric_snapshot={},
            expected_shape=ExpectedShape(
                assignment_unit="user_id",
                arms=["control", "treatment"],
                expected_arm_count_ratio={"control": 0.5, "treatment": 0.5},
                cohort_definitions=[
                    CohortDefinition(name="all", definition="all assigned users"),
                ],
            ),
            sealed_at=datetime(2026, 1, 1, 12, 0, 0),  # naive
            sealed_by="ci@test",
            agentxp_version="0.0.0",
        )
    assert "timezone-aware UTC" in str(exc_info.value)
