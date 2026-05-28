"""Tests for the 5-layer SQL safety pipeline (§11)."""
from __future__ import annotations

import pytest

from agentxp.sql.safety import (
    DenyListViolation,
    DialectHazardViolation,
    ReadOnlyViolation,
    SafetyResult,
    UnparseableSQL,
    assert_no_dialect_hazard,
    layer_3a_assert_single_adapter,
    layer_4_enforce_resource_bounds,
    run_pipeline,
)
from agentxp.sql.parser import parse_sql


# ──────────────────────────────────────────────────────────────────────────
# Layer 2 — read-only allowed shapes
# ──────────────────────────────────────────────────────────────────────────


def test_read_only_allows_select():
    r = run_pipeline("SELECT * FROM t LIMIT 10", "duckdb", "preview")
    assert isinstance(r, SafetyResult)
    assert r.layers_passed == [1, 2, 3, 4]


def test_read_only_allows_explain():
    r = run_pipeline("EXPLAIN SELECT * FROM t", "duckdb", "preview")
    assert isinstance(r, SafetyResult)
    assert "EXPLAIN" in r.sql_validated.upper()


def test_read_only_allows_cte():
    r = run_pipeline(
        "WITH x AS (SELECT 1 AS n) SELECT * FROM x", "duckdb", "preview"
    )
    assert r.layers_passed == [1, 2, 3, 4]


# ──────────────────────────────────────────────────────────────────────────
# Layer 2 — write / DDL rejection
# ──────────────────────────────────────────────────────────────────────────


def test_read_only_blocks_delete():
    with pytest.raises(ReadOnlyViolation):
        run_pipeline("DELETE FROM t WHERE id = 1", "duckdb", "preview")


def test_read_only_blocks_drop():
    with pytest.raises(ReadOnlyViolation):
        run_pipeline("DROP TABLE t", "duckdb", "preview")


def test_read_only_blocks_update():
    with pytest.raises(ReadOnlyViolation):
        run_pipeline("UPDATE t SET x = 1", "duckdb", "preview")


def test_read_only_blocks_insert():
    with pytest.raises(ReadOnlyViolation):
        run_pipeline("INSERT INTO t VALUES (1)", "duckdb", "preview")


def test_read_only_blocks_truncate():
    with pytest.raises(ReadOnlyViolation):
        run_pipeline("TRUNCATE TABLE t", "duckdb", "preview")


def test_read_only_blocks_merge():
    with pytest.raises(ReadOnlyViolation):
        run_pipeline(
            "MERGE INTO t USING s ON t.id = s.id "
            "WHEN MATCHED THEN UPDATE SET x = 1",
            "snowflake",
            "preview",
        )


def test_read_only_blocks_create():
    with pytest.raises(ReadOnlyViolation):
        run_pipeline("CREATE TABLE t (x INT)", "duckdb", "preview")


def test_read_only_blocks_alter():
    with pytest.raises(ReadOnlyViolation):
        run_pipeline("ALTER TABLE t ADD COLUMN x INT", "duckdb", "preview")


# ──────────────────────────────────────────────────────────────────────────
# Layer 3c — deny-list functions
# ──────────────────────────────────────────────────────────────────────────


def test_deny_list_blocks_pg_sleep():
    with pytest.raises(DenyListViolation):
        run_pipeline("SELECT pg_sleep(60)", "postgres", "preview")


def test_deny_list_blocks_exec():
    with pytest.raises(DenyListViolation):
        run_pipeline("SELECT exec('drop table t')", "duckdb", "preview")


def test_deny_list_blocks_system_wait():
    with pytest.raises(DenyListViolation):
        run_pipeline("SELECT SYSTEM$WAIT(60)", "snowflake", "preview")


# ──────────────────────────────────────────────────────────────────────────
# Layer 4 — resource bounds
# ──────────────────────────────────────────────────────────────────────────


def test_resource_bounds_injects_limit():
    r = run_pipeline("SELECT * FROM t", "duckdb", "preview")
    assert "LIMIT 1000" in r.sql_validated.upper()


def test_resource_bounds_caps_existing_limit():
    r = run_pipeline("SELECT * FROM t LIMIT 10000", "duckdb", "preview")
    # Existing 10k > preview cap (1k) → replaced.
    assert "LIMIT 1000" in r.sql_validated.upper()
    assert "10000" not in r.sql_validated


def test_resource_bounds_preserves_smaller_limit():
    r = run_pipeline("SELECT * FROM t LIMIT 50", "duckdb", "preview")
    assert "LIMIT 50" in r.sql_validated.upper()


def test_resource_bounds_profile_purpose_has_larger_cap():
    # profile cap is 100k; an existing LIMIT 50_000 should be preserved.
    r = run_pipeline("SELECT * FROM t LIMIT 50000", "duckdb", "profile")
    assert "LIMIT 50000" in r.sql_validated.upper()


# ──────────────────────────────────────────────────────────────────────────
# Orchestrator — happy path + parse failure + Layer 3a no-op
# ──────────────────────────────────────────────────────────────────────────


def test_run_pipeline_happy_path():
    r = run_pipeline(
        "SELECT id, value FROM events WHERE value > 0 LIMIT 100",
        "duckdb",
        "preview",
    )
    assert r.layers_passed == [1, 2, 3, 4]
    assert r.sql_validated  # non-empty
    assert "LIMIT 100" in r.sql_validated.upper()


def test_run_pipeline_unparseable_raises():
    with pytest.raises(UnparseableSQL):
        run_pipeline("SELECT FROM WHERE", "duckdb", "preview")


def test_layer_3a_no_op_without_config():
    tree = parse_sql("SELECT * FROM t", "duckdb")
    # config=None → no raise even with multi-adapter-looking text elsewhere.
    layer_3a_assert_single_adapter(tree, config=None)


# ──────────────────────────────────────────────────────────────────────────
# Layer 4 directly — unit-level (no orchestrator)
# ──────────────────────────────────────────────────────────────────────────


def test_layer_4_direct_injects_limit():
    tree = parse_sql("SELECT * FROM t", "duckdb")
    new_tree = layer_4_enforce_resource_bounds(tree, purpose="preview")
    assert "LIMIT 1000" in new_tree.sql().upper()


# ──────────────────────────────────────────────────────────────────────────
# Dialect-hazard guard (recursive CTE → databricks)
# ──────────────────────────────────────────────────────────────────────────


_RECURSIVE_CTE = (
    "WITH RECURSIVE t(n) AS ("
    "SELECT 1 UNION ALL SELECT n + 1 FROM t WHERE n < 5"
    ") SELECT * FROM t"
)


def test_recursive_cte_rejected_for_databricks():
    with pytest.raises(DialectHazardViolation):
        run_pipeline(_RECURSIVE_CTE, "databricks", "preview")


def test_recursive_cte_allowed_for_duckdb():
    # duckdb supports recursive CTEs; the hazard guard must not fire. (The
    # arithmetic in the recursive body trips Layer 3c's allowlist, which is a
    # separate concern — so assert the guard itself is a no-op here.)
    tree = parse_sql(_RECURSIVE_CTE, "duckdb")
    assert_no_dialect_hazard(tree, "duckdb")  # no raise


def test_non_recursive_cte_allowed_for_databricks():
    r = run_pipeline(
        "WITH t AS (SELECT 1 AS n) SELECT * FROM t", "databricks", "preview"
    )
    assert isinstance(r, SafetyResult)


def test_assert_no_dialect_hazard_noop_for_other_dialects():
    tree = parse_sql(_RECURSIVE_CTE, "duckdb")
    # snowflake/bigquery support recursive CTEs — explicit no-op.
    assert_no_dialect_hazard(tree, "snowflake")
    assert_no_dialect_hazard(tree, "bigquery")
