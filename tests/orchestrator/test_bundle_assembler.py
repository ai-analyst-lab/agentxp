"""T61 — Bundle assembler tests (closure-test for R5/R6/R10).

These tests assert two invariants:

  1. The BLINDNESS_MANIFEST in agentxp.schemas.bundles is structurally
     enforced — for each role, every field name in the manifest's
     forbidden list is absent from the bundle's model_fields.
  2. The assemble() function rejects unauthorized fields at construction
     time (Pydantic extra="forbid" works as expected through the
     assembler).

Failure of either is an audit point: widening a bundle's allowed context
must be a visible schema edit (with rationale in the commit message),
not an accidental config drift.
"""
from __future__ import annotations

import pytest

from agentxp.orchestrator.bundle_assembler import (
    AssembledBundle,
    BundleAssemblyError,
    UnknownSpecialistRole,
    assemble,
    assert_blindness_manifest_holds,
)
from agentxp.schemas.bundles import (
    BLINDNESS_MANIFEST,
    BUNDLE_SCHEMAS,
    ArtifactRef,
    AssignmentSurface,
    ClaimedScope,
    DecisionRule,
    GuardrailResult,
    MetricResult,
    SrmResult,
    SqlIntent,
    WarehouseProfile,
    WarehouseSchema,
)


# ─────────────────────────────────────────────────────────────────────────────
# Closure test — BLINDNESS_MANIFEST is structurally enforced
# ─────────────────────────────────────────────────────────────────────────────


def test_blindness_manifest_holds_at_runtime():
    """assert_blindness_manifest_holds() does not raise on the current state."""
    assert_blindness_manifest_holds()


@pytest.mark.parametrize("role,forbidden", list(BLINDNESS_MANIFEST.items()))
def test_each_role_lacks_its_forbidden_fields(role, forbidden):
    """For every (role, forbidden_field) pair, the bundle schema does NOT
    declare that field. This is the discipline-as-code: a developer who
    adds an outcome-revealing field to a bundle gets caught by this test
    before it lands."""
    schema = BUNDLE_SCHEMAS[role]
    declared = set(schema.model_fields.keys())
    overlap = set(forbidden) & declared
    assert not overlap, (
        f"{role} bundle declares fields that should be blind to it: {overlap}. "
        f"See agentxp/schemas/bundles.py and rebuild/CLAUDE.md R5/R6/R10."
    )


def test_blindness_manifest_covers_every_registered_role():
    """Every bundle in BUNDLE_SCHEMAS appears in the manifest, even if
    its forbidden-field list is empty (e.g. sql_specialist is bounded-
    context, not adversarially blind). Forces a manifest review when a
    new role is added."""
    assert set(BLINDNESS_MANIFEST.keys()) == set(BUNDLE_SCHEMAS.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Unknown role rejection
# ─────────────────────────────────────────────────────────────────────────────


def test_assemble_raises_on_unknown_role():
    with pytest.raises(UnknownSpecialistRole) as excinfo:
        assemble("not_a_real_role", {})
    msg = str(excinfo.value)
    assert "not_a_real_role" in msg
    # The error names the registered roles so the caller can self-correct.
    for role in BUNDLE_SCHEMAS:
        assert role in msg


# ─────────────────────────────────────────────────────────────────────────────
# R10 enforcement — extra fields are refused
# ─────────────────────────────────────────────────────────────────────────────


def test_understander_assembly_rejects_intent_field():
    """The Understander must be blind to experiment intent (prevents
    metric-fishing). Passing an `intent` field through the assembler
    must raise BundleAssemblyError, not silently drop it."""
    sources = {
        "warehouse_profile": WarehouseProfile(tables={}, flags=[]),
        "existing_semantic_models": [],
        "existing_metrics": [],
        "task": "draft_semantic_models",
        "intent": {"text": "test X improves conversion"},   # FORBIDDEN
    }
    with pytest.raises(BundleAssemblyError) as excinfo:
        assemble("understander", sources)
    assert "understander" in str(excinfo.value)
    # The underlying pydantic error names the offending field.
    assert "intent" in str(excinfo.value.__cause__)


def test_critic_assembly_rejects_producer_reasoning():
    """The Critic judges blind. Passing producer_reasoning through must
    raise — R6 enforcement."""
    sources = {
        "artifact": ArtifactRef(path="brief.yaml", sha256="a" * 64, kind="brief"),
        "artifact_payload": {"hypothesis": "X"},
        "claimed_scope": ClaimedScope(claim="tests X", cites=[]),
        "judging_mode": "brief_consistency",
        "producer_reasoning": "I drafted this by thinking about...",   # FORBIDDEN
    }
    with pytest.raises(BundleAssemblyError):
        assemble("critic", sources)


def test_analyst_narrator_assembly_rejects_hypothesis():
    """The narrator describes stats. Passing the hypothesis prose biases
    the narrative direction — R5 forbids it."""
    sources = {
        "metric_results": [],
        "brief_decision_rules": [],
        "srm_result": SrmResult(
            verdict="PASS", chi2=0.1, p_value=0.95,
            observed_counts={"c": 100, "t": 100},
            expected_ratios={"c": 0.5, "t": 0.5},
        ),
        "guardrail_results": [],
        "confidence_labels": [],
        "hypothesis": "treatment should win",   # FORBIDDEN
    }
    with pytest.raises(BundleAssemblyError):
        assemble("analyst_narrator", sources)


def test_designer_assembly_rejects_analysis_output():
    """The designer drafts pre-registered artifacts. Seeing analysis
    output (lift, CI, etc.) is the peek-prevention failure mode the
    design verb's whole architecture is built to prevent."""
    sources = {
        "intent": {"text": "test X", "captured_at": "2026-06-04T00:00:00Z"},
        "semantic_models": [],
        "metrics": [],
        "assignment_surface": AssignmentSurface(
            units_available=100_000, accrual_per_day=5_000.0,
            segments=[], assignment_unit="user_id",
        ),
        "prior_drafts": [],
        "task": "draft_brief",
        "lift": 0.10,   # FORBIDDEN
    }
    with pytest.raises(BundleAssemblyError):
        assemble("designer", sources)


# ─────────────────────────────────────────────────────────────────────────────
# Happy path — valid sources produce a hashed bundle
# ─────────────────────────────────────────────────────────────────────────────


def test_assemble_returns_hashed_bundle():
    """Valid sources produce an AssembledBundle with a non-empty sha256."""
    sources = {
        "warehouse_profile": WarehouseProfile(tables={}, flags=[]),
        "existing_semantic_models": [],
        "existing_metrics": [],
        "task": "draft_semantic_models",
    }
    result = assemble("understander", sources)
    assert isinstance(result, AssembledBundle)
    assert result.role == "understander"
    assert len(result.sha256) == 64
    assert result.sha256 != "0" * 64


def test_assemble_is_deterministic_for_identical_inputs():
    """Re-running with the same source produces the same sha256."""
    sources = {
        "warehouse_profile": WarehouseProfile(tables={"users": {"id": {}}}, flags=["a"]),
        "existing_semantic_models": [],
        "existing_metrics": [],
        "task": "draft_metrics",
    }
    a = assemble("understander", sources)
    b = assemble("understander", sources)
    assert a.sha256 == b.sha256


def test_assemble_hash_changes_when_source_changes():
    """Different sources produce different hashes (sanity check on the
    canonicalization)."""
    s1 = {
        "warehouse_profile": WarehouseProfile(tables={}, flags=[]),
        "existing_semantic_models": [],
        "existing_metrics": [],
        "task": "draft_semantic_models",
    }
    s2 = dict(s1, task="draft_metrics")
    a = assemble("understander", s1)
    b = assemble("understander", s2)
    assert a.sha256 != b.sha256


# ─────────────────────────────────────────────────────────────────────────────
# Coverage — every role can produce a valid bundle from minimal sources
# ─────────────────────────────────────────────────────────────────────────────


def _minimal_sources_for(role: str) -> dict:
    """Return minimum-viable sources for a role's bundle. Used to assert
    every role has a constructible happy-path bundle."""
    if role == "understander":
        return {
            "warehouse_profile": WarehouseProfile(tables={}, flags=[]),
            "existing_semantic_models": [],
            "existing_metrics": [],
            "task": "draft_semantic_models",
        }
    if role == "designer":
        return {
            "intent": {"text": "test X", "captured_at": "2026-06-04T00:00:00Z"},
            "semantic_models": [],
            "metrics": [],
            "assignment_surface": AssignmentSurface(
                units_available=100_000, accrual_per_day=5_000.0,
                segments=[], assignment_unit="user_id",
            ),
            "prior_drafts": [],
            "task": "draft_brief",
        }
    if role == "critic":
        return {
            "artifact": ArtifactRef(path="brief.yaml", sha256="a" * 64, kind="brief"),
            "artifact_payload": {"hypothesis": "X"},
            "claimed_scope": ClaimedScope(claim="tests X", cites=[]),
            "cited_inputs": [],
            "judging_mode": "brief_consistency",
        }
    if role == "sql_specialist":
        return {
            "intent": SqlIntent(purpose="srm_check", description="check assignment ratio"),
            "warehouse_schema": WarehouseSchema(tables={"users": {"user_id": "VARCHAR"}}),
            "semantic_models": [],
            "verb": "design",
            "brief_ref": None,
            "prior_attempt": None,
        }
    if role == "analyst_narrator":
        return {
            "metric_results": [],
            "brief_decision_rules": [],
            "srm_result": SrmResult(
                verdict="PASS", chi2=0.1, p_value=0.95,
                observed_counts={"c": 100, "t": 100},
                expected_ratios={"c": 0.5, "t": 0.5},
            ),
            "guardrail_results": [],
            "confidence_labels": [],
        }
    raise ValueError(f"no minimal-sources fixture for role {role!r}")


@pytest.mark.parametrize("role", list(BUNDLE_SCHEMAS.keys()))
def test_every_role_has_constructible_happy_path(role):
    """Every registered role assembles cleanly from minimum-viable sources.
    Asserts the bundle schemas are not so strict that they're unusable."""
    sources = _minimal_sources_for(role)
    result = assemble(role, sources)
    assert result.role == role
    assert isinstance(result.sha256, str) and len(result.sha256) == 64
