# Module 4 — The integrity spine

> **Goal:** Understand *why anyone should believe the verdict*, mechanically. By
> the end you can name all five chain invariants and what each rejects, explain
> the locked-rule wall (`ArtifactLocked`) precisely, distinguish the parent-action
> chain from the replay hash, and break an invariant on purpose and watch the
> system catch you.

---

## Why (the design reasoning)

The product's headline promise is: *two reviewers replay the append-only log and
reach the same answer.* That promise has a sharp history — the system audit
(Module 7) found it was once **green-but-broken**: the validator couldn't fire,
the log wasn't replay-reproducible, and the integrity wall didn't exist in the
code. The remediation made all three real. This module is the result, and it's the
subsystem that most justifies the word "trustworthy."

There are two distinct integrity mechanisms here, and conflating them is the
most common mistake. Teach them as separate ideas:

1. **The parent-action chain** — every logged event names its parent by
   `parent_action_id` (a ULID reference to a prior event's `action_id`). This is
   linkage *by ID*, not by content hash. `validate_chain` walks the log and
   enforces that the references form one clean, forward-only, cycle-free tree.
   **It is not a blockchain.** Do not say "each event hashes the previous one."
2. **The replay hash** (`canonical_chain_hash`) — a SHA-256 over the
   canonical-JSON of the whole event log, used as a *replay-determinism* anchor:
   same run → same hash. This is the credibility check that two replays produced
   identical histories. It's separate from `validate_chain` and the audit CLI
   doesn't even call it.

And one more wall, structurally simpler but conceptually central:

3. **The locked-rule wall** — a committed artifact (your pre-registered brief)
   exists on disk, and `_write_artifact` *refuses to overwrite it*. Locking isn't
   a flag; **existence on disk is the lock.** This is how pre-registration is
   enforced against your future, results-tempted self.

---

## Walkthrough — the three mechanisms in code

### 1. The five chain invariants (`agentxp/audit/chain.py`)

`validate_chain(experiment_id, *, from_event=0, to_event=None, perf_budget_ms=200, _root=None) -> ChainValidation`
is called at every `_commit_stage` (Module 1, step 6). Critically: **it returns
violations, it does not raise on them.** It returns a `ChainValidation` with
`ok = (len(violations) == 0)`. The *only* thing it raises is `PerfBudgetExceeded`,
when validation takes longer than the hard cap (2× the soft budget — default
400 ms). That design choice matters: integrity problems are *data* to be surfaced
and acted on, not exceptions that crash the process.

The five invariants, exactly as the code numbers them:

- **Invariant 1 — parent-action chain integrity.** One pass with a `seen` set.
  Rejects: a duplicate `action_id`; a non-root event whose `parent_action_id` is
  null *after* a root was already seen; a `parent_action_id` that wasn't seen
  earlier in the file. Because the seen-set is built in file order, a forward
  reference fails the existence check — so **cycle-freeness falls out for free.**
  Exactly one root (null parent), and it must come first.
- **Invariant 2 — conversation_ref integrity.** Each `bundles/*.ctx.yaml` that
  carries a `conversation_ref` must point at a `through_turn_id` that actually
  exists in `conversation.jsonl`. (Orphan turns the other way are not checked in
  v0.1.)
- **Invariant 3 — artifact reference integrity.** Every `query_id` referenced from
  a `bundles/*.out.yaml` must resolve to a real `queries/{query_id}.yaml` on disk.
  (The old `decisions/*.yaml` hash sub-check was *removed* because nothing writes
  `decisions/` in v0.1 — a deliberate decoupling of a live checker from dead code,
  see Module 7.)
- **Invariant 4 — no `stage.committed` while a gate is OPEN.** You can't commit a
  stage while a gate you opened in it is still unresolved. Gates are attributed to
  the ambient stage (the most recent `stage.entered`).
- **Invariant 5 — no `gate.resolved` without a preceding `gate.opened`** of the
  same kind in the same stage. `gate.blocked` is exempt (it's a terminal system
  halt, not a paired open/resolve).

The result types live in `agentxp/schemas/report.py`: `Violation`
(`invariant_id ∈ {1..5}`, `description`, optional `offending_action_id` /
`offending_path`) and `ChainValidation` (`ok`, `invariants_checked`, `violations`,
`ms`, `perf_warning`). Both are `extra="forbid"`.

### 2. The event model (`agentxp/audit/events.py`)

A **closed 13-event enum** (`EventName`) — `stage.entered/committed`,
`gate.opened/resolved/blocked`, `agent.dispatched/completed`,
`query.proposed/validated/executed/failed`, and two RESERVED-in-v0.1 hook events
that are never emitted. Closure is itself tested (`len(EventName) == 13`).

Every event shares a 9-field base payload (`extra="forbid"`): `schema_version`,
`timestamp` (UTC-enforced — naive datetimes are *rejected* with a `ValueError`,
because a naive timestamp would corrupt chain validation), `action_id` (ULID),
`parent_action_id` (the linkage), `actor_kind`, `actor_name`, `experiment_id`,
plus the pinned `event_name`. Some events carry content anchors — `bundle_hash`,
`raw_hash`/`ast_hash` (on `query.proposed`), `result_hash` (on `query.executed`).
These are recorded values, not chain links — `validate_chain` doesn't verify
them; they're for replay and provenance.

The **append-only substrate** (`agentxp/audit/storage.py`) adds two physical
guards worth knowing: every log line must be ≤ 4096 bytes (PIPE_BUF, so appends
are atomic and can't interleave), and the file is created `chmod 600` and
re-verified 600 on every append — if the mode drifted, the write is refused
with a `PermissionError`. Integrity isn't only logical; it's enforced at the
filesystem.

### 3. The locked-rule wall (`agentxp/orchestrator/store.py`)

`_write_artifact(filename, payload, *, amend=False)`:

- Resolves the target path; a path that escapes the experiment dir raises
  `ValueError`.
- **If the file already exists and `amend` is False → raises `ArtifactLocked`.**
  The current message names the v0.1 boundary explicitly: the artifact is already
  committed, the store refuses to overwrite it, v0.1 does not auto-apply
  post-commit amendments through this store (G14), and *the supported way to
  change a locked pre-registration is to start a new experiment.*
- `amend=True` is a **reserved write seam** — not wired into any live flow in
  v0.1. It exists for the future chain-aware amendment path.

So "locked" is not a bit you set. **A committed file *is* the lock**, because
everything reaches disk through `_commit_stage`, and `_commit_stage` writes
through `_write_artifact`. The integrity wall and the commit path are the same
path.

### 4. Amendments — the disclosed-deviation layer (`agentxp/amendments/`)

If the brief is locked, how do you *ever* record a legitimate change? Through the
amendments subsystem — and the key fact is that **it's deliberately a separate
audit layer, not a way to rewrite the locked file.** `AmendmentTracker.record_amendment`
diffs the proposed change against the saved experiment (`diff_experiments`),
classifies each change as **material** or **administrative** (`classify_change` —
metric/power/hypothesis/variant/data changes are material; description/notes/tags/
owner are administrative), requires a reason ≥ 10 chars ("describe WHY, not just
WHAT"), and appends an `Amendment` record to `amendments.jsonl` plus a breadcrumb
to the log. It does not write the new YAML to disk.

The honest v0.1 boundary (G14): the `amendments/` package runs against the legacy
store, *not* the chained orchestrator log. So amendments are real and tested, but
they are **not yet chained into the orchestrator's log** — wiring them naively
would break Invariant 1, since an un-chained event has no valid parent. Module 6
explains the two-store split that makes this concrete; Module 7 covers why it was
kept-but-unwired rather than deleted or half-wired.

### 5. `agentxp audit` — replay on demand (`agentxp/cli/audit.py`)

The CLI that makes all of this inspectable. `agentxp audit <exp_id>` prints the
event timeline and, if events exist, re-runs `validate_chain` and prints
`chain integrity: OK` or `FAILED — <first violation description>`. Flags:
`--json` (raw events), `--diff <other_exp_id>`, `--html`, `--quiet`. This is the
"replay me, don't trust me" promise as a command you can run.

---

## Lab / break-it (this is the module where you attack the system)

**Lab 4a — break the parent chain (Invariant 1).** Copy a completed experiment's
directory, then hand-edit one event in `log.jsonl`: change its `parent_action_id`
to a ULID that appears *nowhere*, or duplicate an existing `action_id`. Run
`agentxp audit <exp_id>`. Expected: footer reads
`chain integrity: FAILED — parent_action_id=… not found before action_id=…`
(or `duplicate action_id=…`). You just proved tampering is detected on every read
— no hash needed, the *reference graph* itself is the tripwire.

**Lab 4b — try to rewrite a locked brief (the wall).** From Python:

```python
from agentxp.orchestrator.store import OrchestratorStore, ArtifactLocked
# open a store for an experiment that already committed brief.yaml, then:
store._write_artifact("brief.yaml", some_new_payload)   # no amend=True
```

Expected: `ArtifactLocked: artifact 'brief.yaml' is already committed … refusing
to overwrite a locked artifact … to change a locked pre-registration, start a new
experiment.` Then re-run with `amend=True` and watch it allow the write — and note
that `amend=True` is the reserved seam nothing in v0.1 actually calls.

**Lab 4c — break gate pairing (Invariants 4/5).** In `log.jsonl`, move a
`gate.resolved` line *above* its `gate.opened`, or insert a `stage.committed` while
a gate kind is still open. `agentxp audit` → `FAILED — gate.resolved(…) without
preceding gate.opened` or `… emitted while gate kind=… is OPEN`.

**Lab 4d — break the filesystem guard.** `chmod 644 experiments/<exp_id>/log.jsonl`,
then drive any code path that appends an event. Expected: `PermissionError:
Refusing to write … mode drifted to 0o644, expected 0o600.` Integrity is enforced
below the application layer.

**Lab 4e — confirm replay determinism.** Edit any event body and recompute
`canonical_chain_hash(exp_dir)` before and after — the hash changes. Then run the
same fixture twice cleanly and confirm the hash matches. This is the "two reviewers
get the same answer" claim, made concrete.

(For each lab, the matching tests under `tests/audit/test_validate_chain.py`,
`tests/orchestrator/test_store.py`, `tests/audit/test_storage.py`, and
`tests/test_amendments.py` show the same refusals as green assertions — read them
alongside your hand-breaking.)

---

## Teach-back checkpoint

You pass Module 4 when you can, without notes:

1. **Distinguish the three mechanisms** — the parent-action chain, the replay hash,
   and the locked-rule wall — and say what each guarantees. Explicitly correct the
   "it's a blockchain" misconception.
2. **Name all five invariants** and what each rejects, and explain why
   `validate_chain` *returns* violations rather than raising (and what the one
   exception it raises is).
3. **Explain the lock precisely**: what marks an artifact locked (existence on
   disk), what `_write_artifact` does on a locked file, what `amend=True` is and
   isn't, and the supported way to change a locked pre-registration.
4. **Explain the amendments boundary (G14)**: why amendments are a separate audit
   layer on a different store, and why naive wiring would break Invariant 1.
5. **Break one invariant in front of me** and read the refusal aloud.

When you can attack the chain four ways and predict each refusal exactly, check the
box and we go to Module 5.
