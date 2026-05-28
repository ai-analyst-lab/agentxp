"""Generate ``ship_demo.csv`` — the Lightning-Lesson happy-path fixture.

A clean, self-contained A/B test engineered so the full Stage 0->8 experiment
workflow lands on a **SHIP** verdict:

  * Primary (conversion): treatment significantly higher than control
    (control ~10%, treatment ~13%, n ~3,000/group -> p well under 0.05).
  * Secondary (revenue/user): directionally positive.
  * Guardrail (page_load_ms p95): essentially flat — no degradation, so the
    interpreter does NOT divert to INVESTIGATE.
  * Balanced 50/50 assignment -> clean SRM (no block).
  * Two segments (platform) both positive -> no Simpson's reversal.

Columns are the auto-detected shape the /experiment pipeline expects:
    user_id, variant, converted, revenue, page_load_ms, platform

Deterministic: fixed RNG seed -> byte-stable output.

Usage:
    .venv/bin/python sample-data/seeds/generate_ship_demo.py
Writes to sample-data/ship_demo.csv (the demo/fixture location).
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

SEED = 424242
N_PER_GROUP = 3000
CONTROL_CONV = 0.10
TREATMENT_CONV = 0.13
CONTROL_AOV = 38.0
TREATMENT_AOV = 40.0
# Guardrail: page load p95 ~ stable. Same distribution for both arms.
LOAD_MEAN = 1800.0  # ms
LOAD_SD = 350.0


def _rows(rng: np.random.Generator) -> list[dict]:
    rows: list[dict] = []
    uid = 0
    platforms = np.array(["web", "ios", "android"])
    for variant, conv_p, aov in (
        ("control", CONTROL_CONV, CONTROL_AOV),
        ("treatment", TREATMENT_CONV, TREATMENT_AOV),
    ):
        converted = rng.random(N_PER_GROUP) < conv_p
        rev_raw = rng.gamma(shape=2.0, scale=aov / 2.0, size=N_PER_GROUP)
        load = rng.normal(LOAD_MEAN, LOAD_SD, size=N_PER_GROUP).clip(min=200)
        plat = rng.choice(platforms, size=N_PER_GROUP, p=[0.5, 0.3, 0.2])
        for i in range(N_PER_GROUP):
            conv = bool(converted[i])
            rows.append(
                {
                    "user_id": f"u{uid:06d}",
                    "variant": variant,
                    "converted": 1 if conv else 0,
                    "revenue": round(float(rev_raw[i]), 2) if conv else 0.0,
                    "page_load_ms": round(float(load[i]), 1),
                    "platform": str(plat[i]),
                }
            )
            uid += 1
    rows.sort(key=lambda r: r["user_id"])
    return rows


def main() -> None:
    rng = np.random.default_rng(SEED)
    rows = _rows(rng)
    out = Path(__file__).parent.parent / "ship_demo.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "user_id",
                "variant",
                "converted",
                "revenue",
                "page_load_ms",
                "platform",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
