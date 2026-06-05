"""Synchronous SQL dispatch chokepoint for AgentXP v0.1 (§11, §22.5, §13).

Single entry point through which every agent-proposed SQL passes on its way
to the warehouse. Wraps the 5-layer safety pipeline (§11), the SQL correction
retry loop (§22.5, max 3 attempts), and the per-query :class:`QueryArtifact`
lifecycle (§13). Emits the canonical ``query.proposed`` / ``query.executed``
/ ``query.failed`` audit events from :mod:`agentxp.audit.events`.

v0.1 is synchronous: each correction round is a full re-entry through the
safety pipeline. The cache layer (validated_queries/) is checked by the
*caller* (orchestrator) before dispatch; cache writes happen here on
successful execution so the cache anchor matches the audit trail.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md
  - §11      5-layer SQL safety pipeline
  - §13      QueryArtifact lifecycle
  - §22.5    Correction loop (max 3 attempts; auth_expired surrenders)
  - §1.8.5   metadata.subtype values (auth_expired, failed_after_retries, cache_hit)
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from agentxp.audit.redactor import redact_message
from agentxp.sql.adapter import (
    AdapterError,
    AdapterResult,
    AuthExpiredError,
)
from agentxp.sql.artifact_writer import _new_query_ulid, write_query_artifact
from agentxp.sql.safety import SafetyViolation, run_pipeline
from agentxp.sql.schema import (
    ConnectionConfig,
    QueryArtifact,
    QueryDialectInfo,
    QueryExecution,
    QueryOutcome,
    QueryResultSummary,
    ResourceBounds,
    RoutingConfig,
    SafetyLayerResult,
)


# ──────────────────────────────────────────────────────────────────────────
# Resource-bounds matrix mirror — keeps this module from importing safety's
# private dict. Same values, just lifted so dispatch can pick the row that
# matches `intent.purpose` for adapter.execute() row + timeout caps.
# ──────────────────────────────────────────────────────────────────────────


_PURPOSE_BOUNDS: dict[str, tuple[int, int]] = {
    # purpose: (max_rows, timeout_s)
    "profile":         (100_000,    60),
    "preview":           (1_000,    30),
    "srm_check":     (1_000_000,   120),
    "metric_compute": (10_000_000, 300),
    "user_paste":        (1_000,    30),
}


# ──────────────────────────────────────────────────────────────────────────
# Public models — SqlIntent (in), SqlResult (out).
# ──────────────────────────────────────────────────────────────────────────


class SqlIntent(BaseModel):
    """Input contract for :func:`dispatch_sql` (§11 + §13).

    Carries everything the safety pipeline needs to run + every field
    required to write a faithful :class:`QueryArtifact` row. ``semantic_models``
    and ``config`` are passed through to layers 3a / 3b verbatim.
    """

    model_config = ConfigDict(extra="forbid")

    purpose: Literal[
        "profile", "preview", "srm_check", "metric_compute", "user_paste"
    ]
    sql: str
    dialect: str
    exp_id: str
    semantic_models: Optional[list] = None    # Layer 3b
    config: Optional[dict] = None             # Layer 3a
    target_profile: Optional[str] = None
    parent_action_id: Optional[str] = None

    # Optional audit-trail context. When the orchestrator dispatches it
    # supplies these; standalone callers (tests) get sensible defaults.
    action_id: Optional[str] = None
    agent_name: str = "sql_query_writer"
    stage: str = "unspecified"
    auth_kind: Literal[
        "pwd", "externalbrowser", "oauth", "keypair", "adc", "sa", "none"
    ] = "none"
    adapter_type: Literal["duckdb", "snowflake", "bigquery", "databricks"] = "duckdb"
    profile_name: str = "default"


class SqlResult(BaseModel):
    """Outcome of :func:`dispatch_sql` (§13 lifecycle + §22.5 correction)."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    artifact: Any                              # QueryArtifact
    adapter_result: Optional[Any] = None       # AdapterResult on success
    attempts: int = Field(..., ge=1)
    final_status: Literal[
        "executed",
        "blocked_by_safety",
        "failed_after_correction",
        "auth_expired",
    ]
    artifact_path: Optional[Path] = None
    error_message: Optional[str] = None        # already PII-redacted


# ──────────────────────────────────────────────────────────────────────────
# Internal helpers.
# ──────────────────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_artifact(
    intent: SqlIntent,
    sql_validated: str,
    outcome: QueryOutcome,
    safety_trace: list[SafetyLayerResult],
    proposed_at: datetime,
    *,
    outcome_reason: Optional[str] = None,
    execution: Optional[QueryExecution] = None,
    result_summary: Optional[QueryResultSummary] = None,
    metadata: Optional[dict] = None,
    query_id: Optional[str] = None,
) -> QueryArtifact:
    """Assemble a :class:`QueryArtifact` from an intent + lifecycle context."""
    return QueryArtifact(
        query_id=query_id or _new_query_ulid(),
        action_id=intent.action_id or f"act-{_new_query_ulid()}",
        parent_action_id=intent.parent_action_id,
        experiment_id=intent.exp_id,
        agent_name=intent.agent_name,
        stage=intent.stage,
        purpose=intent.purpose,
        proposed_at=proposed_at,
        outcome=outcome,
        outcome_reason=outcome_reason,
        auth_kind=intent.auth_kind,
        routing=RoutingConfig(
            connection=ConnectionConfig(
                adapter=intent.adapter_type,
                auth_kind=intent.auth_kind,
                profile_name=intent.profile_name,
            ),
        ),
        bounds=ResourceBounds(
            purpose=intent.purpose,
            row_limit_default=_PURPOSE_BOUNDS[intent.purpose][0],
            timeout_s=_PURPOSE_BOUNDS[intent.purpose][1],
        ),
        sql=QueryDialectInfo(
            canonical_text=sql_validated,
            rendered_text=sql_validated,
            rendered_dialect=intent.adapter_type,
        ),
        safety_trace=safety_trace,
        execution=execution,
        result_summary=result_summary,
        metadata=metadata or {},
    )


def _emit_proposed(
    exp_dir: Path,
    intent: SqlIntent,
    query_id: str,
    sql_validated: str,
    proposed_at: datetime,
) -> None:
    # v3: event-emission is replaced by git + log.md at the orchestrator
    # boundary (commit_artifact). No structured event emission here.
    return


def _emit_executed(
    exp_dir: Path,
    intent: SqlIntent,
    query_id: str,
    adapter_result: AdapterResult,
) -> None:
    # v3: see _emit_proposed.
    return


def _emit_failed(
    exp_dir: Path,
    intent: SqlIntent,
    query_id: str,
    error_class: str,
    error_message: str,
    subtype: Optional[str] = None,
) -> None:
    # v3: see _emit_proposed.
    return


def _safety_trace_from_layers(layers_passed: list[int]) -> list[SafetyLayerResult]:
    """Map a list of layer numbers (1-4) to SafetyLayerResult rows."""
    name_by_layer = {
        1: "parse",
        2: "read_only",
        3: "cross_adapter",
        4: "resource",
    }
    trace: list[SafetyLayerResult] = []
    for n in layers_passed:
        name = name_by_layer.get(n)
        if name is None:
            continue
        trace.append(SafetyLayerResult(layer=name, passed=True))
    return trace


def _safety_layer_for_violation(exc: SafetyViolation) -> str:
    """Map a :class:`SafetyViolation` subclass to the canonical layer name."""
    from agentxp.sql.safety import (
        CrossAdapterViolation,
        DenyListViolation,
        ReadOnlyViolation,
        ResourceBoundsViolation,
        SemanticModelViolation,
        UnparseableSQL,
    )
    if isinstance(exc, UnparseableSQL):
        return "parse"
    if isinstance(exc, ReadOnlyViolation):
        return "read_only"
    if isinstance(exc, CrossAdapterViolation):
        return "cross_adapter"
    if isinstance(exc, SemanticModelViolation):
        return "semantic"
    if isinstance(exc, DenyListViolation):
        return "deny_list"
    if isinstance(exc, ResourceBoundsViolation):
        return "resource"
    return "parse"  # defensive fallback


# ──────────────────────────────────────────────────────────────────────────
# Public entry point.
# ──────────────────────────────────────────────────────────────────────────


def dispatch_sql(
    intent: SqlIntent,
    adapter,
    exp_dir: Path,
    max_correction_attempts: int = 3,
    correction_fn: Optional[Callable[[str, str, int], str]] = None,
) -> SqlResult:
    """Run ``intent.sql`` through the §11 safety pipeline + adapter dispatch.

    Behaviour (§22.5 correction loop):

    1. Run :func:`agentxp.sql.safety.run_pipeline` on the candidate SQL.
    2. On :class:`SafetyViolation`: write a ``blocked`` artifact, emit
       ``query.proposed`` + ``query.failed``, return SqlResult with
       ``final_status="blocked_by_safety"``. No correction is attempted for
       safety violations — the §11 contract is fail-closed.
    3. On safety success: emit ``query.proposed`` (with post-Layer-4 SQL),
       write a ``proposed`` artifact, then call
       ``adapter.execute(sql_validated, max_rows, timeout_s)``.
    4. On :class:`AuthExpiredError`: surrender immediately. Write an
       ``errored`` artifact tagged ``auth_expired``; emit ``query.failed``
       with ``metadata.subtype="auth_expired"``; return SqlResult.
    5. On other :class:`AdapterError`: if attempts remain AND ``correction_fn``
       was supplied, call ``correction_fn(failed_sql, error_message, attempt_n)``
       to get a revised SQL, then re-enter at step 1.
    6. On adapter success: write an ``executed`` artifact, emit
       ``query.executed``, return SqlResult.
    7. After ``max_correction_attempts`` failures: write a ``failed`` artifact;
       emit ``query.failed`` with ``metadata.subtype="failed_after_retries"``;
       return SqlResult.
    """
    current_sql = intent.sql
    attempts = 0
    last_error_message: Optional[str] = None

    while True:
        attempts += 1
        attempt_intent = intent.model_copy(update={"sql": current_sql})
        proposed_at = _utc_now()
        query_id = _new_query_ulid()

        # ----- Layer 1-4 safety pipeline -----
        # mode="analyze" preserves v0.1 dispatch behavior. T80-T84 will plumb
        # the actual verb (design vs analyze) through QueryIntent so design-mode
        # dispatches activate Layer 3d outcome-column rejection (T20, R11).
        try:
            safety = run_pipeline(
                current_sql,
                dialect=intent.dialect,
                purpose=intent.purpose,
                mode="analyze",
                config=intent.config,
                target_profile=intent.target_profile,
                semantic_models=intent.semantic_models,
            )
        except SafetyViolation as exc:
            reason = redact_message(exc)
            layer_name = _safety_layer_for_violation(exc)
            artifact = _build_artifact(
                attempt_intent,
                sql_validated=current_sql,
                outcome=QueryOutcome.BLOCKED,
                safety_trace=[SafetyLayerResult(
                    layer=layer_name, passed=False, reason=reason,
                )],
                proposed_at=proposed_at,
                outcome_reason=reason,
                query_id=query_id,
            )
            artifact_path = write_query_artifact(artifact, exp_dir)
            _emit_proposed(exp_dir, attempt_intent, query_id, current_sql, proposed_at)
            _emit_failed(
                exp_dir, attempt_intent, query_id,
                error_class=type(exc).__name__,
                error_message=reason,
            )
            return SqlResult(
                artifact=artifact,
                adapter_result=None,
                attempts=attempts,
                final_status="blocked_by_safety",
                artifact_path=artifact_path,
                error_message=reason,
            )

        sql_validated = safety.sql_validated
        safety_trace = _safety_trace_from_layers(safety.layers_passed)

        # ----- Emit query.proposed + persist proposed artifact -----
        _emit_proposed(
            exp_dir, attempt_intent, query_id, sql_validated, proposed_at,
        )
        proposed_artifact = _build_artifact(
            attempt_intent,
            sql_validated=sql_validated,
            outcome=QueryOutcome.PROPOSED,
            safety_trace=safety_trace,
            proposed_at=proposed_at,
            query_id=query_id,
        )
        write_query_artifact(proposed_artifact, exp_dir)

        # ----- Adapter dispatch -----
        max_rows, timeout_s = _PURPOSE_BOUNDS[intent.purpose]
        execution_started = _utc_now()
        try:
            adapter_result: AdapterResult = adapter.execute(
                sql_validated, max_rows=max_rows, timeout_s=timeout_s,
            )
        except AuthExpiredError as exc:
            # §10.5.5 — surrender immediately, do not retry.
            reason = redact_message(exc)
            last_error_message = reason
            execution = QueryExecution(
                started_at=execution_started,
                ended_at=_utc_now(),
                error_class="AuthExpiredError",
                error_message=reason,
            )
            artifact = _build_artifact(
                attempt_intent,
                sql_validated=sql_validated,
                outcome=QueryOutcome.ERRORED,
                safety_trace=safety_trace,
                proposed_at=proposed_at,
                outcome_reason=reason,
                execution=execution,
                metadata={"subtype": "auth_expired"},
                query_id=query_id,
            )
            artifact_path = write_query_artifact(artifact, exp_dir)
            _emit_failed(
                exp_dir, attempt_intent, query_id,
                error_class="AuthExpiredError",
                error_message=reason,
                subtype="auth_expired",
            )
            return SqlResult(
                artifact=artifact,
                adapter_result=None,
                attempts=attempts,
                final_status="auth_expired",
                artifact_path=artifact_path,
                error_message=reason,
            )
        except AdapterError as exc:
            reason = redact_message(exc)
            last_error_message = reason
            execution = QueryExecution(
                started_at=execution_started,
                ended_at=_utc_now(),
                error_class=type(exc).__name__,
                error_message=reason,
            )
            errored_artifact = _build_artifact(
                attempt_intent,
                sql_validated=sql_validated,
                outcome=QueryOutcome.ERRORED,
                safety_trace=safety_trace,
                proposed_at=proposed_at,
                outcome_reason=reason,
                execution=execution,
                query_id=query_id,
            )
            write_query_artifact(errored_artifact, exp_dir)

            # Decide: retry through correction, or surrender?
            can_correct = (
                correction_fn is not None
                and attempts < max_correction_attempts
            )
            if can_correct:
                # The correction agent gets the failed SQL + error + attempt
                # number; it returns the revised candidate for the next loop.
                revised = correction_fn(sql_validated, reason, attempts)
                current_sql = revised
                continue

            # Exhausted: write final failed artifact, emit query.failed.
            _emit_failed(
                exp_dir, attempt_intent, query_id,
                error_class=type(exc).__name__,
                error_message=reason,
                subtype="failed_after_retries",
            )
            return SqlResult(
                artifact=errored_artifact,
                adapter_result=None,
                attempts=attempts,
                final_status="failed_after_correction",
                error_message=reason,
            )
        except Exception as exc:  # noqa: BLE001 — last-resort credential redaction
            # The adapter raised something outside the AuthExpiredError /
            # AdapterError contract (e.g., a raw driver exception). Its
            # message can carry a DSN or credential, so scrub it through the
            # redactor before it ever reaches a traceback, log, or terminal.
            # Re-raise as a plain error carrying only the redacted text and
            # suppress the original cause chain (``from None``) so the
            # unredacted message cannot leak via __cause__.
            raise RuntimeError(
                f"adapter.execute raised an unexpected "
                f"{type(exc).__name__}: {redact_message(exc)}"
            ) from None

        # ----- Success path -----
        execution = QueryExecution(
            started_at=execution_started,
            ended_at=_utc_now(),
            wall_clock_ms=int(adapter_result.elapsed_seconds * 1000),
            rows_returned=adapter_result.row_count,
            bytes_scanned=adapter_result.bytes_scanned,
        )
        result_summary = QueryResultSummary(rows=adapter_result.row_count)
        executed_artifact = _build_artifact(
            attempt_intent,
            sql_validated=sql_validated,
            outcome=QueryOutcome.EXECUTED,
            safety_trace=safety_trace,
            proposed_at=proposed_at,
            execution=execution,
            result_summary=result_summary,
            query_id=query_id,
        )
        artifact_path = write_query_artifact(executed_artifact, exp_dir)
        _emit_executed(exp_dir, attempt_intent, query_id, adapter_result)
        return SqlResult(
            artifact=executed_artifact,
            adapter_result=adapter_result,
            attempts=attempts,
            final_status="executed",
            artifact_path=artifact_path,
            error_message=last_error_message,
        )


__all__ = ["SqlIntent", "SqlResult", "dispatch_sql"]
