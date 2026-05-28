"""Tests for agentxp.sql.adapters.duckdb_adapter.DuckDBAdapter.

Verifies the §12 adapter contract against the DuckDB driver: protocol
conformance, in-memory + file-path connection modes, max_rows truncation,
EXPLAIN passthrough, no-free-dry-run preview, and connection lifecycle.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentxp.sql.adapter import (
    AdapterError,
    AdapterResult,
    BaseAdapter,
    PreviewResult,
)
from agentxp.sql.adapters.duckdb_adapter import DuckDBAdapter


def test_implements_base_adapter_protocol():
    adapter = DuckDBAdapter()
    assert isinstance(adapter, BaseAdapter)
    adapter.close()


def test_execute_simple_select_returns_adapter_result():
    adapter = DuckDBAdapter()
    try:
        result = adapter.execute("SELECT 1 AS x, 'alice' AS name")
        assert isinstance(result, AdapterResult)
        assert result.row_count == 1
        assert result.rows == [{"x": 1, "name": "alice"}]
        assert result.elapsed_seconds >= 0.0
    finally:
        adapter.close()


def test_execute_returns_duckdb_dialect():
    adapter = DuckDBAdapter()
    try:
        result = adapter.execute("SELECT 42 AS answer")
        assert result.dialect == "duckdb"
        assert adapter.get_dialect() == "duckdb"
    finally:
        adapter.close()


def test_in_memory_connection_when_file_path_none():
    adapter = DuckDBAdapter(file_path=None)
    try:
        result = adapter.execute("SELECT 1 AS x")
        assert result.row_count == 1
    finally:
        adapter.close()


def test_execute_against_attached_duckdb_file(tmp_path: Path):
    db_path = tmp_path / "warehouse.duckdb"

    # Use one adapter to seed the file with a table.
    seeder = DuckDBAdapter(file_path=db_path)
    try:
        seeder.execute(
            "CREATE TABLE events AS "
            "SELECT * FROM (VALUES (1, 'a'), (2, 'b'), (3, 'c')) "
            "AS t(id, label)"
        )
    finally:
        seeder.close()

    assert db_path.exists()

    # Re-open via a new adapter and read back.
    reader = DuckDBAdapter(file_path=db_path)
    try:
        result = reader.execute("SELECT * FROM events ORDER BY id")
        assert result.row_count == 3
        assert result.rows[0] == {"id": 1, "label": "a"}
        assert result.rows[-1] == {"id": 3, "label": "c"}
    finally:
        reader.close()


def test_max_rows_truncates_result():
    adapter = DuckDBAdapter()
    try:
        # range(0, 1000) -> 1000 rows
        result = adapter.execute("SELECT * FROM range(0, 1000)", max_rows=10)
        assert result.row_count == 10
        assert len(result.rows) == 10
    finally:
        adapter.close()


def test_explain_returns_string():
    adapter = DuckDBAdapter()
    try:
        plan = adapter.explain("SELECT 1 AS x")
        assert isinstance(plan, str)
        assert len(plan) > 0
    finally:
        adapter.close()


def test_dry_run_returns_preview_result_with_no_estimate_warning():
    adapter = DuckDBAdapter()
    try:
        pv = adapter.dry_run("SELECT 1 AS x")
        assert isinstance(pv, PreviewResult)
        assert pv.estimated_rows is None
        assert pv.estimated_bytes_scanned is None
        assert pv.estimated_cost_usd is None
        assert pv.warnings
        assert any("dry-run" in w.lower() for w in pv.warnings)
    finally:
        adapter.close()


def test_close_releases_connection():
    adapter = DuckDBAdapter()
    adapter.execute("SELECT 1")
    assert adapter._conn is not None
    adapter.close()
    assert adapter._conn is None
    # close is idempotent.
    adapter.close()
    assert adapter._conn is None


def test_multiple_execute_calls_reuse_connection():
    adapter = DuckDBAdapter()
    try:
        adapter.execute("SELECT 1")
        first_conn = adapter._conn
        assert first_conn is not None
        adapter.execute("SELECT 2")
        assert adapter._conn is first_conn
    finally:
        adapter.close()


def test_bytes_scanned_is_none_for_duckdb():
    adapter = DuckDBAdapter()
    try:
        result = adapter.execute("SELECT 1 AS x")
        assert result.bytes_scanned is None
    finally:
        adapter.close()


# ----------------------------------------------------------------------
# Credential-leakage bar (BLOCKER-1): the RAW driver exception must not be
# interpolated into the new query-path error message.
# ----------------------------------------------------------------------

_PLANTED = "password=pwd_LEAKED_9999"


class _BoomConn:
    """A fake DuckDB connection whose execute/fetchall raise with a planted
    secret in the message — the adapter must not echo it in the new exception."""

    def __init__(self, where: str):
        self._where = where  # "execute" | "explain"

    def execute(self, sql: str):
        if self._where == "explain" and not sql.upper().startswith("EXPLAIN"):
            return self  # only the EXPLAIN call should boom
        raise RuntimeError(f"duckdb backend died: {_PLANTED} in conn string")

    def fetchall(self):
        raise RuntimeError(f"duckdb backend died: {_PLANTED} in conn string")

    def close(self):
        pass


def test_planted_secret_in_driver_exc_never_leaks_on_execute(caplog):
    adapter = DuckDBAdapter()
    adapter._conn = _BoomConn("execute")
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.execute("SELECT 1")
    assert _PLANTED not in str(excinfo.value)
    assert "pwd_LEAKED_9999" not in str(excinfo.value)
    assert "pwd_LEAKED_9999" not in caplog.text
    assert excinfo.value.__cause__ is not None


def test_planted_secret_in_driver_exc_never_leaks_on_explain(caplog):
    adapter = DuckDBAdapter()
    adapter._conn = _BoomConn("explain")
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.explain("SELECT 1")
    assert _PLANTED not in str(excinfo.value)
    assert "pwd_LEAKED_9999" not in str(excinfo.value)
    assert "pwd_LEAKED_9999" not in caplog.text
    assert excinfo.value.__cause__ is not None
