# Module 1 — The shape: the eleven stages

> **Goal:** Hold the whole experiment in your head as a single pipeline. Name all
> eleven stages in order (0, 0.5, 0.75, then 1 through 8), say which agent owns
> each, what artifact each commits, and what gate can stop it. By the end you can
> drive `ship_demo.csv` from Stage 0 to a SHIP verdict and narrate every step as
> it happens.

---

## Why (the design reasoning)

An experiment platform is really a pipeline with a conscience. The pipeline
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

The single most important structural fact to carry out of this module: every
stage ends at the same chokepoint, `_commit_stage` — and that one function is
where the artifact gets written, the chain gets validated, and the state advances. Eleven stages, one commit path. When you understand that one
function (Module 6 goes deep; we meet it here), the whole pipeline stops looking
like eleven things and starts looking like one thing that runs eleven times.

### Where the stages actually run

Re-anchor the two surfaces from the README before you trace anything:

- The **shell CLI** (`agentxp …`) does setup and inspection only.
- The eleven-stage pipeline runs inside a Claude Code conversation, started
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

| # | Stage (`state` value) | Owner agent | Commits (artifact) | Gate that can stop it |
|---|-------|-------------|--------------------|-----------------------|
| 0 | **Profile** (`data_loaded`) | `profiler` | `data_plan.yaml` (partial: source + register) | bad timestamps → `mixed_timestamp_formats` (escalated only) |
| 0.5 | **Semantic models** (`semantic_models_drafted`) | `semantic_modeler` | `semantic_models/{entity}.yaml` | `confirm_semantic_model` |
| 0.75 | **Metrics** (`metrics_bootstrapped`) | `metric_drafter` | `metrics/{name}.yaml` | `confirm_metric` |
| 1 | **Intent** (`intent_captured`) | `designer.elicitor` | captured intent + `conversation.jsonl` | — (multi-turn; no gate) |
| 2 | **Hypothesis** (`hypothesis_drafted`) | `designer.elicitor` (hypothesis mode) | `decisions/02-hypothesis.yaml` | — (folds into `confirm_brief`) |
| 3 | **Brief / pre-register** (`brief_drafted`) | `designer.drafter` + `consistency_judge` | locked `experiment.yaml` + `decisions/03-brief.yaml` | `confirm_brief` |
| 3b | **(substate) Contradiction** (`brief_contradicted`) | `consistency_judge` fires; `designer.editor` on edit | `decisions/03b-contradiction.yaml` | `brief_contradiction` (r/e/o) |
| 4 | **Data plan** (`data_plan_confirmed`) | `designer.drafter` (+ `metric_drafter`) | full `data_plan.yaml` + `decisions/04-data-plan.yaml`; DAG → POWERED | `confirm_data_plan`, `confirm_cohort`, `confirm_assignment` |
| 5 | **Monitor / SRM** (`monitor`) | `sql_query_writer` + `monitor` | `analyses/{ts}.json` (pre-analysis); DAG → COLLECTING → ANALYZING | `confirm_query`; SRM breach → `srm_override` |
| 6 | **Analyze** (`analyze`) | `sql_query_writer` + `analyzer` | `analyses/{ts}.json` (full: lifts, CIs, p-values) | `confirm_query`; `cross_adapter_resolution` |
| 7 | **Interpret** (`interpret`) | `interpreter` (blind) | `interpretation.json` (verdict + confidence); DAG → INTERPRETED | — (this is the verdict itself) |
| 8 | **Read out** (`readout`) | `readout` | `report.md` + `report.json`; DAG → REPORTED | `confirm_readout` (+ `NoShipReasonCode` on a no-ship) |

That's eleven stages, not nine: the decimal stages 0.5 and 0.75 are real stages
with their own agents and gates, and 3b is a *substate* of Stage 3, not a stage of
its own. Stages 0.5 and 0.75 skip automatically when the project already has
matching semantic models and metrics, which is why a second experiment on the same
data feels shorter. A few things to notice, because reviewers will test you on them:

- **Stage 3 is the integrity hinge.** The brief (`experiment.yaml`) is *locked*
  here — written once, and `_write_artifact` will refuse to overwrite it (Module 4,
  the `ArtifactLocked` wall). Everything downstream is measured against this locked
  rule. This is the stage the README calls "pre-register."
- **Stage 3b is a substate, not a full stage.** It only exists when the
  `consistency_judge` catches the drafted brief contradicting the hypothesis (at
  confidence ≥ 0.7). It opens a revert / edit / override (r/e/o) gate; an override
  is logged with a reason and the contradiction is preserved in
  `decisions/03b-contradiction.yaml`. No silent edits.
- **There is no standalone "power" or "collect" stage.** Power and MDE are
  parameters of the brief (Stage 3) and the data plan (Stage 4); collection is the
  `POWERED → COLLECTING → ANALYZING` transition that rides on the Stage 5 commit.
  If you remember an earlier draft that listed "Stage 3 Power" and "Stage 4
  Collect," forget it — those were never real stages.
- **The interpreter (Stage 7) is the blind judge.** It renders the verdict from the
  analyzer's numbers and the locked brief's rules, and it never sees your hypothesis
  prose or what you hoped for (Module 2's isolation axiom). Guardrails are *measured*
  by the analyzer at Stage 6 and *enforced* by the tree at Stage 7 (Step 2 →
  `NO-SHIP-GUARDRAIL`); the monitor at Stage 5 is a different check — sample-ratio
  mismatch (SRM), not guardrails.
- **Stage 8 is the only stage that produces prose**, and the readout agent is told
  the verdict is already decided and unchangeable — it *explains*, it does not
  *re-decide* (`readout.system.md`: a readout that argues with the verdict is wrong
  by construction).

### The one function under all eleven: `_commit_stage`

Every stage, no matter which agent ran, ends the same way. The orchestrator calls
`_commit_stage` on the `OrchestratorStore`, and that one function writes the
artifact, validates the chain, appends to the log, and advances the state — under
a lock, with SIGINT deferred so Ctrl-C can't tear a commit in half.

The one ordering to memorize is the tail: **validate the chain → append
`stage.committed` to `log.jsonl` → write `state.yaml` last.** The log is the
source of truth, so it must record the step before the state claims it. That
*validate → append → advance* sequence is what closes the G11 crash window and
makes a crash mid-commit recoverable. Module 6 traces all eight steps line by
line; here you only need the chokepoint and that tail ordering.

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
$ ls experiments/<exp_id>/         # experiment.yaml, data_plan.yaml, decisions/, analyses/, interpretation.json, report.md, log.jsonl, state.yaml
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

1. **List all eleven stages in order** (0, 0.5, 0.75, 1–8, plus the 3b substate),
   and for each name the owner agent, the artifact it commits, and the gate that
   can stop it.
2. **Explain why Stage 3 (pre-register) must come before Stage 6 (analyze)** in
   terms of the thesis — why ordering *is* the integrity mechanism.
3. **Name the one function every stage funnels through** and recite the
   validate → append → advance ordering, and say what crash it protects against.
4. **Name the blind judge (Stage 7, the interpreter)**, say what it's blind to (your
   hypothesis prose, what you hoped for), and why that makes the verdict more
   trustworthy, not less.

Drive `ship_demo.csv` 0→8 in front of me and narrate it as you go. When your
narration matches the `agentxp audit` timeline, check the box and we go to
Module 2.
