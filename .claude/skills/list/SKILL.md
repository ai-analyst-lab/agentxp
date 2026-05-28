---
name: list
description: Show experiments in this project (current stage, last commit, intent).
---

# Skill: `/list` — Project-Level Experiment Discovery

## Purpose

Render a table of every experiment in the current project — `exp_id`, current stage, last commit timestamp, intent (first 80 chars). Output is markdown by default; `--json` returns a structured array. `--status STAGE` filters by current stage; `--since DAYS` filters to experiments committed within the last N days. The skill is a thin wrapper over `agentxp list`, which walks `experiments/*/state.yaml` and applies the filters.

## When to invoke

- Direct: `/list`
- Plain-English routing:
  - "What experiments are in this project?" → `/list`
  - "What's running right now?" → `/list --status` (the running-stage values)
  - "What did I do this week?" → `/list --since 7`
  - "Give me a JSON dump of all experiments" → `/list --json`

## Arguments

```
/list [--status STAGE] [--since DAYS] [--json]
```

- `--status STAGE` — filter by `current_stage`. Closed set drawn from the Stage enum.
- `--since DAYS` — filter to experiments with `last_committed_at >= now - DAYS`.
- `--json` — emit a JSON array instead of the markdown table.

## Workflow

1. **Shell out.** Run `agentxp list [flags]` with whichever filters were passed. Capture stdout.

2. **Handle the empty case.** If stdout is `No experiments found` (the CLI's empty-project sentinel), surface a single line: `no experiments yet — run /experiment to start one.` Stop there.

3. **Render the table.** Otherwise, pass the CLI output through to the user as-is. Markdown table or JSON, whichever the flags selected. Do not reformat columns or re-sort rows.

4. **Flag pending decisions.** If any row's `current_stage` carries the warning marker (e.g., `cohorts_built (⚠)` from the CLI), append one line after the table naming the affected `exp_id` and suggesting `/resume <exp_id>` to continue. One line total, not one per row.

## What this skill does not do

- It does not read `state.yaml` directly. Trust the CLI's output.
- It does not modify any state. Read-only.
- It does not fire `stage.committed` or any other event.
- It does not call `/audit` or `/resume` itself; it only points at them.

## Cross-references

- Per-experiment detail and event reconstruction: `/audit <exp_id>`.
- Continue a paused experiment: `/resume <exp_id>`.
- Top-level orientation: `CLAUDE.md` at the repository root.

## Example

```
User: /list

[skill runs `agentxp list`]

| exp_id  | stage              | last_committed_at      | intent                          |
|---------|--------------------|------------------------|---------------------------------|
| exp_001 | report_rendered    | 2026-05-26T18:42:00Z  | Checkout button A/B test        |
| exp_002 | brief_drafted      | 2026-05-27T09:15:00Z  | Free shipping banner test       |
| exp_007 | cohorts_built (⚠)  | 2026-05-27T14:30:00Z  | Signup flow redesign (paused)   |

exp_007 has a pending decision (srm_override). Run /resume exp_007 to continue.
```

## Banned vocabulary

The output produced by this skill must avoid the tokens below. Treated as syntax errors.

- `leverage`
- `powerful`
- `delightful`
- `robust`
- `seamless`
- `cutting-edge`
- `great question`
- `excellent observation`
- `we're excited`
- `successfully` (as a self-congratulatory adverb)
- `Let me walk you through`
- `Before we begin, let me explain`
- `co-pilot`
- `colleague`

Banned patterns: throat-clearing openers; manufactured emotional beats; confirming every row individually.
