# AgentXP — Necessity & Over-Engineering Review

**Date:** 2026-05-28
**Scope:** Whole package (`agentxp/`, 116 files, ~22,982 LOC) + agent prompts + skills + docs.
**Question asked:** Is everything in here required, or is it over-engineered — and does it actually fit the agentic system we set out to build?
**Method:** Four blind, read-only reachability audits (one per slice), then cross-checked against `BUILD_STATUS.yaml` and the live `/experiment` skill. Every claim below is grep-confirmed to file:line.

---

## 1. The one-paragraph verdict

The codebase is **not over-engineered in the usual sense** (no baroque abstractions, no premature generality run wild). What it *is* is **breadth-first**: ~23k LOC of surface area was built across 18 modules while the **agentic spine that would make it an agentic system was deliberately left stubbed.** `_invoke_llm` raises `NotImplementedError` (`orchestrator/dispatch.py:201`), `advance()` is a no-op that just re-reads state (`orchestrator/store.py:460`), and `dispatch_sql` raises `NotImplementedError` (`orchestrator/store.py:739`). Per `BUILD_STATUS.yaml:27`, this is **intentional** — "Phase 5 headless `_invoke_llm` wiring" is an explicit exclusion. So the honest framing is not "we built too much," it's **"we built the body before the nervous system."** The result reads as over-engineered because a lot of organs exist that nothing yet drives. On top of that deliberate posture sit ~1.6–1.9k LOC of genuinely dead code, two pairs of parallel implementations, and a flagship "integrity" checker that is itself broken — those are real defects, not strategy.

---

## 2. How I decided what's "necessary" (the methodology)

Necessity is not an abstract property; it's **reachability from a real entry point.** The entry points are exactly three: (a) the `/experiment` 11-stage workflow as defined in `.claude/skills/experiment/SKILL.md`, (b) the seven README CLI commands, (c) the deterministic stats the analyzer/monitor/interpreter agents actually name in their `*.system.md` prompts. Every public symbol was placed in one bucket:

| Bucket | Definition | Disposition |
|---|---|---|
| **LOAD-BEARING** | Reachable from (a)/(b)/(c) | Keep |
| **SCAFFOLDING** | Unwired now but the *current* wave's deliverable or near roadmap, tracked in `BUILD_STATUS.yaml` | Keep, label honestly |
| **SPECULATIVE** | Built for distant roadmap (v0.5/v1.0/v2), or knobs nobody sets, or abstraction over one caller | Defer behind a flag / `roadmap/` dir |
| **DEAD** | Zero non-test callers (grep-confirmed), vestigial | Delete |

The critical refinement: **"exported / importable / has a test" ≠ "reachable in a run."** A function with a unit test but no workflow caller is dead-for-v0.1. And **`BUILD_STATUS.yaml` is the arbiter of SCAFFOLDING-vs-SPECULATIVE** — if a wave is tracked and current, the code is the deliverable, not gold-plating.

---

## 3. The numbers

| Category | ~LOC | Notes |
|---|---|---|
| Total package | 22,982 | 116 `.py` files |
| **Confirmed DEAD (delete now)** | **~1,600–1,900** | zero non-test callers, grep-confirmed |
| **Duplicate / parallel implementations** | **~1,050** | two Snowflake codebases, two state models |
| **Speculative for distant roadmap (v0.5–v1.0)** | **~2,100** | bayesian + sequential + cuped + power — nothing in v0.1 calls them |
| **Built-ahead-of-spine, but tracked & legit (v0.1.1 warehouse wave)** | **~3,400** | `sql/` + 3 warehouse adapters; the *current* deliverable, just not live-verified (no creds) |
| **Genuinely live in a run today** | small islands | and even these can't run end-to-end — the spine is stubbed |

---

## 4. Findings by severity

### A. Dead code — delete now (zero non-test callers, all grep-confirmed)

| What | file | LOC | Evidence |
|---|---|---|---|
| `amendments/` (whole package) | `agentxp/amendments/` | 457 | only self-references; absent from skill/stages/agents |
| `audit/decisions.py` | `write_decision`/`Decision`/`next_ordinal` | 145 | `_commit_stage` *mentions* decisions in a comment (store.py:530) but never calls it |
| `schemas/_versioning.py` | `check_schema_version` | 213 | zero callers; advertises a `migrate state` cmd that doesn't exist |
| `sql/cache.py` | `cache_lookup`/`cache_store` | 199 | docstring claims dispatch calls it; dispatch does not |
| `sql/preview.py` | `preview_query` | 55 | only its own test calls it |
| `sql/transpiler.py` | `transpile()` | 60 | **verify** — W0 edits its dialect *list*, but the function may have no caller |
| `stats/prep.py` | `prepare_experiment_data` | ~200 | only "reference" is an error-code string |
| stats orphans | `effect_size*`, `fishers`, `winsorize`, `denominator_srm`, `_trace.set_trace` | ~330 | named only by the orphaned `experiment-*.md` prompts |

**Highest-leverage single cleanup:** delete the orphaned **`agents/experiment-*.md`** prompt set (a stale parallel to the live `agents/*.system.md`). It is the source of most false "this is wired" signals — it names `winsorize`, `cohens_d`, `power_*`, `extension_estimate`, `monitoring/*`, making dead code look reachable to any grep-based reader (including future-you).

### B. Duplicate / parallel implementations — reconcile (pick one)

1. **Two Snowflake codebases.** `data/snowflake_loader.py` (444 LOC, not exported, test-only) duplicates `sql/adapters/snowflake_adapter.py` (the real one). `BUILD_STATUS.yaml:230` already flags this as `deferred_to_shane`. **Decision needed:** fold-in or delete the loader.
2. **Two state models.** `storage/lifecycle.py` (11-state DAG: DESIGNING/POWERED/COLLECTING…) competes with the `Stage` enum in `schemas/state.py`. The 11-stage loop uses `Stage`; the lifecycle DAG is used only by the orphaned validators/amendments. One of these is the real state machine; the other is conceptual debt.
3. **Duplicated infra helpers.** Two `_atomic_write_bytes` (`audit/storage.py:138`, `storage/store.py:59`) and two `_check_disk_space`. Collapse to one.

### C. The integrity machinery is itself broken (the real irony)

The most gold-plated subsystem — `audit/chain.py` `validate_chain` with 5 invariants, a 200/400ms perf budget, and `PerfBudgetExceeded` rollback — **does not actually work as specified**:

- **Invariants 4 & 5 can't match real events.** `_check_gate_pairing` (chain.py:271-321) reads `event["stage"]` on gate events, but `GateOpened/Resolved/BlockedPayload` carry no `stage` field (events.py:157-193). Gate events never register under a stage; the flagship checker validates a chain the emitters can't produce.
- **Invariant 3(b) hashes `decisions/*.yaml` that are never written** (decisions.py is dead, §A). Vacuously passes; couples a live checker to dead code.
- **Spec drift in the closed sets.** This review originally read the direction backwards: it called `schemas/report.py:27` canonical and `SKILL.md:143/187` + `interpret/tree.py` wrong. The reverse is true — `interpret/tree.py::Verdict` is the canonical home per §1.8.17, `SKILL.md:143/187` and the coherence test (`test_canonical_names.py:187`) agree, and `report.py` held the stale local copy (`LEARN-UNDERPOWERED/NO-SHIP-PRIMARY/ITERATE-WEAK/ITERATE-NOVELTY` vs the canonical `INCONCLUSIVE/NO-LIFT/DIRECTIONAL-ONLY/LIFT-WITH-CAVEAT`). **RESOLVED (W2.3):** `report.py` now imports `Verdict` from `interpret/tree.py`; the divergent enum is deleted. Single source of truth restored.

This matters for the user's actual question: the audit trail is the product's credibility claim ("two reviewers replay the log, reach the same answer"). A broken chain validator undermines the one thing that's supposed to be airtight.

### D. Speculative for a distant roadmap — defer behind a flag

`stats/bayesian.py` (620), `stats/sequential.py` (600), `stats/cuped.py` (430), `stats/power.py`+`ratio_power.py` (470) are all **v0.5–v1.0 per `FINAL_STATUS.md:165`** and called by **nothing** in the v0.1 workflow (the drafter sizes samples in prose, the analyzer dispatches only Welch/proportion/ratio + Holm + SRM). ~2,100 LOC of mathematically-correct, well-tested, **unreachable** code in the default import surface.

> **Honest note on our own recent effort:** the two prior sessions hardened `sequential.py` (the mSPRT radius + small-n Type-I floor, fixes P3-2/#62). That module is roadmap-v1.0 and called by nothing in the live workflow. We did careful work on an organ the body doesn't yet use. That is precisely the pattern this review exists to surface — and a reason to pause the remaining P3 fixes until we agree on scope.

### E. Doc sprawl

The repo README claims it "can be read end-to-end in an afternoon," but the root carries ~**400KB of process docs**: `TEST_PLAN.md` (112KB), `PRD_COVERAGE.md` (43KB), `WAVE1_REVIEW.md` (21KB), `WAVE2_REVIEW.md` (31KB), `REVIEW_4_FINAL.md`, `FINAL_STATUS.md`, `DEMO.md`, `BUILD_STATUS.yaml`, plus this file and the `REVIEW_*` set. Several contradict each other (README "ships in v0.1.1" vs BUILD_STATUS "waves done/live_unverified"). Recommend: move build-process artifacts to `docs/build-history/` and keep the root to README + QUICKSTART + KNOWN_LIMITATIONS.

---

## 5. Does it fit the agentic system we set out to build?

**Partly — the design fits; the build order fought it.** The *design* is genuinely good and genuinely agentic: bundle isolation so the SRM monitor can't see the hypothesis, the interpreter bound to a pre-registered decision rule, a closed-set verdict vocabulary, an append-only audit log. That is the right shape for "agents own judgment, Python owns math."

But an agentic system is defined by the **loop that dispatches agents and routes on their output.** That loop — `advance()` DAG routing + `_invoke_llm` + `dispatch_sql` — is exactly what's stubbed. So today the repo is **a very complete set of tools and schemas for agents that cannot yet be called.** The breadth (4 warehouse adapters, 4 migration entry points, Bayesian/sequential/CUPED stats, an 11-state lifecycle DAG, a perf-budgeted chain validator) was built *around* an empty center. That inversion — periphery before spine — is the source of the "is this over-engineered?" feeling. It isn't mostly over-engineered; it's **mis-sequenced**, with real dead code and broken-integrity defects layered on top.

---

## 6. Recommendation

In priority order:

1. **Delete the confirmed dead code** (§A, ~1.1–1.6k LOC) — including the orphaned `experiment-*.md` prompts. Pure subtraction, no risk, instantly shrinks the readable surface. *(Verify `transpiler.transpile()` first.)*
2. **Fix or rip out the broken integrity machinery** (§C). Either make `validate_chain` Invariants 4/5 match the real payloads, or delete them — a checker that can't fire is worse than none. Reconcile the `Verdict` spec drift between `SKILL.md` and the code.
3. **Reconcile the two parallel pairs** (§B): one Snowflake impl, one state model.
4. **Move §D distant-roadmap stats behind a `roadmap/` boundary or extra** so they're out of the default surface (and pause further hardening of them — see the note in §D).
5. **Then return to the spine.** The single highest-value thing for "is this the agentic system we aim to build" is wiring `_invoke_llm` + `advance()` so one experiment runs Stage 0→8 end-to-end on the existing DuckDB seed (`BUILD_STATUS.yaml:188` W8.3 already wants this). That converts the whole periphery from "plausible" to "demonstrated."
6. **Tidy docs** (§E) last.

**Net:** the instinct is right, but the diagnosis is "mis-sequenced breadth + removable dead code + a broken integrity layer," not "fundamentally over-engineered." Roughly **3–3.5k LOC can be deleted or quarantined this week** with zero loss to v0.1.1, and the design itself is worth keeping.
