# Pre-Registration: Why and How

Write your decision rules BEFORE seeing results. This is the single most important practice in experimentation.

## Why Pre-Register?

Without pre-registration, you'll:
- Move the goalposts after seeing results ("well, it didn't hit 5% but 3% is still good...")
- Cherry-pick favorable segments or time windows
- Rationalize shipping features that didn't actually work
- Lose credibility with data-savvy stakeholders

With pre-registration, you:
- Make decisions based on pre-committed criteria
- Avoid post-hoc rationalization
- Build trust with stakeholders ("we said we'd ship if X, and X happened")
- Create an audit trail of experimental rigor

## The experiment.yaml File

OpenXP uses `experiment.yaml` as the pre-registration document. It captures everything BEFORE data collection begins.

### Creating It

```
/experiment design
```

OpenXP walks you through an interactive conversation and produces the YAML.

### What It Contains

```yaml
experiment:
  id: checkout-redesign-2026q1
  name: "Checkout Redesign Test"
  status: DESIGNING

  # What you believe will happen
  hypothesis:
    action: "Redesign checkout to single-page flow"
    metric: "checkout_completion_rate"
    direction: "increase"
    magnitude: "5% relative lift"
    mechanism: "Reduced friction from fewer page loads"

  # How you'll measure success
  metrics:
    primary:
      name: checkout_completion_rate
      type: proportion
      mde: 0.05           # smallest lift worth detecting
      baseline: 0.35      # current conversion rate
    secondary:
      - name: revenue_per_user
        type: continuous
    guardrail:
      - name: page_load_time_p95
        threshold: 3000    # must not exceed 3 seconds
        direction: do_not_increase

  # How you'll split traffic
  variants:
    - name: control
      allocation: 0.50
      is_control: true
    - name: treatment
      allocation: 0.50

  # Statistical parameters
  power:
    alpha: 0.05
    power: 0.80
    sample_size_per_group: 12500   # computed by /experiment power
    duration_days: 14              # computed from traffic
    viable: VIABLE

  # What you'll do with each result
  decision_rules:
    ship_if: "Primary significant positive, no guardrail violations"
    do_not_ship_if: "Any guardrail violation OR negative primary"
    inconclusive_if: "Underpowered null — extend or increase allocation"
    emergency_stop: "Page load > 5s — halt immediately"
```

## The Most Important Section: Decision Rules

Write these BEFORE you see any data:

| If this happens... | We will... |
|---------------------|-----------|
| Primary positive, guardrails clean | **Ship to 100%** |
| Primary positive, guardrail degraded | **Investigate** — quantify trade-off before deciding |
| Primary null, well-powered | **Don't ship** — feature doesn't work |
| Primary null, underpowered | **Extend** the experiment or increase traffic |
| Primary negative | **Kill** the feature |
| SRM detected | **Invalidate** — fix randomization and re-run |

## The Lifecycle

```
DESIGNING → POWERED → COLLECTING → ANALYZING → INTERPRETED → REPORTED
```

Each stage updates the YAML. The file is the single source of truth for the experiment's entire history.

## Tips

1. **Be specific about MDE.** "5% relative lift" not "some improvement."
2. **Name your guardrails.** If you can't name what must not degrade, you don't understand the risks.
3. **Set the emergency stop.** What's bad enough to kill the experiment immediately?
4. **Share the YAML with stakeholders.** Getting buy-in on decision rules prevents arguments later.
5. **Don't change decision rules after peeking at data.** That defeats the entire purpose.
