"""Validated-query cache for AgentXP v0.1 (§22.5 / B9 §1.7.3).

A query that has cleared the 5-layer safety pipeline and executed successfully
against the warehouse is cached by ``sha256(purpose|dialect|normalized_sql)``
under ``{project}/validated_queries/{cache_key}.yaml``. The cache anchor lets
the orchestrator skip re-running the safety pipeline + warehouse round-trip on
semantically-equivalent re-issues (same purpose + dialect + comment-stripped
SQL), and the on-disk YAML is the audit anchor for ``cache_hit`` query.executed
events.

Entries are chmod 600 (M83 / §1.7.3) and written atomically through
:func:`agentxp.audit.storage._atomic_write_bytes`. ``last_executed_at`` /
``execution_count`` are bumped on every hit via :func:`cache_update_hit`.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §22.5 (correction loop),
§1.7.3 (chmod 600 secrets policy), §1.8.5 (cache_hit subtype), M83 / B9 §1.7.3.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentxp.audit.storage import _atomic_write_bytes
from agentxp.schemas.state import _enforce_utc


# ──────────────────────────────────────────────────────────────────────────
# ValidatedQueryCacheEntry — the per-key YAML row.
# ──────────────────────────────────────────────────────────────────────────


class ValidatedQueryCacheEntry(BaseModel):
    """One row of ``{project}/validated_queries/{cache_key}.yaml`` (§22.5).

    ``sql_normalized`` is the canonical-form SQL (comments stripped, whitespace
    collapsed, keywords lowercased) used to compute the cache key.
    ``sql_original`` is what the proposer actually wrote — kept so the audit
    trail can show the human-readable form even after the cache is hit.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    cache_key: str = Field(..., min_length=64, max_length=64)
    purpose: str
    dialect: str
    sql_normalized: str
    sql_original: str
    first_executed_at: datetime
    last_executed_at: datetime
    execution_count: int = Field(default=1, ge=1)
    fact_sources_referenced: list[str] = Field(default_factory=list)

    @field_validator("first_executed_at", "last_executed_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return _enforce_utc(v)


# ──────────────────────────────────────────────────────────────────────────
# Normalisation — strip comments + whitespace + case so equivalent SQL hits.
# ──────────────────────────────────────────────────────────────────────────


# SQL keywords we lowercase in the normalised form. Closed set — adding new
# keywords doesn't invalidate existing cache keys for unrelated queries.
_SQL_KEYWORDS: frozenset[str] = frozenset({
    "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "HAVING", "LIMIT",
    "OFFSET", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "ON",
    "AS", "AND", "OR", "NOT", "IN", "IS", "NULL", "TRUE", "FALSE",
    "CASE", "WHEN", "THEN", "ELSE", "END", "WITH", "UNION", "ALL",
    "DISTINCT", "BETWEEN", "LIKE", "EXISTS", "CAST", "INT", "INTEGER",
})

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_WHITESPACE = re.compile(r"\s+")
_KEYWORD_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def normalize_sql_for_cache(sql: str) -> str:
    """Strip comments, collapse whitespace, lowercase keywords.

    Two queries with the same semantic shape but different formatting /
    comments / casing produce the same normalised string and therefore the
    same cache key. Concretely:

      * ``-- comment`` and ``/* block */`` runs are removed.
      * Runs of whitespace (incl. newlines / tabs) collapse to a single space.
      * Reserved keywords from :data:`_SQL_KEYWORDS` are lowercased; identifiers
        (table / column / alias names) keep their original case so
        ``users`` and ``Users`` remain distinct cache entries (the warehouse
        treats them differently depending on dialect; the cache stays
        conservative and does NOT collapse identifier case).
    """
    # 1. Strip block comments first (they may contain `--`).
    stripped = _BLOCK_COMMENT.sub(" ", sql)
    # 2. Strip line comments.
    stripped = _LINE_COMMENT.sub(" ", stripped)
    # 3. Lowercase keywords (identifiers preserved).
    def _maybe_lower(match: re.Match) -> str:
        word = match.group(0)
        if word.upper() in _SQL_KEYWORDS:
            return word.lower()
        return word

    stripped = _KEYWORD_WORD.sub(_maybe_lower, stripped)
    # 4. Collapse whitespace and trim.
    stripped = _WHITESPACE.sub(" ", stripped).strip()
    return stripped


def compute_cache_key(purpose: str, dialect: str, sql_normalized: str) -> str:
    """Return the 64-char hex sha256 of ``"{purpose}|{dialect}|{sql_normalized}"``.

    Deterministic across processes and across machines — the cache directory
    can be checked into a project repo (per §22.5 cross-session reuse) and
    keys remain stable.
    """
    payload = f"{purpose}|{dialect}|{sql_normalized}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# Read / write / update.
# ──────────────────────────────────────────────────────────────────────────


def _entry_path(cache_dir: Path, cache_key: str) -> Path:
    return cache_dir / f"{cache_key}.yaml"


def cache_lookup(
    cache_dir: Path, cache_key: str
) -> Optional[ValidatedQueryCacheEntry]:
    """Return the cached entry for ``cache_key`` or ``None`` on miss.

    Missing ``cache_dir`` is treated as a clean miss (fresh project — no
    cache directory yet). A malformed entry file raises through pydantic
    validation rather than being silently dropped.
    """
    if not cache_dir.is_dir():
        return None
    path = _entry_path(cache_dir, cache_key)
    if not path.exists():
        return None
    with open(path, "rb") as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return None
    return ValidatedQueryCacheEntry.model_validate(raw)


def cache_write(cache_dir: Path, entry: ValidatedQueryCacheEntry) -> Path:
    """Atomically write ``entry`` to ``cache_dir/{cache_key}.yaml`` (chmod 600).

    Auto-creates ``cache_dir``. Returns the absolute path written.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = _entry_path(cache_dir, entry.cache_key)
    payload = entry.model_dump(mode="json")
    data = yaml.safe_dump(payload, sort_keys=False).encode("utf-8")
    _atomic_write_bytes(target, data, mode=0o600)
    return target


def cache_update_hit(cache_dir: Path, cache_key: str) -> None:
    """Increment ``execution_count`` and bump ``last_executed_at`` on a hit.

    No-op if the entry is missing (the caller is expected to have done a
    :func:`cache_lookup` first; a race where the file was deleted between
    lookup and update is tolerated rather than raising).
    """
    entry = cache_lookup(cache_dir, cache_key)
    if entry is None:
        return
    updated = entry.model_copy(
        update={
            "execution_count": entry.execution_count + 1,
            "last_executed_at": datetime.now(timezone.utc),
        }
    )
    cache_write(cache_dir, updated)


__all__ = [
    "ValidatedQueryCacheEntry",
    "normalize_sql_for_cache",
    "compute_cache_key",
    "cache_lookup",
    "cache_write",
    "cache_update_hit",
]
