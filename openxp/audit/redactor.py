"""Synchronous regex redactor for PII and credentials in audit-bound text.

Replaces v1's external `pii_pre_flight` hook with an internal scrubber used by
OrchestratorStore.dispatch_sql, the error-message wrapper around `except` surfaces
in store.py (B9), and any user-supplied text crossing the audit log boundary.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §1.7.3, §1.8.13, §22.5.
Idempotent by construction: every replacement uses a `[REDACTED_*]` placeholder
that no pattern matches a second time.
"""
from __future__ import annotations

import re

# AWS access key IDs (AKIA + 16 base32 chars).
_AWS_ACCESS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")

# AWS secret access key when adjacent to its canonical key name.
_AWS_SECRET = re.compile(
    r"(aws_secret_access_key\s*[:=]\s*)([A-Za-z0-9/+=]{40})",
    re.IGNORECASE,
)

# JWT: three base64url segments separated by dots, header starts with `eyJ`.
_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+")

# PEM-encapsulated private key block.
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----[\s\S]*?-----END \1PRIVATE KEY-----"
)

# GCP service-account JSON: `"private_key": "..."` fragment.
_GCP_PRIVATE_KEY_JSON = re.compile(r'"private_key"\s*:\s*"[^"]+"')

# Bearer token in an Authorization header / similar context.
_BEARER = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.=]{20,}")

# Snowflake-style connection string: preserve account, redact password. The gap
# between `account=` and `password=` is bounded to avoid pathological backtracking.
_SNOWFLAKE_CONN = re.compile(
    r"(account=)([^&;\s]+)([^=]{0,200}?)(password=)([^&;\s]+)",
    re.IGNORECASE,
)

# URL with embedded credentials: scheme://user:pass@host -> placeholder.
_URL_CREDS = re.compile(r"(https?://)[^:/\s]+:[^@\s]+@")

# Generic password/secret/token key=value pair. `\b` anchors the keyword so the
# engine doesn't restart the alternation at every character. The value class
# excludes `[` so we never re-match a `[REDACTED_*]` placeholder.
_PASSWORD_KV = re.compile(
    r"\b(password|passwd|pwd|secret|token|api_key|apikey|access_key)(\s*[:=]\s*)([^\s,;)\[\]}\"']+)",
    re.IGNORECASE,
)

# Email address.
_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Home-directory path: collapse `/Users/<name>/` or `/home/<name>/` to `~/`.
_HOME_PATH = re.compile(r"(?:/Users/|/home/)[^/\s]+/")


REDACTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Order matters: specific credentials before generic keyword matches; structural
    # patterns (private key blocks, JWTs, URLs) before keyword scrubbing that could
    # otherwise eat parts of them.
    (_PRIVATE_KEY, "[REDACTED_PRIVATE_KEY]"),
    (_GCP_PRIVATE_KEY_JSON, '"private_key": "[REDACTED_GCP_PRIVATE_KEY]"'),
    (_AWS_ACCESS_KEY, "[REDACTED_AWS_ACCESS_KEY]"),
    (_AWS_SECRET, r"\1[REDACTED_AWS_SECRET]"),
    (_JWT, "[REDACTED_JWT]"),
    (_BEARER, "Bearer [REDACTED_TOKEN]"),
    (_SNOWFLAKE_CONN, r"\1\2\3\4[REDACTED]"),
    (_URL_CREDS, r"\1[REDACTED_URL_CREDS]@"),
    (_PASSWORD_KV, r"\1\2[REDACTED]"),
    (_EMAIL, "[REDACTED_EMAIL]"),
    (_HOME_PATH, "~/"),
]


def redact(text: str) -> str:
    """Return ``text`` with PII / credentials replaced by stable placeholders.

    Idempotent: ``redact(redact(x)) == redact(x)``.
    """
    if not text:
        return text
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_message(exc: BaseException) -> str:
    """Apply :func:`redact` to ``str(exc)`` and return the scrubbed message."""
    return redact(str(exc))
