"""
OpenXP data layer.

Data-agnostic loaders and schema discovery. Nothing in this module hardcodes
column names or file paths — the discovery protocol inspects real data at
runtime and reports what it found.

Public API:

    from openxp.data import load_data, discover_schema, CSVLoader, DuckDBLoader

``load_data(path)`` is the one-shot convenience wrapper. Use the loader
classes directly when you need per-row streaming, chunked loads, or explicit
connection management.
"""

from __future__ import annotations

import os

from openxp.data.base import DataSource, LoadResult, SchemaDiscovery
from openxp.data.csv_loader import CSVLoader
from openxp.data.discovery import discover_schema
from openxp.data.duckdb_loader import DuckDBLoader


def load_data(path: str, **kwargs) -> LoadResult:
    """Load an experiment dataset from a filesystem path.

    Routes to ``CSVLoader`` for ``.csv`` files and ``DuckDBLoader`` for
    ``.duckdb`` / ``.db`` files. Anything else raises ``ValueError``.

    Args:
        path: file path to a CSV or DuckDB database.
        **kwargs: forwarded to the underlying loader's ``load`` method.

    Returns:
        ``LoadResult`` with a pandas DataFrame and metadata.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return CSVLoader().load(path, **kwargs)
    if ext in (".duckdb", ".db"):
        table = kwargs.pop("table", None)
        treatment_col = kwargs.pop("treatment_col", None)
        if table is None or treatment_col is None:
            raise ValueError(
                "DuckDB loads require 'table' and 'treatment_col' kwargs."
            )
        loader = DuckDBLoader().connect(path)
        return loader.load_experiment(table, treatment_col=treatment_col)

    raise ValueError(
        f"Unsupported data file extension: {ext!r}. Supported: .csv, .duckdb, .db"
    )


__all__ = [
    "load_data",
    "discover_schema",
    "CSVLoader",
    "DuckDBLoader",
    "SchemaDiscovery",
    "DataSource",
    "LoadResult",
]
