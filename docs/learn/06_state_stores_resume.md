# Module 6 — State, stores & resume

> **Goal:** Understand how an experiment survives a crash. By the end you can name
> the two store layers and why they're separate, recite the `_commit_stage`
> ordering and the exact crash window it closes, and interrupt a real run and
> resume it from the log.

---

## Why (the design reasoning)

An eleven-stage pipeline that talks to a warehouse and an LLM *will* get
interrupted — Ctrl-C, a dropped connection, a full disk, a laptop lid. The
question isn't whether it crashes; it's whether a crash can leave the experiment
in a **lying state**: the `state.yaml` says "Stage 5 committed" but the artifact
or the log doesn't back that up. If that can happen, the whole replay promise
(Module 4) is hollow — you'd be replaying a fiction.

So the design rule is: **the append-only log is the source of truth, and state is
a derived cache that can always be rebuilt from the log.** State never gets ahead
of the log. That single ordering constraint — *append to the log before you
advance the state* — is what makes every crash recoverable, because on restart you
can trust the log and discard any state that ran ahead of it.

---

## Walkthrough — two stores, one chokepoint, one rebuild

### The two store layers (and why they're not unified)

There are two stores in the codebase, and conflating them causes most of the
confusion around amendments (Module 4, G14):

- **`OrchestratorStore`** — the pipeline store. Root: the project's
  `experiments/{exp_id}/`. Holds the **chained** `log.jsonl` (the
  `parent_action_id` chain), the committed artifacts, `state.yaml`, the bundles,
  and the queries. This is what `_commit_stage` writes to and what
  `validate_chain` validates. Everything in Modules 1–5 lives here.
- **`ExperimentStore`** — the *legacy* store. Root: `~/.agentxp/experiments`. Holds
  an **un-chained** `log.jsonl`. The `amendments/` subsystem operates on *this*
  store.

They are deliberately **not unified in v0.1**. That's the honest boundary behind
G14: you can't naively chain amendments into the orchestrator log because the
legacy store's events have no valid `parent_action_id`, so they'd fail Invariant 1
the instant `validate_chain` ran. Module 7 covers why this was left as an honest
boundary rather than half-wired.

### The chokepoint: `_commit_stage`

Every stage ends here (Module 1). The ordering is the whole module — memorize it:

1. **Disk pre-flight** — check free space *outside* the lock, so a full disk fails
   fast and doesn't strand the lock. (A `gate.blocked` is emitted if the pre-flight
   fails.)
2. **Acquire `.state.lock`** — a sidecar file lock guarding `state.yaml`, carrying
   a JSON envelope with PID + UTC timestamp so a *stale* lock (dead PID) can be
   detected and broken, while a *fresh* lock blocks.
3. **Defer SIGINT** — Ctrl-C is held off so the commit can't be torn in half.
4. **Write the artifact(s)** via `_write_artifact` — which refuses to overwrite a
   locked file (Module 4).
5. **Mutate state in memory** — not yet on disk.
6. **`validate_chain` BEFORE advancing** — if the chain wouldn't validate, the
   commit is abandoned. The integrity check gates the advance.
7. **Emit `stage.committed` to `log.jsonl` BEFORE writing `state.yaml`** — this is
   the **append-then-advance** ordering (the G11 fix). The log records the step
   *before* the state claims it.
8. **Write `state.yaml` last.**

Now see the crash window it closes. Suppose the process dies *between* steps 7 and
8: the log says "Stage N committed" but `state.yaml` still says "Stage N−1." On
restart, you rebuild state from the log and arrive at the truth (Stage N). The
*opposite* ordering — advance state, then append log — would create the lying
state: `state.yaml` ahead of the log, claiming a commit the log can't prove. The
ordering is chosen so that any crash leaves the log either equal to or *ahead of*
state, never behind. Equal-or-ahead is recoverable; behind is a lie.

### Rebuilding: `reconstruct_from_log()` (`store.py:570`)

`OrchestratorStore.reconstruct_from_log()` walks the chained `log.jsonl` and
rebuilds the in-memory experiment state purely from the events — no trust in the
possibly-stale `state.yaml`. This is the function that makes "the log is the
source of truth" operational: state is *derived*, and this is the derivation.

### Resume: the 8 cases (`agentxp/cli/resume.py::_detect_case`)

`agentxp resume` doesn't guess — it classifies the on-disk situation into one of
**8 cases** (`_detect_case`) and surfaces the recommended next action on stderr.
Be precise about what v0.1 does here: **resume detects and reports; it does not
auto-fix.** The docstring says so outright ("v0.1 does not auto-fix"). It loads
`state.yaml` and `log.jsonl`, prints something like `resume case 5: lock died
mid-commit … current_stage may advance on resume`, and returns an exit code —
clean no-op for Case 1, a user-error code for the cases that need attention (unless
you pass `--force` to acknowledge). The actual roll-forward is
`reconstruct_from_log` (below), which the orchestrator runs on the next dispatch
inside Claude Code; `resume` is the diagnosis, not the repair. The point isn't to
memorize all eight verbatim; it's to understand that **resume is a function of
(log, state) divergence**, and each divergence has one correct resolution because
the append-then-advance ordering constrains what divergences are even possible.

---

## Lab / break-it (kill it and bring it back)

**Lab 6a — interrupt and resume a real run.** Start `/experiment` on
`ship_demo.csv`, drive it a few stages in, then hard-interrupt (Ctrl-C, or just
close the conversation) mid-pipeline. Then:

```bash
$ agentxp list                      # see the half-finished experiment
$ agentxp audit <exp_id>            # the log shows committed stages; chain OK
$ agentxp resume <exp_id>           # detect the case, print the recommendation
```

Read the `resume case N: …` line it prints to stderr — that's the diagnosis, the
divergence it found between log and state, and what to do next. It does *not*
silently roll the experiment forward; the roll-forward happens when you re-open the
experiment in Claude Code and the orchestrator calls `reconstruct_from_log` (Lab
6b). Confirm the case it reports matches where you interrupted.

**Lab 6b — watch the rebuild in the test suite.**
```bash
$ .venv/bin/python -m pytest tests/smoke/test_resume_reconstruct_from_log.py -v
```
Read that test next to `reconstruct_from_log`. It deliberately constructs a
log-ahead-of-state situation and proves the rebuild lands on the truth.

**Lab 6c — manufacture the lying state and watch the detector catch it.** Copy a
completed experiment dir. Hand-edit `state.yaml` to claim a stage *behind* what
`log.jsonl` records (simulating the crash between steps 7 and 8). Run `agentxp
resume` and confirm it detects the log-ahead-of-state divergence and reports the
matching case (it tells you the state may advance on resume — it does not rewrite
`state.yaml` itself). Then drive the actual roll-forward by calling
`reconstruct_from_log` directly (as Lab 6b's test does) and confirm it lands on the
log's stage, ignoring the stale state. Then try the reverse — make `state.yaml`
claim a stage *ahead* of the log — and reason about why the append-then-advance
ordering means this divergence shouldn't occur from a real crash, only from
tampering (and how that connects to `validate_chain`).

> **Not a Python person?** Labs 6a and 6d are pure CLI — you can do them as-is. For
> 6b/6c, you don't have to call `reconstruct_from_log` yourself: hand-editing
> `state.yaml` and running `agentxp resume` (6a/6c) shows the *detection*, and
> reading `tests/smoke/test_resume_reconstruct_from_log.py` shows the *rebuild*. The
> CLI plus the test give you the whole resume story without writing any Python.

**Lab 6d — exercise the lock.** Inspect `.state.lock` during a run (PID + timestamp
envelope). Read the store tests for stale-lock detection
(`tests/orchestrator/test_store.py`: dead-PID stale lock is broken; fresh lock
blocks then acquires; disk-full pre-flight emits `gate.blocked`).

---

## Teach-back checkpoint

You pass Module 6 when you can, without notes:

1. **Name the two stores**, their roots, which one is chained, which the
   amendments subsystem uses, and why they're deliberately not unified (tie it to
   G14 and Invariant 1).
2. **Recite the `_commit_stage` ordering**, especially steps 6→7→8 (validate →
   append → advance), and explain the exact crash window the append-then-advance
   ordering closes and why the opposite ordering would create a lying state.
3. **Explain `reconstruct_from_log`** — what it trusts, what it ignores, and why
   "state is a derived cache" is the whole design.
4. **Explain resume as a function of (log, state) divergence** — why the ordering
   constrains which divergences are even possible.

I'll describe a crash point (e.g., "process dies between the log append and the
state write") and ask you what's on disk and what resume does. When you can answer
for any crash point, check the box and we go to Module 7.
