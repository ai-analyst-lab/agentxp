"""Structured error handling for OpenXP.

Provides a consistent error envelope (``OpenXPError``) with a stable code,
human-readable message, actionable hint, severity, and optional details dict.
All OpenXP subsystems should raise one of these instead of bare ``ValueError``
so that agent-facing code can render errors uniformly.

Typical usage::

    from openxp.errors import ValidationError, codes

    raise ValidationError(
        code=codes.E_MISSING_FIELD,
        message="experiment.yaml is missing 'hypothesis'",
        hint="Add a 'hypothesis' block with action/metric/direction.",
        details={"field": "hypothesis"},
    )
"""

from openxp.errors import codes
from openxp.errors.base import (
    DataError,
    LifecycleError,
    OpenXPError,
    StatsError,
    StorageError,
    ValidationError,
)

__all__ = [
    "OpenXPError",
    "ValidationError",
    "DataError",
    "StatsError",
    "StorageError",
    "LifecycleError",
    "codes",
]
