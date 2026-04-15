"""
Snowflake loader for OpenXP.

Provides a `SnowflakeLoader` class that pulls assignment and outcome data from
a Snowflake warehouse. Supports three operating modes:

1. **Direct mode** — uses `snowflake-connector-python` to talk to Snowflake. The
   package is an optional dependency (`pip install openxp[snowflake]`).
2. **Env-var mode** — credentials sourced from `OPENXP_SNOWFLAKE_*` environment
   variables when `connection_params` is not supplied.
3. **MCP mode** — when `mcp_mode=True`, the loader does not open a direct
   connection. Instead, `query()` returns an empty stub DataFrame and logs a
   notice. The orchestrator skill is expected to call the Snowflake MCP tools
   (e.g. `mcp__snowflake__run_snowflake_query`) from the agent layer and pass
   the resulting data back into OpenXP by another path.

Security notes:
- Credentials are NEVER logged, printed, or included in exception messages.
- A row-count guardrail rejects queries that would return more than
  `MAX_ROWS_DEFAULT` rows unless `force=True` is passed to `query()`.
- Parameterized queries should be preferred; the high-level
  `load_experiment()` helper validates identifier inputs before interpolating
  them into SQL.

See `docs/snowflake-setup.md` for setup instructions.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

#: Default row-count guardrail. Queries that would return more than this many
#: rows are rejected unless ``force=True`` is passed to ``query()``.
MAX_ROWS_DEFAULT = 10_000_000

#: Environment variables used when ``connection_params`` is not supplied.
ENV_VAR_MAP = {
    "account": "OPENXP_SNOWFLAKE_ACCOUNT",
    "user": "OPENXP_SNOWFLAKE_USER",
    "password": "OPENXP_SNOWFLAKE_PASSWORD",
    "warehouse": "OPENXP_SNOWFLAKE_WAREHOUSE",
    "database": "OPENXP_SNOWFLAKE_DATABASE",
    "schema": "OPENXP_SNOWFLAKE_SCHEMA",
    "role": "OPENXP_SNOWFLAKE_ROLE",
}

#: Keys that must NEVER appear in log output.
_SECRET_KEYS = {"password", "private_key", "token", "oauth_token"}

#: Regex for validating SQL identifiers (table names, column names).
#: Allows letters, digits, underscore, and a single optional dotted qualifier.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")


class SnowflakeLoader:
    """
    Snowflake data loader for OpenXP.

    Parameters
    ----------
    connection_params : dict, optional
        Keys: ``account``, ``user``, ``password``, ``warehouse``, ``database``,
        ``schema``, ``role``. If omitted, values are read from environment
        variables (see :data:`ENV_VAR_MAP`).
    mcp_mode : bool, default False
        If True, do not open a direct Snowflake connection. ``query()`` will
        return a stub DataFrame and log a notice. Use this mode when the
        calling skill plans to execute queries via the Snowflake MCP server
        (``mcp__snowflake__run_snowflake_query``) instead.
    max_rows : int, default :data:`MAX_ROWS_DEFAULT`
        Row-count guardrail. Queries that would return more rows are rejected
        unless ``force=True`` is passed to ``query()``.

    Examples
    --------
    Direct mode::

        with SnowflakeLoader() as loader:
            df = loader.query("SELECT user_id, variant FROM assignments")

    MCP mode (inside Claude Code)::

        loader = SnowflakeLoader(mcp_mode=True)
        # The skill calls mcp__snowflake__run_snowflake_query itself.
    """

    def __init__(
        self,
        connection_params: dict[str, Any] | None = None,
        *,
        mcp_mode: bool = False,
        max_rows: int = MAX_ROWS_DEFAULT,
    ) -> None:
        self.mcp_mode = mcp_mode
        self.max_rows = max_rows
        self._conn = None  # lazily opened
        self._connection_params = self._resolve_params(connection_params)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_params(
        connection_params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Resolve connection parameters from arg or env vars."""
        if connection_params is not None:
            # Shallow copy so we don't mutate the caller's dict.
            return dict(connection_params)

        params: dict[str, Any] = {}
        for key, env_var in ENV_VAR_MAP.items():
            val = os.environ.get(env_var)
            if val:
                params[key] = val
        return params

    @staticmethod
    def _safe_params_for_log(params: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of params with secret fields masked."""
        return {
            k: ("***" if k in _SECRET_KEYS else v)
            for k, v in params.items()
        }

    def _connect(self):
        """Open a Snowflake connection (direct mode only)."""
        if self.mcp_mode:
            raise RuntimeError(
                "SnowflakeLoader is in MCP mode; direct connections are "
                "disabled. Call the Snowflake MCP tool from the skill layer."
            )

        try:
            import snowflake.connector  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised via patching
            raise ImportError(
                "snowflake-connector-python is not installed. Install the "
                "optional extra with:  pip install openxp[snowflake]"
            ) from exc

        if not self._connection_params:
            raise ValueError(
                "No Snowflake connection parameters supplied and no "
                "OPENXP_SNOWFLAKE_* environment variables set."
            )

        logger.debug(
            "Opening Snowflake connection (params=%s)",
            self._safe_params_for_log(self._connection_params),
        )
        self._conn = snowflake.connector.connect(**self._connection_params)
        return self._conn

    def _ensure_conn(self):
        if self._conn is None:
            self._connect()
        return self._conn

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------
    def query(self, sql: str, *, force: bool = False) -> pd.DataFrame:
        """
        Run a SQL query and return the result as a DataFrame.

        Parameters
        ----------
        sql : str
            The SQL query to execute. Must be a non-empty string.
        force : bool, default False
            Bypass the row-count guardrail. Use only when you are confident
            the query will not return an unbounded result set.

        Returns
        -------
        pandas.DataFrame
            Query results. In MCP mode, returns an empty DataFrame stub.
        """
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("sql must be a non-empty string")

        if self.mcp_mode:
            logger.info(
                "SnowflakeLoader in MCP mode: query not executed directly. "
                "The orchestrator skill should call "
                "mcp__snowflake__run_snowflake_query with this SQL and pass "
                "the result back."
            )
            return pd.DataFrame()

        if not force:
            self._check_row_count(sql)

        conn = self._ensure_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            columns = (
                [c[0] for c in cursor.description]
                if cursor.description
                else []
            )
        finally:
            cursor.close()

        return pd.DataFrame(rows, columns=columns)

    def _check_row_count(self, sql: str) -> None:
        """
        Estimate the row count of ``sql`` and reject if above ``max_rows``.

        Uses a ``SELECT COUNT(*) FROM (sql)`` subquery. This is a best-effort
        guardrail — some queries (e.g. DDL, ``SHOW``, multi-statement) cannot
        be wrapped. For those, callers should pass ``force=True``.
        """
        stripped = sql.strip().rstrip(";")
        # Only count SELECT-like queries.
        head = stripped.lstrip("(").lstrip().split(None, 1)[0].upper()
        if head not in {"SELECT", "WITH"}:
            return

        count_sql = f"SELECT COUNT(*) FROM ({stripped}) AS _openxp_guardrail"
        conn = self._ensure_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(count_sql)
            row = cursor.fetchone()
        finally:
            cursor.close()

        estimated = int(row[0]) if row else 0
        if estimated > self.max_rows:
            raise ValueError(
                f"Query would return {estimated:,} rows, which exceeds the "
                f"guardrail of {self.max_rows:,}. Pass force=True to "
                f"override."
            )

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------
    def load_experiment(
        self,
        table: str,
        treatment_col: str,
        metric_cols: list[str],
        where: str | None = None,
    ) -> pd.DataFrame:
        """
        Load experiment data from ``table`` via a SELECT query.

        Parameters
        ----------
        table : str
            Fully-qualified table name (``db.schema.table`` or ``schema.table``
            or ``table``). Must match ``[A-Za-z_][A-Za-z0-9_]*`` per segment.
        treatment_col : str
            Column that identifies treatment assignment.
        metric_cols : list[str]
            Metric columns to select alongside ``treatment_col``.
        where : str, optional
            Raw WHERE clause (without the ``WHERE`` keyword). **Not validated.**
            Only pass trusted, static values here.

        Returns
        -------
        pandas.DataFrame
            One row per observation with ``treatment_col`` and each metric.
        """
        self._validate_ident(table, "table")
        self._validate_ident(treatment_col, "treatment_col")
        if not metric_cols:
            raise ValueError("metric_cols must be a non-empty list")
        for col in metric_cols:
            self._validate_ident(col, "metric_cols")

        col_list = ", ".join([treatment_col, *metric_cols])
        sql = f"SELECT {col_list} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return self.query(sql)

    @staticmethod
    def _validate_ident(value: str, field: str) -> None:
        if not isinstance(value, str) or not _IDENT_RE.match(value):
            raise ValueError(
                f"Invalid SQL identifier for {field}: must match "
                f"[A-Za-z_][A-Za-z0-9_]* (dotted qualifiers allowed)."
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Close the underlying Snowflake connection, if any."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # pragma: no cover - best effort
                logger.debug("Error closing Snowflake connection", exc_info=True)
            finally:
                self._conn = None

    def __enter__(self) -> "SnowflakeLoader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        mode = "mcp" if self.mcp_mode else "direct"
        db = self._connection_params.get("database", "?")
        return f"SnowflakeLoader(mode={mode}, database={db!r})"
