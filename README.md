# AgentXP

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Claude Code Required](https://img.shields.io/badge/requires-Claude%20Code-blueviolet.svg)](https://claude.ai/code)

AgentXP is an open-source system for the design and analysis of controlled experiments, opened inside Claude Code and driven through plain-English conversation, with a pipeline of LLM agents carrying the experiment from data profiling through a pre-registered brief, sample-ratio monitoring, statistical analysis, and a final readout. The statistical work itself is handled by deterministic Python functions; the agents take responsibility only for the steps that require judgment — drafting the brief, naming the events the analysis depends on, and interpreting the result against the decision rule that was fixed at brief time. Every choice the system makes is written to an audit log that any reviewer can replay.

Apache 2.0. Runs locally. Reads from DuckDB in v0.1; Snowflake, BigQuery, and Databricks arrive in v0.1.1.

---

## Why this exists

Running an A/B test correctly is mostly a discipline problem rather than a mathematical one. The math is well understood; the difficulty lies in the steps where the discipline tends to break — writing down the hypothesis and the decision rule before any data is seen, verifying that the assignment actually randomized before the lift is interpreted, applying the decision rule to the analysis tables alone instead of constructing a narrative that fits the result, flagging guardrail violations in the same readout as the primary metric, and keeping a record of every choice the analysis made so that a reviewer can later replay it.

AgentXP enforces these steps as a workflow. The user supplies the intent and the judgment; the system handles the discipline.

---

## How to use it

Install Claude Code, clone the repository, and open it:

```bash
npm install -g @anthropic-ai/claude-code
git clone https://github.com/<your-fork>/agentxp.git
cd agentxp
pip install -e .
claude
```

Inside Claude, describe the test:

```
I want to test whether the new checkout button improves completion 
rate. My data is at ~/data/checkout_test.parquet.
```

Claude walks the eleven stages with the user — profiling the data, drafting the brief, running the analysis, rendering the readout. At each stage the system proposes a default with a one-clause justification, which the user accepts or overrides before the stage commits.

For a fuller walkthrough including a sample-ratio-mismatch halt, see [docs/QUICKSTART.md](docs/QUICKSTART.md).

---

## The 11-stage workflow

When `/experiment` is invoked, the system orchestrates 13 agents across 11 stages:

| Stage | Agent(s) | Purpose |
|-------|----------|---------|
| 0 | `profiler` | Profile the dataset; surface column structure, null rates, data-quality flags |
| 0.5 | `semantic_modeler` | Draft semantic entity definitions from the profile |
| 0.75 | `metric_drafter` | Bootstrap a starter metric catalog from outcomes and measures |
| 1-3 | `designer.elicitor`, `designer.drafter`, `designer.editor`, `consistency_judge` | Capture intent, draft the hypothesis, draft the pre-registered brief |
| 4 | `designer.drafter` | Bind the brief to a data plan: which metrics, which cohorts |
| 5 | `sql_query_writer`, `monitor` | Build cohort SQL; check for sample-ratio mismatch before any results render |
| 6 | `analyzer` | Compute primary metric, guardrails, and pre-registered segments |
| 7 | `interpreter` | Apply the 8-step decision tree against the pre-registered decision rule |
| 8 | `readout` | Render the verdict, diagnostics panel, and JSON sidecar |

Stages 0 / 0.5 / 0.75 run once per dataset. Stages 1-8 run per experiment.

The full pipeline does not have to run end-to-end. Five execution plans cover the common cases:

| Plan | Use when | What runs |
|------|----------|-----------|
| `full` | Hypothesis → verdict, end to end | All 13 agents, stages 0-8 |
| `from_brief` | Brief already exists; analyze the data | Stages 5-8 |
| `from_data` | Data already loaded; design from there | Stages 1-8 |
| `profile_only` | Inspect data without designing | Stage 0 only |
| `audit` | Replay a past run | No agents; reads logs |

If a stage pauses (sample-ratio-mismatch halt, gate opened, ambiguous brief), the run resumes via `/resume <exp_id>`.

---

## Sub-agent isolation

Each agent runs with only the context it requires. The agent that monitors for sample-ratio mismatch has no access to the hypothesis prose and therefore cannot construct an explanation that rescues a contaminated result, because no preferred result is present in its context to be rescued. The agent that interprets the analysis sees the result tables but not the original framing, so the verdict is bound to the data and to the decision rule that was specified at brief time rather than to whatever the analyst hoped to find. The agent that renders the readout has no power to revisit the verdict at all.

The audit trail derives its credibility from this isolation: every bundle hash, every query, every gate is committed to disk, so two reviewers running the same audit log will reach the same answer.

The audit vocabulary is a closed set of thirteen events: `stage.entered`, `stage.committed`, `gate.opened`, `gate.resolved`, `gate.blocked`, `agent.dispatched`, `agent.completed`, `query.proposed`, `query.validated`, `query.executed`, `query.failed`, and two reserved for the v0.2 hook system. An internal validator walks the chain on every commit and rejects orphans or broken references.

---

## What's in the repository

| Path | Contents |
|------|----------|
| `agents/*.system.md` | The 13 LLM agent system prompts |
| `openxp/schemas/` | Pydantic models for state, profile reports, semantic models, metrics, fact sources, assignments |
| `openxp/audit/` | Append-only audit log, conversation log, `validate_chain` invariant checker |
| `openxp/profiler/` | Stage 0 implementation (DuckDB `SUMMARIZE` + data-quality heuristics) |
| `openxp/semantic/` | YAML validators and project-lock-wrapped I/O for semantic models, metrics, fact sources, assignments |
| `openxp/stats/` | Deterministic statistical routines (Welch, SRM, proportion tests, CUPED, sequential, Bayesian) |
| `openxp/cli/` | Command-line entry points |
| `tests/` | Unit and integration tests |

---

## Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `/experiment` | Run a full experiment end to end | `/experiment plan=full` |
| `/profile` | Profile a dataset (Stage 0) | `/profile ~/data/checkout.parquet` |
| `/connect-data` | Connect a warehouse | `/connect-data snowflake` |
| `/resume` | Resume an interrupted experiment | `/resume exp_001` |
| `/audit` | Replay the decision chain | `/audit exp_001` |
| `/list` | Show all experiments in this project | `/list` |
| `/unlock` | Force-unlock a stale project lock | `/unlock` |

Plain-English questions also work. "Why did exp_007 halt at Stage 5?" produces the same result as `/audit exp_007`.

---

## Limitations

v0.1 ships deliberately narrow.

- **v0.1 is in active development.** The data-profiling stage and the audit substrate are complete; the brief-drafting, analysis, interpretation, and readout stages land through the W1-W7 build waves. See `BUILD_STATUS.yaml` for current state.
- Single-user. No team collaboration, no shared project locks.
- Randomized A/B tests only. Causal inference and quasi-experimental designs are a separate project.
- v0.1 ships one warehouse adapter (DuckDB). The three analytical warehouses — Snowflake, BigQuery, and Databricks — land in v0.1.1, within two weeks of v0.1. The operational stores (Postgres, MySQL, Redshift) follow in v0.1.2.
- No external hook system. The internal `validate_chain` runs on every stage commit. Hooks land in v0.2.
- No OpenTelemetry export. The append-only log is the audit substrate. OTel lands in v0.5.

Full list at [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

---

## License

Apache 2.0. See [LICENSE](LICENSE). The patent grant covers statistical methods.

Issues and PRs welcome. The repository is small enough to read end-to-end in an afternoon — the system prompts in `agents/*.system.md` are the spec.
