"""Markdown adapter — the reference renderer over a :class:`ViewBundle`.

Thin wrapper over the existing §21 markdown renderer (``render/report.py``),
now driven by ``distill(report.json)`` instead of a hand-built agent model. It
appends the provenance footer so the rendered ``report.md`` carries its replay
receipts inseparably (the receipts are part of the document, not an addendum a
reader can drop).
"""
from __future__ import annotations

from agentxp.render.receipts import footer_block
from agentxp.render.report import render_report
from agentxp.render.viewmodel import ViewBundle


class MarkdownAdapter:
    """Render a ViewBundle to verdict-first markdown (``report.md``)."""

    format_id = "md"
    binary = False
    requires_node = False

    def render(self, bundle: ViewBundle) -> str:
        body = render_report(bundle.vm)
        footer = footer_block(bundle.provenance)
        # render_report keeps a trailing newline; separate body and footer with
        # a blank line so the provenance block reads as its own section.
        return f"{body}\n{footer}\n"

    def default_filename(self, bundle: ViewBundle) -> str:
        return f"{bundle.vm.experiment_id}.report.md"


__all__ = ["MarkdownAdapter"]
