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

from typing import Annotated

from pydantic import Field

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

__all__ = ["Sha256Hex"]
