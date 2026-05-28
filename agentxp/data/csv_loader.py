"""
CSV loader with row-count safety limits.

Implements the size tiers from PRD §5.20:

  - < 100K rows  : load directly
  - 100K - 1M    : load + warn (consider DuckDB)
  - > 10M        : block unless ``force=True``

The 1M soft cap from the PRD is surfaced as a warning; the hard fail-fast
limit is 10M rows because above that pandas will OOM on most laptops.
"""

from __future__ import annotations

import os
from typing import Iterator

import pandas as pd

from agentxp.data.base import DataSource, LoadResult


SOFT_WARN_ROWS = 100_000
HARD_WARN_ROWS = 1_000_000
BLOCK_ROWS = 10_000_000


class CSVLoader:
    """Pandas-backed CSV loader with fail-fast row-count guards.

    Usage:
        loader = CSVLoader()
        result = loader.load("experiment.csv")
        df = result.dataframe
    """

    def __init__(self, *, soft_warn: int = SOFT_WARN_ROWS,
                 hard_warn: int = HARD_WARN_ROWS,
                 block_rows: int = BLOCK_ROWS) -> None:
        self.soft_warn = soft_warn
        self.hard_warn = hard_warn
        self.block_rows = block_rows

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _count_rows(path: str) -> int:
        """Quickly count data rows in a CSV (subtracts header)."""
        with open(path, "rb") as f:
            total = sum(1 for _ in f)
        return max(total - 1, 0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def peek(self, path: str, n: int = 5) -> pd.DataFrame:
        """Return the first ``n`` rows of the CSV without loading the rest.

        Used by the discovery protocol to inspect column names + dtypes
        before committing to a full load.
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"CSV not found: {path}")
        return pd.read_csv(path, nrows=n)

    def load(
        self,
        path: str,
        *,
        chunk_size: int | None = None,
        force: bool = False,
    ) -> LoadResult:
        """Load a CSV into a DataFrame, respecting row-count safety limits.

        Args:
            path: path to the CSV file.
            chunk_size: if set, stream rows via ``pandas.read_csv(chunksize=)``
                and concatenate. Useful for memory-constrained environments.
            force: bypass the hard block for files over 10M rows.

        Returns:
            ``LoadResult`` with the loaded DataFrame and a metadata envelope.

        Raises:
            FileNotFoundError: path does not exist.
            ValueError: file exceeds ``block_rows`` and ``force`` is False.
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"CSV not found: {path}")

        row_count = self._count_rows(path)
        warnings: list[str] = []

        if row_count > self.block_rows and not force:
            raise ValueError(
                f"CSV has {row_count:,} rows (> {self.block_rows:,} hard limit)."
                " Use DuckDB for datasets this large, or pass force=True to"
                " override. See: pip install agentxp[duckdb]"
            )
        if row_count > self.hard_warn:
            warnings.append(
                f"Large CSV ({row_count:,} rows): loading into pandas will use"
                " significant memory. Consider DuckDB for repeated analysis."
            )
        elif row_count > self.soft_warn:
            warnings.append(
                f"CSV has {row_count:,} rows: loading fine but DuckDB will be"
                " faster for repeated analysis."
            )

        if chunk_size:
            chunks: list[pd.DataFrame] = []
            for chunk in pd.read_csv(path, chunksize=chunk_size):
                chunks.append(chunk)
            df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        else:
            df = pd.read_csv(path)

        interpretation = (
            f"Loaded {len(df):,} rows x {df.shape[1]} columns from CSV '{path}'."
        )
        if warnings:
            interpretation += " Warnings: " + " ".join(warnings)

        return LoadResult(
            dataframe=df,
            source=DataSource(kind="csv", location=path),
            n_rows=len(df),
            n_columns=df.shape[1],
            warnings=warnings,
            interpretation=interpretation,
        )

    def stream(self, path: str, chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
        """Stream a CSV in chunks without ever materializing the full frame."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"CSV not found: {path}")
        for chunk in pd.read_csv(path, chunksize=chunk_size):
            yield chunk
