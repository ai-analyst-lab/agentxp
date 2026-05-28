"""Tests for agentxp.data.csv_loader."""

import os
from unittest.mock import patch

import pandas as pd
import pytest

from agentxp.data import CSVLoader
from agentxp.data.base import LoadResult


SAMPLE_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "sample-data")
)
CLEAN_AB = os.path.join(SAMPLE_DATA_DIR, "clean_ab.csv")


class TestCSVLoaderLoad:
    def test_loads_clean_ab(self):
        loader = CSVLoader()
        result = loader.load(CLEAN_AB)
        assert isinstance(result, LoadResult)
        assert isinstance(result.dataframe, pd.DataFrame)
        assert result.n_rows > 0
        assert result.n_columns >= 4
        assert result.source.kind == "csv"
        assert result.source.location == CLEAN_AB

    def test_clean_ab_columns_match_file(self):
        result = CSVLoader().load(CLEAN_AB)
        assert "variant" in result.dataframe.columns
        assert "revenue" in result.dataframe.columns

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CSVLoader().load(str(tmp_path / "does_not_exist.csv"))

    def test_chunked_load_matches_direct_load(self):
        direct = CSVLoader().load(CLEAN_AB).dataframe
        chunked = CSVLoader().load(CLEAN_AB, chunk_size=1000).dataframe
        assert len(direct) == len(chunked)
        assert list(direct.columns) == list(chunked.columns)

    def test_interpretation_is_populated(self):
        result = CSVLoader().load(CLEAN_AB)
        assert result.interpretation
        assert "row" in result.interpretation.lower()


class TestCSVLoaderPeek:
    def test_peek_returns_n_rows(self):
        df = CSVLoader().peek(CLEAN_AB, n=5)
        assert len(df) == 5
        assert "variant" in df.columns

    def test_peek_default_is_five(self):
        df = CSVLoader().peek(CLEAN_AB)
        assert len(df) == 5

    def test_peek_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CSVLoader().peek(str(tmp_path / "nope.csv"))


class TestCSVLoaderGuard:
    def test_large_file_guard_triggers(self):
        """Mock the row count to simulate a >10M-row file."""
        loader = CSVLoader()
        with patch.object(CSVLoader, "_count_rows", return_value=20_000_000):
            with pytest.raises(ValueError, match="hard limit"):
                loader.load(CLEAN_AB)

    def test_force_bypasses_hard_limit(self):
        loader = CSVLoader()
        with patch.object(CSVLoader, "_count_rows", return_value=20_000_000):
            # Should not raise when force=True (it actually loads the small file)
            result = loader.load(CLEAN_AB, force=True)
            assert result.n_rows > 0

    def test_soft_warning_for_medium_files(self):
        loader = CSVLoader()
        with patch.object(CSVLoader, "_count_rows", return_value=200_000):
            result = loader.load(CLEAN_AB)
            assert any("DuckDB" in w for w in result.warnings)

    def test_hard_warning_for_large_files(self):
        loader = CSVLoader()
        with patch.object(CSVLoader, "_count_rows", return_value=2_000_000):
            result = loader.load(CLEAN_AB)
            assert any("memory" in w.lower() for w in result.warnings)

    def test_small_file_no_warnings(self):
        result = CSVLoader().load(CLEAN_AB)
        assert result.warnings == []


class TestCSVLoaderStream:
    def test_stream_yields_chunks(self):
        chunks = list(CSVLoader().stream(CLEAN_AB, chunk_size=1000))
        assert len(chunks) > 1
        total = sum(len(c) for c in chunks)
        direct = CSVLoader().load(CLEAN_AB).dataframe
        assert total == len(direct)
