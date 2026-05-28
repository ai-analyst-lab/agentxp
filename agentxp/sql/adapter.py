"""Warehouse adapter protocol and result models for AgentXP v0.1.

Defines the BaseAdapter Protocol that every warehouse adapter must satisfy,
the pydantic result models returned by `execute` / `dry_run`, and the
exception hierarchy used across adapters. v0.1 ships the DuckDB adapter;
v0.1.1 adds Snowflake + BigQuery adapters that conform to the same shape.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 (adapters table).
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from agentxp.audit.redactor import redact


class AdapterError(Exception):
    """Base class for all warehouse adapter errors."""


class AuthExpiredError(AdapterError):
    """Raised when the warehouse rejects current credentials (expired token,
    revoked key, etc.). Callers should prompt for re-authentication."""


class QueryTimeoutError(AdapterError):
    """Raised when a query exceeds the configured `timeout_s` ceiling."""


class BytesLimitExceededError(AdapterError):
    """Raised when a dry-run or executed query is projected/known to scan
    more bytes than the caller's configured limit."""


class AdapterResult(BaseModel):
    """Materialised result of a successful `BaseAdapter.execute` call."""

    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, Any]]
    row_count: int
    bytes_scanned: Optional[int] = None
    elapsed_seconds: float
    dialect: str


class PreviewResult(BaseModel):
    """Estimate returned by `BaseAdapter.dry_run` before paying for execution."""

    model_config = ConfigDict(extra="forbid")

    estimated_rows: Optional[int] = None
    estimated_bytes_scanned: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    warnings: list[str] = []


@runtime_checkable
class BaseAdapter(Protocol):
    """All warehouse adapters implement this. v0.1 ships duckdb; v0.1.1
    ships snowflake + bigquery."""

    def execute(
        self, sql: str, max_rows: int = 10_000, timeout_s: int = 30
    ) -> AdapterResult:
        ...

    def explain(self, sql: str) -> str:
        ...

    def dry_run(self, sql: str) -> PreviewResult:
        ...

    def get_dialect(self) -> str:
        ...

    def close(self) -> None:
        ...


# Connection-dict keys whose values are credential material by definition.
# These get blanket-redacted; the regex-based `redact` only catches values
# with internal structure (Bearer tokens, JWTs, URLs with creds, etc.) and
# would otherwise pass a bare `"secret123"` through unchanged.
#
# THIS IS THE SINGLE CANONICAL SET. Adapters and connect wizards MUST NOT keep
# their own local secret-key sets — every secret-bearing connection-dict key
# that any adapter's ``_build_connect_kwargs`` / ``_build_client`` or any
# wizard's ``collect()`` accepts is listed here so the shared
# :func:`_redact_creds_for_log` scrubs it. (A drift between three local sets is
# exactly how ``access_token`` / ``client_secret`` / ``credentials_info`` once
# fell out of the canonical set and leaked.) ``client_id`` is intentionally
# absent — a client id is not a secret.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_key",
        "access_key_id",
        "secret_key",
        "secret_access_key",
        "private_key",
        "private_key_path",
        "auth",
        "authorization",
        # BigQuery inline service-account dicts (carry a private key).
        "credentials_info",
        "service_account_info",
        # Databricks PAT.
        "access_token",
        # Databricks OAuth M2M service-principal secret.
        "client_secret",
        # Snowflake key-pair file passphrase.
        "private_key_file_pwd",
    }
)


def _redact_creds_for_log(creds: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``creds`` safe to write to the audit log.

    Redaction rules, applied per key/value:

    * Any key whose name is in :data:`_SENSITIVE_KEYS` is replaced with
      ``"[REDACTED]"`` REGARDLESS of value type — ``str``, ``bytes`` (a
      Snowflake key-pair ``private_key`` is DER bytes), ``dict`` (an inline
      service-account dict), anything. The regex redactor only fires on values
      with recognisable structure, so a bare ``"secret123"`` — or raw key bytes
      — would otherwise pass through.
    * A nested ``dict`` value (e.g. an inline service-account dict stored under
      a NON-sensitive key) is recursed into, so its own sensitive entries
      (``private_key`` …) are scrubbed by the same rules.
    * Non-sensitive ``str`` values go through :func:`agentxp.audit.redactor.redact`
      (so embedded JWTs, bearer tokens, URLs with creds, etc. are scrubbed).
    * Non-sensitive non-str values pass through untouched (ports, booleans).
    """
    out: dict[str, Any] = {}
    for key, value in creds.items():
        if key.lower() in _SENSITIVE_KEYS:
            # Blanket-redact: any type, including bytes / dict.
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            # Recurse so a nested dict's own sensitive entries are scrubbed.
            out[key] = _redact_creds_for_log(value)
        elif isinstance(value, str):
            out[key] = redact(value)
        else:
            out[key] = value
    return out
