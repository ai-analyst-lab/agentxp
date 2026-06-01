"""Raster adapters — PNG / PDF, the only adapters that need an external engine.

These do NOT render anything new: they rasterize the self-contained pages the
``html`` and ``card`` adapters already produce, using a pinned headless Chromium
(the optional ``agentxp[png]`` extra). PNG screenshots the fixed-frame social
``card``; PDF prints the exec ``html`` one-pager. Because the source pages are
fully self-contained (inlined CSS, base64 fonts, inline SVG, no CDN), the
rasterizer feeds Chromium a single string and never touches the network.

playwright is imported lazily — the module imports fine without the extra so the
CLI can probe :func:`is_available` and fail fast with the extra's name rather
than an opaque ImportError. ``binary`` is True (the payload is bytes, so the CLI
requires ``--out``); ``requires_node`` flags the external-engine dependency.
"""
from __future__ import annotations

from typing import Optional

from agentxp.render.adapters.card import CardAdapter
from agentxp.render.adapters.html import HtmlAdapter
from agentxp.render.viewmodel import ViewBundle

_RASTER_FORMATS = ("png", "pdf")


def is_available() -> bool:
    """True when the ``agentxp[png]`` extra (playwright) is importable.

    Does not verify the Chromium binary is installed — that surfaces as a clear
    playwright error at render time (the install hint names both steps).
    """
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def _rasterize(html: str, *, mode: str, viewport: Optional[dict] = None) -> bytes:
    """Drive headless Chromium over a self-contained HTML string → PNG/PDF bytes.

    A fresh browser per call keeps the adapter stateless and side-effect-free
    (no shared engine to leak between renders). ``wait_until="networkidle"`` is
    safe and fast because the page makes no requests — everything is inlined.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport=viewport) if viewport else browser.new_page()
            page.set_content(html, wait_until="networkidle")
            if mode == "png":
                return page.screenshot(full_page=True, type="png")
            return page.pdf(print_background=True)
        finally:
            browser.close()


class PngAdapter:
    """Rasterize the fixed-frame social ``card`` to a PNG."""

    format_id = "png"
    binary = True
    requires_node = True  # needs an external browser engine (Chromium)

    def __init__(self, theme: str = "editorial-light"):
        self._source = CardAdapter(theme=theme)

    def render(self, bundle: ViewBundle) -> bytes:
        html = self._source.render(bundle)
        # The card is a pixel-locked 1200×1500 frame; match the viewport so the
        # screenshot is the card, not the card centred in a default window.
        return _rasterize(
            html, mode="png", viewport={"width": 1200, "height": 1500}
        )

    def default_filename(self, bundle: ViewBundle) -> str:
        return f"{bundle.vm.experiment_id}.card.png"


class PdfAdapter:
    """Print the exec ``html`` one-pager to a PDF."""

    format_id = "pdf"
    binary = True
    requires_node = True

    def __init__(self, theme: str = "editorial-light", audience: str = "exec"):
        self._source = HtmlAdapter(theme=theme, audience=audience)

    def render(self, bundle: ViewBundle) -> bytes:
        html = self._source.render(bundle)
        return _rasterize(html, mode="pdf")

    def default_filename(self, bundle: ViewBundle) -> str:
        return f"{bundle.vm.experiment_id}.report.pdf"


def build_adapter(
    fmt: str, *, theme: str = "editorial-light", audience: Optional[str] = None
):
    """Construct the raster adapter for ``png`` / ``pdf`` with CLI config threaded."""
    if fmt == "png":
        return PngAdapter(theme=theme)
    if fmt == "pdf":
        return PdfAdapter(
            theme=theme, audience=audience if audience == "skeptic" else "exec"
        )
    raise KeyError(fmt)


__all__ = [
    "PngAdapter",
    "PdfAdapter",
    "build_adapter",
    "is_available",
]
