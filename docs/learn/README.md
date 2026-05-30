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

All nine modules (0–8) are written and live next to this file as `NN_slug.md`.
This README is the durable map; work the modules in order. Modules beyond v0.1
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
| 3 | **The deterministic core** | How is the verdict computed? | Predict verdicts for 4 fixtures, check against the 8-step tree | Walk the tree cold on a novel analyzer output |
| 4 | **The integrity spine** | Why is it trustworthy? | Break-it: rewrite a locked brief / corrupt the chain | Explain all chain invariants + the locked-rule wall |
| 5 | **Data plumbing** | How does it touch a warehouse safely? | Trace a query through all 5 SQL-safety layers | Explain what each layer rejects + the redaction bar |
| 6 | **State, stores & resume** | How does it survive a crash? | Interrupt a run, resume from the log | Explain the two store layers + `_commit_stage` chokepoint |
| 7 | **Build history & judgment** | How was it built? What got cut, and why? | Defend a keep-vs-cut call from the audit | Reconstruct why amendments/ was KEPT, lifecycle wasn't deleted |
| 8 | **Release readiness (capstone)** | Can you ship and defend it? | Demo Stage 0→8 to me + survive the skeptic drill | Pass the full hostile-reviewer gauntlet |

---

## Fixture cheat-sheet (your lab inventory)

The 8 CSVs in `sample-data/` are each a deliberate verdict path. Nothing in the
codebase depends on them — they exist *only* to practice on. You will use these
constantly from Module 1 onward.

| Fixture | Scenario | Lands on | Teaches |
|---------|----------|----------|---------|
| `clean_ab.csv` | Standard positive A/B | **SHIP** | The happy path |
| `ship_demo.csv` | LL demo, n=3k/grp, +22.3% conv | **SHIP** | Full 0→8; the E2E anchor |
| `checkout_redesign.csv` | Positive proportion, flat revenue | **SHIP** | How metric *type* affects power |
| `no_effect.csv` | Null, adequately powered | **LEARN (powered)** | A real null is a finding, not a failure |
| `underpowered.csv` | Null, n=500/grp too small | **LEARN (underpowered)** | Power & MDE |
| `srm_violation.csv` | Broken randomization 52/48 | **INVALID-SRM** | Why a halt beats a flag |
| `guardrail_violation.csv` | Primary flat, latency +16% | **NO-SHIP-GUARDRAIL** | The rule beats the number |
| `mixed_results.csv` | Simpson's paradox, segment reversal | **caveat / investigate** | Why averages lie |

A good drill at any point: read the fixture name, predict the verdict and the
*step that fires*, then run it and check yourself.

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

---

## Source-of-truth docs (where the "why" lives)

When a module cites reasoning, it traces to one of these. You should end the
curriculum having read all of them:

- `docs/USER_JOURNEYS.md` — the 30+ journeys the product must serve; the gap
  register (G1–G14); the discipline-defense interrogation scripts (J3.5.6–9).
- `SYSTEM_AUDIT.md` — the deep audit that found what was wrong before release.
- `REMEDIATION_PLAN.yaml` — the four-wave fix plan; every keep-vs-cut decision.
- `OVER_ENGINEERING_REVIEW.md` — what was deliberately *not* built, and why.
- `BUILD_STATUS.yaml` — current build state, what ships `live_unverified`.
- `.claude/skills/experiment/SKILL.md` + `STAGES.md` — the orchestrator spec.
- `experimentation-platform/OPENXP_V01_PLAN.md` (in the monorepo) — the locked
  plan: §3 journey, §5 agents, §10 orchestrator API, §22 interpreter tree.
