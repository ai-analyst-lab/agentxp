"""Cross-adapter error-mapping PARITY (Tier-A, always-on, NO network).

Each warehouse adapter already has its own file asserting that *it* maps an
auth failure to :class:`AuthExpiredError` and a timeout to
:class:`QueryTimeoutError`. But those tests live in separate modules and each
only exercises its own dialect — so nothing fails if a single adapter drifts.
A contributor who changes Databricks' ``_is_auth_error`` to raise a bare
``AdapterError`` (instead of the auth-specific subclass) would still see every
existing per-adapter test pass, because no test compares the three adapters
against one canonical mapping.

This module is that comparison. It drives all three warehouse adapters through
the SAME failure scenarios and asserts they converge on ONE canonical exception
type, so any single-adapter divergence breaks the build. It also re-asserts the
redaction bar across all three in one place: a secret planted in the raw driver
exception must never reach the raised message or the log.

Creds-free: no real secrets, no network. Each dialect's import boundary is
faked in-process by reusing the per-adapter fake module classes.
"""
from __future__ import annotations

import sys
import types

import pytest

from agentxp.sql.adapter import (
    AdapterError,
    AuthExpiredError,
    QueryTimeoutError,
)
from agentxp.sql.adapters.bigquery_adapter import BigQueryAdapter
from agentxp.sql.adapters.databricks_adapter import DatabricksAdapter
from agentxp.sql.adapters.snowflake_adapter import SnowflakeAdapter

# Reuse the fake import-boundary modules the per-adapter tests already define,
# so this parity suite stays in lockstep with the driver shapes those tests
# pin (it imports the fake CLASSES, not their pytest fixtures).
from tests.sql.test_bigquery_adapter import (
    _FakeBigQueryModule,
    _FakeServiceAccountModule,
)
from tests.sql.test_databricks_adapter import _FakeSqlModule
from tests.sql.test_snowflake_adapter import _FakeConnector

# A secret planted INSIDE the raw driver exception for the "leak" scenario. It
# is fake; it never authenticates anything. The bar: it must not survive into
# the AgentXP-raised message or the captured log.
_PLANTED = "password=pw_PARITY_LEAK_123"


def _install_snowflake(monkeypatch, scenario: str) -> SnowflakeAdapter:
    pkg = types.ModuleType("snowflake")
    connector = _FakeConnector()
    if scenario == "auth":
        connector.execute_behavior = "auth"
    elif scenario == "timeout":
        connector.execute_behavior = "timeout"
    elif scenario == "leak":
        connector.execute_behavior = "boom"
        connector.boom_message = f"connect string account=a {_PLANTED} rejected"
    pkg.connector = connector  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "snowflake", pkg)
    monkeypatch.setitem(sys.modules, "snowflake.connector", connector)
    return SnowflakeAdapter(account="a", user="u", password="hunter2")


def _install_databricks(monkeypatch, scenario: str) -> DatabricksAdapter:
    pkg = types.ModuleType("databricks")
    sql_mod = _FakeSqlModule()
    if scenario == "auth":
        sql_mod.execute_behavior = "auth"
    elif scenario == "timeout":
        sql_mod.execute_behavior = "timeout"
    elif scenario == "leak":
        sql_mod.execute_behavior = "boom"
        sql_mod.boom_message = f"backend rejected {_PLANTED} on host"
    pkg.sql = sql_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "databricks", pkg)
    monkeypatch.setitem(sys.modules, "databricks.sql", sql_mod)
    return DatabricksAdapter(
        server_hostname="adb-1.azuredatabricks.net",
        http_path="/sql/1.0/warehouses/abc",
        access_token="dapi_x",
    )


def _install_bigquery(monkeypatch, scenario: str) -> BigQueryAdapter:
    google_pkg = types.ModuleType("google")
    cloud_pkg = types.ModuleType("google.cloud")
    oauth2_pkg = types.ModuleType("google.oauth2")
    bq_mod = _FakeBigQueryModule()
    sa_mod = _FakeServiceAccountModule()
    if scenario == "auth":
        # BigQuery surfaces auth at query-submit time.
        bq_mod.query_behavior = "auth"
    elif scenario == "timeout":
        # …and timeout while materializing the job result.
        bq_mod.result_behavior = "timeout"
    elif scenario == "leak":
        bq_mod.query_behavior = "boom"
        bq_mod.boom_message = f"backend rejected {_PLANTED} on request"

    google_pkg.cloud = cloud_pkg  # type: ignore[attr-defined]
    google_pkg.oauth2 = oauth2_pkg  # type: ignore[attr-defined]
    cloud_pkg.bigquery = bq_mod  # type: ignore[attr-defined]
    oauth2_pkg.service_account = sa_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_pkg)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", bq_mod)
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2_pkg)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", sa_mod)
    return BigQueryAdapter(project="p")


# Every warehouse adapter that participates in the canonical mapping contract.
# DuckDB is local/embedded (no auth, no remote timeout class) and is excluded by
# design — add new remote adapters here so they inherit the parity bar.
_INSTALLERS = {
    "snowflake": _install_snowflake,
    "databricks": _install_databricks,
    "bigquery": _install_bigquery,
}


@pytest.mark.parametrize("dialect", sorted(_INSTALLERS))
def test_auth_failure_maps_to_auth_expired_across_adapters(dialect, monkeypatch):
    adapter = _INSTALLERS[dialect](monkeypatch, "auth")
    with pytest.raises(AdapterError) as excinfo:
        adapter.execute("SELECT 1")
    # Exact-type, not isinstance: a bare AdapterError (the parent) is the exact
    # regression this guards against — a classifier that stopped distinguishing
    # auth from generic failure. AuthExpiredError is the one canonical type all
    # adapters must agree on.
    assert type(excinfo.value) is AuthExpiredError, (
        f"{dialect} mapped an auth failure to "
        f"{type(excinfo.value).__name__}; expected AuthExpiredError "
        f"(canonical cross-adapter mapping)"
    )


@pytest.mark.parametrize("dialect", sorted(_INSTALLERS))
def test_timeout_maps_to_query_timeout_across_adapters(dialect, monkeypatch):
    adapter = _INSTALLERS[dialect](monkeypatch, "timeout")
    with pytest.raises(AdapterError) as excinfo:
        adapter.execute("SELECT 1")
    assert type(excinfo.value) is QueryTimeoutError, (
        f"{dialect} mapped a timeout to "
        f"{type(excinfo.value).__name__}; expected QueryTimeoutError "
        f"(canonical cross-adapter mapping)"
    )


@pytest.mark.parametrize("dialect", sorted(_INSTALLERS))
def test_planted_secret_never_leaks_across_adapters(dialect, monkeypatch, caplog):
    # A secret carried in the raw driver exception must not survive into the
    # AgentXP-raised message or the log, on ANY adapter. (Per-adapter files
    # already cover this; here it is one shared bar so a new adapter can't ship
    # without inheriting it.)
    adapter = _INSTALLERS[dialect](monkeypatch, "leak")
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.execute("SELECT 1")
    assert _PLANTED not in str(excinfo.value), f"{dialect} leaked secret in message"
    assert "pw_PARITY_LEAK_123" not in str(excinfo.value)
    assert "pw_PARITY_LEAK_123" not in caplog.text, f"{dialect} leaked secret to log"
    # The chained cause may still carry it (local debugging) — but it must be a
    # chained cause, not interpolated into our message.
    assert excinfo.value.__cause__ is not None
