"""W2.3 — Purpose Literal ↔ matrix ↔ SqlIntent closure test.

Three sources of truth must agree:

  1. ``agentxp.sql.safety.Purpose`` Literal members
  2. ``agentxp.sql.safety._ROW_LIMIT_BY_PURPOSE`` dict keys
  3. ``agentxp.schemas.bundles.SqlIntent.purpose`` Literal members

Pre-W2.3 (2) and (3) carried disjoint enums and ``probe_data(purpose=...)``
calls would raise ResourceBoundsViolation when the SqlIntent purpose was
not also in the matrix (DIAGNOSTIC §B.3 #7). Post-W2.3 (1) is the
canonical Literal, (3) imports from it, and (2) keys match by definition.
"""
from __future__ import annotations

from typing import get_args

from agentxp.schemas.bundles import SqlIntent
from agentxp.sql.safety import Purpose, _ROW_LIMIT_BY_PURPOSE


def test_purpose_literal_matches_row_limit_keys() -> None:
    """Every Purpose value has a row-limit entry and vice versa."""
    literal_values = set(get_args(Purpose))
    matrix_keys = set(_ROW_LIMIT_BY_PURPOSE.keys())
    assert literal_values == matrix_keys, (
        f"Purpose Literal and _ROW_LIMIT_BY_PURPOSE drifted: "
        f"only-in-Literal={literal_values - matrix_keys}, "
        f"only-in-matrix={matrix_keys - literal_values}"
    )


def test_sql_intent_purpose_uses_canonical_literal() -> None:
    """SqlIntent.purpose is the canonical safety.Purpose."""
    annotation = SqlIntent.model_fields["purpose"].annotation
    # When Literal is imported by alias, the inner values still match.
    annotation_values = set(get_args(annotation))
    canonical_values = set(get_args(Purpose))
    assert annotation_values == canonical_values, (
        f"SqlIntent.purpose drifted from safety.Purpose: "
        f"only-in-SqlIntent={annotation_values - canonical_values}, "
        f"only-in-safety={canonical_values - annotation_values}"
    )


def test_sql_intent_accepts_every_canonical_purpose() -> None:
    """Smoke test — instantiating SqlIntent with each canonical purpose works."""
    for purpose in get_args(Purpose):
        si = SqlIntent(purpose=purpose, description="test")
        assert si.purpose == purpose
