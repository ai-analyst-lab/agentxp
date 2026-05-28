---
name: profile
description: Profile a dataset (Stage 0). Surfaces column structure, null rates, and data-quality flags.
---

# Skill: `/profile` — Stage-0 Dataset Inspection

## Purpose

Profile a dataset before designing a test. This is Stage 0 of the AgentXP pipeline, scoped to the case where a user only wants to inspect the data — no brief, no hypothesis, no analysis. The skill shells out to `agentxp profile <path>`, which runs DuckDB `SUMMARIZE` plus the HG-D4 heuristics and writes `bundles/profiler.out.yaml`. It then dispatches the `profiler` sub-agent to render a column table with `my read` annotations and surface any flagged columns. The skill ends at the bundle receipt; it does not advance to Stage 0.5 or write any project-level configuration.

## When to invoke

- Direct: `/profile <path>`
- Plain-English routing: "Look at this dataset", "What's in this CSV?", "Inspect the data at ~/data/X", "Just profile this file"

If the user describes a hypothesis or asks for a test design, do not handle that here. Route to `/experiment` instead.

## Arguments

```
/profile <path> [--bundle PATH] [--deep]
```

- `<path>` — required; path to a parquet, CSV, JSON, JSONL, or other tabular file readable by DuckDB.
- `--bundle PATH` — optional; where the profile bundle is written. Default: `bundles/profiler.out.yaml`.
- `--deep` — optional; also run the ydata-profiling deep sidecar. Slower, higher-detail HTML output. Default: off.

## Workflow

1. **Validate the path.** Confirm the file exists on disk. If it does not, print `file not found: <path>` to stderr and exit without invoking the CLI or the agent.

2. **Run the CLI.** Shell out to `agentxp profile <path>` (with `--bundle` and `--deep` passed through when supplied). This calls `openxp.profiler.driver.profile_dataset()`, which runs DuckDB `SUMMARIZE` and the HG-D4 heuristics in `openxp.profiler.heuristics`, then writes `bundles/profiler.out.yaml` (the deterministic profile). The bundle is the source of truth for everything downstream in this turn; do not re-read the data file.

3. **Dispatch the profiler agent.** Read `agents/profiler.system.md` verbatim as the sub-agent system prompt. Pass the just-written `bundles/profiler.out.yaml` as input. The sub-agent's job is the semantic-interpretation pass: it renders the column table inside a fenced code block with five columns (`column`, `type`, `null%`, `sample`, `my read`), annotates each row with what the column probably is (unit of randomization, assignment column, exposure event, primary outcome candidate, guardrail candidate, negative-control candidate, dimension, pipeline meta), and asks at most one clarifying question.

4. **Surface HG-D4 flags.** Read `mixed_format_detected` and per-column `flagged_for_review` / `flag_reason` from the bundle. If `mixed_format_detected` is true on any timestamp column, the agent pauses with the mixed-format escalation: pick a format or skip the column. If a column matching an identifier name pattern (`user_id`, `account_id`, `device_id`, `session_id`) has `null_rate > 0.5`, it goes into the agent's "things to check" section with the high-null-entity-ID phrasing from `agents/profiler.system.md` §6. If both flags fire, the mixed-format question takes the single ask; the null-rate flag becomes an observation.

5. **Close with the receipt.** When the agent commits, print exactly `wrote: bundles/profiler.out.yaml` (or the `--bundle` override path) on its own line. That is the end of the skill.

## What this skill does not do

- It does not advance to Stage 0.5. The `semantic_modeler` agent and the rest of the `/experiment` flow are out of scope here.
- It does not write project-level YAMLs such as `semantic_models/` or `metrics/`.
- It does not update `state.yaml` and does not fire any `stage.committed` event. Stage-0-only invocations are intentionally orchestrator-silent.
- It does not load, sample, or query the data outside what `agentxp profile` already does. Trust the bundle.
- It does not edit, move, or delete the input file. The path is read-only from this skill's perspective.

## Cross-references

- For the full Stage 0 → Stage 8 pipeline (brief, semantic model, metrics, design, power, analyze, interpret, report), use `/experiment` instead.
- For top-level orientation on AgentXP and its agent index, see `CLAUDE.md` at the repository root.
- The `/audit` skill is not applicable to profile-only runs. Stage-0-only invocations do not write to `log.jsonl`, so there is nothing for `/audit` to reconstruct.

## Example walkthrough

```
User: /profile ~/data/checkout_test.parquet

[skill runs `agentxp profile ~/data/checkout_test.parquet`]
[bundle written to ./bundles/profiler.out.yaml]

[skill loads agents/profiler.system.md and dispatches the profiler sub-agent]
[sub-agent renders the column table with `my read` annotations]

read: ~/data/checkout_test.parquet
rows: 91,204  cols: 11  date range: 2026-05-19 → 2026-05-26

column            type       null%   sample                my read
─────────────────────────────────────────────────────────────────────
user_id           string     0%      "u_8a3f..."           unit of randomization
bucket            string     0%      "A","B"               assignment column
session_started   timestamp  0%      2026-05-19 14:33      exposure event
reached_confirm   boolean    0%      true/false            primary outcome candidate
revenue_usd       float      62%     142.50                guardrail candidate (null=$0)
...

Looks right? Or fix one thing.

User: Looks right.

Saved.
wrote: bundles/profiler.out.yaml
```

If a column is flagged (mixed timestamp formats, or `null_rate > 0.5` on a likely identifier), the sub-agent surfaces the escalation in place of the open-ended confirm. The CLI also emits a `flag: <reason>` line to stderr and returns the `EXIT_WARNING` code; the skill treats this as a successful run with a flag, not as a failure.

## Banned vocabulary

The output produced by this skill — both the orchestration text and any text emitted by the dispatched sub-agent — must avoid the tokens below. These mirror `agents/profiler.system.md` §8 and are treated as syntax errors.

- `leverage`
- `powerful`
- `delightful`
- `robust`
- `seamless`
- `cutting-edge`
- `great question`
- `excellent observation`
- `we're excited`
- `successfully` (as a self-congratulatory adverb, e.g. "I've successfully loaded the data")
- `Let me walk you through`
- `Before we begin, let me explain`
- `co-pilot`
- `colleague`

Banned patterns: opening a turn with throat-clearing; punting the default by asking the user to pick everything; confirming every column individually; manufactured emotional beats. If the urge to write "That's a tricky one" appears, delete it and state the observation plainly.
