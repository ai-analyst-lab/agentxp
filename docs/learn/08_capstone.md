# Module 8 — Release readiness (capstone)

> **Goal:** Prove you can ship it and defend it. This module has no new material —
> it's the gauntlet. You run a clean end-to-end demo from memory, then survive a
> hostile-reviewer interrogation that pulls from every prior module. When you pass
> this, you own the system.

---

## Why (the design reasoning)

A public release is a promise you have to defend in real time, usually to someone
who *wants* to find the hole. The skill this module certifies isn't knowledge —
you already have that from Modules 0–7. It's **retrieval under pressure**: can you,
without notes and without stalling, produce the right answer the moment a skeptic
pokes the exact spot where the system made a non-obvious choice?

The structure mirrors how a real launch goes: first you *show* the thing working
(the demo), then you *defend* every decision behind it (the gauntlet). If you can
do both, you're ready. If a defense wobbles, the wobble tells you exactly which
module to re-read.

---

## Part 1 — The demo (do this live, from memory)

Open Claude Code in the repo and drive `ship_demo.csv` from Stage 0 to a SHIP
verdict, narrating as you go. You are not allowed to read the earlier modules
during this — narrate from memory.

```
> /experiment --data sample-data/ship_demo.csv
```

As you drive, hit these marks out loud:

1. **Name each stage as you enter it** (0 profile → 0.5 semantic models → 0.75
   metrics → 1 intent → 2 hypothesis → 3 brief/pre-register [3b if the consistency
   judge fires] → 4 data plan → 5 monitor/SRM → 6 analyze → 7 interpret → 8
   readout), its owner agent, and the artifact about to commit. (Module 1)
2. **At Stage 3, say "this is the lock"** — the brief (`experiment.yaml`) is now
   write-once; the integrity wall will refuse to overwrite it. (Modules 1, 4)
3. **At Stage 7, say what the interpreter cannot see** — your hypothesis prose,
   your hopes, `state.yaml` — and why that's why you can trust the verdict.
   (Modules 2, 3)
4. **Predict the verdict and the tree step before it renders** (+22.3%, clean
   guardrails, lift above MDE/2, `late_ratio` ≥ 0.7 → SHIP at step 7). (Module 3)

Then inspect the receipts and narrate them:

```bash
$ agentxp audit <exp_id>        # walk the timeline; point at chain integrity: OK
```

5. **Point at one `stage.committed` event** and explain the
   validate→append→advance ordering that produced it, and the crash it survives.
   (Module 6)
6. **Run the replay claim aloud** — "anyone can re-derive this verdict from the
   logged inputs and the deterministic tree; the claim isn't trust me, it's replay
   me." (Modules 0, 4)

A clean demo is necessary but not sufficient. The gauntlet is where readiness is
actually decided.

---

## Part 2 — The hostile-reviewer gauntlet

Answer each out loud, cold. After each question is the module that holds the
answer (for when you wobble) — but in a real defense you won't get the hint.

### On the thesis and market (Module 0)
1. *"This is just statsmodels with a chatbot on top. Why not Eppo — hosted,
   battle-tested?"*
2. *"If an LLM makes the call, how is that more trustworthy than me making it?
   You've added a black box."*
3. *"Pre-registration and audit logs are process theater. Disciplined teams do
   this already; undisciplined teams override everything. What does the tool change?"*

### On the architecture (Modules 1–2)
4. *"Walk me through what happens between me typing `/experiment` and getting a
   verdict. Where does Claude stop and Python start?"*
5. *"Your interpreter is an LLM. Prove to me it can't be talked into the verdict I
   want."* (Expected: the isolation axiom — its bundle doesn't contain your intent;
   show it in `bundle.py`.)
6. *"Why split design into three agents? Sounds like over-engineering."*

### On the deterministic core (Module 3)
7. *"Why is the verdict a hard-coded tree instead of letting the model reason?
   Isn't that less intelligent?"* (Expected: recoverable vs unrecoverable error;
   replayability.)
8. Hand them a novel analyzer output. *"What's the verdict and which step fires?"*
   Walk the tree cold.
9. *"Your SRM check halts the whole experiment. Isn't that brittle? Why not flag
   and continue?"* (Expected: a broken split poisons every downstream number —
   step 1 for a reason.)

### On trust (Modules 4, 6)
10. *"You call it tamper-evident. Show me. What stops me editing a logged number?"*
    (Then actually break Invariant 1 in front of them and show the refusal.)
11. *"Is this a blockchain?"* (Expected: no — `parent_action_id` ID-linkage, not
    parent-content hashing; the replay hash is a separate determinism anchor.)
12. *"What happens if it crashes mid-experiment? Do I lose the run or — worse —
    get a wrong answer that looks right?"* (Expected: append-then-advance →
    log-ahead-of-state is recoverable, the lying state can't arise from a crash.)
13. *"Your own audit said the integrity spine was 'green-but-broken.' Why should I
    believe it's fixed now and not just green again?"* (Expected: the monkeypatch
    was deleted; tests now exercise real emitters; the E2E runs `validate_chain`
    ON. Module 7.)

### On the data boundary (Module 5)
14. *"An LLM is writing SQL against my production warehouse. Talk me down."*
    (Expected: the fail-closed layer pipeline; the agent proposes, Python disposes;
    DuckDB demo of a `DROP`/`pg_sleep` rejection.)
15. *"Show me you won't print my Snowflake password in a stack trace."* (Expected:
    the two redaction layers + the dispatch chokepoint; demo `_redact_creds_for_log`.)

### On scope and judgment (Module 7)
16. *"What doesn't this do, and why is each non-feature a strength?"* (Randomized
    A/B only; no causal inference; headless loop stubbed; three adapters
    `live_unverified`.)
17. *"You kept a module nothing calls (`amendments/`). That's dead code you were
    scared to delete."* (Expected: the reachability-from-a-near-need judgment;
    `amendments_decision: KEEP`.)
18. *"How do I know the warehouse adapters work if you never ran them on real
    credentials?"* (Expected: the honest `live_unverified` framing — mock-tested,
    Tier-B authored and skipping, named as a boundary not hidden.)

If any answer takes more than a beat or comes out fuzzy, that's your signal: the
question number maps to a module — go re-read it, then come back and re-run the
gauntlet from the top.

---

## The release-readiness checklist

You are ready to release when all of these are true and you can demonstrate each:

- [ ] **Demo:** drive `ship_demo.csv` 0→8 to SHIP from memory, narrating stage,
      agent, artifact, gate at each step.
- [ ] **Thesis:** state it in one sentence; survive the three market objections.
- [ ] **Isolation:** explain what the interpreter can't see and *show* it in the
      bundle code.
- [ ] **Tree:** walk all 8 steps cold on a novel input; name verdict + step +
      confidence.
- [ ] **Integrity:** break an invariant live and read the refusal; correctly deny
      "it's a blockchain."
- [ ] **Crash safety:** explain validate→append→advance and what crash it
      survives.
- [ ] **SQL safety:** reject a `DROP` and a `pg_sleep` live; name every layer.
- [ ] **Redaction:** prove a secret can't reach a log.
- [ ] **Scope honesty:** name three deliberate non-features and defend each.
- [ ] **Build judgment:** defend one keep-vs-cut call from the remediation.

When every box is checked and the gauntlet holds under pressure, the system is
yours to ship. Update the progress tracker in `README.md`, and you're done.

---

## Where to go after v0.1

The honest boundaries you defended in question 16 are the roadmap:

- **Phase 5 — the headless spine.** Wire `_invoke_llm`/`advance()`/`dispatch_sql`
  so the pipeline can run without a human in the Claude Code loop. (The stubs are
  already shaped for it.)
- **The unified store + chained amendments (G14).** Resolve the two-store split so
  post-lock amendments can chain into the orchestrator log without breaking
  Invariant 1.
- **Live-credential verification** of the three `live_unverified` adapters.
- **Causal inference** (the sibling toolkit) for the questions that aren't
  randomized A/B.

Each of those is a future module of this curriculum, written when you reach it —
the same four-beat shape, tailored to where the code actually is then.

Two things to do *now*, while the system is fresh. First, run the
[one-number trace](trace.md): follow a single value — the treatment conversion
count in `ship_demo.csv` — from a raw CSV cell to the chain hash, across every
stage. Defending each subsystem is necessary; narrating one number through all of
them is what proves you hold the whole path at once. Second, go to **Module 9 —
Extend it**: stop defending the system someone else's decisions built and *change*
it (add an adapter, a verdict, a stage) while predicting, in advance, which
guardrail catches you if you're wrong. Defend, then extend — that's the full
ownership the release demands.
