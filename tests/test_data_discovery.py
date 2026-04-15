"""Tests for openxp.data.discovery — schema auto-detection."""

import os

import numpy as np
import pandas as pd
import pytest

from openxp.data import CSVLoader, discover_schema
from openxp.data.base import SchemaDiscovery


SAMPLE_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "sample-data")
)
CLEAN_AB = os.path.join(SAMPLE_DATA_DIR, "clean_ab.csv")
SRM_VIOLATION = os.path.join(SAMPLE_DATA_DIR, "srm_violation.csv")


@pytest.fixture
def clean_df():
    return CSVLoader().load(CLEAN_AB).dataframe


@pytest.fixture
def srm_df():
    return CSVLoader().load(SRM_VIOLATION).dataframe


class TestDiscoverySampleData:
    def test_detects_variant_as_treatment_column(self, clean_df):
        schema = discover_schema(clean_df)
        assert schema.treatment_column == "variant"
        assert schema.confidence["treatment_column"] == "high"

    def test_detects_control_value(self, clean_df):
        schema = discover_schema(clean_df)
        assert schema.control_value == "control"
        assert "treatment" in [str(v) for v in schema.treatment_values]

    def test_metric_columns_include_numerics(self, clean_df):
        schema = discover_schema(clean_df)
        # clean_ab has: user_id, variant, converted, revenue, platform, signup_days
        assert "revenue" in schema.metric_columns
        assert "converted" in schema.metric_columns
        # id-like columns excluded
        assert "user_id" not in schema.metric_columns
        # variant column excluded
        assert "variant" not in schema.metric_columns

    def test_segment_columns_exclude_ids(self, clean_df):
        schema = discover_schema(clean_df)
        assert "user_id" not in schema.segment_columns
        assert "variant" not in schema.segment_columns
        # platform has 2-20 unique string values → should be a segment
        assert "platform" in schema.segment_columns

    def test_srm_violation_still_discovers_schema(self, srm_df):
        schema = discover_schema(srm_df)
        assert schema.treatment_column == "variant"
        assert schema.control_value == "control"
        assert "revenue" in schema.metric_columns
        assert "platform" in schema.segment_columns

    def test_returns_schema_discovery_instance(self, clean_df):
        schema = discover_schema(clean_df)
        assert isinstance(schema, SchemaDiscovery)
        assert schema.n_rows > 0
        assert schema.n_columns > 0
        assert "interpretation" in schema.to_dict()
        assert schema.interpretation  # non-empty

    def test_clean_sample_needs_no_disambiguation(self, clean_df):
        schema = discover_schema(clean_df)
        assert schema.needs_disambiguation == []


class TestDiscoverySynthetic:
    def test_disambiguation_triggers_when_no_treatment_column(self):
        df = pd.DataFrame(
            {
                "user_id": ["u1", "u2", "u3"],
                "revenue": [1.0, 2.0, 3.0],
            }
        )
        schema = discover_schema(df)
        assert schema.treatment_column is None
        assert len(schema.needs_disambiguation) > 0
        assert any(
            "treatment indicator" in msg for msg in schema.needs_disambiguation
        )

    def test_disambiguation_triggers_when_no_metric(self):
        df = pd.DataFrame(
            {
                "user_id": ["u1", "u2", "u3", "u4"],
                "variant": ["control", "treatment", "control", "treatment"],
                "platform": ["web", "ios", "web", "ios"],
            }
        )
        schema = discover_schema(df)
        assert schema.treatment_column == "variant"
        assert schema.metric_columns == []
        assert any(
            "metric" in msg.lower() for msg in schema.needs_disambiguation
        )

    def test_detects_alternate_treatment_column_names(self):
        for hint in ["group", "treatment", "arm", "bucket", "experiment_group"]:
            df = pd.DataFrame(
                {
                    "user_id": range(10),
                    hint: ["control", "treatment"] * 5,
                    "revenue": np.arange(10, dtype=float),
                }
            )
            schema = discover_schema(df)
            assert schema.treatment_column == hint, f"failed for hint {hint}"

    def test_detects_timestamp_column(self):
        df = pd.DataFrame(
            {
                "user_id": range(5),
                "variant": ["control", "treatment"] * 2 + ["control"],
                "revenue": [1.0, 2.0, 3.0, 4.0, 5.0],
                "assigned_at": pd.date_range("2026-01-01", periods=5),
            }
        )
        schema = discover_schema(df)
        assert "assigned_at" in schema.timestamp_columns

    def test_raises_on_non_dataframe(self):
        with pytest.raises(TypeError):
            discover_schema([1, 2, 3])

    def test_detects_numeric_zero_as_control(self):
        df = pd.DataFrame(
            {
                "user_id": range(6),
                "variant": [0, 1, 0, 1, 0, 1],
                "revenue": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            }
        )
        schema = discover_schema(df)
        assert schema.treatment_column == "variant"
        assert schema.control_value == 0
