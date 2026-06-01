"""Adapter registry — ``ADAPTERS`` maps a format id to its adapter instance.

The registry mirrors the CLI ``report`` subcommand's ``--format`` choices. A
deferred format (glance/html/card/png/…) is registered as it lands in its wave;
the CLI consults ``ADAPTERS`` to fail fast on an unknown or not-yet-built format
rather than importing a heavy/absent dependency.
"""
from __future__ import annotations

from agentxp.render.adapters.base import FormatAdapter
from agentxp.render.adapters.card import CardAdapter
from agentxp.render.adapters.data import CsvAdapter, JsonAdapter
from agentxp.render.adapters.glance import GlanceAdapter
from agentxp.render.adapters.html import HtmlAdapter
from agentxp.render.adapters.markdown import MarkdownAdapter

# Format id → adapter instance. Wave 1 ships markdown; Wave 2 adds glance; Wave 4
# adds html; Wave 5 adds card; Wave 8 adds the pure data exports (json/csv); the
# heavy png/pdf extras land later. The html and card instances here are the
# defaults (editorial-light); the CLI builds a configured instance when
# --theme/--audience are passed.
ADAPTERS: dict[str, FormatAdapter] = {
    MarkdownAdapter.format_id: MarkdownAdapter(),
    GlanceAdapter.format_id: GlanceAdapter(),
    HtmlAdapter.format_id: HtmlAdapter(),
    CardAdapter.format_id: CardAdapter(),
    JsonAdapter.format_id: JsonAdapter(),
    CsvAdapter.format_id: CsvAdapter(),
}


def get_adapter(format_id: str) -> FormatAdapter:
    """Return the registered adapter for ``format_id`` or raise ``KeyError``."""
    return ADAPTERS[format_id]


__all__ = [
    "ADAPTERS",
    "FormatAdapter",
    "MarkdownAdapter",
    "GlanceAdapter",
    "HtmlAdapter",
    "CardAdapter",
    "JsonAdapter",
    "CsvAdapter",
    "get_adapter",
]
