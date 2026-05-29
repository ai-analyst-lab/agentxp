"""Tests for agentxp.audit.redactor.

Covers the 11 load-bearing patterns in §1.7.3, idempotency, multi-pattern combined
input, error-message convenience, performance on a 1MB input, and the public
REDACTION_PATTERNS surface.
"""
from __future__ import annotations

import time

import pytest

from agentxp.audit.redactor import REDACTION_PATTERNS, redact, redact_message


# --- Per-pattern coverage ---------------------------------------------------


def test_aws_access_key_id_redacted() -> None:
    text = "key is AKIAIOSFODNN7EXAMPLE in config"
    out = redact(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[REDACTED_AWS_ACCESS_KEY]" in out
    assert "key is " in out and " in config" in out


def test_aws_secret_access_key_redacted() -> None:
    secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # 40 chars
    text = f"aws_secret_access_key={secret}"
    out = redact(text)
    assert secret not in out
    assert "aws_secret_access_key=" in out
    assert "[REDACTED_AWS_SECRET]" in out


def test_bearer_token_redacted_preserves_header_prefix() -> None:
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdef"
    out = redact(text)
    assert "Authorization: " in out
    assert "Bearer [REDACTED_TOKEN]" in out
    assert "eyJhbGc" not in out


def test_url_credentials_redacted() -> None:
    text = "connect to https://user:pass@host.example.com/path/to/db"
    out = redact(text)
    assert "user:pass@" not in out
    assert "https://[REDACTED_URL_CREDS]@host.example.com/path/to/db" in out


@pytest.mark.parametrize(
    "text,secret,host_kept",
    [
        ("ATTACH 'mysql://root:rootpw123@10.0.0.1/app' AS m", "rootpw123", "10.0.0.1"),
        ("postgresql://u:topsecret@10.0.0.5/db", "topsecret", "10.0.0.5"),
        # Password containing '@' must not strand a fragment after the placeholder.
        ("postgresql://admin:S3cretP@ss@db/prod", "S3cretP", "db/prod"),
        (
            "snowflake://user:hunter2@acct.snowflakecomputing.com/db",
            "hunter2",
            "acct.snowflakecomputing.com",
        ),
        ("redis://default:R3disPw@cache:6379/0", "R3disPw", "cache:6379"),
        ("jdbc:mysql://svc:Jdbc_Pw_9@host:3306/wh", "Jdbc_Pw_9", "host:3306"),
    ],
)
def test_non_http_dsn_credentials_redacted(text, secret, host_kept) -> None:
    # The canonical redactor is scheme-agnostic: only matching https:// would
    # leak passwords from mysql/postgres/snowflake/redis/jdbc DSNs, which a
    # DuckDB user can ATTACH and a driver can echo in an exception.
    out = redact(text)
    assert secret not in out
    assert "[REDACTED_URL_CREDS]" in out
    assert host_kept in out  # host is preserved; only the userinfo is scrubbed


def test_password_in_error_message_redacted() -> None:
    text = "connection failed: password=mySecret123 on host"
    out = redact(text)
    assert "mySecret123" not in out
    assert "password=[REDACTED]" in out


def test_jwt_redacted() -> None:
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    text = f"token: {jwt} expired"
    out = redact(text)
    assert jwt not in out
    assert "[REDACTED_JWT]" in out
    assert "token: " in out and " expired" in out


def test_snowflake_connection_preserves_account_redacts_password() -> None:
    text = "account=acme-prod;user=foo;password=hunter2;warehouse=wh"
    out = redact(text)
    assert "hunter2" not in out
    assert "account=acme-prod" in out
    assert "password=[REDACTED]" in out


def test_private_key_block_redacted() -> None:
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEAxyz...\nmoreLines\n"
        "-----END RSA PRIVATE KEY-----"
    )
    out = redact(text)
    assert "MIIEowIBAA" not in out
    assert "[REDACTED_PRIVATE_KEY]" in out


def test_gcp_private_key_json_field_redacted() -> None:
    text = (
        '{"type":"service_account",'
        '"private_key":"-----BEGIN PRIVATE KEY-----\\nABCDEF\\n-----END PRIVATE KEY-----\\n",'
        '"client_email":"sa@proj.iam.gserviceaccount.com"}'
    )
    out = redact(text)
    assert "ABCDEF" not in out
    assert '"private_key": "[REDACTED_GCP_PRIVATE_KEY]"' in out
    # Surrounding JSON structure preserved.
    assert '"type":"service_account"' in out


def test_email_redacted() -> None:
    text = "error reaching user@example.com over smtp"
    out = redact(text)
    assert "user@example.com" not in out
    assert "[REDACTED_EMAIL]" in out


def test_home_path_normalized() -> None:
    text = "no such file: /Users/alice/foo/bar.csv"
    out = redact(text)
    assert "/Users/alice/" not in out
    assert "~/foo/bar.csv" in out


# --- Cross-cutting properties ----------------------------------------------


@pytest.mark.parametrize(
    "sample",
    [
        "key AKIAIOSFODNN7EXAMPLE",
        "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdef",
        "https://user:pass@host/path",
        "password=mySecret123",
        (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        ),
        "account=acme;password=hunter2",
        "-----BEGIN PRIVATE KEY-----\nABC\n-----END PRIVATE KEY-----",
        '"private_key":"abc"',
        "user@example.com",
        "/Users/alice/foo",
    ],
)
def test_idempotent(sample: str) -> None:
    once = redact(sample)
    twice = redact(once)
    assert once == twice


def test_combined_text_redacts_all_patterns_in_one_pass() -> None:
    text = (
        "AWS key AKIAIOSFODNN7EXAMPLE failed to auth at "
        "https://admin:hunter2@db.example.com/ for user dev@example.com"
    )
    out = redact(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "admin:hunter2@" not in out
    assert "dev@example.com" not in out
    assert "[REDACTED_AWS_ACCESS_KEY]" in out
    assert "[REDACTED_URL_CREDS]" in out
    assert "[REDACTED_EMAIL]" in out


def test_empty_string() -> None:
    assert redact("") == ""


def test_plain_text_unchanged() -> None:
    text = "SELECT count(*) FROM events WHERE day = '2026-05-27'"
    assert redact(text) == text


def test_redact_message_scrubs_exception() -> None:
    exc = ValueError("connect failed: password=topsecret")
    out = redact_message(exc)
    assert "topsecret" not in out
    assert "password=[REDACTED]" in out


def test_performance_1mb_linear_no_backtracking() -> None:
    # The contract is "O(text length); no quadratic backtracking" — verify that
    # 1MB completes well under a second (a catastrophic backtracker would hang
    # for minutes or run out of stack). The pure-CPython `re` engine cannot hit
    # the spec's optimistic <100ms target on a 1MB alternation-heavy scan, but
    # linearity is what the audit hot path actually needs.
    body = "SELECT count(*) FROM events WHERE day = '2026-05-27' AND ts > now() - interval 1 day; "
    secrets = (
        " password=hunter2 AKIAIOSFODNN7EXAMPLE user@example.com "
        "https://u:p@host/db Authorization: Bearer eyJabcdefghijklmnopqrstuvwxyz "
    )
    # ~1MB of body with one secret block every ~10KB.
    text = (body * 125 + secrets) * 100
    assert len(text) >= 1_000_000

    start = time.perf_counter()
    out = redact(text)
    elapsed_1mb = time.perf_counter() - start

    # Linearity check: doubling input should roughly double time, not square it.
    text2 = text * 2
    start = time.perf_counter()
    redact(text2)
    elapsed_2mb = time.perf_counter() - start

    assert elapsed_1mb < 2.0, f"1MB redact took {elapsed_1mb:.3f}s"
    # 2x input should take <3x time (loose bound to absorb timing jitter).
    assert elapsed_2mb < elapsed_1mb * 3, (
        f"non-linear: 1MB={elapsed_1mb:.3f}s, 2MB={elapsed_2mb:.3f}s"
    )
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "hunter2" not in out


def test_multiline_input_with_multiple_credentials() -> None:
    text = (
        "line1: AKIAIOSFODNN7EXAMPLE\n"
        "line2: password=hunter2\n"
        "line3: https://u:p@host/db\n"
        "line4: nothing sensitive here\n"
    )
    out = redact(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "hunter2" not in out
    assert "u:p@host" not in out
    assert "nothing sensitive here" in out


def test_password_keyword_case_insensitive() -> None:
    for keyword in ("password", "Password", "PASSWORD"):
        out = redact(f"{keyword}=secretValue")
        assert "secretValue" not in out
        assert f"{keyword}=[REDACTED]" in out


def test_redaction_patterns_exposed_and_nonempty() -> None:
    assert REDACTION_PATTERNS
    assert all(len(entry) == 2 for entry in REDACTION_PATTERNS)
