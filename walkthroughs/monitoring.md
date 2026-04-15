# Monitoring Running Experiments

Don't wait for the final analysis to find out your experiment is broken. Catch SRM drift, guardrail violations, and pacing problems while you can still fix them.

## Why Live Monitoring Matters

The default failure mode for an experiment is silent. You set up the flag, you wait two weeks, you run the analysis — and THEN you notice that 60% of users went to treatment because of a rollout bug, or that your p99 page load has been creeping up the whole time, or that your daily sample rate dropped to a trickle after day 3.

By then it's too late. You've burned two weeks and you have to start over.

Monitoring fixes this. You check in every day (or every hour if you like), you see the health signals, and you kill problems in hours instead of weeks.

## What a Monitor Checks

Three independent health signals, each with its own verdict:

### 1. SRM Trending

Sample Ratio Mismatch isn't a single yes/no check — it can emerge mid-experiment as one variant's randomizer drifts. The monitor runs a chi-square SRM check not just on the cumulative counts, but on a rolling window (last 24 hours, last 7 days) to spot drift.

If yesterday's allocation was 50/50 and today's is 43/57, the cumulative test might still pass while the recent data is broken. The trending view catches it.

### 2. Guardrail Health

Your experiment.yaml names guardrails (p95 page load, error rate, CSAT, whatever). The monitor checks each one against its threshold and reports:

- **GREEN** — well within threshold
- **YELLOW** — approaching threshold, worth watching
- **RED** — threshold breached, emergency stop should fire

### 3. Sample Accumulation

Are you on pace to hit the required sample size by the end of the planned duration?

- **ON_PACE** — trajectory meets the target
- **SLOW** — you'll finish late; consider extending or re-powering
- **STALLED** — allocation is near zero; something is wrong with the assignment pipeline

## The Traffic-Light Verdict

The monitor rolls these three signals into a single verdict:

| Overall | Meaning |
|---------|---------|
| **HEALTHY** | Ship the dashboard screenshot to Slack and move on |
| **WATCH** | One yellow signal — keep an eye on it, no action yet |
| **WARN** | One red signal or multiple yellows — human review needed |
| **STOP** | SRM red or guardrail red — kill the experiment, investigate |

The verdict is designed to be scannable. If you have 40 running experiments, a HEALTHY wall of green tells you to spend your attention on the handful of yellows and reds.

## Wiring Into /experiment monitor

From Claude Code:

```
/experiment monitor sample-data/clean_ab.csv
```

The monitor agent loads the data, pulls the experiment.yaml for guardrail definitions, calls the monitoring module, and prints a compact health report.

## The Python API

```python
from openxp.monitoring import (
    run_monitor,
    srm_trend,
    guardrail_health,
    sample_accumulation,
)

# One-shot full health check
report = run_monitor(
    data=df,
    experiment_yaml="experiments/checkout-redesign/experiment.yaml",
)
print(report["verdict"])          # "HEALTHY" / "WATCH" / "WARN" / "STOP"
print(report["interpretation"])   # human-readable summary

# Or call individual checks
srm = srm_trend(df, treatment_col="variant", window_days=7)
print(srm["verdict"], srm["interpretation"])

guardrails = guardrail_health(
    df,
    guardrails=[
        {"name": "page_load_p95", "threshold": 3000, "direction": "do_not_increase"},
    ],
)
print(guardrails["verdict"])

pacing = sample_accumulation(
    df,
    target_n=25000,
    planned_duration_days=14,
    elapsed_days=6,
)
print(pacing["verdict"], pacing["interpretation"])
```

> **Note:** the `openxp.monitoring` module is part of W7 (monitoring agent), shipping in parallel with this walkthrough. The API surface above is the planned contract — function names and return dicts are stable; field names may be finalized when W7 lands.

## A Typical Monitoring Cadence

- **Day 0:** experiment goes live. Run `/experiment monitor` once to sanity-check allocation at low sample size. Don't panic at noisy SRM — chi-square is unstable below a few hundred observations per arm.
- **Day 1-3:** daily monitor. Pacing is the main signal here. If you're already SLOW, it won't improve on its own.
- **Mid-experiment:** the interesting window. SRM trending will catch any rollout drift. Guardrails are where production incidents show up.
- **Last few days:** monitor becomes redundant with the final analysis. At this point you're mostly watching for last-minute guardrail surprises.

Automate it. A cron job that runs `/experiment monitor` every 6 hours and posts STOPs to your on-call channel is 20 lines and saves you weeks of cleanup per year.

## Common Monitor Triggers and What to Do

| Trigger | Likely cause | Action |
|---------|-------------|--------|
| SRM trend goes red after day 3 | One arm of the flag is failing to assign | Stop, debug the flag, restart as a new experiment |
| Guardrail red on page load | Treatment shipped a blocking JS bundle | Stop, fix the bundle, re-run |
| Pacing STALLED | Assignment pipeline is broken upstream | Fix the pipeline, extend the experiment to make up the lost window |
| Guardrail yellow on error rate | Edge case bug in treatment | Watch it, decide at analysis time whether INVESTIGATE or SHIP |
| SRM yellow first 24h, green after | Normal startup noise from cache warm-up | Ignore |

## See Also

- `reading-results.md` — SRM and guardrails at final analysis time
- `pre-registration.md` — how guardrails are defined in experiment.yaml
- `state-machine.md` — monitoring runs in the COLLECTING state
- PRD §5.8 (Monitoring agent)
