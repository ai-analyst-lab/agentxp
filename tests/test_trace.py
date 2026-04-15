"""Tests for openxp.stats._trace — opt-in computation tracing."""

from __future__ import annotations

import numpy as np
import pytest

from openxp.stats._trace import is_trace_enabled, set_trace, trace_dict
from openxp.stats.ab_tests import proportion_test, ratio_metric_test, welch_test
from openxp.stats.power import power_mean, power_proportion
from openxp.stats.srm import srm_check


EXPECTED_TRACE_KEYS = {"inputs", "intermediate_values", "formula_ref", "timestamp"}


@pytest.fixture(autouse=True)
def _trace_off_between_tests():
    """Ensure tracing is off before and after every test (safety)."""
    set_trace(False)
    yield
    set_trace(False)


# ---------------------------------------------------------------------------
# trace_dict shape and state flag
# ---------------------------------------------------------------------------

def test_trace_disabled_by_default():
    assert is_trace_enabled() is False


def test_set_trace_toggles_state():
    set_trace(True)
    assert is_trace_enabled() is True
    set_trace(False)
    assert is_trace_enabled() is False


def test_trace_dict_shape():
    d = trace_dict(
        inputs={"x": 1},
        intermediate={"y": 2.0},
        formula="y = x + 1",
    )
    assert set(d.keys()) == EXPECTED_TRACE_KEYS
    assert d["inputs"] == {"x": 1}
    assert d["intermediate_values"] == {"y": 2.0}
    assert d["formula_ref"] == "y = x + 1"
    assert isinstance(d["timestamp"], str)
    assert d["timestamp"].endswith("Z")


# ---------------------------------------------------------------------------
# Backward compatibility: default returns do NOT have computation_trace
# ---------------------------------------------------------------------------

def test_welch_no_trace_by_default():
    c = np.arange(1.0, 11.0)
    t = np.arange(2.0, 12.0)
    result = welch_test(c, t)
    assert "computation_trace" not in result


def test_proportion_no_trace_by_default():
    result = proportion_test(50, 100, 70, 100)
    assert "computation_trace" not in result


def test_ratio_no_trace_by_default():
    num_c = [1.0, 2.0, 3.0, 4.0]
    den_c = [1.0, 1.0, 1.0, 1.0]
    num_t = [2.0, 3.0, 4.0, 5.0]
    den_t = [1.0, 1.0, 1.0, 1.0]
    result = ratio_metric_test(num_c, den_c, num_t, den_t)
    assert "computation_trace" not in result


def test_srm_no_trace_by_default():
    result = srm_check([5000, 5000])
    assert "computation_trace" not in result


def test_power_proportion_no_trace_by_default():
    result = power_proportion(0.1, 0.05)
    assert "computation_trace" not in result


def test_power_mean_no_trace_by_default():
    result = power_mean(50.0, 10.0, 0.05)
    assert "computation_trace" not in result


# ---------------------------------------------------------------------------
# When enabled, computation_trace is present and well-shaped
# ---------------------------------------------------------------------------

def _assert_trace(result: dict) -> None:
    assert "computation_trace" in result, "expected computation_trace key"
    trace = result["computation_trace"]
    assert set(trace.keys()) == EXPECTED_TRACE_KEYS
    assert isinstance(trace["inputs"], dict)
    assert isinstance(trace["intermediate_values"], dict)
    assert isinstance(trace["formula_ref"], str) and trace["formula_ref"]
    assert isinstance(trace["timestamp"], str) and trace["timestamp"].endswith("Z")


def test_welch_trace_when_enabled():
    set_trace(True)
    c = np.arange(1.0, 11.0)
    t = np.arange(2.0, 12.0)
    result = welch_test(c, t)
    _assert_trace(result)
    assert "mean_control" in result["computation_trace"]["intermediate_values"]


def test_proportion_trace_when_enabled():
    set_trace(True)
    result = proportion_test(50, 100, 70, 100)
    _assert_trace(result)
    assert "pooled_rate" in result["computation_trace"]["intermediate_values"]


def test_ratio_trace_when_enabled():
    set_trace(True)
    num_c = [1.0, 2.0, 3.0, 4.0]
    den_c = [1.0, 1.0, 1.0, 1.0]
    num_t = [2.0, 3.0, 4.0, 5.0]
    den_t = [1.0, 1.0, 1.0, 1.0]
    result = ratio_metric_test(num_c, den_c, num_t, den_t)
    _assert_trace(result)


def test_srm_trace_when_enabled():
    set_trace(True)
    result = srm_check([5000, 5000])
    _assert_trace(result)
    assert "chi2_stat" in result["computation_trace"]["intermediate_values"]


def test_power_proportion_trace_when_enabled():
    set_trace(True)
    result = power_proportion(0.1, 0.05)
    _assert_trace(result)
    assert "cohens_h" in result["computation_trace"]["intermediate_values"]


def test_power_mean_trace_when_enabled():
    set_trace(True)
    result = power_mean(50.0, 10.0, 0.05)
    _assert_trace(result)
    assert "cohens_d" in result["computation_trace"]["intermediate_values"]


# ---------------------------------------------------------------------------
# Revert behavior
# ---------------------------------------------------------------------------

def test_set_trace_false_reverts():
    set_trace(True)
    result_on = welch_test([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
    assert "computation_trace" in result_on

    set_trace(False)
    result_off = welch_test([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
    assert "computation_trace" not in result_off


# ---------------------------------------------------------------------------
# Determinism with trace enabled: numeric outputs must be bit-identical to
# an untraced run for the same inputs (tracing must be a pure side-effect).
# ---------------------------------------------------------------------------

def test_trace_does_not_change_numeric_output():
    c = np.arange(1.0, 21.0)
    t = np.arange(2.0, 22.0)

    set_trace(False)
    plain = welch_test(c, t)

    set_trace(True)
    traced = welch_test(c, t)

    # Every shared scalar key should match exactly.
    for key, val in plain.items():
        if key in ("interpretation",):
            assert traced[key] == val
        else:
            assert traced[key] == val, f"mismatch on {key}"
