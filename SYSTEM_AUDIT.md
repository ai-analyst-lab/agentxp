# AgentXP — Full System Audit (journeys as the yardstick)

**Date:** 2026-05-29
**Scope:** Whole package (`agentxp/`, agent prompts, skills, docs) measured against `docs/USER_JOURNEYS.md` (38 journeys, gap register G1–G14).
**Question asked:** How well does the *actual code* serve the user journeys — where does it diverge, where are the gaps/risks, what's over-engineered, what's dead, how much is a genuine agentic system vs. scaffolding vs. slop, how readable/reviewable is it, where is it cheating (tests that don't test), and is the security real or theater?
**Method:** Six blind, read-only, parallel audits — (A) journey-fit, (B) necessity/spec-drift, (C) authenticity/cheating/tests, (D) craft/performance, (E) security/determinism/resilience/supply-chain, (F) the G9 integrity-wall behavioral probe. Every claim below is grep-confirmed to file:line and cross-checked against `BUILD_STATUS.yaml` (the arbiter of scaffolding-vs-speculative) and the live `/experiment` skill.

---

## 1. The one-paragraph verdict

**The design is genuinely agentic and genuinely good; the integrity spine that the product sells as its differentiator is green-but-broken; and roughly a fifth of the surface is dead or duplicate.** AgentXP's headline promise is *"two reviewers replay the append-only log and reach the same answer"* — a credibility claim resting on three things: a chain validator that fires on every commit, a replay-reproducible log, and an integrity wall that refuses to loosen a locked rule after results are seen. **All three are currently not real.** `validate_chain` is broken in three independent ways and would *actively halt* the first real gated commit (it passes CI only because the tests monkeypatch it and feed it a log shape the emitters cannot produce). The log is **not** replay-reproducible (uuid4 ids, wall-clock timestamps, warehouse-dependent hashes). And the "you can't change a locked brief after seeing results" wall — gap **G9**, the single most important trust property — **is absent in both the code and the agent prompts**; the editor prompt explicitly accepts `stage: post_commit`. Against that, the parts that *aren't* the headline are strong: secrets handling and the 5-layer SQL-safety pipeline are real, not theater; the stats are mathematically sound and well-tested; the interaction contract (infer / ask-one / offer-menu, halt-is-never-a-menu) is mostly honored. So the honest framing is: **16 of 38 journeys are genuinely supported today, the agentic skeleton is sound, but the product's central trust claim is unbacked and must be the first thing fixed.**

---

## 2. How "supported" was decided

A journey is **SUPPORTED** only if a real entry point (the `/experiment` SKILL/STAGES walk, a README CLI command, or a deterministic stat an agent prompt actually names) reaches working code that produces the journey's described behavior. "Has a test" or "is importable" is not support — several green tests assert against stubs (see §6). Each journey was placed in one of: **SUPPORTED**, **PARTIAL** (works but diverges from the doc, or works only in the interactive path while the headless path is stubbed), **ABSENT** (specced, not built), **REFUSED-BY-DESIGN** (the journey is a thing the system *should* decline, and does).

---

## 3. Per-dimension scorecard (the 14 tracks)

| # | Dimension | Score | One-line |
|---|---|---|---|
| 1 | Journey fit (does code serve the 38 journeys) | **4/10** | 16 SUPPORTED, 9 PARTIAL, 8 ABSENT, 5 REFUSED-BY-DESIGN; the interactive path carries almost all the wins |
| 2 | Agentic-system realness (dispatch + route on agent output) | **5/10** | Real when *Claude* is the orchestrator; the headless Python spine (`_invoke_llm`/`advance`/`dispatch_sql`) is stubbed by design |
| 3 | Necessity / over-engineering | **6/10** | Not baroque, but breadth-first: ~2,516 LOC dead/duplicate around an empty center |
| 4 | Dead code | **3/10** | 9 confirmed-dead modules; orphaned `experiment-*.md` prompts actively mislead grep-based readers |
| 5 | Code that *should* be used but isn't | **4/10** | sequential/amendments map to real journeys (J2.5.7, J3.5.5) but are unwired |
| 6 | Readability / reviewability (OSS afternoon-read claim) | **3/10** | 336 KB of contradictory root process-docs; core modules themselves read cleanly |
| 7 | Authenticity (real logic vs. plausible-looking slop) | **6/10** | Stats + safety are real; the integrity layer is the slop — it *looks* rigorous and doesn't work |
| 8 | Cheating tests (green that proves nothing) | **2/10** | Flagship chain tests monkeypatch the validator and assert on a fabricated log shape |
| 9 | Security — secrets placement | **9/10** | getpass no-echo, 0o600, env:VAR refs, redactor at every log/exception boundary — genuinely strong |
| 10 | Security — SQL / injection / fail-closed | **8/10** | Positive-AST allowlist, read-only deny, LIMIT cap; one untyped-exception leak path |
| 11 | Determinism / replay-reproducibility | **2/10** | uuid4 ids + wall-clock ts + warehouse-dependent result_hash → the replay claim is false |
| 12 | Resilience (crash/resume/SIGINT/expired creds) | **4/10** | SIGINT-defer works; resume is ABSENT; a hard-crash window exists in `_commit_stage` |
| 13 | Integrity wall (G9 — refuse to loosen locked rule) | **1/10** | Absent in code *and* prompts; editor accepts `post_commit`; locked artifacts are rewritable |
| 14 | Spec/doc drift (SKILL vs code vs docs) | **4/10** | 3-way Verdict split; profiles-vs-credentials dir mismatch; OVER_ENGINEERING_REVIEW §C is itself wrong |

---

## 4. The cross-cutting headline: the credibility spine is unbacked

The product's one differentiator is *auditability*. Four findings, taken together, mean that claim does not currently hold. **Fix these before anything else.**

### 4.1 `validate_chain` is broken three ways and would halt real runs — CRITICAL

`validate_chain` (`audit/chain.py`) runs on **every** `_commit_stage` with a 200/400 ms perf budget and rolls back on failure. It cannot return `ok=True` on any real multi-event log:

- **Invariant 1 (parent linkage)** flags every event after the first, because `_emit` always passes `parent_action_id=None` (the emitter never threads the prior id). chain.py expects a chain; the emitter produces a forest of orphans.
- **Invariants 4 & 5 (gate pairing)** read `event["stage"]` on gate events (`chain.py:271-321`), but `GateOpenedPayload`/`GateResolvedPayload`/`GateBlockedPayload` (`events.py:157-193`) are `extra="forbid"` and carry **no `stage` field**. Gate events can never register under a stage → pairing never validates.
- **Invariant 3(b)** hashes `decisions/*.yaml` files that **nothing writes** (`audit/decisions.py` is dead — zero callers). Vacuously passes today; couples a live checker to dead code, and would break the moment decisions are emitted.

Net: the first real gated commit (any SRM halt, any guardrail resolution) would spuriously `CommitRollback`. The product cannot complete a gated experiment with its own integrity check enabled.
→ Gaps G3, G4. Anchors: J3.1 (SRM halt), J2.1 (full happy path through a gate).

### 4.2 The flagship tests don't test it — CRITICAL (cheating)

The reason §4.1 ships green: `tests/audit/test_chain*.py` **monkeypatch `validate_chain` to a stub** and assert against a **hand-fabricated log shape that the real emitters cannot produce** (events with `stage` on gates, with threaded `parent_action_id`). The perf-budget tests **monkeypatch the clock**. So the suite proves the spec's *intent*, not the code's *behavior* — the single most dangerous category of green test, on the single most important module.
→ This is the root cause that hid §4.1 across two prior review passes.

### 4.3 The log is not replay-reproducible — HIGH

Even with §4.1 fixed, "two reviewers replay and reach the same answer" fails: action ids are `uuid4()`, timestamps are wall-clock, and `result_hash` folds in warehouse-dependent row ordering. A re-run produces a different chain hash. The audit log is *tamper-evident* (append-only + hashed) but **not reproducible** — those are different claims, and the docs assert the stronger one.
→ Gap G3. Anchor: J4.5 (lost run / reconstruct), J5.2 (export readout).

### 4.4 The G9 integrity wall is absent in code AND prompts — CRITICAL

The trust property a skeptic actually tests (J3.5.1, J3.5.4/5): *after results are visible, the system must refuse to loosen a pre-locked rule (guardrail, success criterion, locked brief).* There is **no enforcement anywhere**:

- `agents/designer/editor.system.md:7,20` **explicitly accepts `stage: post_commit`** to "re-open a committed artifact," routed through normal edit machinery gated only by a *visibility* `edit_override` flag — no refusal, no results-seen check.
- `orchestrator/store.py:615` `_write_artifact` does an **unconditional** `_atomic_write_bytes` to any exp-dir path — no "already committed?" guard. A locked brief is silently rewritable.

A determined user can get Claude to rewrite a locked success criterion after seeing the result. This is the exact scenario the journeys hold up as the thing the system must never do.
→ Gaps G9, G14. Anchors: J3.5.1, J3.5.2, J3.5.4, J3.5.5.

---

## 5. Journey-fit detail (Track 1)

**SUPPORTED (16):** J0.1, J0.2, J1.1, J1.3, J2.1 *(interactive path only)*, J2.2, J2.3, J2.5.1, J2.5.2, J2.5.4, J3.2, J3.5.6–3.5.9 *(hold-and-explain "why" paths)*, J5.3.
**PARTIAL (9):** J1.2 (warehouse works; doc says `profiles/`, code uses `credentials/`), J2.5.3/J2.5.5/J2.5.6 (handled in stats but not surfaced as a confirm/menu), J3.1 (SRM detection real, but the halt's commit would roll back per §4.1), J3.4 (expired creds caught, message not as specced), J4.1/J4.2 (list/compare exist; "why" reconstruction leans on §4.3), J5.1/J5.2 (export path thin).
**ABSENT (8):** J3.3 (resume) — specced, not built; J4.3/J4.4/J4.5 (post-hoc "doesn't look right" / raw numbers / lost-run reconstruction) — depend on §4.3; J2.5.7 (peeking) — `stats/sequential.py` exists but unwired; J3.5.4/J3.5.5 (re-confirm on change) — no guard; G9 wall (per §4.4).
**REFUSED-BY-DESIGN (5, working correctly):** J3.5.10 (causal — declined, points to OpenCausalInf), J3.5.11 (junk input — declined), J3.5.1–3 *as halts* (loosen guardrail / force-ship / skip brief should refuse) — **but see §4.4: the refusal is currently only convention, not enforced.**

---

## 6. Necessity, dead code, and duplication (Tracks 3–5)

**Confirmed DEAD — delete (~2,516 LOC, zero non-test callers, grep-confirmed):**

| What | LOC | Evidence |
|---|---|---|
| `audit/decisions.py` (`write_decision`/`Decision`/`next_ordinal`) | 145 | zero callers; inv 3(b) hashes files it never writes |
| `schemas/_versioning.py` (`check_schema_version`) | 213 | zero callers; advertises a `migrate state` cmd that doesn't exist |
| `sql/cache.py` | 199 | docstring claims dispatch calls it; dispatch does not |
| `sql/preview.py` | 55 | only its own test calls it |
| `sql/transpiler.py` `transpile()` | 60 | zero callers (confirmed — W0 edits only its dialect list) |
| `stats/prep.py` (`prepare_experiment_data`) | 180 | only "reference" is an error-code string |
| `data/snowflake_loader.py` | 444 | parallel to the real `sql/adapters/snowflake_adapter.py`; test-only |
| `storage/lifecycle.py` (11-state DAG) | ~250 | parallel state model; live loop uses `Stage` enum in `schemas/state.py` |
| orphaned `agents/experiment-*.md` (5 files) | 765 | stale parallel to the live `agents/*.system.md`; **highest-leverage delete** — names `winsorize`/`cohens_d`/`power_*`/`monitoring/*`, making dead code grep as reachable |

**KEEP-PENDING-DECISION (maps to a real journey — do not delete):**
- `amendments/` (457) → J3.5.5 / G14 (post-lock change-request flow). Unwired, but it's the *right shape* for the missing G9 re-confirm path.
- `stats/sequential.py` (600) → J2.5.7 / G13 (peeking / always-valid). Roadmap; the mSPRT work from prior sessions is sound, just not dispatched.

**Duplication to reconcile:** two Snowflake codebases (above); two state models (above); two `_atomic_write_bytes` (`audit/storage.py:138`, `storage/store.py:59`) and two `_check_disk_space` — collapse to one.

---

## 7. Authenticity: what's real vs. what only looks real (Track 7)

**Real (keep, trust):**
- **SQL safety** (`sql/safety.py` + `parser.py:26-63`): a genuine 5-layer fail-closed pipeline — positive AST allowlist, read-only deny-list, LIMIT cap. Not theater.
- **Secrets** (`cli/connect_common.py`): `getpass(stream=sys.stderr):111`, `os.open` 0o600 + chmod `:312-330`, `env:VAR` default `:167-185`. Genuinely strong.
- **Redactor** (`audit/redactor.py`): idempotent, applied at every SQL exception boundary (`dispatch.py:361/416/451`). Real.
- **Stats** (`welch`, `proportion`, `ratio`, Holm, SRM; `sequential` mSPRT): mathematically correct, well-tested for behavior.

**Looks-real-but-isn't (the slop is concentrated in the integrity layer):**
- `validate_chain` — 5 named invariants, a perf budget, a `PerfBudgetExceeded` rollback class: *reads* as the most rigorous subsystem, *is* the most broken (§4.1).
- The `decisions/*.yaml` integrity coupling (§4.1 inv 3b) — a checker wired to a writer that doesn't exist.

---

## 8. Security & resilience detail (Tracks 9–12)

- **Secrets / SQL: strong** (§7). One real gap: `dispatch_sql` catches only 3 typed exceptions (`dispatch.py`); an *unexpected* exception type bypasses the redactor and can surface a raw driver message. Wrap the dispatch body in a final `except Exception` that routes through `redact_message` before re-raise.
- **Determinism: failing** (§4.3) — uuid4 + wall-clock + warehouse-ordering in `result_hash`.
- **Resilience:**
  - SIGINT during `_commit_stage` is correctly deferred (signal handler holds until the atomic write completes). Good.
  - **Hard-crash window:** `_commit_stage` advances `state.yaml` (~line 552) *before* appending the `stage.committed` event (~599). A crash in that window leaves state ahead of the log → the next `validate_chain` sees a committed stage with no commit event. Reorder: append-then-advance, or make the pair atomic.
  - **Resume (J3.3) is ABSENT** — specced in journeys, no code path reconstructs in-flight state from the log.
- **Supply chain:** dependency set is small and mainstream (scipy/numpy/pydantic/duckdb); no obvious risk. No pinned lockfile committed — note for OSS release.

---

## 9. Reviewability (Track 6) — the OSS "afternoon read" is false today

The README says the repo "can be read end-to-end in an afternoon," but the root carries **~336 KB of process docs** — `TEST_PLAN.md`, `PRD_COVERAGE.md`, `WAVE1/2_REVIEW.md`, `REVIEW_4_FINAL.md`, `REVIEW_FINDINGS.md`, `REVIEW_RUBRIC.md`, `FINAL_STATUS.md`, `DEMO.md`, plus this file and `OVER_ENGINEERING_REVIEW.md` — several mutually contradictory (README "ships in v0.1.1" vs `BUILD_STATUS.yaml` "live_unverified"). The *core modules* read cleanly; the *root* is the problem. **Recommend:** move build-history artifacts to `docs/build-history/`, keep root to README + QUICKSTART + KNOWN_LIMITATIONS.

---

## 10. Spec/doc drift (Track 14)

- **3-way Verdict split.** `interpret/tree.py:29` and `SKILL.md:143` **agree** (8 values incl. `NO-LIFT`/`DIRECTIONAL-ONLY`/`LIFT-WITH-CAVEAT`). `schemas/report.py:27` is the **outlier** (`LEARN-UNDERPOWERED`/`NO-SHIP-PRIMARY`/`ITERATE-WEAK`/`ITERATE-NOVELTY`). Stage 7→8 hands tree.py verdicts into a report.py schema that rejects ~5 of 8. **Fix:** make report.py import the `Verdict` literal from tree.py.
- **`OVER_ENGINEERING_REVIEW.md` §C is itself wrong** — it claimed Verdict lives in report.py "not tree.py as SKILL claims." Reality is the reverse (tree.py + SKILL agree; report.py is the outlier). Correct that paragraph.
- **Doc path mismatch:** journeys J1.2 say `~/.agentxp/profiles/`; code uses `~/.agentxp/credentials/`. Pick one (code is canonical).

---

## 11. Updated gap register

| Gap | Title | Status after audit | Severity | Anchor |
|---|---|---|---|---|
| G1 | Headless spine stubbed (`_invoke_llm`/`advance`/`dispatch_sql`) | Confirmed; by design (Phase 5) | Med | J2.1 |
| G2 | E2E Stage 0→8 never run on seed | Confirmed; not yet demonstrated | High | J2.1 |
| **G3** | **Log not replay-reproducible** | **Confirmed (uuid4/wall-clock/hash)** | **CRITICAL** | J4.5, J5.2 |
| **G4** | **`validate_chain` broken / halts real commits** | **Confirmed 3 ways** | **CRITICAL** | J3.1, J2.1 |
| G5 | Verdict enum 3-way split | Confirmed; report.py outlier | High | J2.1 |
| G6 | Dead code ~2,516 LOC | Confirmed | Med | — |
| G7 | Root doc sprawl 336 KB | Confirmed | Low | — |
| G8 | Snowflake / state-model duplication | Confirmed | Med | J1.2 |
| **G9** | **Integrity wall (refuse loosen-after-results) absent in code+prompts** | **Confirmed absent** | **CRITICAL** | J3.5.1/4/5 |
| G10 | Unguarded `_write_artifact` (locked brief rewritable) | Confirmed | High | J3.5.4 |
| G11 | Hard-crash window in `_commit_stage` (state before log) | Confirmed | High | J3.3 |
| G12 | Resume from log ABSENT | Confirmed | High | J3.3 |
| G13 | Peeking/sequential built but unwired | Confirmed | Med | J2.5.7 |
| G14 | Post-lock amendment flow built but unwired | Confirmed | Med | J3.5.5 |
| G15 | Unredacted leak on untyped dispatch exception | **New** | Med | J3.4 |
| G16 | Flagship chain tests monkeypatch the validator | **New** | High | — |

---

## 12. Recommendation (priority order)

1. **Make the credibility spine real or stop claiming it.** Fix `validate_chain` invariants 1/4/5 (thread `parent_action_id`; add `stage` to gate payloads or key pairing off `action_id`; drop the dead inv 3b), then **delete the monkeypatching** in the chain tests so they exercise real emitters (closes G4, G16). This is the whole ballgame for the product's thesis.
2. **Build the G9 integrity wall** (closes G9, G10): add a "committed?" guard in `_write_artifact`; make `editor.system.md` refuse `post_commit` loosening of locked rules and route legitimate changes through the existing `amendments/` flow (which is the right shape — G14). A skeptic's first test must fail safe.
3. **Make replay real or downgrade the claim** (G3): deterministic ids (content-hash or seq), recorded-not-wall-clock timestamps, order-stable `result_hash`. If out of scope for v0.1, change the docs from "replay reaches the same answer" to "tamper-evident append-only log."
4. **Close the crash window** (G11): append `stage.committed` before advancing `state.yaml`, or make the pair atomic.
5. **Reconcile Verdict** (G5): report.py imports tree.py's literal. Correct `OVER_ENGINEERING_REVIEW.md` §C.
6. **Delete confirmed dead code** (G6) — especially the orphaned `experiment-*.md` prompts; reconcile the two Snowflake impls and two state models (G8).
7. **Wrap dispatch in a final redacted except** (G15).
8. **Then the spine + E2E** (G1/G2): wire one real Stage 0→8 run on the DuckDB seed — converts the periphery from "plausible" to "demonstrated."
9. **Resume** (G12) and **tidy docs** (G7) last.

**Net:** the agentic design is worth keeping and the non-headline engineering (stats, SQL safety, secrets) is genuinely strong. But today AgentXP **demonstrably does not deliver its one differentiating promise** — the audit trail is neither reliably validated, reproducible, nor protected by an integrity wall — and a green test suite is actively hiding that. Items 1–2 are not polish; they are the difference between the product's claim being true and false.
