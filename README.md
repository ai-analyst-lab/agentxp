# AgentXP

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Claude Code Required](https://img.shields.io/badge/requires-Claude%20Code-blueviolet.svg)](https://claude.ai/code)

AgentXP is an open-source system for the design and analysis of controlled experiments, intended for use inside Claude Code. The user describes a hypothesis in plain English; a pipeline of LLM agents walks from data profiling and a pre-registered brief through monitoring, statistical analysis, and a stakeholder-ready readout. Deterministic Python functions handle the statistical work; agentic stages handle the judgment-dependent steps — drafting the brief, naming the events the analysis requires, interpreting the result against the pre-registered decision rule. Every decision the system makes is committed to disk and reproducible from the audit chain.

Apache 2.0. Runs locally. Reads from DuckDB, Snowflake, or BigQuery.

---

## Why this exists

Running an A/B test correctly is mostly a discipline problem. The math is well understood. The hard parts are the steps where humans get sloppy: writing down the hypothesis and the decision rule before looking at the results, verifying the assignment randomized correctly before interpreting the lift, applying the decision rule cold instead of finding a story that fits the data, flagging guardrail violations alongside the primary metric, and keeping a record of every choice the analysis made so a reviewer can replay it.

AgentXP enforces these steps as a workflow. The user supplies intent and judgment; the system handles the discipline.

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

Claude walks the 11 stages with the user — profiling the data, drafting the brief, running the analysis, rendering the readout. At each stage the system commits a default with a one-clause justification; the user overrides if it picked wrong.

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

Each agent runs with only the context it needs. The agent that monitors for sample-ratio mismatch does not see the hypothesis prose, so it cannot motivated-reason past a contamination signal. The agent that interprets the analysis reads the results tables but not the original framing — it applies the decision rule that was locked at brief time, cold. The agent that renders the readout never re-litigates the verdict.

This is what makes the audit trail credible. Every bundle hash, every query, every gate is on disk. Two reviewers running the same audit log produce the same answer.

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
- Three warehouse adapters in v0.1 (DuckDB, Snowflake, BigQuery). Redshift, Databricks, MySQL, and Postgres land in v0.1.1, within two weeks of v0.1.
- No external hook system. The internal `validate_chain` runs on every stage commit. Hooks land in v0.2.
- No OpenTelemetry export. The append-only log is the audit substrate. OTel lands in v0.5.

Full list at [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

---

## License

Apache 2.0. See [LICENSE](LICENSE). The patent grant covers statistical methods.

Issues and PRs welcome. The repository is small enough to read end-to-end in an afternoon — the system prompts in `agents/*.system.md` are the spec.
