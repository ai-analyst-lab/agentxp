"""T20/T21 — design-mode outcome-column rejection (Layer 3d, R11 wall).

The safety pipeline's ``mode`` parameter is keyword-only and required.
``mode="design"`` activates Layer 3d, which rejects any query that
references an outcome-bearing column. ``mode="analyze"`` skips Layer 3d
(the brief authorized the outcome read).

These tests assert the R11 architectural wall holds at the SQL layer:
the design verb cannot peek at variants, arms, or assignment outcomes
without an explicit, visible safety rule change here.
"""
from __future__ import annotations

import pytest

from agentxp.sql.safety import (
    DesignModePeekViolation,
    SafetyResult,
    layer_3d_design_mode_outcome_reject,
    run_pipeline,
)
from agentxp.sql.parser import parse_sql


# ─────────────────────────────────────────────────────────────────────────────
# mode is required — no default — bypassing is a TypeError, not a silent pass
# ─────────────────────────────────────────────────────────────────────────────


def test_mode_is_keyword_only_and_required():
    """run_pipeline raises TypeError when mode is not supplied. Discipline:
    callers cannot accidentally bypass R11 by forgetting the param."""
    with pytest.raises(TypeError):
        run_pipeline("SELECT * FROM t LIMIT 10", "duckdb", "preview")


def test_mode_is_keyword_only_not_positional():
    """mode cannot be passed positionally — keyword-only signature."""
    with pytest.raises(TypeError):
        run_pipeline("SELECT * FROM t LIMIT 10", "duckdb", "preview", "analyze")


# ─────────────────────────────────────────────────────────────────────────────
# Design mode REJECTS outcome-bearing column references
# ─────────────────────────────────────────────────────────────────────────────


_FORBIDDEN_COLUMNS = [
    "variant",
    "treatment",
    "treatment_group",
    "arm",
    "assigned_arm",
    "exposure_arm",
    "experiment_arm",
    "cohort_assignment",
    "bucket",
]


@pytest.mark.parametrize("col", _FORBIDDEN_COLUMNS)
def test_design_mode_rejects_outcome_column_in_select(col):
    """Each forbidden column triggers DesignModePeekViolation in design mode."""
    with pytest.raises(DesignModePeekViolation) as excinfo:
        run_pipeline(
            f"SELECT {col} FROM assignments LIMIT 10",
            "duckdb",
            "preview",
            mode="design",
        )
    assert col in str(excinfo.value)
    assert "design mode" in str(excinfo.value).lower()


@pytest.mark.parametrize("col", _FORBIDDEN_COLUMNS)
def test_design_mode_rejects_outcome_column_in_where(col):
    """Forbidden column in a WHERE filter is still detected."""
    with pytest.raises(DesignModePeekViolation):
        run_pipeline(
            f"SELECT user_id FROM assignments WHERE {col} = 'treatment' LIMIT 10",
            "duckdb",
            "preview",
            mode="design",
        )


def test_design_mode_rejects_case_insensitive():
    """Column matching is case-insensitive — uppercase doesn't bypass."""
    with pytest.raises(DesignModePeekViolation):
        run_pipeline(
            "SELECT VARIANT FROM assignments LIMIT 10",
            "duckdb",
            "preview",
            mode="design",
        )
    with pytest.raises(DesignModePeekViolation):
        run_pipeline(
            "SELECT Variant FROM assignments LIMIT 10",
            "duckdb",
            "preview",
            mode="design",
        )


def test_design_mode_rejects_via_alias_source():
    """Aliasing the outcome column doesn't bypass — the underlying
    reference is still detected."""
    with pytest.raises(DesignModePeekViolation):
        run_pipeline(
            "SELECT variant AS v FROM assignments LIMIT 10",
            "duckdb",
            "preview",
            mode="design",
        )


def test_design_mode_rejects_in_join_condition():
    """Outcome column referenced in JOIN ON clause triggers rejection."""
    with pytest.raises(DesignModePeekViolation):
        run_pipeline(
            "SELECT u.user_id FROM users u "
            "JOIN assignments a ON u.user_id = a.user_id "
            "WHERE a.bucket = 0 LIMIT 10",
            "duckdb",
            "preview",
            mode="design",
        )


def test_design_mode_rejects_in_group_by():
    """GROUP BY on outcome column triggers rejection."""
    with pytest.raises(DesignModePeekViolation):
        run_pipeline(
            "SELECT count(*) FROM assignments GROUP BY variant LIMIT 10",
            "duckdb",
            "preview",
            mode="design",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Design mode ALLOWS non-outcome queries
# ─────────────────────────────────────────────────────────────────────────────


def test_design_mode_allows_user_table_query():
    """Querying the user table for design-mode purposes (e.g. assignment
    surface sizing) is allowed."""
    r = run_pipeline(
        "SELECT user_id, signup_date FROM users LIMIT 10",
        "duckdb",
        "preview",
        mode="design",
    )
    assert isinstance(r, SafetyResult)


def test_design_mode_allows_shape_probe():
    """Counting users in segments to size the assignment surface — no
    outcome columns referenced — passes design mode."""
    r = run_pipeline(
        "SELECT segment, count(*) FROM users GROUP BY segment LIMIT 100",
        "duckdb",
        "preview",
        mode="design",
    )
    assert isinstance(r, SafetyResult)


# ─────────────────────────────────────────────────────────────────────────────
# Analyze mode ALLOWS outcome-bearing column references
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("col", _FORBIDDEN_COLUMNS)
def test_analyze_mode_allows_outcome_columns(col):
    """In analyze mode (which only opens against a sealed brief), the SQL
    layer permits the outcome columns the brief authorized."""
    r = run_pipeline(
        f"SELECT {col}, count(*) FROM assignments GROUP BY {col} LIMIT 100",
        "duckdb",
        "preview",
        mode="analyze",
    )
    assert isinstance(r, SafetyResult)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3d direct — unit-level test bypassing run_pipeline
# ─────────────────────────────────────────────────────────────────────────────


def test_layer_3d_direct_call_rejects():
    """The layer function rejects an outcome reference directly."""
    tree = parse_sql("SELECT variant FROM assignments", "duckdb")
    with pytest.raises(DesignModePeekViolation):
        layer_3d_design_mode_outcome_reject(tree)


def test_layer_3d_direct_call_passes_clean_query():
    """The layer function returns None (no raise) on a clean query."""
    tree = parse_sql("SELECT user_id FROM users", "duckdb")
    result = layer_3d_design_mode_outcome_reject(tree)
    assert result is None
