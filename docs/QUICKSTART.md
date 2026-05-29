# Quickstart

A hand-walked first run. By the end of this doc you'll have run a real experiment against a fixture, hit an SRM halt, decided whether to override it, and inspected the audit trail.

Assumes Python 3.11+. macOS or Linux first-class; Windows via WSL2.

> **How to read the commands below.** AgentXP v0.1 has two surfaces:
> - A small **shell CLI** (`agentxp …`) for setup and inspection: `profile`, `connect`, `list`, `resume`, `unlock`, `audit`, `experiment`. Lines marked `$` run in your terminal.
> - The **experiment pipeline itself**, which runs *inside a Claude Code conversation*. You start it with the `/experiment` slash command and then talk to Claude through the eleven stages. Lines marked `>` are typed inside Claude Code, not the shell.
>
> The shell `agentxp experiment` command does not run a long-lived analysis loop in v0.1 — it just prints guidance pointing you into Claude Code.

## 1. Install

```bash
$ git clone https://github.com/ai-analyst-lab/agentxp.git
$ cd agentxp
$ pip install -e .
$ agentxp --version
```

You should see `agentxp 0.1.0`. If `agentxp` isn't on your PATH, your virtualenv isn't active — activate it and re-run.

## 2. Look at the sample data

AgentXP reads from DuckDB, Snowflake, or BigQuery. For this walkthrough use the shipped CSV fixtures — DuckDB will load them inline.

```bash
$ ls sample-data/
# checkout_redesign.csv  clean_ab.csv      guardrail_violation.csv
# mixed_results.csv      no_effect.csv     srm_violation.csv
# ship_demo.csv          underpowered.csv  seeds/  README.md
```

We'll use `srm_violation.csv` first — it has a broken randomization. Connecting a real warehouse is `agentxp connect <dialect> <name>` (e.g. `agentxp connect duckdb local`); run `agentxp connect --help` for the wizard.

## 3. Start the experiment in Claude Code

Open the project in Claude Code, then start the pipeline with the `/experiment` slash command, pointing it at the fixture:

```text
$ claude            # opens Claude Code in this directory
```

Inside Claude Code:

```text
> /experiment --data sample-data/srm_violation.csv
```

The elicitor stage opens and asks what you're testing. Type a one-line hypothesis:

```text
> We added a "free shipping" banner to checkout. Want to see
  if it lifts completion without hurting AOV.
```

## 4. The elicitation turns

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

Each turn commits one default with a one-clause reason. By the end the pipeline has written a brief and advanced the state:

```
wrote: experiments/exp_002/brief.yaml
wrote: experiments/exp_002/state.yaml (stage_2 -> stage_3)
```

That brief is the contract — the interpreter applies it cold at the end. You can read it any time from the shell:

```bash
$ cat experiments/exp_002/brief.yaml
```

## 5. The SRM halt

The pipeline continues into the monitor stage, which computes the SRM chi-squared on the assignment counts. For `srm_violation.csv`, the split is 5600/4400 against an expected 50/50, so the monitor halts:

```
gate.blocked: srm_violation
  chi_squared = 144.0   p < 0.001
  observed: control=5600, treatment=4400
  expected: 5000/5000

Stage 5 (monitor) halted. Randomization is broken.
```

The monitor doesn't read your hypothesis. It can't tell you whether the SRM is "probably fine." It just halts. Shipping a verdict from this data means shipping on contaminated assignment.

## 6. Override or accept

For a real broken experiment you'd stop here, fix the assignment system, and re-run. For this walkthrough, tell Claude to override so you can see the rest of the flow — the orchestrator records the override and your justification in `log.jsonl` as a `gate.resolved` event:

```text
> Override the SRM halt — this is a synthetic fixture, treat it as illustrative.
```

Anyone reading the audit later sees both the halt and the reason it was bypassed.

## 7. The verdict

Analysis continues. The interpreter applies the decision rule from the brief — not from current vibes:

```
## Verdict
> NO-SHIP — completion +0.4pp [-0.8, +1.6] at 95% CI;
> CI straddles zero; AOV guardrail -1.2% [-2.1, -0.3].
Confidence: inconclusive on primary; very likely negative on guardrail.

wrote: experiments/exp_002/report.md
wrote: experiments/exp_002/report.json
```

The stakeholder paragraph below the verdict reads:

> The free-shipping banner did not reliably lift completion (+0.4pp, 95% CI [-0.8, +1.6] — includes zero) and AOV dropped 1.2% with the confidence interval excluding zero on the downside. No detectable upside, real downside on basket value. Don't ship this variant.

Paste that paragraph in Slack. That's the deliverable.

## 8. Inspect the audit trail

Back in the shell, the `audit` CLI replays every decision from disk:

```bash
$ agentxp audit exp_002                 # text timeline
$ agentxp audit exp_002 --diff exp_001  # pairwise diff against another experiment
$ agentxp audit exp_002 --html          # self-contained HTML report
$ agentxp audit exp_002 --json          # JSON event array (for piping)
```

You'll see every event in order: stage commits, agent dispatches, queries proposed and executed, the SRM gate that fired, the override, every bundle hash. The text output is replayable — run it on a teammate's machine against the same `experiments/exp_002/` directory and you get the same answer. That's the spine: every decision is on disk, hashed, and chained.

If the pipeline ever stops mid-run, `agentxp resume exp_002` detects the recovery case and prints the recommended next step.

## Where to go next

- Run `/experiment --data sample-data/clean_ab.csv` in Claude Code for a clean SHIP verdict.
- Run it against `sample-data/guardrail_violation.csv` to see how guardrail breaches surface.
- Connect a real warehouse: `agentxp connect <dialect> <name>` (run `agentxp connect --help` first).
- Skim the limits before you build on it: [../KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md).
