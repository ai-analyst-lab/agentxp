"""Tests for agentxp.sql.preview.preview_query.

Verifies the never-raises wrapper around BaseAdapter.dry_run: happy-path
passthrough on the DuckDB adapter, and adapter-exception capture as warnings.
"""
from __future__ import annotations

from agentxp.sql.adapter import PreviewResult
from agentxp.sql.adapters.duckdb_adapter import DuckDBAdapter
from agentxp.sql.preview import preview_query


class _ExplodingAdapter:
    """Stub BaseAdapter whose dry_run raises — used to assert preview_query
    catches and surfaces the failure as a warning rather than re-raising."""

    def execute(self, sql, max_rows=10_000, timeout_s=30):  # pragma: no cover
        raise NotImplementedError

    def explain(self, sql):  # pragma: no cover
        raise NotImplementedError

    def dry_run(self, sql):
        raise RuntimeError("simulated dry_run failure")

    def get_dialect(self):
        return "duckdb"

    def close(self):  # pragma: no cover
        pass


def test_preview_query_happy_path_against_duckdb():
    adapter = DuckDBAdapter()
    try:
        pv = preview_query(adapter, "SELECT 1 AS x", purpose="preview")
        assert isinstance(pv, PreviewResult)
        # DuckDB has no free dry-run; happy path returns the warning.
        assert pv.estimated_rows is None
        assert pv.warnings
    finally:
        adapter.close()


def test_preview_query_catches_adapter_exceptions():
    adapter = _ExplodingAdapter()
    pv = preview_query(adapter, "SELECT 1", purpose="preview")
    assert isinstance(pv, PreviewResult)
    assert pv.estimated_rows is None
    assert pv.estimated_bytes_scanned is None
    assert pv.estimated_cost_usd is None
    assert pv.warnings
    assert any("RuntimeError" in w for w in pv.warnings)
    assert any("simulated dry_run failure" in w for w in pv.warnings)


def test_preview_query_includes_dialect_in_failure_warning():
    adapter = _ExplodingAdapter()
    pv = preview_query(adapter, "SELECT 1", purpose="metric_compute")
    assert any("duckdb" in w for w in pv.warnings)
