"""Authenticity provenance — the receipts that make a rendered report credible.

``build_provenance(report, exp_dir)`` is the IMPURE companion to the pure
``distill()``. It recomputes verification facts from disk (the chain hash, the
chain-validation result, the verdict-tree reproduction) rather than trusting the
values stored in ``report.json``. ``distill()`` NEVER calls this — the split is
deliberate: a renderer stays pure and offline, while verification is an explicit,
separately-callable step the CLI runs once and bundles in.

Three-state status (one-directional — any "can't check" demotes, never promotes):

  - **VERIFIED** (green): requires ALL of — ``log.jsonl`` present, stored
    ``chain_hash`` present, recomputed hash == stored, ``validate_chain`` ok,
    and the verdict tree reproduces. Achievable only once the full live flow
    lands in W3.
  - **DRAFT_UNVERIFIED** (red): an ACTIVE failure — a hash mismatch or a
    tree-reproduction failure. An accusation; reserved for real contradictions.
  - **UNVERIFIABLE** (neutral gray): "can't check" — schema_version 1, or
    ``chain_hash``/``log.jsonl`` absent, or a required tree-reproduction scalar
    is missing (half-migrated v2). NOT an accusation.

The full live flow (W3) runs in strict precedence: (0) the "can't-check" gate;
(1) recompute ``canonical_chain_hash``; (2) compare to the stored hash;
(3) ``validate_chain`` (perf-budget blow-out degrades to UNVERIFIABLE, never an
accusation); (4) verdict-tree reproduction (``receipts._reproduce_verdict``);
(5) VERIFIED iff log + stored hash present AND hash matches AND ``cv.ok`` AND the
verdict reproduces. An active failure (hash mismatch or tree-reproduction
failure) resolves to DRAFT_UNVERIFIED with the first-failing-check reason
(precedence chain → hash → tree). One-directional: any "can't check" demotes to
UNVERIFIABLE and never promotes to VERIFIED.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from agentxp.schemas.report import Report

# The 7 verdict-tree-reproduction scalars that must ALL be present for a
# schema_version-2 report to be eligible for tree reproduction (W3). A missing
# scalar is the "half-migrated" case → UNVERIFIABLE, never DRAFT_UNVERIFIED.
_TREE_REPRO_SCALARS = (
    "srm_override_resolved",
    "n_observed",
    "n_required",
    "primary_direction",
    "mde_pct",
    "baseline",
    # late_ratio is intentionally NOT required: None is a legal walk_tree input
    # (treated as ">= novelty floor"), so its absence does not block reproduction.
)


class RenderStatus(str, Enum):
    """Three-state verification status. One-directional: can't-check never VERIFIED."""
    VERIFIED = "verified"
    DRAFT_UNVERIFIED = "draft_unverified"
    UNVERIFIABLE = "unverifiable"


class Provenance(BaseModel):
    """Frozen authenticity receipts for one rendered report.

    Tier-tagged: ``chain_hash_stored`` / ``locked_brief_hash`` /
    ``agentxp_version`` are RECORDED receipts read from ``report.json``;
    ``chain_hash_live`` / ``hash_matches`` / ``chain_validation_ok`` /
    ``tree_reproduces`` are VERIFIED receipts recomputed from disk (populated by
    W2/W3). ``render_status`` is the resolved verdict over all of them.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    experiment_id: str
    render_status: RenderStatus
    status_reason: str  # one-line human explanation of the status

    # ── recorded receipts (from report.json — trusted only as "claimed") ──
    chain_hash_stored: Optional[str] = None
    locked_brief_hash: Optional[str] = None  # "recorded" receipt; NOT in the VERIFIED gate
    agentxp_version: Optional[str] = None
    report_schema_version: int = 2

    # ── verified receipts (recomputed from disk — None until W2/W3 run them) ──
    chain_hash_live: Optional[str] = None
    hash_matches: Optional[bool] = None
    chain_validation_ok: Optional[bool] = None
    tree_reproduces: Optional[bool] = None

    # ── replay affordance ──
    replay_command: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Can't-check gate — the precedence-zero step, live from Wave 1
# ──────────────────────────────────────────────────────────────────────────

def _cant_check_reason(report: Report, exp_dir: Path) -> Optional[str]:
    """Return a reason string iff the report CANNOT be verified, else None.

    Runs BEFORE any reproduction is attempted (W3 precedence step 0). A report
    that trips this gate resolves to UNVERIFIABLE — never DRAFT_UNVERIFIED — so
    a missing input is never surfaced as an accusation of tampering.
    """
    if report.schema_version == 1:
        return "schema_version 1 predates provenance fields — cannot verify"
    if not report.chain_hash:
        return "no chain_hash recorded in report.json — cannot verify"
    if not (exp_dir / "log.jsonl").exists():
        return "log.jsonl absent — nothing to recompute the chain hash from"
    missing = [s for s in _TREE_REPRO_SCALARS if getattr(report, s, None) is None]
    if missing:
        return (
            "half-migrated schema_version 2 — missing tree-reproduction "
            f"scalar(s): {', '.join(missing)}"
        )
    return None


def build_provenance(report: Report, exp_dir: Path) -> Provenance:
    """Recompute authenticity receipts for ``report`` rooted at ``exp_dir``.

    Wave 1 behavior: populate the recorded receipts, run the can't-check gate,
    and resolve UNVERIFIABLE either for a gate trip or for the not-yet-run live
    flow. W2 adds the minimal hash recompute; W3 adds full ``validate_chain`` +
    tree reproduction and the VERIFIED / DRAFT_UNVERIFIED resolution.

    Call-shape note: ``validate_chain`` takes ``(experiment_id, *, _root=...)``,
    not an ``exp_dir`` — so callers split ``exp_dir`` into
    ``experiment_id = exp_dir.name`` and ``root = exp_dir.parent``. W1 records
    this split in ``experiment_id`` / ``replay_command``; W3 issues the call.
    """
    exp_dir = Path(exp_dir)
    experiment_id = exp_dir.name
    replay_command = f"agentxp audit {experiment_id}"

    recorded = dict(
        experiment_id=experiment_id,
        chain_hash_stored=report.chain_hash,
        locked_brief_hash=report.locked_brief_hash,
        agentxp_version=report.agentxp_version,
        report_schema_version=report.schema_version,
        replay_command=replay_command,
    )

    # ── Step 0 — can't-check gate (precedence zero, before any reproduction) ──
    cant = _cant_check_reason(report, exp_dir)
    if cant is not None:
        return Provenance(
            render_status=RenderStatus.UNVERIFIABLE,
            status_reason=cant,
            **recorded,
        )

    # ── Step 1 — recompute the chain hash from log.jsonl (never trust stored) ──
    try:
        from agentxp.audit.storage import canonical_chain_hash

        live_hash = canonical_chain_hash(exp_dir)
    except Exception as e:  # noqa: BLE001 — never crash a render over verification
        return Provenance(
            render_status=RenderStatus.UNVERIFIABLE,
            status_reason=f"could not recompute chain hash ({type(e).__name__})",
            **recorded,
        )

    # ── Step 2 — does the recomputed hash match the recorded one? ──
    hash_matches = live_hash == report.chain_hash

    # ── Step 3 — run the 5 chain invariants (validate_chain). A perf-budget
    # blow-out is a "can't check", never an accusation — degrade to UNVERIFIABLE.
    from agentxp.audit.chain import PerfBudgetExceeded, validate_chain

    try:
        cv = validate_chain(experiment_id, _root=exp_dir.parent)
    except PerfBudgetExceeded:
        return Provenance(
            render_status=RenderStatus.UNVERIFIABLE,
            status_reason=(
                "chain validation exceeded its time budget — cannot verify "
                "within the perf cap"
            ),
            chain_hash_live=live_hash,
            hash_matches=hash_matches,
            **recorded,
        )
    except Exception as e:  # noqa: BLE001 — never crash a render over verification
        return Provenance(
            render_status=RenderStatus.UNVERIFIABLE,
            status_reason=f"chain validation could not run ({type(e).__name__})",
            chain_hash_live=live_hash,
            hash_matches=hash_matches,
            **recorded,
        )
    cv_ok = cv.ok

    # ── Step 4 — reproduce the verdict from the recorded inputs (W3-T2). A None
    # means the inputs are incomplete (can't check), not a contradiction. The
    # can't-check gate already guards the 7 scalars; this also guards a missing
    # per-guardrail direction → UNVERIFIABLE.
    from agentxp.render.receipts import _reproduce_verdict

    tree_reproduces = _reproduce_verdict(report)
    if tree_reproduces is None:
        return Provenance(
            render_status=RenderStatus.UNVERIFIABLE,
            status_reason=(
                "verdict-tree inputs are incomplete (a guardrail direction or "
                "scalar is missing) — cannot reproduce the verdict"
            ),
            chain_hash_live=live_hash,
            hash_matches=hash_matches,
            chain_validation_ok=cv_ok,
            **recorded,
        )

    # ── Step 5 — resolve. VERIFIED iff EVERY positive check passes. ──
    if hash_matches and cv_ok and tree_reproduces:
        return Provenance(
            render_status=RenderStatus.VERIFIED,
            status_reason=(
                "chain hash matches the recorded value, the audit chain "
                "satisfies all invariants, and the verdict reproduces from the "
                "recorded inputs"
            ),
            chain_hash_live=live_hash,
            hash_matches=True,
            chain_validation_ok=True,
            tree_reproduces=True,
            **recorded,
        )

    # Active failure → DRAFT_UNVERIFIED with the first-failing-check reason
    # (precedence chain → hash → tree).
    if not cv_ok:
        detail = cv.violations[0].description if cv.violations else "invariant violated"
        reason = f"audit chain validation failed: {detail}"
    elif not hash_matches:
        reason = (
            "recomputed chain hash does not match the value recorded in "
            "report.json — the sidecar is stale or has been edited"
        )
    else:  # not tree_reproduces
        reason = (
            "the verdict does not reproduce from the recorded inputs — the "
            "readout's verdict disagrees with the recorded decision-tree scalars"
        )
    return Provenance(
        render_status=RenderStatus.DRAFT_UNVERIFIED,
        status_reason=reason,
        chain_hash_live=live_hash,
        hash_matches=hash_matches,
        chain_validation_ok=cv_ok,
        tree_reproduces=tree_reproduces,
        **recorded,
    )


# ──────────────────────────────────────────────────────────────────────────
# Process-local cache — verification touches disk; render once, reuse.
# ──────────────────────────────────────────────────────────────────────────

class ProvenanceCache:
    """Memoize ``build_provenance`` by resolved experiment dir within one process.

    Rendering several formats of the same experiment in one CLI invocation must
    not re-hash the log per format. Keyed on the absolute ``exp_dir``; the
    report is assumed immutable for the life of the process (it is finalized
    once at Stage 8).
    """

    def __init__(self) -> None:
        self._cache: dict[str, Provenance] = {}

    def get(self, report: Report, exp_dir: Path) -> Provenance:
        key = str(Path(exp_dir).resolve())
        if key not in self._cache:
            self._cache[key] = build_provenance(report, exp_dir)
        return self._cache[key]

    def clear(self) -> None:
        self._cache.clear()


__all__ = [
    "RenderStatus",
    "Provenance",
    "build_provenance",
    "ProvenanceCache",
]
