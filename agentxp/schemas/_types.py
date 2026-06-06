"""Reusable annotated types for schema-wide constraints.

v0.1 cleanup W0.1 — `Sha256Hex` is the canonical type for any field that
stores a sha256 hex digest. Replaces ad-hoc ``str`` + per-field
``min_length=64, max_length=64`` constraints with a single pattern-validated
type that refuses any value that isn't exactly 64 lowercase hex characters.

Addresses audit B3: the SemanticModel schema accepted literal ``<pending>``
where a hash should be. With Sha256Hex applied repo-wide, placeholders fail at
validation time, not at audit time.

The accompanying closure test in tests/schemas/test_hash_field_closure.py
scans every Pydantic field name ending in ``_hash`` or ``_sha256`` and asserts
the type annotation resolves to Sha256Hex (or Optional[Sha256Hex]). Adding a
new hash-shaped field without using this type fails the closure test.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator, Field


def _enforce_utc(v: datetime) -> datetime:
    """Refuse naive datetimes and refuse aware-but-non-UTC datetimes.

    Centralised here (W1.1) so brief_seal, bundles, and any future
    timestamp field share one definition rather than duplicating the
    inline check brief_seal.py used to carry. Two failure modes:
    timezone-unaware (``v.tzinfo is None``) and aware-but-not-UTC
    (offset mismatch against ``timezone.utc``).
    """
    if v.tzinfo is None or v.tzinfo.utcoffset(v) != timezone.utc.utcoffset(v):
        raise ValueError("datetime must be timezone-aware UTC")
    return v


AwareUtcDatetime = Annotated[datetime, AfterValidator(_enforce_utc)]
"""Timezone-aware UTC datetime. Naive datetimes raise at validation.

Replaces the previous pattern of declaring ``captured_at: str`` and
manually re-parsing strings through ``datetime.fromisoformat`` at the
call site (DIAGNOSTIC §B.2 #4): pydantic accepts ``datetime`` instances
directly, ``yaml.safe_load`` emits them, and the validator catches naive
or off-UTC values before they reach domain code.
"""

Sha256Hex = Annotated[
    str,
    Field(
        pattern=r"^[a-f0-9]{64}$",
        min_length=64,
        max_length=64,
        description="A 64-character lowercase hex digest. Rejects placeholders.",
    ),
]
"""sha256 hex digest constrained to exactly 64 lowercase hex characters.

Usage:
    class SomeSchema(BaseModel):
        chain_hash: Sha256Hex
        prior_hash: Optional[Sha256Hex] = None
"""

__all__ = ["AwareUtcDatetime", "Sha256Hex"]
