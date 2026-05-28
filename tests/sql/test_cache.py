"""Tests for agentxp.sql.cache.

Covers SQL normalisation (comment / whitespace / keyword stripping), sha256
cache-key determinism, and the on-disk read/write/update helpers under
``{project}/validated_queries/``.
"""
from __future__ import annotations

import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentxp.sql.cache import (
    ValidatedQueryCacheEntry,
    cache_lookup,
    cache_update_hit,
    cache_write,
    compute_cache_key,
    normalize_sql_for_cache,
)


# ──────────────────────────────────────────────────────────────────────────
# Normalisation
# ──────────────────────────────────────────────────────────────────────────


def test_normalize_strips_line_comments():
    sql = "SELECT 1 -- this is a comment\nFROM dual"
    assert "--" not in normalize_sql_for_cache(sql)
    assert "comment" not in normalize_sql_for_cache(sql)


def test_normalize_strips_block_comments():
    sql = "SELECT /* inline */ 1 FROM /* multi\nline */ dual"
    out = normalize_sql_for_cache(sql)
    assert "/*" not in out
    assert "*/" not in out
    assert "inline" not in out


def test_normalize_collapses_whitespace():
    sql = "SELECT   1\n\tFROM\n  dual"
    out = normalize_sql_for_cache(sql)
    assert "  " not in out  # no double-space
    assert "\n" not in out
    assert "\t" not in out


# ──────────────────────────────────────────────────────────────────────────
# Cache key
# ──────────────────────────────────────────────────────────────────────────


def test_compute_cache_key_is_deterministic():
    k1 = compute_cache_key("preview", "duckdb", "select 1 from dual")
    k2 = compute_cache_key("preview", "duckdb", "select 1 from dual")
    assert k1 == k2
    assert len(k1) == 64


def test_compute_cache_key_differs_by_purpose():
    k1 = compute_cache_key("preview", "duckdb", "select 1 from dual")
    k2 = compute_cache_key("profile", "duckdb", "select 1 from dual")
    assert k1 != k2


# ──────────────────────────────────────────────────────────────────────────
# Read / write / update
# ──────────────────────────────────────────────────────────────────────────


def _make_entry(cache_key: str = "a" * 64) -> ValidatedQueryCacheEntry:
    # Use an epoch-ish baseline so a real-time update_hit always lands later.
    now = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return ValidatedQueryCacheEntry(
        cache_key=cache_key,
        purpose="preview",
        dialect="duckdb",
        sql_normalized="select 1 from dual",
        sql_original="SELECT 1 FROM dual",
        first_executed_at=now,
        last_executed_at=now,
        execution_count=1,
        fact_sources_referenced=["users"],
    )


def test_cache_lookup_returns_none_on_miss(tmp_path: Path):
    assert cache_lookup(tmp_path, "deadbeef" * 8) is None


def test_cache_write_round_trip(tmp_path: Path):
    entry = _make_entry()
    written = cache_write(tmp_path, entry)
    assert written.exists()
    mode = stat.S_IMODE(written.stat().st_mode)
    assert mode == 0o600

    loaded = cache_lookup(tmp_path, entry.cache_key)
    assert loaded is not None
    assert loaded.cache_key == entry.cache_key
    assert loaded.execution_count == 1
    assert loaded.fact_sources_referenced == ["users"]


def test_cache_update_hit_increments_count(tmp_path: Path):
    entry = _make_entry()
    cache_write(tmp_path, entry)

    cache_update_hit(tmp_path, entry.cache_key)
    cache_update_hit(tmp_path, entry.cache_key)

    loaded = cache_lookup(tmp_path, entry.cache_key)
    assert loaded is not None
    assert loaded.execution_count == 3
    # last_executed_at should have advanced (or at least not be earlier).
    assert loaded.last_executed_at >= entry.first_executed_at
