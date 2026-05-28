"""
AgentXP metric definitions.

Reusable metric definitions loaded from YAML files. Experiments reference
metrics by name (e.g. `checkout_completion_rate`) and the registry resolves
each name to a MetricDefinition with the correct test function.

Usage:
    from agentxp.metrics import MetricRegistry, load_metric

    registry = MetricRegistry()  # autoloads ./metrics or ~/.agentxp/metrics
    md = registry.get("checkout_completion_rate")
    test_fn = to_test_function(md)
"""

from agentxp.metrics.schema import (
    MetricDefinition,
    MetricValidationError,
    to_test_function,
    validate,
)
from agentxp.metrics.registry import (
    MetricRegistry,
    load_all_metrics,
    load_metric,
)

__all__ = [
    "MetricDefinition",
    "MetricRegistry",
    "MetricValidationError",
    "load_metric",
    "load_all_metrics",
    "to_test_function",
    "validate",
]
