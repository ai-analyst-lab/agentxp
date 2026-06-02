# Learn AgentXP — an expert curriculum

A guided path from "I built this" to "I can demo it, defend every design
decision under hostile questioning, and extend the code." Built for the moment
before a public release, where you need to *own* the system, not just have
shipped it.

**Depth target:** defend + extend. By the end you can (a) answer any reviewer
question about why the system is the way it is, and (b) add an adapter, add a
verdict step, or change a stage without breaking the integrity spine.

**Primary mode:** hands-on + break-it. You learn by driving real runs and by
deliberately trying to break invariants and watching the system refuse. Reading
is the scaffold; doing is the lesson.

---

## How to use this

Work the modules in order. Each one has the same four-beat shape:

1. **Why** — the design reasoning (problem → constraint → choice), sourced from
   the real `PLAN`, `SYSTEM_AUDIT`, `USER_JOURNEYS`, and `OVER_ENGINEERING_REVIEW`
   docs. You learn *why it was built this way*, not just what it does.
2. **Walkthrough** — we open the actual files and trace the load-bearing pieces.
3. **Lab / break-it** — you run something, or you try to break something and
   watch the guardrail catch you. This is where it sticks.
4. **Teach-back checkpoint** — you explain the subsystem back, in your own words,
   as if to a student. If you can't, the module isn't done. Explaining is the
   test, and it's the exact skill a public release demands.

All eleven modules (0–10) are written and live next to this file as `NN_slug.md`.
Modules 0–9 teach the *analysis* spine (CSV → verdict → integrity chain); Module 10
teaches the *presentation / share-out* spine (`report.json` → renderers). This
README is the durable map; work the modules in order. Modules beyond v0.1
(Phase 5 spine, chained amendments, live-cred verification, causal inference) get
written in the same four-beat shape when the code reaches them — see Module 8's
"Where to go after v0.1."

### Prerequisites (do this once)

```bash
$ cd ~/projects/agentxp
$ python -m venv .venv && source .venv/bin/activate   # if not already
$ pip install -e .
$ agentxp --version          # expect: agentxp 0.1.0
$ .venv/bin/python -m pytest -q   # expect: ~1240 passed, ~63 skipped
```

The skips are credential-gated warehouse tests — that is correct and expected;
see Module 5. If the pass count is green, your environment is sound.

---

## The two surfaces (read this before Module 1)

AgentXP v0.1 has **two** places things run, and conflating them is the most
common confusion:

- **The shell CLI** (`agentxp …`) — setup and inspection only: `profile`,
  `connect`, `list`, `resume`, `unlock`, `audit`, `experiment`. These run in your
  terminal (`$`).
- **The experiment pipeline** — the eleven-stage analysis itself runs *inside a
  Claude Code conversation*, started with the `/experiment` slash command. You
  talk to Claude through the stages (`>`). **Claude is the orchestrator.** The
  headless Python orchestration loop is deliberately stubbed in v0.1 (Phase 5);
  Module 6 covers why, and why that's an honest boundary rather than a bug.

So "run an experiment" means: open Claude Code in the repo, type
`/experiment --data sample-data/<file>.csv`, and converse. "Inspect an
experiment" means: `agentxp audit <exp_id>` in the shell.

---

## The module map

| # | Module | Core question | Signature exercise | Mastery checkpoint |
|---|--------|---------------|--------------------|--------------------|
| 0 | **Thesis & market** | Why does this exist? Why now? | FAQ skeptic drill: "why not Eppo/StatSig/GrowthBook?" | Defend the one-sentence thesis against three objections |
| 1 | **The shape: 11 stages** | What happens end-to-end? | Drive `ship_demo.csv` Stage 0→8 to SHIP | Name all 11 stages, their agent, and what each commits |
| 2 | **Agents as programs** | How do markdown prompts do work? Why is each sealed off? | Trace the isolation axiom from profiler → interpreter | Explain why the interpreter never sees the hypothesis |
| 3 | **The deterministic core** | How is the verdict computed? | Predict verdicts for all 8 fixtures, check against the 8-step tree | Walk the tree cold on a novel analyzer output |
| 4 | **The integrity spine** | Why is it trustworthy? | Break-it: rewrite a locked brief / corrupt the chain | Explain all chain invariants + the locked-rule wall |
| 5 | **Data plumbing** | How does it touch a warehouse safely? | Trace a query through all 5 SQL-safety layers | Explain what each layer rejects + the redaction bar |
| 6 | **State, stores & resume** | How does it survive a crash? | Interrupt a run, resume from the log | Explain the two store layers + `_commit_stage` chokepoint |
| 7 | **Build history & judgment** | How was it built? What got cut, and why? | Defend a keep-vs-cut call from the audit | Reconstruct why amendments/ was KEPT, lifecycle wasn't deleted |
| 8 | **Release readiness (capstone)** | Can you ship and defend it? | Demo Stage 0→8 to me + survive the skeptic drill | Pass the full hostile-reviewer gauntlet |
| 9 | **Extend it (build-to-break)** | Can you change it without breaking the spine? | Add an adapter, a verdict, and rename a stage — predict the blast radius first | Route any proposed change to the guardrail that catches it (chain vs coherence vs closure) |
| 10 | **The presentation layer** | How does a `report.json` become shareable without losing the proof? | Trace one number to six formats; tamper the chain and watch every format stamp DRAFT; add a `txt` adapter | State the pure-renderer axiom, defend the pure/impure split, extend the layer without re-deriving a number |

---

## The aha index (the nine load-bearing insights)

If you remember nothing else, remember these. Each is the moment a design choice
stops feeling arbitrary and starts feeling inevitable. They're marked inline with
a `> **Aha —**` callout in the module where they land — this index is the map.

| # | The insight | Module | The inversion it teaches |
|---|-------------|--------|--------------------------|
| 1 | You make the judge more trustworthy by giving it *less* context. | 2 | More information ≠ better decision, when the extra information is what you hoped for. |
| 2 | The *order* of the verdict-tree steps is the priority ranking. | 3 | A win you can't trust or can't ship is rejected before the good news is read. |
| 3 | Existence of the file on disk *is* the lock — there's no flag to flip back. | 4 | Integrity comes from there being no quiet door, not from a toggle you promise not to touch. |
| 4 | You can't make a crash atomic, so you point its only failure at the *recoverable* direction. | 6 | Don't eliminate the crash window; order the writes so the survivable partial state is the only one. |
| 5 | A test that stubs the thing it tests always passes and proves nothing. | 7 | Green ≠ correct; "green-but-broken" is a category, not a fluke. |
| 6 | "Is this code necessary?" is the wrong question; "what entry point reaches it?" is the right one. | 7 | Necessity isn't a property of the code — it's reachability you can grep for. |
| 7 | Predict the blast radius, *then* run the suite. | 9 | The gap between your prediction and the red output is the exact shape of a coupling you didn't understand. |
| 8 | A renderer that does arithmetic is a second source of truth in disguise. | 10 | "Be careful with numbers" is a wish; one pure formatter + string-typed view-model fields is a wall. |
| 9 | Polish and proof must arrive in the same object, or polish will outrun proof. | 10 | You don't keep receipts attached by discipline; you bundle them so an adapter *cannot* emit the verdict while dropping the receipt. |

---

## Fixture cheat-sheet (your lab inventory)

The 8 CSVs in `sample-data/` are each a deliberate verdict path. Nothing in the
codebase depends on them — they exist *only* to practice on. You will use these
constantly from Module 1 onward.

The "Lands on" column uses the canonical eight-value `Verdict` enum from
`agentxp/interpret/tree.py` (Module 3). Note: `sample-data/README.md` and the
direction tests in `tests/test_sample_data_verdicts.py` use older informal labels
(`INVALID`, `INVESTIGATE`) that predate the enum — where they differ, the table
flags it, because the divergence is itself a teaching point.

| Fixture | Scenario | Lands on (verdict) | Teaches |
|---------|----------|----------|---------|
| `clean_ab.csv` | Standard positive A/B | **SHIP** | The happy path |
| `ship_demo.csv` | LL demo, n=3k/grp, +22.3% conv | **SHIP** | Full 0→8; the E2E anchor |
| `checkout_redesign.csv` | Positive proportion, flat revenue | **SHIP** (or **LIFT-WITH-CAVEAT** if the lift is below MDE/2) | How metric *type* affects power |
| `no_effect.csv` | Null, adequately powered (n≥5k/grp) | **LEARN** (well-powered null), or **NO-LIFT** if the CI is wider than 2×MDE | A real null is a finding, not a failure |
| `underpowered.csv` | Null, n=500/grp too small | **INCONCLUSIVE** (Step 3: underpowered *and* the 95% CI straddles 0) — *not* the informal "LEARN (underpowered)" | Power & MDE; Step 3 vs Step 8 |
| `srm_violation.csv` | Broken randomization 52/48 | **INVALID-SRM** | Why a halt beats a flag |
| `guardrail_violation.csv` | Primary flat, latency +16% | **NO-SHIP-GUARDRAIL** | The rule beats the number |
| `mixed_results.csv` | Simpson's paradox, segment reversal | the tree walks the **primary** and lands on its verdict; the segment conflict surfaces as a `CONTRADICTORY_SEGMENTS` reason code at readout, not a verdict | Why averages lie |

A few of these are brief-dependent — `no_effect` and `underpowered` hinge on how
the brief sets `n_required` and MDE relative to the observed CI, which is exactly
why Module 3 has you walk Steps 3-8 by hand. A good drill at any point: read the
fixture name, predict the verdict and the *step that fires*, then run it and check
yourself.

---

## Progress tracker

- [ ] Prerequisites green (`agentxp --version` + suite passes)
- [ ] Module 0 — Thesis & market
- [ ] Module 1 — The shape: 11 stages
- [ ] Module 2 — Agents as programs
- [ ] Module 3 — The deterministic core
- [ ] Module 4 — The integrity spine
- [ ] Module 5 — Data plumbing
- [ ] Module 6 — State, stores & resume
- [ ] Module 7 — Build history & judgment
- [ ] Module 8 — Release readiness (capstone)
- [ ] Module 9 — Extend it (build-to-break)
- [ ] Module 10 — The presentation layer (share-out without losing the proof)
- [ ] Appendix — [the one-number trace](trace.md) (read after Module 8)

---

## The one-number trace (read it after Module 8)

[`trace.md`](trace.md) follows a *single value* — the treatment conversion count
in `ship_demo.csv` — from a raw CSV cell through every stage to the chain hash.
The modules teach the subsystems one at a time; the trace proves they're one
system. It's the fastest way to convert "I can defend each part" into "I can
narrate the whole path a number walks." Read it once the capstone demo is in your
hands.

---

## Source-of-truth docs (where the "why" lives)

When a module cites reasoning, it traces to one of these. You should end the
curriculum having read all of them:

- `docs/USER_JOURNEYS.md` — the 30+ journeys the product must serve; an *early*
  gap register (G1–G14, dated 2026-05-29); the discipline-defense interrogation
  scripts (J3.5.6–9).
- `SYSTEM_AUDIT.md` — the deep audit that found what was wrong before release. Its
  §11 "Updated gap register" (G1–G16, with G15/G16 found *during* the audit) is the
  one the curriculum cites — Module 7 especially. **Heads-up:** the two registers
  *renumber* the gaps (e.g. G3 means "invariants 4&5 never fire" in USER_JOURNEYS
  but "log not replay-reproducible" in SYSTEM_AUDIT). When a module says "G3,"
  it means the SYSTEM_AUDIT §11 numbering.
- `REMEDIATION_PLAN.yaml` — the four-wave fix plan; every keep-vs-cut decision.
- `OVER_ENGINEERING_REVIEW.md` — what was deliberately *not* built, and why.
- `BUILD_STATUS.yaml` — current build state, what ships `live_unverified`.
- `.claude/skills/experiment/SKILL.md` + `STAGES.md` — the orchestrator spec.
- `PRESENTATION_LAYER_MASTER_PLAN.md` + `BUILD_STATUS_PRESENTATION.yaml` — the
  multi-persona master plan and the Wave 0–8 build log for the share-out spine
  (Module 10): the pure-renderer axiom, `distill()`/`build_provenance()` split,
  the adapter Protocol, and the format/audience/tier matrix.
- `experimentation-platform/OPENXP_V01_PLAN.md` (in the monorepo) — the locked
  plan: §3 journey, §5 agents, §10 orchestrator API, §22 interpreter tree.
