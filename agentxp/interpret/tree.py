"""Pure-function 8-step decision tree for the Stage-7 interpreter.

Implements the verdict ladder defined in OPENXP_V01_PLAN.md §22 and emits one
of the 9 closed Verdict labels per §1.8.17 (extended in v0.1 cleanup W0.11):

    INVALID-SRM, NO-SHIP-GUARDRAIL, INCONCLUSIVE, NO-LIFT,
    DIRECTIONAL-ONLY, LIFT-WITH-CAVEAT, SHIP, LEARN, UNVERIFIABLE

Order of evaluation is fixed (Step 1 -> Step 8); the first step that fires
terminates the walk. ``late_ratio`` is formally defined here per M106 /
F.GAP.29 — it is the analyzer-emitted ratio of the late-window primary
effect to the early-window primary effect, used by Step 7 to flag novelty.
This module is a deterministic compute kernel: no I/O, no LLM, no imports
from agentxp.audit / agentxp.orchestrator / agentxp.cli. It is consumed by the
interpreter agent's bundle writer (see ``agents/interpreter.system.md``).

UNVERIFIABLE (added v0.1 W0.11, wired in W1.6) is the "the tree could not
complete" verdict — emitted when a tree-step input is null instead of falling
through to SHIP-default. Preserves Module 3 aha #2 (the order of the steps IS
the priority ranking) under null-input conditions. Renders distinct from
RenderStatus.UNVERIFIABLE — two layers, two "can't check" claims.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


# ──────────────────────────────────────────────────────────────────────────
# Verdict closed set — §1.8.17. Defined here (not imported from
# agentxp.schemas.report) because tree.py is the canonical home per §1.8.17:
# "Defined in agentxp/interpret/tree.py::Verdict = Literal[...]".
# ──────────────────────────────────────────────────────────────────────────

Verdict = Literal[
    "INVALID-SRM",
    "NO-SHIP-GUARDRAIL",
    "INCONCLUSIVE",
    "NO-LIFT",
    "DIRECTIONAL-ONLY",
    "LIFT-WITH-CAVEAT",
    "SHIP",
    "LEARN",
    "UNVERIFIABLE",
]


# ──────────────────────────────────────────────────────────────────────────
# Thresholds — §22. Named constants, not magic numbers.
# ──────────────────────────────────────────────────────────────────────────

MDE_HALF_FRACTION: float = 0.5
"""Step 6 / Step 7: lift magnitude must be >= this * mde_absolute to count as
'meaningful'. Below this fraction, the verdict downgrades from SHIP to
LIFT-WITH-CAVEAT (caveat: small lift)."""

NOLIFT_CI_WIDTH_MULTIPLIER: float = 2.0
"""Step 4: a well-powered null with a CI half-width wider than this *
mde_absolute fires NO-LIFT (study was sized for the MDE but the effect
either doesn't exist or is too small to detect)."""

NOVELTY_LATE_RATIO_FLOOR: float = 0.7
"""Step 7: late_ratio < this fires the novelty downgrade (SHIP -> LIFT-WITH-CAVEAT).
``late_ratio is None`` is treated as >= floor (study too short to compute)
and the diagnostics flag ``late_ratio_unavailable`` is emitted."""


# ──────────────────────────────────────────────────────────────────────────
# Inputs / output dataclasses
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class GuardrailEval:
    """One guardrail's evaluation row.

    Harm-side selection depends on ``direction``:
      - ``higher_is_better``: harm side is the lower end of the CI; violation
        when ``ci_lower_90 > 0`` is FALSE and ``ci_upper_90 < 0`` is TRUE
        (the CI lies entirely below 0).
      - ``lower_is_better``: harm side is the upper end of the CI; violation
        when ``ci_lower_90 > 0`` (the CI lies entirely above 0).
    """
    metric_name: str
    direction: Literal["higher_is_better", "lower_is_better"]
    ci_lower_90: float
    ci_upper_90: float


@dataclass
class TreeInput:
    """Pure-function input. The interpreter's bundle inputs flattened to the
    decision-relevant scalars. See §22 for field semantics.

    Analysis-derived fields are typed ``Optional`` because they may legitimately
    be None during partial analysis (SRM not yet computed, monitoring not
    started, primary metric still pending). Brief-derived fields
    (``n_required``, ``primary_direction``, ``mde_pct``, ``baseline``,
    ``guardrails``) stay non-Optional because a sealed brief always supplies
    them — passing None for a brief-derived field is a malformed-input
    signal and ``walk_tree`` returns ``UNVERIFIABLE`` rather than risking a
    wrong verdict.
    """
    # Step 1 — SRM gate (analysis-derived)
    srm_pass: Optional[bool]
    # Step 2 — Guardrail check (brief + analysis; the list may be empty)
    guardrails: list[GuardrailEval]
    # Step 3 — Sample adequacy
    n_observed: Optional[int]                    # analysis-derived
    n_required: int                              # brief-derived
    # Steps 4-7 — Primary metric (analysis-derived)
    primary_ci_lower_95: Optional[float]
    primary_ci_upper_95: Optional[float]
    primary_ci_lower_90: Optional[float]
    primary_ci_upper_90: Optional[float]
    primary_lift_magnitude: Optional[float]
    # Brief-derived (non-Optional — sealed-brief invariants)
    primary_direction: Literal["higher_is_better", "lower_is_better", "neither"]
    mde_pct: float
    baseline: float
    # Optional fields with defaults
    srm_override_resolved: bool = False
    late_ratio: Optional[float] = None


@dataclass
class TreeResult:
    """Pure-function output of :func:`walk_tree`. ``step_fired`` records every
    step evaluated (including those that passed without firing) in the
    ``"{N}: {rule} ({value})"`` format the interpreter prompt uses.

    ``terminal_step`` is the integer step number (1-8) whose firing produced
    the verdict — the stable, machine-comparable companion to the human-readable
    ``step_fired`` trail. Verdict-tree reproduction (presentation layer W3)
    compares ``(verdict, terminal_step)`` as enum+int and NEVER parses the
    ``step_fired`` strings (whose format is not a stable contract). Purely
    additive: it does not touch the verdict logic.
    """
    verdict: Verdict
    step_fired: list[str]
    terminal_step: int
    diagnostics: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Helpers — pure, no I/O
# ──────────────────────────────────────────────────────────────────────────

def _ci_straddles_zero(lower: float, upper: float) -> bool:
    """True iff the interval [lower, upper] contains 0."""
    return lower <= 0.0 <= upper


def _ci_excludes_zero(lower: float, upper: float) -> bool:
    """True iff the interval [lower, upper] does NOT contain 0."""
    return not _ci_straddles_zero(lower, upper)


def _ci_excludes_zero_on_benefit_side(
    lower: float,
    upper: float,
    direction: Literal["higher_is_better", "lower_is_better", "neither"],
) -> bool:
    """True iff the CI excludes 0 AND lies on the benefit side per direction.

    - higher_is_better: benefit = positive lift => CI lies entirely above 0.
    - lower_is_better:  benefit = negative lift => CI lies entirely below 0.
    - neither: any exclusion of 0 counts as benefit-side (absolute magnitude).
    """
    if not _ci_excludes_zero(lower, upper):
        return False
    if direction == "higher_is_better":
        return lower > 0.0
    if direction == "lower_is_better":
        return upper < 0.0
    return True  # "neither"


def _guardrail_violates(g: GuardrailEval) -> bool:
    """True iff guardrail ``g``'s 90% CI excludes 0 on the harm side.

    See :class:`GuardrailEval` for harm-side definition.
    """
    if g.direction == "higher_is_better":
        # harm = downward movement; violation when CI is entirely below 0
        return g.ci_upper_90 < 0.0
    # lower_is_better — harm = upward movement; violation when CI > 0
    return g.ci_lower_90 > 0.0


def _ci_half_width(lower: float, upper: float) -> float:
    return (upper - lower) / 2.0


def _mde_absolute(mde_pct: float, baseline: float) -> float:
    """Convert relative MDE (percent) to absolute MDE in metric units.

    ``mde_pct = 2.0`` means 2% relative to baseline. ``mde_absolute`` is the
    effect size the study was powered to detect.
    """
    return (mde_pct / 100.0) * baseline


# ──────────────────────────────────────────────────────────────────────────
# late_ratio — formal definition site (M106 / F.GAP.29 / §1.8.18).
#
# The analyzer (W6) is responsible for computing this and writing it into
# ``analyzer.out.yaml``. ``walk_tree`` reads it as an input only. This
# helper exists as the canonical definition site referenced by §1.8.18
# ("``late_ratio: float``, defined in ``agentxp/interpret/tree.py``") and
# is the symbol the canonical-name coherence test pins.
# ──────────────────────────────────────────────────────────────────────────

def compute_late_ratio(
    early_window_effect: float,
    late_window_effect: float,
) -> Optional[float]:
    """Ratio of late-window primary effect to early-window primary effect.

    Definition (M106): split the exposure window into thirds. The
    *early window* is the first third; the *late window* is the last
    third. ``compute_late_ratio = late_window_effect / early_window_effect``.

    - Values near 1.0  -> stable effect over time.
    - Values < 0.7     -> classic novelty pattern (Step 7 downgrades to
      LIFT-WITH-CAVEAT).
    - Values > 1.3     -> primacy-in-reverse / slow-burn (still SHIP per
      the asymmetric threshold).

    Returns ``None`` when the early-window effect is exactly 0 (ratio
    undefined) or when either input is non-finite — callers should pass
    ``None`` through to :class:`TreeInput.late_ratio` so Step 7 treats it
    as ``late_ratio_unavailable``.

    This helper is intentionally minimal; the analyzer owns window-slicing,
    estimation, and sample-size adequacy for the late/early subsets.
    """
    if early_window_effect == 0.0:
        return None
    ratio = late_window_effect / early_window_effect
    # NaN / inf guard — let the interpreter treat them as unavailable.
    if ratio != ratio or ratio in (float("inf"), float("-inf")):
        return None
    return ratio


# ──────────────────────────────────────────────────────────────────────────
# UNVERIFIABLE wiring (W1.6) — per-step required-input declarations.
#
# Every step declares which TreeInput fields it needs to evaluate. Before a
# step runs, ``walk_tree`` checks the declared fields are non-None; if any
# is missing, the walk short-circuits to UNVERIFIABLE with the step number
# whose inputs were incomplete. This preserves the verdict ladder's priority
# ordering under partial-analysis conditions instead of falling through to
# SHIP-default on null (the failure mode the v1 audit B5 surfaced).
#
# Brief-derived fields (mde_pct, baseline, primary_direction, n_required) are
# checked separately at step 0 because they participate in mde_absolute
# computation that runs before any per-step check.
# ──────────────────────────────────────────────────────────────────────────


REQUIRED_INPUTS_PER_STEP: dict[int, tuple[str, ...]] = {
    1: ("srm_pass",),
    2: ("guardrails",),
    3: ("n_observed", "primary_ci_lower_95", "primary_ci_upper_95"),
    4: ("n_observed", "primary_ci_lower_95", "primary_ci_upper_95"),
    5: ("primary_ci_lower_90", "primary_ci_upper_90",
        "primary_ci_lower_95", "primary_ci_upper_95"),
    6: ("primary_lift_magnitude",
        "primary_ci_lower_95", "primary_ci_upper_95"),
    7: ("primary_lift_magnitude",
        "primary_ci_lower_95", "primary_ci_upper_95"),
    # Step 8 is terminal LEARN; we only reach it after prior steps passed,
    # which means their inputs were already validated as non-None.
}


def _unverifiable_at(
    step: int, missing: list[str], diagnostics: dict[str, Any],
) -> TreeResult:
    """Build the UNVERIFIABLE TreeResult for a step with missing inputs."""
    diagnostics = {**diagnostics, "missing_inputs": missing, "unverifiable_step": step}
    return TreeResult(
        verdict="UNVERIFIABLE",
        step_fired=[
            f"{step}: UNVERIFIABLE — required input(s) missing: {', '.join(missing)}"
        ],
        terminal_step=step,
        diagnostics=diagnostics,
    )


def _missing_for(inputs: TreeInput, step: int) -> list[str]:
    """Return the list of required-but-None field names for ``step``."""
    required = REQUIRED_INPUTS_PER_STEP.get(step, ())
    return [name for name in required if getattr(inputs, name) is None]


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

def walk_tree(inputs: TreeInput) -> TreeResult:
    """Walk the 8-step interpreter decision tree (§22).

    Pure function. Deterministic for any given ``inputs``. The first step
    that fires terminates the walk and returns; the ``step_fired`` list
    records every step evaluated, in order, for audit traceability.
    """
    step_fired: list[str] = []
    diagnostics: dict[str, Any] = {}

    # ── Step 0 — brief-derived input pre-flight (UNVERIFIABLE wiring W1.6) ──
    # mde_pct and baseline participate in mde_absolute which is used by every
    # downstream step. They are brief-derived so should always be present, but
    # we defend against a malformed input rather than risk a wrong verdict.
    pre_missing = [
        name for name, val in
        (("mde_pct", inputs.mde_pct), ("baseline", inputs.baseline))
        if val is None
    ]
    if pre_missing:
        return _unverifiable_at(0, pre_missing, diagnostics)

    mde_absolute = _mde_absolute(inputs.mde_pct, inputs.baseline)
    diagnostics["mde_absolute"] = mde_absolute
    # Persist the two inputs to mde_absolute so finalize_report (presentation
    # layer) can source mde_pct + baseline from the interpreter bundle and W3
    # can reproduce mde_absolute identically rather than back-deriving it.
    diagnostics["mde_pct"] = inputs.mde_pct
    diagnostics["baseline"] = inputs.baseline

    # ── Step 1 — SRM gate ────────────────────────────────────────────────
    if (missing := _missing_for(inputs, 1)):
        return _unverifiable_at(1, missing, diagnostics)
    if not inputs.srm_pass and not inputs.srm_override_resolved:
        step_fired.append("1: SRM gate (fail, no override) — INVALID-SRM")
        diagnostics["srm_pass"] = False
        diagnostics["srm_override_resolved"] = False
        return TreeResult(verdict="INVALID-SRM", step_fired=step_fired, terminal_step=1, diagnostics=diagnostics)

    if not inputs.srm_pass and inputs.srm_override_resolved:
        step_fired.append("1: SRM gate (fail, override resolved)")
    else:
        step_fired.append("1: SRM gate (pass)")
    diagnostics["srm_pass"] = inputs.srm_pass
    diagnostics["srm_override_resolved"] = inputs.srm_override_resolved

    # ── Step 2 — Guardrail check ─────────────────────────────────────────
    if (missing := _missing_for(inputs, 2)):
        return _unverifiable_at(2, missing, diagnostics)
    violators = [g for g in inputs.guardrails if _guardrail_violates(g)]
    if violators:
        names = [g.metric_name for g in violators]
        diagnostics["guardrails_violated"] = [
            {
                "metric_name": g.metric_name,
                "direction": g.direction,
                "ci_lower_90": g.ci_lower_90,
                "ci_upper_90": g.ci_upper_90,
            }
            for g in violators
        ]
        step_fired.append(
            f"2: guardrail breach ({', '.join(names)}) — NO-SHIP-GUARDRAIL"
        )
        return TreeResult(
            verdict="NO-SHIP-GUARDRAIL",
            step_fired=step_fired,
            terminal_step=2,
            diagnostics=diagnostics,
        )
    step_fired.append("2: guardrails clear")
    diagnostics["guardrails_violated"] = []

    # ── Step 3 — Sample adequacy ─────────────────────────────────────────
    if (missing := _missing_for(inputs, 3)):
        return _unverifiable_at(3, missing, diagnostics)
    primary_95_straddles = _ci_straddles_zero(
        inputs.primary_ci_lower_95, inputs.primary_ci_upper_95
    )
    diagnostics["n_observed"] = inputs.n_observed
    diagnostics["n_required"] = inputs.n_required
    if inputs.n_observed < inputs.n_required and primary_95_straddles:
        step_fired.append(
            f"3: underpowered (n={inputs.n_observed} < {inputs.n_required}) "
            f"AND primary 95% CI straddles 0 — INCONCLUSIVE"
        )
        return TreeResult(
            verdict="INCONCLUSIVE",
            step_fired=step_fired,
            terminal_step=3,
            diagnostics=diagnostics,
        )
    step_fired.append(
        f"3: sample adequacy check "
        f"(n={inputs.n_observed}, required={inputs.n_required})"
    )

    # ── Step 4 — Primary effect existence (well-powered wide null) ────────
    if (missing := _missing_for(inputs, 4)):
        return _unverifiable_at(4, missing, diagnostics)
    ci_half_width_95 = _ci_half_width(
        inputs.primary_ci_lower_95, inputs.primary_ci_upper_95
    )
    diagnostics["primary_ci_lower_95"] = inputs.primary_ci_lower_95
    diagnostics["primary_ci_upper_95"] = inputs.primary_ci_upper_95
    diagnostics["primary_ci_half_width_95"] = ci_half_width_95

    if (
        primary_95_straddles
        and inputs.n_observed >= inputs.n_required
        and ci_half_width_95 > NOLIFT_CI_WIDTH_MULTIPLIER * mde_absolute
    ):
        step_fired.append(
            f"4: well-powered, wide null "
            f"(CI half-width {ci_half_width_95:.4g} > "
            f"{NOLIFT_CI_WIDTH_MULTIPLIER} * mde_absolute "
            f"{mde_absolute:.4g}) — NO-LIFT"
        )
        return TreeResult(
            verdict="NO-LIFT",
            step_fired=step_fired,
            terminal_step=4,
            diagnostics=diagnostics,
        )
    step_fired.append(
        f"4: not NO-LIFT (CI half-width {ci_half_width_95:.4g} vs "
        f"{NOLIFT_CI_WIDTH_MULTIPLIER}*mde {NOLIFT_CI_WIDTH_MULTIPLIER * mde_absolute:.4g})"
    )

    # ── Step 5 — Primary direction (directional-only signal) ─────────────
    if (missing := _missing_for(inputs, 5)):
        return _unverifiable_at(5, missing, diagnostics)
    primary_90_excludes = _ci_excludes_zero(
        inputs.primary_ci_lower_90, inputs.primary_ci_upper_90
    )
    diagnostics["primary_ci_lower_90"] = inputs.primary_ci_lower_90
    diagnostics["primary_ci_upper_90"] = inputs.primary_ci_upper_90
    if primary_95_straddles and primary_90_excludes:
        step_fired.append(
            f"5: 95% CI straddles 0, 90% CI excludes 0 "
            f"([{inputs.primary_ci_lower_90:.4g}, "
            f"{inputs.primary_ci_upper_90:.4g}]) — DIRECTIONAL-ONLY"
        )
        return TreeResult(
            verdict="DIRECTIONAL-ONLY",
            step_fired=step_fired,
            terminal_step=5,
            diagnostics=diagnostics,
        )
    step_fired.append("5: no directional-only signal")

    # ── Step 6 — Magnitude vs MDE ────────────────────────────────────────
    if (missing := _missing_for(inputs, 6)):
        return _unverifiable_at(6, missing, diagnostics)
    benefit_side_95 = _ci_excludes_zero_on_benefit_side(
        inputs.primary_ci_lower_95,
        inputs.primary_ci_upper_95,
        inputs.primary_direction,
    )
    diagnostics["primary_lift_magnitude"] = inputs.primary_lift_magnitude
    diagnostics["primary_direction"] = inputs.primary_direction
    diagnostics["benefit_side_95"] = benefit_side_95

    abs_lift = abs(inputs.primary_lift_magnitude)
    if benefit_side_95 and abs_lift < MDE_HALF_FRACTION * mde_absolute:
        step_fired.append(
            f"6: 95% CI excludes 0 on benefit side but "
            f"|lift|={abs_lift:.4g} < {MDE_HALF_FRACTION} * mde_absolute "
            f"{mde_absolute:.4g} — LIFT-WITH-CAVEAT (small lift)"
        )
        diagnostics["lift_with_caveat_reason"] = "small_lift"
        return TreeResult(
            verdict="LIFT-WITH-CAVEAT",
            step_fired=step_fired,
            terminal_step=6,
            diagnostics=diagnostics,
        )

    # ── Step 7 — Novelty / late-window ───────────────────────────────────
    if (missing := _missing_for(inputs, 7)):
        return _unverifiable_at(7, missing, diagnostics)
    if benefit_side_95 and abs_lift >= MDE_HALF_FRACTION * mde_absolute:
        # Guardrails already cleared at Step 2.
        if inputs.late_ratio is None:
            diagnostics["late_ratio"] = None
            diagnostics["late_ratio_unavailable"] = True
            step_fired.append(
                "7: late_ratio unavailable (treated as >= "
                f"{NOVELTY_LATE_RATIO_FLOOR}) — SHIP"
            )
            return TreeResult(
                verdict="SHIP",
                step_fired=step_fired,
                terminal_step=7,
                diagnostics=diagnostics,
            )
        diagnostics["late_ratio"] = inputs.late_ratio
        if inputs.late_ratio >= NOVELTY_LATE_RATIO_FLOOR:
            step_fired.append(
                f"7: late_ratio {inputs.late_ratio:.4g} >= "
                f"{NOVELTY_LATE_RATIO_FLOOR} — SHIP"
            )
            return TreeResult(
                verdict="SHIP",
                step_fired=step_fired,
                terminal_step=7,
                diagnostics=diagnostics,
            )
        # Novelty downgrade
        step_fired.append(
            f"7: late_ratio {inputs.late_ratio:.4g} < "
            f"{NOVELTY_LATE_RATIO_FLOOR} — LIFT-WITH-CAVEAT (novelty)"
        )
        diagnostics["lift_with_caveat_reason"] = "novelty"
        return TreeResult(
            verdict="LIFT-WITH-CAVEAT",
            step_fired=step_fired,
            terminal_step=7,
            diagnostics=diagnostics,
        )
    step_fired.append("7: no SHIP path (no benefit-side 95% CI exclusion or lift below MDE/2)")

    # ── Step 8 — LEARN (terminal) ────────────────────────────────────────
    # Distinguish sub-cases for the rationale.
    if primary_95_straddles and inputs.n_observed >= inputs.n_required:
        # Well-powered null. CI half-width was NOT wider than 2*mde
        # (else Step 4 fired) and 90% CI did not exclude 0 (else Step 5
        # fired). So the effect is tight around 0 — a real null.
        ratio = ci_half_width_95 / mde_absolute if mde_absolute != 0 else float("inf")
        step_fired.append(
            f"8: LEARN (well-powered null, CI half-width "
            f"{ratio:.4g} * mde_absolute)"
        )
        diagnostics["learn_subcase"] = "well_powered_null"
    elif primary_95_straddles and inputs.n_observed < inputs.n_required:
        # Underpowered. (Step 3 only fires when BOTH underpowered AND
        # primary 95% straddles 0 — but that path is already covered there.
        # Reaching here means n < required but step 3 didn't fire — which
        # implies primary didn't straddle. The 'elif' is defensive; if we
        # got here with straddling AND underpowered, Step 3 should have
        # returned. Recompute the rationale.)
        ratio = ci_half_width_95 / mde_absolute if mde_absolute != 0 else float("inf")
        step_fired.append(
            f"8: LEARN (underpowered, CI half-width "
            f"{ratio:.4g} * mde_absolute, recommend extend)"
        )
        diagnostics["learn_subcase"] = "underpowered"
    else:
        step_fired.append("8: LEARN (analysis incomplete)")
        diagnostics["learn_subcase"] = "analysis_incomplete"

    return TreeResult(verdict="LEARN", step_fired=step_fired, terminal_step=8, diagnostics=diagnostics)


__all__ = [
    "Verdict",
    "GuardrailEval",
    "TreeInput",
    "TreeResult",
    "walk_tree",
    "compute_late_ratio",
    "MDE_HALF_FRACTION",
    "NOLIFT_CI_WIDTH_MULTIPLIER",
    "NOVELTY_LATE_RATIO_FLOOR",
    "REQUIRED_INPUTS_PER_STEP",
]
