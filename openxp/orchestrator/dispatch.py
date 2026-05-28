"""Orchestrator agent dispatch — the single chokepoint for invoking an agent.

Wraps the LLM call with:
  - System-prompt loading from agents/{name}.system.md
  - Bundle assembly (caller passes the ctx bundle; we don't read project state)
  - RetryPolicy per §10.5.1 (3 attempts on transient 5xx; surface auth_expired)
  - `agent.dispatched` + `agent.completed` audit events
  - `conversation.jsonl` append on success
  - Pydantic validation of the agent's out-bundle (caller supplies schema)

Does NOT:
  - Read or write state.yaml (orchestrator owns that)
  - Decide retry budget exhaustion handling (caller decides; we surface
    failed_after_retries)
  - Actually call the LLM (placeholder — W1 wires this)

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10.5.1, §1.8.5,
§1.8.8, §9.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from openxp.audit.events import (
    AgentCompletedPayload,
    AgentDispatchedPayload,
    EventName,
)
from openxp.audit.storage import append_conversation_turn, append_event

T = TypeVar("T", bound=BaseModel)


# ──────────────────────────────────────────────────────────────────────────
# §1.8.8 canonical agent names
# ──────────────────────────────────────────────────────────────────────────

CANONICAL_AGENT_NAMES = {
    "profiler",
    "semantic_modeler",
    "metric_drafter",
    "designer.elicitor",
    "designer.drafter",
    "designer.editor",
    "consistency_judge",
    "sql_query_writer",
    "sql_corrector",
    "monitor",
    "analyzer",
    "interpreter",
    "readout",
}
"""§1.8.8 canonical agent names. Dispatch refuses any name not in this set."""


# ──────────────────────────────────────────────────────────────────────────
# Public dataclasses + errors
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class RetryPolicy:
    """Retry policy per §10.5.1.

    Attempts on 5xx transient errors. Auth-expired errors do NOT retry — they
    surface as a `gate.opened(kind="auth_expired")` event for the user to
    re-auth, and the dispatcher raises AuthExpiredError without retrying.
    """

    max_attempts: int = 3
    backoff_seconds: tuple[float, ...] = (1.0, 2.5, 6.0)  # exponential-ish
    transient_status_codes: tuple[int, ...] = (500, 502, 503, 504, 529)


@dataclass
class DispatchRequest:
    """Inputs to a single agent invocation."""

    agent_name: str  # one of CANONICAL_AGENT_NAMES
    experiment_id: str  # for audit log lineage
    project_root: Path
    ctx_bundle: dict[str, Any]  # already assembled by caller
    out_schema: Type[BaseModel]  # pydantic class to validate response
    system_prompt_path: Optional[Path] = None  # default: agents/{name}.system.md
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    parent_action_id: Optional[str] = None  # for audit chain


@dataclass
class DispatchResult:
    """Output of a single agent invocation."""

    out: BaseModel  # validated agent output
    action_id: str  # action_id of agent.dispatched event (root of this invocation)
    attempts: int  # 1 if happy path
    raw_response: str  # for debugging / conversation.jsonl


class AgentDispatchError(Exception):
    """Base class for dispatch errors."""


class AuthExpiredError(AgentDispatchError):
    """Warehouse credentials expired during agent call. Caller should open gate."""


class FailedAfterRetriesError(AgentDispatchError):
    """All retry attempts exhausted on transient errors. Caller decides next step."""


class TransientServerError(Exception):
    """5xx from LLM provider. Internal signal — handled by retry loop.

    Carries `status_code` so the dispatcher can record it in the
    agent.completed metadata (subtype=transient_5xx).
    """

    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message or f"transient {status_code}")
        self.status_code = status_code


# ──────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────


def _new_action_id() -> str:
    """Generate an action id.

    v0.1 placeholder: UUID4 hex (uppercase) — not strictly ULID-sortable, but
    unambiguous and dependency-free. Plan §6 calls for ULIDs; W1 will swap to
    `python-ulid` (or an inline Crockford-base32 ULID) at the orchestrator
    seam without touching dispatch.py callers. Sortability is provided by
    event timestamps in log.jsonl, so this placeholder is fine for the
    dispatch skeleton.
    """
    return uuid.uuid4().hex.upper()


def _hash_bundle(bundle: dict[str, Any]) -> str:
    """Deterministic hash of the ctx bundle for `bundle_hash` audit fields.

    JSON-sorted-keys + sha256, hex. Best-effort: non-JSON-serializable values
    fall back to `repr()` via `default=str` so this never raises in tests.
    """
    blob = json.dumps(bundle, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _default_system_prompt_path(project_root: Path, agent_name: str) -> Path:
    """Resolve the default system-prompt path for an agent.

    Layout: ``<repo_root>/agents/{name}.system.md``.

    The `project_root` argument is the user's experiment project root (where
    state.yaml lives), NOT the openxp install root. The agent prompts ship
    inside the installed package's sibling `agents/` directory. We compute
    the install location relative to *this* module so the lookup works
    whether the package is installed from source or via pip.

    W1 may swap this for an importlib.resources-based lookup; for v0.1 we
    walk up from this file: ``openxp/orchestrator/dispatch.py`` →
    ``openxp/`` → ``<repo>/agents/{name}.system.md``.
    """
    # __file__ → .../openxp/orchestrator/dispatch.py
    # parents[0] = orchestrator/, parents[1] = openxp/, parents[2] = repo root
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "agents" / f"{agent_name}.system.md"


def _invoke_llm(system_prompt: str, ctx_bundle: dict[str, Any]) -> str:
    """Placeholder LLM call. W1 wires in the real Anthropic / OpenAI client.

    Tests monkeypatch this symbol via
        monkeypatch.setattr("openxp.orchestrator.dispatch._invoke_llm", fake)
    to inject controlled responses (success YAML, TransientServerError,
    AuthExpiredError, malformed YAML, etc.).

    Raises:
        NotImplementedError: in v0.1 production code paths. Real callers must
            wait for W1.
    """
    raise NotImplementedError(
        "LLM call wires in W1 — use monkeypatch on "
        "openxp.orchestrator.dispatch._invoke_llm in tests"
    )


def _parse_response(raw: str, schema: Type[BaseModel]) -> BaseModel:
    """Validate the agent's raw response against the caller-supplied schema.

    Supports JSON or YAML-ish input. We try JSON first (fast path); if that
    fails, try yaml.safe_load. If both fail or the parsed object fails
    pydantic validation, raise ValueError so the retry loop can treat the
    response as malformed (per §10.5.4).
    """
    parsed: Any
    # Fast path: JSON.
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Try YAML as a fallback for agent outputs that ship as YAML blocks.
        try:
            import yaml  # local import; pyyaml is a core dep
            parsed = yaml.safe_load(raw)
        except Exception as exc:  # noqa: BLE001 — malformed-response path
            raise ValueError(f"agent response is neither JSON nor YAML: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"agent response did not parse to a mapping (got {type(parsed).__name__})"
        )

    try:
        return schema.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"agent response failed {schema.__name__} validation: {exc}") from exc


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────


def dispatch_agent(req: DispatchRequest) -> DispatchResult:
    """Single-agent dispatch with retry + audit.

    Algorithm:
      1. Validate req.agent_name ∈ CANONICAL_AGENT_NAMES (raises ValueError).
      2. Resolve system_prompt_path (default: <repo>/agents/{name}.system.md).
      3. Load system prompt (raises FileNotFoundError if missing).
      4. Append `agent.dispatched` event (audit chain root for this invocation).
      5. For each attempt in 1..max_attempts:
         a. Call _invoke_llm(system_prompt, req.ctx_bundle).
         b. On TransientServerError: append `agent.completed` with
            classification="retry" + metadata.subtype="transient_5xx";
            sleep backoff_seconds[attempt-1]; continue.
         c. On AuthExpiredError: append `agent.completed` with
            classification="failed" + metadata.subtype="auth_expired";
            raise upstream (no retry).
         d. On success: validate out_schema. If invalid, treat as transient
            (§10.5.4 malformed-YAML retry path) and continue with backoff.
            On valid, append `agent.completed` with classification="success"
            (and metadata.subtype="retry" if attempts > 1);
            append_conversation_turn; return.
      6. After max_attempts exhausted: append `agent.completed` with
         classification="failed" + metadata.subtype="failed_after_retries";
         raise FailedAfterRetriesError.

    The `experiment_dir` for audit writes is
    ``project_root / "experiments" / experiment_id`` if that path exists,
    otherwise ``project_root`` itself (so tests can pass a flat tmp_path).
    """
    # 1. Validate agent name.
    if req.agent_name not in CANONICAL_AGENT_NAMES:
        raise ValueError(
            f"agent_name {req.agent_name!r} is not in §1.8.8 canonical set. "
            f"Valid names: {sorted(CANONICAL_AGENT_NAMES)}"
        )

    # 2-3. Resolve + load system prompt.
    system_prompt_path = req.system_prompt_path or _default_system_prompt_path(
        req.project_root, req.agent_name
    )
    if not system_prompt_path.exists():
        raise FileNotFoundError(
            f"system prompt not found for agent {req.agent_name!r}: {system_prompt_path}"
        )
    system_prompt = system_prompt_path.read_text(encoding="utf-8")

    # Experiment dir for audit writes. Tests pass a flat tmp_path; production
    # callers (W1) will pass the canonical project_root and an experiment_id
    # that resolves to a subdir.
    experiment_dir = req.project_root
    candidate = req.project_root / "experiments" / req.experiment_id
    if candidate.exists():
        experiment_dir = candidate

    bundle_hash = _hash_bundle(req.ctx_bundle)

    # 4. Append agent.dispatched as the chain root for this invocation.
    dispatched_action_id = _new_action_id()
    dispatched_event = AgentDispatchedPayload(
        timestamp=_utc_now(),
        action_id=dispatched_action_id,
        parent_action_id=req.parent_action_id,
        actor_kind="orchestrator",
        actor_name="dispatch_agent",
        experiment_id=req.experiment_id,
        agent_name=req.agent_name,
        bundle_hash=bundle_hash,
        metadata={},
    )
    append_event(experiment_dir, dispatched_event)

    policy = req.retry_policy
    last_error: Optional[Exception] = None

    # 5. Retry loop.
    for attempt in range(1, policy.max_attempts + 1):
        start_ms = time.monotonic()
        try:
            raw_response = _invoke_llm(system_prompt, req.ctx_bundle)
        except AuthExpiredError as exc:
            # 5c. Auth expired — no retry; record failure and re-raise.
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            completed = AgentCompletedPayload(
                timestamp=_utc_now(),
                action_id=_new_action_id(),
                parent_action_id=dispatched_action_id,
                actor_kind="orchestrator",
                actor_name="dispatch_agent",
                experiment_id=req.experiment_id,
                agent_name=req.agent_name,
                bundle_hash=bundle_hash,
                duration_ms=duration_ms,
                classification="failed",
                metadata={"subtype": "auth_expired", "attempt": attempt},
            )
            append_event(experiment_dir, completed)
            raise
        except TransientServerError as exc:
            # 5b. Transient 5xx — record retry, back off, continue.
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            completed = AgentCompletedPayload(
                timestamp=_utc_now(),
                action_id=_new_action_id(),
                parent_action_id=dispatched_action_id,
                actor_kind="orchestrator",
                actor_name="dispatch_agent",
                experiment_id=req.experiment_id,
                agent_name=req.agent_name,
                bundle_hash=bundle_hash,
                duration_ms=duration_ms,
                classification="retry",
                metadata={
                    "subtype": "transient_5xx",
                    "attempt": attempt,
                    "status_code": exc.status_code,
                },
            )
            append_event(experiment_dir, completed)
            last_error = exc
            if attempt < policy.max_attempts:
                time.sleep(policy.backoff_seconds[attempt - 1])
            continue

        # 5d. LLM call returned a string — validate against schema.
        try:
            validated = _parse_response(raw_response, req.out_schema)
        except ValueError as exc:
            # Malformed response — treat as transient per §10.5.4.
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            completed = AgentCompletedPayload(
                timestamp=_utc_now(),
                action_id=_new_action_id(),
                parent_action_id=dispatched_action_id,
                actor_kind="orchestrator",
                actor_name="dispatch_agent",
                experiment_id=req.experiment_id,
                agent_name=req.agent_name,
                bundle_hash=bundle_hash,
                duration_ms=duration_ms,
                classification="retry",
                metadata={
                    "subtype": "transient_5xx",
                    "attempt": attempt,
                    "malformed_response": True,
                },
            )
            append_event(experiment_dir, completed)
            last_error = exc
            if attempt < policy.max_attempts:
                time.sleep(policy.backoff_seconds[attempt - 1])
            continue

        # Success path.
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        success_metadata: dict[str, Any] = {"attempt": attempt}
        if attempt > 1:
            # Per §1.8.5 / B3: mark the eventual-success completion as a
            # retry-resolved success.
            success_metadata["subtype"] = "retry"
        completed = AgentCompletedPayload(
            timestamp=_utc_now(),
            action_id=_new_action_id(),
            parent_action_id=dispatched_action_id,
            actor_kind="orchestrator",
            actor_name="dispatch_agent",
            experiment_id=req.experiment_id,
            agent_name=req.agent_name,
            bundle_hash=bundle_hash,
            duration_ms=duration_ms,
            classification="success",
            metadata=success_metadata,
        )
        append_event(experiment_dir, completed)

        # Append conversation turn (system + user + assistant per §9).
        append_conversation_turn(
            experiment_dir,
            {
                "timestamp": _utc_now().isoformat(),
                "action_id": dispatched_action_id,
                "agent_name": req.agent_name,
                "system": system_prompt,
                "user": json.dumps(req.ctx_bundle, sort_keys=True, default=str),
                "assistant": raw_response,
            },
        )

        return DispatchResult(
            out=validated,
            action_id=dispatched_action_id,
            attempts=attempt,
            raw_response=raw_response,
        )

    # 6. All attempts exhausted — record terminal failure + raise.
    completed = AgentCompletedPayload(
        timestamp=_utc_now(),
        action_id=_new_action_id(),
        parent_action_id=dispatched_action_id,
        actor_kind="orchestrator",
        actor_name="dispatch_agent",
        experiment_id=req.experiment_id,
        agent_name=req.agent_name,
        bundle_hash=bundle_hash,
        duration_ms=0,
        classification="failed",
        metadata={"subtype": "failed_after_retries", "attempts": policy.max_attempts},
    )
    append_event(experiment_dir, completed)
    raise FailedAfterRetriesError(
        f"agent {req.agent_name!r} failed after {policy.max_attempts} attempts; "
        f"last error: {last_error!r}"
    )


__all__ = [
    "CANONICAL_AGENT_NAMES",
    "RetryPolicy",
    "DispatchRequest",
    "DispatchResult",
    "AgentDispatchError",
    "AuthExpiredError",
    "FailedAfterRetriesError",
    "TransientServerError",
    "dispatch_agent",
]
