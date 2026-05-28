"""Canonical AgentXP error codes and default message/hint templates.

Each code is a stable string constant (``E_*``) paired with a default
message template and a default hint template. Callers can use the
templates as-is or format them with context-specific values.

Message templates use Python ``str.format`` placeholders. Hints are
plain strings and should always describe the *next action* the user
can take.

Usage::

    from agentxp.errors import codes, ValidationError

    raise ValidationError(
        code=codes.E_MISSING_FIELD,
        message=codes.MESSAGES[codes.E_MISSING_FIELD].format(field="hypothesis"),
        hint=codes.HINTS[codes.E_MISSING_FIELD].format(field="hypothesis"),
    )
"""

from __future__ import annotations

# --- Schema / validation -------------------------------------------------
E_SCHEMA_INVALID = "E_SCHEMA_INVALID"
E_MISSING_FIELD = "E_MISSING_FIELD"
E_BAD_TYPE = "E_BAD_TYPE"

# --- Lifecycle -----------------------------------------------------------
E_LIFECYCLE_SKIP = "E_LIFECYCLE_SKIP"
E_LIFECYCLE_BACKWARD_NO_REASON = "E_LIFECYCLE_BACKWARD_NO_REASON"

# --- Stats / experiment integrity ----------------------------------------
E_SRM_DETECTED = "E_SRM_DETECTED"
E_GUARDRAIL_VIOLATION = "E_GUARDRAIL_VIOLATION"
E_POWER_NOT_VIABLE = "E_POWER_NOT_VIABLE"

# --- Data loading / shape ------------------------------------------------
E_DATA_TOO_LARGE = "E_DATA_TOO_LARGE"
E_DATA_AMBIGUOUS = "E_DATA_AMBIGUOUS"
E_NAN_VALUES = "E_NAN_VALUES"
E_EMPTY_GROUP = "E_EMPTY_GROUP"

# --- Metrics / deps ------------------------------------------------------
E_METRIC_UNKNOWN = "E_METRIC_UNKNOWN"
E_DEPENDENCY_MISSING = "E_DEPENDENCY_MISSING"
E_BAD_PRIOR = "E_BAD_PRIOR"

# --- Credentials ---------------------------------------------------------
E_CREDENTIALS_MISSING = "E_CREDENTIALS_MISSING"


#: Ordered tuple of all known error code constants.
ALL_CODES: tuple[str, ...] = (
    E_SCHEMA_INVALID,
    E_MISSING_FIELD,
    E_BAD_TYPE,
    E_LIFECYCLE_SKIP,
    E_LIFECYCLE_BACKWARD_NO_REASON,
    E_SRM_DETECTED,
    E_GUARDRAIL_VIOLATION,
    E_POWER_NOT_VIABLE,
    E_DATA_TOO_LARGE,
    E_DATA_AMBIGUOUS,
    E_METRIC_UNKNOWN,
    E_DEPENDENCY_MISSING,
    E_BAD_PRIOR,
    E_NAN_VALUES,
    E_EMPTY_GROUP,
    E_CREDENTIALS_MISSING,
)


#: Default message templates for each code. May contain ``{placeholders}``.
MESSAGES: dict[str, str] = {
    E_SCHEMA_INVALID: "Schema validation failed: {reason}",
    E_MISSING_FIELD: "Missing required field '{field}'",
    E_BAD_TYPE: "Field '{field}' has wrong type: expected {expected}, got {got}",
    E_LIFECYCLE_SKIP: "Illegal lifecycle transition: {from_state} -> {to_state}",
    E_LIFECYCLE_BACKWARD_NO_REASON: (
        "Backward transition {from_state} -> {to_state} requires an amendment_reason"
    ),
    E_SRM_DETECTED: "Sample Ratio Mismatch detected (p={p_value})",
    E_GUARDRAIL_VIOLATION: "Guardrail metric '{metric}' violated",
    E_POWER_NOT_VIABLE: "Experiment is not statistically viable at current sample size",
    E_DATA_TOO_LARGE: "Input data is too large to load ({rows} rows)",
    E_DATA_AMBIGUOUS: "Data schema is ambiguous: {reason}",
    E_METRIC_UNKNOWN: "Unknown metric '{metric}'",
    E_DEPENDENCY_MISSING: "Required dependency '{dep}' is not installed",
    E_BAD_PRIOR: "Invalid Bayesian prior: {reason}",
    E_NAN_VALUES: "Column '{column}' contains NaN values",
    E_EMPTY_GROUP: "Group '{group}' has zero observations",
    E_CREDENTIALS_MISSING: "Required credentials for '{service}' are not set",
}


#: Default actionable hint templates for each code.
HINTS: dict[str, str] = {
    E_SCHEMA_INVALID: "Fix the schema issue described above and re-run validation.",
    E_MISSING_FIELD: "Add a '{field}' entry to the YAML and re-run.",
    E_BAD_TYPE: "Change '{field}' to a {expected} value.",
    E_LIFECYCLE_SKIP: (
        "Take one step at a time through the lifecycle DAG; see "
        "agentxp.storage.lifecycle.VALID_TRANSITIONS."
    ),
    E_LIFECYCLE_BACKWARD_NO_REASON: (
        "Pass amendment_reason='<why you are retreating>' to store.save()."
    ),
    E_SRM_DETECTED: (
        "Do not interpret results. Investigate bot filtering, redirects, "
        "or bucketing bugs before proceeding."
    ),
    E_GUARDRAIL_VIOLATION: (
        "Do not ship. Quantify the trade-off or redesign the treatment."
    ),
    E_POWER_NOT_VIABLE: (
        "Increase allocation, extend duration, or raise MDE until viable."
    ),
    E_DATA_TOO_LARGE: "Pre-aggregate in SQL, or sample before loading into AgentXP.",
    E_DATA_AMBIGUOUS: (
        "Use agentxp.data.discovery.prepare_experiment_data() with explicit hints."
    ),
    E_METRIC_UNKNOWN: "Register '{metric}' in metrics/ or fix the typo in experiment.yaml.",
    E_DEPENDENCY_MISSING: "Install it with `pip install {dep}` and retry.",
    E_BAD_PRIOR: "Use a proper Beta/Normal prior with strictly positive parameters.",
    E_NAN_VALUES: "Drop or impute NaN values in '{column}' before running stats.",
    E_EMPTY_GROUP: "Check your variant assignment — '{group}' has no observations.",
    E_CREDENTIALS_MISSING: (
        "Set the required environment variable(s) for '{service}' and retry."
    ),
}


def message_for(code: str, **fmt: object) -> str:
    """Return the default message for ``code`` formatted with ``fmt``.

    Unknown placeholders are left untouched (falls back to a plain string on
    KeyError) so callers don't have to supply every placeholder.
    """
    template = MESSAGES.get(code, code)
    try:
        return template.format(**fmt)
    except KeyError:
        return template


def hint_for(code: str, **fmt: object) -> str:
    """Return the default hint for ``code`` formatted with ``fmt``."""
    template = HINTS.get(code, "")
    try:
        return template.format(**fmt)
    except KeyError:
        return template
