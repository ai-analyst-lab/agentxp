# Hostile accuracy review — `docs/learn/` curriculum vs. AgentXP source

Reviewer stance: adversarial fact-check. Every claim traced to source `file:line`.
Date: 2026-05-30. Source tree: `/Users/shanebutler/projects/agentxp/`.

## Verdict

**Overall grade: C+ (accurate on the deep internals, badly wrong on the pipeline spine it opens with).**

The curriculum is *extremely* accurate where it quotes Python internals: Module 4
(integrity spine), Module 5 (SQL safety + redaction), and Module 7 (build history)
are near-flawless — constants, exception names, error strings, gap register, and
audit quotes all check out verbatim. But Module 1 (the "11 stages" spine that the
whole course is built on) and Module 2's agent roster are **structurally wrong**:
the stage→owner→artifact table mis-numbers the pipeline, omits two real stages,
reverses Analyze/Monitor, mislabels Stage 3b, and invents agent names that do not
exist. Module 6 overclaims what `agentxp resume` actually does.

**Count: 11 WRONG, 9 IMPRECISE.** Most serious WRONG claim: the entire Module 1
11-stage table (stage numbering, owners, artifacts, and the Stage 3b definition)
does not match `.claude/skills/experiment/STAGES.md` — and Module 1 is the spine
every other module hangs off.

---

## WRONG claims

### W1. The Module 3 verdict labels are wrong (5 of 8 names invented)
- **Curriculum** (`03_deterministic_core.md:77-98`): lists the 8 verdicts as
  `INVALID-SRM, NO-SHIP-GUARDRAIL, SHIP, NO-SHIP, LEARN (powered),
  LEARN (underpowered), caveat / investigate, (terminal/fallback)`.
- **Ground truth** (`agentxp/interpret/tree.py:29-38`): the `Verdict` literal is
  exactly `INVALID-SRM, NO-SHIP-GUARDRAIL, INCONCLUSIVE, NO-LIFT,
  DIRECTIONAL-ONLY, LIFT-WITH-CAVEAT, SHIP, LEARN`.
- The curriculum invents `NO-SHIP`, `LEARN (powered)`, `LEARN (underpowered)`,
  `caveat / investigate`, and a `(fallback)` label. None of those are emitted
  verdicts. The real missing labels are `INCONCLUSIVE` (step 3),
  `NO-LIFT` (step 4), `DIRECTIONAL-ONLY` (step 5), `LIFT-WITH-CAVEAT` (steps 6/7,
  the small-lift/novelty caveat), and a single `LEARN` (step 8, with `learn_subcase`
  diagnostics — not two separate verdicts).
- **Fix:** Rewrite the 8-step list to match `tree.py` step-by-step:
  1 SRM→INVALID-SRM, 2 guardrail→NO-SHIP-GUARDRAIL, 3 underpowered+straddle→
  INCONCLUSIVE, 4 well-powered wide null→NO-LIFT, 5 90% excludes/95% straddles→
  DIRECTIONAL-ONLY, 6 benefit-side but |lift|<MDE/2→LIFT-WITH-CAVEAT(small),
  7 SHIP or novelty→LIFT-WITH-CAVEAT(novelty), 8 LEARN. The README cheat-sheet
  "lands on" column (`LEARN (powered)`, `caveat / investigate`, etc.,
  `README.md:100-104`) is wrong for the same reason.

### W2. Module 1 stage table — owners, artifacts, numbering all wrong
- **Curriculum** (`01_shape.md:58-69`): Stage 1 Design = `designer/*`
  (architect, editor, namer); Stage 2 Pre-register commits `brief.yaml`;
  Stage 3 = "Power / `power` reasoning + `stats.power_*`"; Stage 5 = Analyze;
  Stage 6 = Monitor.
- **Ground truth** (`.claude/skills/experiment/STAGES.md:11-269`): the eleven
  sections are Stage 0 (profiler), **Stage 0.5 (semantic_modeler)**,
  **Stage 0.75 (metric_drafter)**, Stage 1 intent_captured (designer.elicitor),
  Stage 2 hypothesis_drafted (designer.elicitor), Stage 3 brief_drafted
  (designer.drafter + consistency_judge), Stage 4 data_plan_confirmed,
  **Stage 5 = monitor/SRM**, **Stage 6 = analyze**, Stage 7 interpret, Stage 8 readout.
- Errors: (a) Stages 0.5 and 0.75 are omitted entirely. (b) The brief is drafted
  at Stage 3, not "pre-registered as `brief.yaml`" at Stage 2. (c) There is **no
  dedicated Power stage** — power sizing is done in prose by the drafter, not a
  `power` agent at Stage 3. (d) **Analyze and Monitor are reversed**: the code runs
  monitor/SRM at Stage 5 *before* analyze at Stage 6 (`STAGES.md:187,209`).
- **Fix:** Rebuild the table from `STAGES.md` section headers. At minimum: add
  Stages 0.5/0.75, move the brief lock to Stage 3, delete the phantom Power stage,
  and swap Analyze↔Monitor.

### W3. The designer-trio agent names do not exist
- **Curriculum** (`01_shape.md:61`, `02_agents.md:88-90,97-101`): names the design
  agents `designer/architect`, `designer/editor`, `designer/namer`.
- **Ground truth** (`ls agents/designer/`; `STAGES.md:25`): the three files are
  `elicitor.system.md`, `drafter.system.md`, `editor.system.md`. There is no
  `architect` and no `namer`. SKILL.md resolves `designer.elicitor`,
  `designer.drafter`, `designer.editor`.
- **Fix:** Replace architect→drafter (structure), namer→elicitor (intent/hypothesis
  elicitation). The Module 2 roles ("invent structure / tighten+lock / name it")
  should become elicit-intent / draft-structure / tighten-and-lock.

### W4. The `monitor` agent is the SRM checker, not a Stage-6 guardrail judge
- **Curriculum** (`01_shape.md:67,82`; `02_agents.md:92`): "Stage 6 Monitor … guardrail
  check … guardrail breach → block ship"; "monitor … guardrail breach? block ship?"
- **Ground truth** (`agents/monitor.system.md:7,22`): "You are the **Stage-5
  monitor** … Your single job is the sample-ratio-mismatch (SRM) check." Guardrail
  evaluation is not the monitor's job — it is computed by the analyzer (Stage 6) and
  evaluated deterministically in `walk_tree` Step 2 (`tree.py:250-272`).
- **Fix:** Monitor = Stage 5, SRM only. Move the "guardrail beats the number" logic
  to the analyzer/tree, not the monitor. The Module 1 claim "the monitor can block a
  ship the interpreter would otherwise grant" (`01_shape.md:82-83`) is false — the
  monitor sets `srm_pass`; the tree blocks on guardrails at Step 2.

### W5. "Stage 2 (pre-register) must come before Stage 5 (analyze)" reasoning is mis-anchored
- **Curriculum** (`01_shape.md:177-178`, capstone `08_capstone.md:42`): the lock is at
  Stage 2 and analyze is Stage 5.
- **Ground truth:** the brief lock lands around Stage 3 (`brief_drafted`,
  `STAGES.md:125`) and analyze is Stage 6 (`STAGES.md:209`). The ordering argument is
  sound in spirit but cites the wrong stage numbers.
- **Fix:** "the brief is locked at Stage 3 and analysis runs at Stage 6."

### W6. `agentxp resume` does NOT reconstruct-and-continue
- **Curriculum** (`06_state_stores_resume.md:104-108` Lab 6a;
  `:119-125` Lab 6c): `agentxp resume <exp_id>` will "detect case → reconstruct →
  continue", "picks up from the last logged commit", and "reconstructs forward from
  the log, ignoring the stale state."
- **Ground truth** (`agentxp/cli/resume.py:108-109,281-292`): "v0.1 surfaces all of
  them but **only auto-acts on Case 1 (nothing to do). The rest return a user-facing
  message.**" `main()` calls `_detect_case`, **prints** the case, and returns an exit
  code. It never calls `reconstruct_from_log()`; it does not continue the pipeline.
- **Fix:** `agentxp resume` *classifies* the divergence and prints guidance (and an
  exit code; non-Case-1 needs `--force`). Reconstruction is `reconstruct_from_log()`
  on the store, exercised by the orchestrator/tests — not by the resume CLI. Labs 6a
  and 6c as written would not behave as claimed.

### W7. Module 7 gap-table G6 LOC vs. README G-range
- **Curriculum** (`07_build_history.md:50`): G6 "~2,516 LOC dead code".
- **Ground truth:** `SYSTEM_AUDIT.md:28` says "~2,516 LOC dead/duplicate";
  `OVER_ENGINEERING_REVIEW.md:36` says "Confirmed DEAD ~1,600–1,900" and total
  surface "~23k LOC". The 2,516 figure is the audit's dead+duplicate count; the
  over-engineering review's narrower "dead" count is 1,600–1,900. The curriculum
  presents 2,516 as plain "dead code", conflating two different measures.
- **Fix:** Label it "~2,516 LOC dead/duplicate (per SYSTEM_AUDIT §6)".
  (Borderline IMPRECISE; flagged WRONG only because "dead code" drops "duplicate".)

### W8. README pytest baseline understates the real count
- **Curriculum** (`README.md:45`, `00_thesis.md:114`, `01_shape.md:45-46`): "expect:
  ~1240 passed, ~63 skipped".
- **Ground truth** (`BUILD_STATUS.yaml:15`): "1277 pass / 63 skip / 0 fail".
  Module 7 itself (`07_build_history.md:133`) correctly says 1277. The prereq pages
  say ~1240, which is below the actual baseline and inconsistent with Module 7.
- **Fix:** Use "~1277 passed, ~63 skipped" everywhere.

### W9. `agents/` roster description says "designer/*" exists as a stage owner for "Design"
- **Curriculum** (`01_shape.md:61`): owner agent for Stage 1 "Design" =
  `designer/*` collectively.
- **Ground truth:** Stage 1 (intent_captured) and Stage 2 (hypothesis_drafted) are
  both owned by `designer.elicitor` (`STAGES.md:87,109`); `designer.drafter` owns the
  brief (Stage 3) and the data plan (Stage 4). "Design" is not a single stage.
- **Fix:** Split into the real stages and assign elicitor/drafter accordingly.

### W10. Module 2 "consistency_judge §2 — judges consistency on a restricted view"
- **Curriculum** (`02_agents.md:46,95`): cites `consistency_judge §2` as a blind-judge
  example "judges consistency on a restricted view so it can't be swayed."
- **Ground truth:** `agents/consistency_judge.system.md` exists and runs at Stage 3
  (`STAGES.md:131`, fires at confidence ≥ 0.7), but it checks the brief *against the
  hypothesis and the semantic model* — i.e. it is deliberately given the hypothesis,
  which is the opposite of the "denied the biasing input" framing used for the
  interpreter. Presenting it as an isolation-axiom exemplar is misleading; its job is
  to detect brief↔hypothesis contradiction, which requires seeing both.
- **Fix:** Drop consistency_judge from the "blind judge" list or reframe it as a
  contradiction-detector that is given both sides on purpose.

### W11. Module 2 roster maps interpreter "blind to … `state.yaml`" via "§2 / §9"
- **Curriculum** (`02_agents.md:40-41`): "`interpreter.system.md` §2 / §9 — explicitly:
  *'you do not have access to state.yaml'*."
- **Ground truth** (`agents/interpreter.system.md:121`): the line exists verbatim
  ("…you do not have access to `state.yaml`…") but it is in the inputs/contract body,
  not numbered §2/§9. The quote is real; the section citation is fabricated.
- **Fix:** Drop the "§2 / §9" citation or replace with the real location. (Minor, but
  it is a specific false citation, hence listed.)

---

## IMPRECISE / misleading claims

### I1. `compute_late_ratio` "compares late-window effect to overall"
- `03_deterministic_core.md:106-108`: "compares late-window effect to overall."
- `tree.py:186-216`: `late_window_effect / early_window_effect` (last third / first
  third), **not** late-vs-overall. The `tree.py:186` line citation is correct; the
  description of the ratio is wrong. Fix: "late-window over early-window."

### I2. Stats whitelist "about 30 exported symbols"
- `03_deterministic_core.md:47`: "about 30 exported symbols."
- `stats/__init__.py:86-136`: `__all__` has **33** entries. "About 30" is loose but
  defensible; tighten to "33 exported symbols" for an expert audience.

### I3. Event base payload "9-field"
- `04_integrity_spine.md:91-93`: "Every event shares a 9-field base payload" then
  lists 8 (`schema_version, timestamp, action_id, parent_action_id, actor_kind,
  actor_name, experiment_id`, + pinned `event_name`).
- `audit/events.py:94-128`: `_BasePayload` has 7 own fields; `event_name` is pinned
  in each subclass (8 total counting it). There is no 9th field. Fix: "8-field" (or
  "7-field base + pinned event_name").

### I4. README "gap register (G1–G14)" vs Module 7 "G1–G16"
- `README.md:133` / `00_thesis.md:103` say G1–G14; `07_build_history.md:39` says
  G1–G16. Source has both: `SYSTEM_AUDIT.md:4` ("G1–G14") and §11
  (`SYSTEM_AUDIT.md:153+`, the updated register G1–G16 with G15/G16 "New"). Both are
  technically sourced, but the README should say "G1–G16 (G15/16 found during the
  audit)" to match the live register and Module 7.

### I5. Over-engineering "single quote" is stitched from two passages
- `07_build_history.md:104-106` presents as one block quote: *"It isn't mostly
  over-engineered; it's mis-sequenced — periphery before spine. We built the body
  before the nervous system… a lot of organs exist that nothing yet drives."*
- Source: "periphery before spine" is `OVER_ENGINEERING_REVIEW.md:93`; "we built the
  body before the nervous system" and "a lot of organs exist that nothing yet drives"
  are `:12`. The words are all real but they are not contiguous in the source. Mark
  the ellipsis as spanning sections, or quote them separately.

### I6. "Stage 3b is a substate … collect-readiness"
- `01_shape.md:64,76-79`: Stage 3b = "(substate) Collect-readiness … not enough data
  to proceed."
- `STAGES.md:125-157`: Stage 3b = `brief_contradicted` — the consistency-judge
  contradiction r/e/o dialog inside the brief stage (Section 6). It has nothing to do
  with collect-readiness. (This is arguably WRONG; listed here because the *existence*
  of a "Stage 3b substate" is correct even though its meaning is fabricated.)
  Fix: Stage 3b is the brief-contradiction substate (judge fires ≥0.7 → r/e/o).

### I7. "Lazy connect — no connection until the first execute"
- `05_data_plumbing.md:101`: accurate in spirit, but `adapter.py` BaseAdapter is a
  Protocol; "lazy connect" is a per-adapter property. Fine for the level, but the
  phrase "the package imports cleanly with no driver installed" is the stronger,
  verifiable claim (lazy *import*), which the curriculum also states — keep that one.

### I8. "EXPLAIN is allowed (it parses as a `Command`)"
- `05_data_plumbing.md:60`: correct, but note Layer 3c *rejects* a non-EXPLAIN
  `Command` (`safety.py:386-388`). The curriculum says this at `:78` ("A non-EXPLAIN
  Command is also rejected") — consistent, just verify the two statements aren't read
  as contradictory by a student. No fix required; flagged for clarity.

### I9. "the analyzer … picks which function applies and reports the number"
- `03_deterministic_core.md:46,67`: accurate framing, but the dispatch is the
  orchestrator running the stats and handing the analyzer a dict
  (`monitor.system.md:22` shows this pattern for SRM: "the orchestrator runs it and
  hands you the dict"). The agent does not call Python directly. Minor; tighten to
  "the agent selects; the orchestrator executes the whitelisted function."

---

## Unverifiable or fragile labs

- **Lab 6a / 6c (`06_state_stores_resume.md`)** — would NOT behave as claimed.
  `agentxp resume` prints a case classification and returns an exit code; it does not
  reconstruct or continue (W6, `resume.py:281-292`). A student running these labs will
  see "resume case N: <message>" and no pipeline continuation. Rewrite to: run
  `agentxp resume`, observe the case + message, then point at
  `tests/smoke/test_resume_reconstruct_from_log.py` for the actual rebuild.
- **Lab 1 / Lab 3b / capstone demo** — "drive `ship_demo.csv` Stage 0→8 to SHIP" via
  `/experiment`. The fixture and the E2E test exist (`tests/smoke/test_e2e_ship_demo.py`,
  `sample-data/ship_demo.csv`), so the *test* is real. But the live narration script
  (`08_capstone.md:37`: "0 profile → 1 design → 2 pre-register → 3 power → 3b → 4
  collect → 5 analyze → 6 monitor → 7 interpret → 8 readout") names the wrong stages
  in the wrong order (W2/W4). A student narrating from this script will mis-name every
  stage from 0.5 onward. Fix the narration marks to the real `STAGES.md` order.
- **Lab 2a/2c** — reference `agents/interpreter.system.md` and "designer/editor.system.md"
  (`02_agents.md:153`). `designer/editor.system.md` exists (good), interpreter file
  exists (good). These labs are sound; only the surrounding roster names (architect/
  namer) are wrong.
- **All Module 4 labs (4a–4e)** — verified sound: `validate_chain` FAILED footer
  `FAILED — {description}` (`cli/audit.py:261`), `ArtifactLocked` message
  (`store.py:837-845`), gate-pairing violations (`chain.py:298-327`), chmod-600
  `PermissionError: Refusing to write … mode drifted to 0o644, expected 0o600.`
  (`audit/storage.py:90-93`), `canonical_chain_hash(exp_dir)` (`audit/storage.py:134`).
  Cited test files all exist.
- **All Module 5 labs (5a–5d)** — verified sound: `ReadOnlyViolation: Write / DDL
  operation not permitted: Drop` (`safety.py:158-160`), `DenyListViolation: Function
  'PG_SLEEP' is on the §11 deny-list` (`safety.py:394-396`), Layer 4 LIMIT injection
  (`safety.py:412-`, `_ROW_LIMIT_BY_PURPOSE` preview=1000 at `:80`),
  `_redact_creds_for_log` (`adapter.py:129`), `redact` URL creds (`redactor.py:52,80`).
  Cited tests exist.

---

## Gauntlet weak spots (Module 8)

- **Q4 ("walk me through `/experiment` → verdict; where does Claude stop and Python
  start")** — the expected answer rests on the Module 1 stage map, which is wrong
  (W2/W4). A student answering from the curriculum will mis-state the stage order
  (esp. Analyze-before-Monitor) and get caught by any reviewer who has read STAGES.md.
- **Q9 ("SRM check halts the whole experiment … why step 1?")** — the curriculum's
  answer is correct *for the tree* (INVALID-SRM is `tree.py:237` step 1), but note the
  SRM *check* physically runs at Stage 5 (monitor) before analyze (Stage 6); the
  "step 1" framing is about the verdict tree, not pipeline order. A sharp reviewer
  will probe "you said SRM is step 1 but you run analysis first?" — the honest answer
  is: SRM is gathered at Stage 5 and is the *first* tree step at Stage 7. The
  curriculum never reconciles these because it has Analyze at Stage 5.
- **Q11 ("is this a blockchain?")** — strong. `parent_action_id` ID-linkage vs.
  `canonical_chain_hash` replay anchor is exactly right (`chain.py:181-245`,
  `audit/storage.py:134`; audit CLI does not call the hash, `cli/audit.py` has no
  `canonical_chain_hash` call). No weakness.
- **Q12 ("crash mid-experiment")** — strong. validate→append→advance and the
  log-ahead-of-state invariant match `store.py:655-797` exactly. But the follow-on
  "how do I recover?" should NOT claim `agentxp resume` auto-recovers (W6).
- **Q17 ("you kept a module nothing calls — `amendments/`")** — strong.
  `amendments_decision: KEEP` / "audit overruled old task #68; amendments/ is the G9
  re-confirm vehicle" verbatim at `REMEDIATION_PLAN.yaml:17`. No weakness.

---

## Confirmed-correct highlights (do NOT "fix" these)

- **Module 3 constants**: `MDE_HALF_FRACTION=0.5` (`tree.py:45`),
  `NOLIFT_CI_WIDTH_MULTIPLIER=2.0` (`:50`), `NOVELTY_LATE_RATIO_FLOOR=0.7` (`:55`),
  `compute_late_ratio` at `tree.py:186` — all correct. `walk_tree(TreeInput)->TreeResult`
  pure function, first-firing-step-terminates — correct (`:223-435`).
- **Confidence labels = 7**: `ConfidenceLabel` literal has exactly 7 values
  (`confidence.py:16-24`); `map_confidence(...)` signature correct (`:72`).
- **Stats whitelist functions**: `welch_test, proportion_test, ratio_metric_test,
  srm_check, power_proportion, adjust_pvalues, msprt_test` all in `__all__`
  (`stats/__init__.py`).
- **Module 4 chain**: `validate_chain(experiment_id, *, from_event=0, to_event=None,
  perf_budget_ms=200, _root=None)` returns `ChainValidation`, raises only
  `PerfBudgetExceeded` at 2× budget (default 400ms) — exact (`chain.py:80-139`). The 5
  invariants and their reject conditions match (`chain.py:181-442`). 13-event enum,
  closure-tested `len(EventName)==13` (`events.py:8,25-47`). UTC `ValueError` on naive
  timestamps (`events.py:122-123`). `_write_artifact` / `ArtifactLocked` / `amend=True`
  reserved seam — exact (`store.py:801-849`). `query.executed` hashes
  `row_count|bytes_scanned` (`dispatch.py:229-230`). `QueryResultSummary` "never raw
  warehouse rows" (`schema.py:330`).
- **Module 5 layers**: "4 numbered layers, Layer 3 split 3a/b/c", `layers_passed=[1,2,3,4]`
  (`safety.py:483-502`), `_WRITE_NODES` set exact (`safety.py:137-146`),
  `_ROW_LIMIT_BY_PURPOSE` values exact (`safety.py:78-84`), `DENY_FUNCTIONS` superset
  correct (`parser.py:78-95`), `_SENSITIVE_KEYS` single canonical set + drift comment
  (`adapter.py:88-126`), dispatch redaction chokepoint with `from None` re-raise
  (`dispatch.py:497-508`), connect_common `os.open(...,0o600)` + 0o700 parent + `getpass`
  + stderr + `env:VAR_NAME` default (`connect_common.py:318-336,114,188`). Module 5 is
  the strongest module in the course.
- **Module 6 stores**: `OrchestratorStore` root `experiments/{exp_id}` (`store.py:322`),
  `ExperimentStore` root `~/.agentxp/experiments` (`storage/store.py:43`),
  `reconstruct_from_log()` at `store.py:570`, `_detect_case` 8 cases (`resume.py:103-249`),
  `_commit_stage` validate→append→advance ordering (`store.py:734-797`) — all correct.
  Only the *resume-auto-recovers* overclaim is wrong (W6).
- **Module 7**: green-but-broken verdict quote verbatim (`SYSTEM_AUDIT.md:12`), gap
  register G1–G16 with G3/G4/G9 CRITICAL (`SYSTEM_AUDIT.md:153-172`), "forest of orphans"
  (`:51`), monkeypatch/fabricated-log §4.2 (`:60`), "~2,516 LOC", "336 KB",
  Invariants 4/5 read `event["stage"]` on `extra="forbid"` gate payloads (`:52`),
  `replay_decision: full-fix-now` + `amendments_decision: KEEP` (`REMEDIATION_PLAN.yaml:16-17`),
  Wave 3 "34 files, +108/−3127" (real commit `cb27c87`), the three rescued modules
  (prep.py/transpiler.py/lifecycle.py, `REMEDIATION_PLAN.yaml:178,191,210-212`),
  necessity criterion + "exported ≠ reachable" (`OVER_ENGINEERING_REVIEW.md:18,27`),
  report.py-imports-tree.py W2.3 (`:73`), 1277/63 baseline (`BUILD_STATUS.yaml:15`) —
  all correct. Module 7 is essentially flawless.
