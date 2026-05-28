"""AgentXP structured error base classes.

All AgentXP errors inherit from :class:`AgentXPError`, which carries a stable
machine-readable ``code`` (see :mod:`agentxp.errors.codes`), a human message,
an actionable ``hint``, a ``severity`` tag, and a free-form ``details`` dict.

This envelope is designed to be safe to surface directly to an LLM agent:
every error answers both "what went wrong?" and "what should I do about it?".
"""

from __future__ import annotations

from typing import Any, Literal, Optional

Severity = Literal["error", "warning", "info"]
_VALID_SEVERITIES: frozenset[str] = frozenset({"error", "warning", "info"})


class AgentXPError(Exception):
    """Base class for all structured AgentXP errors.

    Parameters
    ----------
    code:
        Stable machine-readable error code, e.g. ``"E_SRM_VIOLATION"``.
        Conventionally defined in :mod:`agentxp.errors.codes`.
    message:
        Human-readable description of what went wrong.
    hint:
        Actionable next step for the user. Required — the AgentXP philosophy
        is that every error tells you what to do next.
    severity:
        One of ``"error"``, ``"warning"``, ``"info"``. Defaults to ``"error"``.
    details:
        Optional free-form dict of extra context (field names, offending
        values, computation traces, etc). Safe to serialize as JSON.
    """

    def __init__(
        self,
        code: str,
        message: str,
        hint: str = "",
        severity: Severity = "error",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("AgentXPError.code must be a non-empty string")
        if not isinstance(message, str) or not message:
            raise ValueError("AgentXPError.message must be a non-empty string")
        if severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"AgentXPError.severity must be one of {sorted(_VALID_SEVERITIES)}, "
                f"got {severity!r}"
            )
        self.code = code
        self.message = message
        self.hint = hint or ""
        self.severity = severity
        self.details: dict[str, Any] = dict(details) if details else {}
        super().__init__(self.__str__())

    def __str__(self) -> str:
        header = f"[{self.code}] {self.message}"
        if self.hint:
            return f"{header}\n  hint: {self.hint}"
        return header

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"{type(self).__name__}(code={self.code!r}, message={self.message!r}, "
            f"severity={self.severity!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation of this error."""
        return {
            "type": type(self).__name__,
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "severity": self.severity,
            "details": dict(self.details),
        }


class ValidationError(AgentXPError):
    """Raised when a YAML or dict fails schema / cross-field validation."""


class DataError(AgentXPError):
    """Raised when input data is missing, malformed, or unusable."""


class StatsError(AgentXPError):
    """Raised when a statistical computation cannot be performed or is unsafe."""


class StorageError(AgentXPError):
    """Raised on persistence / filesystem / atomic-write problems."""


class LifecycleError(AgentXPError):
    """Raised on illegal experiment lifecycle state transitions."""
