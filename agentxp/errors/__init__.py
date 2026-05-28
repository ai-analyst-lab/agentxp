"""Structured error handling for AgentXP.

Provides a consistent error envelope (``AgentXPError``) with a stable code,
human-readable message, actionable hint, severity, and optional details dict.
All AgentXP subsystems should raise one of these instead of bare ``ValueError``
so that agent-facing code can render errors uniformly.

Typical usage::

    from agentxp.errors import ValidationError, codes

    raise ValidationError(
        code=codes.E_MISSING_FIELD,
        message="experiment.yaml is missing 'hypothesis'",
        hint="Add a 'hypothesis' block with action/metric/direction.",
        details={"field": "hypothesis"},
    )
"""

from agentxp.errors import codes
from agentxp.errors.base import (
    DataError,
    LifecycleError,
    AgentXPError,
    StatsError,
    StorageError,
    ValidationError,
)

__all__ = [
    "AgentXPError",
    "ValidationError",
    "DataError",
    "StatsError",
    "StorageError",
    "LifecycleError",
    "codes",
]
