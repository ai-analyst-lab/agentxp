"""Tests for agentxp.profiler.driver — W_pre2.1."""
from __future__ import annotations

import stat
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agentxp.profiler.driver import (
    compute_schema_fingerprint,
    profile_dataset,
    write_profile_bundle,
)
from agentxp.schemas.profiler import ColumnProfile, ProfileReport


def _make_column(
    name: str = "user_id",
    dtype: str = "integer",
    null_rate: float = 0.0,
    distinct_count: int | None = 100,
    mixed_format_detected: bool = False,
    format_samples: list[str] | None = None,
    flagged_for_review: bool = False,
    flag_reason: str | None = None,
) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        dtype=dtype,  # type: ignore[arg-type]
        null_rate=null_rate,
        distinct_count=distinct_count,
        mixed_format_detected=mixed_format_detected,
        format_samples=format_samples or [],
        flagged_for_review=flagged_for_review,
        flag_reason=flag_reason,
    )


def _make_report(columns: list[ColumnProfile], row_count: int = 100) -> ProfileReport:
    return ProfileReport(
        source_ref="agentxp_data.test_table",
        profiled_at=datetime.now(timezone.utc),
        row_count=row_count,
        column_count=len(columns),
        schema_sha256=compute_schema_fingerprint(columns),
        columns=columns,
    )


def test_profile_dataset_raises_for_non_duckdb() -> None:
    with pytest.raises(NotImplementedError, match="W_sql"):
        profile_dataset("some.table", adapter_type="snowflake")


def test_write_profile_bundle_atomic(tmp_path: Path) -> None:
    report = _make_report([_make_column()])
    bundle_path = tmp_path / "bundles" / "profiler.out.yaml"

    write_profile_bundle(report, bundle_path)

    assert bundle_path.exists()
    mode = stat.S_IMODE(bundle_path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    loaded = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    rehydrated = ProfileReport.model_validate(loaded)
    assert rehydrated.model_dump(mode="json") == report.model_dump(mode="json")


def test_schema_fingerprint_stable() -> None:
    cols_a = [
        _make_column(name="user_id", dtype="integer"),
        _make_column(name="email", dtype="string"),
    ]
    cols_b = [
        _make_column(name="email", dtype="string"),
        _make_column(name="user_id", dtype="integer"),
    ]
    assert compute_schema_fingerprint(cols_a) == compute_schema_fingerprint(cols_b)

    cols_c = [_make_column(name="user_id", dtype="string")]
    assert compute_schema_fingerprint(cols_a) != compute_schema_fingerprint(cols_c)


def test_table_level_flags_OR_over_columns() -> None:
    clean = _make_column(name="user_id", dtype="integer")
    dirty = _make_column(
        name="signup_ts",
        dtype="string",
        mixed_format_detected=True,
        format_samples=["2024-01-01T00:00:00Z", "01/02/2024"],
        flagged_for_review=True,
        flag_reason="mixed timestamp formats detected",
    )

    fake_row_count = 100
    columns = [clean, dirty]
    mixed = any(c.mixed_format_detected for c in columns)
    flagged = any(c.flagged_for_review for c in columns)
    assert mixed is True
    assert flagged is True

    fake_raw_columns = [
        {
            "name": "user_id",
            "dtype": "integer",
            "null_rate": 0.0,
            "distinct_count": fake_row_count,
        },
        {
            "name": "signup_ts",
            "dtype": "string",
            "null_rate": 0.0,
            "distinct_count": fake_row_count,
        },
    ]

    def fake_summarize(source_ref, *, file_path=None, sample_values_n=10):
        return {"row_count": fake_row_count, "columns": fake_raw_columns}

    def fake_heuristics(raw_column, *, row_count, **kwargs):
        if raw_column["name"] == "signup_ts":
            return {
                **raw_column,
                "mixed_format_detected": True,
                "format_samples": ["2024-01-01T00:00:00Z", "01/02/2024"],
                "flagged_for_review": True,
                "flag_reason": "mixed timestamp formats detected",
            }
        return {**raw_column}

    with (
        patch(
            "agentxp.profiler.duckdb_summarize.run_duckdb_summarize",
            side_effect=fake_summarize,
        ),
        patch(
            "agentxp.profiler.heuristics.apply_hg_d4_heuristics",
            side_effect=fake_heuristics,
        ),
    ):
        report = profile_dataset("agentxp_data.events", adapter_type="duckdb")

    assert report.mixed_format_detected is True
    assert report.flagged_for_review is True
    assert "2024-01-01T00:00:00Z" in report.format_samples
    assert "01/02/2024" in report.format_samples
    assert report.flag_reason and "mixed timestamp formats" in report.flag_reason


def test_profile_dataset_happy_path_mocked() -> None:
    fake_row_count = 42
    fake_raw_columns = [
        {
            "name": "user_id",
            "dtype": "integer",
            "null_rate": 0.0,
            "distinct_count": 42,
            "sample_values": ["1", "2", "3"],
        },
        {
            "name": "country",
            "dtype": "string",
            "null_rate": 0.1,
            "distinct_count": 12,
            "sample_values": ["US", "UK"],
        },
    ]

    def fake_summarize(source_ref, *, file_path=None, sample_values_n=10):
        assert source_ref == "agentxp_data.events"
        return {"row_count": fake_row_count, "columns": fake_raw_columns}

    def fake_heuristics(raw_column, *, row_count, **kwargs):
        return {**raw_column}

    with (
        patch(
            "agentxp.profiler.duckdb_summarize.run_duckdb_summarize",
            side_effect=fake_summarize,
        ),
        patch(
            "agentxp.profiler.heuristics.apply_hg_d4_heuristics",
            side_effect=fake_heuristics,
        ),
    ):
        report = profile_dataset("agentxp_data.events")

    assert report.schema_version == 1
    assert report.row_count == fake_row_count
    assert report.column_count == 2
    assert len(report.columns) == 2
    assert {c.name for c in report.columns} == {"user_id", "country"}
    assert report.profiled_at.tzinfo is not None
    assert report.profiled_at.utcoffset() == timezone.utc.utcoffset(report.profiled_at)
    assert len(report.schema_sha256) == 64

    # Entity-PK suggestion fires for user_id (null_rate=0, distinct==row_count).
    assert any("user_id" in s and "entity primary key" in s for s in report.suggestions)
    assert not any("country" in s for s in report.suggestions)
