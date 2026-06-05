# Design brief — exp_fb984821

> **Status:** VERIFIED · sealed 2026-06-05 18:43:44 UTC · `design_chain_hash` `37770e1e22d1…`
> **Verdict path:** the analyze verb will compute a verdict against this brief; no analysis output exists at the seal moment by R11.

## What we are testing

Rendering the Buy Now call-to-action above the fold on the product detail page, relative to the current below-fold placement, is expected to increase **conversion_rate** among product-page visitors on the demo storefront over the exposure window — a higher per-user probability of placing at least one order. The mechanism the treatment is hypothesized to exploit is a reduction in the interaction distance between product consideration and purchase initiation. The magnitude of the effect is left to analysis; the brief pre-registers only the minimum detectable effect below.

— *cite:* `brief.sealed.yaml#brief_content.hypothesis`

## Primary metric and decision rule

| Field                | Value                                                                                          |
|----------------------|------------------------------------------------------------------------------------------------|
| Primary metric       | `conversion_rate` (proportion · `higher_is_better`)                                            |
| Decision rule        | Ship iff 95% CI lower bound on the relative lift in `conversion_rate` is strictly greater than zero **and** no guardrail breaches its non-inferiority margin. |
| MDE                  | 7.0% relative (baseline 0.10 → treatment 0.107)                                                |
| Power                | 80% at α = 0.05, two-sided                                                                      |
| Required sample      | 59,436 total (29,718 / arm)                                                                     |
| Available surface    | 114,085 product-page users — 92% headroom                                                       |
| Expected duration    | ~7.7 days at the observed accrual of ~7,735 product-page users / day                            |

— *cite:* `brief.sealed.yaml#brief_content.primary_metric`, `primary_decision_rule`, `mde_text`, `n_required`

The decision rule is intentionally tight: a treatment whose true effect is below the pre-registered MDE is expected to fail it.

## Guardrails

| Metric                  | Direction         | Non-inferiority margin (relative) |
|-------------------------|-------------------|-----------------------------------|
| `revenue_per_user`      | higher_is_better  | −1.0% (catalog default)           |
| `page_load_time` (p95)  | lower_is_better   | +5.0% (catalog default)           |
| `cart_abandonment_rate` | lower_is_better   | +5.0%                             |

A breach of any guardrail's CI against its margin in the adverse direction is a do-not-ship signal regardless of the primary point estimate.

— *cite:* `brief.sealed.yaml#brief_content.guardrails`

## Cohort and assignment

- **Cohort:** users on the demo storefront whose first exposure to the experiment is their first `page_event` row with `event_name = 'product_view'` during the exposure window. By construction, the assigned population is co-extensive with product-page visitors during the window; `segment = general`.
- **Assignment unit:** `user_id`
- **Assignment trigger:** `assignment.first_exposure_at = MIN(page_event.event_at WHERE event_name = 'product_view')` per `user_id`
- **Arms / allocation:** `control` / `treatment`, 50 / 50

— *cite:* `brief.sealed.yaml#brief_content.cohorts`, `expected_shape.assignment_unit`, `arms`

## Integrity lock (R11)

| Component             | Value                                                       |
|-----------------------|-------------------------------------------------------------|
| `design_chain_hash`   | `37770e1e22d1d584de8602b37156d00854a1c79702a1cd12e0829393849b1a13` |
| `metric_snapshot`     | 4 entries: `conversion_rate`, `revenue_per_user`, `page_load_time`, `cart_abandonment_rate` |
| `expected_shape`      | assignment_unit = `user_id`; arms = `control` / `treatment` 50 / 50; cohort pinned |
| `sealed_at`           | 2026-06-05T18:43:44.845392Z                                 |
| `sealed_by`           | shane@aieval.ai                                             |
| `agentxp_version`     | 0.1.0                                                       |

The analyze verb verifies all three components before opening. A drift in any of them refuses the analyze open.

## Next step

```
/analyze --brief experiments/exp_fb984821/brief.sealed.yaml
```
