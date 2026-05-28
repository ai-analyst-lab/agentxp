"""Tests for ``openxp.schemas._versioning`` — the schema_version registry +
load-refusal helpers.

Closure invariants under test:

1. ``MAX_SUPPORTED`` has 16 rows (matches §1.7.6 table row-for-row).
2. Per-file pydantic ``schema_version`` defaults match the registry values
   (this is the load-bearing drift test for §1.8.6).
3. Load-refusal raises the named errors for too-new / too-old / missing.
4. Unknown file patterns are permissive (pass through without raising).

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §1.7.6, §1.8.6.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from openxp.schemas._versioning import (
    MAX_SUPPORTED,
    MIN_SUPPORTED,
    SchemaVersionMissing,
    SchemaVersionTooNew,
    SchemaVersionTooOld,
    check_schema_version,
)


# ──────────────────────────────────────────────────────────────────────────
# Registry shape.
# ──────────────────────────────────────────────────────────────────────────


def test_max_supported_has_16_rows() -> None:
    """§1.7.6 has 16 rows; the registry must match row-for-row."""
    assert len(MAX_SUPPORTED) == 16


def test_max_supported_canonical_anchors() -> None:
    """Hard-pinned anchor values from §1.8.6 (catch typos in version bumps)."""
    assert MAX_SUPPORTED["state.yaml"] == 3
    assert MAX_SUPPORTED["data_plan.yaml"] == 2
    assert MAX_SUPPORTED["experiment.yaml"] == 2
    assert MAX_SUPPORTED["metrics/*.yaml"] == 2
    assert MAX_SUPPORTED["report.json"] == 1
    assert MAX_SUPPORTED["queries/{ulid}.yaml"] == 1
    assert MAX_SUPPORTED["bundles/{agent}.ctx.yaml"] == 1
    assert MAX_SUPPORTED["bundles/{agent}.out.yaml"] == 1


def test_min_supported_all_ones() -> None:
    """v0.1 has no v0 grace period — every MIN_SUPPORTED row is 1."""
    assert set(MIN_SUPPORTED.values()) == {1}
    assert set(MIN_SUPPORTED.keys()) == set(MAX_SUPPORTED.keys())


# ──────────────────────────────────────────────────────────────────────────
# Cross-check: MAX_SUPPORTED ↔ per-file pydantic model defaults.
#
# Load-bearing: this catches §1.8.6 drift between the registry and the
# Literal[N] = N defaults baked into each pydantic model.
# ──────────────────────────────────────────────────────────────────────────


def test_max_supported_table_matches_per_file_models() -> None:
    """Each registry entry that maps to a shipped pydantic model has the same
    ``schema_version`` default as the model declares.

    Only the models shipped at W_pre1.10 build time are checked here:
    ``state.yaml`` (StateYaml), ``data_plan.yaml`` (DataPlanV2),
    ``report.json`` (Report), ``queries/{ulid}.yaml`` (QueryArtifact),
    ``bundles/profiler.out.yaml`` (ProfileReport, schema_version 1 = matches
    the ``bundles/{agent}.out.yaml`` registry row).

    Other registry rows (``experiment.yaml``, ``metrics/*.yaml``, etc.) point
    at pydantic models that ship in later W_pre1 tasks; this test should be
    extended to cover them as those models land.
    """
    from openxp.schemas.data_plan import DataPlanV2
    from openxp.schemas.profiler import ProfileReport
    from openxp.schemas.report import Report
    from openxp.schemas.state import StateYaml
    from openxp.sql.schema import QueryArtifact

    cross_check = {
        "state.yaml": StateYaml,
        "data_plan.yaml": DataPlanV2,
        "report.json": Report,
        "queries/{ulid}.yaml": QueryArtifact,
        "bundles/{agent}.out.yaml": ProfileReport,
    }

    for pattern, model in cross_check.items():
        assert pattern in MAX_SUPPORTED, f"missing registry row: {pattern!r}"
        instance = model.model_construct()
        # The schema_version Literal default is the canonical anchor; pydantic
        # exposes it via the model's default factory machinery, but the
        # simplest check is just to read the attribute off an instance.
        model_version = getattr(instance, "schema_version", None)
        registry_version = MAX_SUPPORTED[pattern]
        assert model_version == registry_version, (
            f"drift: {model.__name__}.schema_version={model_version!r} "
            f"but MAX_SUPPORTED[{pattern!r}]={registry_version!r}"
        )


# ──────────────────────────────────────────────────────────────────────────
# Load-refusal behaviour.
# ──────────────────────────────────────────────────────────────────────────


def test_too_new_raises() -> None:
    """A state.yaml with schema_version=99 must raise SchemaVersionTooNew."""
    with pytest.raises(SchemaVersionTooNew) as excinfo:
        check_schema_version(Path("state.yaml"), {"schema_version": 99})
    msg = str(excinfo.value)
    assert "newer OpenXP" in msg
    assert "pip install --upgrade openxp" in msg


def test_too_old_raises() -> None:
    """A state.yaml with schema_version=0 must raise SchemaVersionTooOld."""
    with pytest.raises(SchemaVersionTooOld) as excinfo:
        check_schema_version(Path("state.yaml"), {"schema_version": 0})
    msg = str(excinfo.value)
    assert "older OpenXP" in msg
    assert "openxp migrate state" in msg


def test_missing_raises() -> None:
    """A dict with no schema_version key must raise SchemaVersionMissing."""
    with pytest.raises(SchemaVersionMissing):
        check_schema_version(Path("state.yaml"), {"experiment_id": "abc"})


def test_non_integer_schema_version_raises_missing() -> None:
    """A non-int schema_version (str, float, bool) is treated as missing."""
    for bad in ("3", 3.0, True, None):
        with pytest.raises(SchemaVersionMissing):
            check_schema_version(Path("state.yaml"), {"schema_version": bad})


def test_unrecognized_pattern_returns_version_without_error() -> None:
    """File patterns not in the registry are permissive — return as-is."""
    result = check_schema_version(
        Path("not_a_known_file.txt"), {"schema_version": 42}
    )
    assert result == 42


# ──────────────────────────────────────────────────────────────────────────
# Happy paths across all 16 registry rows.
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,version",
    [
        (Path("experiments/exp1/state.yaml"), 3),
        (Path("experiments/exp1/data_plan.yaml"), 2),
        (Path("experiment.yaml"), 2),
        (Path("experiments/exp1/metrics/dau.yaml"), 2),
        (Path("semantic_models/users.yaml"), 1),
        (Path("fact_sources/checkout.yaml"), 1),
        (Path("assignments/treatment.yaml"), 1),
        (Path("decisions/2026-05-27.yaml"), 1),
        (Path("experiments/exp1/analyses/2026-05-27.json"), 1),
        (Path("experiments/exp1/interpretation.json"), 1),
        (Path("experiments/exp1/report.json"), 1),
        (Path("experiments/exp1/bundles/profiler.ctx.yaml"), 1),
        (Path("experiments/exp1/bundles/profiler.out.yaml"), 1),
        (Path("experiments/exp1/queries/01HXYZ.yaml"), 1),
        (Path("experiments/exp1/conversation.jsonl"), 1),
        (Path("experiments/exp1/log.jsonl"), 1),
    ],
)
def test_happy_path_each_pattern_matches(path: Path, version: int) -> None:
    """Every registry pattern matches its canonical version on a sample path."""
    assert check_schema_version(path, {"schema_version": version}) == version


def test_at_max_is_accepted() -> None:
    """schema_version == MAX_SUPPORTED is accepted (boundary)."""
    assert check_schema_version(Path("state.yaml"), {"schema_version": 3}) == 3


def test_at_min_is_accepted() -> None:
    """schema_version == MIN_SUPPORTED is accepted (boundary)."""
    assert check_schema_version(Path("state.yaml"), {"schema_version": 1}) == 1
