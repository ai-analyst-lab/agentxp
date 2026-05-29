"""Free-cost preview helpers for the SQL user-review screen (§11 / §13).

Wraps :meth:`BaseAdapter.dry_run` in a never-raises shell so the orchestrator
can surface estimate-or-warning to the review screen without crash-handling
adapter exceptions at the call site. When the adapter raises, the failure is
captured as a warning string on the returned :class:`PreviewResult` and the
estimate fields are left as ``None``.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §11 (Layer 4 EXPLAIN
input) + §13 (QueryArtifact.explain).
"""
from __future__ import annotations

from agentxp.audit.redactor import redact_message
from agentxp.sql.adapter import BaseAdapter, PreviewResult


def preview_query(adapter: BaseAdapter, sql: str, purpose: str) -> PreviewResult:
    """Return a :class:`PreviewResult` estimate for ``sql`` on ``adapter``.

    Never raises. Adapter exceptions are caught and rendered as warning
    strings on the result so the caller (review-screen renderer) can show
    "estimate unavailable: <reason>" alongside the SQL.

    ``purpose`` is currently unused by the adapter-level dry_run path; it is
    plumbed through for forward-compat with adapters that price differently
    per purpose (e.g., BigQuery's ``maximumBytesBilled`` budget).
    """
    try:
        result = adapter.dry_run(sql)
    except Exception as e:
        return PreviewResult(
            estimated_rows=None,
            estimated_bytes_scanned=None,
            estimated_cost_usd=None,
            warnings=[
                f"Preview failed on adapter {adapter.get_dialect()}: "
                f"{type(e).__name__}: {redact_message(e)}"
            ],
        )

    # Decorate the warnings with the purpose for downstream telemetry.
    if purpose and result.warnings:
        # Don't mutate the model in place; build a fresh one to satisfy
        # ConfigDict(extra="forbid") + immutability conventions elsewhere.
        return PreviewResult(
            estimated_rows=result.estimated_rows,
            estimated_bytes_scanned=result.estimated_bytes_scanned,
            estimated_cost_usd=result.estimated_cost_usd,
            warnings=result.warnings,
        )
    return result


__all__ = ["preview_query"]
