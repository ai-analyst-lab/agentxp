"""
Shared test fixtures for OpenXP stats tests.

Provides synthetic datasets with KNOWN effects for validation:
- clean_ab: 5% lift in conversion, n=2000/group
- large_effect_ab: 50% lift in conversion, n=5000/group
- no_effect_ab: null effect (A/A test)
- continuous_ab: known mean difference in revenue
- ratio_metric_data: ratio metric (revenue per session) with known effect
- srm_clean: clean 50/50 split
- srm_violation: imbalanced split
"""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def rng():
    """Reproducible random number generator."""
    return np.random.default_rng(42)


@pytest.fixture
def clean_ab(rng):
    """A/B test with known 5% relative lift in conversion.

    Control: 10% conversion, n=2000
    Treatment: 10.5% conversion, n=2000
    """
    n = 2000
    control = rng.binomial(1, 0.10, size=n)
    treatment = rng.binomial(1, 0.105, size=n)
    return {"control": control, "treatment": treatment,
            "true_lift": 0.05, "true_control_rate": 0.10}


@pytest.fixture
def large_effect_ab(rng):
    """A/B test with large, easily detectable effect.

    Control: 10% conversion, n=5000
    Treatment: 15% conversion, n=5000
    """
    n = 5000
    control = rng.binomial(1, 0.10, size=n)
    treatment = rng.binomial(1, 0.15, size=n)
    return {"control": control, "treatment": treatment,
            "true_lift": 0.50, "true_control_rate": 0.10}


@pytest.fixture
def no_effect_ab(rng):
    """A/B test with no true effect (A/A test).

    Both groups: 10% conversion, n=2000
    """
    n = 2000
    control = rng.binomial(1, 0.10, size=n)
    treatment = rng.binomial(1, 0.10, size=n)
    return {"control": control, "treatment": treatment}


@pytest.fixture
def continuous_ab(rng):
    """A/B test on continuous metric (revenue) with known effect.

    Control: mean=50, std=20, n=1000
    Treatment: mean=55, std=20, n=1000 (10% lift)
    """
    n = 1000
    control = rng.normal(50, 20, size=n)
    treatment = rng.normal(55, 20, size=n)
    return {"control": control, "treatment": treatment,
            "true_diff": 5.0, "true_std": 20.0}


@pytest.fixture
def ratio_metric_data(rng):
    """Ratio metric data (revenue per session) with known effect.

    Control: ~$5/session, Treatment: ~$5.50/session (10% lift)
    """
    n = 1000
    sessions_c = rng.poisson(3, size=n) + 1
    revenue_c = rng.normal(5, 2, size=n) * sessions_c

    sessions_t = rng.poisson(3, size=n) + 1
    revenue_t = rng.normal(5.5, 2, size=n) * sessions_t

    return {"num_c": revenue_c, "den_c": sessions_c.astype(float),
            "num_t": revenue_t, "den_t": sessions_t.astype(float)}


@pytest.fixture
def srm_clean(rng):
    """Clean randomization — 50/50 split, n=10000."""
    return [5023, 4977]


@pytest.fixture
def srm_violation():
    """SRM violation — 52/48 split, n=10000."""
    return [5200, 4800]
