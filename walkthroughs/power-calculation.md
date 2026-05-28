# Power Calculation Deep Dive

Understanding sample size, duration, and sensitivity trade-offs.

## The Core Question

**"How many users do I need to detect a meaningful effect?"**

This depends on four inputs:
1. **Baseline rate** — your current metric value
2. **MDE** — the smallest change worth detecting
3. **Alpha** — false positive tolerance (usually 0.05)
4. **Power** — detection probability (usually 0.80)

## Proportion Metrics (Conversion Rate)

```python
from agentxp.stats import power_proportion

result = power_proportion(
    baseline_rate=0.08,     # 8% current conversion
    mde_relative=0.10,      # want to detect 10% relative lift (→ 8.8%)
    alpha=0.05,
    power=0.80,
)

print(result["interpretation"])
# "Need 24,572 users per group (49,144 total) to detect a 10.0% relative lift
#  from 8.0% to 8.8% (alpha=0.05, power=80%)."
```

## Continuous Metrics (Revenue, Duration)

```python
from agentxp.stats import power_mean

result = power_mean(
    baseline_mean=47.20,    # current average revenue
    baseline_std=35.0,      # standard deviation
    mde_relative=0.05,      # detect 5% change in mean
    alpha=0.05,
    power=0.80,
)
```

## Duration Estimation

```python
from agentxp.stats import duration_estimate

duration = duration_estimate(
    n_required=49_144,      # total sample from power calc
    daily_traffic=5_000,    # users per day entering the flow
    allocation=1.0,         # fraction of traffic in experiment
)

print(duration["interpretation"])
# "Need 49,144 total users at 5,000/day = 10 days (1.4 weeks). Well within standard window."
print(duration["viable"])
# "VIABLE"
```

Viability verdicts:
- **VIABLE** (≤ 28 days): Proceed
- **MARGINAL** (29-56 days): Consider alternatives
- **NOT_VIABLE** (> 56 days): Need a different approach

## Sensitivity Tables

Explore the MDE vs. duration trade-off:

```python
from agentxp.stats import power_sensitivity_table

table = power_sensitivity_table(
    baseline_rate=0.08,
    mde_values=[0.03, 0.05, 0.10, 0.15, 0.20],
    daily_traffic_values=[1_000, 5_000, 10_000],
)

for row in table["table"]:
    print(f"MDE={row['mde_relative']:.0%}, "
          f"traffic={row['daily_traffic']:,}/day → "
          f"{row['days']} days ({row['viable']})")
```

## Reverse Power: "What Can I Detect?"

When sample size is fixed (e.g., you only have 3,000 users):

```python
from agentxp.stats import detectable_effect

mde = detectable_effect(
    n_per_group=3_000,
    baseline_rate=0.08,
)

print(mde["interpretation"])
# "With 3,000 users/group, can detect a 12.3% relative lift..."
```

## Rules of Thumb

| Scenario | Typical Sample Size per Group |
|----------|------------------------------|
| 10% conversion, detect 5% relative lift | ~30,000 |
| 10% conversion, detect 10% relative lift | ~8,000 |
| 50% conversion, detect 5% relative lift | ~3,200 |
| Revenue ($50 mean, $35 std), detect 5% lift | ~5,000 |

## What to Do When NOT_VIABLE

1. **Increase MDE** — detect only large effects
2. **Use a more sensitive metric** — e.g., click-through instead of purchase
3. **Increase traffic allocation** — allocate more users to the experiment
4. **Accept longer timeline** — if the team can wait
5. **Use CUPED** (v1.0) — reduce variance with pre-experiment data
6. **Consider quasi-experimental methods** — DiD, PSM (separate product)
