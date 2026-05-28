"""Seed a DuckDB database with the canonical ``checkout_events`` A/B table.

Loads ``checkout_events.csv`` (the single source of truth produced by
``generate_checkout_events.py``) into a DuckDB file so the Tier-B
cross-warehouse matrix can query an identical table on every warehouse.

EXECUTABLE LOCALLY: DuckDB is the only warehouse installed in this repo's
venv, so this seed is run as part of the build to prove the schema and load
path work. The Snowflake / BigQuery / Databricks seeds in this directory mirror
this exact schema but cannot be executed here (no cloud credentials).

Usage:
    .venv/bin/python sample-data/seeds/seed_duckdb.py [path/to/out.duckdb]

Default output: sample-data/seeds/checkout_events.duckdb
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).parent
CSV_PATH = HERE / "checkout_events.csv"

CREATE_SQL = """
CREATE OR REPLACE TABLE checkout_events (
    user_id      VARCHAR    NOT NULL,
    variant      VARCHAR    NOT NULL,   -- 'control' | 'treatment'
    assigned_at  TIMESTAMP  NOT NULL,
    converted    INTEGER    NOT NULL,   -- 0 | 1
    revenue      DOUBLE     NOT NULL,   -- USD, 0.0 if not converted
    event_ts     TIMESTAMP  NOT NULL
);
"""


def seed(db_path: Path) -> int:
    """Create the table, load the CSV, return the loaded row count."""
    con = duckdb.connect(str(db_path))
    try:
        con.execute(CREATE_SQL)
        con.execute(
            "INSERT INTO checkout_events "
            "SELECT user_id, variant, assigned_at, converted, revenue, event_ts "
            "FROM read_csv_auto(?, header=true)",
            [str(CSV_PATH)],
        )
        (n,) = con.execute("SELECT COUNT(*) FROM checkout_events").fetchone()
        return int(n)
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    db_path = Path(argv[0]) if argv else HERE / "checkout_events.duckdb"

    if not CSV_PATH.exists():
        print(
            f"Error: {CSV_PATH.name} not found. Run generate_checkout_events.py first.",
            file=sys.stderr,
        )
        return 1

    csv_rows = sum(1 for _ in CSV_PATH.open()) - 1  # minus header
    n = seed(db_path)
    print(f"Loaded {n} rows into checkout_events at {db_path}")
    print(f"CSV had {csv_rows} data rows -> {'MATCH' if n == csv_rows else 'MISMATCH'}")
    return 0 if n == csv_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
