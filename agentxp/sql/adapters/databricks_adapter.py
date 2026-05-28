"""Databricks warehouse adapter for AgentXP v0.1.1 (§12).

Implements the :class:`agentxp.sql.adapter.BaseAdapter` Protocol against the
``databricks-sql-connector`` driver. Replaces the v0.1 stub.

Every method goes through ``databricks.sql.connect(...)`` which always needs
``server_hostname`` + ``http_path`` plus auth material.

Behavioural notes:

* **Lazy connect.** The adapter does not open a connection at construction
  time. The first call to :meth:`execute` / :meth:`explain` / :meth:`dry_run`
  opens the connection; subsequent calls reuse it. :meth:`close` releases the
  cursor + connection.
* **Two auth surfaces** (see :meth:`_build_connect_kwargs`):
    1. **PAT** — Personal Access Token via the ``access_token`` kwarg. The
       common, non-interactive path. ``access_token`` is SECRET.
    2. **OAuth** — both flavours are documented and supported:
       - **U2M** (user-to-machine, interactive/browser): pass
         ``auth_type="databricks-oauth"`` (no token). The connector opens a
         browser for user consent.
       - **M2M** (machine-to-machine, service principal): pass ``client_id``
         + ``client_secret``; the adapter builds a ``credentials_provider``
         callable via ``databricks.sdk.core`` (lazy import, optional
         ``databricks-sdk`` dependency). ``client_secret`` is SECRET.
  ``auth_method`` (``"pat"`` / ``"oauth_u2m"`` / ``"oauth_m2m"``) may be set
  explicitly or is inferred from the supplied credential keys. An unknown
  ``auth_method`` raises :class:`AdapterError` with a message that contains NO
  secret material.
* **Unity Catalog three-level naming.** Databricks addresses objects as
  ``catalog.schema.table`` (e.g. ``main.sales.orders``). This adapter passes
  SQL through verbatim and never parses table names, so a three-level name is
  handled transparently. The *semantic-model layer* is responsible for
  emitting three-level names for the ``databricks`` dialect; the adapter just
  does not choke on the third qualifier.
* **bytes_scanned.** **Not exposed by the connector** (per
  WAREHOUSE_AUTH_BRIEF §3). The Python connector returns rows + a thin DB-API
  cursor and surfaces no scan/byte stats; the only source is the Query History
  REST API, out of band. v0.1.1 therefore sets ``bytes_scanned=None`` — the
  same honest-unknown contract DuckDB uses — rather than guessing.
* **Timeout enforcement.** The connector has no per-``execute`` timeout kwarg;
  it exposes a connection-level ``socket_timeout`` (communication timeout,
  seconds), and server-side statement timeouts are governed by the SQL
  warehouse config. v0.1.1 sets ``socket_timeout`` from ``timeout_s`` at
  connect for a best-effort ceiling. A server-side statement timeout surfaces
  as ``ServerOperationError`` with ``DEADLINE_EXCEEDED`` (and a socket timeout
  surfaces as a socket/timeout error) → :class:`QueryTimeoutError`.
* **dry_run.** **None available** (per WAREHOUSE_AUTH_BRIEF §3): no dry-run, no
  byte-estimate call. :meth:`dry_run` returns a :class:`PreviewResult` with
  ``estimated_*=None`` and an honest warning, mirroring DuckDB / Snowflake.
* **explain.** Databricks supports ``EXPLAIN <query>`` (plan text, no reliable
  byte figure). :meth:`explain` runs it and flattens the rows to a string.
* **Byte ceiling.** No connector-level byte cap exists (per
  WAREHOUSE_AUTH_BRIEF §3). The adapter cannot enforce a byte ceiling through
  this driver; enforce via warehouse policy / post-hoc Query History.
* **Credential safety.** Every connection dict is passed through
  :func:`agentxp.sql.adapter._redact_creds_for_log` before any log / exception
  text is produced. ``access_token`` and ``client_secret`` NEVER reach an
  exception message, traceback, or log line.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 (adapters table).
Ground truth: experimentation-platform/research/v0.1.1-warehouse-auth/WAREHOUSE_AUTH_BRIEF.md §3.
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


_DATABRICKS_INSTALL_HINT = (
    "Databricks is an optional dependency. Install it with:\n"
    "    pip install 'agentxp[databricks]'\n"
    "or directly:\n"
    "    pip install databricks-sql-connector\n"
    "(OAuth M2M / service-principal auth additionally needs databricks-sdk.)"
)

#: Auth surface names this adapter accepts. ``pat`` = personal access token,
#: ``oauth_u2m`` = browser-based user-to-machine, ``oauth_m2m`` = service
#: principal (client_id/client_secret). Never logged in the clear.
_AUTH_SURFACES: tuple[str, ...] = ("pat", "oauth_u2m", "oauth_m2m")

#: Databricks-specific secret keys. The shared ``_redact_creds_for_log`` only
#: blanket-redacts keys in :data:`agentxp.sql.adapter._SENSITIVE_KEYS`, which
#: does NOT include ``access_token`` / ``client_secret``; their values
#: (``dapi...`` PATs, SP secrets) have no internal structure the regex redactor
#: catches, so they would otherwise pass through. :func:`_safe_conn` scrubs
#: them before delegating to the shared redactor (the same pattern the BigQuery
#: adapter uses for its nested service-account dict).
_DATABRICKS_SECRET_KEYS: frozenset[str] = frozenset(
    {"access_token", "client_secret"}
)


def _safe_conn(conn_params: dict[str, Any]) -> dict[str, Any]:
    """Redact a Databricks connection dict for logs / exceptions.

    Blanket-redacts the Databricks-specific secret keys
    (:data:`_DATABRICKS_SECRET_KEYS`) — which the shared
    :func:`agentxp.sql.adapter._redact_creds_for_log` does not know about — then
    delegates to the shared redactor for everything else.
    """
    cleaned: dict[str, Any] = {}
    for key, value in conn_params.items():
        if key.lower() in _DATABRICKS_SECRET_KEYS and isinstance(value, str):
            cleaned[key] = "[REDACTED]"
        else:
            cleaned[key] = value
    return _redact_creds_for_log(cleaned)


def _import_databricks_sql():
    """Import ``databricks.sql`` lazily so this module imports cleanly without
    the driver installed (Tier-A tests patch at this boundary)."""
    try:
        from databricks import sql  # type: ignore
    except ImportError as e:  # pragma: no cover — depends on env
        raise ImportError(_DATABRICKS_INSTALL_HINT) from e
    return sql


def _import_databricks_sdk_core():
    """Import ``databricks.sdk.core`` lazily for the OAuth M2M path only."""
    try:
        from databricks.sdk.core import (  # type: ignore
            Config,
            oauth_service_principal,
        )
    except ImportError as e:  # pragma: no cover — depends on env
        raise ImportError(_DATABRICKS_INSTALL_HINT) from e
    return Config, oauth_service_principal


def _is_auth_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like a Databricks auth/credential failure.

    Per WAREHOUSE_AUTH_BRIEF §3, auth failures generally surface as
    ``RequestError`` / ``OperationalError`` wrapping HTTP 401/403. We match on
    the driver exception class NAMES (no hard import of ``databricks.sql.exc``)
    plus the (credential-free) HTTP status / keyword in the message.
    """
    name = type(exc).__name__
    if name in {"RequestError", "OperationalError"}:
        text = str(exc).lower()
        if (
            "401" in text
            or "403" in text
            or "unauthorized" in text
            or "forbidden" in text
            or "authentication" in text
            or "invalid access token" in text
            or "credential" in text
        ):
            return True
    return False


def _is_timeout_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like a statement / socket timeout.

    Per WAREHOUSE_AUTH_BRIEF §3, a server-side statement timeout surfaces as
    ``ServerOperationError`` with message ``DEADLINE_EXCEEDED: This operation
    took too long...``. A connection-level ``socket_timeout`` overrun surfaces
    as a socket / ``TimeoutError``. Match on class name + message so the
    mapping holds without importing ``databricks.sql.exc``.
    """
    if isinstance(exc, TimeoutError):
        return True
    name = type(exc).__name__
    if name in {"ServerOperationError", "TimeoutError"}:
        return True
    text = str(exc).lower()
    return (
        "deadline_exceeded" in text
        or "timed out" in text
        or "timeout" in text
        or "operation took too long" in text
    )


class DatabricksAdapter:
    """Databricks SQL-warehouse adapter (§12) over ``databricks-sql-connector``.

    Construct with the connection params as keyword args, e.g.::

        # PAT
        DatabricksAdapter(
            server_hostname="adb-1234.5.azuredatabricks.net",
            http_path="/sql/1.0/warehouses/abc123",
            access_token="dapi...",
        )

        # OAuth U2M (browser)
        DatabricksAdapter(
            server_hostname="...", http_path="...",
            auth_method="oauth_u2m",
        )

        # OAuth M2M (service principal)
        DatabricksAdapter(
            server_hostname="...", http_path="...",
            client_id="...", client_secret="...",
        )

    The connection is created lazily on the first real-method call; nothing
    touches the network at construction. Optional ``catalog`` / ``schema``
    kwargs set Unity Catalog defaults; SQL may also fully-qualify objects as
    ``catalog.schema.table`` (this adapter never parses table names).
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
                    f"Unknown Databricks auth_method {method!r}; "
                    f"expected one of {sorted(_AUTH_SURFACES)}"
                )
            return method
        # Infer from supplied credential keys.
        if self._conn_params.get("access_token") is not None:
            return "pat"
        if (
            self._conn_params.get("client_id") is not None
            and self._conn_params.get("client_secret") is not None
        ):
            return "oauth_m2m"
        if self._conn_params.get("auth_type") == "databricks-oauth":
            return "oauth_u2m"
        # Nothing identifiable — refuse without leaking the dict.
        raise AdapterError(
            "Could not determine Databricks auth method from connection params; "
            f"set auth_method to one of {sorted(_AUTH_SURFACES)}"
        )

    def _build_connect_kwargs(self, conn_params: dict[str, Any]) -> dict[str, Any]:
        """Map a connection dict to ``databricks.sql.connect`` kwargs.

        Always emits ``server_hostname`` + ``http_path`` (the connector
        requires both) plus optional Unity Catalog defaults (``catalog`` /
        ``schema``), then layers the auth-surface kwargs:

        * ``pat`` → ``access_token``
        * ``oauth_u2m`` → ``auth_type="databricks-oauth"`` (no secret)
        * ``oauth_m2m`` → ``credentials_provider=<callable>`` built from the
          SDK's ``Config(client_id, client_secret)`` + ``oauth_service_principal``

        Raises :class:`AdapterError` with a secret-free message for an unknown
        auth method or missing required connection fields.
        """
        method = self._resolve_auth_method()

        for required in ("server_hostname", "http_path"):
            if conn_params.get(required) is None:
                raise AdapterError(
                    f"Databricks connection requires {required!r} "
                    "(plus auth material)"
                )

        kwargs: dict[str, Any] = {
            "server_hostname": conn_params["server_hostname"],
            "http_path": conn_params["http_path"],
        }
        # Unity Catalog defaults (non-secret), only when present.
        for field in ("catalog", "schema"):
            if conn_params.get(field) is not None:
                kwargs[field] = conn_params[field]

        if method == "pat":
            if conn_params.get("access_token") is None:
                raise AdapterError(
                    "Databricks PAT auth requires 'access_token'"
                )
            kwargs["access_token"] = conn_params["access_token"]
        elif method == "oauth_u2m":
            kwargs["auth_type"] = "databricks-oauth"
        elif method == "oauth_m2m":
            client_id = conn_params.get("client_id")
            client_secret = conn_params.get("client_secret")
            if client_id is None or client_secret is None:
                raise AdapterError(
                    "Databricks OAuth M2M auth requires 'client_id' "
                    "and 'client_secret'"
                )
            kwargs["credentials_provider"] = self._build_m2m_provider(
                conn_params["server_hostname"], client_id, client_secret
            )
        else:  # pragma: no cover — _resolve_auth_method already guards this.
            raise AdapterError(f"Unknown Databricks auth_method {method!r}")

        return kwargs

    @staticmethod
    def _build_m2m_provider(
        server_hostname: str, client_id: str, client_secret: str
    ) -> Any:
        """Build the OAuth M2M ``credentials_provider`` callable.

        Uses the SDK's ``Config(host, client_id, client_secret)`` +
        ``oauth_service_principal`` (per WAREHOUSE_AUTH_BRIEF §3c). The SDK is
        an optional dependency, imported lazily only on this path; ``client_secret``
        is never logged.
        """
        Config, oauth_service_principal = _import_databricks_sdk_core()

        def credential_provider():  # pragma: no cover — exercised in live tests
            cfg = Config(
                host=f"https://{server_hostname}",
                client_id=client_id,
                client_secret=client_secret,
            )
            return oauth_service_principal(cfg)

        return credential_provider

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self, timeout_s: int = 30) -> Any:
        if self._conn is not None:
            return self._conn
        sql = _import_databricks_sql()
        connect_kwargs = self._build_connect_kwargs(self._conn_params)
        # Best-effort comms ceiling; the connector has no per-execute timeout.
        connect_kwargs["socket_timeout"] = int(timeout_s)
        try:
            self._conn = sql.connect(**connect_kwargs)
        except Exception as e:
            # Redact the connection dict before it can reach any log/exception.
            safe = _safe_conn(self._conn_params)
            if _is_auth_error(e):
                raise AuthExpiredError(
                    f"Databricks authentication failed for connection {safe!r}"
                ) from e
            raise AdapterError(
                f"Databricks failed to open connection {safe!r}"
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
        return "databricks"

    def execute(
        self,
        sql: str,
        max_rows: int = 10_000,
        timeout_s: int = 30,
    ) -> AdapterResult:
        """Run ``sql`` and return at most ``max_rows`` rows.

        ``bytes_scanned`` is always ``None`` — the connector does not surface
        scan stats (see module docstring). A statement / socket timeout maps to
        :class:`QueryTimeoutError`; auth rejection to :class:`AuthExpiredError`;
        anything else to :class:`AdapterError`.

        Unity Catalog three-level names (``catalog.schema.table``) pass through
        verbatim — this adapter never parses table names.
        """
        conn = self._connect(timeout_s=timeout_s)
        cursor = conn.cursor()
        started = time.monotonic()
        try:
            cursor.execute(sql)
            raw_rows = cursor.fetchmany(max_rows)
            description = cursor.description or []
        except Exception as e:
            cursor.close()
            if _is_timeout_error(e):
                raise QueryTimeoutError(
                    f"Databricks query exceeded timeout_s={timeout_s}"
                ) from e
            if _is_auth_error(e):
                raise AuthExpiredError(
                    "Databricks rejected credentials during execute "
                    "(token expired / revoked)"
                ) from e
            raise AdapterError(f"Databricks execute failed: {e}") from e
        finally:
            elapsed = time.monotonic() - started

        columns = [d[0] for d in description]
        rows: list[dict[str, Any]] = [dict(zip(columns, row)) for row in raw_rows]
        cursor.close()

        return AdapterResult(
            rows=rows,
            row_count=len(rows),
            bytes_scanned=None,  # not exposed by the databricks connector
            elapsed_seconds=elapsed,
            dialect="databricks",
        )

    def explain(self, sql: str) -> str:
        """Return the Databricks ``EXPLAIN`` plan text for ``sql``.

        Databricks supports ``EXPLAIN <query>`` (plan only, no reliable byte
        figure — see module docstring). The rows are flattened to one string.
        """
        conn = self._connect()
        cursor = conn.cursor()
        try:
            cursor.execute(f"EXPLAIN {sql}")
            rows = cursor.fetchall()
        except Exception as e:
            cursor.close()
            if _is_auth_error(e):
                raise AuthExpiredError(
                    "Databricks rejected credentials during EXPLAIN"
                ) from e
            raise AdapterError(f"Databricks EXPLAIN failed: {e}") from e
        cursor.close()

        chunks: list[str] = []
        for row in rows:
            chunks.append(" | ".join(str(cell) for cell in row))
        return "\n".join(chunks)

    def dry_run(self, sql: str) -> PreviewResult:
        """Return an empty :class:`PreviewResult` with an honest warning.

        The Databricks connector has no dry-run / byte-estimate call (per
        WAREHOUSE_AUTH_BRIEF §3). v0.1.1 surfaces the gap honestly — mirroring
        DuckDB / Snowflake — rather than reporting a misleading "0". Use
        :meth:`explain` for a plan or :meth:`execute` for actuals.
        """
        return PreviewResult(
            estimated_rows=None,
            estimated_bytes_scanned=None,
            estimated_cost_usd=None,
            warnings=[
                "Databricks has no free dry-run; estimates unavailable. "
                "Use adapter.explain() for a plan, or execute() for actuals."
            ],
        )


__all__ = ["DatabricksAdapter"]
