"""Closure test for the Verdict Literal. Asserts EXACTLY 9 values, canonical form.

Sibling to tests/audit/test_event_enum_closure.py — this is the dedicated
closure target for the §1.8.17 verdict vocabulary (8 -> 9 in v0.1 W0.11 with
UNVERIFIABLE for null-input tree paths). If anyone adds, removes, or renames
a verdict, this test fails first and loudly.
"""
from __future__ import annotations

from typing import get_args

from agentxp.interpret.tree import Verdict


def test_verdict_has_exactly_9_values() -> None:
    """§1.8.17 (extended W0.11): Verdict is a closed set at exactly 9 values."""
    values = get_args(Verdict)
    assert len(values) == 9, f"Expected 9 verdicts, got {len(values)}: {values}"


def test_verdict_values_are_canonical() -> None:
    """The canonical labels for each verdict-tree branch + UNVERIFIABLE."""
    expected = {
        "INVALID-SRM",
        "NO-SHIP-GUARDRAIL",
        "INCONCLUSIVE",
        "NO-LIFT",
        "DIRECTIONAL-ONLY",
        "LIFT-WITH-CAVEAT",
        "SHIP",
        "LEARN",
        "UNVERIFIABLE",
    }
    actual = set(get_args(Verdict))
    assert actual == expected, (
        f"Verdict values mismatch: missing={expected - actual}, extra={actual - expected}"
    )


def test_verdict_values_uppercase_hyphenated_form() -> None:
    """Verdict labels are SCREAMING-KEBAB-CASE (uppercase, hyphen-separated)."""
    for value in get_args(Verdict):
        assert value.isupper(), f"{value!r} should be uppercase"
        assert "_" not in value, f"{value!r} should not contain underscores (use hyphens)"
        assert " " not in value, f"{value!r} should not contain spaces"


def test_unverifiable_present_for_null_input_handling() -> None:
    """W0.11 — UNVERIFIABLE is the v0.1 addition for the null-input verdict path.

    Per audit B5: the tree previously silently passed when an input was null
    (e.g., null late_ratio → SHIP-default). UNVERIFIABLE is the explicit refusal.
    Wired in W1.6.
    """
    assert "UNVERIFIABLE" in get_args(Verdict)
