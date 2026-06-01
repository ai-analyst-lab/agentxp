"""Brand layer - the single source of presentation styling for every renderer.

No renderer hard-codes a hex value, a font stack, or an escape code: it asks the
brand layer, which resolves everything through the vendored
``agentxp/assets/design/brand.json`` (W4-T1). This is the enforcement point for
"no hex literal in any renderer".

Surface:
  - :func:`css_vars` - inlined ``:root{--xp-...}`` for the HTML/card/index tiers.
  - :func:`font_face_css` - deterministic base64 ``@font-face`` block over the
    vendored OFL ``.woff2`` files (offline, no CDN). Activates only for the files
    that are actually present, so the layer degrades to the fallback stack.
  - :func:`ansi` - the terminal escape map for glance (wraps the brand SGR codes).
  - :func:`svg_palette` - token-resolved hex for the deterministic SVG charts.
  - :func:`color` / :func:`theme` / :func:`fonts` - low-level accessors.

The W2 ANSI constants (``RESET`` etc. + :func:`style`) are retained for the
glance/CLI call sites that already import them.
"""
from __future__ import annotations

import base64
import functools
import json
from pathlib import Path
from typing import Optional

# ── ANSI escape codes (the W2 mirror; kept for existing call sites) ──
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
GREY = "\x1b[90m"


def style(text: str, *codes: str, enabled: bool = True) -> str:
    """Wrap ``text`` in the given ANSI codes, or return it bare when disabled."""
    if not enabled or not codes:
        return text
    return f"{''.join(codes)}{text}{RESET}"


# ── brand.json loading ──────────────────────────────────────────────────────

_DESIGN_DIR = Path(__file__).resolve().parent.parent / "assets" / "design"
_BRAND_PATH = _DESIGN_DIR / "brand.json"
_FONTS_DIR = _DESIGN_DIR / "fonts"


@functools.lru_cache(maxsize=1)
def _load() -> dict:
    """Load and cache ``brand.json`` once per process."""
    return json.loads(_BRAND_PATH.read_text(encoding="utf-8"))


def _theme_name(name: Optional[str]) -> str:
    brand = _load()
    return name or brand["default_theme"]


def theme(name: Optional[str] = None) -> dict[str, str]:
    """The colour map for a named theme (default: ``brand.json`` default_theme)."""
    brand = _load()
    return brand["themes"][_theme_name(name)]


def color(token: str, theme_name: Optional[str] = None) -> str:
    """Resolve one semantic colour token (e.g. ``"pass"``) to its hex value."""
    return theme(theme_name)[token]


def fonts() -> dict:
    """The ``fonts`` block from brand.json (family / file / weights / fallback)."""
    return _load()["fonts"]


# ── CSS variables ────────────────────────────────────────────────────────────

# Underscored brand keys (e.g. paper_raised) become hyphenated CSS custom
# properties (--xp-paper-raised). Keys starting with "_" are notes, never emitted.
def _var_name(key: str) -> str:
    return f"--xp-{key.replace('_', '-')}"


def css_vars(theme_name: Optional[str] = None) -> str:
    """Emit an inlined ``:root{ ... }`` block of ``--xp-*`` custom properties.

    Carries the theme's colours, the three font stacks (vendored family +
    fallback), and the type scale. Every component value in components.css
    resolves through one of these vars - the single enforcement point.
    """
    t = theme(theme_name)
    f = fonts()
    scale = _load()["type_scale"]

    decls: list[str] = []
    for key, value in t.items():
        if key.startswith("_"):
            continue
        decls.append(f"  {_var_name(key)}: {value};")
    for role in ("serif", "sans", "mono"):
        spec = f[role]
        stack = f"'{spec['family']}', {spec['fallback']}"
        decls.append(f"  --xp-font-{role}: {stack};")
    for key, value in scale.items():
        decls.append(f"  --xp-type-{key}: {value};")
    return ":root {\n" + "\n".join(decls) + "\n}"


# ── base64 @font-face ─────────────────────────────────────────────────────────

def font_face_css() -> str:
    """Build a deterministic, offline ``@font-face`` block over the vendored fonts.

    Each present ``.woff2`` is base64-embedded as a ``data:`` URL (no CDN, works
    offline). A family whose file is absent is SKIPPED - the renderer then falls
    back to that family's system stack (the fonts are a soft dependency at the
    layer level). Family order is fixed (serif, sans, mono) so the output is
    byte-stable for golden tests.
    """
    f = fonts()
    blocks: list[str] = []
    for role in ("serif", "sans", "mono"):
        spec = f[role]
        path = _FONTS_DIR / spec["file"]
        if not path.exists():
            continue
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        weights = spec["weights"]
        weight_decl = (
            f"{min(weights)} {max(weights)}" if len(weights) > 1 else str(weights[0])
        )
        blocks.append(
            "@font-face {\n"
            f"  font-family: '{spec['family']}';\n"
            "  font-style: normal;\n"
            f"  font-weight: {weight_decl};\n"
            "  font-display: swap;\n"
            f"  src: url(data:font/woff2;base64,{b64}) format('woff2');\n"
            "}"
        )
    return "\n".join(blocks)


# ── ANSI map (brand-driven) ────────────────────────────────────────────────────

def ansi() -> dict[str, str]:
    """Map of brand role -> full ANSI escape (ESC[<n>m) for the glance tier."""
    return {role: f"\x1b[{sgr}m" for role, sgr in _load()["ansi"].items()}


# ── SVG palette (token-resolved) ───────────────────────────────────────────────

def svg_palette(theme_name: Optional[str] = None) -> dict[str, str]:
    """Resolve the ``svg_palette`` role->token map to role->hex for the charts."""
    t = theme(theme_name)
    return {role: t[token] for role, token in _load()["svg_palette"].items()}


__all__ = [
    "RESET",
    "BOLD",
    "DIM",
    "GREEN",
    "RED",
    "YELLOW",
    "GREY",
    "style",
    "theme",
    "color",
    "fonts",
    "css_vars",
    "font_face_css",
    "ansi",
    "svg_palette",
]
