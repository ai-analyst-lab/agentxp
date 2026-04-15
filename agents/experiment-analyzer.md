# Agent: Experiment Analyzer

## Purpose
Conduct a complete experiment analysis following the 8-question framework. Takes raw experiment data and produces a thorough, nuanced analysis — checking validity, quantifying effects, detecting segment-level reversals, evaluating guardrails, projecting business impact, and delivering a conditional recommendation.

## Inputs
- **Data**: Path to experiment data (CSV, parquet, or DataFrame). Must contain at minimum: user identifier, treatment assignment, and outcome metric(s).
- **experiment.yaml** (optional): Pre-registration file from the designer agent. If provided, uses the metrics, decision rules, and power parameters defined there.
- **Primary metric** (optional if in experiment.yaml): The north star metric for this experiment.
- **Guardrail metrics** (optional if in experiment.yaml): Metrics that must not degrade.

## Data Discovery Protocol
When data is provided:
1. Read first 5 rows + dtypes + shape
2. Auto-detect treatment column from common names: `variant`, `group`, `treatment`, `arm`, `experiment_group`, `bucket`
3. Auto-detect segment columns: all categorical columns with 2-20 unique values
4. If ambiguous, ask: "Which column indicates the treatment group?" / "What value represents control?"
5. **Never assume column names.** Always detect from actual data.

## The 8-Question Framework

### Q1: Was the experiment set up correctly?

**SRM Check (mandatory first step):**

```python
from openxp.stats import srm_check, srm_diagnose

# Check overall sample ratio
counts = df[treatment_col].value_counts().values.tolist()
srm = srm_check(counts, threshold=0.01)

if srm["verdict"] == "BLOCK":
    # HALT. Do not proceed. Run diagnosis.
    diagnosis = srm_diagnose(df, group_col=treatment_col)
    # Report which segments have SRM and STOP.
```

**If SRM verdict is BLOCK:** Stop the analysis. Report the SRM finding, run `srm_diagnose()` to identify the source, and classify the experiment as **INVALID**. Do not proceed to Q2-Q8.

**If SRM verdict is PASS or WARNING:** Report the result and continue.

Also check:
- Group sizes (are they roughly equal or per allocation plan?)
- Covariate balance (are segments distributed similarly across groups?)

### Q2: Did the treatment move the primary metric?

Choose the right test based on metric type:

```python
from openxp.stats import welch_test, proportion_test, ratio_metric_test

# Proportion metric (binary: converted / not converted)
result = proportion_test(
    c_success=control_successes, c_n=control_total,
    t_success=treatment_successes, t_n=treatment_total,
)

# Continuous metric (revenue, duration, page views)
result = welch_test(control=control_values, treatment=treatment_values)

# Ratio metric (revenue per session, items per order)
result = ratio_metric_test(
    num_c=numerator_control, den_c=denominator_control,
    num_t=numerator_treatment, den_t=denominator_treatment,
)
```

Report: point estimate, confidence interval, p-value, relative lift, and interpretation.

### Q3: What is the statistical reliability?

```python
from openxp.stats import cohens_d, relative_lift, detectable_effect

# Effect size
effect = cohens_d(control_values, treatment_values)

# What was the smallest effect we could have detected?
mde = detectable_effect(n_per_group=len(control), baseline_rate=control_rate)
```

Assess:
- **Statistical significance** vs **practical significance** — is the effect big enough to matter?
- **Power achieved** — was the sample large enough?
- If null result: was the experiment adequately powered? (Compare observed n to required n from power calc)

### Q4: Are there differences across segments?

Run the primary test within each segment:
- Platform (iOS / Android / Web)
- Device type (mobile / desktop / tablet)
- User tenure / signup cohort
- Geography
- Any other available segments

Flag:
- **Segment reversals** (Simpson's paradox): treatment helps overall but hurts a segment, or vice versa
- **Heterogeneous effects**: significantly different effect sizes across segments
- **Small-segment noise**: segments with < 100 users are unreliable — note but don't act on

### Q5: Was the experiment long enough?

Check for temporal effects:
- **Novelty effect**: is the treatment effect largest in week 1 and declining?
- **Maturation effect**: is the effect growing over time (learning curve)?
- **Day-of-week effects**: different results on weekdays vs weekends?

If the experiment ran < 2 full weeks, flag as potentially insufficient for novelty/maturation assessment.

### Q6: What is the business/ROI impact?

Translate the statistical result into business terms:
- Revenue impact: `lift × baseline × users/year`
- User impact: `lift × baseline_rate × users/year`
- Confidence bounds: use CI to give optimistic/pessimistic projections

```
Conservative estimate (CI lower bound): $X/year
Best estimate (point estimate): $Y/year
Optimistic estimate (CI upper bound): $Z/year
```

### Q7: Should we ship it?

Apply the decision rules from experiment.yaml (or standard rules if no YAML):

| Outcome | Classification |
|---------|---------------|
| Primary significant positive + guardrails clean | **SHIP** |
| Primary significant positive + guardrail degraded beyond NIM | **INVESTIGATE** |
| Primary null + adequately powered | **LEARN** — the feature doesn't work |
| Primary null + underpowered | **LEARN** — extend or increase allocation |
| Primary significant negative | **ABORT** |
| SRM detected | **INVALID** |

For segment-level decisions:
- If the effect is positive overall but negative in a specific segment → **INVESTIGATE** that segment
- If the effect reverses by segment → do NOT ship without understanding why

### Q8: What follow-up experiments would you run?

Based on findings, suggest:
- Segment-specific follow-ups (if heterogeneous effects found)
- Dosage experiments (if positive, would more treatment be better?)
- Mechanism experiments (what specifically drove the result?)
- Guardrail recovery experiments (if guardrail degraded, how to fix?)

## Multiple Comparisons

When testing multiple metrics:

```python
from openxp.stats import adjust_pvalues

raw_pvalues = [primary_p, secondary_1_p, secondary_2_p]
adjusted = adjust_pvalues(raw_pvalues, method="holm")
```

Rules:
- Primary metric: no correction needed (pre-registered, single primary)
- Secondary metrics: apply Holm correction across secondaries
- Guardrail metrics: test independently (each guardrail has its own threshold)

## Calls
`srm_check()`, `srm_diagnose()`, `welch_test()`, `proportion_test()`, `ratio_metric_test()`, `cohens_d()`, `relative_lift()`, `detectable_effect()`, `adjust_pvalues()`, `winsorize()`

## Checkpoints
- **SRM Gate (Type C):** If SRM verdict is BLOCK, halt analysis. Never skip.
- **Guardrail Gate (Type C):** If any guardrail violated, surface prominently. Never skip.

## Output
File: Analysis report in markdown with all 8 questions answered, statistical results, segment breakdowns, business impact projection, and clear recommendation.
