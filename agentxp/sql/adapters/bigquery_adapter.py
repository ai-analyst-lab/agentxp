"""BigQuery warehouse adapter for AgentXP v0.1.1 (§12).

Implements the :class:`agentxp.sql.adapter.BaseAdapter` Protocol against the
``google-cloud-bigquery`` Python client. Replaces the v0.1 stub.

Behavioural notes:

* **Lazy connect.** The adapter does not build a ``bigquery.Client`` at
  construction time. The first call to :meth:`execute` / :meth:`explain` /
  :meth:`dry_run` builds the client; subsequent calls reuse it. :meth:`close`
  releases it.
* **Two auth surfaces** (see :meth:`_build_client`):
    1. **ADC** — no explicit credentials. ``bigquery.Client(project=...)``
       picks up Application Default Credentials (``GOOGLE_APPLICATION_CREDENTIALS``
       env var, ``gcloud auth application-default login`` user creds, or an
       attached service account on GCP compute). This is the safer default —
       no key material lives in the app.
    2. **Service-account JSON** — either a path on disk (``credentials_path`` /
       ``service_account_path``) or an inline dict (``credentials_info`` /
       ``service_account_info``). Loaded via
       ``service_account.Credentials.from_service_account_file`` /
       ``.from_service_account_info`` and handed to
       ``bigquery.Client(credentials=..., project=...)``.
* **bytes_scanned.** Read from ``query_job.total_bytes_processed`` after the
  job completes (Optional[int]).
* **Byte ceiling.** When the caller passes ``maximum_bytes_billed`` (bytes),
  it is set on the ``QueryJobConfig``; BigQuery fails the job *before running*
  if the scan would exceed it (nothing is billed). That rejection
  (``Forbidden`` reason ``bytesBilledLimitExceeded`` / ``BadRequest``) maps to
  :class:`BytesLimitExceededError`.
* **Real timeout.** ``QueryJobConfig.job_timeout_ms`` is the server-side
  ceiling (derived from ``timeout_s``). A client-side poll timeout
  (``concurrent.futures.TimeoutError`` from ``result(timeout=...)``) also maps
  to :class:`QueryTimeoutError`.
* **dry_run.** BigQuery's strength: ``QueryJobConfig(dry_run=True,
  use_query_cache=False)`` returns ``total_bytes_processed`` with *nothing
  billed*. We turn that into ``estimated_bytes_scanned`` plus an
  ``estimated_cost_usd`` using the on-demand US rate (see
  :data:`_ON_DEMAND_USD_PER_TIB`).
* **explain.** BigQuery has no ``EXPLAIN`` keyword. We surface the dry-run
  byte estimate as the "plan" text (builder's call), which is the cheapest
  pre-flight signal the API offers.
* **Credential safety.** Every connection dict — especially an inline
  service-account dict, which contains a private key — passes through
  :func:`agentxp.sql.adapter._redact_creds_for_log` before any log line or
  exception message. Service-account JSON contents are NEVER logged.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 (adapters table).
Ground-truth reference: research/v0.1.1-warehouse-auth/WAREHOUSE_AUTH_BRIEF.md §2.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from agentxp.sql.adapter import (
    AdapterError,
    AdapterResult,
    AuthExpiredError,
    BytesLimitExceededError,
    PreviewResult,
    QueryTimeoutError,
    _redact_creds_for_log,
)

logger = logging.getLogger(__name__)


def _safe_conn(conn_params: dict[str, Any]) -> dict[str, Any]:
    """Redact a connection dict for logs/exceptions, including the nested
    service-account dict.

    ``_redact_creds_for_log`` only scrubs *top-level* string values; a BigQuery
    SA dict arrives nested under ``credentials_info`` / ``service_account_info``
    and would otherwise pass through with its ``private_key`` intact. Replace
    any inline SA dict wholesale before delegating to the shared redactor.
    """
    cleaned: dict[str, Any] = {}
    for key, value in conn_params.items():
        if key in ("credentials_info", "service_account_info") and isinstance(
            value, dict
        ):
            cleaned[key] = "[REDACTED]"
        else:
            cleaned[key] = value
    return _redact_creds_for_log(cleaned)


_BIGQUERY_INSTALL_HINT = (
    "google-cloud-bigquery is an optional dependency. Install it with:\n"
    "    pip install 'agentxp[bigquery]'\n"
    "or directly:\n"
    "    pip install google-cloud-bigquery"
)

# On-demand BigQuery query pricing assumption: US multi-region on-demand rate,
# $6.25 per TiB scanned (2^40 bytes). This is the *list* on-demand rate and may
# NOT match a given user's contract (flat-rate / capacity / editions pricing,
# regional differences, or negotiated discounts). The cost figure from
# :meth:`dry_run` is therefore an order-of-magnitude estimate, not a bill.
_ON_DEMAND_USD_PER_TIB = 6.25
_BYTES_PER_TIB = 2 ** 40

# OAuth scope required for BigQuery query jobs (used when building SA creds).
_BQ_SCOPES = ("https://www.googleapis.com/auth/bigquery",)


def _import_bigquery():
    """Import ``google.cloud.bigquery`` lazily so this module imports cleanly
    without the driver installed (Tier-A tests patch at this boundary)."""
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError as e:  # pragma: no cover — depends on env
        raise ImportError(_BIGQUERY_INSTALL_HINT) from e
    return bigquery


def _import_service_account():
    """Import ``google.oauth2.service_account`` lazily."""
    try:
        from google.oauth2 import service_account  # type: ignore
    except ImportError as e:  # pragma: no cover — depends on env
        raise ImportError(_BIGQUERY_INSTALL_HINT) from e
    return service_account


def _is_auth_error(exc: BaseException) -> bool:
    """Heuristic: does ``exc`` look like a BigQuery auth/credential failure?

    The driver's auth exceptions live across two packages
    (``google.api_core.exceptions.{Unauthorized,Forbidden}``,
    ``google.auth.exceptions.{DefaultCredentialsError,RefreshError}``) which we
    do not hard-import. Match on class name + HTTP status so the mapping holds
    without importing google packages at module load.
    """
    name = type(exc).__name__
    if name in {"Unauthorized", "DefaultCredentialsError", "RefreshError"}:
        return True
    if name == "Forbidden":
        # Forbidden(403) is used for BOTH auth-denied and bytesBilledLimitExceeded.
        # Over-scan is handled first by _is_bytes_limit_error; anything else 403
        # is treated as an auth/permission problem.
        return not _is_bytes_limit_error(exc)
    return False


def _is_bytes_limit_error(exc: BaseException) -> bool:
    """Does ``exc`` indicate the maximum_bytes_billed ceiling was exceeded?

    BigQuery surfaces this as ``Forbidden`` (403, reason
    ``bytesBilledLimitExceeded``) on most paths and occasionally ``BadRequest``
    (400). We match the reason string defensively against the message.
    """
    name = type(exc).__name__
    if name not in {"Forbidden", "BadRequest"}:
        return False
    text = str(exc).lower()
    return "bytesbilledlimitexceeded" in text or "maximum bytes billed" in text


def _is_timeout_error(exc: BaseException) -> bool:
    """Does ``exc`` indicate a job/poll timeout?"""
    if isinstance(exc, TimeoutError):  # concurrent.futures.TimeoutError subclasses this
        return True
    name = type(exc).__name__
    if name == "TimeoutError":
        return True
    text = str(exc).lower()
    return "job_timeout" in text or "timeout" in text and "exceeded" in text


class BigQueryAdapter:
    """ADC / service-account BigQuery adapter (§12).

    Construct credential-free (``BigQueryAdapter()`` → ADC) or with explicit
    connection params::

        BigQueryAdapter(project="my-proj")                       # ADC
        BigQueryAdapter(project="p", credentials_path="key.json")  # SA file
        BigQueryAdapter(project="p", credentials_info={...})       # SA dict

    The client is built lazily on first use so constructing an adapter never
    touches the network or reads a key file.
    """

    def __init__(self, **conn_params: Any) -> None:
        self._conn_params = conn_params
        self._client: Any | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _build_client(self, conn_params: dict[str, Any]) -> Any:
        """Construct a ``bigquery.Client`` for the two supported auth surfaces.

        (a) **ADC** — no ``credentials_path`` / ``credentials_info``: build
            ``bigquery.Client(project=...)`` and let ``google.auth`` resolve
            Application Default Credentials.
        (b) **Service-account JSON** — a path or an inline dict: build
            ``service_account.Credentials`` and pass to the client.

        Any failure here is redacted (the SA dict carries a private key) and
        re-raised as :class:`AuthExpiredError` (credential problems) or
        :class:`AdapterError`.
        """
        bigquery = _import_bigquery()

        project = conn_params.get("project") or conn_params.get("project_id")
        sa_path = (
            conn_params.get("credentials_path")
            or conn_params.get("service_account_path")
        )
        sa_info = (
            conn_params.get("credentials_info")
            or conn_params.get("service_account_info")
        )

        try:
            if sa_info is not None:
                service_account = _import_service_account()
                creds = service_account.Credentials.from_service_account_info(
                    sa_info, scopes=list(_BQ_SCOPES)
                )
                return bigquery.Client(
                    credentials=creds,
                    project=project or getattr(creds, "project_id", None),
                )
            if sa_path is not None:
                service_account = _import_service_account()
                creds = service_account.Credentials.from_service_account_file(
                    sa_path, scopes=list(_BQ_SCOPES)
                )
                return bigquery.Client(
                    credentials=creds,
                    project=project or getattr(creds, "project_id", None),
                )
            # (a) ADC path — no key material in the app.
            return bigquery.Client(project=project)
        except Exception as e:
            # Redact before the message ever crosses a log / exception boundary.
            safe = _safe_conn(conn_params)
            if _is_auth_error(e):
                raise AuthExpiredError(
                    f"BigQuery authentication failed for conn={safe}: "
                    f"{type(e).__name__}"
                ) from e
            raise AdapterError(
                f"BigQuery client construction failed for conn={safe}: "
                f"{type(e).__name__}"
            ) from e

    def _connect(self) -> Any:
        if self._client is not None:
            return self._client
        self._client = self._build_client(self._conn_params)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                # bigquery.Client.close() exists on modern drivers; guard for
                # older ones that lack it.
                close = getattr(self._client, "close", None)
                if callable(close):
                    close()
            finally:
                self._client = None

    # ------------------------------------------------------------------
    # BaseAdapter Protocol
    # ------------------------------------------------------------------

    def get_dialect(self) -> str:
        return "bigquery"

    def execute(
        self,
        sql: str,
        max_rows: int = 10_000,
        timeout_s: int = 30,
    ) -> AdapterResult:
        """Run ``sql`` and return at most ``max_rows`` rows.

        Maps BigQuery failures onto the AgentXP exception hierarchy:

        * over ``maximum_bytes_billed`` → :class:`BytesLimitExceededError`
        * auth/credential rejection → :class:`AuthExpiredError`
        * job / poll timeout → :class:`QueryTimeoutError`
        * everything else → :class:`AdapterError`

        Pass a byte ceiling via the connection param ``maximum_bytes_billed``
        (int bytes) so BigQuery rejects an over-scan before billing.
        """
        bigquery = _import_bigquery()
        client = self._connect()

        job_config = bigquery.QueryJobConfig(
            job_timeout_ms=int(timeout_s * 1000),
        )
        ceiling = self._conn_params.get("maximum_bytes_billed")
        if ceiling is not None:
            job_config.maximum_bytes_billed = int(ceiling)

        started = time.monotonic()
        try:
            query_job = client.query(sql, job_config=job_config)
            row_iter = query_job.result(timeout=timeout_s, max_results=max_rows)
        except Exception as e:
            raise self._map_query_error(e, "execute") from e
        elapsed = time.monotonic() - started

        rows: list[dict[str, Any]] = []
        for i, row in enumerate(row_iter):
            if i >= max_rows:
                break
            rows.append(dict(row))

        bytes_scanned = getattr(query_job, "total_bytes_processed", None)

        return AdapterResult(
            rows=rows,
            row_count=len(rows),
            bytes_scanned=bytes_scanned,
            elapsed_seconds=elapsed,
            dialect="bigquery",
        )

    def explain(self, sql: str) -> str:
        """Return a plan-ish string for ``sql``.

        BigQuery has no ``EXPLAIN`` keyword. The cheapest pre-flight signal is
        the dry-run byte estimate, so we surface that as the explain text
        (builder's call — documented in the module docstring).
        """
        pv = self.dry_run(sql)
        est = pv.estimated_bytes_scanned
        cost = pv.estimated_cost_usd
        if est is None:
            return "BigQuery has no EXPLAIN; dry-run estimate unavailable."
        return (
            "BigQuery has no EXPLAIN keyword; showing dry-run estimate.\n"
            f"estimated_bytes_scanned={est}\n"
            f"estimated_cost_usd={cost}"
        )

    def dry_run(self, sql: str) -> PreviewResult:
        """Issue a BigQuery dry-run job and return a cost/byte estimate.

        ``QueryJobConfig(dry_run=True, use_query_cache=False)`` returns
        ``total_bytes_processed`` with nothing billed. ``estimated_cost_usd``
        is ``bytes / 2**40 * _ON_DEMAND_USD_PER_TIB`` — see the module-level
        rate assumption.
        """
        bigquery = _import_bigquery()
        client = self._connect()

        job_config = bigquery.QueryJobConfig(
            dry_run=True,
            use_query_cache=False,
        )
        try:
            query_job = client.query(sql, job_config=job_config)
        except Exception as e:
            raise self._map_query_error(e, "dry_run") from e

        est_bytes = getattr(query_job, "total_bytes_processed", None)
        warnings: list[str] = []
        est_cost: Optional[float] = None
        if est_bytes is not None:
            est_cost = (est_bytes / _BYTES_PER_TIB) * _ON_DEMAND_USD_PER_TIB
            warnings.append(
                f"Cost estimated at the on-demand US list rate "
                f"(${_ON_DEMAND_USD_PER_TIB}/TiB); your contract pricing "
                f"(flat-rate / editions / regional / negotiated) may differ."
            )
        else:
            warnings.append(
                "BigQuery dry-run returned no total_bytes_processed; "
                "estimate unavailable."
            )

        return PreviewResult(
            estimated_rows=None,  # BigQuery dry-run gives bytes, not row counts
            estimated_bytes_scanned=est_bytes,
            estimated_cost_usd=est_cost,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal: error mapping
    # ------------------------------------------------------------------

    def _map_query_error(self, exc: BaseException, where: str) -> AdapterError:
        """Map a driver exception onto the AgentXP exception hierarchy.

        Order matters: a byte-ceiling rejection arrives as ``Forbidden`` (403),
        the same class used for auth-denied, so check the byte ceiling first.
        The redacted conn dict is included so the byte ceiling is visible in
        logs WITHOUT leaking the SA private key.
        """
        safe = _safe_conn(self._conn_params)
        if _is_bytes_limit_error(exc):
            return BytesLimitExceededError(
                f"BigQuery {where} exceeded maximum_bytes_billed for conn={safe}: "
                f"{type(exc).__name__}"
            )
        if _is_timeout_error(exc):
            return QueryTimeoutError(
                f"BigQuery {where} timed out for conn={safe}: "
                f"{type(exc).__name__}"
            )
        if _is_auth_error(exc):
            return AuthExpiredError(
                f"BigQuery {where} auth failed for conn={safe}: "
                f"{type(exc).__name__}"
            )
        return AdapterError(
            f"BigQuery {where} failed for conn={safe}: {type(exc).__name__}"
        )


__all__ = ["BigQueryAdapter"]
