"""Closure test — every Pydantic field named ``*_hash`` or ``*_sha256`` uses Sha256Hex.

v0.1 cleanup W0.1 — adding a new hash-shaped field anywhere in
``agentxp/schemas/`` or ``agentxp/audit/events.py`` without using
``Sha256Hex`` (or ``Optional[Sha256Hex]``) fails this closure test.

Scans the loaded Pydantic models reflectively; doesn't rely on AST parsing,
which means future model files Just Work as long as they import their models
into the modules we walk.
"""
from __future__ import annotations

import importlib
import inspect
from typing import Annotated, get_args, get_origin, Union

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from agentxp.schemas._types import Sha256Hex


# Modules to scan. Add new schema modules here as the codebase grows; the
# closure check applies to every BaseModel found.
_MODULES_TO_SCAN = [
    "agentxp.schemas.data_plan",
    "agentxp.schemas.profiler",
    "agentxp.schemas.report",
    "agentxp.schemas.state",
    "agentxp.schemas.experiment",
    "agentxp.schemas.results",
    "agentxp.audit.events",
]


def _is_hash_named(field_name: str) -> bool:
    """The naming convention: anything ending in _hash or _sha256."""
    return field_name.endswith("_hash") or field_name.endswith("_sha256")


_SHA256_PATTERN = r"^[a-f0-9]{64}$"


def _metadata_has_sha256_pattern(metadata) -> bool:
    """True iff the metadata list contains an entry with our sha256 pattern."""
    for entry in metadata or []:
        pattern = getattr(entry, "pattern", None)
        if pattern == _SHA256_PATTERN:
            return True
    return False


def _annotation_carries_sha256_pattern(annotation) -> bool:
    """Recursively check whether an annotation (Optional[X], Annotated[X, ...], etc.)
    carries the Sha256Hex pattern constraint somewhere inside.
    """
    # Direct Annotated[T, FieldInfo(...)] / Annotated[T, ...]
    origin = get_origin(annotation)
    if origin is Annotated:
        # First arg is the underlying type; the rest are metadata
        meta = get_args(annotation)[1:]
        for m in meta:
            # FieldInfo objects (Pydantic) carry .metadata; other constraint
            # objects may carry .pattern directly.
            if _metadata_has_sha256_pattern(getattr(m, "metadata", None)):
                return True
            if getattr(m, "pattern", None) == _SHA256_PATTERN:
                return True
        return False
    # Optional[X] / Union[X, None] — recurse into each non-None branch
    if origin is Union:
        return any(
            _annotation_carries_sha256_pattern(a)
            for a in get_args(annotation)
            if a is not type(None)
        )
    return False


def _field_carries_sha256_pattern(field_info: FieldInfo) -> bool:
    """True iff the field's FieldInfo metadata or annotation carries the pattern.

    Pydantic stores the constraint differently depending on whether the field
    is ``Sha256Hex`` directly or ``Optional[Sha256Hex]``. We check both.
    """
    if _metadata_has_sha256_pattern(getattr(field_info, "metadata", None)):
        return True
    return _annotation_carries_sha256_pattern(field_info.annotation)


def _walk_pydantic_models():
    """Yield (module_name, class_name, field_name, FieldInfo) for every Pydantic field."""
    for mod_name in _MODULES_TO_SCAN:
        mod = importlib.import_module(mod_name)
        for class_name, cls in inspect.getmembers(mod, inspect.isclass):
            if not issubclass(cls, BaseModel) or cls is BaseModel:
                continue
            if cls.__module__ != mod_name:
                # Re-exports — skip; the canonical module catches it.
                continue
            for field_name, field_info in cls.model_fields.items():
                yield (mod_name, class_name, field_name, field_info)


def test_every_hash_named_field_uses_sha256hex() -> None:
    """Every field whose name ends in _hash or _sha256 must carry Sha256Hex's pattern."""
    violations: list[str] = []
    for mod_name, class_name, field_name, field_info in _walk_pydantic_models():
        if not _is_hash_named(field_name):
            continue
        if not _field_carries_sha256_pattern(field_info):
            violations.append(
                f"{mod_name}::{class_name}.{field_name}: "
                f"missing Sha256Hex pattern constraint (annotation: {field_info.annotation!r})"
            )
    assert not violations, (
        "Hash-named fields must use Sha256Hex (or Optional[Sha256Hex]).\n"
        "Offenders:\n  " + "\n  ".join(violations)
    )
