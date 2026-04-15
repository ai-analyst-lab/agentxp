# Reading Experiment Results

How to interpret p-values, confidence intervals, and effect sizes without a statistics degree.

## The Three Numbers That Matter

Every experiment result has three key numbers:

### 1. Relative Lift (the "what")
How much the treatment changed the metric, as a percentage.

> "Treatment increased conversion by +4.2%"

This is the point estimate — your best guess of the true effect.

### 2. Confidence Interval (the "how sure")
The range where the true effect likely falls (95% of the time).

> "95% CI: [+1.8%, +6.6%]"

- **Narrow CI** = precise estimate, lots of data
- **Wide CI** = noisy estimate, need more data
- **CI excludes 0** = statistically significant
- **CI includes 0** = not statistically significant

### 3. p-value (the "is it real")
The probability of seeing this result if there's actually no effect.

> "p = 0.003"

- p < 0.05 → statistically significant (reject the null)
- p > 0.05 → not significant (can't rule out chance)

**Common misconception:** p = 0.03 does NOT mean "3% chance the result is wrong." It means "3% chance of seeing this result if the treatment has zero effect."

## Statistical Significance vs Practical Significance

A result can be:
- **Statistically significant but practically meaningless:** +0.1% conversion lift with p = 0.02. Real effect, but too small to matter.
- **Practically significant but statistically non-significant:** +8% revenue lift with p = 0.12. Potentially large effect, but noisy (underpowered).

Always check BOTH:
1. Is p < 0.05? (statistical significance)
2. Is the effect big enough to matter? (practical significance via Cohen's d or business impact)

## Effect Sizes

Cohen's d tells you if the effect is meaningfully large:

| Cohen's d | Label | Interpretation |
|-----------|-------|---------------|
| < 0.2 | Negligible | Hard to notice in practice |
| 0.2 - 0.5 | Small | Detectable with careful measurement |
| 0.5 - 0.8 | Medium | Obvious to most observers |
| > 0.8 | Large | Cannot be missed |

Most experiment effects in tech are d < 0.1. This is normal — you're optimizing within an existing product.

## Reading an OpenXP Analysis Report

### SRM Verdict (check first!)
- **PASS:** Randomization is clean. Trust the results.
- **WARNING:** Marginal issue. Proceed with caution.
- **BLOCK:** Randomization is broken. Results are unreliable. Stop.

### Treatment Effect Table
```
| Metric      | Control | Treatment | Lift    | p-value | Sig? |
|-------------|---------|-----------|---------|---------|------|
| Conversion  | 8.2%    | 8.9%      | +8.5%   | 0.018   | Yes  |
| Revenue/user| $4.12   | $4.28     | +3.9%   | 0.134   | No   |
| Page load   | 2.1s    | 2.3s      | +9.5%   | 0.002   | Yes  |
```

Reading this:
- Primary metric (conversion) is up 8.5% and significant
- Secondary (revenue) trends positive but not significant
- Guardrail (page load) degraded significantly — this triggers INVESTIGATE

### Business Impact
```
Conservative: $180K/year (CI lower bound)
Best estimate: $340K/year (point estimate)
Optimistic: $500K/year (CI upper bound)
```

Use the conservative estimate for investment decisions.

## Common Pitfalls

1. **Peeking at results** — checking before reaching planned sample size inflates false positives. Use sequential testing (v1.0) if you need to peek.
2. **Cherry-picking segments** — "it works for iOS users!" without correction is p-hacking. Use multiple comparison correction.
3. **Ignoring underpowered nulls** — "p > 0.05 means it doesn't work" is only true if the experiment was adequately powered.
4. **Confusing correlation with causation** — only randomized experiments establish causation. Observational results require caveats.
