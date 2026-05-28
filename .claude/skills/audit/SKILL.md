---
name: audit
description: Replay the decision chain for any experiment in the project. Default text mode, --diff, or --html.
---

# Skill: `/audit` — Decision Chain Replay

## Purpose

This skill replays the full chain of decisions, agent dispatches, gate openings, and stage commits for any experiment in the project. The README promises that plain-English questions ("Why did exp_007 halt at Stage 5?") produce the same result as the explicit CLI call. The skill classifies the question, dispatches the right `agentxp audit` subcommand, and surfaces the chain integrity verdict that the CLI computes.

## When to invoke

Direct invocation:

- `/audit <exp_id>` — default text timeline
- `/audit <exp_id> --diff <other_exp_id>` — pairwise diff
- `/audit <exp_id> --html` — render the self-contained HTML report

Plain-English routing examples:

| Phrase | Dispatch |
|---|---|
| "Why did exp_007 halt at Stage 5?" | default text mode + filter rendering to `gate.blocked` and `query.failed` |
| "What did the analyzer decide?" | default text mode + filter to `agent.completed` where agent_name=analyzer |
| "Compare exp_001 to exp_007" | `--diff` |
| "Send the report to my director" | `--html` and surface the output path |
| "Show me the queries for exp_004" | default text mode + filter to `query.*` events |

## Arguments

```
/audit <exp_id> [flags]

Positional:
  <exp_id>                   required; experiment identifier under experiments/

Flags:
  --diff <other_exp_id>      pairwise diff against another experiment
  --html                     render self-contained HTML report
  --out <path>               output path for --html (default per CLI)
  --quiet                    suppress chain integrity chrome
  --json                     emit structured event array
```

## The workflow

1. **Validate that `experiments/<exp_id>/` exists.** If the directory is absent, surface the error and exit; do not shell out.

2. **Classify the question** when invocation is plain-English. The classifier is a single pass over the user phrase:

   - "timeline" / "history" / "what happened" → default text mode.
   - "diff" / "compared to" / "vs" → `--diff`. If the second exp_id is not in the phrase, ask once for it.
   - "html" / "share" / "send to" / "report" → `--html`. Offer the default output path.
   - "why did X halt" / "why did X fail" → default text mode plus filter rendering to `gate.blocked` and `query.failed` events.
   - "show me the queries" → default text mode plus filter to `query.*` events.

   Explicit slash invocations skip classification.

3. **Execute the CLI.** Shell out to `agentxp audit <exp_id> [flags]`. Capture stdout and surface it to the user verbatim. The CLI is canonical.

4. **Augment when the question requires it.** For "why" questions, read `experiments/<exp_id>/log.jsonl` directly and surface the matching `gate.blocked.reason` or `query.failed.metadata.subtype`. For `--diff` questions where the user wants commentary, write one paragraph after the CLI output naming which bundle hashes differ and which queries diverged. No statistical reinterpretation.

5. **Chain integrity verdict.** The CLI prints `chain integrity: OK` or `chain integrity: FAILED` at the end of the text mode. If the verdict is FAILED, surface this prominently and warn the user that the audit is not trustworthy. Do not paper over a FAILED verdict with commentary.

## What this skill does NOT do

- Does not reinterpret the verdict. The interpreter's output stays canonical; this skill replays the chain that produced it.
- Does not modify any audit artifact. Read-only on `log.jsonl`, `decisions.jsonl`, and bundle hashes.
- Does not fire any events. No `_commit_stage` happens here.

## Cross-references

- Top-level orientation: `CLAUDE.md`.
- Decisions writer detail: `openxp/audit/decisions.py`.
- Event vocabulary (the 13 closed-set values): `openxp/audit/events.py`.
- CLI entry: `openxp/cli/audit.py` and the HTML renderer at `openxp/cli/audit_html.py`.
- Diff helper: `openxp/cli/prune.py`.

## Example walkthrough

```
User: "Why did exp_007 halt at Stage 5?"

[skill classifies the phrase as a "why halt" question]
[dispatch: agentxp audit exp_007, filtered rendering to gate.blocked and query.failed]
[skill reads log.jsonl and locates gate.blocked(kind="srm_halt") at Stage 5]

Stage 5 halted on a sample-ratio mismatch.
gate.blocked(kind="srm_halt", chi_square=158.79, p=0.00012)
observed: A=45612, B=45592 (expected: 50/50)
The monitor agent surfaced an imbalance well below the 0.0005 threshold.

To proceed, run /resume exp_007. The resume classifier will surface the
override dialog (SrmOverrideReasonCode: known_imbalance |
manual_continuation | investigation_complete).
```

## Banned vocabulary

These tokens never appear in skill output, dispatched commentary, or augmentation paragraphs:

- `leverage`
- `powerful`
- `delightful`
- `robust`
- `seamless`
- `cutting-edge`
- `great question`
- `excellent observation`
- `we're excited`
- `successfully`
- `Let me walk you through`
- `Before we begin, let me explain`
- `co-pilot`
- `statistically significant improvement` (use lift + CI)
- `trending positively`
- `encouraging signal`
- `promising results`
- `consider shipping`
- `appears to have been successful`

Banned patterns:

- Reinterpreting the chain integrity verdict instead of surfacing it.
- Co-pilot or colleague register ("Here's what I found for your experiment"). The audit is a chain replay; there is no second person beyond the dispatch dialog.
- Manufactured emotional beats around a FAILED verdict. Plain statement only.
