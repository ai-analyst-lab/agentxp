"""Tests for agentxp.sql.adapter: result models, error hierarchy, redaction."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentxp.sql.adapter import (
    AdapterError,
    AdapterResult,
    AuthExpiredError,
    BaseAdapter,
    BytesLimitExceededError,
    PreviewResult,
    QueryTimeoutError,
    _redact_creds_for_log,
)


def test_adapter_result_pydantic_shape():
    result = AdapterResult(
        rows=[{"id": 1, "name": "alice"}],
        row_count=1,
        bytes_scanned=128,
        elapsed_seconds=0.42,
        dialect="duckdb",
    )
    assert result.row_count == 1
    assert result.rows[0]["name"] == "alice"
    assert result.bytes_scanned == 128
    assert result.elapsed_seconds == pytest.approx(0.42)
    assert result.dialect == "duckdb"

    # extra fields are forbidden by ConfigDict(extra="forbid").
    with pytest.raises(ValidationError):
        AdapterResult(
            rows=[],
            row_count=0,
            elapsed_seconds=0.0,
            dialect="duckdb",
            mystery_field="nope",
        )

    # bytes_scanned is optional.
    minimal = AdapterResult(rows=[], row_count=0, elapsed_seconds=0.0, dialect="duckdb")
    assert minimal.bytes_scanned is None


def test_preview_result_pydantic_shape():
    pv = PreviewResult(
        estimated_rows=10_000,
        estimated_bytes_scanned=1_048_576,
        estimated_cost_usd=0.005,
        warnings=["full table scan"],
    )
    assert pv.estimated_rows == 10_000
    assert pv.estimated_bytes_scanned == 1_048_576
    assert pv.estimated_cost_usd == pytest.approx(0.005)
    assert pv.warnings == ["full table scan"]

    # All fields optional / defaulted.
    empty = PreviewResult()
    assert empty.estimated_rows is None
    assert empty.estimated_bytes_scanned is None
    assert empty.estimated_cost_usd is None
    assert empty.warnings == []

    with pytest.raises(ValidationError):
        PreviewResult(unexpected="field")


def test_adapter_error_hierarchy():
    # Every adapter-specific error is an AdapterError, which is an Exception.
    assert issubclass(AuthExpiredError, AdapterError)
    assert issubclass(QueryTimeoutError, AdapterError)
    assert issubclass(BytesLimitExceededError, AdapterError)
    assert issubclass(AdapterError, Exception)

    # They're catchable as the base class.
    with pytest.raises(AdapterError):
        raise AuthExpiredError("token expired")
    with pytest.raises(AdapterError):
        raise QueryTimeoutError("30s exceeded")
    with pytest.raises(AdapterError):
        raise BytesLimitExceededError("1GB cap")


def test_redact_creds_for_log_scrubs_password():
    creds = {"user": "alice", "password": "secret123"}
    scrubbed = _redact_creds_for_log(creds)

    assert scrubbed["user"] == "alice"
    assert "secret123" not in str(scrubbed)
    assert scrubbed["password"] != "secret123"
    # original dict untouched (returns a copy).
    assert creds["password"] == "secret123"


def test_redact_preserves_non_string_fields():
    creds = {"port": 5432, "ssl": True, "timeout": 30, "retries": None}
    scrubbed = _redact_creds_for_log(creds)
    assert scrubbed == {"port": 5432, "ssl": True, "timeout": 30, "retries": None}


def test_baseadapter_is_protocol():
    # BaseAdapter is decorated with @runtime_checkable, so isinstance checks
    # against any object work and a structurally-conforming class passes.
    class FakeAdapter:
        def execute(self, sql, max_rows=10_000, timeout_s=30):
            return AdapterResult(
                rows=[], row_count=0, elapsed_seconds=0.0, dialect="duckdb"
            )

        def explain(self, sql):
            return ""

        def dry_run(self, sql):
            return PreviewResult()

        def get_dialect(self):
            return "duckdb"

        def close(self):
            return None

    assert isinstance(FakeAdapter(), BaseAdapter)

    class NotAnAdapter:
        def execute(self, sql):
            return None
        # Missing explain / dry_run / get_dialect / close.

    assert not isinstance(NotAnAdapter(), BaseAdapter)
