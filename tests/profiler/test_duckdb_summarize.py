"""Tests for agentxp.profiler.duckdb_summarize — W_pre2.2."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from agentxp.profiler.duckdb_summarize import (
    _validate_qualified_name,
    run_duckdb_summarize,
)
from agentxp.schemas.profiler import ColumnProfile


def _write_parquet(path: Path, sql: str) -> None:
    con = duckdb.connect(":memory:")
    try:
        path_str = str(path).replace("'", "''")
        con.execute(f"COPY ({sql}) TO '{path_str}' (FORMAT 'parquet')")
    finally:
        con.close()


def _write_csv(path: Path, sql: str) -> None:
    con = duckdb.connect(":memory:")
    try:
        path_str = str(path).replace("'", "''")
        con.execute(f"COPY ({sql}) TO '{path_str}' (FORMAT 'csv', HEADER)")
    finally:
        con.close()


def test_summarize_parquet_happy_path(tmp_path: Path) -> None:
    p = tmp_path / "happy.parquet"
    _write_parquet(
        p,
        """
        SELECT
            i::BIGINT AS user_id,
            ('val_' || i)::VARCHAR AS label,
            (i * 1.5)::DOUBLE AS score,
            (TIMESTAMP '2024-01-01' + INTERVAL (i) DAY) AS event_ts
        FROM range(100) tbl(i)
        """,
    )

    out = run_duckdb_summarize("ignored", file_path=p)
    assert out["row_count"] == 100
    assert len(out["columns"]) == 4
    by_name = {c["name"]: c for c in out["columns"]}
    assert by_name["user_id"]["dtype"] == "integer"
    assert by_name["label"]["dtype"] == "string"
    assert by_name["score"]["dtype"] == "float"
    assert by_name["event_ts"]["dtype"] == "timestamp"
    for c in out["columns"]:
        assert c["null_rate"] == 0.0
        # Each column dict must be valid input to ColumnProfile.
        ColumnProfile(**c)


def test_summarize_csv(tmp_path: Path) -> None:
    p = tmp_path / "happy.csv"
    _write_csv(
        p,
        """
        SELECT i::BIGINT AS user_id, ('s_' || i)::VARCHAR AS label
        FROM range(20) tbl(i)
        """,
    )

    out = run_duckdb_summarize("ignored", file_path=p)
    assert out["row_count"] == 20
    by_name = {c["name"]: c for c in out["columns"]}
    assert by_name["user_id"]["dtype"] == "integer"
    assert by_name["label"]["dtype"] == "string"


def test_null_rate_computation(tmp_path: Path) -> None:
    p = tmp_path / "nulls.parquet"
    _write_parquet(
        p,
        """
        SELECT
            i::BIGINT AS row_id,
            CASE WHEN i % 2 = 0 THEN NULL ELSE ('v_' || i)::VARCHAR END AS maybe
        FROM range(100) tbl(i)
        """,
    )

    out = run_duckdb_summarize("ignored", file_path=p)
    by_name = {c["name"]: c for c in out["columns"]}
    assert out["row_count"] == 100
    assert by_name["maybe"]["null_rate"] == pytest.approx(0.5, abs=1e-9)
    assert by_name["row_id"]["null_rate"] == 0.0


def test_distinct_count_exact_under_1m(tmp_path: Path) -> None:
    p = tmp_path / "distinct.parquet"
    _write_parquet(p, "SELECT i::BIGINT AS user_id FROM range(100) tbl(i)")

    out = run_duckdb_summarize("ignored", file_path=p)
    col = out["columns"][0]
    assert col["distinct_count"] == 100
    assert col["distinct_count_is_approx"] is False


def test_string_length_stats(tmp_path: Path) -> None:
    p = tmp_path / "lengths.parquet"
    _write_parquet(
        p,
        """
        SELECT
            i::BIGINT AS user_id,
            repeat('x', (i + 1)::INTEGER)::VARCHAR AS label
        FROM range(10) tbl(i)
        """,
    )

    out = run_duckdb_summarize("ignored", file_path=p)
    by_name = {c["name"]: c for c in out["columns"]}
    assert by_name["label"]["min_length"] == 1
    assert by_name["label"]["max_length"] == 10
    assert by_name["user_id"]["min_length"] is None
    assert by_name["user_id"]["max_length"] is None


def test_numeric_quartiles_populated(tmp_path: Path) -> None:
    p = tmp_path / "quart.parquet"
    _write_parquet(
        p,
        """
        SELECT
            i::BIGINT AS user_id,
            ('v_' || i)::VARCHAR AS label
        FROM range(100) tbl(i)
        """,
    )

    out = run_duckdb_summarize("ignored", file_path=p)
    by_name = {c["name"]: c for c in out["columns"]}
    uid = by_name["user_id"]
    assert uid["q25"] is not None
    assert uid["q50"] is not None
    assert uid["q75"] is not None
    assert uid["mean"] is not None
    assert uid["stddev"] is not None
    label = by_name["label"]
    assert label["q25"] is None
    assert label["q50"] is None
    assert label["q75"] is None
    assert label["mean"] is None
    assert label["stddev"] is None


def test_dtype_coalescing(tmp_path: Path) -> None:
    p = tmp_path / "types.parquet"
    _write_parquet(
        p,
        """
        SELECT
            1::BIGINT AS a_bigint,
            1.5::DOUBLE AS a_double,
            TRUE::BOOLEAN AS a_bool,
            'x'::VARCHAR AS a_str,
            TIMESTAMP '2024-01-01 00:00:00' AS a_ts
        """,
    )

    out = run_duckdb_summarize("ignored", file_path=p)
    by_name = {c["name"]: c["dtype"] for c in out["columns"]}
    assert by_name["a_bigint"] == "integer"
    assert by_name["a_double"] == "float"
    assert by_name["a_bool"] == "boolean"
    assert by_name["a_str"] == "string"
    assert by_name["a_ts"] == "timestamp"


def test_sample_values_truncated_to_80_chars(tmp_path: Path) -> None:
    p = tmp_path / "long.parquet"
    _write_parquet(
        p,
        """
        SELECT repeat('a', 200)::VARCHAR AS big_str
        """,
    )

    out = run_duckdb_summarize("ignored", file_path=p, sample_values_n=5)
    col = out["columns"][0]
    assert col["sample_values"], "expected at least one sampled value"
    for sv in col["sample_values"]:
        assert len(sv) <= 80


def test_column_name_with_double_quote_handled(tmp_path: Path) -> None:
    p = tmp_path / "weird.parquet"
    con = duckdb.connect(":memory:")
    try:
        path_str = str(p).replace("'", "''")
        # Column literally named: weird"name
        con.execute(
            "CREATE TABLE t (\"weird\"\"name\" INTEGER, ok_col VARCHAR)"
        )
        con.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c')")
        con.execute(f"COPY t TO '{path_str}' (FORMAT 'parquet')")
    finally:
        con.close()

    out = run_duckdb_summarize("ignored", file_path=p)
    names = {c["name"] for c in out["columns"]}
    assert 'weird"name' in names
    by_name = {c["name"]: c for c in out["columns"]}
    weird = by_name['weird"name']
    assert weird["dtype"] == "integer"
    assert weird["distinct_count"] == 3
    # Final shape validates against ColumnProfile.
    ColumnProfile(**weird)


def test_summarize_attached_table_via_source_ref() -> None:
    """When file_path is None, source_ref must be a qualified attached name.

    Verifies the path through ``_build_source_clause`` that just returns the ref.
    """
    # Pre-stage a duckdb file, then point at it through file_path=.duckdb.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        ddb_path = Path(td) / "store.duckdb"
        con = duckdb.connect(str(ddb_path))
        try:
            con.execute(
                "CREATE TABLE evt AS SELECT i::BIGINT AS uid FROM range(5) t(i)"
            )
        finally:
            con.close()

        out = run_duckdb_summarize(
            "src.evt",
            file_path=ddb_path,
        )
        assert out["row_count"] == 5
        assert out["columns"][0]["name"] == "uid"


# ---------------------------------------------------------------------------
# W_pre2 Hotfix-2: identifier regex gate
# ---------------------------------------------------------------------------


def test_validate_qualified_name_accepts_unquoted_dotted() -> None:
    # Each of these must pass silently.
    _validate_qualified_name("src.events")
    _validate_qualified_name("my_table")
    _validate_qualified_name("db.schema.table")
    _validate_qualified_name("_underscore_lead")


def test_validate_qualified_name_rejects_semicolon() -> None:
    with pytest.raises(ValueError):
        _validate_qualified_name("events; DROP TABLE x")


def test_validate_qualified_name_rejects_quote() -> None:
    with pytest.raises(ValueError):
        _validate_qualified_name('events"; DROP')


def test_validate_qualified_name_rejects_space() -> None:
    with pytest.raises(ValueError):
        _validate_qualified_name("my table")


def test_validate_qualified_name_rejects_hyphen() -> None:
    with pytest.raises(ValueError):
        _validate_qualified_name("my-table")


def test_validate_qualified_name_rejects_paren() -> None:
    with pytest.raises(ValueError):
        _validate_qualified_name("events(1)")


def test_validate_qualified_name_rejects_leading_digit() -> None:
    with pytest.raises(ValueError):
        _validate_qualified_name("1events")


def test_validate_qualified_name_rejects_double_dot() -> None:
    with pytest.raises(ValueError):
        _validate_qualified_name("a..b")


def test_validate_qualified_name_rejects_trailing_dot() -> None:
    with pytest.raises(ValueError):
        _validate_qualified_name("a.b.")


def test_validate_qualified_name_rejects_empty() -> None:
    with pytest.raises(ValueError):
        _validate_qualified_name("")


def test_run_duckdb_summarize_rejects_injection_via_source_ref() -> None:
    with pytest.raises(ValueError):
        run_duckdb_summarize("events; DROP TABLE x", file_path=None)


def test_run_duckdb_summarize_rejects_injection_via_duckdb_ref(tmp_path: Path) -> None:
    # Real .duckdb file so the branch is exercised; validator must fire before ATTACH.
    ddb_path = tmp_path / "store.duckdb"
    con = duckdb.connect(str(ddb_path))
    try:
        con.execute("CREATE TABLE evt AS SELECT 1::BIGINT AS uid")
    finally:
        con.close()

    with pytest.raises(ValueError):
        run_duckdb_summarize('src"; DROP', file_path=ddb_path)
