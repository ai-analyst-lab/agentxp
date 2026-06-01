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

from agentxp.render.provenance import Provenance, RenderStatus

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
        lines.append(f"- Chain hash (recorded): `{prov.chain_hash_stored}`")
    if prov.chain_hash_live and prov.chain_hash_live != prov.chain_hash_stored:
        lines.append(f"- Chain hash (recomputed): `{prov.chain_hash_live}`")
    if prov.locked_brief_hash:
        lines.append(f"- Locked-brief hash (recorded): `{prov.locked_brief_hash}`")
    if prov.agentxp_version:
        lines.append(f"- agentxp version: `{prov.agentxp_version}`")
    return "\n".join(lines)


__all__ = ["status_token", "chain_token", "replay_line", "footer_block"]
