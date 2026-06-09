"""W2.1 — SQL safety test corpus.

Three named pattern groups feed Waves 2 and 3:

* ``DESIGN_MUST_REFUSE`` — queries that Layer 3d (R11) must refuse in
  ``mode="design"``. The corpus covers SELECT projections, JOIN exposure,
  WHERE predicate filtering, subquery exposure, and aliased outcomes.
* ``DESIGN_SHOULD_ACCEPT`` — routine shape probes the design verb needs
  to run: distinct-user counts, daily accrual via ``CAST(... AS DATE)``,
  segment cardinality, fact-row counts. These pass with the W3.1
  ``ALLOWED_AST_NODES`` broadening; the corpus locks the contract.
* ``ANALYZE_MUST_ACCEPT`` — the same outcome-bearing queries that fail
  ``mode="design"`` must succeed in ``mode="analyze"``. Layer 3d is
  what differs by mode (per round2/sql-safety-architect §2); a single
  global ``ALLOWED_AST_NODES`` keeps the AST surface consistent.

The corpus is the contract Wave 2 and Wave 3 modify the pipeline to
satisfy. Adding a query here without updating the pipeline is the audit
point.
"""
from __future__ import annotations

import pytest

from agentxp.orchestrator.tools import ToolRefusal, probe_data
from agentxp.sql.safety import DesignModePeekViolation


# ──────────────────────────────────────────────────────────────────────────
# Pattern fixtures
# ──────────────────────────────────────────────────────────────────────────


DESIGN_MUST_REFUSE: list[tuple[str, str]] = [
    (
        "select_arm",
        "SELECT user_id, arm FROM assignments",
    ),
    (
        "select_arm_aliased",
        "SELECT user_id, arm AS bucket FROM assignments",
    ),
    (
        "where_arm_equals_literal",
        "SELECT COUNT(*) FROM assignments WHERE arm = 'control'",
    ),
    (
        "where_arm_in_list",
        "SELECT COUNT(*) FROM assignments WHERE arm IN ('control', 'treatment')",
    ),
    (
        "join_assignment_with_orders_on_arm",
        (
            "SELECT a.arm, COUNT(*) FROM assignments a "
            "JOIN orders o ON a.user_id = o.user_id GROUP BY a.arm"
        ),
    ),
    (
        "subquery_with_arm",
        (
            "SELECT user_id FROM users WHERE user_id IN "
            "(SELECT user_id FROM assignments WHERE arm = 'treatment')"
        ),
    ),
]


# Post-Round-5: Layer 3d consults only semantic_models.outcome_columns.
# A query against a column NOT declared as outcome on any semantic model
# is permitted in design mode even if the column name was on the old
# hardcoded list (e.g. `variant` is not declared in the repo's
# assignment.yaml; the canonical declaration is `arm`).


DESIGN_SHOULD_ACCEPT: list[tuple[str, str]] = [
    (
        "distinct_users_total",
        "SELECT COUNT(DISTINCT user_id) AS n FROM users",
    ),
    (
        "users_by_segment",
        "SELECT segment, COUNT(*) AS n FROM users GROUP BY segment ORDER BY n DESC",
    ),
    (
        "daily_distinct_users_via_cast",
        (
            "SELECT CAST(started_at AS DATE) AS day, COUNT(DISTINCT user_id) AS n "
            "FROM sessions GROUP BY day ORDER BY day"
        ),
    ),
    (
        "session_window_bounds",
        "SELECT MIN(started_at) AS lo, MAX(started_at) AS hi FROM sessions",
    ),
    (
        "product_view_rows",
        "SELECT COUNT(*) FROM page_events WHERE event_name = 'product_view'",
    ),
    (
        "active_users_last_30d_via_interval_arithmetic",
        (
            "SELECT COUNT(DISTINCT user_id) AS n FROM sessions "
            "WHERE started_at >= (SELECT MAX(started_at) - INTERVAL 30 DAY FROM sessions)"
        ),
    ),
    (
        "daily_buckets_via_date_trunc",
        (
            "SELECT DATE_TRUNC('day', started_at) AS day, COUNT(*) FROM sessions "
            "GROUP BY day ORDER BY day"
        ),
    ),
    (
        "between_dates",
        (
            "SELECT COUNT(*) FROM sessions WHERE started_at "
            "BETWEEN '2026-01-01' AND '2026-01-31'"
        ),
    ),
    (
        "is_not_null_check",
        "SELECT COUNT(*) FROM users WHERE segment IS NOT NULL",
    ),
    (
        "like_segment_filter",
        "SELECT COUNT(*) FROM users WHERE segment LIKE 'enterprise%'",
    ),
]


ANALYZE_MUST_ACCEPT: list[tuple[str, str]] = [
    (
        "arm_count_for_srm_check",
        "SELECT arm, COUNT(*) AS n FROM assignments GROUP BY arm",
    ),
    (
        "arm_orders_joined_for_metric_compute",
        (
            "SELECT a.arm, COUNT(DISTINCT o.user_id) AS converted "
            "FROM assignments a LEFT JOIN orders o ON a.user_id = o.user_id "
            "GROUP BY a.arm"
        ),
    ),
]


# ──────────────────────────────────────────────────────────────────────────
# Tests parametrized on the corpus
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def repo_semantic_models() -> list:
    """Load every shipped semantic model so Layer 3d has its canonical
    outcome-column declarations. Post-Round-5 (S11.A), the hardcoded
    `_DESIGN_MODE_FORBIDDEN_COLUMNS` is gone; the wall fires from
    semantic_models.outcome_columns or not at all.
    """
    import yaml as _yaml
    from agentxp.semantic.validators import SemanticModel
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[2]
    out: list = []
    for p in sorted((root / "semantic_models").glob("*.yaml")):
        if p.stem.startswith("_"):
            continue
        raw = _yaml.safe_load(p.read_text())
        out.append(SemanticModel.model_validate(raw))
    return out


@pytest.mark.parametrize("name,sql", DESIGN_MUST_REFUSE, ids=[n for n, _ in DESIGN_MUST_REFUSE])
def test_design_mode_refuses_outcome_patterns(name: str, sql: str, repo_semantic_models) -> None:
    """Layer 3d (R11) rejects every outcome-touching pattern in design mode.

    Post-Round-5: callers must pass semantic_models for the wall to fire.
    """
    with pytest.raises((DesignModePeekViolation, ToolRefusal)):
        probe_data(sql, mode="design", dialect="duckdb", purpose="profile",
                   semantic_models=repo_semantic_models)


@pytest.mark.parametrize("name,sql", ANALYZE_MUST_ACCEPT, ids=[n for n, _ in ANALYZE_MUST_ACCEPT])
def test_analyze_mode_accepts_outcome_patterns(name: str, sql: str, repo_semantic_models) -> None:
    """Same outcome-bearing queries pass in analyze mode (Layer 3d skipped)."""
    probe_data(sql, mode="analyze", dialect="duckdb", purpose="profile",
               semantic_models=repo_semantic_models)


@pytest.mark.parametrize("name,sql", DESIGN_SHOULD_ACCEPT, ids=[n for n, _ in DESIGN_SHOULD_ACCEPT])
def test_design_mode_accepts_shape_probes(name: str, sql: str, repo_semantic_models) -> None:
    """Routine shape probes pass design-mode safety.

    Pre-W3.1: several of these fail with DenyListViolation on AST nodes
    like ``Sub`` (date arithmetic), ``Var`` (DATE_TRUNC format-string
    slot), ``In``, ``Between``, ``Like``, ``Is``. The corpus marks the
    contract; W3.1 broadens ``ALLOWED_AST_NODES`` to satisfy it.
    """
    probe_data(sql, mode="design", dialect="duckdb", purpose="profile",
               semantic_models=repo_semantic_models)
