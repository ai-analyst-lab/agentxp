"""Track B — DATA_ONLY warehouse-path smoke tests.

Uses a temp DuckDB file as a stand-in for a real warehouse. Verifies the
SQL safety pipeline + DuckDB adapter + QueryArtifact writer all wire end
to end and emit the expected ``query.executed`` event in ``log.jsonl``.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §11 (5-layer safety),
§13 (QueryArtifact), §10.5.5 (auth_expired wiring).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from openxp.sql.adapters.duckdb_adapter import DuckDBAdapter
from openxp.sql.artifact_writer import list_query_artifacts, read_query_artifact
from openxp.sql.dispatch import SqlIntent, dispatch_sql


def _run_select(tiny_duckdb: Path, exp_dir: Path):
    adapter = DuckDBAdapter(file_path=tiny_duckdb)
    intent = SqlIntent(
        purpose="preview",
        sql="SELECT user_id, converted FROM users LIMIT 5",
        dialect="duckdb",
        exp_id=exp_dir.name,
        adapter_type="duckdb",
        agent_name="sql_query_writer",
        stage="data_plan_confirmed",
    )
    try:
        return dispatch_sql(intent, adapter, exp_dir)
    finally:
        adapter.close()


def test_warehouse_select_writes_query_artifact(
    fake_exp_dir: Path, tiny_duckdb: Path
) -> None:
    """A successful SELECT writes a QueryArtifact YAML to queries/."""
    result = _run_select(tiny_duckdb, fake_exp_dir)
    assert result.final_status == "executed", (
        f"expected executed; got {result.final_status} ({result.error_message})"
    )
    artifacts = list_query_artifacts(fake_exp_dir)
    assert artifacts, "queries/ should hold at least one artifact"
    # Round-trip: the on-disk artifact validates.
    artifact = read_query_artifact(artifacts[-1])
    assert artifact.outcome.value in {"executed", "proposed"}


def test_warehouse_select_emits_query_executed_event(
    fake_exp_dir: Path, tiny_duckdb: Path
) -> None:
    """log.jsonl gains ``query.proposed`` + ``query.executed`` rows."""
    _run_select(tiny_duckdb, fake_exp_dir)
    log = fake_exp_dir / "log.jsonl"
    assert log.exists(), "log.jsonl must be created by dispatch_sql"
    events = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]
    names = [ev.get("event_name") for ev in events]
    assert "query.proposed" in names
    assert "query.executed" in names


def test_warehouse_safety_blocks_write_sql(
    fake_exp_dir: Path, tiny_duckdb: Path
) -> None:
    """Layer-1 read-only enforcement: DELETE is blocked before adapter dispatch."""
    adapter = DuckDBAdapter(file_path=tiny_duckdb)
    intent = SqlIntent(
        purpose="preview",
        sql="DELETE FROM users WHERE converted = 0",
        dialect="duckdb",
        exp_id=fake_exp_dir.name,
        adapter_type="duckdb",
        agent_name="sql_query_writer",
        stage="data_plan_confirmed",
    )
    try:
        result = dispatch_sql(intent, adapter, fake_exp_dir)
    finally:
        adapter.close()
    assert result.final_status == "blocked_by_safety", (
        f"DELETE must be blocked by Layer 1; got {result.final_status}"
    )
    # And a query.failed row landed.
    log = fake_exp_dir / "log.jsonl"
    events = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]
    assert any(ev.get("event_name") == "query.failed" for ev in events)
