"""Render-time helpers for AgentXP.

Includes the voice audit (D5 / NDS-3 / M67) that runs at render time and
emits stderr warnings without blocking. See voice_audit.py.

Also exposes the verdict-first experiment-report renderer (§21). See report.py.

The presentation layer (§ presentation master plan) is a pure-renderer spine:
``report.json -> distill() -> ReportVM -> adapters``, with provenance built
separately (it does I/O) and bundled into a :class:`ViewBundle`. ``distill`` is
the single place numbers are formatted; adapters never re-derive a value.
"""
from __future__ import annotations

from agentxp.render.distill import distill
from agentxp.render.provenance import (
    Provenance,
    ProvenanceCache,
    RenderStatus,
    build_provenance,
)
from agentxp.render.report import render_report, write_report
from agentxp.render.viewmodel import ReportVM, ViewBundle

__all__ = [
    "distill",
    "render_report",
    "write_report",
    "build_provenance",
    "Provenance",
    "ProvenanceCache",
    "RenderStatus",
    "ReportVM",
    "ViewBundle",
]
