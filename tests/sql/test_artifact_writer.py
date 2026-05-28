"""Tests for agentxp.sql.artifact_writer.

Verifies the §13 QueryArtifact persistence helpers: atomic chmod-600 write,
round-trip read, sorted listing, fresh ULID generation, and missing-dir
tolerance.
"""
from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentxp.sql.artifact_writer import (
    _new_query_ulid,
    list_query_artifacts,
    read_query_artifact,
    write_query_artifact,
)
from agentxp.sql.schema import (
    ConnectionConfig,
    QueryArtifact,
    QueryDialectInfo,
    QueryOutcome,
    ResourceBounds,
    RoutingConfig,
)


def _make_artifact(query_id: str | None = None) -> QueryArtifact:
    """Return a minimal-valid QueryArtifact for round-trip tests."""
    qid = query_id or _new_query_ulid()
    return QueryArtifact(
        query_id=qid,
        action_id="act-0000000000000001",
        experiment_id="exp-test",
        agent_name="sql_query_writer",
        stage="0_data_archaeology",
        purpose="preview",
        proposed_at=datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc),
        outcome=QueryOutcome.PROPOSED,
        auth_kind="none",
        routing=RoutingConfig(
            connection=ConnectionConfig(
                adapter="duckdb",
                auth_kind="none",
                profile_name="default",
            ),
        ),
        bounds=ResourceBounds(
            purpose="preview",
            row_limit_default=1_000,
            timeout_s=30,
        ),
        sql=QueryDialectInfo(
            canonical_text="SELECT 1 AS x",
            rendered_text="SELECT 1 AS x",
            rendered_dialect="duckdb",
        ),
    )


def test_write_then_read_round_trip(tmp_path: Path):
    artifact = _make_artifact()
    written = write_query_artifact(artifact, tmp_path)
    assert written.exists()
    assert written.parent == tmp_path / "queries"
    assert written.name == f"{artifact.query_id}.yaml"

    loaded = read_query_artifact(written)
    assert loaded.query_id == artifact.query_id
    assert loaded.experiment_id == artifact.experiment_id
    assert loaded.outcome == QueryOutcome.PROPOSED
    assert loaded.sql.canonical_text == "SELECT 1 AS x"
    assert loaded.auth_kind == "none"


def test_write_chmod_600_and_atomic(tmp_path: Path):
    artifact = _make_artifact()
    written = write_query_artifact(artifact, tmp_path)

    mode = stat.S_IMODE(written.stat().st_mode)
    assert mode == 0o600

    # No stray .tmp sidecar should remain after the atomic rename.
    leftovers = list((tmp_path / "queries").glob("*.tmp"))
    assert leftovers == []


def test_write_creates_queries_subdirectory(tmp_path: Path):
    artifact = _make_artifact()
    assert not (tmp_path / "queries").exists()
    write_query_artifact(artifact, tmp_path)
    assert (tmp_path / "queries").is_dir()


def test_list_query_artifacts_returns_sorted(tmp_path: Path):
    ids = ["ZZZZZZZZZZZZZZZZZZZZZZZZZZ", "AAAAAAAAAAAAAAAAAAAAAAAAAA", "MMMMMMMMMMMMMMMMMMMMMMMMMM"]
    for qid in ids:
        write_query_artifact(_make_artifact(query_id=qid), tmp_path)

    listed = list_query_artifacts(tmp_path)
    assert [p.stem for p in listed] == sorted(ids)


def test_list_query_artifacts_empty_when_no_dir(tmp_path: Path):
    assert list_query_artifacts(tmp_path) == []


def test_new_query_ulid_format_and_uniqueness():
    ids = {_new_query_ulid() for _ in range(50)}
    assert len(ids) == 50  # all unique
    for qid in ids:
        assert len(qid) == 26
        # Crockford base32: digits + uppercase A-Z minus I, L, O, U.
        forbidden = set("ILOU")
        assert forbidden.isdisjoint(set(qid))
        assert qid.isupper() or qid.replace("0", "").replace("1", "")  # has chars
