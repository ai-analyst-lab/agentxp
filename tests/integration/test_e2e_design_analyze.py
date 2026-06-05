"""T100-T108 — End-to-end walks for the 8 seeded experiments.

Status: SKELETONS. The full E2E walks require the orchestrator running
inside a real Claude Code session against the seeded DuckDB warehouse —
the LLM dispatch can't be mocked without losing the point. These tests
are pytest-skipped by default and document the expected outcomes.

To run a real E2E walk (manual, requires user inside Claude Code):

  1. python -m agentxp.data.demo.build
  2. agentxp design --data sample-data/agentxp_demo.duckdb \
       --experiment-id exp_2026q2_checkout_above_fold
  3. open Claude Code in this repo; follow CLAUDE.md to draft + seal a
     brief for the scenario (the orchestrator's first-turn behavior
     picks up the in-flight experiment).
  4. agentxp analyze --brief experiments/exp_2026q2_checkout_above_fold/brief.sealed.yaml
  5. inspect experiments/exp_2026q2_checkout_above_fold/report.json — assert
     verdict == "SHIP" and step_fired matches EXPECTED_VERDICTS.md

When the orchestrator can be invoked headlessly (e.g., via the
Anthropic SDK with the appropriate Claude Code SDK shim), each test
below can flip from `@pytest.mark.skip` to a real run.
"""
from __future__ import annotations

import pytest


# Expected verdict + terminal step per scenario (from sample-data/EXPECTED_VERDICTS.md)
EXPECTED: dict[str, tuple[str, int]] = {
    "exp_2026q2_checkout_above_fold":  ("SHIP", 7),
    "exp_2026q2_invalid_split":        ("INVALID-SRM", 1),
    "exp_2026q2_search_relevance":     ("NO-SHIP-GUARDRAIL", 2),
    "exp_2026q2_recs_v2":              ("LIFT-WITH-CAVEAT", 6),
    "exp_2026q2_email_subject":        ("NO-LIFT", 4),
    "exp_2026q2_cart_nudges":          ("INCONCLUSIVE", 3),
    "exp_2026q2_onboarding_tour":      ("LIFT-WITH-CAVEAT", 7),
    "exp_2026q2_pricing_anchor":       ("NO-LIFT", 4),
}


@pytest.mark.parametrize("scenario_id,expected", list(EXPECTED.items()))
@pytest.mark.skip(
    reason=(
        "E2E walk requires the orchestrator running inside Claude Code "
        "against the seeded warehouse — LLM dispatch is not mockable "
        "without defeating the test. Run manually per the docstring or "
        "wire the Claude Code SDK shim when available."
    )
)
def test_e2e_scenario_lands_on_expected_verdict(scenario_id, expected):
    """Cutover bar (PLAN.md §8): each scenario walks through design then
    analyze and emits its expected verdict."""
    expected_verdict, expected_step = expected
    # Stub for when the headless runner is wired:
    #   result = run_e2e_walk(scenario_id)
    #   assert result.verdict == expected_verdict
    #   assert result.terminal_step == expected_step
    pytest.fail("not implemented — see module docstring")


def test_expected_verdicts_match_warehouse_scenarios():
    """Closure: EXPECTED ids must match the eight scenarios in the
    warehouse generator. Adding a new scenario without updating
    EXPECTED is caught here."""
    from agentxp.data.demo.scenarios import SCENARIOS
    warehouse_ids = {s.experiment_id for s in SCENARIOS}
    expected_ids = set(EXPECTED.keys())
    assert warehouse_ids == expected_ids, (
        f"warehouse scenarios {warehouse_ids} vs EXPECTED {expected_ids}"
    )


def test_expected_verdicts_match_scenario_target():
    """Closure: each scenario's expected_verdict field matches the
    EXPECTED truth table. Discipline-as-code."""
    from agentxp.data.demo.scenarios import SCENARIOS
    for s in SCENARIOS:
        expected_verdict, _ = EXPECTED[s.experiment_id]
        assert s.expected_verdict == expected_verdict, (
            f"{s.experiment_id}: scenario.expected_verdict="
            f"{s.expected_verdict!r} vs EXPECTED={expected_verdict!r}"
        )
