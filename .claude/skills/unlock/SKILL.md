---
name: unlock
description: Force-release a stale project lock at experiments/<exp_id>/.state.lock.
---

# Skill: `/unlock` — Stale Lock Recovery

## Purpose

Release a stale `.state.lock` file when the holding process is dead or the user accepts breaking the lock. The CLI checks PID-aliveness via `os.kill(pid, 0)`; if the PID is dead, the lock auto-releases. If the PID is alive, the CLI refuses unless `--force` is supplied. In either path, the CLI emits a `lock.stale_reclaimed` audit event so the decision chain reflects the break.

## When to invoke

Direct invocation:

- `/unlock <exp_id>` — attempt release; auto-clears if holding PID is dead
- `/unlock <exp_id> --force` — break the lock when the holding PID is still alive

Plain-English routing:

| Phrase | Dispatch |
|---|---|
| "I can't open exp_001; something says it's locked" | `/unlock exp_001` |
| "Force-release the lock on exp_007" | `/unlock exp_007 --force` |

## Arguments

```
/unlock <exp_id> [--force]

Positional:
  <exp_id>    required; experiment identifier under experiments/

Flags:
  --force     required if the holding PID is alive
```

## The workflow

1. **Validate that `experiments/<exp_id>/.state.lock` exists.** If absent, surface "no lock to release" and exit; do not shell out.
2. **Shell out** to `agentxp unlock <exp_id> [--force]`. The CLI is canonical.
3. **Parse the outcome** from stdout/stderr:
   - "Lock released; PID was dead" — clean release, no force needed.
   - "Lock held by PID N (alive); use --force to break" — re-prompt with `--force` guidance.
   - "Lock released by force; emitted lock.stale_reclaimed event" — force release recorded.
4. **Surface the outcome** to the user. If the user is trying to continue an experiment, recommend `/resume <exp_id>` as the next step.

## Critical warning to surface

**Do NOT run `rm .state.lock` directly.** The shell `rm` orphans the audit row that records the prior session's halt. The CLI's `agentxp unlock` emits a `lock.stale_reclaimed` event so the audit chain stays intact. Shell removal breaks chain integrity and the next `/audit` will report FAILED.

## What this skill does NOT do

- Does not decide whether the lock should be broken. That is the user's call, expressed via `--force`.
- Does not resume the experiment. That is `/resume`'s job; run it after `/unlock`.

## Cross-references

- Session continuation after unlock: `/resume <exp_id>`.
- Lock-handling semantics: Plan §10.6.3.
- CLI entry: `openxp/cli/unlock.py`.
- Lock module: `openxp/orchestrator/project_lock.py`.
- Top-level orientation: `CLAUDE.md`.

## Example walkthrough

```
User: /unlock exp_001

[skill runs `agentxp unlock exp_001`]
[CLI: "Lock held by PID 12345 (alive); use --force to break"]

The lock on exp_001 is held by PID 12345, which is still running. If you are
sure that process is no longer relevant (e.g., another Claude Code session
crashed), re-run with --force:

  /unlock exp_001 --force

Do NOT run `rm .state.lock` directly — the audit chain depends on the
lock.stale_reclaimed event that the CLI emits.
```

## Banned vocabulary

These tokens never appear in skill output or dispatched commentary:

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

- Co-pilot or colleague register around lock recovery. State the outcome the CLI reported; do not narrate.
- Manufactured urgency around a held lock. Plain statement only.
