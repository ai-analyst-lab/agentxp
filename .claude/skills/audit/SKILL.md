---
name: audit
description: Replay the decision chain for any experiment in the project. Walks log.md + git log. Default text mode, --diff, or --html.
---

# Skill: `/audit`

## Purpose

The audit surface is two things: `experiments/<id>/log.md` (append-only human-readable log) and `git log` (every `commit_artifact` runs a git commit). This skill walks both, optionally diffs two experiments, and optionally renders HTML.

There is no separate event log in v2 — git is the chain.

## When to invoke

Direct:
- `/audit <exp_id>` — text timeline
- `/audit <exp_id> --diff <other_exp_id>` — pairwise diff
- `/audit <exp_id> --html` — self-contained HTML

Plain-English routing:

| Phrase | What to do |
|---|---|
| "Why did exp_007 halt?" | `/audit exp_007` then look for halt-related entries |
| "Compare exp_001 to exp_007" | `/audit exp_001 --diff exp_007` |
| "Send the audit to my director" | `/audit <id> --html` and surface the file path |
| "What dispatches landed for exp_004" | `/audit exp_004` then filter for dispatch entries |

## Procedure

### Text mode (default)

```python
from pathlib import Path
from agentxp.workflows.audit import walk_log

for entry in walk_log(Path.cwd() / "experiments" / args.exp_id):
    print(f"{entry.timestamp}  {entry.message}")
```

Optionally interleave `git log --oneline -- experiments/<id>/` so each commit SHA appears next to its log entry. The two are kept in sync by `commit_artifact`.

### Diff mode

```python
from agentxp.workflows.audit import diff_logs

for d in diff_logs(exp_a, exp_b):
    if d.kind == "changed":
        print(f"line {d.line_no}: {d.a.message}  ->  {d.b.message}")
    elif d.kind == "only_in_a":
        print(f"only in {exp_a.name}: {d.a.message}")
    elif d.kind == "only_in_b":
        print(f"only in {exp_b.name}: {d.b.message}")
```

### HTML mode

Render a self-contained HTML page that includes the log timeline + the renders catalog summary + the integrity-lock receipt from `brief.sealed.yaml`. Use `agentxp.render.report` for the HTML adapter; the data comes from `walk_log` and `list_catalog`.

## Tools you call

- `walk_log` / `diff_logs` from `agentxp.workflows.audit`
- `list_catalog` from `agentxp.workflows.readouts` (for the renders catalog summary in HTML mode)
- `git log --oneline -- experiments/<id>/` via Bash for commit SHAs

## Rules cited

- **R7** — every claim in the audit cites a log entry or a commit SHA

## What this skill does NOT do

- Replay specialist dispatches against an LLM — the log captures the dispatch result, not the prompt
- Validate the renders chain — that is `/readouts <id> --validate`

## Terminal output

Text mode: timeline printed to stdout. Diff mode: changes printed to stdout. HTML mode: file path + suggested next step (open in browser).

## Banned vocabulary

The voice audit at `agentxp/render/voice_audit.py` rejects the marketing-register phrases listed in CLAUDE.md §13. Audit narration is academic and traceable; every claim cites a log entry or a commit SHA.
