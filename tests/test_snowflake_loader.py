"""Tests for agentxp.data.snowflake_loader.

All network calls are mocked — no real Snowflake connection is ever opened.
"""

from __future__ import annotations

import logging
import sys
from unittest import mock

import pandas as pd
import pytest

from agentxp.data.snowflake_loader import (
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
        monkeypatch.setenv("AGENTXP_SNOWFLAKE_ACCOUNT", "from-env")

        loader = SnowflakeLoader({"account": "explicit", "user": "u"})
        assert loader._connection_params["account"] == "explicit"
        assert loader._connection_params["user"] == "u"

    def test_env_vars_loaded_when_params_none(self, monkeypatch):
        for env in ENV_VAR_MAP.values():
            monkeypatch.delenv(env, raising=False)

        monkeypatch.setenv("AGENTXP_SNOWFLAKE_ACCOUNT", "acc-123")
        monkeypatch.setenv("AGENTXP_SNOWFLAKE_USER", "alice")
        monkeypatch.setenv("AGENTXP_SNOWFLAKE_PASSWORD", "hunter2")
        monkeypatch.setenv("AGENTXP_SNOWFLAKE_WAREHOUSE", "wh")
        monkeypatch.setenv("AGENTXP_SNOWFLAKE_DATABASE", "db")
        monkeypatch.setenv("AGENTXP_SNOWFLAKE_SCHEMA", "sc")

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
        assert safe["password"] == "[REDACTED]"
        assert safe["account"] == "a"

    def test_safe_params_masks_all_connector_secrets(self):
        # Regression: the loader once kept its own 4-key secret set that missed
        # private_key_file_pwd / client_secret / passcode / oauth_token, leaking
        # them to DEBUG logs. It now routes through the canonical redactor.
        raw = {
            "account": "a",
            "user": "u",
            "password": "pw",
            "private_key": b"DERBYTES",
            "private_key_file_pwd": "passphrase",
            "client_secret": "cs",
            "passcode": "123456",
            "oauth_token": "tok",
            "token": "tok2",
        }
        safe = SnowflakeLoader._safe_params_for_log(raw)
        for k in (
            "password",
            "private_key",
            "private_key_file_pwd",
            "client_secret",
            "passcode",
            "oauth_token",
            "token",
        ):
            assert safe[k] == "[REDACTED]", f"{k} not masked"
        assert safe["account"] == "a"
        assert safe["user"] == "u"

    def test_password_never_logged_on_connect(self, monkeypatch, caplog):
        conn = _make_fake_conn(_make_fake_cursor([(1,)], ["n"]))
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader(
            {"account": "a", "user": "u", "password": "super-secret-123"}
        )
        with caplog.at_level(logging.DEBUG, logger="agentxp.data.snowflake_loader"):
            loader._connect()

        for record in caplog.records:
            assert "super-secret-123" not in record.getMessage()
        loader.close()

    def test_password_not_in_exception_on_connect_failure(self, monkeypatch):
        # The Snowflake driver's connection errors routinely echo the conn
        # string (account/user/password). The loader must scrub it from the
        # exception it raises (line-18 docstring promise) while preserving the
        # original via the __cause__ chain for debugging.
        fake_connector = mock.MagicMock()
        leaky = Exception(
            "250001: could not connect: account=acme user=svc "
            "password=super-secret-123"
        )
        fake_connector.connect.side_effect = leaky
        fake_module = mock.MagicMock()
        fake_module.connector = fake_connector
        monkeypatch.setitem(sys.modules, "snowflake", fake_module)
        monkeypatch.setitem(sys.modules, "snowflake.connector", fake_connector)

        loader = SnowflakeLoader(
            {"account": "acme", "user": "svc", "password": "super-secret-123"}
        )
        with pytest.raises(RuntimeError) as ei:
            loader._connect()

        assert "super-secret-123" not in str(ei.value)
        assert "[REDACTED]" in str(ei.value)
        # The driver exception is still chained for a debugger.
        assert ei.value.__cause__ is leaky

    def test_password_not_in_exception_on_query_failure(self, monkeypatch):
        cursor = _make_fake_cursor([], [])
        # guardrail count returns small so we proceed to the real execute
        cursor.fetchone.return_value = (1,)
        cursor.execute.side_effect = Exception(
            "001003: SQL error; conn account=acme password=super-secret-123"
        )
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader(
            {"account": "acme", "user": "svc", "password": "super-secret-123"}
        )
        with pytest.raises(RuntimeError) as ei:
            loader.query("SELECT 1", force=True)

        assert "super-secret-123" not in str(ei.value)
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
        with pytest.raises(ImportError, match=r"agentxp\[snowflake\]"):
            loader._connect()


# ---------------------------------------------------------------------------
# MCP mode
# ---------------------------------------------------------------------------
class TestMcpMode:
    def test_mcp_mode_returns_stub_and_logs(self, caplog):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with caplog.at_level(logging.INFO, logger="agentxp.data.snowflake_loader"):
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


# ---------------------------------------------------------------------------
# Filters parameter (parameterized queries)
# ---------------------------------------------------------------------------
class TestFilters:
    def test_filters_builds_parameterized_query(self, monkeypatch):
        """filters= should build WHERE col = %s with bound params."""
        cursor = _make_fake_cursor(
            [("treatment", 5.0)],
            ["variant", "revenue"],
        )
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader({"account": "a", "user": "u"})
        df = loader.load_experiment(
            table="analytics.events",
            treatment_col="variant",
            metric_cols=["revenue"],
            filters={"platform": "ios", "country": "US"},
        )

        # Verify the SQL and params passed to cursor.execute
        call_args = cursor.execute.call_args
        executed_sql = call_args[0][0]
        bound_params = call_args[0][1]
        assert "WHERE platform = %s AND country = %s" in executed_sql
        assert bound_params == ["ios", "US"]
        assert len(df) == 1
        loader.close()

    def test_filters_empty_dict_skips_where(self, monkeypatch):
        """Empty filters dict should produce no WHERE clause."""
        cursor = _make_fake_cursor(
            [("control", 1.0)],
            ["variant", "revenue"],
        )
        cursor.fetchone.return_value = (1,)
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader({"account": "a", "user": "u"})
        loader.load_experiment(
            table="t",
            treatment_col="variant",
            metric_cols=["revenue"],
            filters={},
        )

        # The real query (2nd call) should not contain WHERE
        executed_sqls = [c.args[0] for c in cursor.execute.call_args_list]
        real_sql = executed_sqls[-1]
        assert "WHERE" not in real_sql
        loader.close()

    def test_filters_validates_column_names(self):
        """Filter keys must be valid identifiers."""
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            loader.load_experiment(
                table="t",
                treatment_col="variant",
                metric_cols=["revenue"],
                filters={"variant; DROP TABLE x": "bad"},
            )

    def test_filters_mcp_mode_returns_stub(self):
        """In MCP mode, filters path returns empty DataFrame."""
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        df = loader.load_experiment(
            table="t",
            treatment_col="variant",
            metric_cols=["revenue"],
            filters={"platform": "ios"},
        )
        assert isinstance(df, pd.DataFrame)
        assert df.empty


# ---------------------------------------------------------------------------
# where= deprecation warning
# ---------------------------------------------------------------------------
class TestWhereDeprecation:
    def test_where_emits_deprecation_warning(self, monkeypatch):
        cursor = _make_fake_cursor(
            [("control", 1.0)],
            ["variant", "revenue"],
        )
        cursor.fetchone.return_value = (1,)
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader({"account": "a", "user": "u"})
        with pytest.warns(DeprecationWarning, match="deprecated"):
            loader.load_experiment(
                table="t",
                treatment_col="variant",
                metric_cols=["revenue"],
                where="ts > '2026-01-01'",
            )
        loader.close()

    def test_where_still_works(self, monkeypatch):
        """Deprecated where= should still produce correct SQL."""
        cursor = _make_fake_cursor(
            [("control", 1.0)],
            ["variant", "revenue"],
        )
        cursor.fetchone.return_value = (1,)
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader({"account": "a", "user": "u"})
        with pytest.warns(DeprecationWarning):
            loader.load_experiment(
                table="t",
                treatment_col="variant",
                metric_cols=["revenue"],
                where="ts > '2026-01-01'",
            )

        executed_sqls = [c.args[0] for c in cursor.execute.call_args_list]
        assert any("WHERE ts > '2026-01-01'" in s for s in executed_sqls)
        loader.close()


# ---------------------------------------------------------------------------
# where + filters conflict
# ---------------------------------------------------------------------------
class TestWhereFiltersConflict:
    def test_both_filters_and_where_raises(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="Cannot specify both"):
            loader.load_experiment(
                table="t",
                treatment_col="variant",
                metric_cols=["revenue"],
                where="x = 1",
                filters={"y": 2},
            )


# ---------------------------------------------------------------------------
# SQL injection via identifiers
# ---------------------------------------------------------------------------
class TestIdentifierInjection:
    def test_evil_table_name_semicolon(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            loader.load_experiment(
                table="t; DROP TABLE users;--",
                treatment_col="variant",
                metric_cols=["revenue"],
            )

    def test_evil_table_name_drop(self):
        """Table name 'DROP' alone is technically valid regex, but
        'DROP TABLE x' is not (contains space)."""
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            loader.load_experiment(
                table="DROP TABLE users",
                treatment_col="variant",
                metric_cols=["revenue"],
            )

    def test_evil_table_name_comment(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            loader.load_experiment(
                table="t--comment",
                treatment_col="variant",
                metric_cols=["revenue"],
            )

    def test_evil_column_name_semicolon(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            loader.load_experiment(
                table="t",
                treatment_col="variant; DROP TABLE x",
                metric_cols=["revenue"],
            )

    def test_evil_column_name_in_metric_cols(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            loader.load_experiment(
                table="t",
                treatment_col="variant",
                metric_cols=["revenue; DELETE FROM t"],
            )

    def test_evil_column_name_union(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            loader.load_experiment(
                table="t",
                treatment_col="variant",
                metric_cols=["revenue UNION SELECT password FROM users"],
            )

    def test_evil_filter_key(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            loader.load_experiment(
                table="t",
                treatment_col="variant",
                metric_cols=["revenue"],
                filters={"1=1; --": "bad"},
            )

    def test_identifier_too_long(self):
        loader = SnowflakeLoader({"account": "a"}, mcp_mode=True)
        long_name = "a" * 129
        with pytest.raises(ValueError, match="exceeds 128 characters"):
            loader.load_experiment(
                table=long_name,
                treatment_col="variant",
                metric_cols=["revenue"],
            )

    def test_identifier_at_max_length_ok(self, monkeypatch):
        """128-char identifier should be accepted."""
        cursor = _make_fake_cursor([("c", 1.0)], ["variant", "revenue"])
        cursor.fetchone.return_value = (1,)
        conn = _make_fake_conn(cursor)
        _install_fake_snowflake(monkeypatch, conn)

        loader = SnowflakeLoader({"account": "a", "user": "u"})
        long_name = "a" * 128
        # Should not raise
        loader.load_experiment(
            table=long_name,
            treatment_col="variant",
            metric_cols=["revenue"],
        )
        loader.close()
