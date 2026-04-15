# CUPED: Variance Reduction with Pre-Experiment Data

Cut your required sample size without changing your metric — by regressing out the noise you already know about.

## What CUPED Is

CUPED (Controlled-experiment Using Pre-Experiment Data) is a variance reduction technique from Microsoft's ExP team (Deng et al. 2013). The trick: if you have a pre-experiment measurement that correlates with the post-experiment outcome, you can subtract off the "expected" part of each user's outcome and run the A/B test on the residuals.

The treatment effect estimate is unbiased. The confidence interval gets tighter. Same data, more signal.

## The Math Intuition

For pre-experiment covariate `X` and post-experiment outcome `Y`, compute:

```
theta = Cov(Y, X) / Var(X)
Y* = Y - theta * (X - mean(X))
```

Then run your usual Welch's t-test on `Y*` instead of `Y`.

The variance of the adjusted outcome is reduced by a factor of `(1 - rho^2)`, where `rho = corr(Y, X)`. So the theoretical variance reduction as a percentage is just `rho^2 * 100`.

That's it. CUPED is a one-line OLS regression dressed up in experimentation language.

## Expected Variance Reduction

| Correlation ρ | Variance reduction | Sample-size reduction |
|---------------|-------------------|----------------------|
| 0.3 | 9% | ~9% |
| 0.5 | 25% | ~25% |
| 0.7 | 49% | ~49% |
| 0.9 | 81% | ~81% |

At ρ = 0.7, you need roughly half the users to detect the same effect. At ρ = 0.9, you need a fifth. This is why Netflix, Microsoft, Booking, and LinkedIn all run CUPED in production.

## When to Use It

Good candidates for the pre-experiment covariate:
- **User-level historical metric** — a user's pre-experiment revenue is highly correlated with their post-experiment revenue
- **Engagement baseline** — sessions-in-prior-week predicts sessions-in-experiment
- **Any stable user trait** — tenure, plan, region

Bad candidates:
- Anything measured DURING the experiment (breaks causal identification)
- Random noise (ρ ≈ 0, zero benefit)
- New users with no history (theta has nothing to work with)

## API Example

```python
import numpy as np
from openxp.stats.cuped import cuped_welch_test, variance_reduction

# Pre-experiment revenue (prior 28 days) — correlates with post-experiment revenue
control_pre = np.array([12.1, 8.4, 22.3, 5.1, 17.8, ...])
control_post = np.array([14.2, 9.0, 24.7, 6.3, 19.1, ...])
treatment_pre = np.array([11.8, 9.2, 21.6, 4.8, 18.3, ...])
treatment_post = np.array([15.4, 10.1, 26.8, 7.2, 21.0, ...])

result = cuped_welch_test(
    control_pre, control_post,
    treatment_pre, treatment_post,
    alpha=0.05,
)

print(result["interpretation"])
# "CUPED theta = 1.0834 (pooled rho = 0.712, expected variance reduction = 50.7%).
#  Realized within-group variance reduction = 49.2%. Adjusted CI is narrower than
#  the unadjusted CI (unadj p = 0.0421). Significant adjusted effect: diff = +1.304,
#  p = 0.0038."
```

The return dict exposes the adjusted Welch result (`p_value`, `ci_lower`, `ci_upper`, `diff`, `relative_lift_pct`) side-by-side with the unadjusted values (`unadjusted_p_value`, `unadjusted_ci_lower`, `unadjusted_ci_upper`) so you can show stakeholders how much CUPED actually bought you.

## Preview: Will CUPED Help?

Before rewiring your analysis, use the cheap diagnostic:

```python
from openxp.stats.cuped import variance_reduction

preview = variance_reduction(y_pre=all_pre, y_post=all_post)
print(preview["interpretation"])
# "Pre/post correlation rho = 0.412 (moderate). Expected variance reduction = 17.0%.
#  CUPED is worthwhile on this metric."
```

If rho comes back below 0.1, don't bother — the overhead of tracking a pre-period covariate isn't worth a 1% win.

## Manual Adjustment

If you want the adjusted series for your own downstream work:

```python
from openxp.stats.cuped import cuped_adjust

adj = cuped_adjust(y_pre=all_pre, y_post=all_post, treatment=treatment_flags)
print(adj["theta"], adj["variance_reduction_pct"])
# Use adj["control_adjusted"] and adj["treatment_adjusted"] for downstream analysis
```

## The One Gotcha

**Compute theta once, pre-analysis, on all pooled data.**

If you compute theta separately per variant, or recompute after peeking at the treatment effect, you introduce bias. `cuped_welch_test` does this correctly — it estimates theta on the pooled pre/post across both arms before adjusting. If you're rolling your own, do the same.

Also: CUPED is for unbiased variance reduction on the same estimand. It does not fix SRM, it does not fix selection bias, and it does not give you more users. Run the SRM gate first, then CUPED.

## See Also

- `power-calculation.md` — use CUPED's expected variance reduction to shrink required sample size
- PRD §5.9 (CUPED) for the decision rules
- Deng et al. 2013, "Improving the Sensitivity of Online Controlled Experiments by Utilizing Pre-Experiment Data"
