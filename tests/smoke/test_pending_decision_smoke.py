"""Track D — PendingDecisionKind plumbing smoke tests.

Every one of the 14 locked :class:`PendingDecisionKind` values must
round-trip through ``state.yaml.pending_decision`` (build → write → read →
validate) — except ``CONFIRM_HYPOTHESIS``, which is v0.1-reserved and MUST
raise on construction.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §1.8.1 / §6.4.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from openxp.orchestrator.store import StateStore
from openxp.schemas.state import (
    PendingDecision,
    PendingDecisionKind,
    Stage,
    StateYaml,
    V01_RESERVED_PENDING_DECISION_KINDS,
)


# Sanity invariant: the enum is exactly 14 values (§1.8.1 lock).
def test_pending_decision_kind_has_exactly_14_values() -> None:
    assert len(list(PendingDecisionKind)) == 14, (
        f"PendingDecisionKind must lock at 14 values; got {len(list(PendingDecisionKind))}"
    )


def test_pending_decision_kind_reserved_v01_blocks_emission() -> None:
    """§6.4: ``CONFIRM_HYPOTHESIS`` is reserved-not-emitted in v0.1."""
    assert PendingDecisionKind.CONFIRM_HYPOTHESIS in V01_RESERVED_PENDING_DECISION_KINDS
    with pytest.raises(ValueError, match="reserved"):
        PendingDecision(
            kind=PendingDecisionKind.CONFIRM_HYPOTHESIS,
            opened_at=datetime.now(timezone.utc),
            prompt_to_user="should never be emitted",
        )


# All 14 PendingDecisionKind values, minus the reserved one (which has its
# own dedicated test above).
_EMITTABLE_KINDS = [
    kind for kind in PendingDecisionKind
    if kind not in V01_RESERVED_PENDING_DECISION_KINDS
]


@pytest.mark.parametrize("kind", _EMITTABLE_KINDS, ids=lambda k: k.value)
def test_pending_decision_kind_roundtrips_through_state_yaml(
    kind: PendingDecisionKind, fake_exp_dir: Path
) -> None:
    """For every emittable kind: build → write → read → validate."""
    state = StateYaml(
        experiment_id=fake_exp_dir.name,
        current_stage=Stage.BRIEF_DRAFTED,
        pending_decision=PendingDecision(
            kind=kind,
            opened_at=datetime.now(timezone.utc),
            prompt_to_user=f"smoke test for {kind.value}",
            options=["yes", "no"],
        ),
    )
    store = StateStore(fake_exp_dir / "state.yaml")
    store.write(state)

    reread = store.read()
    assert reread.pending_decision is not None
    assert reread.pending_decision.kind == kind
    # On-disk YAML carries the snake_case value.
    raw = yaml.safe_load(store.path.read_text())
    assert raw["pending_decision"]["kind"] == kind.value
