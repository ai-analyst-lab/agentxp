"""Tests for agentxp.profiler.heuristics — W_pre2.2 / HG-D4."""
from __future__ import annotations

from agentxp.profiler.heuristics import apply_hg_d4_heuristics
from agentxp.schemas.profiler import ColumnProfile


def _base(**overrides):
    base = {
        "name": "col",
        "dtype": "string",
        "null_rate": 0.0,
        "distinct_count": 10,
        "sample_values": [],
    }
    base.update(overrides)
    return base


def test_null_rate_identifier_flag_user_id() -> None:
    raw = _base(name="user_id", dtype="integer", null_rate=0.6)
    out = apply_hg_d4_heuristics(raw, row_count=100)
    assert out["flagged_for_review"] is True
    assert out["flag_reason"] is not None
    assert "60% null" in out["flag_reason"]
    # Round-trips through ColumnProfile.
    ColumnProfile(**out)


def test_null_rate_identifier_flag_session() -> None:
    raw = _base(name="session", dtype="string", null_rate=0.55)
    out = apply_hg_d4_heuristics(raw, row_count=100)
    assert out["flagged_for_review"] is True
    assert "session" in (out["flag_reason"] or "")


def test_null_rate_identifier_flag_session_prefix() -> None:
    raw = _base(name="session_token", dtype="string", null_rate=0.8)
    out = apply_hg_d4_heuristics(raw, row_count=100)
    assert out["flagged_for_review"] is True


def test_null_rate_non_identifier_not_flagged() -> None:
    raw = _base(name="revenue", dtype="float", null_rate=0.7)
    out = apply_hg_d4_heuristics(raw, row_count=100)
    assert out["flagged_for_review"] is False
    assert out["flag_reason"] is None


def test_null_rate_below_threshold_not_flagged() -> None:
    raw = _base(name="user_id", dtype="integer", null_rate=0.4)
    out = apply_hg_d4_heuristics(raw, row_count=100)
    assert out["flagged_for_review"] is False
    assert out["flag_reason"] is None


def test_mixed_timestamps_iso_and_us() -> None:
    raw = _base(
        name="signup_ts",
        dtype="string",
        sample_values=["2026-01-01", "01/01/2026", "2026-02-15"],
    )
    out = apply_hg_d4_heuristics(raw, row_count=100)
    assert out["mixed_format_detected"] is True
    assert out["flagged_for_review"] is True
    assert out["format_samples"]
    assert "iso8601_date" in (out["flag_reason"] or "")
    assert "us_date" in (out["flag_reason"] or "")
    ColumnProfile(**out)


def test_mixed_timestamps_only_iso() -> None:
    raw = _base(
        name="signup_ts",
        dtype="string",
        sample_values=["2026-01-01", "2026-02-15", "2026-03-30"],
    )
    out = apply_hg_d4_heuristics(raw, row_count=100)
    assert out["mixed_format_detected"] is False
    assert out["flagged_for_review"] is False


def test_mixed_format_skipped_for_non_string_dtype() -> None:
    raw = _base(
        name="signup_ts",
        dtype="integer",
        sample_values=["1", "2", "3"],
    )
    out = apply_hg_d4_heuristics(raw, row_count=100)
    assert out["mixed_format_detected"] is False
    assert out["flagged_for_review"] is False


def test_both_flags_compose_flag_reason() -> None:
    raw = _base(
        name="user_id",
        dtype="string",
        null_rate=0.7,
        sample_values=["2026-01-01", "01/01/2026"],
    )
    out = apply_hg_d4_heuristics(raw, row_count=100)
    assert out["flagged_for_review"] is True
    assert out["flag_reason"] is not None
    assert ";" in out["flag_reason"]
    assert "70% null" in out["flag_reason"]
    assert "multiple timestamp formats" in out["flag_reason"]


def test_iso8601_datetime_with_tz_recognized() -> None:
    raw = _base(
        name="signup_ts",
        dtype="string",
        sample_values=["2026-01-01T12:34:56Z", "01/01/2026"],
    )
    out = apply_hg_d4_heuristics(raw, row_count=10)
    assert out["mixed_format_detected"] is True


def test_epoch_seconds_vs_iso() -> None:
    raw = _base(
        name="ts",
        dtype="string",
        sample_values=["1735689600", "2026-01-01"],
    )
    out = apply_hg_d4_heuristics(raw, row_count=10)
    assert out["mixed_format_detected"] is True
