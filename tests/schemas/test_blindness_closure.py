"""W1.9 — recursive BLINDNESS_MANIFEST closure test.

The legacy closure test at ``tests/orchestrator/test_bundle_assembler.py``
checks only top-level field names. That's enough to catch a literal
``DesignerBundle.lift: float`` addition, but it does NOT catch a future
change that wraps a forbidden field inside a sub-model — e.g. inlining a
``MetricResult`` (which carries ``ci_low``, ``ci_high``, ``p_value``) as
a nested submodel of ``DesignerBundle.results``. The top-level walker
sees only ``results``; the forbidden fields hide one level down.

W1.9 closes that gap. The walker:

  1. Iterates every bundle in ``BUNDLE_SCHEMAS``.
  2. For each field of each bundle, unwraps ``Annotated``, ``Optional``,
     ``list[T]``, ``dict[K, V]``, ``Union[A, B]``, ``tuple[A, ...]``.
  3. When the unwrapped type is itself a ``BaseModel`` subclass, recurses
     into its ``model_fields``.
  4. Excludes ``_ENVELOPE_FIELDS`` (W1.5 — prior_error is metadata, not
     domain content).
  5. Records every (field_name, owning_class) pair it visits.
  6. Asserts no forbidden field name from the role's manifest appears
     anywhere in the transitive walk.

The test bites at CI time when someone adds, removes, or restructures a
bundle in a way that lets a forbidden field through a nested path.
"""
from __future__ import annotations

from typing import Annotated, Any, Union, get_args, get_origin

import pytest
from pydantic import BaseModel

from agentxp.schemas.bundles import (
    BLINDNESS_MANIFEST,
    BUNDLE_SCHEMAS,
    _ENVELOPE_FIELDS,
)


def _unwrap(tp: Any) -> list[Any]:
    """Return the inner type(s) of a possibly-wrapped annotation.

    Handles: Annotated[X, ...], Optional[X], list[X], dict[K, V],
    Union[A, B], tuple[X, ...]. Returns a list because Union expands to
    multiple inner types.
    """
    origin = get_origin(tp)
    args = get_args(tp)

    if origin is Annotated:
        return [args[0]] if args else []
    if origin is Union:
        return [a for a in args if a is not type(None)]
    if origin in (list, set, frozenset, tuple):
        return [a for a in args if a is not Ellipsis]
    if origin is dict:
        return list(args)
    return [tp]


def _walk(
    cls: type[BaseModel],
    visited: set[type],
    out: list[tuple[type[BaseModel], str]],
) -> None:
    """Walk every field of cls and all transitively-referenced submodels."""
    if cls in visited:
        return
    visited.add(cls)
    for field_name, field_info in cls.model_fields.items():
        if field_name in _ENVELOPE_FIELDS:
            continue
        out.append((cls, field_name))
        for inner in _unwrap(field_info.annotation):
            try:
                if isinstance(inner, type) and issubclass(inner, BaseModel):
                    _walk(inner, visited, out)
            except TypeError:
                # not a class (e.g., a Literal value, a typing form)
                continue


@pytest.mark.parametrize("role,forbidden", list(BLINDNESS_MANIFEST.items()))
def test_no_forbidden_field_in_transitive_walk(role: str, forbidden: list[str]) -> None:
    """No forbidden field appears at any depth of the bundle's field tree."""
    bundle_cls = BUNDLE_SCHEMAS[role]
    visited: set[type] = set()
    visited_fields: list[tuple[type[BaseModel], str]] = []
    _walk(bundle_cls, visited, visited_fields)

    violations = [
        (owner.__name__, name)
        for owner, name in visited_fields
        if name in forbidden
    ]
    assert not violations, (
        f"{role} bundle exposes forbidden field(s) through a nested submodel: "
        f"{violations}. See CLAUDE.md R5/R6/R10 and BLINDNESS_MANIFEST."
    )


def test_envelope_fields_excluded_from_walker() -> None:
    """W1.5 prior_error is metadata; it must be visited only as an envelope skip."""
    bundle_cls = BUNDLE_SCHEMAS["designer"]
    visited: set[type] = set()
    visited_fields: list[tuple[type[BaseModel], str]] = []
    _walk(bundle_cls, visited, visited_fields)

    visited_names = {name for _, name in visited_fields}
    assert "prior_error" not in visited_names, (
        "prior_error was visited; the walker must skip _ENVELOPE_FIELDS"
    )


def test_walker_finds_nested_field_when_one_exists() -> None:
    """Self-test: if we injected a forbidden field as a nested submodel,
    would the walker catch it? Constructs a synthetic bundle to verify."""
    from pydantic import BaseModel, ConfigDict

    class _LiftHolder(BaseModel):
        model_config = ConfigDict(extra="forbid")
        lift: float  # listed in designer's BLINDNESS_MANIFEST

    class _SyntheticDesignerBundle(BaseModel):
        model_config = ConfigDict(extra="forbid")
        intent: str
        results: list[_LiftHolder]  # forbidden field nested one level deep

    visited: set[type] = set()
    visited_fields: list[tuple[type[BaseModel], str]] = []
    _walk(_SyntheticDesignerBundle, visited, visited_fields)

    visited_names = {name for _, name in visited_fields}
    assert "lift" in visited_names, (
        "Walker self-test failed: nested 'lift' was not visited; "
        "the recursive descent is broken."
    )
