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

    set_trace(True)
    result = welch_test(control, treatment)
    # result["computation_trace"] is now present
    set_trace(False)

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

# Module-level flag. Defaults to OFF so production calls stay backward
# compatible and don't pay the dict-construction cost.
_TRACE_ENABLED: bool = False


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
