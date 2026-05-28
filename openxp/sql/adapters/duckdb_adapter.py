"""DuckDB warehouse adapter for OpenXP v0.1 (§12).

Implements the :class:`openxp.sql.adapter.BaseAdapter` Protocol against the
``duckdb`` Python driver. v0.1 ships file-path / in-memory auth only; cloud
DuckDB (MotherDuck) is deferred.

Behavioural notes:

* **Lazy connect.** The adapter does not open a connection at construction
  time. The first call to :meth:`execute` / :meth:`explain` / :meth:`dry_run`
  opens the connection; subsequent calls reuse it. :meth:`close` releases it.
* **Timeout enforcement.** DuckDB has no native query-cancel hook in the
  Python driver, so v0.1 measures elapsed wall-clock around ``.fetchall()``
  and raises :class:`QueryTimeoutError` *post-hoc* if it exceeded
  ``timeout_s``. The query has already run by that point — the timeout is
  advisory at the v0.1 adapter layer (this matches the §12 footnote that
  DuckDB timeouts are best-effort).
* **bytes_scanned.** Not exposed by the DuckDB driver; ``AdapterResult.bytes_scanned``
  is always ``None`` for this adapter.
* **dry_run.** DuckDB has no free dry-run; :meth:`dry_run` returns a
  :class:`PreviewResult` with ``estimated_rows=None`` and a warning so the
  user-review screen knows the estimate is unavailable rather than "0".

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 (adapters table).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from openxp.sql.adapter import (
    AdapterError,
    AdapterResult,
    PreviewResult,
    QueryTimeoutError,
)


_DUCKDB_INSTALL_HINT = (
    "DuckDB is an optional dependency. Install it with:\n"
    "    pip install 'openxp[duckdb]'\n"
    "or directly:\n"
    "    pip install duckdb"
)


def _import_duckdb():
    """Import duckdb lazily so this module imports cleanly without it."""
    try:
        import duckdb  # type: ignore
    except ImportError as e:  # pragma: no cover — depends on env
        raise ImportError(_DUCKDB_INSTALL_HINT) from e
    return duckdb


class DuckDBAdapter:
    """File-path / in-memory DuckDB adapter (§12).

    ``file_path=None`` uses an in-memory database (``":memory:"``). Otherwise
    the adapter opens / attaches the given ``.duckdb`` file on first use. The
    connection is lazily created so constructing an adapter for a path that
    does not yet exist is safe — the driver will create the file on first
    connect.
    """

    def __init__(self, file_path: Optional[Path] = None) -> None:
        self.file_path = file_path
        self._conn: Any | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> Any:
        if self._conn is not None:
            return self._conn
        duckdb = _import_duckdb()
        target = ":memory:" if self.file_path is None else str(self.file_path)
        try:
            self._conn = duckdb.connect(target)
        except Exception as e:  # pragma: no cover — driver-specific
            raise AdapterError(
                f"DuckDB failed to open connection at {target!r}: {e}"
            ) from e
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    # ------------------------------------------------------------------
    # BaseAdapter Protocol
    # ------------------------------------------------------------------

    def get_dialect(self) -> str:
        return "duckdb"

    def execute(
        self,
        sql: str,
        max_rows: int = 10_000,
        timeout_s: int = 30,
    ) -> AdapterResult:
        """Run ``sql`` and return at most ``max_rows`` rows.

        Raises :class:`QueryTimeoutError` if wall-clock elapsed exceeded
        ``timeout_s`` (post-hoc; the query has already run — DuckDB v0.1
        does not expose a Python-driver cancel hook).
        """
        conn = self._connect()
        started = time.monotonic()
        try:
            cursor = conn.execute(sql)
        except Exception as e:
            raise AdapterError(f"DuckDB execute failed: {e}") from e

        # Drain rows + capture column names. DuckDB returns Python objects
        # via fetchall(); we zip with description to materialise dicts.
        try:
            raw_rows = cursor.fetchall()
        except Exception as e:
            raise AdapterError(f"DuckDB fetchall failed: {e}") from e
        elapsed = time.monotonic() - started

        # Post-hoc timeout check — see module docstring.
        if elapsed > timeout_s:
            raise QueryTimeoutError(
                f"DuckDB query exceeded timeout_s={timeout_s} "
                f"(elapsed={elapsed:.3f}s); v0.1 enforces post-hoc only"
            )

        description = cursor.description or []
        columns = [d[0] for d in description]

        truncated = raw_rows[:max_rows] if max_rows is not None else raw_rows
        rows: list[dict[str, Any]] = [
            dict(zip(columns, row)) for row in truncated
        ]

        return AdapterResult(
            rows=rows,
            row_count=len(rows),
            bytes_scanned=None,  # not exposed by the DuckDB driver
            elapsed_seconds=elapsed,
            dialect="duckdb",
        )

    def explain(self, sql: str) -> str:
        """Return the DuckDB ``EXPLAIN`` plan text for ``sql``."""
        conn = self._connect()
        try:
            cursor = conn.execute(f"EXPLAIN {sql}")
            rows = cursor.fetchall()
        except Exception as e:
            raise AdapterError(f"DuckDB EXPLAIN failed: {e}") from e

        # DuckDB EXPLAIN returns rows like [(phase, plan_text), ...]. Flatten
        # to a single string for the audit anchor.
        chunks: list[str] = []
        for row in rows:
            chunks.append(" | ".join(str(cell) for cell in row))
        return "\n".join(chunks)

    def dry_run(self, sql: str) -> PreviewResult:
        """Return an empty :class:`PreviewResult` with a warning.

        DuckDB has no free dry-run path; the only way to know row counts is
        to execute. v0.1 surfaces this honestly via a warning so the
        user-review screen can label the estimate as unavailable.
        """
        return PreviewResult(
            estimated_rows=None,
            estimated_bytes_scanned=None,
            estimated_cost_usd=None,
            warnings=[
                "DuckDB has no free dry-run; estimates unavailable. "
                "Use adapter.explain() for a plan, or execute() for actuals."
            ],
        )


__all__ = ["DuckDBAdapter"]
