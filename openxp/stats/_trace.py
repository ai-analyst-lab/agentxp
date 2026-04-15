"""
Opt-in computation tracing for openxp.stats functions.

The `/experiment` skill orchestrator (and the D.9 validation step it enforces)
expects stats functions to expose a `computation_trace` dict describing how a
result was computed: the inputs, the intermediate values, and a pointer to the
formula reference. Emitting this unconditionally would balloon every return
dict, so tracing is opt-in via a module-level flag.

Usage
-----
    from openxp.stats._trace import set_trace, is_trace_enabled, trace_dict

    # Tracing is ON by default (D.9 audit-trail contract).
    result = welch_test(control, treatment)
    # result["computation_trace"] is now present

    # Disable only if a caller explicitly wants slimmer return dicts:
    set_trace(False)
    result = welch_test(control, treatment)
    # result has no "computation_trace" key

The trace dict shape is stable and documented here so agents can validate it:

    {
        "inputs": {...},               # raw inputs (or summaries for arrays)
        "intermediate_values": {...},  # named sub-results (means, SEs, etc.)
        "formula_ref": "<str>",        # human-readable formula identifier
        "timestamp": "<ISO-8601 UTC>", # when the trace was built
    }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Module-level flag. Defaults to ON because the `/experiment` skill and the
# D.9 audit-trail contract expect every stats return dict to carry a
# `computation_trace`. The `interpret` mode validates traces before advancing
# state, so turning this off silently breaks the analyze -> interpret handoff.
# Callers that want slimmer return dicts can `set_trace(False)` explicitly.
_TRACE_ENABLED: bool = True


def set_trace(enabled: bool) -> None:
    """Enable or disable computation tracing for all openxp.stats functions."""
    global _TRACE_ENABLED
    _TRACE_ENABLED = bool(enabled)


def is_trace_enabled() -> bool:
    """Return True if tracing is currently enabled."""
    return _TRACE_ENABLED


def trace_dict(
    inputs: dict[str, Any],
    intermediate: dict[str, Any],
    formula: str,
) -> dict[str, Any]:
    """Build the standard computation trace dict."""
    return {
        "inputs": dict(inputs),
        "intermediate_values": dict(intermediate),
        "formula_ref": str(formula),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
