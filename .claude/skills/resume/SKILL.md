---
name: resume
description: Resume an interrupted experiment. Classifies into one of 8 recovery cases per plan §10.6.
---

# Skill: `/resume` — AgentXP Recovery Dispatcher

## Purpose

Resume an interrupted experiment. The 8 recovery cases per §10.6 cover every way a session can end mid-flight: clean stop, pending decision unresolved, mid-commit interruption, mid-dispatch interruption, conversation drift, agent-crash with bundle but no completion event, disk full or auth expired blocking the next step, and schema version mismatch. The `agentxp resume` CLI classifies the case from `state.yaml` + `log.jsonl` + `.state.lock`; this skill presents the case-specific next-step dialog and dispatches the chosen recovery path.

## When to Use

- `/resume <exp_id>` — direct invocation.
- Plain-English routing:
  - "I'm stuck" / "What's the next step?" → walk `state.yaml` for the active experiment and offer resume.
  - "Pick up exp_001 where I left off" → `/resume exp_001`.
  - "What's pending on exp_007?" → `/resume exp_007` (typically Case 2).
  - "Resume exp_X" → `/resume exp_X`.

If `<exp_id>` is omitted and only one in-flight experiment exists under `experiments/`, default to it. Otherwise ask once, then exit.

## Arguments

```
/resume <exp_id> [--force]

Positional:
  <exp_id>   Required. Directory under experiments/<exp_id>/.

Flags:
  --force    Required to override safety checks in Cases 3, 4, and 8, and to
             reclaim a live-PID .state.lock. Never auto-applied.
```

## The 8 Recovery Cases (per §10.6)

### Case 1 — Nothing to resume

`current_stage == last_committed_stage` AND no `pending_decision`. The experiment is at a clean stop point.

- Skill response: "Nothing to resume; `exp_X` is at `<stage>`. Run `/audit` to review or `/experiment` to start a new one."
- Exit: `EXIT_OK`.

### Case 2 — Pending decision unresolved

`state.yaml.pending_decision` is set.

- Skill response: render the gate dialog for the matching `kind`:
  - `srm_override` → present the `SrmOverrideReasonCode` options (`known_imbalance`, `manual_continuation`, `investigation_complete`, `abort`).
  - `brief_contradiction` → present `r` (revise) / `e` (edit) / `o` (override).
  - `confirm_brief` → re-show the brief and present accept / edit / override.
  - Any other registered kind → render its options as defined in the gate registry.
- On user pick: call `resolve_decision(choice=..., reason_code=...)` and let `OrchestratorStore.advance()` continue.

### Case 3 — Mid-commit interruption

`state.yaml.session.last_action_id` has no matching `stage.committed` in `log.jsonl`. The prior session crashed between writing the artifact and emitting the event.

- Skill response: "Last commit incomplete; rolling forward from `<stage>`. Continue?"
- On confirm with `--force`: re-emit the missing `stage.committed` event and advance via `OrchestratorStore.advance()`.
- Without `--force`: print the required flag and exit.

### Case 4 — Mid-dispatch interruption

An `agent.dispatched` event has no matching `agent.completed`. The agent dispatch was in-flight when the session died.

- Skill response: "Agent `<name>` was dispatched but never returned. Options: (a) re-dispatch (fresh attempt), (b) check the warehouse if the agent was SQL, (c) abort and roll back."
- User picks (a): emit `agent.redispatched` and re-invoke the agent with the original bundle.
- User picks (b): print the SQL the dispatch would have run; on user confirm, re-dispatch.
- User picks (c): roll back to `last_committed_stage` and emit `agent.aborted`.
- `--force` required for (a) and (c).

### Case 5 — Conversation drift

`ConversationStore` has turns after `state.yaml.session.last_action_id`, but state did not advance.

- Skill response: "Conversation drift detected; orphan turns will be marked but not replayed. Continue?"
- On confirm: mark the orphan turns (`turn.orphaned`) and advance.

### Case 6 — Agent crash with bundle, no completion event

`bundles/<agent>.out.yaml` exists but no `agent.completed` event was emitted.

- Skill response: "Agent `<name>` wrote its bundle but the event was never emitted. The bundle output looks valid. Options: (a) emit the event and continue, (b) re-dispatch."
- User picks (a): emit `agent.completed` from the bundle contents and advance.
- User picks (b): discard the bundle, re-dispatch.

### Case 7 — Blocked: disk full or auth expired

`gate.blocked(reason="disk_full")` or `gate.blocked(reason="auth_expired")` is the last event in `log.jsonl`.

- Skill response: surface the blocked reason plus the recovery action.
  - `disk_full`: "Free at least 100MB on `<filesystem>` and re-run `/resume <exp_id>`."
  - `auth_expired`: "Run `agentxp connect <warehouse>` to re-auth, then re-run `/resume <exp_id>`."
- Exit without advancing; the gate will re-evaluate on next `/resume`.

### Case 8 — Schema migration needed

`state.yaml.schema_version < 3`.

- Skill response: "Schema migration needed. Run `agentxp migrate state <exp_id>` before resuming."
- Exit: `EXIT_USER_ERROR`. `--force` does not bypass this; migration is the only valid path.

## Stale-Lock Handling (per §10.6.3)

Before classifying any case, inspect `experiments/<exp_id>/.state.lock`:

1. If the lock file is absent, proceed.
2. If present, read its PID. Probe with `os.kill(pid, 0)`:
   - **Live PID** (no exception): refuse to proceed. Print "Another session is holding `exp_X` (PID `<pid>`). Pass `--force` to override (risks a double-writer race)." Exit with `EXIT_USER_ERROR` unless `--force` is set.
   - **Dead PID** (`OSError`): auto-reclaim. Rewrite the lock with the current PID, emit `lock.stale_reclaimed` to `log.jsonl`, then proceed to case classification.

The skill never deletes a live lock without `--force` and never writes a lock for a different experiment.

## Workflow

1. Validate that `experiments/<exp_id>/` exists. If not, print the path tried and exit `EXIT_USER_ERROR`.
2. Check `.state.lock` per §10.6.3 (auto-reclaim dead, refuse live).
3. Shell out to `agentxp resume <exp_id>` and capture stderr — the CLI emits the classified case as `Case <N>: <message>`.
4. Parse the case number (1–8) and the case-specific fields (e.g., `kind=srm_override`, `agent=<name>`, `reason=disk_full`).
5. Render the case-specific dialog from the section above.
6. On user confirmation, call `OrchestratorStore.advance()` (or the case-specific helper: `resolve_decision`, re-dispatch, emit-event, mark-orphan) to continue.
7. Return a one-screen summary: which case fired, what action was taken, the new `current_stage`, and the next mode the user should run (typically `/experiment <mode>` or `/audit`).

## What This Skill Does NOT Do

- Does NOT manually mutate `state.yaml`. Only `OrchestratorStore.advance()` writes state.
- Does NOT skip case classification. `agentxp resume` is the classifier; this skill renders the dialog.
- Does NOT bypass the `_commit_stage` chokepoint. Every recovery path that advances state goes through it.
- Does NOT delete a live `.state.lock` without `--force`.
- Does NOT auto-apply `--force` on the user's behalf in Cases 3, 4, or 8.

## Cross-References

- Top-level: `CLAUDE.md`.
- Plan §10.5: failure modes that produce these cases.
- Plan §10.6: full case specifications.
- Plan §10.6.3: stale-lock detection.
- `/unlock` skill: stale-lock override for edge cases the auto-reclaim path does not cover.
- CLI source: `agentxp/cli/resume.py` (the 8-case classifier).

## Example Walkthrough — Case 2 (pending decision)

```
User: /resume exp_007

[skill runs `agentxp resume exp_007`]
[CLI stderr: "Case 2: pending_decision unresolved; kind=srm_override"]

[skill renders Case 2 dialog]

exp_007 halted at Stage 5 on a sample-ratio mismatch.
gate.opened(kind="srm_override", chi_square=158.79, p=0.00012)

Pick one to continue:
  [1] known_imbalance        — the imbalance is from a documented randomization bug
  [2] manual_continuation    — you accept the risk and will document it in the readout
  [3] investigation_complete — you've investigated; the data is sound
  [4] abort                  — stop here, do not ship

User: 2
[skill calls resolve_decision(choice="manual_continuation", reason_code="MANUAL_CONTINUATION")]
[OrchestratorStore.advance() continues to Stage 6]

Stage 6 reached. Next: /experiment analyze or /audit exp_007.
```

## Banned vocabulary

The output produced by this skill — both the orchestration text and any case dialog rendered to the user — must avoid the tokens below. These mirror the standard banned vocabulary list and are treated as syntax errors by the voice CI.

- `leverage`
- `powerful`
- `delightful`
- `robust`
- `seamless`
- `cutting-edge`
- `great question`
- `excellent observation`
- `we're excited`
- `successfully` (as a self-congratulatory adverb, e.g. "I've successfully resumed the experiment")
- `Let me walk you through`
- `Before we begin, let me explain`
- `co-pilot`
- `colleague`

Banned patterns: opening a turn with throat-clearing; manufactured urgency around the recovery ("don't worry, we've got this"); narrating the classifier's work instead of presenting the case; asking the user to confirm every state read. State the case, render its dialog, dispatch the choice.
