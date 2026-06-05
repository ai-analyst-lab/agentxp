"""Readouts helpers — called by .claude/skills/readouts/SKILL.md.

Wraps the renders catalog primitives for the skill. Re-exports
``build_index`` from ``agentxp.render.catalog`` so the skill has a single
import point.

Public surface:
  - list_catalog(exp_dir) -> list[CatalogEntry]
  - build_index (re-exported from agentxp.render.catalog)
"""
from __future__ import annotations

from pathlib import Path

from agentxp.render.catalog import (  # re-export
    CatalogEntry,
    build_index,
)


def list_catalog(exp_dir: Path) -> list[CatalogEntry]:
    """Parse every entry in ``exp_dir/readouts/catalog.jsonl``.

    Returns the full list (eager). Empty / missing catalog returns ``[]``.
    The caller decides whether to print, filter, or validate the chain
    (``validate_catalog`` is in ``agentxp.render.catalog``).
    """
    catalog_path = Path(exp_dir) / "readouts" / "catalog.jsonl"
    if not catalog_path.exists():
        return []
    entries: list[CatalogEntry] = []
    with catalog_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(CatalogEntry.model_validate_json(line))
    return entries


__all__ = ["list_catalog", "build_index", "CatalogEntry"]
