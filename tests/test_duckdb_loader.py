"""Tests for openxp.data.duckdb_loader. Skipped if duckdb is not installed."""

import os

import pytest

duckdb = pytest.importorskip("duckdb")

from openxp.data import DuckDBLoader  # noqa: E402
from openxp.data.base import LoadResult  # noqa: E402


SAMPLE_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "sample-data")
)
CLEAN_AB = os.path.join(SAMPLE_DATA_DIR, "clean_ab.csv")


@pytest.fixture
def loader():
    ld = DuckDBLoader().connect(":memory:")
    yield ld
    ld.close()


class TestDuckDBLoaderBasics:
    def test_connect_in_memory(self):
        ld = DuckDBLoader().connect(":memory:")
        assert ld.conn is not None
        assert ld.db_path == ":memory:"
        ld.close()

    def test_context_manager(self):
        with DuckDBLoader() as ld:
            assert ld.conn is not None
        assert ld.conn is None

    def test_query_without_connection_raises(self):
        ld = DuckDBLoader()
        with pytest.raises(RuntimeError, match="no active connection"):
            ld.query("SELECT 1")


class TestDuckDBLoaderQuery:
    def test_simple_query(self, loader):
        df = loader.query("SELECT 1 AS x, 2 AS y")
        assert len(df) == 1
        assert df["x"].iloc[0] == 1
        assert df["y"].iloc[0] == 2

    def test_load_csv_as_table(self, loader):
        n = loader.load_csv_as_table(CLEAN_AB, "clean_ab")
        assert n > 0
        df = loader.query("SELECT COUNT(*) AS n FROM clean_ab")
        assert int(df["n"].iloc[0]) == n

    def test_unsafe_table_name_rejected(self, loader):
        with pytest.raises(ValueError, match="Unsafe table name"):
            loader.load_csv_as_table(CLEAN_AB, "drop table; --")


class TestDuckDBLoaderLoadExperiment:
    def test_load_experiment_returns_load_result(self, loader):
        loader.load_csv_as_table(CLEAN_AB, "clean_ab")
        result = loader.load_experiment("clean_ab", treatment_col="variant")
        assert isinstance(result, LoadResult)
        assert result.n_rows > 0
        assert "variant" in result.dataframe.columns
        assert result.source.kind == "duckdb"
        assert result.source.table == "clean_ab"

    def test_missing_treatment_col_raises(self, loader):
        loader.load_csv_as_table(CLEAN_AB, "clean_ab")
        with pytest.raises(ValueError, match="not found in table"):
            loader.load_experiment("clean_ab", treatment_col="does_not_exist")

    def test_unsafe_table_name_in_load_experiment(self, loader):
        with pytest.raises(ValueError, match="Unsafe table name"):
            loader.load_experiment("bad name", treatment_col="variant")

    def test_interpretation_is_populated(self, loader):
        loader.load_csv_as_table(CLEAN_AB, "clean_ab")
        result = loader.load_experiment("clean_ab", treatment_col="variant")
        assert result.interpretation
        assert "clean_ab" in result.interpretation


class TestImportErrorGuard:
    def test_import_error_message_mentions_pip_install(self):
        from openxp.data.duckdb_loader import _DUCKDB_INSTALL_HINT
        assert "pip install" in _DUCKDB_INSTALL_HINT
        assert "openxp[duckdb]" in _DUCKDB_INSTALL_HINT
