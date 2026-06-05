"""Smoke tests for the seeded demo warehouse (T33).

These tests assert the *substrate* — that the warehouse has the right
shape, the eight experiments are present, the arm ratios are roughly
where the scenarios target them. Full verdict-tree-landing assertions
live in tests/integration/test_e2e_*.py (Phase 10), which require
running the agentic loop against the data.
"""
from __future__ import annotations

from pathlib import Path

import pytest


WAREHOUSE = Path("sample-data/agentxp_demo.duckdb")
LOCK_FILE = Path("sample-data/fixture.lock.yaml")
EXPECTED_EXPERIMENT_IDS = {
    "E_F12345", "E_INVSRM", "E_GUARDR", "E_LIFTCV",
    "E_NOLIFT", "E_INCONC", "E_NOVELT", "E_UNVER",
}


def _open():
    if not WAREHOUSE.exists():
        pytest.skip(
            f"{WAREHOUSE} not present — run `python -m agentxp.data.demo.build`"
        )
    import duckdb
    return duckdb.connect(str(WAREHOUSE), read_only=True)


def test_warehouse_has_six_tables():
    con = _open()
    tables = {row[0] for row in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main'"
    ).fetchall()}
    assert tables == {
        "experiments", "users", "assignments",
        "sessions", "orders", "page_events",
    }


def test_warehouse_has_eight_experiments():
    con = _open()
    ids = {row[0] for row in con.execute(
        "SELECT experiment_id FROM experiments"
    ).fetchall()}
    assert ids == EXPECTED_EXPERIMENT_IDS


def test_every_assignment_has_a_valid_arm():
    con = _open()
    bad = con.execute(
        "SELECT count(*) FROM assignments "
        "WHERE arm NOT IN ('control', 'treatment')"
    ).fetchone()[0]
    assert bad == 0


def test_anchor_experiment_balanced_arms():
    """E_F12345 is the anchor — assignment imbalance = 0.0 → close to 50/50."""
    con = _open()
    counts = dict(con.execute(
        "SELECT arm, count(*) FROM assignments "
        "WHERE experiment_id = 'E_F12345' GROUP BY arm"
    ).fetchall())
    total = counts["control"] + counts["treatment"]
    treatment_share = counts["treatment"] / total
    # 50/50 ± 3% under random sampling at n=10k
    assert 0.47 < treatment_share < 0.53


def test_invsrm_experiment_has_imbalance():
    """E_INVSRM should show treatment share ~57% (50% + 7% drift)."""
    con = _open()
    counts = dict(con.execute(
        "SELECT arm, count(*) FROM assignments "
        "WHERE experiment_id = 'E_INVSRM' GROUP BY arm"
    ).fetchall())
    total = counts["control"] + counts["treatment"]
    treatment_share = counts["treatment"] / total
    assert treatment_share > 0.55  # the drift is real


def test_first_exposure_at_is_within_two_weeks():
    con = _open()
    n_outside = con.execute("""
        SELECT count(*) FROM assignments
        WHERE first_exposure_at < TIMESTAMP '2026-01-01'
           OR first_exposure_at > TIMESTAMP '2026-01-15'
    """).fetchone()[0]
    assert n_outside == 0


# ─────────────────────────────────────────────────────────────────────────────
# Fixture lock — deterministic regeneration
# ─────────────────────────────────────────────────────────────────────────────


def test_fixture_lock_verifies_if_present():
    """If fixture.lock.yaml exists, recomputing must match it. Catches
    accidental drift between the generator and the locked artifact."""
    if not LOCK_FILE.exists():
        pytest.skip(
            f"{LOCK_FILE} not present — run "
            f"`python -m agentxp.data.demo.fixture_lock --write`"
        )
    if not WAREHOUSE.exists():
        pytest.skip(f"{WAREHOUSE} not present")
    from agentxp.data.demo.fixture_lock import verify_lock
    passed, reasons = verify_lock(WAREHOUSE, LOCK_FILE)
    assert passed, "fixture.lock.yaml drift: " + "; ".join(reasons)
