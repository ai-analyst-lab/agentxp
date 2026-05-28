"""Closure test for the EventName enum. Asserts EXACTLY 13 values, in canonical form.

Companion to tests/coherence/test_canonical_names.py — this file is the dedicated
closure target for §1.8.3 / §9 (the 13-event vocabulary). If anyone adds, removes,
or renames an event, this test fails first and loudly.
"""
from __future__ import annotations

from openxp.audit.events import EventName, V01_RESERVED_EVENTS


def test_event_enum_has_exactly_13_values() -> None:
    """§9: EventName is a closed enum at exactly 13 values."""
    assert len(EventName) == 13, f"Expected 13 events, got {len(EventName)}"


def test_event_enum_values_are_canonical() -> None:
    """§1.8.3: each canonical dotted name must be present."""
    expected = {
        "stage.entered",
        "stage.committed",
        "gate.opened",
        "gate.resolved",
        "gate.blocked",
        "agent.dispatched",
        "agent.completed",
        "query.proposed",
        "query.validated",
        "query.executed",
        "query.failed",
        "hook.invoked",
        "hook.failed",
    }
    actual = {e.value for e in EventName}
    assert actual == expected, f"EventName values mismatch: missing={expected - actual}, extra={actual - expected}"


def test_reserved_v01_events_documented() -> None:
    """§22.5 / D2: hook.invoked + hook.failed are reserved in v0.1, emitted starting v0.2."""
    assert EventName.HOOK_INVOKED in V01_RESERVED_EVENTS
    assert EventName.HOOK_FAILED in V01_RESERVED_EVENTS
    assert len(V01_RESERVED_EVENTS) == 2, (
        f"V01_RESERVED_EVENTS has {len(V01_RESERVED_EVENTS)} entries; expected 2"
    )


def test_all_event_names_dotted_form() -> None:
    """All canonical EventName values use dotted notation (per F.COHERENCE.04 / M97)."""
    for e in EventName:
        assert "." in e.value, f"{e.value!r} is not in dotted form"


def test_event_name_symbols_match_uppercase_canonical_form() -> None:
    """Each enum member's symbol is the uppercased dotted form with '.' → '_'."""
    for e in EventName:
        expected_symbol = e.value.upper().replace(".", "_")
        assert e.name == expected_symbol, (
            f"EventName.{e.name}.value={e.value!r} but symbol should be {expected_symbol!r}"
        )
