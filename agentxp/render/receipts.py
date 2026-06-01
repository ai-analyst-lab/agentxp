"""Human-readable authenticity receipts rendered from a :class:`Provenance`.

These strings are the inseparable companion to every rendered number: the
replay command, the chain-hash token, and the verification badge. They are
plain text here (format-agnostic); a given adapter may style them (ANSI for
glance, a footer block for markdown, a badge for HTML) but never invents or
omits them.

Token vocabulary (honest from day one — no "verified" off a stored hash alone):
  - ``verified``      — full live flow passed (W3 only)
  - ``MISMATCH``      — recomputed hash != stored hash (active failure)
  - ``unverifiable``  — can't check (v1 / missing hash / not-yet-run)
"""
from __future__ import annotations

from typing import Optional

from agentxp.interpret.tree import GuardrailEval, TreeInput, walk_tree
from agentxp.render.provenance import Provenance, RenderStatus
from agentxp.schemas.report import Report

#: How many leading hex chars of a chain hash to SHOW a human (W3-T5). The full
#: 64-char hash is always embedded alongside; the short form is never the sole
#: anchor — it is a readable handle, not the verifiable record.
CHAIN_HASH_SHORT_LEN = 12

_STATUS_TOKEN = {
    RenderStatus.VERIFIED: "verified",
    RenderStatus.DRAFT_UNVERIFIED: "MISMATCH",
    RenderStatus.UNVERIFIABLE: "unverifiable",
}


def status_token(prov: Provenance) -> str:
    """The one-word token for the resolved render status (verified/MISMATCH/unverifiable)."""
    return _STATUS_TOKEN[prov.render_status]


def chain_token(prov: Provenance) -> str:
    """The honest one-word CHAIN token for the receipt line: OK / MISMATCH / unverifiable.

    Derived from the minimal live check (``hash_matches``), NOT from the render
    status — so a matching hash reads ``OK`` even while the full VERIFIED badge
    is still gated on W3's validate_chain + tree reproduction. This keeps the
    receipt honest: ``OK`` means "the recomputed chain hash matches the recorded
    one", never "verified".
    """
    if prov.hash_matches is True:
        return "OK"
    if prov.hash_matches is False:
        return "MISMATCH"
    return "unverifiable"


def chain_hash_short(full: Optional[str]) -> Optional[str]:
    """First :data:`CHAIN_HASH_SHORT_LEN` chars of a 64-char chain hash, or None.

    A readable handle for display. The full hash is always embedded alongside
    (W3-T5) — the short form is never the sole anchor of a provenance claim.
    """
    if not full:
        return None
    return full[:CHAIN_HASH_SHORT_LEN]


# ──────────────────────────────────────────────────────────────────────────
# Verdict-tree reproduction (W3-T2) — defends against a doctored sidecar.
# ──────────────────────────────────────────────────────────────────────────

def _reproduce_verdict(report: Report) -> Optional[bool]:
    """Re-run the 8-step decision tree from the report's persisted scalars.

    Rebuilds a :class:`TreeInput` from the verifiable fields the core finalizer
    authored (the 7 W0 tree-reproduction scalars + the primary CIs + per-guardrail
    ``direction``), re-runs :func:`walk_tree`, and returns whether the re-run
    ``(verdict, terminal_step)`` matches ``(report.verdict, report.step_fired)``.

    Comparison is enum+int — NEVER a parse of the unstable ``step_fired`` trail
    strings. ``Report.verdict`` is the TREE verdict; a human NO-SHIP sign-off
    lives in ``override_justification`` and never overwrites it, so a legitimate
    override still reproduces.

    Returns:
        ``True``  — the verdict reproduces (verdict AND terminal step match).
        ``False`` — an active contradiction (the readout disagrees with the
                    tree the recorded inputs produce).
        ``None``  — the inputs are incomplete (a required scalar or a guardrail
                    ``direction`` is absent), so reproduction CANNOT be attempted
                    — the caller resolves this to UNVERIFIABLE, never DRAFT.
    """
    required = (
        report.srm_override_resolved,
        report.n_observed,
        report.n_required,
        report.primary_direction,
        report.mde_pct,
        report.baseline,
    )
    if any(v is None for v in required):
        return None

    guardrails: list[GuardrailEval] = []
    for g in report.guardrails:
        if g.direction not in ("higher_is_better", "lower_is_better"):
            # The tree's harm-side selection needs a concrete direction; without
            # it we cannot reproduce — treat as can't-check, not a contradiction.
            return None
        guardrails.append(
            GuardrailEval(
                metric_name=g.name,
                direction=g.direction,
                ci_lower_90=g.ci_90_lower,
                ci_upper_90=g.ci_90_upper,
            )
        )

    inputs = TreeInput(
        srm_pass=report.diagnostics.srm_passed,
        guardrails=guardrails,
        n_observed=report.n_observed,  # type: ignore[arg-type]
        n_required=report.n_required,  # type: ignore[arg-type]
        primary_ci_lower_95=report.primary.ci_95_lower,
        primary_ci_upper_95=report.primary.ci_95_upper,
        primary_ci_lower_90=report.primary.ci_90_lower,
        primary_ci_upper_90=report.primary.ci_90_upper,
        primary_lift_magnitude=report.primary.lift_absolute,
        primary_direction=report.primary_direction,  # type: ignore[arg-type]
        mde_pct=report.mde_pct,  # type: ignore[arg-type]
        baseline=report.baseline,  # type: ignore[arg-type]
        srm_override_resolved=bool(report.srm_override_resolved),
        late_ratio=report.late_ratio,
    )
    result = walk_tree(inputs)
    return (result.verdict, result.terminal_step) == (report.verdict, report.step_fired)


def replay_line(prov: Provenance) -> str:
    """One-line receipt: replay command + chain token. Used by glance and footers.

    Example: ``agentxp audit exp_001  ·  chain OK``
    """
    return f"{prov.replay_command}  ·  chain {chain_token(prov)}"


def footer_block(prov: Provenance) -> str:
    """Multi-line replay footer for the markdown / HTML readouts.

    Carries the recorded receipts (chain hash, locked-brief hash, version) and
    the resolved status with its reason, so the footer is a complete,
    uncroppable provenance record.
    """
    lines = [
        "## Provenance",
        "",
        f"- Replay: `{prov.replay_command}`",
        f"- Chain: {chain_token(prov)}",
        f"- Verification: **{prov.render_status.value}** — {prov.status_reason}",
    ]
    if prov.chain_hash_stored:
        # Display short for readability; embed full so it stays the verifiable
        # anchor (W3-T5 — short hash is never the sole anchor).
        lines.append(
            f"- Chain hash (recorded): `{chain_hash_short(prov.chain_hash_stored)}…` "
            f"(full: `{prov.chain_hash_stored}`)"
        )
    if prov.chain_hash_live and prov.chain_hash_live != prov.chain_hash_stored:
        lines.append(
            f"- Chain hash (recomputed): `{chain_hash_short(prov.chain_hash_live)}…` "
            f"(full: `{prov.chain_hash_live}`)"
        )
    if prov.locked_brief_hash:
        lines.append(f"- Locked-brief hash (recorded): `{prov.locked_brief_hash}`")
    if prov.agentxp_version:
        lines.append(f"- agentxp version: `{prov.agentxp_version}`")
    return "\n".join(lines)


__all__ = [
    "status_token",
    "chain_token",
    "chain_hash_short",
    "_reproduce_verdict",
    "replay_line",
    "footer_block",
    "CHAIN_HASH_SHORT_LEN",
]
