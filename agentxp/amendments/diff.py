"""
Deep-diff for experiment.yaml dicts + material/administrative classification.

Algorithm: recursive path-walk over the union of keys at each level. Dicts
recurse key-by-key. Lists are compared index-by-index (with added/removed for
length delta); each differing index recurses if both sides are dicts, otherwise
reports a scalar change. This is intentionally simpler than a LCS/structural
diff — for experiment.yaml the "position" of a secondary metric is its
identity, and we want a stable, reviewable diff rather than the minimum edit
script.

Change record shape:
    {"path": "metrics.primary.name", "op": "changed", "before": X, "after": Y}
    {"path": "metrics.secondary[1]", "op": "added",   "before": None, "after": {...}}
    {"path": "power.duration_days", "op": "removed", "before": 14, "after": None}

Paths use dotted keys for dicts and [i] for list indices, mirroring JSON
pointer-ish notation but dot-separated for readability.
"""

from __future__ import annotations

from typing import Any

_SENTINEL = object()


def _is_mapping(x: Any) -> bool:
    return isinstance(x, dict)


def _is_sequence(x: Any) -> bool:
    # Bytes/str are not sequences for our purposes.
    return isinstance(x, (list, tuple))


def _join(parent: str, child: str) -> str:
    if not parent:
        return child
    if child.startswith("["):
        return f"{parent}{child}"
    return f"{parent}.{child}"


def _walk(before: Any, after: Any, path: str, out: list[dict]) -> None:
    # Both missing -> nothing (shouldn't happen from the public entrypoint).
    if before is _SENTINEL and after is _SENTINEL:
        return

    if before is _SENTINEL:
        out.append({"path": path, "op": "added", "before": None, "after": after})
        return

    if after is _SENTINEL:
        out.append({"path": path, "op": "removed", "before": before, "after": None})
        return

    # Both present.
    if _is_mapping(before) and _is_mapping(after):
        keys = sorted(set(before.keys()) | set(after.keys()))
        for k in keys:
            b = before.get(k, _SENTINEL) if k in before else _SENTINEL
            a = after.get(k, _SENTINEL) if k in after else _SENTINEL
            _walk(b, a, _join(path, str(k)), out)
        return

    if _is_sequence(before) and _is_sequence(after):
        n = max(len(before), len(after))
        for i in range(n):
            b = before[i] if i < len(before) else _SENTINEL
            a = after[i] if i < len(after) else _SENTINEL
            _walk(b, a, _join(path, f"[{i}]"), out)
        return

    # Scalar or type-mismatch case.
    if before != after:
        out.append(
            {"path": path, "op": "changed", "before": before, "after": after}
        )


def diff_experiments(before: dict, after: dict) -> list[dict]:
    """Deep-diff two experiment.yaml dicts.

    Returns a list of change records. Paths are dotted/indexed. Stable key
    ordering (sorted) so two equal diffs produce identical lists.
    """
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise TypeError(
            "diff_experiments requires dicts. "
            f"Got before={type(before).__name__}, after={type(after).__name__}."
        )
    out: list[dict] = []
    _walk(before, after, "", out)
    return out


# ---------------------------------------------------------------- classification

# Path prefixes (after stripping an optional leading "experiment.") that count
# as "material" changes — i.e., changes that can alter the decision math.
# These include metric definitions, success criteria, power parameters,
# decision rules, variants, and hypothesis direction.
_MATERIAL_PREFIXES: tuple[str, ...] = (
    "hypothesis",
    "metrics",
    "power",
    "decision_rules",
    "variants",
    "data",
)

# Leaf names that are administrative even when nested under a material tree.
# Note: we deliberately do NOT put "name" here — metric/variant renames are
# material (they change the identity of what we're measuring). Only the
# top-level experiment.name is admin, handled separately below.
_ADMIN_LEAVES: frozenset[str] = frozenset(
    {
        "description",
        "notes",
        "tags",
        "owner",
    }
)

# Top-level fields that are purely administrative metadata.
_ADMIN_PREFIXES: tuple[str, ...] = (
    "description",
    "notes",
    "tags",
    "owner",
    "timeline",  # pure bookkeeping dates
    "results",   # computed after analysis — not a pre-reg change
)


def _normalize_path(path: str) -> str:
    """Drop a leading 'experiment.' wrapper so classification works on
    either the nested-under-experiment or flat shape.
    """
    if path.startswith("experiment."):
        return path[len("experiment."):]
    return path


def _leaf_name(path: str) -> str:
    # Strip trailing [i] indices, then take the final dotted segment.
    p = path
    while p.endswith("]"):
        lb = p.rfind("[")
        if lb == -1:
            break
        p = p[:lb]
    return p.rsplit(".", 1)[-1] if "." in p else p


def classify_change(change: dict) -> str:
    """Return 'material' if the change affects decision math, else
    'administrative'.

    Material: metric defs, success criteria, power params, sample size,
              hypothesis direction, variant allocation, decision rules,
              data sources.
    Administrative: description, notes, tags, owner, timeline bookkeeping,
                    results (computed), human-readable name.
    """
    if not isinstance(change, dict) or "path" not in change:
        raise TypeError("classify_change requires a change dict with a 'path'.")

    path = _normalize_path(change["path"])
    if not path:
        return "administrative"

    # Top-level admin prefixes win first.
    head = path.split(".", 1)[0].split("[", 1)[0]
    if head in _ADMIN_PREFIXES:
        return "administrative"

    # Admin leaves even inside material trees.
    if _leaf_name(path) in _ADMIN_LEAVES:
        return "administrative"

    if head in _MATERIAL_PREFIXES:
        return "material"

    # Unknown top-level field (e.g., "id", "status") — treat as administrative.
    return "administrative"
