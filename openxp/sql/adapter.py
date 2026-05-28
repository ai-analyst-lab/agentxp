"""Warehouse adapter protocol and result models for OpenXP v0.1.

Defines the BaseAdapter Protocol that every warehouse adapter must satisfy,
the pydantic result models returned by `execute` / `dry_run`, and the
exception hierarchy used across adapters. v0.1 ships the DuckDB adapter;
v0.1.1 adds Snowflake + BigQuery adapters that conform to the same shape.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 (adapters table).
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from openxp.audit.redactor import redact


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
    }
)


def _redact_creds_for_log(creds: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``creds`` safe to write to the audit log.

    Apply :func:`openxp.audit.redactor.redact` to every string value (so
    embedded JWTs, bearer tokens, URLs with creds, etc. get scrubbed). On
    top of that, any key whose name matches a known-sensitive marker
    (``password``, ``token``, ``api_key`` …) has its value replaced with
    ``[REDACTED]`` regardless of contents, because the regex redactor only
    fires on values with recognisable structure.

    Non-string values pass through untouched (ports, booleans, ints).
    """
    out: dict[str, Any] = {}
    for key, value in creds.items():
        if isinstance(value, str):
            if key.lower() in _SENSITIVE_KEYS:
                out[key] = "[REDACTED]"
            else:
                out[key] = redact(value)
        else:
            out[key] = value
    return out
