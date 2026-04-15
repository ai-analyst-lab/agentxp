# Reusable Metric Definitions

Define a metric once, reference it everywhere. The OpenXP metric registry turns metrics into first-class YAML objects that experiments look up by name.

## Why Reusable Metrics

Without a registry, every experiment re-states the math: "primary metric is `checkout_completion_rate`, which is `checkouts / sessions`, and we winsorize the top 1%, and lower values are worse..." Across a year of experiments, definitions drift. One team's `checkout_completion_rate` excludes guest users; another team's doesn't. The numbers stop being comparable.

A central registry fixes this. You write one YAML file per metric. Every experiment that references `checkout_completion_rate` by name gets the same definition, the same test function, the same winsorization rules, the same "higher is better" orientation.

It's the data team's equivalent of a style guide — except it's enforced by code, not by Slack comments.

## The Schema

From `openxp/metrics/schema.py`:

| Field | Required | Meaning |
|-------|----------|---------|
| `name` | yes | Unique identifier (e.g. `checkout_completion_rate`) |
| `type` | yes | One of `proportion`, `mean`, `ratio` |
| `numerator` | yes | Column or expression for the numerator series |
| `description` | yes | Human-readable description |
| `denominator` | ratio only | Column or expression for the denominator |
| `unit` | no | Experimental unit (e.g. `user_id`, `session_id`) |
| `baseline_range` | no | `[low, high]` expected range — used for sanity checks |
| `winsorize` | no | Whether to winsorize before testing (default false) |
| `winsorize_bounds` | no | `[lower_quantile, upper_quantile]` (default `[0.01, 0.99]`) |
| `invert` | no | If true, lower values are better (e.g. bounce rate, error rate) |
| `tags` | no | Free-form list for organization |

## Example: checkout_completion_rate.yaml

```yaml
metric:
  name: checkout_completion_rate
  type: proportion
  numerator: checkouts_completed
  description: >
    Fraction of sessions that reach the order confirmation page. The
    canonical top-of-funnel conversion metric for the checkout team.
  unit: session_id
  baseline_range: [0.20, 0.45]
  winsorize: false
  invert: false
  tags: [conversion, checkout, primary]
```

Put this in `./metrics/checkout_completion_rate.yaml` (or `~/.openxp/metrics/`) and it gets auto-loaded into the default registry.

## Example: revenue_per_user.yaml

```yaml
metric:
  name: revenue_per_user
  type: mean
  numerator: revenue
  description: Mean revenue per exposed user over the experiment window.
  unit: user_id
  baseline_range: [0.0, 500.0]
  winsorize: true
  winsorize_bounds: [0.01, 0.99]
  invert: false
  tags: [revenue, continuous]
```

Winsorize is set to `true` because revenue is heavy-tailed — a handful of whales will dominate the variance if you don't trim.

## Example: page_load_time_p95.yaml

```yaml
metric:
  name: page_load_time_p95
  type: mean
  numerator: page_load_ms_p95
  description: 95th percentile page load latency. Performance guardrail.
  unit: session_id
  baseline_range: [1500, 3000]
  invert: true
  tags: [performance, guardrail]
```

Note `invert: true`. Lower latency is better, so the interpretation layer flips the direction of significance tests. A "significant increase" here becomes a guardrail violation, not a win.

## How Experiments Reference Metrics

In `experiment.yaml`, metrics are named — not redefined:

```yaml
experiment:
  id: checkout-redesign-2026q2
  metrics:
    primary:
      name: checkout_completion_rate
      mde: 0.05
      baseline: 0.35
    secondary:
      - name: revenue_per_user
    guardrail:
      - name: page_load_time_p95
        threshold: 3000
        direction: do_not_increase
```

The experiment provides the experiment-specific knobs (MDE, baseline, thresholds). The metric definition provides the rest (type, winsorization, inversion, test function).

## Loading the Registry

```python
from openxp.metrics.registry import MetricRegistry, load_all_metrics

# Autoloads from ./metrics or ~/.openxp/metrics
registry = load_all_metrics()

print(registry.list())
# ['checkout_completion_rate', 'page_load_time_p95', 'revenue_per_user']

metric = registry.get("checkout_completion_rate")
print(metric.type, metric.numerator, metric.tags)
# proportion checkouts_completed ['conversion', 'checkout', 'primary']
```

Or point at a specific directory:

```python
registry = MetricRegistry(metrics_dir="./my-team/metrics")
```

## From Metric to Test Function

Each metric type maps to the right stats function:

```python
from openxp.metrics.schema import to_test_function

metric = registry.get("checkout_completion_rate")   # type: proportion
test_fn = to_test_function(metric)                  # openxp.stats.proportion_test

metric = registry.get("revenue_per_user")           # type: mean
test_fn = to_test_function(metric)                  # openxp.stats.welch_test

metric = registry.get("revenue_per_session")        # type: ratio
test_fn = to_test_function(metric)                  # openxp.stats.ratio_metric_test
```

The analyzer agent uses this mapping automatically. You almost never call `to_test_function` directly — but it's the hook that keeps metrics and tests in sync.

## Validation

Every load validates the YAML. Bad definitions fail loudly:

```python
from openxp.metrics.schema import validate, MetricValidationError

try:
    validate({"name": "foo", "type": "proportion"})  # missing numerator, description
except MetricValidationError as e:
    print(e)
# missing required field 'numerator' in metric definition
```

The registry will refuse to load a broken file rather than silently skip it. This keeps the "metrics directory" honest.

## Tips

1. **One metric per file.** Easier to review, easier to diff, easier to grep.
2. **Tag aggressively.** `primary`, `guardrail`, `revenue`, `performance` — tags are how you answer "what are all our checkout guardrails?" without reading every file.
3. **Set `invert: true` for any "less is better" metric.** Latency, errors, churn, bounce rate. The interpretation layer does the right thing when the flag is set.
4. **Use baseline_range as a sanity check.** If a running experiment reports a baseline outside the expected range, the monitor can flag it before you waste weeks on bad data.
5. **Version through git.** The metrics directory is plain YAML. PRs on metric definitions are the same as PRs on code. That's the point.

## See Also

- `pre-registration.md` — how experiment.yaml references metrics by name
- `reading-results.md` — how the test function gets chosen from metric type
- PRD §5.7 (Metric definition schema)
