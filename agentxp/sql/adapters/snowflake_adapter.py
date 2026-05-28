"""Snowflake warehouse adapter for AgentXP v0.1.1 (§12).

Implements the :class:`agentxp.sql.adapter.BaseAdapter` Protocol against the
``snowflake-connector-python`` driver. Replaces the v0.1 stub. Supports the
four auth surfaces Snowflake exposes through ``snowflake.connector.connect``:
password, external-browser SSO, OAuth bearer token, and key-pair (RSA JWT).

Behavioural notes:

* **Lazy connect.** The adapter does not open a connection at construction
  time. The first call to :meth:`execute` / :meth:`explain` / :meth:`dry_run`
  opens the connection; subsequent calls reuse it. :meth:`close` releases it.
* **Auth surfaces.** The connection dict is mapped to driver kwargs by
  :meth:`_build_connect_kwargs`. ``auth_method`` (or, absent that, the presence
  of ``password`` / ``token`` / ``private_key``) selects the surface:

  - ``password`` → default authenticator (``"snowflake"``) + ``password``.
  - ``externalbrowser`` → ``authenticator="externalbrowser"`` (no secret).
  - ``oauth`` → ``authenticator="oauth"`` + ``token``.
  - ``keypair`` → ``authenticator="SNOWFLAKE_JWT"`` + ``private_key`` (DER
    bytes) or ``private_key_file`` (+ optional ``private_key_file_pwd``).

  An unknown ``auth_method`` raises :class:`AdapterError` with a message that
  contains NO secret material.
* **bytes_scanned.** Read from the per-query stats: after ``execute`` the
  connector exposes ``cursor.sfqid`` (the query ID). The authoritative
  ``BYTES_SCANNED`` lives in ``QUERY_HISTORY``; the connector also surfaces it
  on the result-set metadata as ``cursor._result.total_row_index``-adjacent
  stats. v0.1.1 reads the connector-surfaced stat (``cursor.query_result_format``
  metadata via ``_inner_cursor`` is private), falling back to ``None`` when the
  driver does not expose it. See :func:`_extract_bytes_scanned`.
* **Timeout enforcement.** REAL, server-side. The
  ``STATEMENT_TIMEOUT_IN_SECONDS`` session parameter is set at connect time
  from ``timeout_s`` so Snowflake itself cancels overruns; the per-call value
  is also passed to ``cursor.execute(sql, timeout=...)`` for a client-side
  belt-and-braces abort. A server cancellation surfaces as an
  ``OperationalError`` / ``ProgrammingError`` and is mapped to
  :class:`QueryTimeoutError`.
* **dry_run.** Snowflake has no free dry-run (no BigQuery-style "estimate
  bytes, bill nothing" call). :meth:`dry_run` returns a :class:`PreviewResult`
  with ``estimated_*=None`` and an honest warning, mirroring DuckDB.
* **Credential safety.** Every connection dict is passed through
  :func:`agentxp.sql.adapter._redact_creds_for_log` before any log / exception
  text is produced. No secret ever reaches an exception message or traceback.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 (adapters table).
Ground truth: experimentation-platform/research/v0.1.1-warehouse-auth/WAREHOUSE_AUTH_BRIEF.md §1.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from agentxp.sql.adapter import (
    AdapterError,
    AdapterResult,
    AuthExpiredError,
    PreviewResult,
    QueryTimeoutError,
    _redact_creds_for_log,
)


_SNOWFLAKE_INSTALL_HINT = (
    "Snowflake is an optional dependency. Install it with:\n"
    "    pip install 'agentxp[snowflake]'\n"
    "or directly:\n"
    "    pip install snowflake-connector-python"
)

#: Snowflake auth error codes (per WAREHOUSE_AUTH_BRIEF §1, errors.py source).
#: 390100 = incorrect username/password, 390114 = auth token expired,
#: 250001 = could not connect / auth.
_AUTH_ERROR_CODES: frozenset[str] = frozenset({"390100", "390114", "250001"})

#: Driver kwargs that select an auth surface — never logged in the clear.
_AUTH_SURFACES: tuple[str, ...] = ("password", "externalbrowser", "oauth", "keypair")


def _import_snowflake():
    """Import snowflake.connector lazily so this module imports cleanly without it."""
    try:
        import snowflake.connector  # type: ignore
    except ImportError as e:  # pragma: no cover — depends on env
        raise ImportError(_SNOWFLAKE_INSTALL_HINT) from e
    return snowflake.connector


def _is_auth_error(exc: Exception) -> bool:
    """True if ``exc`` looks like a Snowflake authentication failure.

    Snowflake auth failures surface as ``ProgrammingError`` / ``DatabaseError``
    with ``errno`` in :data:`_AUTH_ERROR_CODES` and/or SQLSTATE ``08001``.
    We inspect ``errno`` / ``sqlstate`` attributes when present and fall back
    to scanning the (already credential-free) message for the codes.
    """
    errno = getattr(exc, "errno", None)
    if errno is not None and str(errno) in _AUTH_ERROR_CODES:
        return True
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate == "08001":
        return True
    msg = str(exc)
    return any(code in msg for code in _AUTH_ERROR_CODES)


def _is_timeout_error(exc: Exception) -> bool:
    """True if ``exc`` looks like a statement-timeout / cancellation.

    A server-side ``STATEMENT_TIMEOUT_IN_SECONDS`` cancellation surfaces as an
    ``OperationalError`` (or a ``ProgrammingError`` whose message mentions the
    statement being cancelled / reaching the timeout). Snowflake uses errno
    ``604`` for "statement canceled" and ``630`` for "statement aborted".
    """
    errno = getattr(exc, "errno", None)
    if errno is not None and str(errno) in {"604", "630"}:
        return True
    msg = str(exc).lower()
    return (
        "statement_timeout" in msg
        or "statement timeout" in msg
        or "canceled" in msg
        or "cancelled" in msg
        or "timed out" in msg
        or "reached its statement timeout" in msg
    )


def _extract_bytes_scanned(cursor: Any) -> Optional[int]:
    """Best-effort read of bytes scanned for the last query on ``cursor``.

    Per WAREHOUSE_AUTH_BRIEF §1, the authoritative ``BYTES_SCANNED`` lives in
    ``QUERY_HISTORY`` keyed by ``cursor.sfqid``. Issuing a second
    ``INFORMATION_SCHEMA.QUERY_HISTORY`` round-trip per query would double the
    request cost and add latency, so v0.1.1 reads the stat the connector
    already attaches to the result set when present
    (``cursor._stats`` / ``cursor.query_result_format`` metadata expose a
    ``stats`` dict with ``bytesScanned`` on recent driver versions). When the
    driver does not surface it, return ``None`` rather than guessing — the same
    honest-unknown contract DuckDB uses for ``bytes_scanned``.
    """
    # Recent connector versions expose a private ``_stats`` mapping with the
    # scan stats already parsed from the result envelope. Treat any failure as
    # "stat unavailable" and fall back to None.
    stats = getattr(cursor, "_stats", None)
    if isinstance(stats, dict):
        for key in ("bytesScanned", "BYTES_SCANNED", "bytes_scanned"):
            value = stats.get(key)
            if isinstance(value, int):
                return value
    return None


class SnowflakeAdapter:
    """Snowflake adapter (§12) over ``snowflake-connector-python``.

    Construct with the connection params as keyword args, e.g.::

        SnowflakeAdapter(
            account="myorg-myaccount",
            user="SVC_AGENTXP",
            password="...",
            warehouse="WH_XS",
            database="ANALYTICS",
            schema="PUBLIC",
        )

    The connection is created lazily on the first real-method call; nothing
    touches the network at construction. Pass ``auth_method`` explicitly
    (``"password"`` / ``"externalbrowser"`` / ``"oauth"`` / ``"keypair"``) or
    let the adapter infer it from the supplied credential keys.
    """

    def __init__(self, **conn_params: Any) -> None:
        self._conn_params = conn_params
        self._conn: Any | None = None

    # ------------------------------------------------------------------
    # Auth surface mapping
    # ------------------------------------------------------------------

    def _resolve_auth_method(self) -> str:
        """Return the auth surface name, inferring it from creds if unset."""
        explicit = self._conn_params.get("auth_method")
        if explicit is not None:
            method = str(explicit).strip().lower()
            if method not in _AUTH_SURFACES:
                # NOTE: never echo conn_params — only the (non-secret) method name.
                raise AdapterError(
                    f"Unknown Snowflake auth_method {method!r}; "
                    f"expected one of {sorted(_AUTH_SURFACES)}"
                )
            return method
        # Infer from supplied credential keys.
        if self._conn_params.get("token") is not None:
            return "oauth"
        if (
            self._conn_params.get("private_key") is not None
            or self._conn_params.get("private_key_file") is not None
        ):
            return "keypair"
        if self._conn_params.get("password") is not None:
            return "password"
        if self._conn_params.get("authenticator") == "externalbrowser":
            return "externalbrowser"
        # Nothing identifiable — refuse without leaking the dict.
        raise AdapterError(
            "Could not determine Snowflake auth method from connection params; "
            "set auth_method to one of "
            f"{sorted(_AUTH_SURFACES)}"
        )

    def _build_connect_kwargs(self, conn_params: dict[str, Any]) -> dict[str, Any]:
        """Map a connection dict to ``snowflake.connector.connect`` kwargs.

        Pulls the common connection fields (``account``, ``user``,
        ``warehouse``, ``database``, ``schema``, ``role``) then layers the
        auth-surface-specific kwargs on top. Raises :class:`AdapterError` with
        a secret-free message for an unknown auth method.
        """
        method = self._resolve_auth_method()

        kwargs: dict[str, Any] = {}
        # Common, non-secret connection fields (only when present).
        for field in ("account", "user", "warehouse", "database", "schema", "role"):
            if conn_params.get(field) is not None:
                kwargs[field] = conn_params[field]

        if method == "password":
            kwargs["authenticator"] = "snowflake"
            kwargs["password"] = conn_params["password"]
        elif method == "externalbrowser":
            kwargs["authenticator"] = "externalbrowser"
            if conn_params.get("client_store_temporary_credential") is not None:
                kwargs["client_store_temporary_credential"] = conn_params[
                    "client_store_temporary_credential"
                ]
        elif method == "oauth":
            kwargs["authenticator"] = "oauth"
            kwargs["token"] = conn_params["token"]
        elif method == "keypair":
            kwargs["authenticator"] = "SNOWFLAKE_JWT"
            if conn_params.get("private_key") is not None:
                # DER bytes (PKCS#8), decrypted in-memory by the caller.
                kwargs["private_key"] = conn_params["private_key"]
            elif conn_params.get("private_key_file") is not None:
                kwargs["private_key_file"] = conn_params["private_key_file"]
                if conn_params.get("private_key_file_pwd") is not None:
                    kwargs["private_key_file_pwd"] = conn_params[
                        "private_key_file_pwd"
                    ]
            else:
                raise AdapterError(
                    "Snowflake keypair auth requires either 'private_key' "
                    "(DER bytes) or 'private_key_file' (path)"
                )
        else:  # pragma: no cover — _resolve_auth_method already guards this.
            raise AdapterError(f"Unknown Snowflake auth_method {method!r}")

        return kwargs

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self, timeout_s: int = 30) -> Any:
        if self._conn is not None:
            return self._conn
        connector = _import_snowflake()
        connect_kwargs = self._build_connect_kwargs(self._conn_params)
        # Real, server-enforced statement ceiling.
        session_parameters = {"STATEMENT_TIMEOUT_IN_SECONDS": int(timeout_s)}
        connect_kwargs["session_parameters"] = session_parameters
        try:
            self._conn = connector.connect(**connect_kwargs)
        except Exception as e:
            # Redact the connection dict before it can reach any log/exception.
            safe = _redact_creds_for_log(self._conn_params)
            if _is_auth_error(e):
                raise AuthExpiredError(
                    f"Snowflake authentication failed for connection {safe!r}"
                ) from e
            raise AdapterError(
                f"Snowflake failed to open connection {safe!r}"
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
        return "snowflake"

    def execute(
        self,
        sql: str,
        max_rows: int = 10_000,
        timeout_s: int = 30,
    ) -> AdapterResult:
        """Run ``sql`` and return at most ``max_rows`` rows.

        The statement timeout is enforced server-side via the
        ``STATEMENT_TIMEOUT_IN_SECONDS`` session parameter set at connect, plus
        a client-side ``cursor.execute(..., timeout=)`` belt. A timeout maps to
        :class:`QueryTimeoutError`; auth rejection to :class:`AuthExpiredError`;
        anything else to :class:`AdapterError`.
        """
        conn = self._connect(timeout_s=timeout_s)
        cursor = conn.cursor()
        started = time.monotonic()
        try:
            cursor.execute(sql, timeout=timeout_s)
            raw_rows = cursor.fetchmany(max_rows)
            description = cursor.description or []
            bytes_scanned = _extract_bytes_scanned(cursor)
        except Exception as e:
            cursor.close()
            if _is_timeout_error(e):
                raise QueryTimeoutError(
                    f"Snowflake query exceeded timeout_s={timeout_s}"
                ) from e
            if _is_auth_error(e):
                raise AuthExpiredError(
                    "Snowflake rejected credentials during execute "
                    "(token expired / revoked)"
                ) from e
            raise AdapterError(f"Snowflake execute failed: {e}") from e
        finally:
            elapsed = time.monotonic() - started

        columns = [d[0] for d in description]
        rows: list[dict[str, Any]] = [dict(zip(columns, row)) for row in raw_rows]
        cursor.close()

        return AdapterResult(
            rows=rows,
            row_count=len(rows),
            bytes_scanned=bytes_scanned,
            elapsed_seconds=elapsed,
            dialect="snowflake",
        )

    def explain(self, sql: str) -> str:
        """Return the Snowflake ``EXPLAIN USING TEXT`` plan for ``sql``."""
        conn = self._connect()
        cursor = conn.cursor()
        try:
            cursor.execute(f"EXPLAIN USING TEXT {sql}")
            rows = cursor.fetchall()
        except Exception as e:
            cursor.close()
            if _is_auth_error(e):
                raise AuthExpiredError(
                    "Snowflake rejected credentials during EXPLAIN"
                ) from e
            raise AdapterError(f"Snowflake EXPLAIN failed: {e}") from e
        cursor.close()

        # EXPLAIN USING TEXT returns rows of plan text; flatten to one string.
        chunks: list[str] = []
        for row in rows:
            chunks.append(" | ".join(str(cell) for cell in row))
        return "\n".join(chunks)

    def dry_run(self, sql: str) -> PreviewResult:
        """Return an empty :class:`PreviewResult` with an honest warning.

        Snowflake has no free dry-run / "estimate bytes, bill nothing" call
        (per WAREHOUSE_AUTH_BRIEF §1). ``EXPLAIN`` returns a plan but not an
        authoritative scan-cost figure, so v0.1.1 surfaces the gap honestly —
        mirroring DuckDB — rather than reporting a misleading "0". Use
        :meth:`explain` for a plan or :meth:`execute` for actual
        ``bytes_scanned``.
        """
        return PreviewResult(
            estimated_rows=None,
            estimated_bytes_scanned=None,
            estimated_cost_usd=None,
            warnings=[
                "Snowflake has no free dry-run; estimates unavailable. "
                "Use adapter.explain() for a plan, or execute() for actuals."
            ],
        )


__all__ = ["SnowflakeAdapter"]
