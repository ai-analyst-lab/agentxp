"""Closure test for ReadoutKind. Asserts EXACTLY 5 values, in canonical form.

Mirrors tests/audit/test_event_enum_closure.py — this is the dedicated closure
target for the five-value share-out spine vocabulary. If anyone adds, removes,
or renames a readout kind, this test fails first and loudly.
"""
from __future__ import annotations

from agentxp.render.readout_kind import ReadoutKind


def test_readout_kind_has_exactly_5_values() -> None:
    """The closed share-out vocabulary is five values, not four, not six."""
    assert len(ReadoutKind) == 5, f"Expected 5 readout kinds, got {len(ReadoutKind)}"


def test_readout_kind_values_are_canonical() -> None:
    """Each canonical lowercase name must be present."""
    expected = {
        "intent",
        "design_brief",
        "monitor_check",
        "verdict",
        "audit",
    }
    actual = {k.value for k in ReadoutKind}
    assert actual == expected, (
        f"ReadoutKind values mismatch: missing={expected - actual}, extra={actual - expected}"
    )


def test_readout_kind_symbols_match_uppercase_canonical_form() -> None:
    """Each enum member's symbol is the uppercased canonical name."""
    for k in ReadoutKind:
        assert k.name == k.value.upper(), (
            f"ReadoutKind.{k.name}.value={k.value!r} but symbol should be {k.value.upper()!r}"
        )


def test_readout_kind_values_lowercase_underscore_form() -> None:
    """All canonical values use lowercase + underscores (no dots, no hyphens)."""
    for k in ReadoutKind:
        assert k.value.islower(), f"{k.value!r} should be lowercase"
        assert "." not in k.value, f"{k.value!r} should not contain dots"
        assert "-" not in k.value, f"{k.value!r} should not contain hyphens"
