"""Adapter Protocol — a format is a pure renderer over a :class:`ViewBundle`.

Adding an output format = adding one adapter that consumes the bundle. An
adapter NEVER re-derives a number (it reads preformatted strings off the VM)
and NEVER decides verification status (it reads the bundled provenance). The
``binary`` / ``requires_node`` flags exist from day one so the CLI can fail
fast on a deferred/heavy format without importing its (possibly absent) deps.
"""
from __future__ import annotations

from typing import Protocol, Union, runtime_checkable

from agentxp.render.viewmodel import ViewBundle


@runtime_checkable
class FormatAdapter(Protocol):
    """One output format. Implementations are stateless and side-effect-free."""

    #: stable short id, e.g. "md", "glance", "html", "card"
    format_id: str
    #: True when ``render`` returns bytes (PNG/PDF); False for text (md/html).
    binary: bool
    #: True when the format needs an external engine (e.g. a browser) to render.
    requires_node: bool

    def render(self, bundle: ViewBundle) -> Union[str, bytes]:
        """Render the bundle to its output payload. Pure; no disk writes."""
        ...

    def default_filename(self, bundle: ViewBundle) -> str:
        """Suggested output filename, e.g. ``exp_001.report.md``."""
        ...


__all__ = ["FormatAdapter"]
