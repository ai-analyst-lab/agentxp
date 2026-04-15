"""Tests for openxp.data.snowflake_loader.

All network calls are mocked — no real Snowflake connection is ever opened.
"""

from __future__ import annotations

import logging
import sys
from unittest import mock

import pandas as pd
import pytest

from openxp.data.snowflake_loader import (
    ENV_VAR_MAP,
    MAX_ROWS_DEFAULT,
    SnowflakeLoader,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_fake_cursor(rows, columns):
    cursor = mock.MagicMock()
    cursor.fetchall.return_value = rows
    cursor.fetchone.return_value = (len(rows),)
    cursor.description = [(c,) for c in columns]
    return cursor


def _make_fake_conn(cursor):
    conn = mock.MagicMock()
    conn.cursor.return_value = cursor
    return conn


def _install_fake_snowflake(monkeypatch, conn):
    """Install a stub ``snowflake.connector`` module that returns ``conn``."""
    fake_connector = mock.MagicMock()
    fake_connector.connect.return_value = conn
    fake_module = mock.MagicMock()
    fake_module.connector = fake_connector
    monkeypatch.setitem(sys.modules, "snowflake", fake_module)
    monkeypatch.setitem(sys.modules, "snowflake.connector", fake_connector)
    return fake_connector


# ---------------------------------------------------------------------------
# Construction + env var loading
# ---------------------------------------------------------------------------
class TestEnvVarLoading:
    def test_explicit_params_take_precedence(self, monkeypatch):
        for env in ENV_VAR_MAP.values():
            monkeypatch.delenv(env, raising=False)
        monkeypatch.setenv("OPENXP_SNOWFLAKE_ACCOUNT", "from-env")

        loader = SnowflakeLoader({"account": "explicit", "user": "u"})
        assert loader._connection_params["account"] == "explicit"
        assert loader._connection_params["user"] == "u"

    def test_env_vars_loaded_when_params_none(self, monkeypatch):
        for env in ENV_VAR_MAP.values():
            monkeypatch.delenv(env, raising=False)

        monkeypatch.setenv("OPENXP_SNOWFLAKE_ACCOUNT", "acc-123")
        monkeypatch.setenv("OPENXP_SNOWFLAKE_USER", "alice")
        monkeypatch.setenv("OPENXP_SNOWFLAKE_PASSWORD", "hunter2")
        monkeypatch.setenv("OPENXP_SNOWFLAKE_WAREHOUSE", "wh")
        monkeypatch.setenv("OPENXP_SNOWFLAKE_DATABASE", "db")
        monkeypatch.setenv("OPENXP_SNOWFLAKE_SCHEMA", "sc")

        loader = SnowflakeLoader()
        p = loader._connection_params
        assert p["account"] == "acc-123"
        assert p["user"] == "alice"
        assert p["password"] == "hunter2"
        assert p["warehouse"] == "wh"
        assert p["database"] == "db"
        assert p["schema"] == "sc"

    def test_empty_when_no_env_and_no_params(self, monkeypatch):
        for env in ENV_VAR_MAP.values():
            monkeypatch.delenv(env, raising=False)
        loader = SnowflakeLoader()
        assert loader._connection_params == {}


# ---------------------------------------------------------------------------
# Credential safety
# ---------------------------------------------------------------------------
class TestCredentialSafety:
    def test_safe_params_masks_password(self):
        raw = {"account": "a", "user": "u", "password": "hunter2"}
        safe = SnowflakeLoader._safe_params_for_log(raw)
        assert safe["password"] == "***"
        assert safe["account"] == "a"

    def test_password_never_logged_on_connect(self, monkeypatch, caplog):
        conn = _make_fake_conn(_make_fake_cursor([(1,)], ["n"]))
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader(
            {"account": "a", "user": "u", "password": "super-secret-123"}
        )
        with caplog.at_level(logging.DEBUG, logger="openxp.data.snowflake_loader"):
            loader._connect()

        for record in caplog.records:
            assert "super-secret-123" not in record.getMessage()
        loader.close()


# ---------------------------------------------------------------------------
# Query flow
# ---------------------------------------------------------------------------
class TestQueryFlow:
    def test_query_executes_and_returns_dataframe(self, monkeypatch):
        rows = [("u1", "control", 10.0), ("u2", "treatment", 12.5)]
        cursor = _make_fake_cursor(rows, ["user_id", "variant", "revenue"])
        # count guardrail query returns 2 rows
        cursor.fetchone.return_value = (2,)
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader({"account": "a", "user": "u", "password": "p"})
        df = loader.query("SELECT user_id, variant, revenue FROM t")

        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["user_id", "variant", "revenue"]
        assert len(df) == 2
        # Cursor executed at least twice: guardrail count + actual query.
        assert cursor.execute.call_count == 2
        loader.close()

    def test_query_rejects_empty_sql(self, monkeypatch):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="non-empty"):
            loader.query("")
        with pytest.raises(ValueError, match="non-empty"):
            loader.query("   ")

    def test_load_experiment_builds_select(self, monkeypatch):
        cursor = _make_fake_cursor(
            [("control", 1.0), ("treatment", 2.0)],
            ["variant", "revenue"],
        )
        cursor.fetchone.return_value = (2,)
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader({"account": "a", "user": "u"})
        df = loader.load_experiment(
            table="analytics.events",
            treatment_col="variant",
            metric_cols=["revenue"],
            where="ts > '2026-01-01'",
        )

        # Inspect the actual SQL issued (2nd call is the real query).
        executed_sql = [c.args[0] for c in cursor.execute.call_args_list]
        assert any(
            "SELECT variant, revenue FROM analytics.events" in s
            and "WHERE ts > '2026-01-01'" in s
            for s in executed_sql
        )
        assert len(df) == 2
        loader.close()

    def test_load_experiment_rejects_bad_identifier(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            loader.load_experiment(
                table="t; DROP TABLE users;--",
                treatment_col="variant",
                metric_cols=["revenue"],
            )

    def test_load_experiment_requires_metric_cols(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="non-empty list"):
            loader.load_experiment(
                table="t", treatment_col="variant", metric_cols=[]
            )


# ---------------------------------------------------------------------------
# ImportError path
# ---------------------------------------------------------------------------
class TestImportErrorPath:
    def test_import_error_points_to_extras(self, monkeypatch):
        # Remove any cached snowflake modules and make import fail.
        for mod in list(sys.modules):
            if mod == "snowflake" or mod.startswith("snowflake."):
                monkeypatch.delitem(sys.modules, mod, raising=False)

        real_import = __builtins__["__import__"] if isinstance(
            __builtins__, dict
        ) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name == "snowflake.connector" or name.startswith("snowflake"):
                raise ImportError("No module named 'snowflake'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)

        loader = SnowflakeLoader({"account": "a", "user": "u"})
        with pytest.raises(ImportError, match=r"openxp\[snowflake\]"):
            loader._connect()


# ---------------------------------------------------------------------------
# MCP mode
# ---------------------------------------------------------------------------
class TestMcpMode:
    def test_mcp_mode_returns_stub_and_logs(self, caplog):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with caplog.at_level(logging.INFO, logger="openxp.data.snowflake_loader"):
            df = loader.query("SELECT 1")

        assert isinstance(df, pd.DataFrame)
        assert df.empty
        assert any(
            "MCP mode" in r.getMessage() for r in caplog.records
        ), "Expected a log notice about MCP mode"

    def test_mcp_mode_blocks_direct_connect(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(RuntimeError, match="MCP mode"):
            loader._connect()


# ---------------------------------------------------------------------------
# Row count guardrail
# ---------------------------------------------------------------------------
class TestRowCountGuardrail:
    def test_rejects_over_limit(self, monkeypatch):
        cursor = _make_fake_cursor([], ["x"])
        cursor.fetchone.return_value = (MAX_ROWS_DEFAULT + 1,)
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader({"account": "a", "user": "u"})
        with pytest.raises(ValueError, match="guardrail"):
            loader.query("SELECT * FROM huge_table")
        loader.close()

    def test_force_bypasses_guardrail(self, monkeypatch):
        rows = [(1,)] * 3
        cursor = _make_fake_cursor(rows, ["x"])
        # If guardrail were checked it would return a huge number; force=True
        # should skip that path entirely.
        cursor.fetchone.return_value = (MAX_ROWS_DEFAULT + 9999,)
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader({"account": "a", "user": "u"})
        df = loader.query("SELECT x FROM huge_table", force=True)
        assert len(df) == 3
        # Exactly one execute call (the real query, not a count).
        assert cursor.execute.call_count == 1
        loader.close()

    def test_guardrail_skips_non_select(self, monkeypatch):
        cursor = _make_fake_cursor([], [])
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader({"account": "a", "user": "u"})
        loader.query("SHOW TABLES")
        # Only the actual SHOW ran; no count wrapper.
        assert cursor.execute.call_count == 1
        loader.close()

    def test_custom_max_rows(self, monkeypatch):
        cursor = _make_fake_cursor([], ["x"])
        cursor.fetchone.return_value = (500,)
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader(
            {"account": "a", "user": "u"}, max_rows=100
        )
        with pytest.raises(ValueError, match="500"):
            loader.query("SELECT * FROM t")
        loader.close()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------
class TestContextManager:
    def test_enter_exit_closes_conn(self, monkeypatch):
        cursor = _make_fake_cursor([(1,)], ["x"])
        cursor.fetchone.return_value = (1,)
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        with SnowflakeLoader({"account": "a", "user": "u"}) as loader:
            loader.query("SELECT 1 AS x")
            assert loader._conn is conn

        conn.close.assert_called_once()
        assert loader._conn is None

    def test_close_is_idempotent(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        loader.close()
        loader.close()  # second call must not raise
