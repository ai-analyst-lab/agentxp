"""
DuckDB loader for OpenXP.

DuckDB is an optional dependency. If not installed, importing this module
still works but instantiating ``DuckDBLoader`` raises an ImportError that
points the user at ``pip install openxp[duckdb]``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from openxp.data.base import DataSource, LoadResult


_DUCKDB_INSTALL_HINT = (
    "DuckDB is an optional dependency. Install it with:\n"
    "    pip install 'openxp[duckdb]'\n"
    "or directly:\n"
    "    pip install duckdb"
)


def _import_duckdb():
    """Import duckdb lazily so the module can be imported without it."""
    try:
        import duckdb  # type: ignore
    except ImportError as e:
        raise ImportError(_DUCKDB_INSTALL_HINT) from e
    return duckdb


class DuckDBLoader:
    """Thin wrapper around a DuckDB connection for experiment data.

    Usage:
        loader = DuckDBLoader()
        loader.connect(":memory:")
        loader.conn.execute(
            "CREATE TABLE exp AS SELECT * FROM read_csv_auto('exp.csv')"
        )
        result = loader.load_experiment("exp", treatment_col="variant")
    """

    def __init__(self) -> None:
        self._duckdb = _import_duckdb()
        self.conn: Any | None = None
        self.db_path: str | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    def connect(self, db_path: str = ":memory:") -> "DuckDBLoader":
        """Open (or reopen) a DuckDB connection.

        Args:
            db_path: ':memory:' for an ephemeral db, or a filesystem path.

        Returns:
            Self, so calls can be chained: ``DuckDBLoader().connect(path)``.
        """
        self.conn = self._duckdb.connect(db_path)
        self.db_path = db_path
        return self

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "DuckDBLoader":
        if self.conn is None:
            self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Query + load
    # ------------------------------------------------------------------
    def _require_conn(self):
        if self.conn is None:
            raise RuntimeError(
                "DuckDBLoader has no active connection. Call .connect() first."
            )

    def query(self, sql: str) -> pd.DataFrame:
        """Run a SQL query and return the result as a pandas DataFrame."""
        self._require_conn()
        return self.conn.execute(sql).fetch_df()  # type: ignore[union-attr]

    def load_csv_as_table(self, path: str, table: str) -> int:
        """Register a CSV file as a DuckDB table. Returns row count."""
        self._require_conn()
        assert self.conn is not None
        # Use parameterized path via DuckDB read_csv_auto; table name cannot be
        # parameterized, so we sanity-check it.
        if not table.replace("_", "").isalnum():
            raise ValueError(f"Unsafe table name: {table!r}")
        self.conn.execute(
            f"CREATE OR REPLACE TABLE {table} AS "
            "SELECT * FROM read_csv_auto(?)",
            [path],
        )
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def load_experiment(
        self,
        table: str,
        treatment_col: str,
    ) -> LoadResult:
        """Load an experiment table as a DataFrame for downstream analysis.

        Args:
            table: name of the table to load (must exist in the current db).
            treatment_col: name of the treatment / variant column. Required —
                we never assume it, the caller passes it in after the
                discovery layer has identified it.

        Returns:
            ``LoadResult`` wrapping the full table as a DataFrame.
        """
        self._require_conn()
        assert self.conn is not None

        if not table.replace("_", "").isalnum():
            raise ValueError(f"Unsafe table name: {table!r}")

        # Verify treatment column exists before loading.
        columns = [
            row[0]
            for row in self.conn.execute(f"DESCRIBE {table}").fetchall()
        ]
        if treatment_col not in columns:
            raise ValueError(
                f"Treatment column '{treatment_col}' not found in table"
                f" '{table}'. Available columns: {columns}"
            )

        df = self.conn.execute(f"SELECT * FROM {table}").fetch_df()

        interpretation = (
            f"Loaded {len(df):,} rows from DuckDB table '{table}'"
            f" (treatment column: '{treatment_col}')."
        )

        return LoadResult(
            dataframe=df,
            source=DataSource(
                kind="duckdb",
                location=self.db_path,
                table=table,
                query=f"SELECT * FROM {table}",
            ),
            n_rows=len(df),
            n_columns=df.shape[1],
            warnings=[],
            interpretation=interpretation,
        )
