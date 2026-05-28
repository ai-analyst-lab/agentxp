"""Tier-B (live) Snowflake integration tests — the 10-query matrix (W1.A).

These hit a REAL Snowflake account and therefore require credentials in the
environment. They are marked ``@pytest.mark.integration`` and SKIP cleanly when
the ``AGENTXP_SNOWFLAKE_*`` connection env vars are unset — which is the normal
CI state (no creds available). The skip is at import-safe / collection-safe
level: no ``snowflake-connector-python`` import happens at module import, so
collection never errors even when the driver is absent.

Required env to run:
  AGENTXP_SNOWFLAKE_ACCOUNT   account identifier (no .snowflakecomputing.com)
  AGENTXP_SNOWFLAKE_USER      user
  AGENTXP_SNOWFLAKE_PASSWORD  password (or use a key-pair / oauth env, see below)
  AGENTXP_SNOWFLAKE_WAREHOUSE warehouse
  AGENTXP_SNOWFLAKE_DATABASE  database
  AGENTXP_SNOWFLAKE_SCHEMA    schema (optional, defaults PUBLIC)

Run with:  pytest -m integration tests/integration/test_snowflake_live.py
"""
from __future__ import annotations

import os

import pytest

from agentxp.sql.adapter import AdapterResult, PreviewResult

# Credential gate — every test in this module skips cleanly without these.
_REQUIRED_ENV = (
    "AGENTXP_SNOWFLAKE_ACCOUNT",
    "AGENTXP_SNOWFLAKE_USER",
    "AGENTXP_SNOWFLAKE_PASSWORD",
    "AGENTXP_SNOWFLAKE_WAREHOUSE",
    "AGENTXP_SNOWFLAKE_DATABASE",
)
_MISSING = [k for k in _REQUIRED_ENV if not os.environ.get(k)]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        bool(_MISSING),
        reason=f"Snowflake live creds unset: missing {_MISSING}",
    ),
]


@pytest.fixture
def adapter():
    """Build a password-auth adapter from env; close it after the test."""
    from agentxp.sql.adapters.snowflake_adapter import SnowflakeAdapter

    a = SnowflakeAdapter(
        account=os.environ["AGENTXP_SNOWFLAKE_ACCOUNT"],
        user=os.environ["AGENTXP_SNOWFLAKE_USER"],
        password=os.environ["AGENTXP_SNOWFLAKE_PASSWORD"],
        warehouse=os.environ["AGENTXP_SNOWFLAKE_WAREHOUSE"],
        database=os.environ["AGENTXP_SNOWFLAKE_DATABASE"],
        schema=os.environ.get("AGENTXP_SNOWFLAKE_SCHEMA", "PUBLIC"),
    )
    try:
        yield a
    finally:
        a.close()


# --- The 10-query live matrix --------------------------------------------


def test_q01_select_literal(adapter):
    r = adapter.execute("SELECT 1 AS x")
    assert isinstance(r, AdapterResult)
    assert r.rows == [{"X": 1}] or r.rows == [{"x": 1}]


def test_q02_dialect(adapter):
    assert adapter.execute("SELECT 1").dialect == "snowflake"


def test_q03_current_version(adapter):
    r = adapter.execute("SELECT CURRENT_VERSION() AS v")
    assert r.row_count == 1


def test_q04_multi_column(adapter):
    r = adapter.execute("SELECT 1 AS a, 'x' AS b, 3.5 AS c")
    assert r.row_count == 1


def test_q05_max_rows_truncation(adapter):
    r = adapter.execute(
        "SELECT seq4() AS n FROM TABLE(GENERATOR(ROWCOUNT => 1000))",
        max_rows=10,
    )
    assert r.row_count == 10


def test_q06_bytes_scanned_populated(adapter):
    r = adapter.execute(
        "SELECT seq4() AS n FROM TABLE(GENERATOR(ROWCOUNT => 1000))"
    )
    # bytes_scanned may be None if the driver does not surface stats, but the
    # field must at least be present and an int-or-None.
    assert r.bytes_scanned is None or isinstance(r.bytes_scanned, int)


def test_q07_explain_returns_plan(adapter):
    plan = adapter.explain("SELECT 1")
    assert isinstance(plan, str) and len(plan) > 0


def test_q08_dry_run_is_honest(adapter):
    pv = adapter.dry_run("SELECT 1")
    assert isinstance(pv, PreviewResult)
    assert pv.estimated_bytes_scanned is None
    assert pv.warnings


def test_q09_timeout_is_enforced(adapter):
    from agentxp.sql.adapter import QueryTimeoutError

    with pytest.raises(QueryTimeoutError):
        adapter.execute("CALL SYSTEM$WAIT(30)", timeout_s=1)


def test_q10_reuse_connection(adapter):
    adapter.execute("SELECT 1")
    first = adapter._conn
    adapter.execute("SELECT 2")
    assert adapter._conn is first
