"""Adapter registry — ``ADAPTERS`` maps a format id to its adapter instance.

The registry mirrors the CLI ``report`` subcommand's ``--format`` choices. A
deferred format (glance/html/card/png/…) is registered as it lands in its wave;
the CLI consults ``ADAPTERS`` to fail fast on an unknown or not-yet-built format
rather than importing a heavy/absent dependency.
"""
from __future__ import annotations

from agentxp.render.adapters.base import FormatAdapter
from agentxp.render.adapters.markdown import MarkdownAdapter

# Format id → adapter instance. Wave 1 ships markdown; later waves register
# glance (W2), html (W4), card (W5), and the heavy png/pdf extras.
ADAPTERS: dict[str, FormatAdapter] = {
    MarkdownAdapter.format_id: MarkdownAdapter(),
}


def get_adapter(format_id: str) -> FormatAdapter:
    """Return the registered adapter for ``format_id`` or raise ``KeyError``."""
    return ADAPTERS[format_id]


__all__ = ["ADAPTERS", "FormatAdapter", "MarkdownAdapter", "get_adapter"]
