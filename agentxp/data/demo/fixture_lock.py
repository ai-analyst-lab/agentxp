"""fixture.lock.yaml writer + verifier (T32).

The fixture lock is a per-table sha256 of the sorted-rows JSON. This
captures the *logical content* of the warehouse — not the DuckDB page
layout. Two warehouses built from the same MASTER_SEED + FIXTURE_VERSION
produce identical lock files; if a regeneration produces a different
lock, either the generator changed or the seed contract was violated.

Lock shape (YAML):

    fixture_version: 1
    master_seed: 2849358713
    generated_at: 2026-06-04T...
    tables:
      experiments:
        sha256: <64 hex chars>
        row_count: 8
      assignments:
        ...

Run:
    python -m agentxp.data.demo.fixture_lock --write [--db PATH] [--out PATH]
    python -m agentxp.data.demo.fixture_lock --verify [--db PATH] [--lock PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from agentxp.data.demo.seed import FIXTURE_VERSION, MASTER_SEED


_TABLES = (
    "experiments",
    "users",
    "assignments",
    "sessions",
    "orders",
    "page_events",
)


def _row_hash(db_path: Path, table: str) -> tuple[str, int]:
    """sha256 the JSON-serialized sorted rows of one table."""
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    # ORDER BY all columns to get a stable serialization.
    df = con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchdf()
    con.close()

    n = len(df)
    # Convert to a list-of-lists of plain JSON-able values.
    records = df.to_dict(orient="records")
    canon = json.dumps(records, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest(), n


def write_lock(db_path: Path, out_path: Path) -> dict:
    """Compute and write fixture.lock.yaml. Returns the lock dict."""
    lock = {
        "fixture_version": FIXTURE_VERSION,
        "master_seed": MASTER_SEED,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
    }
    for table in _TABLES:
        sha, n = _row_hash(db_path, table)
        lock["tables"][table] = {"sha256": sha, "row_count": n}
    out_path.write_text(yaml.safe_dump(lock, sort_keys=False))
    return lock


def verify_lock(db_path: Path, lock_path: Path) -> tuple[bool, list[str]]:
    """Recompute hashes and compare to lock. Returns (passed, reasons)."""
    expected = yaml.safe_load(lock_path.read_text())
    reasons: list[str] = []

    if expected["fixture_version"] != FIXTURE_VERSION:
        reasons.append(
            f"fixture_version mismatch: lock={expected['fixture_version']}, "
            f"current={FIXTURE_VERSION}"
        )

    for table in _TABLES:
        expected_row = expected["tables"].get(table)
        if expected_row is None:
            reasons.append(f"lock has no entry for table {table!r}")
            continue
        sha, n = _row_hash(db_path, table)
        if sha != expected_row["sha256"]:
            reasons.append(
                f"{table}: sha mismatch "
                f"(lock={expected_row['sha256'][:12]}…, "
                f"current={sha[:12]}…)"
            )
        if n != expected_row["row_count"]:
            reasons.append(
                f"{table}: row count mismatch "
                f"(lock={expected_row['row_count']}, current={n})"
            )

    return len(reasons) == 0, reasons


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="agentxp_fixture_lock")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true",
                      help="Compute lock from current warehouse and write.")
    mode.add_argument("--verify", action="store_true",
                      help="Compare lock to current warehouse, exit non-zero on mismatch.")
    parser.add_argument(
        "--db", type=Path,
        default=Path("sample-data") / "agentxp_demo.duckdb",
    )
    parser.add_argument(
        "--lock", type=Path,
        default=Path("sample-data") / "fixture.lock.yaml",
    )
    args = parser.parse_args(argv)

    if args.write:
        lock = write_lock(args.db, args.lock)
        print(f"wrote {args.lock} ({sum(t['row_count'] for t in lock['tables'].values()):,} rows)")
        for table, row in lock["tables"].items():
            print(f"  {table:<14} {row['row_count']:>10,} rows  {row['sha256'][:12]}…")
        return 0

    # --verify
    passed, reasons = verify_lock(args.db, args.lock)
    if passed:
        print("fixture.lock.yaml verified")
        return 0
    print("fixture.lock.yaml MISMATCH:", file=sys.stderr)
    for reason in reasons:
        print(f"  - {reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
