# The Experiment State Machine

Every experiment moves through a lifecycle. AgentXP enforces it — you can't analyze before powering, you can't report before interpreting, and you can't quietly revise a pre-registered design without an amendment reason.

## The 11 States

From `openxp/storage/lifecycle.py`:

| State | Meaning |
|-------|---------|
| **DESIGNING** | Initial state. Hypothesis, metrics, and decision rules are being drafted. |
| **POWERED** | Power analysis complete. Sample size and duration are known. |
| **COLLECTING** | Data is being collected in the product. AgentXP doesn't run the flag — this state marks that the experiment is live. |
| **ANALYZING** | Data loaded, SRM check passed, statistical tests running. |
| **INTERPRETED** | Ship/Investigate/Abort/Learn/Invalid decision has been made. |
| **REPORTED** | Stakeholder readout has been generated. |
| **SHIPPED** | Feature rolled out to 100%. |
| **COMPLETED** | Post-ship monitoring done. Terminal. |
| **ABANDONED** | Killed before conclusion. Terminal. |
| **INVALID** | Randomization broken beyond repair. Semi-terminal — you can retreat to DESIGNING and start fresh. |
| **BLOCKED** | Waiting on an external dependency (e.g., flag system is down). |

## Legal Transitions

Forward (normal flow):

```
DESIGNING → POWERED → COLLECTING → ANALYZING → INTERPRETED → REPORTED → SHIPPED → COMPLETED
```

From any state except terminals you can go to `ABANDONED`. From most working states you can go to `BLOCKED` and back.

Backward transitions (retreats) are allowed but require an `amendment_reason`:

- `POWERED → DESIGNING` — power analysis showed the design isn't viable; redesign
- `ANALYZING → COLLECTING` — SRM was fixable; re-collect after fixing the randomizer
- `INTERPRETED → COLLECTING` — underpowered null result; extend duration
- `INVALID → DESIGNING` — start fresh with a new design

That's it. You cannot skip from DESIGNING to COLLECTING. You cannot go from COLLECTING to REPORTED without the analyze and interpret steps in between. The hint message on every failed transition tells you exactly what to do.

## Why Amendments Exist

Pre-registration means nothing if you can silently rewrite the plan after seeing data. The amendment mechanism makes every retreat visible in the event log.

If you power an experiment, start collecting, then realize at day 3 that the MDE was too optimistic — you can retreat POWERED → DESIGNING, but the store forces you to record *why*:

```python
store.save_experiment(
    "checkout-redesign",
    updated_yaml_with_designing_status,
    amendment_reason="Re-scoped MDE from 5% to 10% after discovering baseline had drifted.",
)
```

The reason lands in `log.jsonl` as an `amendment_reason` field on the status-change event. When a stakeholder later asks "why did the numbers change?", the log has the answer.

## ExperimentStore Enforces Transitions

Every `save_experiment` call goes through the state machine:

```python
from openxp.storage.store import ExperimentStore

store = ExperimentStore()

# Legal forward transition
store.save_experiment("checkout-redesign", {
    "experiment": {"name": "Checkout Redesign", "status": "POWERED", ...}
})

# Illegal — skips COLLECTING and ANALYZING
store.save_experiment("checkout-redesign", {
    "experiment": {"name": "Checkout Redesign", "status": "REPORTED", ...}
})
# ValueError: [checkout-redesign] Illegal transition POWERED -> REPORTED.
# Allowed from POWERED: ['ABANDONED', 'BLOCKED', 'COLLECTING', 'DESIGNING'].
# Hint: Take one step at a time through ABANDONED -> BLOCKED -> COLLECTING -> DESIGNING.
```

The store also validates that the status string is one of the 11 canonical states. Typos like `"COLLECTION"` or `"Analyzing"` are rejected at save time, not discovered when the report generator silently skips an unknown state.

## Example Walkthrough

Here's a full happy-path run for the checkout redesign experiment, annotated with the store calls and transitions.

```python
from openxp.storage.store import ExperimentStore

store = ExperimentStore()
exp_id = "checkout-redesign-2026q2"

# --- 1. DESIGNING ---
designed = {
    "experiment": {
        "id": exp_id,
        "name": "Checkout Redesign Q2",
        "status": "DESIGNING",
        "hypothesis": {...},
        "metrics": {...},
        "variants": [...],
    }
}
store.save_experiment(exp_id, designed)

# --- 2. POWERED ---
# /experiment power has run; sample size and duration are known.
powered = dict(designed)
powered["experiment"]["status"] = "POWERED"
powered["experiment"]["power"] = {
    "alpha": 0.05, "power": 0.80,
    "sample_size_per_group": 12500,
    "duration_days": 14,
    "viable": "VIABLE",
}
store.save_experiment(exp_id, powered)

# --- 3. COLLECTING ---
# User has flipped the flag in their product. Mark the lifecycle.
powered["experiment"]["status"] = "COLLECTING"
store.save_experiment(exp_id, powered)

# (While COLLECTING, run /experiment monitor to check SRM + guardrails.)

# --- 4. ANALYZING ---
# Data is in. /experiment analyze runs the 8-question framework.
powered["experiment"]["status"] = "ANALYZING"
store.save_experiment(exp_id, powered)

store.save_analysis(exp_id, {
    "srm": {"verdict": "PASS"},
    "primary": {"lift": 0.042, "p_value": 0.018, "ci": [0.018, 0.066]},
    "guardrails": {"page_load_p95": "PASS"},
})

# --- 5. INTERPRETED ---
powered["experiment"]["status"] = "INTERPRETED"
store.save_experiment(exp_id, powered)

store.save_interpretation(exp_id, {
    "classification": "SHIP",
    "rationale": "Primary lift +4.2%, significant, guardrails clean.",
})

# --- 6. REPORTED ---
powered["experiment"]["status"] = "REPORTED"
store.save_experiment(exp_id, powered)

store.save_report(exp_id, "# Checkout Redesign Q2 — Readout\n\n...")

# --- 7. SHIPPED -> COMPLETED ---
powered["experiment"]["status"] = "SHIPPED"
store.save_experiment(exp_id, powered)

powered["experiment"]["status"] = "COMPLETED"
store.save_experiment(exp_id, powered)

# Full audit trail is now in log.jsonl
print(store.history(exp_id))
```

Every save writes atomically (tmp file + `os.replace`). Every state change appends an event to `log.jsonl`. The full experiment history is reconstructable from the log alone.

## Listing and Filtering

```python
# All experiments
store.list_experiments()

# Just the ones currently collecting data
store.list_experiments(status_filter="COLLECTING")
```

Useful for the monitoring cron job: iterate over COLLECTING experiments, run the health monitor on each.

## The Rules in One Sentence

> **Forward is free. Backward requires a reason. Terminals are terminal.**

## See Also

- `pre-registration.md` — the DESIGNING state and what goes in experiment.yaml
- `monitoring.md` — runs during COLLECTING
- `reading-results.md` — runs during ANALYZING
- PRD Appendix B — full state machine specification
