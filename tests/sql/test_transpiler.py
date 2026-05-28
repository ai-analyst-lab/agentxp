"""Tests for agentxp.sql.transpiler: cross-dialect SQL with bounded dialects."""
from __future__ import annotations

import pytest

from agentxp.sql.transpiler import SUPPORTED_DIALECTS, TranspileError, transpile


def test_transpile_select_duckdb_to_snowflake():
    out = transpile("SELECT id, name FROM users", "duckdb", "snowflake")
    upper = out.upper()
    assert "SELECT" in upper
    assert "ID" in upper
    assert "NAME" in upper
    assert "USERS" in upper


def test_transpile_date_trunc():
    # DATE_TRUNC exists in both dialects; sqlglot should round-trip it.
    out = transpile(
        "SELECT DATE_TRUNC('day', ts) AS d FROM events", "duckdb", "snowflake"
    )
    assert "DATE_TRUNC" in out.upper()
    assert "TS" in out.upper()


def test_transpile_window_function():
    sql = (
        "SELECT user_id, "
        "ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY ts) AS rn "
        "FROM events"
    )
    out = transpile(sql, "duckdb", "snowflake")
    upper = out.upper()
    assert "ROW_NUMBER()" in upper
    assert "OVER" in upper
    assert "PARTITION BY" in upper
    assert "ORDER BY" in upper

    # And round-trips back without losing the window clause.
    back = transpile(out, "snowflake", "duckdb")
    assert "ROW_NUMBER()" in back.upper()
    assert "PARTITION BY" in back.upper()


def test_transpile_unsupported_dialect_raises():
    # mysql is a sqlglot-supported dialect but NOT in AgentXP v0.1's
    # SUPPORTED_DIALECTS set — must be rejected with ValueError.
    with pytest.raises(ValueError):
        transpile("SELECT 1", "mysql", "duckdb")
    with pytest.raises(ValueError):
        transpile("SELECT 1", "duckdb", "mysql")


def test_transpile_unparseable_raises():
    with pytest.raises(TranspileError):
        transpile("NOT VALID SQL @@@ ### ;;;", "duckdb", "snowflake")


def test_supported_dialects_set():
    assert SUPPORTED_DIALECTS == frozenset(
        {"duckdb", "snowflake", "bigquery", "databricks"}
    )


def test_transpile_to_databricks_window_function():
    sql = (
        "SELECT user_id, "
        "ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY ts) AS rn "
        "FROM events"
    )
    out = transpile(sql, "duckdb", "databricks")
    upper = out.upper()
    assert "ROW_NUMBER()" in upper
    assert "OVER" in upper
    assert "PARTITION BY" in upper
