# Your First Experiment with OpenXP

A step-by-step walkthrough from hypothesis to ship/no-ship decision.

## Prerequisites

```bash
pip install -e .
```

## Step 1: Design Your Experiment

```
/experiment design
```

OpenXP will ask you:
1. What change are you making?
2. What metric do you expect to move?
3. In which direction and by how much?
4. Why do you believe this?

It produces an `experiment.yaml` pre-registration file.

## Step 2: Power Calculation

```
/experiment power
```

OpenXP reads your experiment.yaml and computes:
- Required sample size per group
- Estimated duration at your traffic level
- A sensitivity table showing MDE vs duration trade-offs
- Viability verdict: VIABLE, MARGINAL, or NOT_VIABLE

## Step 3: Run Your Experiment

Collect data according to your experiment design. OpenXP doesn't manage randomization or data collection — that's your product's job.

While collecting, you can monitor health:

```
/experiment monitor my_data.csv
```

This checks for SRM issues, guardrail violations, and sample accumulation.

## Step 4: Analyze Results

Once data collection is complete:

```
/experiment analyze my_results.csv
```

OpenXP runs the 8-question analysis framework:
1. Setup validation (SRM check)
2. Treatment effect (with CI and p-value)
3. Statistical reliability (effect size, power)
4. Segment analysis (Simpson's paradox check)
5. Duration adequacy
6. Business impact projection
7. Ship recommendation
8. Follow-up suggestions

## Step 5: Interpret Results

```
/experiment interpret
```

OpenXP walks the Result Interpretation Tree and classifies the outcome:
- **SHIP** — positive result, clean guardrails
- **INVESTIGATE** — positive but guardrail concerns
- **ABORT** — negative result
- **LEARN** — null result (adequately powered or not)
- **INVALID** — SRM detected, data unreliable

## Step 6: Generate Report

```
/experiment report
```

Produces a stakeholder-ready report. Add `executive`, `technical`, or `cross-functional` for audience-specific formatting.

## Try It With Sample Data

OpenXP includes practice datasets in `sample-data/`:

```
/experiment analyze sample-data/clean_ab.csv
```

Try different scenarios:
- `clean_ab.csv` — positive result, clean guardrails
- `no_effect.csv` — null result, adequately powered
- `srm_violation.csv` — randomization failure
- `guardrail_violation.csv` — positive primary, degraded guardrail
- `underpowered.csv` — null result, insufficient power
- `mixed_results.csv` — segment-level reversals

Each dataset teaches a different aspect of experiment analysis.
