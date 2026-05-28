"""Tests for the v0.1 Snowflake + BigQuery adapter stubs.

The full implementations land in v0.1.1. v0.1 ships stubs that satisfy the
:class:`agentxp.sql.adapter.BaseAdapter` Protocol shape (so the connect wizard
+ dispatcher can resolve them) but raise NotImplementedError on any actual
warehouse call.
"""
from __future__ import annotations

import pytest

from agentxp.sql.adapters.bigquery_adapter import BigQueryAdapter
from agentxp.sql.adapters.databricks_adapter import DatabricksAdapter
from agentxp.sql.adapters.snowflake_adapter import SnowflakeAdapter


def test_snowflake_execute_raises_not_implemented():
    adapter = SnowflakeAdapter(account="acct", user="u")
    with pytest.raises(NotImplementedError, match="v0.1.1"):
        adapter.execute("SELECT 1")


def test_snowflake_get_dialect():
    assert SnowflakeAdapter().get_dialect() == "snowflake"


def test_bigquery_execute_raises_not_implemented():
    adapter = BigQueryAdapter(project_id="p")
    with pytest.raises(NotImplementedError, match="v0.1.1"):
        adapter.execute("SELECT 1")


def test_bigquery_get_dialect():
    assert BigQueryAdapter().get_dialect() == "bigquery"


def test_databricks_execute_raises_not_implemented():
    adapter = DatabricksAdapter(server_hostname="h", http_path="/p")
    with pytest.raises(NotImplementedError, match="v0.1.1"):
        adapter.execute("SELECT 1")


def test_databricks_get_dialect():
    assert DatabricksAdapter().get_dialect() == "databricks"
