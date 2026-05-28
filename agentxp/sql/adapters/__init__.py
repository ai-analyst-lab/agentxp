"""Warehouse adapters for AgentXP v0.1.

Each module in this package implements the :class:`agentxp.sql.adapter.BaseAdapter`
Protocol for one warehouse. v0.1 ships DuckDB as the reference implementation;
Snowflake, BigQuery, and Databricks ship as stubs (full implementations land in
v0.1.1) so the dispatcher / connect wizard can resolve every supported dialect
string to a registered class and refuse cleanly with NotImplementedError rather
than ImportError.

``ADAPTER_REGISTRY`` maps a dialect string to its adapter class. Construct an
adapter by dialect with::

    cls = ADAPTER_REGISTRY["duckdb"]
    adapter = cls(file_path=...)
"""
from __future__ import annotations

from agentxp.sql.adapters.bigquery_adapter import BigQueryAdapter
from agentxp.sql.adapters.databricks_adapter import DatabricksAdapter
from agentxp.sql.adapters.duckdb_adapter import DuckDBAdapter
from agentxp.sql.adapters.snowflake_adapter import SnowflakeAdapter

#: Dialect string → adapter class. Keys mirror ``BaseAdapter.get_dialect()``.
ADAPTER_REGISTRY: dict[str, type] = {
    "duckdb": DuckDBAdapter,
    "snowflake": SnowflakeAdapter,
    "bigquery": BigQueryAdapter,
    "databricks": DatabricksAdapter,
}


__all__ = [
    "ADAPTER_REGISTRY",
    "BigQueryAdapter",
    "DatabricksAdapter",
    "DuckDBAdapter",
    "SnowflakeAdapter",
]
