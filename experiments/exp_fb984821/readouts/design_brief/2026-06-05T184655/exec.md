# design_brief — exp_fb984821

```json
{
  "schema_version": 1,
  "experiment_id": "exp_fb984821",
  "hypothesis_text": "Rendering the Buy Now call-to-action above the fold on the product detail\npage, relative to the current below-fold placement, increases conversion_rate\namong product-page visitors on the demo storefront over the exposure window,\nwith the expected direction being a higher per-user probability of placing at\nleast one order. The treatment is hypothesized to act by reducing the\ninteraction distance between product consideration and purchase initiation;\nthe magnitude of the effect is pre-registered in this brief at the\nfeasibility-bounded relative MDE below and is not asserted as a point\nprediction.",
  "primary_metric_name": "conversion_rate",
  "primary_decision_rule": "Ship the treatment if and only if the two-sided 95% confidence interval on\nthe relative lift in conversion_rate excludes zero on the positive side\n(lower bound strictly greater than zero) AND no guardrail breaches its\npre-registered non-inferiority margin. If the primary interval crosses\nzero, or if any guardrail's confidence interval crosses its non-inferiority\nmargin in the adverse direction, the verdict is do-not-ship regardless of\npoint estimate. The rule is intentionally tight: a treatment whose true\neffect is below the pre-registered MDE is expected to fail it.",
  "mde_text": "7.0% relative",
  "power_text": "80% power at α=0.05, two-sided; baseline 0.10, MDE 7.0% relative, n_required = 59,436 (≤ 114,085 surface, 92% headroom)",
  "guardrails_summary": [
    "revenue_per_user (higher_is_better) — nim_relative = -0.01",
    "page_load_time (lower_is_better) — nim_relative = +0.05",
    "cart_abandonment_rate (lower_is_better) — nim_relative = +0.05"
  ],
  "cohorts_summary": [
    "Users on the demo storefront whose first exposure to the experiment is their first `page_event` row with `event_name = 'product_view'` during the exposure window; assignment fires at that event and the assigned population is therefore co-extensive with product-page visitors during the window, segment = general."
  ],
  "assignment_unit": "user_id",
  "expected_arm_ratio_text": "50 / 50",
  "design_chain_hash_short": "37770e1e22d1…",
  "metric_snapshot_count": 4,
  "sealed_at": "2026-06-05T18:43:44.845392Z"
}
```
