"""Structured validators for OpenXP YAML configs.

The validators in this package collect *all* problems in a document and
return them in a :class:`ValidationReport` — they never bail out on the
first failure. This "fail fast with a good hint" path lets agents show
the user every fix they need in a single pass.
"""

from openxp.validators.experiment_validator import (
    ValidationReport,
    validate_experiment_yaml,
)
from openxp.validators.metric_validator import validate_metric_yaml

__all__ = [
    "ValidationReport",
    "validate_experiment_yaml",
    "validate_metric_yaml",
]
