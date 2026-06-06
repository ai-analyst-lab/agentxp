"""W1.5 — BundleBase envelope test.

Every specialist bundle inherits from BundleBase.
BundleBase carries ``prior_error: Optional[list[_PriorErrorEntry]]``.
_ENVELOPE_FIELDS names the metadata fields BLINDNESS_MANIFEST excludes
from forbidden-field traversal (CLAUDE.md §10 retry-on-malformed without
violating R5/R6/R10).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentxp.schemas.bundles import (
    AnalystNarratorBundle,
    BundleBase,
    CriticBundle,
    DesignerBundle,
    SqlSpecialistBundle,
    UnderstanderBundle,
    _ENVELOPE_FIELDS,
    _PriorErrorEntry,
)

ALL_BUNDLES = [
    UnderstanderBundle,
    DesignerBundle,
    CriticBundle,
    SqlSpecialistBundle,
    AnalystNarratorBundle,
]


@pytest.mark.parametrize("bundle_cls", ALL_BUNDLES)
def test_every_bundle_inherits_from_bundle_base(bundle_cls: type) -> None:
    assert issubclass(bundle_cls, BundleBase), (
        f"{bundle_cls.__name__} must inherit from BundleBase so prior_error "
        f"is available to complete_dispatch (W5.2)"
    )


@pytest.mark.parametrize("bundle_cls", ALL_BUNDLES)
def test_every_bundle_has_prior_error_field(bundle_cls: type) -> None:
    assert "prior_error" in bundle_cls.model_fields


def test_prior_error_default_none_on_first_dispatch() -> None:
    """First dispatch carries no retry context."""
    pe_field = BundleBase.model_fields["prior_error"]
    assert pe_field.default is None


def test_prior_error_entry_extra_forbid() -> None:
    """R10 — the orchestrator cannot sneak fields through the retry channel."""
    with pytest.raises(ValidationError):
        _PriorErrorEntry(loc="x", msg="y", type="z", extra="leak")  # type: ignore[call-arg]


def test_envelope_fields_names_prior_error() -> None:
    """BLINDNESS_MANIFEST excludes envelope metadata from walker."""
    assert "prior_error" in _ENVELOPE_FIELDS
    assert isinstance(_ENVELOPE_FIELDS, frozenset)


def test_bundle_base_extra_forbid() -> None:
    """R10 — the envelope itself does not accept extra fields."""
    with pytest.raises(ValidationError):
        BundleBase(prior_error=None, snuck_in="leak")  # type: ignore[call-arg]
