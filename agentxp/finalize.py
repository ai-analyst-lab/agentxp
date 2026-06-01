"""Deterministic Stage-8 finalizer — writes the canonical ``report.json``.

This module is the authenticity anchor for the presentation layer. Before it
existed, the LLM readout agent hand-authored ``report.json`` — which meant the
verifiable fields (the chain hash, the locked-brief hash, the verdict-tree
scalars) were written by the very component they are meant to police. That is
the frame risk this module closes: a deterministic core function computes every
verifiable field ITSELF, recomputes the verdict from the analyzer's committed
numbers via the same ``walk_tree`` kernel the interpreter uses, cross-checks
that recomputed verdict against the agent's claimed verdict (raising on
divergence), merges in the agent's PROSE only, and writes ``report.json``.

The numbers police the agent, not the other way around.

Layering note: this module lives OUTSIDE ``agentxp/render/`` on purpose. The
renderer-purity rule (``render/distill.py`` + ``render/adapters/*`` may not
touch the audit log, a warehouse, an LLM, ``experiment.yaml``, or numpy) does
NOT bind the finalizer. ``finalize_report`` is Stage-8 orchestration: it
legitimately reads ``experiment.yaml``, the stage bundles, and calls
``canonical_chain_hash``. It is never imported by a renderer.

Inputs (all under ``exp_dir``), matching the agent-authored bundle contracts:
  - ``bundles/analyzer.out.yaml``     — Stage-6 metric tables (the numbers)
  - ``bundles/interpreter.out.yaml``  — Stage-7 verdict + rationale (cross-check)
  - ``bundles/monitor.out.yaml``      — Stage-5 SRM verdict
  - ``bundles/readout.out.yaml``      — Stage-8 agent PROSE bundle (prose only)
  - ``experiment.yaml``               — the write-once locked brief (design block)

Output: ``<exp_dir>/report.json`` (atomic, chmod 600).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

import agentxp
from agentxp.audit.storage import _atomic_write_bytes, canonical_chain_hash
from agentxp.interpret.tree import (
    GuardrailEval,
    TreeInput,
    TreeResult,
    walk_tree,
)
from agentxp.schemas.report import (
    AuditPaths,
    ConfidenceLabel,
    DiagnosticGate,
    MetricResult,
    Report,
    UncertaintyNote,
)


class FinalizeError(RuntimeError):
    """Raised when ``report.json`` cannot be finalized deterministically.

    The message names the missing/inconsistent artifact so the failure is
    actionable. A finalize failure is fatal at Stage 8: there is no honest
    ``report.json`` to write, so the run does not silently produce one.
    """


# ──────────────────────────────────────────────────────────────────────────
# Bundle loading
# ──────────────────────────────────────────────────────────────────────────

def _load_yaml(path: Path, *, what: str) -> dict[str, Any]:
    if not path.exists():
        raise FinalizeError(f"{what} not found at {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise FinalizeError(f"{what} is not valid YAML ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise FinalizeError(f"{what} did not parse to a mapping ({path})")
    return data


def _require(d: dict[str, Any], key: str, *, what: str) -> Any:
    if key not in d or d[key] is None:
        raise FinalizeError(f"{what} is missing required key '{key}'")
    return d[key]


def _arm(per_arm: Any, *, control: bool) -> Optional[int]:
    """Pull the control/treatment count from an ``n_observed_per_arm`` mapping.

    The mapping is keyed on variant name. We match the conventional
    ``control`` / ``treatment`` names; an unconventional pair falls back to
    sorted order (control = first key) so the field is still populated.
    """
    if not isinstance(per_arm, dict) or not per_arm:
        return None
    want = "control" if control else "treatment"
    for name, n in per_arm.items():
        if str(name).lower() == want:
            return int(n)
    keys = sorted(per_arm)
    pick = keys[0] if control else keys[-1]
    return int(per_arm[pick])


def _baseline(primary: dict[str, Any]) -> Optional[float]:
    """Source the control-arm baseline for the primary metric.

    Precedence: an explicit ``baseline`` field on the analyzer block (future-
    proof — the analyzer may emit it directly), else derive it from the
    relative/absolute lift identity ``baseline = lift_absolute / (lift_pct/100)``
    when ``lift_pct`` is non-zero. A near-null ``lift_pct`` makes the derivation
    undefined → ``None`` (which downstream resolves to UNVERIFIABLE, never a
    false accusation).
    """
    if primary.get("baseline") is not None:
        return float(primary["baseline"])
    lift_pct = primary.get("lift_pct")
    lift_abs = primary.get("lift_absolute")
    if lift_pct in (None, 0, 0.0) or lift_abs is None:
        return None
    return float(lift_abs) / (float(lift_pct) / 100.0)


# ──────────────────────────────────────────────────────────────────────────
# TreeInput reconstruction + deterministic verdict recompute
# ──────────────────────────────────────────────────────────────────────────

def _build_tree_input(
    *,
    primary: dict[str, Any],
    guardrails: list[dict[str, Any]],
    monitor: dict[str, Any],
    interpreter: dict[str, Any],
    design: dict[str, Any],
    n_observed: int,
    n_required: int,
    baseline: float,
    mde_pct: float,
) -> TreeInput:
    srm_pass = bool(monitor.get("srm_pass", True))
    # An override is "resolved" when SRM failed AND the monitor recorded a
    # reason code (the user's accepted-risk path the interpreter walked past).
    override_resolved = bool(
        (not srm_pass) and monitor.get("srm_override_reason_code")
    )
    # Prefer the interpreter's own recorded resolution if present.
    diag = interpreter.get("diagnostics") or {}
    if isinstance(diag, dict) and diag.get("srm_override_resolved") is not None:
        override_resolved = bool(diag["srm_override_resolved"])

    g_evals: list[GuardrailEval] = []
    for g in guardrails:
        g_evals.append(
            GuardrailEval(
                metric_name=str(_require(g, "metric_name", what="guardrail row")),
                direction=_require(g, "direction", what="guardrail row"),
                ci_lower_90=float(_require(g, "ci_lower_90", what="guardrail row")),
                ci_upper_90=float(_require(g, "ci_upper_90", what="guardrail row")),
            )
        )

    return TreeInput(
        srm_pass=srm_pass,
        guardrails=g_evals,
        n_observed=n_observed,
        n_required=n_required,
        primary_ci_lower_95=float(_require(primary, "ci_lower_95", what="primary")),
        primary_ci_upper_95=float(_require(primary, "ci_upper_95", what="primary")),
        primary_ci_lower_90=float(_require(primary, "ci_lower_90", what="primary")),
        primary_ci_upper_90=float(_require(primary, "ci_upper_90", what="primary")),
        primary_lift_magnitude=float(_require(primary, "lift_absolute", what="primary")),
        primary_direction=_require(primary, "direction", what="primary"),
        mde_pct=mde_pct,
        baseline=baseline,
        srm_override_resolved=override_resolved,
        late_ratio=primary.get("late_ratio"),
    )


# ──────────────────────────────────────────────────────────────────────────
# Report assembly
# ──────────────────────────────────────────────────────────────────────────

def _metric_row(
    block: dict[str, Any],
    *,
    metric_type: str,
    confidence_label: ConfidenceLabel,
    audit_paths: AuditPaths,
) -> MetricResult:
    per_arm = block.get("n_observed_per_arm")
    return MetricResult(
        name=str(_require(block, "metric_name", what=f"{metric_type} block")),
        type=metric_type,  # type: ignore[arg-type]
        lift_absolute=float(_require(block, "lift_absolute", what=f"{metric_type} block")),
        lift_relative=float(_require(block, "lift_pct", what=f"{metric_type} block")),
        ci_95_lower=float(_require(block, "ci_lower_95", what=f"{metric_type} block")),
        ci_95_upper=float(_require(block, "ci_upper_95", what=f"{metric_type} block")),
        ci_90_lower=float(_require(block, "ci_lower_90", what=f"{metric_type} block")),
        ci_90_upper=float(_require(block, "ci_upper_90", what=f"{metric_type} block")),
        p_value=float(_require(block, "p_value", what=f"{metric_type} block")),
        confidence_label=confidence_label,
        audit_paths=audit_paths,
        direction=block.get("direction"),
        n_arm_control=_arm(per_arm, control=True),
        n_arm_treatment=_arm(per_arm, control=False),
        mean_arm_control=block.get("mean_arm_control"),
        mean_arm_treatment=block.get("mean_arm_treatment"),
    )


def _uncertainty_notes(readout: dict[str, Any]) -> list[UncertaintyNote]:
    notes_raw = readout.get("uncertainty_notes") or []
    notes: list[UncertaintyNote] = []
    for entry in notes_raw:
        if isinstance(entry, str):
            notes.append(UncertaintyNote(topic="caveat", detail=entry))
        elif isinstance(entry, dict):
            notes.append(
                UncertaintyNote(
                    topic=str(entry.get("topic", "caveat")),
                    detail=str(entry.get("detail", "")),
                    audit_link=entry.get("audit_link"),
                )
            )
    return notes


def finalize_report(exp_dir: Path) -> Path:
    """Compute and atomically write the canonical ``report.json``.

    Called at Stage 8 by the orchestrator AFTER the readout agent emits its
    prose bundle and BEFORE anything reads ``report.json``. Returns the path
    written. Raises :class:`FinalizeError` if a required artifact is missing or
    the recomputed verdict diverges from the agent's claimed verdict.
    """
    exp_dir = Path(exp_dir)
    bundles = exp_dir / "bundles"

    analyzer = _load_yaml(bundles / "analyzer.out.yaml", what="analyzer bundle")
    interpreter = _load_yaml(bundles / "interpreter.out.yaml", what="interpreter bundle")
    monitor = _load_yaml(bundles / "monitor.out.yaml", what="monitor bundle")
    readout = _load_yaml(bundles / "readout.out.yaml", what="readout prose bundle")
    brief = _load_yaml(exp_dir / "experiment.yaml", what="experiment.yaml")

    primary = _require(analyzer, "primary", what="analyzer bundle")
    guardrails = analyzer.get("guardrails") or []
    design = brief.get("design") or {}

    experiment_id = (
        interpreter.get("exp_id")
        or analyzer.get("exp_id")
        or brief.get("id")
        or exp_dir.name
    )

    # ── verifiable scalars sourced from numbers, never agent prose ──
    # Explicit None resolution — a legitimate n_observed of 0 must not be
    # coerced to "missing" by an `or` chain (it would silently fall through).
    n_observed_raw = primary.get("n_observed_total")
    if n_observed_raw is None:
        n_observed_raw = (interpreter.get("diagnostics") or {}).get("n_observed")
    if n_observed_raw is None:
        raise FinalizeError(
            "could not determine n_observed (analyzer 'n_observed_total' and "
            "interpreter diagnostics 'n_observed' are both absent)"
        )
    n_observed = int(n_observed_raw)
    n_required = int(
        _require(design, "n_required", what="experiment.yaml design block")
    )
    mde_pct = float(_require(design, "mde_pct", what="experiment.yaml design block"))
    baseline = _baseline(primary)
    if baseline is None:
        raise FinalizeError(
            "could not determine primary baseline (no analyzer 'baseline' field "
            "and lift_pct is zero/absent — cannot reconstruct TreeInput)"
        )

    # ── deterministic verdict recompute (the agent-policing step) ──
    tree_input = _build_tree_input(
        primary=primary,
        guardrails=guardrails,
        monitor=monitor,
        interpreter=interpreter,
        design=design,
        n_observed=n_observed,
        n_required=n_required,
        baseline=baseline,
        mde_pct=mde_pct,
    )
    tree: TreeResult = walk_tree(tree_input)

    claimed_verdict = interpreter.get("verdict")
    if claimed_verdict is None:
        raise FinalizeError(
            "interpreter bundle is missing 'verdict' — there is nothing to "
            "cross-check the deterministic recompute against. Refusing to "
            "finalize a report whose verdict would go unpoliced."
        )
    if claimed_verdict != tree.verdict:
        raise FinalizeError(
            "verdict divergence: interpreter agent claimed "
            f"{claimed_verdict!r} but the deterministic tree recomputes "
            f"{tree.verdict!r} from the analyzer numbers. The numbers win; "
            "the run is not finalized to hide the discrepancy."
        )

    confidence_label = ConfidenceLabel(
        interpreter.get("confidence_label", ConfidenceLabel.INCONCLUSIVE.value)
    )

    bundle_ref = AuditPaths(
        bundles=[
            "bundles/analyzer.out.yaml",
            "bundles/interpreter.out.yaml",
            "bundles/monitor.out.yaml",
            "bundles/readout.out.yaml",
        ]
    )

    primary_row = _metric_row(
        primary,
        metric_type="primary",
        confidence_label=confidence_label,
        audit_paths=bundle_ref,
    )
    guardrail_rows = [
        _metric_row(
            g,
            metric_type="guardrail",
            confidence_label=confidence_label,
            audit_paths=bundle_ref,
        )
        for g in guardrails
    ]

    diagnostics_gate = DiagnosticGate(
        srm_passed=bool(monitor.get("srm_pass", True)),
        power_sufficient=(n_observed >= n_required),
        audit_paths=bundle_ref,
    )

    # ── provenance, computed by the core (not the agent) ──
    chain_hash = canonical_chain_hash(exp_dir)
    brief_path = exp_dir / "experiment.yaml"
    locked_brief_hash = hashlib.sha256(brief_path.read_bytes()).hexdigest()

    rationale = (
        interpreter.get("rationale_one_line")
        or readout.get("verdict_rationale")
        or ""
    )
    decision_rule = brief.get("decision_rule") or "agentxp_default"
    decision_rule_source = (
        "agentxp_default" if decision_rule == "agentxp_default" else "user_defined"
    )

    report = Report(
        schema_version=2,
        experiment_id=str(experiment_id),
        generated_at=datetime.now(timezone.utc),
        verdict=tree.verdict,
        verdict_rationale=str(rationale).strip(),
        step_fired=tree.terminal_step,  # type: ignore[arg-type]
        decision_rule_id=str(decision_rule),
        decision_rule_source=decision_rule_source,  # type: ignore[arg-type]
        diagnostics=diagnostics_gate,
        primary=primary_row,
        guardrails=guardrail_rows,
        uncertainty_notes=_uncertainty_notes(readout),
        audit_paths=bundle_ref,
        # provenance (core-written)
        chain_hash=chain_hash,
        locked_brief_hash=locked_brief_hash,
        agentxp_version=agentxp.__version__,
        # design-card
        name=brief.get("name"),
        hypothesis=(brief.get("hypothesis") or {}).get("text"),
        power=design.get("power"),
        ci_level=0.95,
        # verdict-tree-reproduction scalars
        srm_override_resolved=tree_input.srm_override_resolved,
        n_observed=n_observed,
        n_required=n_required,
        primary_direction=tree_input.primary_direction,
        mde_pct=mde_pct,
        baseline=baseline,
        late_ratio=tree_input.late_ratio,
    )

    out_path = exp_dir / "report.json"
    _atomic_write_bytes(
        out_path,
        (report.model_dump_json(indent=2) + "\n").encode("utf-8"),
    )
    return out_path


__all__ = ["finalize_report", "FinalizeError"]
