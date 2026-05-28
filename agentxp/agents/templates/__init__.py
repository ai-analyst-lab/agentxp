"""Shared Jinja2 templates for AgentXP agents.

This package owns the visual format used by Stage-0/0.5/0.75 agents
(profiler, semantic_modeler, metric_drafter) when they show the user
"here's what I read in your data" before committing.

Public API:
    render_show_interpretation(ctx: dict) -> str
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).parent

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(disabled_extensions=("j2",)),
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_show_interpretation(ctx: dict[str, Any]) -> str:
    """Render the show-interpretation block.

    Pads columns to fixed widths before rendering. ``ctx`` is the dict
    described in the W_pre3.4 spec.
    """
    columns = _pad_columns(ctx.get("columns", []))
    ctx_padded = {**ctx, "columns": columns}
    template = _env.get_template("show_interpretation.j2")
    return template.render(**ctx_padded)


def _pad_columns(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Left-pad column fields to fixed widths for terminal alignment."""
    padded = []
    for col in columns:
        padded.append({
            **col,
            "name":     _pad(col["name"], 18),
            "type":     _pad(col["type"], 11),
            "null_pct": _pad(col.get("null_pct", "—"), 8),
            "sample":   _pad(col.get("sample", "—"), 22),
        })
    return padded


def _pad(s: str, n: int) -> str:
    """Pad or truncate ``s`` to exactly ``n`` characters.

    Truncation reserves the last character as a trailing space so adjacent
    columns don't visually run together.
    """
    if len(s) >= n:
        return s[: n - 1] + " "
    return s + " " * (n - len(s))


__all__ = ["render_show_interpretation"]
