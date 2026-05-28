# Bayesian A/B Testing

Instead of "is the effect significant?", ask "what's the probability treatment is better, and how much do I lose if I'm wrong?"

## Frequentist vs Bayesian in One Paragraph

A frequentist test asks: *if there were truly no effect, how weird would my data look?* If the answer is "very weird" (p < 0.05), you reject the null. A Bayesian test asks: *given the data, what's the probability the treatment is actually better than control?* The frequentist answer is a p-value you must interpret. The Bayesian answer is a probability stakeholders can actually use: "84% chance treatment wins, expected loss 0.12%, ship it."

Both are valid. Bayesian is easier to explain, easier to stop early, and easier to turn into a decision rule.

## What AgentXP Gives You

Two conjugate models. No MCMC, no PyMC, no slow sampling. Just closed-form posterior updates that run in milliseconds.

1. **Beta-Binomial** for conversion rates, CTRs, any binary metric
2. **Normal-Normal** for revenue, duration, any continuous metric

For each test, AgentXP returns:

- **P(treatment > control)** — posterior probability the treatment wins
- **95% credible interval** on the relative lift
- **Expected loss** for shipping treatment vs shipping control
- **Decision:** SHIP / ABORT / CONTINUE

## Expected Loss: the Decision Criterion

This is the industry-standard stopping rule (GrowthBook, VWO, Dynamic Yield).

```
loss_ship_treatment = E[max(control - treatment, 0)]
loss_ship_control   = E[max(treatment - control, 0)]
```

In English: *if I pick treatment and treatment is actually worse, how much do I lose on average?*

The rule:

- **SHIP** when `loss_ship_treatment < threshold` (default 0.5% relative) AND `P(T > C) >= 0.5`
- **ABORT** when `loss_ship_control < threshold` AND `P(T > C) < 0.5`
- **CONTINUE** otherwise

"0.5% relative" is the "threshold of caring": you're willing to accept up to a 0.5% regret in exchange for stopping now. Tune it to your business context.

## Beta-Binomial for Conversion

```python
from openxp.stats.bayesian import beta_binomial_test

result = beta_binomial_test(
    c_success=412, c_n=5020,
    t_success=468, t_n=5011,
    prior_alpha=1.0,
    prior_beta=1.0,
)

print(result["decision"])
# "SHIP"
print(result["interpretation"])
# "SHIP treatment. P(T > C) = 0.987, posterior rates 0.0821 -> 0.0933
#  (lift +13.6%, 95% CrI [+3.1%, +24.7%]). Relative expected loss from shipping T
#  is 0.0412%, below threshold 0.50%."
```

Key fields in the returned dict:

- `prob_treatment_better` — P(T > C)
- `posterior_mean_control` / `posterior_mean_treatment`
- `lift_ci_lower` / `lift_ci_upper` — 95% credible interval on relative lift
- `expected_loss_ship_treatment_rel` — the number you compare against threshold
- `decision` — SHIP / ABORT / CONTINUE

## Normal-Normal for Continuous Metrics

```python
from openxp.stats.bayesian import normal_normal_test

result = normal_normal_test(
    control=control_revenue,      # array-like
    treatment=treatment_revenue,
    prior_mean=0.0,
    prior_sd=1e6,                 # weakly informative
)

print(result["decision"], result["interpretation"])
```

Under the hood: Jeffreys prior on sigma^2, Gaussian prior on the mean, conjugate Normal-Inverse-Gamma update. With the default `prior_sd=1e6` it reduces to the textbook Student-t posterior on the mean — basically a "Bayesian version of Welch's t-test."

## How to Set Priors

**Default (Beta(1,1) / weakly informative Normal).** Uniform on [0,1] for conversion; essentially flat on the mean for continuous. Safe starting point. Use when you have no strong prior beliefs or you want to match GrowthBook's defaults.

**Jeffreys (Beta(0.5, 0.5)).** Improper-ish reference prior. Slightly more weight near 0 and 1 than uniform. Use when you want the most "objective" Bayesian answer possible.

**Informative (Beta(100, 900)).** Encodes a prior belief: "I've seen enough of this metric to know the baseline is around 10%, give or take a couple points." The posterior shrinks toward this belief on small samples. Use when you have solid historical data and want to stabilize early results.

Rule of thumb: for launches of known features, weakly informative. For genuinely new features with no history, Jeffreys or uniform. For stable production metrics where you'd be shocked by drift, informative.

## The Ship / Abort / Continue Rule

```python
result = beta_binomial_test(...)

if result["decision"] == "SHIP":
    # Expected loss from shipping treatment is below threshold.
    # Treatment is probably better and the worst case is tolerable.
    ship_it()
elif result["decision"] == "ABORT":
    # Expected loss from shipping control is below threshold.
    # Treatment is probably worse; killing it costs little.
    kill_feature()
else:
    # CONTINUE — not enough data yet. Keep collecting.
    wait_and_peek_later()
```

Unlike frequentist p-values, the Bayesian decision rule is peek-safe by construction. The posterior only gets sharper with more data; expected loss only moves monotonically toward the true value. You can call `beta_binomial_test` daily and act on the decision whenever it flips.

That said — be careful with very small samples and uniform priors. With n=20, the posterior is still dominated by the prior, and `CONTINUE` will be the right call 99% of the time.

## Tuning the Thresholds

```python
result = beta_binomial_test(
    c_success=400, c_n=5000,
    t_success=420, t_n=5000,
    loss_threshold_ship=0.002,   # stricter: 0.2% relative loss
    loss_threshold_abort=0.002,
)
```

Lower thresholds → fewer SHIPs, less regret per decision, longer experiments. Higher thresholds → more SHIPs, more regret, faster throughput. Pick based on reversibility: a homepage redesign deserves 0.1%; a button color deserves 2%.

## When to Use Bayesian vs Frequentist

| Situation | Pick |
|-----------|------|
| Exec wants "probability treatment wins" | Bayesian |
| Regulated or pre-registered study | Frequentist (easier to defend the decision rule) |
| You want to peek without inflating Type I | Bayesian or sequential frequentist |
| You need an expected-loss decision rule | Bayesian |
| Your team is already fluent in p-values | Frequentist |

Both produce the same ship/don't-ship call on clear-cut experiments. They diverge on the borderline cases — and that's where having both tools in the toolkit matters.

## See Also

- `reading-results.md` — frequentist interpretation
- `sequential.md` — frequentist peek-safe alternative
- PRD §5.11 (Bayesian A/B testing)
- GrowthBook documentation on expected loss: https://docs.growthbook.io/statistics/overview
