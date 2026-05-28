"""Tests for the remaining v0.1 adapter stubs (Databricks).

This full implementation lands in v0.1.1. v0.1 ships a stub that satisfies the
:class:`agentxp.sql.adapter.BaseAdapter` Protocol shape (so the connect wizard
+ dispatcher can resolve it) but raises NotImplementedError on any actual
warehouse call. The Snowflake adapter (W1.A) and BigQuery adapter (W1.B) are
now real implementations, exercised in ``test_snowflake_adapter.py`` /
``test_bigquery_adapter.py``.
"""
from __future__ import annotations

import pytest

from agentxp.sql.adapters.databricks_adapter import DatabricksAdapter


def test_databricks_execute_raises_not_implemented():
    adapter = DatabricksAdapter(server_hostname="h", http_path="/p")
    with pytest.raises(NotImplementedError, match="v0.1.1"):
        adapter.execute("SELECT 1")


def test_databricks_get_dialect():
    assert DatabricksAdapter().get_dialect() == "databricks"
