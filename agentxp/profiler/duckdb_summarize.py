"""DuckDB ``SUMMARIZE`` adapter for the Stage-0 profiler (W_pre2.2).

Opens a fresh in-memory DuckDB connection, resolves ``source_ref`` (or
``file_path`` for parquet/csv/json/duckdb files), runs ``SUMMARIZE``, and
coalesces DuckDB's native column types into the 11-value ``DType`` literal
defined in :mod:`agentxp.schemas.profiler`. Output dicts are designed to feed
:func:`agentxp.profiler.heuristics.apply_hg_d4_heuristics` then
``ColumnProfile(**enriched)`` — that schema has ``extra="forbid"``, so this
module returns only the documented keys.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

# Defense-in-depth: this module runs orchestrator-internal on :memory: DuckDB.
# The §11 5-layer SQL safety pipeline gates the agentic SQL path (consistency_judge,
# sql_query_writer, sql_corrector). For qualified-name refs (.duckdb ATTACH, warehouse
# tables), _validate_qualified_name is the v0.1 floor.

__all__ = ["run_duckdb_summarize"]


# Exact-distinct cutoff. Above this, fall back to DuckDB's approx_unique.
_EXACT_DISTINCT_MAX_ROWS = 1_000_000

# Max characters per sample-value string (matches ColumnProfile docstring).
_SAMPLE_VALUE_TRUNCATE = 80


_QUALIFIED_NAME_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"
)
"""Unquoted dotted identifier: alphanumeric + underscore segments, dot-separated.

v0.1 scope: DuckDB ATTACH paths and the warehouse-table contract. Snowflake /
BigQuery have their own quoting conventions; W_sql layers adapter-specific
identifier quoting on top. ASCII-only.
"""


def _validate_qualified_name(source_ref: str) -> None:
    """Raise ValueError if source_ref is not a safe unquoted dotted identifier.

    Defense-in-depth: this function is the v0.1 floor for any caller that
    f-strings source_ref into a FROM clause. See §11 for the agentic SQL
    pipeline.
    """
    if not _QUALIFIED_NAME_RE.match(source_ref):
        raise ValueError(
            f"source_ref must be an unquoted dotted identifier "
            f"(ASCII letters, digits, underscores, dot-separated segments): "
            f"got {source_ref!r}. To profile a file, pass file_path instead."
        )


def _quote_ident(name: str) -> str:
    """Quote a DuckDB identifier; doubles any embedded ``"`` to block injection."""
    return '"' + name.replace('"', '""') + '"'


def _coalesce_dtype(duckdb_type: str) -> str:
    """Map a raw DuckDB column type string to the 11-value ``DType`` literal."""
    t = duckdb_type.upper().strip()
    # DECIMAL(p,s) and similar parameterized types — strip the parens for matching.
    base = t.split("(", 1)[0].strip()

    if base in {
        "BIGINT",
        "INTEGER",
        "INT",
        "SMALLINT",
        "TINYINT",
        "HUGEINT",
        "UBIGINT",
        "UINTEGER",
        "USMALLINT",
        "UTINYINT",
        "INT2",
        "INT4",
        "INT8",
    }:
        return "integer"
    if base in {"DOUBLE", "REAL", "FLOAT", "DECIMAL", "NUMERIC"}:
        return "float"
    if base == "BOOLEAN" or base == "BOOL":
        return "boolean"
    if base in {"VARCHAR", "TEXT", "STRING", "CHAR"}:
        return "string"
    # TIMESTAMP, TIMESTAMP_NS, TIMESTAMPTZ, "TIMESTAMP WITH TIME ZONE" all begin TIMESTAMP.
    if base.startswith("TIMESTAMP"):
        return "timestamp"
    if base == "DATE":
        return "date"
    if base == "TIME":
        return "time"
    if base == "INTERVAL":
        return "interval"
    if base == "JSON":
        return "json"
    if base in {"BLOB", "BINARY", "BYTEA", "VARBINARY"}:
        return "binary"
    return "unknown"


def _to_float_or_none(v: Any) -> Optional[float]:
    """Coerce a SUMMARIZE numeric cell (Decimal / str / None) to ``float`` or ``None``."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v))
    except (ValueError, TypeError):
        return None


def _parse_null_pct(v: Any) -> float:
    """Convert the SUMMARIZE ``null_percentage`` cell into a ``[0, 1]`` rate.

    DuckDB has shipped this as ``Decimal``, ``float``, and ``"15.2%"`` strings
    across versions; we accept all three.
    """
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v) / 100.0
    if isinstance(v, (int, float)):
        return float(v) / 100.0
    s = str(v).strip().rstrip("%").strip()
    try:
        return float(s) / 100.0
    except ValueError:
        return 0.0


def _build_source_clause(
    source_ref: str, file_path: Optional[Path], con: Any
) -> str:
    """Return the SQL fragment to use after ``FROM`` for the source.

    Side-effect: may ``ATTACH`` a ``.duckdb`` file onto ``con``.
    """
    if file_path is None:
        # source_ref is already a qualified, attached table name.
        _validate_qualified_name(source_ref)
        return source_ref

    p = Path(file_path)
    suffix = p.suffix.lower()
    path_str = str(p).replace("'", "''")

    if suffix == ".parquet":
        return f"read_parquet('{path_str}')"
    if suffix in {".csv", ".tsv"}:
        return f"read_csv_auto('{path_str}')"
    if suffix in {".json", ".jsonl", ".ndjson"}:
        return f"read_json_auto('{path_str}')"
    if suffix == ".duckdb":
        # source_ref is the qualified table name inside the attached db; validate
        # *before* ATTACH so a bad ref never touches DuckDB.
        _validate_qualified_name(source_ref)
        con.execute(f"ATTACH '{path_str}' AS src (READ_ONLY)")
        return source_ref
    # Unknown extension — fall back to read_csv_auto and let DuckDB decide.
    return f"read_csv_auto('{path_str}')"


def run_duckdb_summarize(
    source_ref: str,
    *,
    file_path: Optional[Path] = None,
    sample_values_n: int = 10,
) -> dict[str, Any]:
    """Run DuckDB ``SUMMARIZE`` against ``source_ref`` and return raw column stats.

    Returns:
        ``{"row_count": int, "columns": [ {name, dtype, null_rate, ...}, ... ]}``
        — keys constrained to the ``ColumnProfile`` schema (``extra="forbid"``).
    """
    import duckdb  # local import keeps the optional dep out of module load

    con = duckdb.connect(":memory:")
    try:
        from_clause = _build_source_clause(source_ref, file_path, con)
        ref = from_clause  # everything below is interpolated *after* FROM

        row_count = int(con.execute(f"SELECT COUNT(*) FROM {ref}").fetchone()[0])

        summarize_res = con.execute(f"SUMMARIZE SELECT * FROM {ref}")
        col_names = [d[0] for d in summarize_res.description]
        rows = summarize_res.fetchall()
        idx = {c: i for i, c in enumerate(col_names)}

        out_columns: list[dict[str, Any]] = []
        for r in rows:
            name: str = r[idx["column_name"]]
            duckdb_type: str = r[idx["column_type"]]
            dtype = _coalesce_dtype(duckdb_type)
            qname = _quote_ident(name)

            null_rate = 0.0 if row_count == 0 else _parse_null_pct(r[idx["null_percentage"]])
            null_rate = max(0.0, min(1.0, null_rate))

            approx_unique = r[idx["approx_unique"]]
            try:
                approx_int = int(approx_unique) if approx_unique is not None else None
            except (ValueError, TypeError):
                approx_int = None

            if row_count <= _EXACT_DISTINCT_MAX_ROWS:
                try:
                    exact = con.execute(
                        f"SELECT COUNT(DISTINCT {qname}) FROM {ref}"
                    ).fetchone()[0]
                    distinct_count = int(exact)
                    distinct_count_is_approx = False
                except Exception:
                    # Fail soft: keep approx if the exact query bombs (e.g., type that
                    # can't be hashed). The whole profile shouldn't die over one column.
                    distinct_count = approx_int
                    distinct_count_is_approx = approx_int is not None
            else:
                distinct_count = approx_int
                distinct_count_is_approx = approx_int is not None

            min_raw = r[idx["min"]]
            max_raw = r[idx["max"]]
            min_value = None if min_raw is None else str(min_raw)
            max_value = None if max_raw is None else str(max_raw)

            q25 = q50 = q75 = mean = stddev = None
            if dtype in ("integer", "float"):
                q25 = _to_float_or_none(r[idx["q25"]])
                q50 = _to_float_or_none(r[idx["q50"]])
                q75 = _to_float_or_none(r[idx["q75"]])
                mean = _to_float_or_none(r[idx["avg"]])
                stddev = _to_float_or_none(r[idx["std"]])

            min_length: Optional[int] = None
            max_length: Optional[int] = None
            if dtype == "string":
                try:
                    lr = con.execute(
                        f"SELECT MIN(LENGTH({qname})), MAX(LENGTH({qname})) FROM {ref}"
                    ).fetchone()
                    if lr is not None:
                        min_length = None if lr[0] is None else int(lr[0])
                        max_length = None if lr[1] is None else int(lr[1])
                except Exception:
                    # Fail soft on length stats — keep the column row.
                    pass

            sample_values: list[str] = []
            if sample_values_n > 0:
                try:
                    sv_rows = con.execute(
                        f"SELECT DISTINCT CAST({qname} AS VARCHAR) FROM {ref} "
                        f"WHERE {qname} IS NOT NULL "
                        f"USING SAMPLE {int(sample_values_n)} ROWS"
                    ).fetchall()
                    for (val,) in sv_rows:
                        if val is None:
                            continue
                        sv = str(val)
                        if len(sv) > _SAMPLE_VALUE_TRUNCATE:
                            sv = sv[:_SAMPLE_VALUE_TRUNCATE]
                        sample_values.append(sv)
                except Exception:
                    # Fail soft on sampling — keep the column row, just no samples.
                    pass

            out_columns.append(
                {
                    "name": name,
                    "dtype": dtype,
                    "null_rate": null_rate,
                    "distinct_count": distinct_count,
                    "distinct_count_is_approx": distinct_count_is_approx,
                    "min_value": min_value,
                    "max_value": max_value,
                    "q25": q25,
                    "q50": q50,
                    "q75": q75,
                    "mean": mean,
                    "stddev": stddev,
                    "min_length": min_length,
                    "max_length": max_length,
                    "sample_values": sample_values,
                }
            )

        return {"row_count": row_count, "columns": out_columns}
    finally:
        con.close()
