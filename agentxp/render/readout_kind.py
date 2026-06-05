"""ReadoutKind — the closed five-value vocabulary for the share-out spine.

The presentation layer renders five distinct readout kinds. Each has its own
ViewModel, its own ``distill_*`` projection, its own ``build_provenance``
precedence chain, and its own template/adapter. The set is closed; adding a
new kind requires updating the closure test below and is a deliberate
schema-version event.

This file is the dedicated closure target for the five-value vocabulary (the
sibling discipline to EventName-at-13 in ``agentxp/audit/events.py``).
"""
from __future__ import annotations

from enum import Enum


class ReadoutKind(str, Enum):
    """The five readout types of the share-out spine."""

    INTENT = "intent"
    """Stage 1 — captured user intent. Text-only readout (no data yet)."""

    DESIGN_BRIEF = "design_brief"
    """Stage 3+4 — locked brief with power analysis, allocation, decision rules."""

    MONITOR_CHECK = "monitor_check"
    """Stage 5 — halt readout. Peek-safe by schema (no lift/CI/p-value fields)."""

    VERDICT = "verdict"
    """Stage 8 — the verdict + analysis readout. The canonical share-out."""

    AUDIT = "audit"
    """Cross-stage — the full audit-trail render (chain inspection)."""


__all__ = ["ReadoutKind"]
