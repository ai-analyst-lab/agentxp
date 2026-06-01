"""Markdown adapter — the reference renderer over a :class:`ViewBundle`.

Thin wrapper over the existing §21 markdown renderer (``render/report.py``),
now driven by ``distill(report.json)`` instead of a hand-built agent model. It
appends the provenance footer so the rendered ``report.md`` carries its replay
receipts inseparably (the receipts are part of the document, not an addendum a
reader can drop).
"""
from __future__ import annotations

from agentxp.render.provenance import RenderStatus
from agentxp.render.receipts import footer_block
from agentxp.render.report import render_report
from agentxp.render.viewmodel import ViewBundle


class MarkdownAdapter:
    """Render a ViewBundle to verdict-first markdown (``report.md``)."""

    format_id = "md"
    binary = False
    requires_node = False

    def render(self, bundle: ViewBundle) -> str:
        prov = bundle.provenance
        body = render_report(bundle.vm)
        footer = footer_block(prov)
        # W3-T4: an ACTIVE failure stamps a top admonition (so a reader can't
        # miss it above the verdict) and a blunt footer line. UNVERIFIABLE stays
        # calm — no admonition, the footer reason carries the neutral note.
        if prov.render_status is RenderStatus.DRAFT_UNVERIFIED:
            admonition = (
                f"> ⚠ **DRAFT — UNVERIFIED.** {prov.status_reason}\n"
            )
            footer = f"{footer}\n- chain integrity: FAILED — {prov.status_reason}"
            # render_report keeps a trailing newline; separate the sections with
            # blank lines so each reads as its own block.
            return f"{admonition}\n{body}\n{footer}\n"
        return f"{body}\n{footer}\n"

    def default_filename(self, bundle: ViewBundle) -> str:
        return f"{bundle.vm.experiment_id}.report.md"


__all__ = ["MarkdownAdapter"]
