# Sequential Testing: Peeking Without Penalty

Fixed-horizon A/B tests break if you look at results early. Sequential tests are designed to let you peek — every observation is a valid decision point.

## Why Peeking Breaks Fixed-Horizon Tests

A standard Welch's t-test controls Type I error at alpha = 0.05 **if and only if** you look exactly once, at a pre-specified sample size.

If you peek — say, once a day — and stop the first time p < 0.05, the realized false positive rate is much higher than 5%. With 10 daily peeks on a true null, your chance of a spurious "significant" result climbs to roughly 20-30%. With continuous peeking, it approaches 100% as the experiment runs long enough.

The intuition: the t-statistic does a random walk under the null. Given enough looks, it will cross any fixed threshold. Fixed-horizon tests require you to ignore everything until the finish line.

Nobody actually ignores the data. So you need a test that is valid to peek at.

## Two Families

### 1. Mixture SPRT (always-valid CIs)

Based on Robbins (1970) and modernized by Howard, Ramdas, McAuliffe & Sekhon (2021). Deployed in production at Optimizely, Netflix, and others.

**Key property:** the 95% CI has simultaneous coverage over ALL sample sizes. You can peek every observation. You can stop for any reason. The coverage guarantee holds.

**Cost:** the CI is wider than a fixed-horizon CI at the same n. You pay for the freedom.

**Use when:** continuous monitoring, no fixed interim schedule, you want a dashboard anyone on the team can read at any time.

### 2. Group Sequential (alpha spending)

Pre-specify a fixed number of interim looks (e.g., 5), then allocate the alpha budget across them using a spending function.

- **O'Brien-Fleming (1979):** very conservative early, approaches fixed-horizon at the final look. You're unlikely to stop at the first interim; the full alpha is still there at the end.
- **Pocock (1977):** roughly constant boundary at each interim. Equal chance of stopping at each look.

**Cost:** you must commit to the interim schedule in advance. Unscheduled peeks are not covered.

**Use when:** pre-registered trials, regulated contexts, scheduled weekly reviews.

## Always-Valid CI with mSPRT

```python
from agentxp.stats.sequential import msprt_test

result = msprt_test(
    control=control_revenue,
    treatment=treatment_revenue,
    alpha=0.05,
)

print(result["decision"])         # "STOP_REJECT" or "CONTINUE"
print(result["ci_lower"], result["ci_upper"])
print(result["interpretation"])
# "Always-valid CI excludes zero: treatment (12.8421) is higher than control
#  (11.9203) by +0.9218 (95% AV CI: [+0.1244, +1.7192]). STOP and reject null."
```

The `decision` field is the peek-safe verdict:

- **STOP_REJECT** — the always-valid CI excludes zero. You can stop and declare a winner; Type I error is still ≤ alpha.
- **CONTINUE** — CI still includes zero. Keep collecting. Peek again whenever you want.

That's the whole protocol: peek, check `decision`, stop or continue.

For the CI alone (no stop/continue logic), there's a focused endpoint:

```python
from agentxp.stats.sequential import always_valid_ci

ci = always_valid_ci(control, treatment, alpha=0.05)
print(ci["lower"], ci["upper"], ci["width"])
```

## Sequential Proportion Test

For binary metrics (conversion rate, CTR):

```python
from agentxp.stats.sequential import sequential_proportion_test

result = sequential_proportion_test(
    c_success=420, c_n=5120,
    t_success=468, t_n=5089,
    alpha=0.05,
)
print(result["decision"], result["interpretation"])
```

Same decision semantics: STOP_REJECT or CONTINUE.

## Group Sequential Boundaries

If you need a scheduled-interim design — for example, weekly looks over 5 weeks:

```python
from agentxp.stats.sequential import group_sequential_boundaries

obf = group_sequential_boundaries(n_interims=5, alpha=0.05, spending="obrien_fleming")
print(obf["boundaries"])
# [4.56, 3.23, 2.63, 2.28, 2.04]  ← z-threshold at each look

pocock = group_sequential_boundaries(n_interims=5, alpha=0.05, spending="pocock")
print(pocock["boundaries"])
# [2.41, 2.41, 2.41, 2.41, 2.41]  ← roughly constant
```

Then at each interim, compute the standard z-statistic from your Welch test and compare it to `boundaries[k]` at look `k`. If `|z| > boundary`, stop and reject.

## When to Use Which

| Situation | Pick |
|-----------|------|
| Exec asks for daily check-ins | mSPRT (`msprt_test`) |
| Pre-registered clinical-style trial with 5 weekly looks | Group sequential, O'Brien-Fleming |
| Early-stopping experiment with equal chances to stop at each look | Group sequential, Pocock |
| You might want to stop at any moment | mSPRT |
| Tightest possible CI at a fixed horizon, no peeking | Fixed-horizon Welch (see `reading-results.md`) |

## The Peeking-is-Safe Rule

With a sequential test, the only rule is:

> **Use the sequential method for every look, and use it consistently.**

You cannot mix fixed-horizon and sequential analyses on the same experiment. If you started with `welch_test` and then switched to `msprt_test` because the fixed test wasn't significant yet, the Type I guarantee is gone.

Pick one family in the experiment.yaml design phase, stick with it.

## Sample-Size Impact

A sequential test needs, on average, more samples than a fixed-horizon test at the same power — that's the price of optional stopping. Typical inflation:

- mSPRT: ~25-40% more samples than fixed Welch at the same MDE and power
- O'Brien-Fleming: ~5-15% more (most of the alpha is spent at the end)
- Pocock: ~20-30% more (alpha spread evenly)

Rule of thumb: if your team will definitely peek, the sequential overhead is free. If your team genuinely will not peek, fixed-horizon wins on sample efficiency.

## See Also

- `reading-results.md` — fixed-horizon interpretation
- `pre-registration.md` — commit to sequential vs fixed in experiment.yaml
- PRD §5.10 (Sequential testing)
- Howard, Ramdas, McAuliffe, Sekhon (2021), "Time-uniform, nonparametric, nonasymptotic confidence sequences"
- Johari et al. (2017), "Peeking at A/B tests" — the Optimizely paper
