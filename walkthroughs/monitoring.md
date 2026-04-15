# Monitoring Running Experiments

Don't wait for the final analysis to find out your experiment is broken. Catch SRM drift, guardrail violations, and pacing problems while you can still fix them.

## Why Live Monitoring Matters

The default failure mode for an experiment is silent. You set up the flag, you wait two weeks, you run the analysis — and THEN you notice that 60% of users went to treatment because of a rollout bug, or that your p99 page load has been creeping up the whole time, or that your daily sample rate dropped to a trickle after day 3.

By then it's too late. You've burned two weeks and you have to start over.

Monitoring fixes this. You check in every day, you see the health signals, and you kill problems in hours instead of weeks.

## What a Monitor Checks

`openxp.monitoring` runs three independent health checks and aggregates them into a single traffic light.

Each individual check returns an internal verdict in the `PASS / WARNING / BLOCK` vocabulary (matching `openxp.stats`). `run_monitor` maps those to the user-facing `GREEN / YELLOW / RED` traffic lights and takes the worst-of-three.

### 1. SRM Trend

`srm_trend` runs a chi-square SRM check per time window (daily by default). A single aggregate check can mask mid-experiment drift — if yesterday's allocation was 50/50 and today's is 43/57, the cumulative test might still pass while the recent window is broken. Trending per window surfaces the first violation timestamp and the consecutive-violation tail.

### 2. Guardrail Health

`guardrail_health` runs the appropriate test per guardrail metric (Welch's t-test for continuous, proportion Z-test for binary) and compares the treatment effect against a non-inferiority margin (NIM). A guardrail is flagged as `BLOCK` when the **lower confidence bound** in the bad direction breaches the NIM — not the point estimate — which is the correct NI formulation.

### 3. Sample Accumulation

`sample_accumulation` compares `current_n` against `required_n` given `daily_traffic` and `days_elapsed`. It returns GREEN if on pace, YELLOW if running slow, and RED if stalled or severely behind. Day-0 returns a YELLOW "too early to tell" because pace cannot be computed with zero elapsed time.

## The Traffic-Light Verdict

`MonitorReport.status` is one of:

| Overall | Meaning |
|---------|---------|
| **GREEN** | All three checks PASS. Continue on the normal cadence. |
| **YELLOW** | At least one check WARNING, no BLOCK. Keep watching. |
| **RED** | At least one check BLOCK. Investigate before continuing. |

The per-check dicts under `report.checks["srm_trend"]`, `report.checks["guardrail_health"]`, `report.checks["sample_accumulation"]` each carry their own `verdict` (`PASS`/`WARNING`/`BLOCK`) and a plain-language `interpretation` string.

## The Python API

`run_monitor` takes an experiment id and a "data loader" — either a dict or a zero-arg callable returning one — with the context keys the three checks need:

```python
from openxp.monitoring import (
    run_monitor,
    srm_trend,
    guardrail_health,
    sample_accumulation,
    MonitorReport,
)

context = {
    "df": df,
    "treatment_col": "variant",
    "timestamp_col": "event_ts",          # required for SRM trending
    "guardrail_metrics": ["latency_ms", "converted"],
    "thresholds": {
        "latency_ms": {"nim": 0.02, "direction": "increase", "type": "continuous"},
        "converted":  {"nim": 0.05, "direction": "decrease", "type": "binary"},
    },
    "required_n": 20_000,
    "daily_traffic": 1500,
    "days_elapsed": 6,
    "planned_duration_days": 14,          # optional — inferred if omitted
    "srm_window": "1d",                   # optional, default "1d"
    "srm_threshold": 0.0005,              # optional, default 0.0005
    "alpha": 0.05,                        # optional
    "current_n": 9_000,                   # optional; defaults to len(df)
}

report: MonitorReport = run_monitor("checkout-redesign", context)
print(report.status)            # "GREEN" / "YELLOW" / "RED"
print(report.interpretation)    # one-paragraph summary
for rec in report.recommendations:
    print("-", rec)
```

### Running a single check

Each check function is also usable on its own. Real signatures:

```python
# SRM trend — requires a timestamp column
srm = srm_trend(
    df,
    treatment_col="variant",
    timestamp_col="event_ts",
    window="1d",                # convenience alias; "1h" / "1w" also work
    threshold=0.0005,
)
print(srm["verdict"], srm["first_violation_timestamp"])
print(srm["interpretation"])

# Guardrail health — thresholds is a per-metric dict with nim/direction/type
gh = guardrail_health(
    df,
    treatment_col="variant",
    guardrail_metrics=["latency_ms"],
    thresholds={
        "latency_ms": {"nim": 0.02, "direction": "increase", "type": "continuous"},
    },
    alpha=0.05,
)
print(gh["verdict"], gh["flagged_metrics"])

# Sample accumulation — takes scalars, not a dataframe
acc = sample_accumulation(
    current_n=9_000,
    required_n=20_000,
    daily_traffic=1500,
    days_elapsed=6,
    planned_duration_days=14,
)
print(acc["verdict"], acc["traffic_light"], acc["projected_completion"])
```

## Persisting Reports

Pass an `ExperimentStore` to `run_monitor` and the report is written to `{store.root}/{experiment_id}/analyses/{timestamp}.json`:

```python
from openxp.storage import ExperimentStore

store = ExperimentStore(root="~/.openxp/experiments")
report = run_monitor("checkout-redesign", context, store=store)
```

If the experiment id hasn't been registered yet (no `experiment.yaml` on disk), `run_monitor` returns the report anyway but sets `report.persistence_error` and appends a recommendation line noting the failure — you will see it, it won't silently succeed. Real I/O errors (`PermissionError`, `OSError`) propagate as usual.

## Wiring Into `/experiment monitor`

From Claude Code the skill wraps the module so you don't have to assemble the context dict by hand:

```
/experiment monitor sample-data/clean_ab.csv
```

The monitor mode loads the dataframe, reads the experiment.yaml for guardrail definitions and required_n, assembles the context, calls `run_monitor`, and prints a compact health report with the traffic light + per-check breakdown + recommendations.

## A Typical Monitoring Cadence

- **Day 0:** experiment goes live. `sample_accumulation` will return YELLOW "too early to tell" — that's expected; it just means pace can't be computed yet. Sanity-check that the three checks resolve at all.
- **Day 1-3:** daily monitor. Pacing is the main signal here. If you're already YELLOW on pace, it rarely improves on its own.
- **Mid-experiment:** the interesting window. `srm_trend` will catch any rollout drift. Guardrails are where production incidents show up.
- **Last few days:** the monitor becomes redundant with the final analysis, but guardrails are still worth watching.

A cron job that calls `run_monitor` every 6 hours and pages on-call on RED is about 20 lines and saves weeks of cleanup per year.

## Gotchas

- **`current_n` default is `len(df)`.** That's row count, not unique users. For panel data (multiple events per user) pass `current_n` explicitly in the context, or pass `current_n_fn=lambda d: d["user_id"].nunique()` to `run_monitor`.
- **`srm_trend` requires a timestamp column.** If `timestamp_col=None` the orchestrator skips SRM trending and returns a WARNING for that check so the report still has three entries.
- **Guardrail NIM is relative.** `nim=0.02` means "2% of baseline." If baseline is zero it falls back to absolute units — review the `nim_absolute` field in the result dict if that's a concern.
- **Day-0 sample accumulation is YELLOW, not GREEN.** Don't panic; it just means pace is unknowable with zero elapsed time.

## See Also

- `reading-results.md` — SRM and guardrails at final analysis time
- `pre-registration.md` — how guardrails are defined in experiment.yaml
- `state-machine.md` — monitoring runs in the COLLECTING state
- PRD §5.8 (Monitoring agent)
