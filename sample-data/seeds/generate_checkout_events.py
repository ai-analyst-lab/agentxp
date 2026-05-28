"""Generate the canonical ``checkout_events.csv`` fixture (single source of truth).

This CSV is the ONE table that every warehouse seed script
(``seed_duckdb.py``, ``seed_snowflake.sql``, ``seed_bigquery.sh``,
``seed_databricks.sql``) loads, so the Tier-B cross-warehouse matrix sees an
identical, known ``checkout_events`` table on DuckDB, Snowflake, BigQuery, and
Databricks.

Schema (see seeds/README.md):
    user_id      TEXT      unique user identifier (u000000 ...)
    variant      TEXT      'control' or 'treatment'
    assigned_at  TIMESTAMP when the user entered the experiment
    converted    INTEGER   0/1 — did the user complete checkout
    revenue      DOUBLE    USD revenue for the user (0.0 if not converted)
    event_ts     TIMESTAMP last checkout-flow event for the user

The data is a clean, balanced A/B test with a real positive treatment effect
(control ~12% conversion, treatment ~15%), so it doubles as a sanity fixture.

Deterministic: fixed RNG seed -> byte-stable output. Re-run to regenerate.

Usage:
    .venv/bin/python sample-data/seeds/generate_checkout_events.py
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

SEED = 20260528
N_PER_GROUP = 2500  # 5,000 rows total — well under the 500 KB pre-commit limit
CONTROL_CONV = 0.12
TREATMENT_CONV = 0.155
# Mean revenue conditional on conversion (USD); treatment slightly higher AOV.
CONTROL_AOV = 42.0
TREATMENT_AOV = 44.0
WINDOW_START = datetime(2026, 5, 1, 0, 0, 0)


def _rows(rng: np.random.Generator) -> list[dict]:
    rows: list[dict] = []
    uid = 0
    for variant, conv_p, aov in (
        ("control", CONTROL_CONV, CONTROL_AOV),
        ("treatment", TREATMENT_CONV, TREATMENT_AOV),
    ):
        converted = rng.random(N_PER_GROUP) < conv_p
        # Assignment spread over a 14-day window; event a few hours later.
        offset_min = rng.integers(0, 14 * 24 * 60, size=N_PER_GROUP)
        dwell_min = rng.integers(1, 240, size=N_PER_GROUP)
        # Revenue ~ Gamma so it is positive & right-skewed (realistic AOV).
        rev_raw = rng.gamma(shape=2.0, scale=aov / 2.0, size=N_PER_GROUP)
        for i in range(N_PER_GROUP):
            assigned = WINDOW_START + timedelta(minutes=int(offset_min[i]))
            event = assigned + timedelta(minutes=int(dwell_min[i]))
            conv = bool(converted[i])
            rows.append(
                {
                    "user_id": f"u{uid:06d}",
                    "variant": variant,
                    "assigned_at": assigned.strftime("%Y-%m-%d %H:%M:%S"),
                    "converted": 1 if conv else 0,
                    "revenue": round(float(rev_raw[i]), 2) if conv else 0.0,
                    "event_ts": event.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            uid += 1
    # Sort by user_id for stable, diff-friendly output.
    rows.sort(key=lambda r: r["user_id"])
    return rows


def main() -> None:
    rng = np.random.default_rng(SEED)
    rows = _rows(rng)
    out = Path(__file__).parent / "checkout_events.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "user_id",
                "variant",
                "assigned_at",
                "converted",
                "revenue",
                "event_ts",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
