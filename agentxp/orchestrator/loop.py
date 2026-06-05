"""Lean-agentic orchestrator loop (T80, replaces v0.1 store.py).

The orchestrator is a Claude Code session running with the project root
CLAUDE.md as its system prompt. It is *the* agent — it owns the user
conversation, decides path, dispatches specialists, runs the critic at
every commit, commits via git, and narrates results.

This module provides the Python-side scaffolding the orchestrator uses
inside a Claude Code session — not a "main loop" in the Python sense
(the agent IS the loop). Specifically:

  - run_design_verb(exp_id, ...)  enter the design verb's loop
  - run_analyze_verb(brief_path, ...) enter the analyze verb's loop
  - dispatch_specialist(role, sources) assemble bundle + call sub-agent
  - dispatch_critic(artifact, mode) blind critic dispatch
  - require_critic_pass(commit_path, judging_mode) gate a commit on critic

Where this differs from v0.1 store.py (1,071 LOC):

  - No 11-stage state machine. The verb's terminal condition is "brief
    sealed" (design) or "report.md committed + user confirmed" (analyze).
    The loop is the agent's choice of next-action, not a script.

  - No validate_chain. Git is the chain for experiment state; the
    renders catalog (T50) is its own hash chain.

  - No .bak rollback, no SIGINT-deferred commit, no .state.lock,
    no 8-case resume classifier. Resume = read the dir, ask the user.

  - No 9-failure-mode taxonomy. Three categories (CLAUDE.md §10):
    tool refusal, malformed specialist output, crash. Each handled by
    surfacing to the user and choosing a different tool / retrying once
    with the error attached / asking where to continue after restart.

The actual sub-agent dispatch (sending a prompt + bundle to a Claude
sub-agent) is wired through the Claude Code Agent tool when the
orchestrator is running inside a Claude Code session. For test purposes
``dispatch_specialist`` accepts an injectable ``llm_caller`` callable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict

from agentxp.orchestrator.bundle_assembler import (
    AssembledBundle,
    BundleAssemblyError,
    assemble,
)
from agentxp.orchestrator.tools import (
    ExperimentSnapshot,
    ToolRefusal,
    commit_artifact,
    read_experiment_dir,
    render_share_tail,
)


# ─────────────────────────────────────────────────────────────────────────────
# LLM-caller protocol — for injection in tests + actual Claude Code Agent
# ─────────────────────────────────────────────────────────────────────────────


class LLMCaller(Protocol):
    """The contract for sub-agent dispatch.

    The default implementation (``_default_llm_caller``) raises
    NotImplementedError — actual dispatch happens via the Claude Code
    harness's Agent tool when the orchestrator runs inside Claude Code.
    Tests inject a mock that returns canned responses.
    """

    def __call__(
        self,
        *,
        role: str,
        system_prompt_path: Path,
        bundle: AssembledBundle,
    ) -> dict[str, Any]:
        ...


def _default_llm_caller(*, role: str, system_prompt_path: Path, bundle: AssembledBundle) -> dict[str, Any]:
    raise NotImplementedError(
        "No LLM caller configured. The orchestrator must be invoked inside "
        "a Claude Code session (which provides the Agent tool for sub-agent "
        f"dispatch) or with an explicit llm_caller= argument. role={role!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Verb context — what the loop reads at the start of every turn
# ─────────────────────────────────────────────────────────────────────────────


class VerbContext(BaseModel):
    """Per-turn state of a verb's loop. Read fresh from disk at every turn."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    verb: Literal["design", "analyze"]
    snapshot: ExperimentSnapshot
    project_root: Path

    @property
    def terminal(self) -> bool:
        """Has the verb reached its termination condition?

        - design  terminates when the brief seals
        - analyze terminates when report.md is committed
        """
        if self.verb == "design":
            return self.snapshot.brief_sealed
        return self.snapshot.has_report


# ─────────────────────────────────────────────────────────────────────────────
# Specialist + critic dispatch
# ─────────────────────────────────────────────────────────────────────────────


def dispatch_specialist(
    *,
    role: str,
    sources: dict[str, Any],
    project_root: Path,
    llm_caller: LLMCaller = _default_llm_caller,
) -> dict[str, Any]:
    """Assemble a schema-validated bundle and dispatch the specialist.

    R10 enforcement is at the assembler boundary — the bundle is built
    against the role's BundleSchema and refuses any source field outside
    it. The LLM caller is then handed the role's system prompt + the
    validated bundle; it returns a dict the caller parses into the
    role's output schema.

    Raises:
      - BundleAssemblyError if sources fail validation
      - whatever llm_caller raises (typically the harness's own errors)
    """
    bundle = assemble(role, sources)
    prompt_path = project_root / "agents" / f"{role}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"agent prompt not found for role {role!r}: {prompt_path}"
        )
    return llm_caller(
        role=role,
        system_prompt_path=prompt_path,
        bundle=bundle,
    )


def dispatch_critic(
    *,
    artifact_ref: dict,   # ArtifactRef-shaped
    artifact_payload: dict,
    claimed_scope: dict,
    cited_inputs: list,
    judging_mode: Literal[
        "brief_consistency",
        "analysis_vs_brief",
        "verdict_vs_analysis",
        "readout_faithfulness",
    ],
    project_root: Path,
    llm_caller: LLMCaller = _default_llm_caller,
) -> dict[str, Any]:
    """Blind critic dispatch (R6) at a commit-worthy moment.

    The critic's bundle structurally lacks producer_reasoning,
    conversation_history, prior_judgments (R5/R6 closure-enforced by
    CriticBundle in agentxp.schemas.bundles). The returned Judgment has
    .passed bool, .reasons list, .severity ('block' or 'warn').
    """
    sources = dict(
        artifact=artifact_ref,
        artifact_payload=artifact_payload,
        claimed_scope=claimed_scope,
        cited_inputs=cited_inputs,
        judging_mode=judging_mode,
    )
    return dispatch_specialist(
        role="critic",
        sources=sources,
        project_root=project_root,
        llm_caller=llm_caller,
    )


def require_critic_pass(
    *,
    judgment: dict,
) -> None:
    """Raise ToolRefusal if the critic blocked the commit.

    The orchestrator wraps every commit-worthy artifact with:
        judgment = dispatch_critic(...)
        require_critic_pass(judgment=judgment)
        commit_artifact(...)

    Severity 'block' refuses; 'warn' surfaces but allows. The agent is
    responsible for either resolving the objection (re-dispatch the
    designer with the critique attached) or asking the user.
    """
    if judgment.get("passed") is True:
        return
    severity = judgment.get("severity", "block")
    reasons = judgment.get("reasons", [])
    rendered = "; ".join(
        f"{r.get('what', '?')} ({r.get('rule_violated', '?')})" for r in reasons
    )
    if severity == "block":
        raise ToolRefusal(
            f"R6 — critic blocked the commit: {rendered}"
        )
    # warn — orchestrator should surface; here we no-op so the caller
    # decides what to do (asking the user is its job).


# ─────────────────────────────────────────────────────────────────────────────
# The verb runners — entry points for the design / analyze CLI commands
# ─────────────────────────────────────────────────────────────────────────────


def design_verb_initial_snapshot(exp_dir: Path) -> VerbContext:
    """Construct the initial VerbContext for a design-verb session.

    The CLI calls this; the agent then drives the loop using the tools
    in orchestrator/tools.py and dispatch_specialist / dispatch_critic
    above.
    """
    snapshot = read_experiment_dir(exp_dir)
    return VerbContext(
        verb="design",
        snapshot=snapshot,
        project_root=exp_dir.parent.parent,
    )


def analyze_verb_initial_snapshot(
    *,
    exp_dir: Path,
    sealed_brief_path: Path,
) -> VerbContext:
    """Construct the initial VerbContext for an analyze-verb session.

    The CLI verifies the brief seal BEFORE calling this; reaching here
    means the three-part integrity lock passed.
    """
    snapshot = read_experiment_dir(exp_dir)
    return VerbContext(
        verb="analyze",
        snapshot=snapshot,
        project_root=exp_dir.parent.parent,
    )


__all__ = [
    "LLMCaller",
    "VerbContext",
    "dispatch_specialist",
    "dispatch_critic",
    "require_critic_pass",
    "design_verb_initial_snapshot",
    "analyze_verb_initial_snapshot",
]
