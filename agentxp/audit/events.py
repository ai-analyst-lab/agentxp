"""Canonical 13-event audit vocabulary for AgentXP v0.1.

The closed enum + payload pydantic models for every event written to log.jsonl.
hook.invoked and hook.failed are RESERVED in v0.1 (external hooks deferred to v0.2
per D2/§22.5); they exist as enum values but are never emitted by v0.1 code.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §1.8.3, §1.8.5, §9, §22.5.
Closure-tested: tests/audit/test_event_enum_closure.py asserts len(EventName) == 13.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentxp.schemas._types import Sha256Hex
from agentxp.schemas.state import GateKind, Stage


# ──────────────────────────────────────────────────────────────────────────
# EventName — closed 13-event enum (§1.8.3, §9)
# ──────────────────────────────────────────────────────────────────────────

class EventName(str, Enum):
    """The closed 13-event vocabulary for log.jsonl.

    Exactly 13 values; closure-tested in tests/audit/test_event_enum_closure.py.
    The last two (HOOK_INVOKED, HOOK_FAILED) are RESERVED in v0.1 per §22.5 —
    external hook system is deferred to v0.2, but the enum values are locked
    now so v0.1 readers continue to work against v0.2 logs without a
    schema_version bump.
    """

    STAGE_ENTERED = "stage.entered"
    STAGE_COMMITTED = "stage.committed"
    GATE_OPENED = "gate.opened"
    GATE_RESOLVED = "gate.resolved"
    GATE_BLOCKED = "gate.blocked"
    AGENT_DISPATCHED = "agent.dispatched"
    AGENT_COMPLETED = "agent.completed"
    QUERY_PROPOSED = "query.proposed"
    QUERY_VALIDATED = "query.validated"
    QUERY_EXECUTED = "query.executed"
    QUERY_FAILED = "query.failed"
    HOOK_INVOKED = "hook.invoked"      # RESERVED v0.1; emitted v0.2 per §22.5
    HOOK_FAILED = "hook.failed"        # RESERVED v0.1; emitted v0.2 per §22.5


#: The two events that are part of the enum but never emitted by v0.1 code.
#: External hooks ship in v0.2 (D2 / §22.5). Documented here so audit-replay
#: tooling can warn loudly if a v0.1 build attempts to emit one.
V01_RESERVED_EVENTS = frozenset({EventName.HOOK_INVOKED, EventName.HOOK_FAILED})


# ──────────────────────────────────────────────────────────────────────────
# EventMetadata.subtype — bounded set per §1.8.5
# ──────────────────────────────────────────────────────────────────────────
#
# The full §1.8.5 table is 17 subtypes. The field on payloads is documented as
# free-form `str` for forward-compatibility, but every value below MUST have a
# documented triggering event in the plan. Use EventMetadataSubtype where you
# want type-checker enforcement at a callsite.

EventMetadataSubtype = Literal[
    "retry",                        # agent.completed                §1.8.5 / B3
    "transient_5xx",                # agent.completed (retry)        §1.8.5 / B3
    "failed_after_retries",         # agent.completed (failed)       §1.8.5 / B3
    "auth_expired",                 # query.failed                   §1.8.5 / B4
    "disk_full",                    # gate.blocked                   §10.5.3
    "cache_hit",                    # query.executed                 §1.8.5 / B9
    "recovered_from_state_yaml",    # stage.committed                §10.6
    "lock.stale_reclaimed",         # stage.committed                §10.9 / B4
    "dag_transition",               # stage.committed                §3
    "chain_validation_failed",      # gate.blocked                   §10.7
    "chain_validation_slow",        # stage.committed                §10.7.3
    "chain_validation_perf",        # gate.blocked                   §10.7.3
    "project_locked",               # gate.blocked                   §10.9
    "log_rotation",                 # stage.committed                §10.5.6
    "oversize_response",            # agent.completed                §10.5.7
    "schema_migration",             # stage.committed (v0.5+ reserve) §1.7.6
    "srm_override_declined",        # gate.blocked                   §18.X.2
]


# ──────────────────────────────────────────────────────────────────────────
# Base payload — shared 9-field action receipt shape
# ──────────────────────────────────────────────────────────────────────────
#
# Every payload extends this. Sub-classes add event-specific fields and pin
# event_name via Literal[EventName.X] for tagged-union dispatch (Pydantic v2
# discriminator-style routing).

class _BasePayload(BaseModel):
    """Shared base for all 13 payload classes.

    Enforces:
      - extra="forbid" (no silent passthrough of unknown fields)
      - schema_version pinned to 1 for v0.1
      - UTC timestamps (via field_validator)
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    timestamp: datetime
    action_id: str  # ULID per action; matches §1.5 action-receipt contract
    parent_action_id: Optional[str] = None
    actor_kind: Literal["agent", "user", "system", "orchestrator", "hook"]
    actor_name: Optional[str] = None
    experiment_id: str

    @field_validator("timestamp")
    @classmethod
    def _enforce_utc(cls, v: datetime) -> datetime:
        """All audit timestamps must be timezone-aware UTC (no naive datetimes).

        Naive datetimes silently shift across timezones during log rotation /
        replay, which corrupts chain-validation invariants (§10.7). Reject them
        at the model boundary.
        """
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware UTC (got naive datetime)")
        if v.utcoffset() != timezone.utc.utcoffset(v):
            raise ValueError(
                f"timestamp must be UTC (got offset {v.utcoffset()}); convert before emit"
            )
        return v


# ──────────────────────────────────────────────────────────────────────────
# Payload classes — one per EventName value
# ──────────────────────────────────────────────────────────────────────────

class StageEnteredPayload(_BasePayload):
    """Stage N began processing. Paired with a later stage.committed."""

    event_name: Literal[EventName.STAGE_ENTERED] = EventName.STAGE_ENTERED
    stage: Stage
    metadata: dict = Field(default_factory=dict)


class StageCommittedPayload(_BasePayload):
    """Stage N successfully committed; state.yaml + on-disk artifacts persisted.

    metadata.subtype may carry a §1.8.5 value (dag_transition, log_rotation,
    recovered_from_state_yaml, lock.stale_reclaimed, chain_validation_slow,
    schema_migration).
    """

    event_name: Literal[EventName.STAGE_COMMITTED] = EventName.STAGE_COMMITTED
    stage: Stage
    bundle_hash: Optional[Sha256Hex] = None
    metadata: dict = Field(default_factory=dict)


class GateOpenedPayload(_BasePayload):
    """A user-facing gate is now blocking the orchestrator.

    `kind` is the documented superset of PendingDecisionKind (14 values) +
    Literal["sql_review", "edit_override"] (2 within-turn UX gates per §9).
    Total 16 valid values.
    """

    event_name: Literal[EventName.GATE_OPENED] = EventName.GATE_OPENED
    kind: GateKind
    options: list[str] = Field(default_factory=list)
    prompt_to_user: str
    metadata: dict = Field(default_factory=dict)


class GateResolvedPayload(_BasePayload):
    """User chose an option; gate is now cleared."""

    event_name: Literal[EventName.GATE_RESOLVED] = EventName.GATE_RESOLVED
    kind: GateKind
    choice: str
    rationale: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class GateBlockedPayload(_BasePayload):
    """System-side halt; the orchestrator cannot proceed.

    `reason` is bound to the §1.8.5 subtype set in practice (F.COHERENCE.02).
    Documented values include: disk_full, auth_expired, chain_validation_failed,
    chain_validation_perf, project_locked, srm_override_declined.
    metadata.subtype duplicates `reason` for canonical lookup per §10.5.3.
    """

    event_name: Literal[EventName.GATE_BLOCKED] = EventName.GATE_BLOCKED
    reason: str
    metadata: dict = Field(default_factory=dict)


class AgentDispatchedPayload(_BasePayload):
    """An LLM agent invocation has started. Paired with a later agent.completed."""

    event_name: Literal[EventName.AGENT_DISPATCHED] = EventName.AGENT_DISPATCHED
    agent_name: str  # one of §1.8.8 canonical names
    bundle_hash: Sha256Hex
    purpose: Optional[str] = None  # per resource_bounds purpose key (§10.5.7)
    metadata: dict = Field(default_factory=dict)


class AgentCompletedPayload(_BasePayload):
    """An LLM agent invocation finished (or exhausted retries).

    classification:
      - "success" — completed normally
      - "retry"   — transient failure, will be retried; metadata.subtype="transient_5xx" or "retry"
      - "failed"  — exhausted retry budget; metadata.subtype="failed_after_retries"

    RetryPolicy details (per §10.5.1) may travel in metadata.retry_policy.
    """

    event_name: Literal[EventName.AGENT_COMPLETED] = EventName.AGENT_COMPLETED
    agent_name: str
    bundle_hash: Sha256Hex
    duration_ms: int
    classification: Literal["success", "retry", "failed"]
    metadata: dict = Field(default_factory=dict)


class QueryProposedPayload(_BasePayload):
    """sql_query_writer (or sql_corrector) proposed a SQL query.

    raw_hash + ast_hash are the canonical anchors for queries/{ulid}.yaml
    (schema_version 1 per §1.8.6).
    """

    event_name: Literal[EventName.QUERY_PROPOSED] = EventName.QUERY_PROPOSED
    query_id: str  # ULID; matches queries/{ulid}.yaml
    raw_hash: Sha256Hex
    ast_hash: Sha256Hex
    metadata: dict = Field(default_factory=dict)


class QueryValidatedPayload(_BasePayload):
    """User reviewed the proposed query at the sql_review gate.

    user_choice:
      - "accepted" — run as-is
      - "edited"   — user modified, run modified version (triggers edit_override gate)
      - "rejected" — user discarded; sql_query_writer re-runs
    """

    event_name: Literal[EventName.QUERY_VALIDATED] = EventName.QUERY_VALIDATED
    query_id: str
    user_choice: Literal["accepted", "edited", "rejected"]
    metadata: dict = Field(default_factory=dict)


class QueryExecutedPayload(_BasePayload):
    """Warehouse round-trip succeeded; result is now in the bundle.

    metadata.subtype may be "cache_hit" if served from validated_queries/.
    """

    event_name: Literal[EventName.QUERY_EXECUTED] = EventName.QUERY_EXECUTED
    query_id: str
    duration_ms: int
    rows_returned: int
    result_hash: Sha256Hex
    metadata: dict = Field(default_factory=dict)


class QueryFailedPayload(_BasePayload):
    """Warehouse round-trip failed.

    metadata.subtype may be "auth_expired" (B4/H39), triggering the re-auth
    gate per §10.5.4.
    """

    event_name: Literal[EventName.QUERY_FAILED] = EventName.QUERY_FAILED
    query_id: str
    error_class: str
    error_message: str
    metadata: dict = Field(default_factory=dict)


class HookInvokedPayload(_BasePayload):
    """RESERVED in v0.1; emitted starting v0.2 (per D2 / §22.5).

    The enum value is locked now (alongside HOOK_FAILED) so v0.1 readers
    continue to work against v0.2 logs without a schema_version bump. v0.1
    orchestrator code MUST NOT emit this event; closure tests on the audit
    writer will reject it.
    """

    event_name: Literal[EventName.HOOK_INVOKED] = EventName.HOOK_INVOKED
    hook_name: str
    metadata: dict = Field(default_factory=dict)


class HookFailedPayload(_BasePayload):
    """RESERVED in v0.1; emitted starting v0.2 (per D2 / §22.5).

    See HookInvokedPayload docstring. v0.1 orchestrator code MUST NOT emit.
    """

    event_name: Literal[EventName.HOOK_FAILED] = EventName.HOOK_FAILED
    hook_name: str
    error_message: str
    metadata: dict = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Discriminated union of all payload types
# ──────────────────────────────────────────────────────────────────────────
#
# Use for parsing / dispatch of incoming events. Pydantic v2 picks the right
# subclass by the Literal[EventName.X] tag on event_name.

EventPayload = Union[
    StageEnteredPayload,
    StageCommittedPayload,
    GateOpenedPayload,
    GateResolvedPayload,
    GateBlockedPayload,
    AgentDispatchedPayload,
    AgentCompletedPayload,
    QueryProposedPayload,
    QueryValidatedPayload,
    QueryExecutedPayload,
    QueryFailedPayload,
    HookInvokedPayload,
    HookFailedPayload,
]


__all__ = [
    "EventName",
    "V01_RESERVED_EVENTS",
    "EventMetadataSubtype",
    "EventPayload",
    "StageEnteredPayload",
    "StageCommittedPayload",
    "GateOpenedPayload",
    "GateResolvedPayload",
    "GateBlockedPayload",
    "AgentDispatchedPayload",
    "AgentCompletedPayload",
    "QueryProposedPayload",
    "QueryValidatedPayload",
    "QueryExecutedPayload",
    "QueryFailedPayload",
    "HookInvokedPayload",
    "HookFailedPayload",
]
