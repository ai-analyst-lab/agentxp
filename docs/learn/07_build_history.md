# Module 7 — Build history & judgment

> **Goal:** Learn the engineering judgment this codebase teaches — *what to build
> and what to leave alone*. By the end you can reconstruct why
> a specific keep-vs-cut call was made, defend three modules that were rescued from
> deletion, and explain why the most rigorous-looking subsystem was the most
> broken.

---

## Why (the design reasoning)

Every other module taught you *what the system is*. This one teaches you *how the
judgment that built it actually worked* — including where it was wrong and got
corrected. This matters for a public release more than any feature: the questions
that sink a launch are "why did you build *that* and not *this*?" and "how do you
know it works?" The answers live in four documents, and they are unusually honest
ones.

The headline you must internalize comes from `SYSTEM_AUDIT.md`'s verdict:

> *"The design is genuinely agentic and genuinely good; the integrity spine that
> the product sells as its differentiator is green-but-broken; and roughly a fifth
> of the surface is dead or duplicate."*

"Green-but-broken" is the lesson of this module. The tests passed; the thing the
tests were protecting did not work. We'll trace exactly how that happened.

---

## Walkthrough — the four documents

### 1. `SYSTEM_AUDIT.md` — what was wrong (dated 2026-05-29)

The audit measured the *actual code* against the 38 user journeys, via six blind
parallel read-only audits, every claim grep-confirmed to file:line. It scored
**16 of 38 journeys genuinely supported** and produced a **gap register (§11)** of
G1–G16 (G15/G16 were found *during* the audit). The CRITICALs are bold: **G3, G4,
G9.** The gist:

| Gap | One-line | Severity |
|---|---|---|
| G1 | Headless spine stubbed — *by design*, Phase 5 | Med |
| G2 | E2E Stage 0→8 never run on seed data | High |
| **G3** | Log not replay-reproducible (uuid4 ids, wall-clock ts) | **CRITICAL** |
| **G4** | `validate_chain` broken 3 ways — would halt real commits | **CRITICAL** |
| G5 | Verdict enum split 3 ways (`report.py` outlier) | High |
| G6 | ~2,516 LOC dead code | Med |
| G7 | Root doc sprawl (336 KB) | Low |
| G8 | Snowflake / state-model duplication | Med |
| **G9** | Integrity wall (refuse loosen-after-results) absent in code+prompts | **CRITICAL** |
| G10 | `_write_artifact` unguarded — locked brief silently rewritable | High |
| G11 | Crash window in `_commit_stage` (state advanced before log append) | High |
| G12 | Resume-from-log absent | High |
| G13 | Peeking/sequential built but unwired | Med |
| G14 | Post-lock amendment flow built but unwired | Med |
| G15 | Unredacted leak on untyped dispatch exception (New) | Med |
| G16 | Flagship chain tests monkeypatch the validator (New) | High |

The two passages worth quoting cold:

- **The broken validator (§4.1):** Invariant 1 flagged *every* event after the
  first because the emitter always passed `parent_action_id=None` — "a forest of
  orphans." Invariants 4/5 read an `event["stage"]` field that gate payloads
  (`extra="forbid"`) don't carry. Invariant 3(b) hashed `decisions/*.yaml` that
  *nothing writes*. A checker coupled to dead code, that couldn't fire.
- **The cheating tests (§4.2):** the flagship tests "monkeypatch `validate_chain`
  to a stub" and asserted on "a hand-fabricated log shape that the real emitters
  cannot produce… the single most dangerous category of green test, on the single
  most important module." *That's* how green-but-broken happens: the test proved
  the spec's intent, not the code's behavior.

### 2. `REMEDIATION_PLAN.yaml` — what got fixed, in what order

Two top-level decisions you should quote:

- `replay_decision: full-fix-now` — they chose to fully fix replay determinism (G3)
  now, not defer it.
- `amendments_decision: KEEP` — *"audit overruled old task #68; amendments/ is the
  G9 re-confirm vehicle."* An earlier task wanted `amendments/` deleted; the audit
  reversed that because it's the right shape for the missing re-confirm path.

Four waves, sequential, grouped commits, diff review at each boundary:

- **Wave 1 — credibility spine.** *"Nothing else matters until this holds."* Fix the
  three validator invariants, **delete the monkeypatch** (W1.4 — "the test that
  should have caught W1.1–1.3"), guard `_write_artifact` (W1.5), make the editor
  refuse post-lock loosening and route legitimate change "through the amendments/
  flow with an explicit, logged, attributed override — never a silent edit" (W1.6).
- **Wave 2 — trust correctness.** Deterministic ids + recorded timestamps +
  order-stable `result_hash`; close the crash window with **append-then-advance**;
  reconcile the Verdict enum (`report.py` imports `tree.py`); wrap `dispatch_sql` in
  a final redacted except.
- **Wave 3 — cleanup.** Subtract dead/duplicate code — *"keeping amendments/ and
  sequential/."* (The real commit: 34 files, +108 / −3127.)
- **Wave 4 — demonstrate.** Real Stage 0→8 E2E with `validate_chain` ON, and
  resume-from-log.

### 3. `OVER_ENGINEERING_REVIEW.md` — what was deliberately NOT built

The reframe that makes this codebase legible:

> *"It isn't mostly over-engineered; it's mis-sequenced — periphery before spine.
> We built the body before the nervous system… a lot of organs exist that nothing
> yet drives."*

The judgment rule — **the necessity criterion** — is the thing to carry into your
own work:

> *"Necessity is not an abstract property; it's reachability from a real entry
> point."*

The three entry points: the `/experiment` 11-stage workflow, the seven README CLI
commands, and the stats the agent prompts actually name. Everything is sorted into
four buckets: **LOAD-BEARING** (reachable → keep), **SCAFFOLDING** (unwired but
tracked + current → keep, label honestly), **SPECULATIVE** (distant roadmap →
defer behind a flag), **DEAD** (zero non-test callers → delete). The refinement
that catches the subtle cases:

> *"'exported / importable / has a test' ≠ 'reachable in a run.'"*

And the most self-aware passage in the whole repo — the "honest note on our own
recent effort": two prior sessions had *hardened* `sequential.py`, a roadmap-v1.0
module called by nothing in the live workflow. *"We did careful work on an organ
the body doesn't yet use. That is precisely the pattern this review exists to
surface."* The review even catches its own earlier error (it had wrongly called
`report.py` the canonical Verdict enum) and marks it RESOLVED. Judgment under
revision, shown working.

### 4. `BUILD_STATUS.yaml` — where it stands now

`build_state: COMPLETE — all waves done.` Final baseline: **1277 pass / 63 skip /
0 fail.** The skip count is honest: the three warehouse adapters (Snowflake,
BigQuery, Databricks) ship `live_unverified` — *"code_complete AND requires live
creds to fully verify"* — because there are no credentials in the build
environment. The explicit `excluded:` list names the deferrals: **Phase 5 headless
`_invoke_llm` wiring**, v0.1.2 operational stores, v0.2 hooks, v0.5 OTel. And
`deferred_to_shane:` flags the SnowflakeLoader-vs-Adapter reconcile and live-cred
verification.

---

## The judgment lessons (the heart of the module)

Three keep-vs-cut calls, each a different shape of judgment:

1. **`amendments/` was KEPT though it looked dead.** It had zero live callers and
   the over-engineering review even listed it for deletion — yet the audit marked
   it `KEEP` because it's the correct shape for the imminent, journey-anchored G9
   re-confirm path. *Deletability isn't about current callers; it's about whether
   the code is the right shape for a near, real need.*
2. **Three "dead" modules were rescued at edit-time.** `stats/prep.py` (it's in
   `__all__`, referenced by `errors/codes.py`), `sql/transpiler.py` (used by
   `test_adapter_matrix.py`), and `storage/lifecycle.py` (*"the plan premise was
   WRONG"* — it's a live 11-state *status* DAG, distinct from the orchestrator's
   Stage enum, imported by three live modules). *The verify-then-delete step caught
   false positives that grep alone produced.*
3. **The headless loop was KEPT stubbed.** `_invoke_llm`/`advance`/`dispatch_sql`
   raise `NotImplementedError` *on purpose* — a tracked Phase 5 exclusion in
   `BUILD_STATUS.yaml`. SCAFFOLDING, labeled honestly, not a bug.

Contrast 1 and 3: amendments (kept though unwired) and the headless loop (kept
though stubbed) are the *same* judgment applied to two cases — keep code that is
the correct shape for a tracked, near need; don't delete it just because nothing
calls it yet. Contrast that with the genuinely DEAD code that *was* deleted in
Wave 3 (e.g., `data/snowflake_loader.py`, a test-only parallel to the real
adapter). The line between "keep unwired" and "delete dead" is *reachability from a
tracked roadmap need*, not *has a caller today*.

---

## Lab / defend-it (this module's exercise is argument, not code)

**Exercise A — "Why was `amendments/` kept but the headless loop stubbed?"** Write
the answer. Win condition: you cite `amendments_decision: KEEP` (the G9 re-confirm
vehicle, overruling task #68) *and* the Phase 5 `excluded:` entry, and you explain
that both are the same reachability judgment applied to a near need vs a tracked
future phase.

**Exercise B — "Three modules the audit called dead were NOT deleted. Defend each
rescue."** Reconstruct the W3.2/3.3/3.4 reversals. Win condition: you distinguish
*audit claim* from *edit-time verification*, and you can state the rule `"has a
test" ≠ "reachable"` AND its converse — a grep-confirmed "dead" call can be wrong
if the verifier missed `__all__` re-exports, integration tests, or a
conceptually-distinct sibling.

**Exercise C — "The most rigorous-looking subsystem was the most broken. Why, and
what does it teach about green tests?"** Connect §C + §4.1/§4.2: `validate_chain`
read as the most rigorous module (5 invariants, perf budget, rollback) but couldn't
return `ok=True` on a real log, and shipped green only because the tests
monkeypatched the validator and asserted on a fabricated log. Win condition: you
explain why W1.4 (delete the monkeypatch) was the test "that should have caught
W1.1–1.3," and why the fix order was validator-then-untest.

---

## Teach-back checkpoint

You pass Module 7 when you can, without notes:

1. **Explain "green-but-broken"** using `validate_chain` as the worked example —
   the three broken invariants *and* the monkeypatched tests that hid it.
2. **State the necessity criterion** (reachability from a real entry point), name
   the four disposition buckets, and the `"exported ≠ reachable"` refinement.
3. **Defend two keep-vs-cut calls** — `amendments/` KEEP and the headless-loop
   stub — as one consistent judgment, and contrast them with code that was
   correctly deleted.
4. **Name the current honest boundaries**: the `live_unverified` adapters, the
   Phase 5 exclusion, and what `deferred_to_shane` still holds.

I'll play the hostile reviewer: "you kept a module nothing calls — that's
dead code you were too scared to delete." Defend it with the documented rationale.
When your defense holds, check the box and we go to the capstone.
