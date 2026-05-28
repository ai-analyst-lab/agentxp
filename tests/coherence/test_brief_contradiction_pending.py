"""Coherence tests for the Stage-3b consistency_judge gate wiring (W4).

Pins two invariants:

1. ``brief_contradiction`` is a canonical PendingDecisionKind value
   (§1.8.1) — the orchestrator's ``OrchestratorStore.set_pending`` accepts
   any GateKind, so this test guards against drift between the enum and
   the consistency_judge dialog wiring (§10.8.2).

2. The ``agents/consistency_judge.system.md`` prompt declares the output
   YAML shape the orchestrator expects (verdict + findings[]).
"""
from __future__ import annotations

from pathlib import Path


def _resolve_agents_dir() -> Path:
    """Find the agentxp/agents/ directory from the test file location."""
    here = Path(__file__).resolve()
    # tests/coherence/test_*.py → repo root is parents[2]
    for up in (2, 3, 4):
        candidate = here.parents[up] / "agents" / "consistency_judge.system.md"
        if candidate.exists():
            return candidate.parent
    raise FileNotFoundError("could not locate agents/consistency_judge.system.md")


def test_brief_contradiction_in_pending_decision_kind():
    """``brief_contradiction`` must be a member of PendingDecisionKind so
    OrchestratorStore.set_pending(kind=BRIEF_CONTRADICTION, ...) is valid.

    If this drifts, the Stage-3b r/e/o dialog wiring will silently route
    through some other gate kind and §10.8.2 will be violated.
    """
    from agentxp.schemas.state import PendingDecisionKind

    values = {member.value for member in PendingDecisionKind}
    assert "brief_contradiction" in values

    # Accessing via attribute-style enum lookup (both screaming-snake and
    # snake_case mirror exist per state.py's compatibility shim).
    assert PendingDecisionKind.BRIEF_CONTRADICTION.value == "brief_contradiction"


def test_consistency_judge_findings_match_schema():
    """The consistency_judge prompt must declare the verdict + findings[]
    YAML shape the orchestrator routes on. Grep is sufficient — this is a
    coherence check, not a parse test.
    """
    agents_dir = _resolve_agents_dir()
    prompt = (agents_dir / "consistency_judge.system.md").read_text(encoding="utf-8")

    # Verdict tag — exact strings the orchestrator switches on.
    assert "verdict: pass" in prompt, "missing 'verdict: pass' in prompt"
    assert "verdict: fail" in prompt, "missing 'verdict: fail' in prompt"

    # Findings list is what the dialog renders for the user.
    assert "findings" in prompt, "missing 'findings' field in prompt"

    # The Stage-3b gate kind is referenced by name so the prompt and the
    # PendingDecisionKind enum cannot drift apart silently.
    assert "brief_contradiction" in prompt, (
        "consistency_judge prompt must reference brief_contradiction gate kind"
    )
