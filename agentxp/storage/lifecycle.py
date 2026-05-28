"""
Experiment state machine enforcement.

Implements the full DAG from OPENXP_PRD.md Appendix B. Every state transition
is validated; illegal transitions are rejected with an actionable error hint.

States:
    DESIGNING    - initial; hypothesis + metrics being defined
    POWERED      - power analysis complete, sample size known
    COLLECTING   - data collection in progress (user started in flag system)
    ANALYZING    - data loaded, statistical tests running
    INTERPRETED  - Ship/Investigate/Abort/Learn/Invalid classified
    REPORTED     - stakeholder readout produced
    SHIPPED      - rolled out to 100%
    COMPLETED    - post-ship monitoring done (terminal)
    ABANDONED    - killed before conclusion (terminal)
    INVALID      - randomization broken beyond repair (semi-terminal)
    BLOCKED      - waiting on external dependency

Backward transitions (retreats) require an amendment_reason:
    POWERED     -> DESIGNING  (power not viable; redesign needed)
    ANALYZING   -> COLLECTING (SRM fixable; re-collect after fix)
    INTERPRETED -> COLLECTING (extend duration; underpowered)
    INVALID     -> DESIGNING  (start over with new experiment id)
"""

from __future__ import annotations

# Canonical state set (superset of ExperimentStatus enum — the enum covers only
# the pre-registration stages; the store enforces the full lifecycle DAG).
ALL_STATES: frozenset[str] = frozenset(
    {
        "DESIGNING",
        "POWERED",
        "COLLECTING",
        "ANALYZING",
        "INTERPRETED",
        "REPORTED",
        "SHIPPED",
        "COMPLETED",
        "ABANDONED",
        "INVALID",
        "BLOCKED",
    }
)

# Forward transitions (normal flow).
_FORWARD: dict[str, set[str]] = {
    "DESIGNING": {"POWERED", "ABANDONED", "BLOCKED"},
    "POWERED": {"COLLECTING", "ABANDONED", "BLOCKED"},
    "COLLECTING": {"ANALYZING", "ABANDONED", "BLOCKED"},
    "ANALYZING": {"INTERPRETED", "INVALID", "ABANDONED"},
    "INTERPRETED": {"REPORTED", "ABANDONED"},
    "REPORTED": {"SHIPPED", "ABANDONED"},
    "SHIPPED": {"COMPLETED", "ABANDONED"},
    "COMPLETED": set(),  # terminal
    "ABANDONED": set(),  # terminal
    "BLOCKED": {"DESIGNING", "POWERED", "COLLECTING", "ABANDONED"},
}

# Backward transitions (require amendment_reason).
_BACKWARD: dict[str, set[str]] = {
    "POWERED": {"DESIGNING"},
    "ANALYZING": {"COLLECTING"},
    "INTERPRETED": {"COLLECTING"},
    "INVALID": {"DESIGNING", "ABANDONED"},
}

# Public mapping: current state -> allowed next states (forward ∪ backward).
VALID_TRANSITIONS: dict[str, set[str]] = {
    state: _FORWARD.get(state, set()) | _BACKWARD.get(state, set())
    for state in ALL_STATES
}

# States that, when entered FROM a predecessor, count as a "retreat" and
# therefore require an amendment_reason in the log event.
BACKWARD_TARGETS: dict[str, set[str]] = _BACKWARD


def is_backward(from_state: str, to_state: str) -> bool:
    """True if (from_state -> to_state) is a backward/retreat transition."""
    return to_state in _BACKWARD.get(from_state, set())


def validate_transition(
    from_state: str,
    to_state: str,
) -> tuple[bool, str | None]:
    """Check whether a state transition is permitted.

    Returns
    -------
    (ok, error_message)
        ok=True  -> error_message is None
        ok=False -> error_message is an actionable hint
    """
    if from_state == to_state:
        # No-op saves are allowed (e.g., updating other fields without a
        # lifecycle change).
        return True, None

    if from_state not in ALL_STATES:
        return (
            False,
            f"Unknown current state {from_state!r}. "
            f"Valid states: {sorted(ALL_STATES)}",
        )
    if to_state not in ALL_STATES:
        return (
            False,
            f"Unknown target state {to_state!r}. "
            f"Valid states: {sorted(ALL_STATES)}",
        )

    allowed = VALID_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        hint = _hint_for(from_state, to_state, allowed)
        return (
            False,
            f"Illegal transition {from_state} -> {to_state}. "
            f"Allowed from {from_state}: {sorted(allowed) or '<terminal>'}. "
            f"Hint: {hint}",
        )
    return True, None


def _hint_for(from_state: str, to_state: str, allowed: set[str]) -> str:
    """Actionable hint for illegal transitions."""
    if from_state == "DESIGNING" and to_state == "COLLECTING":
        return "Run power analysis first (DESIGNING -> POWERED -> COLLECTING)."
    if from_state == "COLLECTING" and to_state == "REPORTED":
        return "Run /experiment analyze first (COLLECTING -> ANALYZING -> INTERPRETED -> REPORTED)."
    if from_state in {"COMPLETED", "ABANDONED"}:
        return f"{from_state} is terminal; create a new experiment id."
    if not allowed:
        return f"{from_state} is terminal and cannot transition further."
    return f"Take one step at a time through {' -> '.join(sorted(allowed))}."
