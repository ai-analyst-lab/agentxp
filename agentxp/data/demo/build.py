"""Build the seeded DuckDB demo warehouse (T31).

Produces a DuckDB file with 6 tables:

  experiments    one row per experiment
  users          one row per unique user
  assignments    one row per (user_id, experiment_id) with arm
  sessions       fact (per-session row)
  orders         fact (per-order row; carries order_value)
  page_events    fact (interaction events)

Deterministic per scenario.seed; identical regeneration yields identical
row hashes (verified by fixture.lock.yaml from T32).

Run:
    python -m agentxp.data.demo.build [--out PATH]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from agentxp.data.demo.scenarios import SCENARIOS, Scenario
from agentxp.data.demo.seed import streams


_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_EXP_DURATION_DAYS = 14


def _assignments_for(
    scenario: Scenario, user_id_offset: int,
) -> list[tuple]:
    """Sample assignments. Returns list of tuples ready for INSERT."""
    rng = streams(scenario.seed)
    raw = rng[1].random(scenario.n_users)
    treatment_share = (1.0 - scenario.control_share) + scenario.assignment_imbalance
    treatment_share = max(0.0, min(1.0, treatment_share))

    exposure_offsets = rng[6].uniform(0, _EXP_DURATION_DAYS * 24, scenario.n_users)
    rows: list[tuple] = []
    for i in range(scenario.n_users):
        arm = "treatment" if raw[i] < treatment_share else "control"
        rows.append((
            user_id_offset + i,
            scenario.experiment_id,
            arm,
            (_EPOCH + timedelta(hours=float(exposure_offsets[i]))).replace(tzinfo=None),
        ))
    return rows


def _outcomes_for(
    scenario: Scenario, assignments: list[tuple],
) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Sample sessions, orders, page_events. Returns three list[tuple]."""
    rng = streams(scenario.seed)
    sessions: list[tuple] = []
    orders: list[tuple] = []
    events: list[tuple] = []

    for user_id, _exp, arm, exp_at in assignments:
        # Per-user conversion probability
        p = scenario.baseline_conversion
        if arm == "treatment":
            p = scenario.baseline_conversion * (1.0 + scenario.treatment_lift_relative)
            if scenario.novelty_late_ratio is not None:
                hours_in = (exp_at - _EPOCH.replace(tzinfo=None)).total_seconds() / 3600.0
                window_pos = min(1.0, hours_in / (_EXP_DURATION_DAYS * 24))
                effect_scale = 1.0 + (scenario.novelty_late_ratio - 1.0) * window_pos
                p = scenario.baseline_conversion * (
                    1.0 + scenario.treatment_lift_relative * effect_scale
                )
            if scenario.contamination_pct > 0:
                if float(rng[5].random()) < scenario.contamination_pct:
                    p = scenario.baseline_conversion

        converted = float(rng[2].random()) < p
        n_sessions = int(rng[2].integers(1, 4))
        last_sid = None
        for s_idx in range(n_sessions):
            sid = user_id * 100 + s_idx
            sess_at = exp_at + timedelta(hours=float(rng[2].uniform(0, 24)))
            sessions.append((
                sid, user_id, sess_at, int(rng[2].integers(30, 1200)),
            ))
            last_sid = sid
            # Emit a plausible e-commerce funnel of page_events for this session.
            # Every session at least has a page_view. Some progress through
            # the funnel (product_view → add_to_cart → begin_checkout). The
            # treatment arm has slightly higher add_to_cart + click_buy_now
            # rates when the scenario has positive lift (so add_to_cart_rate
            # as a metric reflects the change).
            _emit_funnel_events(
                events, user_id, sid, sess_at,
                rng=rng[2],
                arm=arm,
                lift_relative=scenario.treatment_lift_relative,
            )

        if converted:
            order_val = float(scenario.guardrail_baseline) + float(
                rng[3].normal(0, 1.0)
            )
            if arm == "treatment":
                order_val *= (1.0 + scenario.guardrail_lift_relative)
            order_val = max(0.0, order_val)
            orders.append((
                user_id * 10, user_id, last_sid,
                exp_at + timedelta(hours=float(rng[3].uniform(1, 48))),
                order_val,
            ))

    return sessions, orders, events


_SCHEMA_SQL = """
CREATE TABLE experiments (
    experiment_id VARCHAR PRIMARY KEY,
    status        VARCHAR,
    started_at    TIMESTAMP,
    ended_at      TIMESTAMP,
    description   VARCHAR
);
CREATE TABLE users (
    user_id     INTEGER PRIMARY KEY,
    signup_date DATE,
    segment     VARCHAR
);
CREATE TABLE assignments (
    user_id           INTEGER,
    experiment_id     VARCHAR,
    arm               VARCHAR,
    first_exposure_at TIMESTAMP,
    PRIMARY KEY (user_id, experiment_id)
);
CREATE TABLE sessions (
    session_id        INTEGER PRIMARY KEY,
    user_id           INTEGER,
    started_at        TIMESTAMP,
    duration_seconds  INTEGER
);
CREATE TABLE orders (
    order_id     INTEGER PRIMARY KEY,
    user_id      INTEGER,
    session_id   INTEGER,
    ordered_at   TIMESTAMP,
    order_value  DOUBLE
);
CREATE TABLE page_events (
    user_id     INTEGER,
    session_id  INTEGER,
    event_name  VARCHAR,
    element_id  VARCHAR,
    latency_ms  INTEGER,
    event_at    TIMESTAMP
);
"""


_FUNNEL_EVENTS = (
    # (event_name, element_id, base_probability, latency_low, latency_high)
    ("page_view",        "home_or_listing",   1.0,  120, 380),
    ("product_view",     "pdp",               0.65, 180, 520),
    ("add_to_cart",      "add_to_cart_button", 0.18, 90, 280),
    ("click_buy_now",    "buy_now_button",    0.10, 80,  260),
    ("begin_checkout",   "checkout_proceed_button", 0.08, 110, 320),
    ("search_query",     "search_box",        0.22, 60,  220),
    ("recommendation_view", "recs_module",    0.40, 70,  240),
    ("recommendation_click", "recs_module",   0.05, 70,  200),
)


def _emit_funnel_events(events: list, user_id: int, sid: int, sess_at, *,
                        rng, arm: str, lift_relative: float) -> None:
    """Plausible per-session funnel. Treatment arm gets slightly higher
    add_to_cart + buy_now click rates when lift_relative > 0."""
    from datetime import timedelta as _td

    # Treatment arm boost on key engagement events when scenario has lift
    boost = 1.0
    if arm == "treatment" and lift_relative > 0:
        boost = 1.0 + lift_relative * 0.3  # partial pass-through

    for event_name, element_id, base_p, lat_lo, lat_hi in _FUNNEL_EVENTS:
        p = base_p
        if event_name in ("add_to_cart", "click_buy_now") and boost > 1.0:
            p = min(0.95, p * boost)
        if rng.random() < p:
            offset_min = float(rng.uniform(0, 28))
            events.append((
                user_id,
                sid,
                event_name,
                element_id,
                int(rng.integers(lat_lo, lat_hi)),
                sess_at + _td(minutes=offset_min),
            ))


def build(out_path: Path) -> dict[str, int]:
    """Build the warehouse. Returns per-table row counts."""
    import duckdb

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    con = duckdb.connect(str(out_path))
    con.execute(_SCHEMA_SQL)

    user_offset = 1_000_000
    seen: set[int] = set()
    counts = {"experiments": 0, "users": 0, "assignments": 0,
              "sessions": 0, "orders": 0, "page_events": 0}

    for scenario in SCENARIOS:
        con.execute(
            "INSERT INTO experiments VALUES (?, ?, ?, ?, ?)",
            [
                scenario.experiment_id, "completed",
                _EPOCH.replace(tzinfo=None),
                (_EPOCH + timedelta(days=_EXP_DURATION_DAYS)).replace(tzinfo=None),
                scenario.hypothesis_prose,
            ],
        )
        counts["experiments"] += 1

        assignments = _assignments_for(scenario, user_offset)
        sessions, orders, events = _outcomes_for(scenario, assignments)

        new_users = []
        for uid, *_ in assignments:
            if uid not in seen:
                seen.add(uid)
                new_users.append((uid, _EPOCH.date(), "general"))

        if new_users:
            con.executemany("INSERT INTO users VALUES (?, ?, ?)", new_users)
            counts["users"] += len(new_users)

        con.executemany(
            "INSERT INTO assignments VALUES (?, ?, ?, ?)", assignments
        )
        counts["assignments"] += len(assignments)
        con.executemany(
            "INSERT INTO sessions VALUES (?, ?, ?, ?)", sessions
        )
        counts["sessions"] += len(sessions)
        if orders:
            con.executemany(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders
            )
            counts["orders"] += len(orders)
        if events:
            con.executemany(
                "INSERT INTO page_events VALUES (?, ?, ?, ?, ?, ?)", events
            )
            counts["page_events"] += len(events)

        user_offset += scenario.n_users + 1000

    con.close()
    return counts


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="agentxp_demo_warehouse")
    parser.add_argument(
        "--out", type=Path,
        default=Path("sample-data") / "agentxp_demo.duckdb",
        help="Output path for the DuckDB file.",
    )
    args = parser.parse_args(argv)
    print(f"building {len(SCENARIOS)} experiments → {args.out}")
    counts = build(args.out)
    size_kb = args.out.stat().st_size / 1024
    print(f"OK: wrote {args.out} ({size_kb:.1f} KB)")
    for table, n in counts.items():
        print(f"  {table:<14} {n:>10,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
