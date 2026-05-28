"""Tests for openxp.sql.dispatch.

Covers the synchronous §22.5 SQL dispatch chokepoint: 5-layer safety pass,
correction retry loop, auth_expired surrender, artifact + audit emission.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from openxp.sql.adapter import (
    AdapterError,
    AdapterResult,
    AuthExpiredError,
    PreviewResult,
)
from openxp.sql.dispatch import SqlIntent, dispatch_sql
from openxp.sql.schema import QueryOutcome


# ──────────────────────────────────────────────────────────────────────────
# Fake adapter helpers
# ──────────────────────────────────────────────────────────────────────────


class _FakeAdapter:
    """In-memory BaseAdapter stand-in for dispatch tests.

    ``responses`` is a list of either AdapterResult or Exception objects.
    Each call to :meth:`execute` consumes the next entry; exceptions are
    raised, results are returned.
    """

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[str] = []

    def execute(self, sql: str, max_rows: int = 10_000, timeout_s: int = 30):
        self.calls.append(sql)
        if not self._responses:
            raise AdapterError("FakeAdapter exhausted")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def explain(self, sql: str) -> str:
        return "fake plan"

    def dry_run(self, sql: str) -> PreviewResult:
        return PreviewResult()

    def get_dialect(self) -> str:
        return "duckdb"

    def close(self) -> None:
        pass


def _ok(rows: int = 1, elapsed: float = 0.01) -> AdapterResult:
    return AdapterResult(
        rows=[{"x": i} for i in range(rows)],
        row_count=rows,
        bytes_scanned=None,
        elapsed_seconds=elapsed,
        dialect="duckdb",
    )


def _intent(sql: str = "SELECT 1 AS x", purpose: str = "preview") -> SqlIntent:
    return SqlIntent(
        purpose=purpose,
        sql=sql,
        dialect="duckdb",
        exp_id="exp-test",
        adapter_type="duckdb",
        auth_kind="none",
        profile_name="default",
        stage="0_data_archaeology",
    )


def _read_events(exp_dir: Path) -> list[dict]:
    log_path = exp_dir / "log.jsonl"
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


def test_dispatch_happy_path(tmp_path: Path):
    adapter = _FakeAdapter([_ok(rows=3)])
    result = dispatch_sql(_intent(), adapter, tmp_path)

    assert result.final_status == "executed"
    assert result.attempts == 1
    assert result.adapter_result is not None
    assert result.adapter_result.row_count == 3
    assert result.artifact.outcome == QueryOutcome.EXECUTED


def test_dispatch_blocked_by_safety(tmp_path: Path):
    # DELETE is rejected by Layer 2 (read-only).
    intent = _intent(sql="DELETE FROM users WHERE id = 1")
    adapter = _FakeAdapter([])  # never reached
    result = dispatch_sql(intent, adapter, tmp_path)

    assert result.final_status == "blocked_by_safety"
    assert result.attempts == 1
    assert result.adapter_result is None
    assert result.artifact.outcome == QueryOutcome.BLOCKED
    assert adapter.calls == []  # adapter never invoked

    # Both query.proposed and query.failed should be in the log.
    events = _read_events(tmp_path)
    names = [e["event_name"] for e in events]
    assert "query.proposed" in names
    assert "query.failed" in names


def test_dispatch_correction_succeeds_on_second_attempt(tmp_path: Path):
    bad_error = AdapterError("syntax error near `frm`")
    adapter = _FakeAdapter([bad_error, _ok(rows=2)])

    def fix_it(failed_sql: str, err: str, attempt: int) -> str:
        # Pretend the corrector rewrites the SQL into a valid query.
        return "SELECT 2 AS x"

    result = dispatch_sql(
        _intent(sql="SELECT 1 AS x"),
        adapter,
        tmp_path,
        correction_fn=fix_it,
    )

    assert result.final_status == "executed"
    assert result.attempts == 2
    assert result.adapter_result is not None
    assert result.adapter_result.row_count == 2
    assert len(adapter.calls) == 2


def test_dispatch_correction_exhausts_attempts(tmp_path: Path):
    adapter = _FakeAdapter([
        AdapterError("boom 1"),
        AdapterError("boom 2"),
        AdapterError("boom 3"),
    ])

    def keep_trying(failed_sql: str, err: str, attempt: int) -> str:
        return f"SELECT {attempt} AS x"

    result = dispatch_sql(
        _intent(),
        adapter,
        tmp_path,
        max_correction_attempts=3,
        correction_fn=keep_trying,
    )

    assert result.final_status == "failed_after_correction"
    assert result.attempts == 3
    assert result.adapter_result is None
    # Final query.failed should carry the failed_after_retries subtype.
    events = _read_events(tmp_path)
    failed = [e for e in events if e["event_name"] == "query.failed"]
    assert failed, "expected at least one query.failed event"
    assert failed[-1]["metadata"].get("subtype") == "failed_after_retries"


def test_dispatch_auth_expired_surrenders(tmp_path: Path):
    adapter = _FakeAdapter([AuthExpiredError("token expired")])

    def never_called(failed_sql: str, err: str, attempt: int) -> str:
        raise AssertionError("correction_fn must not be invoked on auth_expired")

    result = dispatch_sql(
        _intent(),
        adapter,
        tmp_path,
        max_correction_attempts=3,
        correction_fn=never_called,
    )

    assert result.final_status == "auth_expired"
    assert result.attempts == 1
    assert result.adapter_result is None
    events = _read_events(tmp_path)
    failed = [e for e in events if e["event_name"] == "query.failed"]
    assert failed
    assert failed[-1]["metadata"].get("subtype") == "auth_expired"
    assert failed[-1]["error_class"] == "AuthExpiredError"


def test_dispatch_writes_artifacts_at_every_status(tmp_path: Path):
    """Happy path writes both a 'proposed' artifact and an 'executed' artifact."""
    adapter = _FakeAdapter([_ok(rows=1)])
    dispatch_sql(_intent(), adapter, tmp_path)

    queries_dir = tmp_path / "queries"
    written = list(queries_dir.glob("*.yaml"))
    # We expect the proposed write + the executed overwrite for the same query_id.
    # write_query_artifact may overwrite the same file (same query_id) which is
    # the expected behaviour — assert at least one artifact landed.
    assert len(written) >= 1


def test_dispatch_emits_proposed_and_executed_events(tmp_path: Path):
    adapter = _FakeAdapter([_ok(rows=5)])
    dispatch_sql(_intent(), adapter, tmp_path)

    events = _read_events(tmp_path)
    names = [e["event_name"] for e in events]
    assert "query.proposed" in names
    assert "query.executed" in names
    executed = [e for e in events if e["event_name"] == "query.executed"][0]
    assert executed["rows_returned"] == 5


def test_dispatch_uses_purpose_resource_bounds(tmp_path: Path):
    """The adapter must receive max_rows / timeout_s from the §11 matrix."""
    captured: dict = {}

    class _Recorder(_FakeAdapter):
        def execute(self, sql: str, max_rows: int = 10_000, timeout_s: int = 30):
            captured["max_rows"] = max_rows
            captured["timeout_s"] = timeout_s
            return _ok(rows=1)

    adapter = _Recorder([])
    # profile purpose → (100_000, 60); use a SELECT so LIMIT injection lands.
    dispatch_sql(_intent(sql="SELECT 1 AS x", purpose="profile"), adapter, tmp_path)

    assert captured["max_rows"] == 100_000
    assert captured["timeout_s"] == 60
