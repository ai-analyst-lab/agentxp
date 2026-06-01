"""Brand layer — single source of presentation styling for every renderer.

Wave 2 ships only the ANSI mirror: a tiny set of terminal escape codes plus an
``enabled``-aware ``style()`` helper. The glance adapter stays PLAIN TEXT (no
colour) by contract, so nothing here is applied to glance output yet; the module
exists from Wave 2 so the CSS-vars / SVG-palette / base64 ``@font-face`` surface
(W4-T2) extends ONE place instead of introducing a new module mid-stream.

No renderer hard-codes a hex value or an escape code: it asks the brand layer.
"""
from __future__ import annotations

# ── ANSI escape codes (the W2 mirror; W4 adds the full brand palette) ──
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"

# Status-tinted foregrounds. Kept conservative (the 8-colour set) so they read
# on any terminal theme; the editorial hex palette is a W4 concern.
GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
GREY = "\x1b[90m"


def style(text: str, *codes: str, enabled: bool = True) -> str:
    """Wrap ``text`` in the given ANSI codes, or return it bare when disabled.

    ``enabled`` is threaded from the CLI (``sys.stdout.isatty()`` and friends) so
    a piped/redirected stream never receives escape codes.
    """
    if not enabled or not codes:
        return text
    return f"{''.join(codes)}{text}{RESET}"


__all__ = ["RESET", "BOLD", "DIM", "GREEN", "RED", "YELLOW", "GREY", "style"]
