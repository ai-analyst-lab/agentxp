# Agent: Experiment Monitor

## Purpose
Daily health monitoring for running experiments. Checks SRM trending, guardrail status, sample accumulation vs plan, and projects completion date. Outputs a traffic-light dashboard (GREEN / YELLOW / RED) with clear action items.

## Inputs
- **Data**: Current experiment data (CSV, database query, or DataFrame). Must contain treatment assignment and outcome metrics, ideally with timestamps.
- **experiment.yaml** (optional): Pre-registration file with planned sample size and guardrail thresholds.
- **Previous monitoring reports** (optional): Prior outputs from this agent for trend comparison.

## Data Discovery Protocol
Same as experiment-analyzer: auto-detect treatment column, outcome columns, and timestamp column from data. Never assume column names.

## Monitoring Checks

### Check 1: SRM Trending

```python
from openxp.stats import srm_check

# Overall SRM
counts = df[treatment_col].value_counts().values.tolist()
srm = srm_check(counts, threshold=0.0005)  # Microsoft standard

# Daily SRM (if timestamps available)
for day, day_df in df.groupby(date_col):
    day_counts = day_df[treatment_col].value_counts().values.tolist()
    day_srm = srm_check(day_counts, threshold=0.0005)
```

Traffic light:
- **GREEN:** p > 0.05 overall and all days
- **YELLOW:** p < 0.05 but > 0.0005 (marginal signal)
- **RED:** p < 0.0005 (strong SRM — halt and investigate)

### Check 2: Guardrail Status

For each guardrail metric, run a one-sided test:

```python
from openxp.stats import welch_test, proportion_test

# Test if guardrail has degraded
result = welch_test(control_values, treatment_values)
# Check direction: has the metric moved in the bad direction?
```

Traffic light:
- **GREEN:** No guardrail degraded (p > 0.05 in bad direction)
- **YELLOW:** Marginal guardrail signal (0.01 < p < 0.05)
- **RED:** Guardrail violation (p < 0.01 in bad direction) — halt and escalate

### Check 3: Sample Accumulation

Compare current enrollment to plan:

```
Current: X users per group (Y% of planned)
Planned: Z users per group
Daily rate: W users/day
Projected completion: [date]
On track: [YES / BEHIND / AHEAD]
```

If behind schedule by > 20%, flag and suggest:
- Check if traffic has decreased
- Consider increasing allocation
- Recalculate completion date

### Check 4: Detectable Effect at Current Sample

```python
from openxp.stats import detectable_effect

# What can we detect right now?
current_mde = detectable_effect(n_per_group=current_n, baseline_rate=baseline)
# Compare to planned MDE — are we close?
```

## Output: Monitoring Dashboard

```markdown
# Experiment Monitor: [Name]
**Date:** [today]
**Day [X] of [planned Y]**

## Traffic Light Summary

| Check | Status | Detail |
|-------|--------|--------|
| SRM | [GREEN/YELLOW/RED] | p = X.XXXX |
| Guardrails | [GREEN/YELLOW/RED] | [all clean / metric X degraded] |
| Sample | [GREEN/YELLOW/RED] | [X% of planned, on track / behind] |
| Power | [GREEN/YELLOW/RED] | Can detect [X%] relative lift (planned: [Y%]) |

## Overall Status: [GREEN / YELLOW / RED]

## Action Items
- [List any required actions]

## Trends (if multiple monitoring reports exist)
- SRM p-value trend: [stable / improving / worsening]
- Guardrail trend: [stable / worsening]
- Enrollment rate: [stable / declining]
```

## Halt Conditions (Type C — never skip)

The monitor MUST recommend halting if:
1. **SRM RED:** p < 0.0005 — randomization is broken
2. **Guardrail RED:** Statistically significant degradation beyond threshold
3. **Emergency stop:** Guardrail degrades by > 15% relative (from experiment.yaml `emergency_stop` rule)

## Calls
`srm_check()`, `srm_diagnose()`, `welch_test()`, `proportion_test()`, `detectable_effect()`

## Checkpoints
- **Guardrail violation (Type C):** If any guardrail is RED, always surface. Never skip.
