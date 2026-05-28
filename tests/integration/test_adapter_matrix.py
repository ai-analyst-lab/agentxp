"""Tier-B cross-warehouse integration matrix (W3) — 10 query shapes × 4 adapters.

The capstone of the v0.1.1 adapter build: a single parametrized matrix that
authors each canonical query ONCE in the DuckDB dialect, transpiles it
per-target via :func:`agentxp.sql.transpiler.transpile`, and executes it on
every registered adapter. 10 shapes × 4 adapters = 40 logical cells.

Gating (so CI stays green with ZERO credentials):

* The whole module is ``@pytest.mark.integration``.
* **DuckDB always runs** — it is credential-free (in-memory) and is the proof
  the harness works: its cells assert concrete golden values computed from the
  seed CSV (``sample-data/seeds/checkout_events.csv``, 5000 rows).
* **Snowflake / BigQuery / Databricks cells skip per-cell** (NOT at module
  level — the module must still run DuckDB) when either the driver is not
  importable OR the required connection env vars are absent. The env-var names
  and driver module names mirror the per-warehouse live tests
  (``test_snowflake_live.py``, ``test_bigquery_live.py``,
  ``test_databricks_live.py``) exactly.

With no creds: 10 DuckDB cells PASS, the other 30 SKIP, 0 FAIL.

NOTE on assertions (acceptance criterion #4): there are NO cross-adapter
equality assertions that can never fire. Each running cell is asserted against
the known-correct golden value FOR ITS DIALECT. Where a dialect genuinely
differs (e.g. Snowflake upper-cases unquoted identifiers), the per-dialect
expected value is selected and the quirk is documented inline.
"""
from __future__ import annotations

import csv
import importlib.util
import os
from pathlib import Path

import pytest

from agentxp.sql.adapter import AdapterResult
from agentxp.sql.adapters import ADAPTER_REGISTRY
from agentxp.sql.adapters.duckdb_adapter import DuckDBAdapter
from agentxp.sql.transpiler import transpile

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------
# Seed data — the canonical checkout_events A/B table (5000 rows).
# --------------------------------------------------------------------------

_SEED_CSV = (
    Path(__file__).resolve().parents[2]
    / "sample-data"
    / "seeds"
    / "checkout_events.csv"
)


def _seed_goldens() -> dict[str, int | float]:
    """Compute the concrete golden values from the seed CSV in pure Python.

    Read once so the DuckDB cells assert real, deterministic numbers rather
    than re-deriving expectations from the same engine under test. Columns:
    user_id, variant, assigned_at, converted, revenue, event_ts.
    """
    total = 0
    converted = 0
    by_variant: dict[str, int] = {}
    with _SEED_CSV.open(newline="") as fh:
        for r in csv.DictReader(fh):
            total += 1
            converted += int(r["converted"])
            by_variant[r["variant"]] = by_variant.get(r["variant"], 0) + 1
    return {
        "total": total,
        "converted": converted,
        "n_variants": len(by_variant),
        "variants": by_variant,
    }


_GOLDEN = _seed_goldens()


# --------------------------------------------------------------------------
# The 10 canonical query shapes — authored ONCE in the duckdb dialect.
# --------------------------------------------------------------------------
#
# Each entry: (id, canonical_sql, golden_fn). ``golden_fn(dialect)`` returns
# an assertion callable ``(AdapterResult) -> None`` selecting the per-dialect
# correct expected value. Shapes 4–10 reference ``checkout_events``.


def _q01_literal_int() -> str:
    return "SELECT 1 AS x"


def _q02_literal_string() -> str:
    return "SELECT 'alice' AS name"


def _q03_multi_column() -> str:
    return "SELECT 1 AS a, 2 AS b, 3 AS c"


def _q04_filter() -> str:
    return (
        "SELECT user_id, variant FROM checkout_events "
        "WHERE variant = 'treatment' AND converted = 1"
    )


def _q05_count() -> str:
    return "SELECT COUNT(*) AS n FROM checkout_events"


def _q06_group_by() -> str:
    return (
        "SELECT variant, COUNT(*) AS n FROM checkout_events "
        "GROUP BY variant ORDER BY variant"
    )


def _q07_order_limit() -> str:
    return (
        "SELECT user_id, revenue FROM checkout_events "
        "ORDER BY revenue DESC, user_id ASC LIMIT 5"
    )


def _q08_distinct() -> str:
    return "SELECT DISTINCT variant FROM checkout_events ORDER BY variant"


def _q09_case() -> str:
    return (
        "SELECT CASE WHEN converted = 1 THEN 'yes' ELSE 'no' END AS did_convert, "
        "COUNT(*) AS n FROM checkout_events "
        "GROUP BY did_convert ORDER BY did_convert"
    )


def _q10_cte() -> str:
    return (
        "WITH per_variant AS ("
        "  SELECT variant, COUNT(*) AS n, SUM(converted) AS conversions "
        "  FROM checkout_events GROUP BY variant"
        ") SELECT variant, n, conversions FROM per_variant ORDER BY variant"
    )


def _col(row: dict, name: str):
    """Fetch a column case-insensitively.

    QUIRK: Snowflake upper-cases unquoted identifiers in result keys (``X``,
    ``NAME``), while DuckDB / BigQuery / Databricks preserve the lower-case
    alias. We assert the VALUE is correct regardless of the key's case rather
    than baking a dialect-specific key into every assertion.
    """
    if name in row:
        return row[name]
    upper = name.upper()
    if upper in row:
        return row[upper]
    # Last resort: single-column rows — return the only value.
    if len(row) == 1:
        return next(iter(row.values()))
    raise KeyError(f"column {name!r} not in row keys {list(row)}")


# Each checker takes (result: AdapterResult, dialect: str) and asserts the
# per-dialect golden. Defined against the concrete seed-derived numbers.

def _check_q01(r: AdapterResult, dialect: str) -> None:
    assert r.row_count == 1
    assert _col(r.rows[0], "x") == 1


def _check_q02(r: AdapterResult, dialect: str) -> None:
    assert r.row_count == 1
    assert _col(r.rows[0], "name") == "alice"


def _check_q03(r: AdapterResult, dialect: str) -> None:
    assert r.row_count == 1
    row = r.rows[0]
    assert (_col(row, "a"), _col(row, "b"), _col(row, "c")) == (1, 2, 3)


def _check_q04(r: AdapterResult, dialect: str) -> None:
    # Filtered rows; every returned row must satisfy the predicate. Row count
    # is bounded by max_rows in the test, so assert the shape not an exact n.
    assert r.row_count >= 1
    for row in r.rows:
        assert _col(row, "variant") == "treatment"


def _check_q05(r: AdapterResult, dialect: str) -> None:
    assert r.row_count == 1
    assert int(_col(r.rows[0], "n")) == _GOLDEN["total"]  # 5000


def _check_q06(r: AdapterResult, dialect: str) -> None:
    assert r.row_count == _GOLDEN["n_variants"]
    got = {_col(row, "variant"): int(_col(row, "n")) for row in r.rows}
    assert got == _GOLDEN["variants"]


def _check_q07(r: AdapterResult, dialect: str) -> None:
    assert r.row_count == 5
    revenues = [float(_col(row, "revenue")) for row in r.rows]
    assert revenues == sorted(revenues, reverse=True)  # ORDER BY ... DESC


def _check_q08(r: AdapterResult, dialect: str) -> None:
    variants = [_col(row, "variant") for row in r.rows]
    assert variants == sorted(set(_GOLDEN["variants"]))


def _check_q09(r: AdapterResult, dialect: str) -> None:
    # Two buckets: 'no' (not converted) and 'yes' (converted).
    got = {_col(row, "did_convert"): int(_col(row, "n")) for row in r.rows}
    assert got["yes"] == _GOLDEN["converted"]
    assert got["no"] == _GOLDEN["total"] - _GOLDEN["converted"]


def _check_q10(r: AdapterResult, dialect: str) -> None:
    assert r.row_count == _GOLDEN["n_variants"]
    got_n = {_col(row, "variant"): int(_col(row, "n")) for row in r.rows}
    assert got_n == _GOLDEN["variants"]
    total_conversions = sum(int(_col(row, "conversions")) for row in r.rows)
    assert total_conversions == _GOLDEN["converted"]


# (id, sql_factory, checker, max_rows). max_rows bounds the unbounded filter
# scan so the matrix never materialises thousands of rows.
QUERY_SHAPES = [
    ("q01_literal_int", _q01_literal_int, _check_q01, 10_000),
    ("q02_literal_string", _q02_literal_string, _check_q02, 10_000),
    ("q03_multi_column", _q03_multi_column, _check_q03, 10_000),
    ("q04_filter", _q04_filter, _check_q04, 50),
    ("q05_count", _q05_count, _check_q05, 10_000),
    ("q06_group_by", _q06_group_by, _check_q06, 10_000),
    ("q07_order_limit", _q07_order_limit, _check_q07, 10_000),
    ("q08_distinct", _q08_distinct, _check_q08, 10_000),
    ("q09_case", _q09_case, _check_q09, 10_000),
    ("q10_cte", _q10_cte, _check_q10, 10_000),
]

_QUERY_IDS = [shape[0] for shape in QUERY_SHAPES]
_DIALECTS = ("duckdb", "snowflake", "bigquery", "databricks")


# --------------------------------------------------------------------------
# Per-adapter credential gating — mirrors the per-warehouse live tests.
# --------------------------------------------------------------------------


def _importable(module: str) -> bool:
    """True if ``module`` (and its parent packages) is importable.

    ``find_spec`` raises ModuleNotFoundError when a *parent* package is missing
    (e.g. ``google`` for ``google.cloud.bigquery``), so guard it rather than
    relying on a ``None`` return — same idiom as ``test_bigquery_live.py``.
    """
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def _snowflake_missing() -> list[str]:
    required = (
        "AGENTXP_SNOWFLAKE_ACCOUNT",
        "AGENTXP_SNOWFLAKE_USER",
        "AGENTXP_SNOWFLAKE_PASSWORD",
        "AGENTXP_SNOWFLAKE_WAREHOUSE",
        "AGENTXP_SNOWFLAKE_DATABASE",
    )
    return [k for k in required if not os.environ.get(k)]


def _bigquery_missing() -> list[str]:
    # BigQuery uses ADC + an explicit project; the project env var is the
    # unambiguous "is this configured" signal (matches test_bigquery_live.py).
    if not os.environ.get("AGENTXP_BQ_PROJECT"):
        return ["AGENTXP_BQ_PROJECT"]
    return []


def _databricks_missing() -> list[str]:
    required = (
        "DATABRICKS_SERVER_HOSTNAME",
        "DATABRICKS_HTTP_PATH",
        "DATABRICKS_ACCESS_TOKEN",
    )
    return [k for k in required if not os.environ.get(k)]


def _gate(dialect: str) -> None:
    """pytest.skip the current cell if ``dialect``'s driver/creds are absent.

    DuckDB is never gated — it is credential-free and always runs.
    """
    if dialect == "duckdb":
        return
    if dialect == "snowflake":
        if not _importable("snowflake.connector"):
            pytest.skip("snowflake-connector-python not installed")
        missing = _snowflake_missing()
        if missing:
            pytest.skip(f"Snowflake live creds unset: missing {missing}")
    elif dialect == "bigquery":
        if not _importable("google.cloud.bigquery"):
            pytest.skip("google-cloud-bigquery not installed")
        missing = _bigquery_missing()
        if missing:
            pytest.skip(f"BigQuery creds/project unset: missing {missing}")
    elif dialect == "databricks":
        if not _importable("databricks.sql"):
            pytest.skip("databricks-sql-connector not installed")
        missing = _databricks_missing()
        if missing:
            pytest.skip(f"Databricks live creds unset: missing {missing}")
    else:  # pragma: no cover — defensive
        pytest.skip(f"unknown dialect {dialect!r}")


def _make_adapter(dialect: str):
    """Construct a connected-ready adapter for ``dialect`` from env.

    Only called AFTER ``_gate`` has confirmed creds exist, so the warehouse
    branches never run without credentials.
    """
    if dialect == "duckdb":
        return _seeded_duckdb_adapter()
    if dialect == "snowflake":
        cls = ADAPTER_REGISTRY["snowflake"]
        return cls(
            account=os.environ["AGENTXP_SNOWFLAKE_ACCOUNT"],
            user=os.environ["AGENTXP_SNOWFLAKE_USER"],
            password=os.environ["AGENTXP_SNOWFLAKE_PASSWORD"],
            warehouse=os.environ["AGENTXP_SNOWFLAKE_WAREHOUSE"],
            database=os.environ["AGENTXP_SNOWFLAKE_DATABASE"],
            schema=os.environ.get("AGENTXP_SNOWFLAKE_SCHEMA", "PUBLIC"),
        )
    if dialect == "bigquery":
        cls = ADAPTER_REGISTRY["bigquery"]
        return cls(project=os.environ["AGENTXP_BQ_PROJECT"])
    if dialect == "databricks":
        cls = ADAPTER_REGISTRY["databricks"]
        kwargs = dict(
            server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
            http_path=os.environ["DATABRICKS_HTTP_PATH"],
            access_token=os.environ["DATABRICKS_ACCESS_TOKEN"],
        )
        if os.environ.get("DATABRICKS_CATALOG"):
            kwargs["catalog"] = os.environ["DATABRICKS_CATALOG"]
        if os.environ.get("DATABRICKS_SCHEMA"):
            kwargs["schema"] = os.environ["DATABRICKS_SCHEMA"]
        return cls(**kwargs)
    raise AssertionError(f"unknown dialect {dialect!r}")  # pragma: no cover


def _seeded_duckdb_adapter() -> DuckDBAdapter:
    """In-memory DuckDB adapter with ``checkout_events`` loaded from the CSV.

    Loads via DuckDB's ``read_csv_auto`` against the same seed CSV the
    cross-warehouse seeds mirror, so the table-scan shapes (q04–q10) have the
    full 5000-row dataset behind them.
    """
    adapter = DuckDBAdapter(file_path=None)  # in-memory, lazy connect, no creds
    conn = adapter._connect()
    conn.execute(
        "CREATE OR REPLACE TABLE checkout_events AS "
        "SELECT user_id, variant, assigned_at, converted, revenue, event_ts "
        "FROM read_csv_auto(?, header=true)",
        [str(_SEED_CSV)],
    )
    return adapter


@pytest.fixture
def adapter(request):
    """Build (and tear down) the adapter for the parametrized ``dialect``.

    Skips the cell first if the warehouse driver/creds are missing; DuckDB
    always proceeds. The fixture is parametrized indirectly from the test.
    """
    dialect = request.param
    _gate(dialect)
    a = _make_adapter(dialect)
    try:
        yield a
    finally:
        a.close()


# --------------------------------------------------------------------------
# The matrix: 10 query shapes × 4 adapters = 40 cells.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("adapter", _DIALECTS, indirect=True, ids=_DIALECTS)
@pytest.mark.parametrize(
    "shape",
    QUERY_SHAPES,
    ids=_QUERY_IDS,
)
def test_matrix(adapter, shape):
    """Author once in duckdb, transpile to the target dialect, execute, assert.

    DuckDB cells assert concrete seed-derived golden values (the proof the
    harness works with zero creds). Warehouse cells skip cleanly unless their
    driver + creds are present, then assert the same per-dialect goldens.
    """
    _shape_id, sql_factory, checker, max_rows = shape
    dialect = adapter.get_dialect()

    canonical_sql = sql_factory()
    target_sql = transpile(canonical_sql, "duckdb", dialect)

    result = adapter.execute(target_sql, max_rows=max_rows)

    assert isinstance(result, AdapterResult)
    assert result.dialect == dialect
    checker(result, dialect)
