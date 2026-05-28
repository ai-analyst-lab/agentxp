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


def test_redact_creds_for_log_scrubs_bytes_private_key():
    # A Snowflake key-pair private_key arrives as DER bytes, not str — it must
    # still be blanket-redacted (BLOCKER-2).
    der = b"\x30\x82SECRET-DER-BYTES"
    creds = {"account": "myorg", "private_key": der}
    scrubbed = _redact_creds_for_log(creds)
    assert scrubbed["private_key"] == "[REDACTED]"
    assert b"SECRET-DER-BYTES" not in str(scrubbed).encode()
    assert "SECRET-DER-BYTES" not in str(scrubbed)


def test_redact_creds_for_log_recurses_into_nested_sa_dict():
    # An inline service-account dict under a non-sensitive key must be recursed
    # into so its nested private_key is scrubbed (BLOCKER-2 nested recursion).
    creds = {
        "project": "p",
        # Outer key is sensitive → whole value blanket-redacted.
        "credentials_info": {
            "type": "service_account",
            "private_key": "-----BEGIN PRIVATE KEY-----\nLEAKED\n-----END PRIVATE KEY-----",
        },
        # Outer key NON-sensitive → recurse, scrub nested private_key only.
        "extra": {
            "private_key": "nested_LEAKED_value",
            "region": "us-central1",
        },
    }
    scrubbed = _redact_creds_for_log(creds)
    assert scrubbed["credentials_info"] == "[REDACTED]"
    assert scrubbed["extra"]["private_key"] == "[REDACTED]"
    assert scrubbed["extra"]["region"] == "us-central1"
    assert "LEAKED" not in str(scrubbed)


def test_redact_creds_for_log_passes_through_non_sensitive_int():
    creds = {"port": 5432}
    scrubbed = _redact_creds_for_log(creds)
    assert scrubbed["port"] == 5432


def test_redact_creds_for_log_knows_consolidated_secret_keys():
    # The consolidated canonical set covers every per-dialect secret key.
    creds = {
        "access_token": "dapi_x",            # Databricks PAT
        "client_secret": "sp_secret",        # Databricks M2M
        "private_key_file_pwd": "passphrase",  # Snowflake key-file passphrase
        "service_account_info": {"private_key": "k"},  # BigQuery SA dict
        "client_id": "app-id",               # NOT a secret — must pass through
    }
    scrubbed = _redact_creds_for_log(creds)
    assert scrubbed["access_token"] == "[REDACTED]"
    assert scrubbed["client_secret"] == "[REDACTED]"
    assert scrubbed["private_key_file_pwd"] == "[REDACTED]"
    assert scrubbed["service_account_info"] == "[REDACTED]"
    assert scrubbed["client_id"] == "app-id"


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
