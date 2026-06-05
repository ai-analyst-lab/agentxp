"""Eight pre-seeded experiment scenarios spanning the verdict tree.

These are real Amazon-style e-commerce product tests with the kind of
story a PM/data scientist would actually write down. Each Scenario
carries the statistical target parameters (which determine the verdict
the tree returns when real stats run against the seeded warehouse data)
PLUS rich narrative metadata that the readout templates render as prose.

The statistical shapes are tuned so each scenario lands on its expected
verdict path through ``decision_tree.walk_tree()``. The narrative metadata
makes the resulting readouts read as real product team writeups rather
than as data-demo scaffolding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


Verdict = Literal[
    "SHIP",
    "INVALID-SRM",
    "NO-SHIP-GUARDRAIL",
    "LIFT-WITH-CAVEAT",
    "NO-LIFT",
    "INCONCLUSIVE",
    "ITERATE-NOVELTY",
    "UNVERIFIABLE",
]


@dataclass(frozen=True)
class Scenario:
    """One seeded experiment — statistical target + narrative metadata.

    Statistical fields determine what the verdict tree returns. Narrative
    fields are rendered by the readout templates as the prose a real
    product team would write.
    """

    # ── identity ───────────────────────────────────────────────────────
    experiment_id: str           # human-readable id like exp_2026q2_X
    seed: int                    # deterministic per-scenario RNG salt
    expected_verdict: Verdict    # closure-test bar for walks

    # ── narrative metadata (rendered as prose) ─────────────────────────
    display_name: str            # short human name
    owner_team: str              # who owns this test
    hypothesis_prose: str        # one sentence
    mechanism_prose: str         # why we think the change will work
    primary_metric_name: str     # the actual metric (matches metrics/*.yaml)
    primary_metric_direction: Literal["higher_is_better", "lower_is_better"]
    secondary_metric_names: tuple[str, ...] = ()
    guardrail_metric_names: tuple[str, ...] = ("revenue_per_user",)
    historical_baseline_context: str = ""
    decision_rule_prose: str = (
        "Ship if the primary metric's 95% CI excludes zero on the benefit "
        "side and no guardrail is breached."
    )

    # ── population ─────────────────────────────────────────────────────
    n_users: int = 10_000
    control_share: float = 0.5

    # ── primary metric (conversion_rate proportion) ────────────────────
    baseline_conversion: float = 0.10
    treatment_lift_relative: float = 0.0

    # ── guardrail (revenue per converted user; negative lift = harm) ───
    guardrail_baseline: float = 5.0
    guardrail_lift_relative: float = 0.0

    # ── halting signals ────────────────────────────────────────────────
    assignment_imbalance: float = 0.0
    novelty_late_ratio: Optional[float] = None
    contamination_pct: float = 0.0


SCENARIOS: list[Scenario] = [
    # ────────────────────────────────────────────────────────────────────
    # SHIP — the anchor scenario; clean lift, balanced, late-ratio stable
    # ────────────────────────────────────────────────────────────────────
    Scenario(
        experiment_id="exp_2026q2_checkout_above_fold",
        seed=12345,
        expected_verdict="SHIP",
        display_name="Move Buy Now button above the fold",
        owner_team="Growth · Checkout",
        hypothesis_prose=(
            "Moving the Buy Now button above the fold on the product detail "
            "page increases conversion rate by reducing the scroll-and-search "
            "friction we see in session recordings."
        ),
        mechanism_prose=(
            "Heatmaps from the last six months show 38% of users scroll past "
            "the fold before adding to cart. Surfacing the Buy Now button in "
            "the first viewport removes a decision-deferral moment."
        ),
        primary_metric_name="conversion_rate",
        primary_metric_direction="higher_is_better",
        secondary_metric_names=("add_to_cart_rate", "average_order_value"),
        guardrail_metric_names=("revenue_per_user", "page_load_time"),
        historical_baseline_context=(
            "Baseline PDP conversion has been stable at 10.0–10.4% for six "
            "months. The last meaningful PDP change shipped in 2025Q4."
        ),
        decision_rule_prose=(
            "Ship if conversion_rate 95% CI excludes zero on the benefit "
            "side AND no guardrail is breached AND late-window effect "
            "remains stable (late_ratio ≥ 0.7)."
        ),
        n_users=10_000,
        baseline_conversion=0.10,
        treatment_lift_relative=0.22,
    ),

    # ────────────────────────────────────────────────────────────────────
    # INVALID-SRM — assignment broke; SRM blocks at step 1
    # ────────────────────────────────────────────────────────────────────
    Scenario(
        experiment_id="exp_2026q2_invalid_split",
        seed=22001,
        expected_verdict="INVALID-SRM",
        display_name="Strikethrough pricing on category pages",
        owner_team="Growth · Pricing",
        hypothesis_prose=(
            "Showing the original price struck through next to the sale "
            "price on category pages increases conversion through anchored "
            "perceived value."
        ),
        mechanism_prose=(
            "Behavioral research suggests price anchoring increases willingness "
            "to purchase when the savings amount is salient. The category "
            "page is the highest-impression surface where this anchor could "
            "fire before users land on the PDP."
        ),
        primary_metric_name="conversion_rate",
        primary_metric_direction="higher_is_better",
        secondary_metric_names=("add_to_cart_rate", "average_order_value"),
        guardrail_metric_names=("revenue_per_user",),
        historical_baseline_context=(
            "Category-page traffic is roughly 4× PDP traffic. A 50/50 split "
            "with normal hashing has been verified in the assignment service "
            "for every other 2026 Q2 experiment."
        ),
        decision_rule_prose=(
            "Standard ship rule, but the SRM gate must pass first (R2)."
        ),
        n_users=10_000,
        baseline_conversion=0.10,
        treatment_lift_relative=0.10,
        assignment_imbalance=0.07,  # 7% drift to treatment trips χ²
    ),

    # ────────────────────────────────────────────────────────────────────
    # NO-SHIP-GUARDRAIL — primary ships but guardrail breaks
    # ────────────────────────────────────────────────────────────────────
    Scenario(
        experiment_id="exp_2026q2_search_relevance",
        seed=33002,
        expected_verdict="NO-SHIP-GUARDRAIL",
        display_name="Neural search ranking model (v2)",
        owner_team="Search · Relevance",
        hypothesis_prose=(
            "Replacing the BM25 baseline ranker with a learned neural model "
            "for search results increases search-to-purchase conversion by "
            "showing more relevant products on the first page."
        ),
        mechanism_prose=(
            "Offline relevance evaluation showed NDCG@10 improvements of "
            "8-12% on held-out search judgments. Online behavior should "
            "follow the offline signal."
        ),
        primary_metric_name="search_to_purchase_rate",
        primary_metric_direction="higher_is_better",
        secondary_metric_names=("add_to_cart_rate",),
        guardrail_metric_names=("page_load_time", "revenue_per_user"),
        historical_baseline_context=(
            "Search-to-purchase has trended down 2% YoY as the catalog grew. "
            "Latency budget for search results is 300ms p95; the neural "
            "model adds inference cost."
        ),
        decision_rule_prose=(
            "Ship if search_to_purchase_rate 95% CI excludes zero AND "
            "page_load_time guardrail does not breach (no increase > 5%)."
        ),
        n_users=12_000,
        baseline_conversion=0.10,
        treatment_lift_relative=0.18,
        guardrail_lift_relative=-0.25,  # 25% per-order value drop → guardrail 90% CI clearly on harm side
    ),

    # ────────────────────────────────────────────────────────────────────
    # LIFT-WITH-CAVEAT (small) — real lift below MDE/2
    # ────────────────────────────────────────────────────────────────────
    Scenario(
        experiment_id="exp_2026q2_recs_v2",
        seed=44003,
        expected_verdict="LIFT-WITH-CAVEAT",
        display_name="Personalized 'You may also like' on PDP",
        owner_team="Recommendations · Personalization",
        hypothesis_prose=(
            "Replacing the static 'frequently bought together' module with "
            "personalized recommendations on the product detail page "
            "increases add-to-cart rate and downstream conversion."
        ),
        mechanism_prose=(
            "Personalization based on past purchase history should surface "
            "more relevant complementary products than the static co-purchase "
            "baseline, especially for repeat customers."
        ),
        primary_metric_name="add_to_cart_rate",
        primary_metric_direction="higher_is_better",
        secondary_metric_names=("conversion_rate", "average_order_value"),
        guardrail_metric_names=("revenue_per_user",),
        historical_baseline_context=(
            "The static module ships for everyone today; click-through on "
            "the module is ~6%. Personalization in the cart page (a separate "
            "test in 2025Q3) showed a 1.5pp lift in CTR."
        ),
        decision_rule_prose=(
            "Ship if add_to_cart_rate lift exceeds MDE/2 (≥1% relative) "
            "with CI clearing zero. Smaller lifts surface a caveat."
        ),
        n_users=30_000,
        baseline_conversion=0.10,
        treatment_lift_relative=0.06,  # ~6pp lift; with mde_pct=20%, lands below MDE/2 = small-lift caveat
    ),

    # ────────────────────────────────────────────────────────────────────
    # NO-LIFT — well-powered null
    # ────────────────────────────────────────────────────────────────────
    Scenario(
        experiment_id="exp_2026q2_email_subject",
        seed=55004,
        expected_verdict="NO-LIFT",
        display_name="Order confirmation email — subject line copy",
        owner_team="Lifecycle · Email",
        hypothesis_prose=(
            "Changing the order confirmation email subject from "
            "'Your order is on the way' to 'Tracking your order #{N}' "
            "increases repeat purchase rate by making it easier to find "
            "the email later."
        ),
        mechanism_prose=(
            "Order numbers in subjects make emails findable by search. "
            "Easier-to-find shipment emails could lead to higher re-engagement "
            "and more repeat purchases over the following 14 days."
        ),
        primary_metric_name="repeat_purchase_rate",
        primary_metric_direction="higher_is_better",
        secondary_metric_names=("email_open_rate",),
        guardrail_metric_names=("revenue_per_user",),
        historical_baseline_context=(
            "Email open rate baseline ~22%, repeat purchase rate within 14 "
            "days ~10%. No subject-line tests have shipped in the past year."
        ),
        decision_rule_prose=(
            "Ship if repeat_purchase_rate CI excludes zero on benefit side. "
            "Conservative — small effects are not worth the email-channel risk."
        ),
        n_users=50_000,
        baseline_conversion=0.10,
        treatment_lift_relative=-0.05,  # slight negative drift so realized lift hugs zero (seed-stable null)
    ),

    # ────────────────────────────────────────────────────────────────────
    # INCONCLUSIVE — underpowered, primary CI straddles zero
    # ────────────────────────────────────────────────────────────────────
    Scenario(
        experiment_id="exp_2026q2_cart_nudges",
        seed=66005,
        expected_verdict="INCONCLUSIVE",
        display_name="Cart-page upsell nudges",
        owner_team="Growth · Cart",
        hypothesis_prose=(
            "Adding a 'Frequently bought with items in your cart' module on "
            "the cart page increases average order value through additional "
            "complementary purchases."
        ),
        mechanism_prose=(
            "Cart visitors have high intent. A complementary-product nudge "
            "at this moment converts more often than the same module on the "
            "PDP, based on the 2025Q3 recs experiment."
        ),
        primary_metric_name="average_order_value",
        primary_metric_direction="higher_is_better",
        secondary_metric_names=("conversion_rate",),
        guardrail_metric_names=("revenue_per_user", "cart_abandonment_rate"),
        historical_baseline_context=(
            "Cart sessions are only ~2k/day, which is the binding constraint "
            "on this test. AOV baseline ~$48. We knew this would be a tight "
            "powered experiment going in."
        ),
        decision_rule_prose=(
            "Ship if AOV CI excludes zero on benefit side. Likely to be "
            "underpowered — be prepared for an inconclusive outcome and a "
            "longer-running follow-up."
        ),
        n_users=2_500,
        baseline_conversion=0.10,
        treatment_lift_relative=0.06,  # genuine signal but n too small to detect
    ),

    # ────────────────────────────────────────────────────────────────────
    # LIFT-WITH-CAVEAT (novelty) — early lift, late fade
    # ────────────────────────────────────────────────────────────────────
    Scenario(
        experiment_id="exp_2026q2_onboarding_tour",
        seed=77006,
        expected_verdict="LIFT-WITH-CAVEAT",  # novelty subcase
        display_name="New user onboarding tour",
        owner_team="Growth · Onboarding",
        hypothesis_prose=(
            "A guided onboarding tour for first-time customers increases "
            "first-week conversion by reducing the discovery friction "
            "around key features (saved addresses, payment methods, wishlists)."
        ),
        mechanism_prose=(
            "First-time customers convert at half the rate of returning "
            "customers in their first week. Most drop-off in qualitative "
            "interviews mapped to 'I couldn't find how to do X' problems "
            "that the tour addresses."
        ),
        primary_metric_name="conversion_rate",
        primary_metric_direction="higher_is_better",
        secondary_metric_names=("repeat_purchase_rate",),
        guardrail_metric_names=("revenue_per_user", "support_ticket_rate"),
        historical_baseline_context=(
            "First-time-user conversion baseline ~10% in week 1. Past "
            "onboarding tours in similar products have shown strong early "
            "lift that decayed within 30 days — this test runs 14 days to "
            "catch novelty decay if present."
        ),
        decision_rule_prose=(
            "Ship if lift is meaningful AND late-window effect (last third) "
            "stays within 70% of early-window effect (late_ratio ≥ 0.7). "
            "Otherwise surface novelty caveat and iterate."
        ),
        n_users=15_000,
        baseline_conversion=0.10,
        treatment_lift_relative=0.20,
        novelty_late_ratio=0.55,  # late drops to 55% of early — novelty fires
    ),

    # ────────────────────────────────────────────────────────────────────
    # NO-LIFT (was UNVER) — contamination data flows through cleanly,
    # producing a well-powered null. The UNVERIFIABLE tree path requires
    # the analyzer specialist to explicitly null an input; not reproducible
    # from raw warehouse data alone. Demoed separately via synthetic-null
    # tests in tests/interpret/test_tree_unverifiable.py.
    # ────────────────────────────────────────────────────────────────────
    Scenario(
        experiment_id="exp_2026q2_pricing_anchor",
        seed=88007,
        expected_verdict="NO-LIFT",  # see comment above
        display_name="Anchored price on PDP",
        owner_team="Growth · Pricing",
        hypothesis_prose=(
            "Adding an anchored 'compare-at' price next to the sale price on "
            "the product detail page increases conversion by making the "
            "discount more salient at the moment of purchase intent."
        ),
        mechanism_prose=(
            "Price anchoring is a well-studied behavioral effect: showing the "
            "original price increases perceived savings even when the actual "
            "discount is unchanged. This should lift conversion on items "
            "that are already on sale."
        ),
        primary_metric_name="conversion_rate",
        primary_metric_direction="higher_is_better",
        secondary_metric_names=("add_to_cart_rate", "average_order_value"),
        guardrail_metric_names=("revenue_per_user",),
        historical_baseline_context=(
            "Sale items are ~30% of catalog impressions. Last 2025Q4 "
            "anchored-pricing test on the cart page showed flat conversion "
            "with a small AOV uplift."
        ),
        decision_rule_prose=(
            "Ship if conversion lift CI excludes zero on benefit side."
        ),
        n_users=8_000,
        baseline_conversion=0.10,
        treatment_lift_relative=0.04,  # contamination dilutes → realized lift near MDE
        contamination_pct=0.50,        # half of treatment users get baseline (not lift)
    ),
]


def by_id(experiment_id: str) -> Scenario:
    for s in SCENARIOS:
        if s.experiment_id == experiment_id:
            return s
    raise KeyError(f"no scenario with id {experiment_id!r}")
