# Module 1 — The shape: 11 stages

> **Goal:** Hold the whole experiment in your head as a single pipeline. Name all
> 11 stages in order, say which agent owns each, what artifact each commits, and
> what gate can stop it. By the end you can drive `ship_demo.csv` from Stage 0 to
> a SHIP verdict and narrate every step as it happens.

---

## Why (the design reasoning)

An experiment platform is really a **pipeline with a conscience**. The pipeline
part is ordinary: ingest data, check it, design a test, collect, analyze,
interpret, write it up. The conscience is the part that makes AgentXP different —
at fixed points the pipeline *stops itself* and refuses to continue unless a
condition holds. Those stopping points are the **gates**, and they are the
physical expression of the thesis from Module 0: the verdict stays honest because
the structure won't let you skip the steps that keep it honest.

So the eleven stages aren't an arbitrary decomposition. Each stage exists because
there is exactly one kind of judgment or computation that must happen there, in
that order, and committing it produces an **artifact** — a YAML file written once
and never silently rewritten (Module 4). The artifact is the receipt. The order
is load-bearing: you cannot design a decision rule *after* you've seen the
analysis, because then the rule is just a story about the result. Stage order is
how pre-registration is enforced in time.

The single most important structural fact to carry out of this module:
**every stage ends at the same chokepoint — `_commit_stage`** — and that one
function is where the artifact gets written, the chain gets validated, and the
state advances. Eleven stages, one commit path. When you understand that one
function (Module 6 goes deep; we meet it here), the whole pipeline stops looking
like eleven things and starts looking like one thing that runs eleven times.

### Where the stages actually run

Re-anchor the two surfaces from the README before you trace anything:

- The **shell CLI** (`agentxp …`) does setup and inspection only.
- The **eleven-stage pipeline runs inside a Claude Code conversation**, started
  with `/experiment`. **Claude is the orchestrator** — it walks the stages,
  dispatches the agents, and calls the commit path. The headless Python
  orchestration loop (`_invoke_llm` / `advance()`) is deliberately stubbed in
  v0.1 (Phase 5; Module 7 explains why that's an honest boundary, not a bug).

That means "Stage 4 runs the analyzer" really means: Claude, acting as
orchestrator, assembles a bundle for the analyzer agent, runs it, and commits the
result through `_commit_stage`. Hold that mental model — it makes Module 2 (agents
as programs) click.

---

## The eleven stages

Read this table as the spine of the whole course. Every later module zooms into
one row or one column of it.

| # | Stage | Owner agent | Commits (artifact) | Gate that can stop it |
|---|-------|-------------|--------------------|-----------------------|
| 0 | **Profile** | `profiler` | `profile.yaml` — column types, row counts, candidate metrics | data unreadable / not an experiment → decline |
| 1 | **Design** | `designer/*` (architect, editor, namer) | `experiment.yaml` (hypothesis, variants, metrics) | non-experimental request → clean decline |
| 2 | **Pre-register** | `designer` + orchestrator | locked `brief.yaml` (the decision rule) | rule incomplete (no MDE / direction / guardrails) |
| 3 | **Power** | `power` reasoning + `stats.power_*` | `power.yaml` (MDE, n required, achieved power) | underpowered design → warn / redesign |
| 3b | **(substate) Collect-readiness** | orchestrator | gate record | not enough data to proceed |
| 4 | **Collect** | orchestrator + adapters | `collection.yaml` (query receipts, row counts) | SRM / data-quality halt |
| 5 | **Analyze** | `analyzer` + `stats.*` | `analysis.yaml` (lifts, CIs, p-values, SRM χ²) | analysis can't be computed |
| 6 | **Monitor** | `monitor` | `monitor.yaml` (guardrail check) | guardrail breach → block ship |
| 7 | **Interpret** | `interpreter` (blind) | `verdict.yaml` (one of 8 labels) | — (this is the verdict itself) |
| 8 | **Read out** | `readout` | `readout.md` (the human-facing writeup) | — (terminal) |

A few things to notice, because reviewers will test you on them:

- **Stage 2 is the integrity hinge.** The brief is *locked* here — written once,
  and `_write_artifact` will refuse to overwrite it (Module 4, the `ArtifactLocked`
  wall). Everything downstream is measured against this locked rule.
- **Stage 3b is a substate, not a full stage.** It's the "do we have enough
  collected data to analyze?" checkpoint. It exists because collect-then-analyze
  has a readiness condition that's cleaner to model as its own gate than to bury
  inside Stage 4.
- **Stages 6 and 7 are the two blind judges.** The monitor checks guardrails and
  the interpreter renders the verdict — and *neither sees your hypothesis prose or
  what you hoped for* (Module 2's isolation axiom). The monitor can block a ship
  the interpreter would otherwise grant; the rule beats the number.
- **Stage 8 is the only stage that produces prose**, and it's produced by an agent
  that is told the verdict is already decided and unchangeable — the readout
  *explains*, it does not *re-decide* (`readout.system.md §6`: a readout that
  argues with the verdict is "wrong by construction").

### The one function under all eleven: `_commit_stage`

Every stage, no matter which agent ran, ends the same way. The orchestrator calls
`_commit_stage` on the `OrchestratorStore`, and that function does a fixed
sequence (we trace it line-by-line in Module 6; here's the shape so you recognize
it):

1. **Disk pre-flight** (space check) — *outside* the lock, so a full disk fails
   fast without holding the lock.
2. **Acquire `.state.lock`** — the concurrency guard on `state.yaml`.
3. **Defer SIGINT** — so Ctrl-C can't tear a commit in half.
4. **Write the artifact(s)** via `_write_artifact` (refuses to overwrite a locked
   file).
5. **Mutate state in memory.**
6. **`validate_chain` BEFORE advancing** — if the audit chain wouldn't validate,
   the commit doesn't happen.
7. **Emit `stage.committed` to `log.jsonl` BEFORE writing `state.yaml`** — this is
   the *append-then-advance* ordering that closes the G11 crash window: the log is
   the source of truth, so the log must record the step before the state claims
   it.
8. **Write `state.yaml` last.**

Memorize the ordering of 6→7→8 (validate, then append, then advance). It's the
whole reason a crash mid-commit is recoverable (Module 6, resume).

---

## Walkthrough (trace one real run on paper first)

Before you run anything, trace `ship_demo.csv` through the table in your head.
It's the end-to-end anchor fixture: n=3k/group, +22.3% conversion, designed to
land on **SHIP** by walking the full Stage 0→8 path.

Open these and follow along:

```bash
$ cd ~/projects/agentxp
$ less .claude/skills/experiment/STAGES.md      # the stage-by-stage spec
$ less sample-data/ship_demo.csv | head          # the fixture itself
$ ls agents/                                      # the owners column, as files
```

For each stage, ask the three questions the table answers: *who owns it, what
does it commit, what could stop it?* When you can do that for all eleven without
looking, you've got the spine.

---

## Lab (drive it end to end)

**Lab 1a — watch the pipeline run.** Open Claude Code in the repo and run:

```
> /experiment --data sample-data/ship_demo.csv
```

Drive it through to Stage 8. Don't try to master the conversation yet — just
*name the stage you're in* at each step and predict the artifact about to be
committed. You should reach a **SHIP** verdict. When you do, inspect the receipts:

```bash
$ ls experiments/                  # find the exp_id that was created
$ ls experiments/<exp_id>/         # profile.yaml, brief.yaml, ... readout.md
$ agentxp audit <exp_id>           # the full event timeline + chain integrity
```

The `agentxp audit` output is the eleven stages made visible: one block of events
per `_commit_stage`, ending in `chain integrity: OK`.

**Lab 1b — confirm the spine in the test suite.** The E2E run is also a test, so
you can watch it deterministically:

```bash
$ .venv/bin/python -m pytest tests/smoke/test_e2e_ship_demo.py -v
```

Read that test file alongside the run. It is the executable version of this whole
module — Stage 0→8 with `validate_chain` ON the entire way (Module 7 explains why
that "ON" is the hard-won part).

---

## Teach-back checkpoint

You pass Module 1 when you can, without notes:

1. **List all 11 stages in order** (0→8 plus 3b), and for each name the owner
   agent, the artifact it commits, and the gate that can stop it.
2. **Explain why Stage 2 (pre-register) must come before Stage 5 (analyze)** in
   terms of the thesis — why ordering *is* the integrity mechanism.
3. **Name the one function every stage funnels through** and recite the
   validate → append → advance ordering, and say what crash it protects against.
4. **Point at two stages whose agents are deliberately blind**, and say what each
   is blind to and why that makes the verdict more trustworthy, not less.

Drive `ship_demo.csv` 0→8 in front of me and narrate it as you go. When your
narration matches the `agentxp audit` timeline, check the box and we go to
Module 2.
