# Quickstart

A hand-walked first run. By the end of this doc you'll have run a real experiment against a fixture, hit an SRM halt, decided whether to override it, and inspected the audit trail.

Assumes Python 3.11+. macOS or Linux first-class; Windows via WSL2.

## 1. Install

```bash
git clone https://github.com/ai-analyst-lab/agentxp.git
cd agentxp
pip install -e .
agentxp --version
```

You should see `agentxp 0.1.0`. If `agentxp` isn't on your PATH, your virtualenv isn't active — activate it and re-run.

## 2. Configure data

AgentXP reads from DuckDB, Snowflake, or BigQuery. For this walkthrough use the shipped CSV fixtures — DuckDB will load them inline.

```bash
ls sample-data/
# checkout_redesign.csv  clean_ab.csv  guardrail_violation.csv
# mixed_results.csv      no_effect.csv srm_violation.csv
# underpowered.csv
```

We'll use `srm_violation.csv` first — it has a broken randomization. Real warehouses connect through `agentxp connect duckdb|snowflake|bigquery`; see `docs/connect.md` *(placeholder — v0.1 patch)*.

## 3. Run /experiment

```bash
agentxp /experiment --data sample-data/srm_violation.csv
```

The elicitor agent opens. It asks what you're testing.

```
> What do you want to test?
```

Type a one-line hypothesis:

```
We added a "free shipping" banner to checkout. Want to see
if it lifts completion without hurting AOV.
```

## 4. The 5-turn elicitation

The elicitor reads your phrasing back as structured fields:

```
Got it. Reading that back:
 - primary: checkout_completion_rate
 - guardrail: aov (avg_order_value)
 - direction: completion up, AOV doesn't get worse

One thing I can't pick for you: how big a lift do you need
to see before this is worth shipping? If you don't have a
number, I'll size for 2pp absolute. Override if 2pp is wrong.
```

Each turn commits one default with a one-clause reason. Five turns max. By the end you have a `brief.yaml`:

```
wrote: experiments/exp_002/brief.yaml
wrote: experiments/exp_002/state.yaml (stage_2 -> stage_3)
```

## 5. See the brief

```bash
agentxp brief exp_002
```

You'll see the full pre-registered brief: primary metric, guardrails, MDE, decision rule, planned segments. This is the contract. The interpreter applies it cold at the end.

## 6. Run analysis

```bash
agentxp /analyze exp_002
```

The monitor agent fires first. It computes the SRM chi-squared on the assignment counts. For `srm_violation.csv`, the split is 5600/4400 against an expected 50/50.

## 7. The SRM halt

You'll see:

```
gate.blocked: srm_violation
  chi_squared = 144.0   p < 0.001
  observed: control=5600, treatment=4400
  expected: 5000/5000

Stage 5 (monitor) halted. Randomization is broken.

To override: agentxp resume exp_002 --override-srm
To stop:     agentxp /readout exp_002 --invalid
```

Shipping a verdict from this data means shipping on contaminated assignment.

The monitor agent doesn't read your hypothesis. It can't tell you whether the SRM is "probably fine." It just halts.

## 8. Override or accept

For a real broken experiment, you'd stop here, fix the assignment system, and re-run. For this walkthrough, override so you can see the rest of the flow:

```bash
agentxp resume exp_002 --override-srm \
  --justification "synthetic fixture; treating as illustrative"
```

The override is recorded in `log.jsonl` as `gate.resolved` with the justification text. Anyone reading the audit later sees both the halt and the reason it was bypassed.

## 9. See the verdict

Analysis continues. The interpreter applies the decision rule from the brief — not from current vibes:

```
## Verdict
> NO-SHIP — completion +0.4pp [-0.8, +1.6] at 95% CI;
> CI straddles zero; AOV guardrail -1.2% [-2.1, -0.3].
Confidence: inconclusive on primary; very likely negative on guardrail.

wrote: experiments/exp_002/report.md
wrote: experiments/exp_002/report.json
```

The stakeholder paragraph that lands below the verdict block reads:

> The free-shipping banner did not reliably lift completion (+0.4pp, 95% CI [-0.8, +1.6] — includes zero) and AOV dropped 1.2% with the confidence interval excluding zero on the downside. No detectable upside, real downside on basket value. Don't ship this variant.

Paste that paragraph in Slack. That's the deliverable.

## 10. Inspect the audit trail

```bash
agentxp audit exp_002
```

You'll see every event in order: stage commits, agent dispatches, queries proposed and executed, the SRM gate that fired, the override, every bundle hash. Three subcommands ship in v0.1:

```bash
agentxp audit exp_002              # text summary
agentxp audit exp_002 --diff exp_001  # pairwise diff
agentxp audit exp_002 --html       # static HTML report
```

The text output is replayable. Run it on a teammate's machine against the same `experiments/exp_002/` directory and you get the same answer. That's the spine: every decision is on disk, hashed, and chained.

## Where to go next

- Run `agentxp /experiment --data sample-data/clean_ab.csv` for a clean SHIP verdict.
- Run it against `guardrail_violation.csv` to see how guardrail breaches surface.
- Connect a real warehouse: `agentxp connect duckdb|snowflake|bigquery`.
- Read the full architecture: [ARCHITECTURE.md](ARCHITECTURE.md) *(placeholder — v0.1 patch)*.
- Skim the limits before you build on it: [../KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md).
