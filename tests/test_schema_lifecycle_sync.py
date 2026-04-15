"""Sync check: Pydantic ExperimentStatus enum must match storage lifecycle.

The storage layer's ``ALL_STATES`` is the canonical source of truth for the
11-state experiment lifecycle. The ``ExperimentStatus`` enum in
``openxp.schemas.experiment`` is the Pydantic-validated surface used when
loading/serializing ``experiment.yaml``. Drift between the two silently breaks
``ExperimentConfig(**data)`` round-trips on any post-COLLECTING state.
"""

from __future__ import annotations

from openxp.schemas.experiment import ExperimentStatus
from openxp.storage.lifecycle import ALL_STATES


def test_experiment_status_enum_matches_lifecycle_states():
    enum_values = {member.value for member in ExperimentStatus}
    assert enum_values == set(ALL_STATES), (
        f"ExperimentStatus enum and storage.lifecycle.ALL_STATES are out of sync. "
        f"Enum only: {enum_values - set(ALL_STATES)}. "
        f"Lifecycle only: {set(ALL_STATES) - enum_values}."
    )


def test_experiment_status_enum_has_11_states():
    assert len(list(ExperimentStatus)) == 11
