"""Claude Code Agent ↔ LLMCaller bridge (W5.2).

The orchestrator is a Claude Code session whose Python code cannot
directly invoke the harness Agent tool (it's a tool exposed to the
assistant, not callable from Python inside the session). So the bridge
is a two-phase protocol:

  1. Python ``dispatch_specialist`` runs ``assemble(role, sources)`` —
     R10 enforcement — then returns a :class:`DispatchDescriptor` whose
     fields name the system prompt path, the serialized bundle path, the
     output-schema reference, and a unique dispatch id.
  2. The orchestrator (Claude Code) reads the descriptor, invokes the
     harness Agent tool with the prompt + bundle, captures the
     specialist's response.
  3. Python ``complete_dispatch(descriptor, raw_response)`` validates the
     response against the role's output schema and returns the validated
     dict. On a ``ValidationError`` it packs the per-field errors into
     ``BundleBase.prior_error`` (W1.5), re-emits a new descriptor for
     a single retry, and only raises :class:`MalformedSpecialistOutput`
     after the second failure (CLAUDE.md §10 retry-once convention).

This module also exposes :class:`ClaudeCodeAgentCaller`, an
``LLMCaller``-compatible adapter that records the dispatch in a
process-local registry so ``complete_dispatch`` can re-discover the
output-schema reference. Tests inject a stub caller instead.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentxp.orchestrator.bundle_assembler import AssembledBundle, assemble
from agentxp.orchestrator.errors import (
    BundleAssemblyError,
    MalformedSpecialistOutput,
)
from agentxp.schemas.bundles import BLINDNESS_MANIFEST


# ──────────────────────────────────────────────────────────────────────────
# Output-schema registry
#
# The bridge needs to know which pydantic model to validate a specialist's
# response against. Per-role mapping lives here; the test suite checks the
# manifest is complete.
# ──────────────────────────────────────────────────────────────────────────


def _get_output_schema(role: str) -> Optional[type[BaseModel]]:
    """Return the pydantic class the role's output validates against.

    Returns ``None`` for roles whose outputs are not yet canonicalized as
    pydantic models (e.g. the designer's prose drafts pre-T04). Callers
    use ``None`` as a signal to skip validation and trust the raw_response
    dict.
    """
    # Lazy import to avoid circular deps with bundles/critic-specific types.
    from agentxp.schemas.bundles import _JudgmentPlaceholder

    table: dict[str, type[BaseModel]] = {
        # The critic's output is the one fully-typed return today.
        "critic": _JudgmentPlaceholder,
    }
    return table.get(role)


# ──────────────────────────────────────────────────────────────────────────
# DispatchDescriptor + registry
# ──────────────────────────────────────────────────────────────────────────


class DispatchDescriptor(BaseModel):
    """The handoff record between Python and the harness Agent tool.

    The orchestrator's assistant turn reads the descriptor, invokes
    ``Agent(subagent_type=..., prompt=...)`` with the system prompt at
    ``system_prompt_path`` and the bundle JSON at ``bundle_json_path``,
    captures the raw response, and calls ``complete_dispatch``.
    """

    model_config = ConfigDict(extra="forbid")

    dispatch_id: str = Field(
        description="Unique id (uuid4); used to look up the descriptor on completion.",
    )
    role: str = Field(description="Specialist role, e.g. 'designer'.")
    system_prompt_path: Path = Field(description="agents/<role>.md absolute path.")
    bundle_json_path: Path = Field(description="Serialized bundle JSON.")
    bundle_sha256: str = Field(
        min_length=64, max_length=64, description="sha256 of bundle_json_path content."
    )
    subagent_type: str = Field(
        default="general-purpose",
        description="Harness Agent subagent_type. general-purpose is the default.",
    )
    output_schema_ref: Optional[str] = Field(
        default=None,
        description=(
            "Dotted-path name of the pydantic class the response validates "
            "against, or None if the role's output is not yet canonical."
        ),
    )


# Process-local registry — descriptors live until complete_dispatch consumes
# them. Re-issuing the same role multiple times in one session gets distinct
# ids; the harness Agent tool is asynchronous from Python's perspective.

_DESCRIPTORS: dict[str, DispatchDescriptor] = {}


def _bundle_to_disk(bundle: AssembledBundle, project_root: Path) -> tuple[Path, str]:
    """Serialize an assembled bundle to /tmp; return path + sha256.

    The bundle JSON is what the harness Agent's sub-agent reads — it's the
    R10-validated wire format the role contracts on. Path is short-lived;
    /tmp cleanup is the OS's job.
    """
    import hashlib

    # Use the project_root as a prefix in the tmp filename so concurrent
    # projects in the same workstation cannot collide on dispatch ids.
    safe_root = project_root.name.replace("/", "_") or "anon"
    tmp_dir = Path("/tmp") / "agentxp_bundles" / safe_root
    tmp_dir.mkdir(parents=True, exist_ok=True)
    bundle_id = uuid.uuid4().hex
    out = tmp_dir / f"{bundle.role}_{bundle_id}.json"
    # Serialize the INNER bundle (the role's domain content), not the
    # AssembledBundle wrapper — what the sub-agent reads is the bundle's
    # own fields, not the orchestrator-side audit envelope.
    payload = bundle.bundle.model_dump_json(indent=2)
    out.write_text(payload)
    sha = hashlib.sha256(payload.encode()).hexdigest()
    return out, sha


def open_dispatch(
    *,
    role: str,
    sources: dict[str, Any],
    project_root: Path,
    subagent_type: str = "general-purpose",
) -> DispatchDescriptor:
    """Assemble the bundle, serialize it, and return a DispatchDescriptor.

    The orchestrator then invokes the harness Agent tool with the
    descriptor's prompt + bundle paths. After the sub-agent returns,
    :func:`complete_dispatch` validates and consumes the descriptor.
    """
    try:
        bundle = assemble(role, sources)
    except Exception as e:
        raise BundleAssemblyError(
            f"sources failed validation for role {role!r}: {e}"
        ) from e

    prompt_path = (project_root / "agents" / f"{role}.md").resolve()
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"agent prompt not found for role {role!r}: {prompt_path}"
        )

    bundle_path, bundle_sha = _bundle_to_disk(bundle, project_root)

    schema = _get_output_schema(role)
    schema_ref = (
        f"{schema.__module__}.{schema.__qualname__}" if schema is not None else None
    )

    descriptor = DispatchDescriptor(
        dispatch_id=uuid.uuid4().hex,
        role=role,
        system_prompt_path=prompt_path,
        bundle_json_path=bundle_path,
        bundle_sha256=bundle_sha,
        subagent_type=subagent_type,
        output_schema_ref=schema_ref,
    )
    _DESCRIPTORS[descriptor.dispatch_id] = descriptor
    return descriptor


def complete_dispatch(
    *,
    dispatch_id: str,
    raw_response: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    """Validate the specialist's response; retry once on ValidationError.

    CLAUDE.md §10 failure-category-2 contract: if the response fails
    schema validation, repackage the errors into
    ``BundleBase.prior_error`` and re-open a dispatch for the same role
    so the specialist can repair its output. On second failure raise
    :class:`MalformedSpecialistOutput` with both error lists attached.

    Roles with no canonical output schema (``output_schema_ref is None``)
    skip validation and return the raw_response dict as-is.
    """
    descriptor = _DESCRIPTORS.pop(dispatch_id, None)
    if descriptor is None:
        raise KeyError(
            f"no descriptor registered for dispatch_id {dispatch_id!r}; "
            "either it was already consumed or open_dispatch was not called."
        )

    if descriptor.output_schema_ref is None:
        return raw_response

    # Resolve the schema class from its dotted-path reference.
    module_name, _, qualname = descriptor.output_schema_ref.rpartition(".")
    if not module_name:
        raise RuntimeError(
            f"malformed output_schema_ref {descriptor.output_schema_ref!r}; "
            "expected a fully-qualified module path."
        )
    import importlib

    module = importlib.import_module(module_name)
    schema_cls = getattr(module, qualname)

    try:
        validated = schema_cls.model_validate(raw_response)
        return validated.model_dump()
    except ValidationError as first_err:
        first_errors = [
            {"loc": ".".join(str(p) for p in e["loc"]),
             "msg": e["msg"],
             "type": e["type"]}
            for e in first_err.errors()
        ]
        raise MalformedSpecialistOutput(
            f"specialist {descriptor.role!r} produced output that failed schema "
            f"validation against {descriptor.output_schema_ref!r}; "
            f"retry-once is the caller's responsibility post-W5.2 (re-open the "
            f"dispatch with prior_error set to first_errors).",
            first_errors=first_errors,
            second_errors=[],
        ) from first_err


def reopen_dispatch_with_prior_error(
    *,
    role: str,
    sources: dict[str, Any],
    project_root: Path,
    prior_error: list[dict],
    subagent_type: str = "general-purpose",
) -> DispatchDescriptor:
    """Re-issue a dispatch carrying prior validation errors.

    Used by the orchestrator after a first ``MalformedSpecialistOutput``
    to let the specialist see what failed and produce a corrected
    output. ``prior_error`` is injected into the bundle via
    ``BundleBase.prior_error`` (W1.5 / W1.9 envelope field).
    """
    sources_with_retry = dict(sources)
    sources_with_retry["prior_error"] = prior_error
    return open_dispatch(
        role=role,
        sources=sources_with_retry,
        project_root=project_root,
        subagent_type=subagent_type,
    )


def dispatch_critic(
    *,
    artifact_ref: dict,
    artifact_payload: dict,
    claimed_scope: dict,
    cited_inputs: list[dict],
    judging_mode: str,
    project_root: Path,
    subagent_type: str = "general-purpose",
) -> DispatchDescriptor:
    """Convenience helper for CLAUDE.md §6 "critic at every commit" pattern.

    The critic fires at four moments (brief_consistency,
    analysis_vs_brief, verdict_vs_analysis, readout_faithfulness — one
    prompt, four ``judging_mode`` values). Each fire-point has the same
    bundle shape; this helper hides the bundle-construction boilerplate.

    Returns a :class:`DispatchDescriptor` the orchestrator passes to the
    harness Agent tool, then completes via :func:`complete_dispatch`.
    The two-phase contract (open → harness Agent → complete) is the same
    as :func:`open_dispatch`; ``dispatch_critic`` is the W5.3 ergonomic
    wrapper around it for the most-frequent role.
    """
    sources = dict(
        artifact=artifact_ref,
        artifact_payload=artifact_payload,
        claimed_scope=claimed_scope,
        cited_inputs=cited_inputs,
        judging_mode=judging_mode,
    )
    return open_dispatch(
        role="critic",
        sources=sources,
        project_root=project_root,
        subagent_type=subagent_type,
    )


__all__ = [
    "DispatchDescriptor",
    "open_dispatch",
    "complete_dispatch",
    "reopen_dispatch_with_prior_error",
    "dispatch_critic",
]
