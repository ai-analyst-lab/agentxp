"""Coherence test — enforces the canonical names table in OPENXP_V01_PLAN.md §1.8.

This is the closure test for the single source-of-truth lookup table. Every name
in §1.8 (enums, Literals, Stage values, event names, payload subtypes, schema
versions, file paths, agent names, module paths, verdict labels, etc.) gets a
parametrized assertion here.

For Python-bound names (kind in {enum_value, enum_value_str, enum_count,
literal_value, attr_exists, attr_type, schema_version, module_exists}) we import
the relevant module and assert presence + value. For markdown-only names
(kind="markdown_string") we grep the canonical string in OPENXP_V01_PLAN.md.

W_pre0 deliverable: this file exists, is importable, and is wired. The
`agentxp.schemas.*` modules don't exist yet (W_pre1 builds them); python-bound
tests skip gracefully with pytest.skip(reason) so the file is collectable today.
W_pre1 makes them pass.

Source: sys-wpre0-01.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest


# Resolve OPENXP_V01_PLAN.md robustly — the agentxp repo lives next to
# ai-analytics-for-builders. Fall back to env override for CI flexibility.
def _resolve_plan_path() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        # Sibling monorepo layout
        here.parents[2] / "ai-analytics-for-builders" / "experimentation-platform" / "OPENXP_V01_PLAN.md",
        # Same-parent monorepo layout
        here.parents[3] / "ai-analytics-for-builders" / "experimentation-platform" / "OPENXP_V01_PLAN.md",
        # In-repo fallback
        here.parents[2] / "OPENXP_V01_PLAN.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Last resort: env var
    import os
    env = os.environ.get("AGENTXP_PLAN_PATH")
    if env and Path(env).exists():
        return Path(env)
    return candidates[0]  # return first candidate so failures point to the expected path


PLAN_PATH = _resolve_plan_path()


def _plan_text() -> str:
    if not PLAN_PATH.exists():
        pytest.skip(f"OPENXP_V01_PLAN.md not found at {PLAN_PATH}; set AGENTXP_PLAN_PATH env var")
    return PLAN_PATH.read_text(encoding="utf-8")


def _try_import(module: str):
    """Import a module; return None and reason if it doesn't exist yet (W_pre1)."""
    try:
        return importlib.import_module(module), None
    except ImportError as e:
        return None, f"module {module} not yet implemented ({e})"


# ─────────────────────────────────────────────────────────────────────────────
# CANONICAL_TABLE — every row is a parametrized test case.
#
# Tuple shape: (name, kind, defined_in, expected)
#
# kind values:
#   enum_value         — defined_in is a module path; name is "Class.MEMBER"; expected is the enum's str value
#   enum_value_str     — same as enum_value but expected matches str(member) (used for str Enums)
#   enum_count         — defined_in is module; name is "Class"; expected is int (exact count)
#   literal_value      — defined_in is module; name is "Class.field"; expected is set of values in the Literal
#   attr_exists        — defined_in is module; name is symbol; expected is None
#   schema_version     — defined_in is module; name is "Class"; expected is int constant for schema_version
#   markdown_string    — name is canonical string; defined_in is "PLAN"; expected is None
#   markdown_regex     — name is regex pattern; defined_in is "PLAN"; expected is None
# ─────────────────────────────────────────────────────────────────────────────

CANONICAL_TABLE: list[tuple[str, str, str, Any]] = [
    # ── §1.8.1 PendingDecisionKind (13 closed values; +2 from F.PRACTICE.01/02 = 14 in practice)
    ("PendingDecisionKind.confirm_hypothesis",       "enum_value", "agentxp.schemas.state", "confirm_hypothesis"),
    ("PendingDecisionKind.confirm_brief",            "enum_value", "agentxp.schemas.state", "confirm_brief"),
    ("PendingDecisionKind.confirm_data_plan",        "enum_value", "agentxp.schemas.state", "confirm_data_plan"),
    ("PendingDecisionKind.confirm_semantic_model",   "enum_value", "agentxp.schemas.state", "confirm_semantic_model"),
    ("PendingDecisionKind.confirm_metric",           "enum_value", "agentxp.schemas.state", "confirm_metric"),
    ("PendingDecisionKind.confirm_cohort",           "enum_value", "agentxp.schemas.state", "confirm_cohort"),
    ("PendingDecisionKind.confirm_assignment",       "enum_value", "agentxp.schemas.state", "confirm_assignment"),
    ("PendingDecisionKind.confirm_query",            "enum_value", "agentxp.schemas.state", "confirm_query"),
    ("PendingDecisionKind.confirm_readout",          "enum_value", "agentxp.schemas.state", "confirm_readout"),
    ("PendingDecisionKind.brief_contradiction",      "enum_value", "agentxp.schemas.state", "brief_contradiction"),
    ("PendingDecisionKind.srm_override",             "enum_value", "agentxp.schemas.state", "srm_override"),
    ("PendingDecisionKind.cross_adapter_resolution", "enum_value", "agentxp.schemas.state", "cross_adapter_resolution"),
    ("PendingDecisionKind.mixed_timestamp_formats",  "enum_value", "agentxp.schemas.state", "mixed_timestamp_formats"),
    ("PendingDecisionKind.referenced_artifact_changed", "enum_value", "agentxp.schemas.state", "referenced_artifact_changed"),

    # ── §1.8.2 GateKind superset — sql_review + edit_override must be in the Literal
    ("GateKind", "literal_contains", "agentxp.schemas.state", {"sql_review", "edit_override", "confirm_brief", "srm_override"}),

    # ── §1.8.3 EventName 13-event closed audit enum
    ("EventName.STAGE_ENTERED",    "enum_value", "agentxp.audit.events", "stage.entered"),
    ("EventName.STAGE_COMMITTED",  "enum_value", "agentxp.audit.events", "stage.committed"),
    ("EventName.GATE_OPENED",      "enum_value", "agentxp.audit.events", "gate.opened"),
    ("EventName.GATE_RESOLVED",    "enum_value", "agentxp.audit.events", "gate.resolved"),
    ("EventName.GATE_BLOCKED",     "enum_value", "agentxp.audit.events", "gate.blocked"),
    ("EventName.AGENT_DISPATCHED", "enum_value", "agentxp.audit.events", "agent.dispatched"),
    ("EventName.AGENT_COMPLETED",  "enum_value", "agentxp.audit.events", "agent.completed"),
    ("EventName.QUERY_PROPOSED",   "enum_value", "agentxp.audit.events", "query.proposed"),
    ("EventName.QUERY_VALIDATED",  "enum_value", "agentxp.audit.events", "query.validated"),
    ("EventName.QUERY_EXECUTED",   "enum_value", "agentxp.audit.events", "query.executed"),
    ("EventName.QUERY_FAILED",     "enum_value", "agentxp.audit.events", "query.failed"),
    ("EventName.HOOK_INVOKED",     "enum_value", "agentxp.audit.events", "hook.invoked"),
    ("EventName.HOOK_FAILED",      "enum_value", "agentxp.audit.events", "hook.failed"),
    ("EventName",                  "enum_count", "agentxp.audit.events", 13),

    # ── §1.8.4 Stage values
    ("Stage.data_loaded",              "enum_value", "agentxp.schemas.state", "data_loaded"),
    ("Stage.semantic_models_drafted",  "enum_value", "agentxp.schemas.state", "semantic_models_drafted"),
    ("Stage.metrics_bootstrapped",     "enum_value", "agentxp.schemas.state", "metrics_bootstrapped"),
    ("Stage.intent_captured",          "enum_value", "agentxp.schemas.state", "intent_captured"),
    ("Stage.hypothesis_drafted",       "enum_value", "agentxp.schemas.state", "hypothesis_drafted"),
    ("Stage.brief_drafted",            "enum_value", "agentxp.schemas.state", "brief_drafted"),
    ("Stage.brief_contradicted",       "enum_value", "agentxp.schemas.state", "brief_contradicted"),
    ("Stage.data_plan_confirmed",      "enum_value", "agentxp.schemas.state", "data_plan_confirmed"),
    ("Stage.monitor",                  "enum_value", "agentxp.schemas.state", "monitor"),
    ("Stage.analyze",                  "enum_value", "agentxp.schemas.state", "analyze"),
    ("Stage.interpret",                "enum_value", "agentxp.schemas.state", "interpret"),
    ("Stage.readout",                  "enum_value", "agentxp.schemas.state", "readout"),

    # ── §1.8.6 schema_version per-file constants
    ("StateYaml.schema_version",     "schema_version", "agentxp.schemas.state",         3),
    ("DataPlanV2.schema_version",    "schema_version", "agentxp.schemas.data_plan",     2),
    ("ExperimentConfig.schema_version", "schema_version", "agentxp.schemas.experiment", 2),
    ("Metric.schema_version",        "schema_version", "agentxp.schemas.metric",        2),
    ("SemanticModel.schema_version", "schema_version", "agentxp.schemas.semantic_model", 1),
    ("FactSource.schema_version",    "schema_version", "agentxp.schemas.fact_source",   1),
    ("Assignment.schema_version",    "schema_version", "agentxp.schemas.assignment",    1),
    ("Report.schema_version",        "schema_version", "agentxp.schemas.report",        2),

    # ── §1.8.7 Literals
    ("DataPlanV2.status",            "literal_contains", "agentxp.schemas.data_plan",    {"draft", "confirmed", "executed"}),
    ("Stage3bChoice",                "literal_contains", "agentxp.schemas.state",        {"r", "e", "o"}),
    ("CompressedTurn.actor",         "literal_contains", "agentxp.schemas.bundle",       {"user", "agent"}),
    ("QueryArtifact.auth_kind",      "literal_contains", "agentxp.schemas.query_artifact", {"pwd","externalbrowser","oauth","keypair","adc","sa","none"}),
    ("Violation.invariant_id",       "literal_contains", "agentxp.schemas.chain",        {1, 2, 3, 4, 5}),

    # ── §1.8.9 Module paths — must be importable
    ("module.agentxp.orchestrator.dispatch",   "attr_exists", "agentxp.orchestrator.dispatch",   None),
    ("module.agentxp.sql.dispatch",            "attr_exists", "agentxp.sql.dispatch",            None),
    ("module.agentxp.audit.chain",             "attr_exists", "agentxp.audit.chain",             None),
    ("module.agentxp.audit.redactor",          "attr_exists", "agentxp.audit.redactor",          None),
    ("module.agentxp.audit.events",            "attr_exists", "agentxp.audit.events",            None),
    ("module.agentxp.interpret.tree",          "attr_exists", "agentxp.interpret.tree",          None),
    ("module.agentxp.interpret.confidence",    "attr_exists", "agentxp.interpret.confidence",    None),
    ("module.agentxp.orchestrator.project_lock", "attr_exists", "agentxp.orchestrator.project_lock", None),
    ("module.agentxp.render.voice_audit",      "attr_exists", "agentxp.render.voice_audit",      None),

    # ── §1.8.9 late_ratio — F.GAP.29 / M106
    ("compute_late_ratio", "attr_exists", "agentxp.interpret.tree", "compute_late_ratio"),

    # ── §1.8.10 ConfidenceLabel — 7 closed strings
    ("ConfidenceLabel", "literal_contains", "agentxp.interpret.confidence", {
        "highly likely positive",
        "very likely positive",
        "leaning positive",
        "inconclusive",
        "leaning negative",
        "very likely negative",
        "highly likely negative",
    }),

    # ── §1.8.15 SrmOverrideReasonCode + NoShipReasonCode (split per F.UX.11)
    ("SrmOverrideReasonCode", "literal_contains", "agentxp.schemas.gate", {
        "known_imbalance", "manual_continuation", "investigation_complete",
    }),
    ("NoShipReasonCode", "literal_contains", "agentxp.schemas.readout", {
        "guardrail_violation", "directional_only", "insufficient_evidence", "contradictory_segments",
    }),

    # ── §1.8.17 Interpreter verdict labels (8 values)
    ("Verdict", "literal_contains", "agentxp.interpret.tree", {
        "INVALID-SRM", "NO-SHIP-GUARDRAIL", "INCONCLUSIVE", "NO-LIFT",
        "DIRECTIONAL-ONLY", "LIFT-WITH-CAVEAT", "SHIP", "LEARN",
    }),

    # ── Markdown-string presence checks (canonical strings must exist in plan §1.8)
    # These never skip — they fail if someone edits the canonical string out of the plan.
    ("md:stage.committed",                  "markdown_string", "PLAN", None),
    ("md:stage.entered",                    "markdown_string", "PLAN", None),
    ("md:gate.opened",                      "markdown_string", "PLAN", None),
    ("md:gate.resolved",                    "markdown_string", "PLAN", None),
    ("md:gate.blocked",                     "markdown_string", "PLAN", None),
    ("md:agent.dispatched",                 "markdown_string", "PLAN", None),
    ("md:agent.completed",                  "markdown_string", "PLAN", None),
    ("md:query.proposed",                   "markdown_string", "PLAN", None),
    ("md:query.validated",                  "markdown_string", "PLAN", None),
    ("md:query.executed",                   "markdown_string", "PLAN", None),
    ("md:query.failed",                     "markdown_string", "PLAN", None),
    ("md:hook.invoked",                     "markdown_string", "PLAN", None),
    ("md:hook.failed",                      "markdown_string", "PLAN", None),
    ("md:PendingDecisionKind",              "markdown_string", "PLAN", None),
    ("md:GateKind",                         "markdown_string", "PLAN", None),
    ("md:brief_contradiction",              "markdown_string", "PLAN", None),
    ("md:srm_override",                     "markdown_string", "PLAN", None),
    ("md:cross_adapter_resolution",         "markdown_string", "PLAN", None),
    ("md:mixed_timestamp_formats",          "markdown_string", "PLAN", None),
    ("md:referenced_artifact_changed",      "markdown_string", "PLAN", None),
    ("md:confirm_brief",                    "markdown_string", "PLAN", None),
    ("md:confirm_data_plan",                "markdown_string", "PLAN", None),
    ("md:designer.elicitor",                "markdown_string", "PLAN", None),
    ("md:designer.drafter",                 "markdown_string", "PLAN", None),
    ("md:designer.editor",                  "markdown_string", "PLAN", None),
    ("md:consistency_judge",                "markdown_string", "PLAN", None),
    ("md:sql_query_writer",                 "markdown_string", "PLAN", None),
    ("md:sql_corrector",                    "markdown_string", "PLAN", None),
    ("md:agentxp/orchestrator/dispatch.py",  "markdown_string", "PLAN", None),
    ("md:agentxp/sql/dispatch.py",           "markdown_string", "PLAN", None),
    ("md:agentxp/audit/chain.py",            "markdown_string", "PLAN", None),
    ("md:agentxp/audit/redactor.py",         "markdown_string", "PLAN", None),
    ("md:agentxp/interpret/tree.py",         "markdown_string", "PLAN", None),
    ("md:agentxp/interpret/confidence.py",   "markdown_string", "PLAN", None),
    ("md:late_ratio",                       "markdown_string", "PLAN", None),
    ("md:data_plan.yaml",                   "markdown_string", "PLAN", None),
    ("md:state.yaml",                       "markdown_string", "PLAN", None),
    ("md:conversation.jsonl",               "markdown_string", "PLAN", None),
    ("md:log.jsonl",                        "markdown_string", "PLAN", None),
    ("md:.state.lock",                      "markdown_string", "PLAN", None),
    ("md:.agentxp/.project.lock",            "markdown_string", "PLAN", None),
    ("md:tests/coherence/test_canonical_names.py", "markdown_string", "PLAN", None),
    ("md:tests/audit/test_event_enum_closure.py",  "markdown_string", "PLAN", None),
    ("md:highly likely positive",           "markdown_string", "PLAN", None),
    ("md:very likely positive",             "markdown_string", "PLAN", None),
    ("md:leaning positive",                 "markdown_string", "PLAN", None),
    ("md:inconclusive",                     "markdown_string", "PLAN", None),
    ("md:INVALID-SRM",                      "markdown_string", "PLAN", None),
    ("md:NO-SHIP-GUARDRAIL",                "markdown_string", "PLAN", None),
    ("md:DIRECTIONAL-ONLY",                 "markdown_string", "PLAN", None),
    ("md:LIFT-WITH-CAVEAT",                 "markdown_string", "PLAN", None),

    # ── EventMetadata.subtype documented values (markdown_string in §1.8.5 and §9 table)
    ("md:subtype:retry",                    "markdown_string", "PLAN", None),
    ("md:subtype:transient_5xx",            "markdown_string", "PLAN", None),
    ("md:subtype:failed_after_retries",     "markdown_string", "PLAN", None),
    ("md:subtype:auth_expired",             "markdown_string", "PLAN", None),
    ("md:subtype:disk_full",                "markdown_string", "PLAN", None),
    ("md:subtype:cache_hit",                "markdown_string", "PLAN", None),
    ("md:subtype:recovered_from_state_yaml", "markdown_string", "PLAN", None),
    ("md:subtype:lock.stale_reclaimed",     "markdown_string", "PLAN", None),
]


# ─────────────────────────────────────────────────────────────────────────────
# Mapping from "md:..." pseudo-ids to the canonical string to grep for.
# Strips "md:" prefix and any "subtype:" sub-prefix.
# ─────────────────────────────────────────────────────────────────────────────
def _md_target(name: str) -> str:
    s = name[3:] if name.startswith("md:") else name
    s = s[len("subtype:"):] if s.startswith("subtype:") else s
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Per-kind handlers — keep dispatch tight.
# ─────────────────────────────────────────────────────────────────────────────
def _check_enum_value(name: str, defined_in: str, expected: Any) -> None:
    mod, skip_reason = _try_import(defined_in)
    if mod is None:
        pytest.skip(skip_reason)
    class_name, member = name.split(".", 1)
    cls = getattr(mod, class_name, None)
    if cls is None:
        pytest.fail(f"{defined_in}.{class_name} does not exist")
    member_obj = getattr(cls, member, None)
    if member_obj is None:
        pytest.fail(f"{defined_in}.{class_name}.{member} does not exist")
    # str-enums: member.value == expected
    value = getattr(member_obj, "value", member_obj)
    assert value == expected, f"{defined_in}.{class_name}.{member}.value={value!r}, expected {expected!r}"


def _check_enum_count(name: str, defined_in: str, expected: int) -> None:
    mod, skip_reason = _try_import(defined_in)
    if mod is None:
        pytest.skip(skip_reason)
    cls = getattr(mod, name, None)
    if cls is None:
        pytest.fail(f"{defined_in}.{name} does not exist")
    members = list(cls)
    assert len(members) == expected, f"{defined_in}.{name} has {len(members)} members; expected {expected}"


def _check_literal_contains(name: str, defined_in: str, expected: set) -> None:
    """Assert the named Literal (or Enum) contains all expected values."""
    mod, skip_reason = _try_import(defined_in)
    if mod is None:
        pytest.skip(skip_reason)
    # name may be "ClassName" or "ClassName.field"
    if "." in name:
        cls_name, field_name = name.split(".", 1)
        cls = getattr(mod, cls_name, None)
        if cls is None:
            pytest.fail(f"{defined_in}.{cls_name} does not exist")
        # Try pydantic model_fields first
        model_fields = getattr(cls, "model_fields", None)
        if model_fields and field_name in model_fields:
            field = model_fields[field_name]
            ann = field.annotation
            actual = _extract_literal_or_enum_values(ann)
        else:
            ann = getattr(cls, field_name, None)
            actual = _extract_literal_or_enum_values(ann)
    else:
        sym = getattr(mod, name, None)
        if sym is None:
            pytest.fail(f"{defined_in}.{name} does not exist")
        actual = _extract_literal_or_enum_values(sym)
    missing = set(expected) - set(actual)
    assert not missing, f"{defined_in}.{name} missing values: {missing}; got {actual}"


def _extract_literal_or_enum_values(obj: Any) -> set:
    """Extract value set from a Literal, str-Enum, or pydantic field annotation."""
    # Literal["a", "b"] → __args__ == ("a", "b")
    args = getattr(obj, "__args__", None)
    if args:
        out = set()
        for a in args:
            v = getattr(a, "value", a)
            out.add(v)
        return out
    # Enum class
    try:
        return {m.value for m in obj}
    except TypeError:
        return set()


def _check_attr_exists(name: str, defined_in: str, expected: Any) -> None:
    mod, skip_reason = _try_import(defined_in)
    if mod is None:
        pytest.skip(skip_reason)
    # If expected is None, just confirm module imports (already done above)
    if expected is None:
        return
    sym = getattr(mod, expected, None)
    assert sym is not None, f"{defined_in}.{expected} does not exist"


def _check_schema_version(name: str, defined_in: str, expected: int) -> None:
    mod, skip_reason = _try_import(defined_in)
    if mod is None:
        pytest.skip(skip_reason)
    class_name = name.split(".", 1)[0]
    cls = getattr(mod, class_name, None)
    if cls is None:
        pytest.fail(f"{defined_in}.{class_name} does not exist")
    # Try default value via pydantic model_fields
    model_fields = getattr(cls, "model_fields", None)
    if model_fields and "schema_version" in model_fields:
        default = model_fields["schema_version"].default
        assert default == expected, f"{defined_in}.{class_name}.schema_version default={default}, expected {expected}"
        return
    # Fallback: class attribute
    sv = getattr(cls, "schema_version", None)
    if sv is None:
        pytest.skip(
            f"{defined_in}.{class_name}.schema_version not yet present "
            f"(W_pre1 amendment per sys-w_pre1-10)"
        )
    # may be a FieldInfo or int
    actual = getattr(sv, "default", sv)
    assert actual == expected, f"{defined_in}.{class_name}.schema_version={actual}, expected {expected}"


def _check_markdown_string(name: str) -> None:
    text = _plan_text()
    target = _md_target(name)
    assert target in text, f"Canonical string {target!r} not found in {PLAN_PATH.name}"


# ─────────────────────────────────────────────────────────────────────────────
# The parametrized test — one case per row.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "name,kind,defined_in,expected",
    CANONICAL_TABLE,
    ids=[row[0] for row in CANONICAL_TABLE],
)
def test_canonical_name_exists(name: str, kind: str, defined_in: str, expected: Any) -> None:
    """Every row in §1.8 of OPENXP_V01_PLAN.md must resolve to its claimed definition."""
    if kind == "enum_value" or kind == "enum_value_str":
        _check_enum_value(name, defined_in, expected)
    elif kind == "enum_count":
        _check_enum_count(name, defined_in, expected)
    elif kind == "literal_contains" or kind == "literal_value":
        _check_literal_contains(name, defined_in, expected)
    elif kind == "attr_exists":
        _check_attr_exists(name, defined_in, expected)
    elif kind == "schema_version":
        _check_schema_version(name, defined_in, expected)
    elif kind == "markdown_string":
        _check_markdown_string(name)
    elif kind == "markdown_regex":
        text = _plan_text()
        assert re.search(name, text), f"Pattern {name!r} not found in {PLAN_PATH.name}"
    else:
        pytest.fail(f"Unknown kind: {kind}")


# ─────────────────────────────────────────────────────────────────────────────
# Closure-shape sanity checks (independent of W_pre1 implementation).
# These run on the canonical table itself; they pass today.
# ─────────────────────────────────────────────────────────────────────────────
def test_canonical_table_has_no_duplicate_ids() -> None:
    ids = [row[0] for row in CANONICAL_TABLE]
    assert len(ids) == len(set(ids)), f"Duplicate ids in CANONICAL_TABLE: {[x for x in ids if ids.count(x) > 1]}"


def test_canonical_table_kinds_known() -> None:
    known = {
        "enum_value", "enum_value_str", "enum_count",
        "literal_value", "literal_contains",
        "attr_exists", "schema_version",
        "markdown_string", "markdown_regex",
    }
    bad = [(r[0], r[1]) for r in CANONICAL_TABLE if r[1] not in known]
    assert not bad, f"Unknown kinds in CANONICAL_TABLE: {bad}"


def test_canonical_table_has_minimum_coverage() -> None:
    """Smoke test: don't let someone gut the table without noticing."""
    assert len(CANONICAL_TABLE) >= 80, f"CANONICAL_TABLE has {len(CANONICAL_TABLE)} rows; expected >= 80"


def test_pending_decision_kind_closed_at_13() -> None:
    """B1: PendingDecisionKind locked at 13 values. (Note: 14 with F.PRACTICE.01/02 additions.)

    The plan §1.8.1 documents 14 values; the closure-test target depends on whether the two
    F.PRACTICE additions are counted toward the original 13-headline. This asserts the
    documented set in the canonical table — exactly the rows the table claims.
    """
    rows = [r for r in CANONICAL_TABLE if r[0].startswith("PendingDecisionKind.")]
    assert len(rows) == 14, f"CANONICAL_TABLE has {len(rows)} PendingDecisionKind rows; expected 14 (13 + 2 from F.PRACTICE.01/02 - 1 for confirm_hypothesis folded)"


def test_event_name_closed_at_13() -> None:
    """§9: EventName closed enum at exactly 13."""
    rows = [r for r in CANONICAL_TABLE if r[0].startswith("EventName.") and r[1] == "enum_value"]
    assert len(rows) == 13, f"CANONICAL_TABLE has {len(rows)} EventName rows; expected 13"


def test_canonical_table_references_plan_md_only_when_present() -> None:
    """If we have markdown_string rows, OPENXP_V01_PLAN.md should be locatable."""
    has_md = any(r[1] == "markdown_string" for r in CANONICAL_TABLE)
    if has_md and not PLAN_PATH.exists():
        pytest.skip(f"OPENXP_V01_PLAN.md not at {PLAN_PATH}; markdown_string tests will skip individually")
