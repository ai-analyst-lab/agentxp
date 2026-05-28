"""Tier-B (live) Databricks integration tests — the 10-query matrix (W1.C).

These hit a REAL Databricks SQL warehouse and therefore require credentials in
the environment. They are marked ``@pytest.mark.integration`` and SKIP cleanly
when the ``DATABRICKS_*`` connection env vars are unset — which is the normal CI
state (no creds available). The skip is at import-safe / collection-safe level:
no ``databricks-sql-connector`` import happens at module import, so collection
never errors even when the driver is absent.

Required env to run (PAT auth):
  DATABRICKS_SERVER_HOSTNAME  e.g. adb-1234.5.azuredatabricks.net (no scheme)
  DATABRICKS_HTTP_PATH        e.g. /sql/1.0/warehouses/abc123
  DATABRICKS_ACCESS_TOKEN     personal access token (dapi...)
  DATABRICKS_CATALOG          Unity Catalog catalog (optional, e.g. samples)
  DATABRICKS_SCHEMA           schema (optional, e.g. nyctaxi)

Run with:  pytest -m integration tests/integration/test_databricks_live.py
"""
from __future__ import annotations

import os

import pytest

from agentxp.sql.adapter import AdapterResult, PreviewResult

# Credential gate — every test in this module skips cleanly without these.
_REQUIRED_ENV = (
    "DATABRICKS_SERVER_HOSTNAME",
    "DATABRICKS_HTTP_PATH",
    "DATABRICKS_ACCESS_TOKEN",
)
_MISSING = [k for k in _REQUIRED_ENV if not os.environ.get(k)]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        bool(_MISSING),
        reason=f"Databricks live creds unset: missing {_MISSING}",
    ),
]


@pytest.fixture
def adapter():
    """Build a PAT-auth adapter from env; close it after the test."""
    from agentxp.sql.adapters.databricks_adapter import DatabricksAdapter

    kwargs = dict(
        server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_ACCESS_TOKEN"],
    )
    if os.environ.get("DATABRICKS_CATALOG"):
        kwargs["catalog"] = os.environ["DATABRICKS_CATALOG"]
    if os.environ.get("DATABRICKS_SCHEMA"):
        kwargs["schema"] = os.environ["DATABRICKS_SCHEMA"]

    a = DatabricksAdapter(**kwargs)
    try:
        yield a
    finally:
        a.close()


# --- The 10-query live matrix --------------------------------------------


def test_q01_select_literal(adapter):
    r = adapter.execute("SELECT 1 AS x")
    assert isinstance(r, AdapterResult)
    assert r.rows == [{"x": 1}] or r.rows == [{"X": 1}]


def test_q02_dialect(adapter):
    assert adapter.execute("SELECT 1").dialect == "databricks"


def test_q03_current_version(adapter):
    r = adapter.execute("SELECT current_version() AS v")
    assert r.row_count == 1


def test_q04_multi_column(adapter):
    r = adapter.execute("SELECT 1 AS a, 'x' AS b, 3.5 AS c")
    assert r.row_count == 1


def test_q05_max_rows_truncation(adapter):
    r = adapter.execute(
        "SELECT id AS n FROM range(1000)",
        max_rows=10,
    )
    assert r.row_count == 10


def test_q06_bytes_scanned_is_none(adapter):
    # The connector does not surface scan stats — adapter sets None by contract.
    r = adapter.execute("SELECT id AS n FROM range(1000)")
    assert r.bytes_scanned is None


def test_q07_explain_returns_plan(adapter):
    plan = adapter.explain("SELECT 1")
    assert isinstance(plan, str) and len(plan) > 0


def test_q08_dry_run_is_honest(adapter):
    pv = adapter.dry_run("SELECT 1")
    assert isinstance(pv, PreviewResult)
    assert pv.estimated_bytes_scanned is None
    assert pv.warnings


def test_q09_three_level_unity_catalog_name(adapter):
    # samples.nyctaxi.trips is the canonical Unity Catalog sample table.
    r = adapter.execute("SELECT * FROM samples.nyctaxi.trips LIMIT 5")
    assert isinstance(r, AdapterResult)
    assert r.row_count <= 5


def test_q10_reuse_connection(adapter):
    adapter.execute("SELECT 1")
    first = adapter._conn
    adapter.execute("SELECT 2")
    assert adapter._conn is first
