# AgentXP v0.1 — Combined Build Plan

**Status:** Execution-ready. Synthesizes `AGENTXP_V01_CLEANUP_MASTER_PLAN.md` (50 tasks, audit-cleanup arc) + `PRESENTATION_SPINE_MASTER_PLAN.md` (33 tasks, continuous-spine + render-quality arc) into a single coherent build.

**Document role:** the **conductor**. Wave structure, task index, dependency graph, files-changed summary, execution order. **Task specs remain in the source plans** — this document points the executor at the right §3.X section of the right source plan for each task. Avoiding duplication of ~30,000 words while keeping execution unambiguous.

**Reading order for executors:** §1 (where you are) → §2 (combined wave table) → §3 (task index for your wave) → §4 (dependency graph) → §5 (files changed) → §6 (open questions, expected empty) → execute.

**Source plans (authoritative for task specs):**
- `~/projects/agentxp/AGENTXP_V01_CLEANUP_MASTER_PLAN.md` — referenced as **[CLEANUP §X.X]** for task specs.
- `~/projects/agentxp/PRESENTATION_SPINE_MASTER_PLAN.md` — referenced as **[PRES §X.X]** for task specs.

---

## §1 Executive Summary

### 1.1 What we're building

One coherent build that closes four product gaps and 20 audit findings (the cleanup arc) AND extends the Module-10 presentation layer from a terminal verb to a continuous share-out spine integrated into the agentic flow (the presentation arc). Six waves, 83 tasks, one atomic surface-flip PR at Wave 4.

**Four cleanup gaps** (CLEANUP plan):
1. CSV → DuckDB warehouse fixture.
2. `/experiment` → `/experiment design` + `/experiment analyze` sub-verbs bridged by a sealed brief.
3. `dispatch_sql` wired through the SQL chokepoint.
4. Inline-mode `dispatch_agent` (Claude is the LLM in v0.1, no API key).

Plus 20 audit findings (B1, B3–B7, B10, G1–G5, S1–S3, S5, S7, I1–I6) folded into the same waves.

**Four presentation categories** (PRES plan):
- A. Continuous share-out spine — five readout types (`intent`, `design_brief`, `monitor_check`, `verdict`, `audit`), share-tails at four moments (Stage 1, 3, 5-on-halt, 8).
- B. Render quality at editorial bar — seven chart primitives, section-per-question template restructure, card adapter rebuild with verdict-as-hero.
- C. Output organization — `experiments/<id>/readouts/<type>/<slot>/<audience>.<format>` directory layout, append-only hash-chained `catalog.jsonl`, cross-experiment readouts index.
- D. User-journey grounding — Maya/Mira/Lin paths each first-class.

### 1.2 The thesis being preserved

Module 0 (deterministic Python owns stats / LLM owns judgment / judgment sealed from result), Module 4 (the integrity spine — locked-rule wall, chain invariants, `_commit_stage` as sole writer), and Module 10 (pure-renderer / polish-and-proof-same-object / three-state RenderStatus) all survive.

Two thesis-extensions added by the combined build:
- **Invariant 6** (cleanup): every committed bundle has paired `agent.dispatched` + `agent.completed` events; legacy unanchored bundles resolve to UNVERIFIABLE (third state alongside valid/invalid). [CLEANUP §3.0 W0.4]
- **Invariant 7** (presentation): every entry in `readouts/catalog.jsonl` has `prev_catalog_entry_hash` linking to the prior entry's sha256; tampering detectable. [PRES §3.0 P0.7]

Plus:
- **Peek-prevention by schema** (presentation): `MidRunVM` literally lacks lift/CI/p-value/per-arm-magnitude fields; `extra="forbid"`. [PRES §3.0 P0.2 + §3.4 P4.6]
- **Provenance cascades downward**: a mid-run over a DRAFT brief is itself DRAFT; cascade is read-time, not write-time. [PRES §3.3 P3.2]

### 1.3 Shane's eight binding decisions (combined)

From the cleanup synthesis (six):
1. Wave 4 ships as one atomic PR.
2. Warehouse seed reproduces `E_F12345 = 314/384/+22.3%` byte-for-byte.
3. State migration is the explicit `agentxp migrate-state` verb.
4. Sample-data CSVs clean-deleted in Wave 4.
5. Power-feasibility threshold: strict 1.0×.
6. `commit-stage` ships as `python3 -m agentxp.recovery commit-stage` (internal namespace).

From the presentation arc (two):
7. Verdict position on HTML report: TOP (F-pattern). Card stays verdict-as-hero in upper third.
8. Mid-run teaching prose tone: matter-of-fact.

### 1.4 The atomic-Wave-4 mechanism

Single feature flag `SURFACE_V01_ENABLED` at `agentxp/_flags.py` (cleanup task **C-W0.2**). Waves 0–3 land schemas + helpers + persist_render behind the flag. Wave 4 is the single atomic PR that flips the flag + deletes CSVs + rewrites SKILL.md/STAGES/CLAUDE.md/QUICKSTART/USER_JOURNEYS/walkthroughs/per-module curriculum + regenerates test bundles + lands EXPERIMENTS.md + lands all new adapters (design_brief, mid_run, intent) + wires share-tails at Stages 1/3/5-halt/8 + lands `/readout` slash command + lands `agentxp readout`/`readouts`/`readouts --index` CLI verbs + writes the catalog at every `persist_render` call.

Wave 5 (1-week post-W4 polish) lands the gauntlet rewrites, trace.md re-walk, README aha-index updates, Module 10 continuous-spine extension, `agentxp prune --readouts`, and cross-experiment index regeneration.

### 1.5 What success looks like

Fresh-clone user, `pip install agentxp`:

```
$ /experiment design
🆕 Starting design for experiment exp_005.
Reading the assignment surface in sample-data/agentxp_demo.duckdb...
No variant column in any table. Good — this is design mode.
What do you want to test?

[... walks Stages 0–3 ...]

📋 Brief locked. Design readout rendered:
   experiments/exp_005/readouts/design_brief/<slot>/exec.html
   (inline preview below; receipt: chain OK · verified)
```

Or, with the seeded fixture:

```
$ /experiment analyze --brief briefs/E_F12345.yaml --experiment-id E_F12345
[... walks Stages 5–8 ...]

📊 Verdict: SHIP — conversion +0.0233 absolute (+22.3% relative), 95% CI [+0.0071, +0.0395], p=0.0048.
   Both guardrails pass.

   Verdict readout rendered:
   experiments/E_F12345/readouts/verdict/<slot>/exec.html

   Want the LinkedIn-shareable card too? [enter to skip]
```

No API key. No CSVs. No NotImplementedError. No `<pending>` literals. No silent test substitution. No null-input passes. No underpowered briefs. No `agentxp report` needed — the readout fires inline. No "where's my chart" — every readout type renders at the editorial quality the reference HTMLs set.

---

## §2 Combined Wave Structure

| # | Theme | Cleanup tasks | Presentation tasks | **Total** | Ships | Lands as |
|---|---|---|---|---|---|---|
| 0 | Schema + hygiene foundations | 17 | 8 | **25** | dark | merge train |
| 1 | SQL chokepoint + result_hash | 6 | 2 | **8** | dark | merge train |
| 2 | Warehouse fixture + semantic models + metrics | 8 | 3 | **11** | dark | merge train |
| 3 | Inline-mode dispatch + brief integrity | 5 | 3 | **8** | dark | merge train |
| 4 | **ATOMIC SURFACE FLIP** | 10 | 14 | **24** | flag flips | one atomic PR |
| 5 | Gauntlet + trace.md + polish | 4 | 3 | **7** | docs only | 1-week post-W4 |
| | **Totals** | **50** | **33** | **83** | | |

Six waves. 83 tasks. One atomic PR.

---

## §3 Task Index (executor's manifest)

Task ID convention:
- **C-W0.1 … C-W5.4** — cleanup tasks. Specs in **[CLEANUP §3.X]**.
- **P-W0.1 … P-W5.3** — presentation tasks. Specs in **[PRES §3.X]**.

Within a wave, tasks may execute in parallel where deps allow. The dependency graph in §4 shows cross-task ordering.

### §3.0 Wave 0 — 25 tasks (schema + hygiene foundations)

| Task ID | Source | One-line | Depends on |
|---|---|---|---|
| **C-W0.1** | [CLEANUP §3.0] | `Sha256Hex` type alias + repo-wide hash-field refactor | — |
| **C-W0.2** | [CLEANUP §3.0] | `SURFACE_V01_ENABLED` feature flag | — |
| **C-W0.3** | [CLEANUP §3.0] | `EventMetadataSubtype` Literal extension | C-W0.1 |
| **C-W0.4** | [CLEANUP §3.0] | Chain Invariant 6 — paired-events-per-bundle | C-W0.3 |
| **C-W0.5** | [CLEANUP §3.0] | StateYaml v3→v4 + `agentxp migrate-state` verb | C-W0.1, C-W0.3 |
| **C-W0.6** | [CLEANUP §3.0] | Repo-wide `exp_id` → `experiment_id` sweep + AST lint | — |
| **C-W0.7** | [CLEANUP §3.0] | `LastActionMetadata` explicit submodel | C-W0.5 |
| **C-W0.8** | [CLEANUP §3.0] | Add `python-ulid>=2.2,<3.0` to pyproject.toml | — |
| **C-W0.9** | [CLEANUP §3.0] | Drop orphan v1 metric YAMLs at project root | — |
| **C-W0.10** | [CLEANUP §3.0] | `VoiceRule.enforcement: Literal["halt","warn"]` | C-W0.1 |
| **C-W0.11** | [CLEANUP §3.0] | `VerdictKind` 8→9 — add `UNVERIFIABLE` | — |
| **C-W0.12** | [CLEANUP §3.0] | `FactSource` discriminated subclass split + `kind: fact\|dim` | C-W0.1 |
| **C-W0.13** | [CLEANUP §3.0] | Schema cleanups (predicted_direction drop, three-slot MDE XOR, ConfidenceLabel enum, status-gated data_plan, predicted_magnitude_*, BriefV3 base) | C-W0.1 |
| **C-W0.14** | [CLEANUP §3.0] | `OrchestratorStore.bootstrap_experiment` + `allocate_experiment_id` | C-W0.5 |
| **C-W0.15** | [CLEANUP §3.0] | `agentxp.recovery` namespace + `commit-stage` + `unlock --reason` + `.state.lock` lifecycle surfacing | C-W0.5 |
| **C-W0.16** | [CLEANUP §3.0] | `agentxp prune` verb | — |
| **C-W0.17** | [CLEANUP §3.0] | `agentxp new` verb | C-W0.14 |
| **P-W0.1** | [PRES §3.0] | `Sha256Hex` reuse in catalog schemas | C-W0.1 |
| **P-W0.2** | [PRES §3.0] | Per-type ViewModels (IntentVM, DesignBriefVM, MidRunVM, VerdictVM rename) | C-W0.13 |
| **P-W0.3** | [PRES §3.0] | Per-type ViewBundle subtypes (IntentBundle, DesignBriefBundle, MidRunBundle) | P-W0.2 |
| **P-W0.4** | [PRES §3.0] | `ChartData` schema_version 2 (per-arm means + SEs) | P-W0.2 |
| **P-W0.5** | [PRES §3.0] | `BriefV3` extensions (power_stats, power_curve, allocation, decision_rules) | C-W0.13 |
| **P-W0.6** | [PRES §3.0] | `ReadoutKind` enum + closure test | — |
| **P-W0.7** | [PRES §3.0] | Catalog event schemas (5 event kinds with hash chain) | P-W0.1, P-W0.6 |
| **P-W0.8** | [PRES §3.0] | `_VERDICT_MODIFIER` UNVERIFIABLE entry + brand stripe tokens + CSS | C-W0.11 |

**W0 parallel batches** (within-wave concurrency):
- **Batch 0-A** (no deps): C-W0.1, C-W0.2, C-W0.6, C-W0.8, C-W0.9, C-W0.11, C-W0.16, P-W0.6
- **Batch 0-B** (after 0-A): C-W0.3, C-W0.5, C-W0.10, C-W0.12, C-W0.13, P-W0.1, P-W0.8
- **Batch 0-C** (after 0-B): C-W0.4, C-W0.7, C-W0.14, C-W0.15, C-W0.17, P-W0.2, P-W0.5
- **Batch 0-D** (after 0-C): P-W0.3, P-W0.4, P-W0.7

### §3.1 Wave 1 — 8 tasks (SQL chokepoint + result_hash)

| Task ID | Source | One-line | Depends on |
|---|---|---|---|
| **C-W1.1** | [CLEANUP §3.1] | `OrchestratorStore.dispatch_sql` wrapper around existing worker | C-W0.3 |
| **C-W1.2** | [CLEANUP §3.1] | `canonical_result_hash(rows, column_names)` content-faithfulness fix | — |
| **C-W1.3** | [CLEANUP §3.1] | DuckDB adapter for `dispatch_sql` | C-W1.1 |
| **C-W1.4** | [CLEANUP §3.1] | Parquet emission for query results | C-W1.3 |
| **C-W1.5** | [CLEANUP §3.1] | `SupportedTestType` Literal + closure test (audit B6) | — |
| **C-W1.6** | [CLEANUP §3.1] | Verdict tree UNVERIFIABLE-on-null path (audit B5) | C-W0.11 |
| **P-W1.1** | [PRES §3.1] | `compute_n_required_curve` in `agentxp.stats.power` | — |
| **P-W1.2** | [PRES §3.1] | `walk_tree` UNVERIFIABLE-on-null (duplicate scope with C-W1.6; merge in execution) | C-W0.11 |

**Note on P-W1.2 / C-W1.6:** these address the same audit finding (B5). Execute as a single task; track as **C-W1.6** for primary; P-W1.2 is the presentation arc's reference to confirm coordination.

**W1 parallel batches:**
- **Batch 1-A**: C-W1.2, C-W1.5, C-W1.6, P-W1.1
- **Batch 1-B**: C-W1.1
- **Batch 1-C**: C-W1.3
- **Batch 1-D**: C-W1.4

### §3.2 Wave 2 — 11 tasks (warehouse fixture)

| Task ID | Source | One-line | Depends on |
|---|---|---|---|
| **C-W2.1** | [CLEANUP §3.2] | Generate `sample-data/agentxp_demo.duckdb` (6 tables, 8 experiments) | C-W1.1, C-W1.3 |
| **C-W2.2** | [CLEANUP §3.2] | Six tables DDL (experiments, assignments, users, sessions, orders, page_events) | — |
| **C-W2.3** | [CLEANUP §3.2] | `semantic_models/*.yaml` with `kind: fact\|dim` and `joins:` blocks | C-W0.12 |
| **C-W2.4** | [CLEANUP §3.2] | `metrics/*.yaml` v2 (6 canonical metrics) | C-W0.13 |
| **C-W2.5** | [CLEANUP §3.2] | `assignments/README.md` convention doc | — |
| **C-W2.6** | [CLEANUP §3.2] | `sample-data/EXPERIMENTS.md` table | — |
| **C-W2.7** | [CLEANUP §3.2] | `fixture.lock.yaml` (logical-content hashing) | C-W2.1 |
| **C-W2.8** | [CLEANUP §3.2] | Regenerate `tests/render/fixtures/bundles_ship/*` from new fixture | C-W2.1 |
| **P-W2.1** | [PRES §3.2] | E_F12345 seed adds `PowerGridData` | P-W0.5, P-W1.1, C-W2.1 |
| **P-W2.2** | [PRES §3.2] | Interim `monitor.50pct.snapshot.yaml` for E_F12345 | C-W2.1 |
| **P-W2.3** | [PRES §3.2] | Per-arm means and SEs in seed + `MetricResult` projection | P-W0.4, C-W2.1 |
| **P-W2.4** | [PRES §3.2] | Cross-format equality test matrix scaffolding (manifests authored in W4) | P-W0.2 |

**W2 parallel batches:**
- **Batch 2-A**: C-W2.2, C-W2.5, C-W2.6, P-W2.4
- **Batch 2-B**: C-W2.1 (gates everything that touches the fixture file)
- **Batch 2-C**: C-W2.3, C-W2.4, C-W2.7, P-W2.1, P-W2.2, P-W2.3, C-W2.8

### §3.3 Wave 3 — 8 tasks (inline dispatch + brief integrity)

| Task ID | Source | One-line | Depends on |
|---|---|---|---|
| **C-W3.1** | [CLEANUP §3.3] | `dispatch_agent` inline branch (atomic pair, no retry) | C-W0.3, C-W0.4 |
| **C-W3.2** | [CLEANUP §3.3] | Inline raw-text persistence at `bundles/<agent>.inline.txt` + `inline_raw_sha256` | C-W3.1 |
| **C-W3.3** | [CLEANUP §3.3] | Three-part brief integrity lock | C-W0.1, C-W0.13 |
| **C-W3.4** | [CLEANUP §3.3] | Brief-commit 1.0× strict power refusal | C-W3.3, C-W2.1 |
| **C-W3.5** | [CLEANUP §3.3] | Two-state-lifecycle (Stage 4 terminal for design, Stage 8 for analyze) | C-W0.5 |
| **P-W3.1** | [PRES §3.3] | `prepare_power_grid(brief)` at brief lock | P-W0.5, P-W1.1 |
| **P-W3.2** | [PRES §3.3] | Per-readout-kind `build_provenance` discriminator + cascade | P-W0.6, P-W0.2, C-W3.3 |
| **P-W3.3** | [PRES §3.3] | `persist_render` helper (atomic write + sidecar + catalog append) | P-W0.7 |

**W3 parallel batches:**
- **Batch 3-A**: C-W3.3, C-W3.5
- **Batch 3-B**: C-W3.1, P-W3.3
- **Batch 3-C**: C-W3.2, C-W3.4, P-W3.1, P-W3.2

### §3.4 Wave 4 — 24 tasks (ATOMIC SURFACE FLIP — one PR)

All 24 tasks land in one PR. Internal task execution can parallelize (per the dependency graph), but no intermediate PR ships. The PR flips `SURFACE_V01_ENABLED`, deletes the CSVs, rewrites the docs/skill/STAGES, lands the new adapters, wires the share-tails, and lands the new CLI verbs.

| Task ID | Source | One-line | Depends on |
|---|---|---|---|
| **C-W4.1** | [CLEANUP §3.4] | Flip `SURFACE_V01_ENABLED` default to True | — |
| **C-W4.2** | [CLEANUP §3.4] | Delete 8 sample-data CSVs | C-W2.1 |
| **C-W4.3** | [CLEANUP §3.4] | `.claude/commands/experiment.md` rewrite for sub-verbs | — |
| **C-W4.4** | [CLEANUP §3.4] | `.claude/skills/experiment/SKILL.md` rewrite (inline-mode v0.1) | C-W3.1 |
| **C-W4.5** | [CLEANUP §3.4] | `.claude/skills/experiment/STAGES.md` split into STAGES_DESIGN.md + STAGES_ANALYZE.md | C-W3.3 |
| **C-W4.6** | [CLEANUP §3.4] | Root `CLAUDE.md` §1 rewrite (literal 3 sentences) | — |
| **C-W4.7** | [CLEANUP §3.4] | `docs/QUICKSTART.md` + `docs/USER_JOURNEYS.md` rewrite | C-W3.3 |
| **C-W4.8** | [CLEANUP §3.4] | Walkthroughs rewrite (your-first → meta; pre-registration → design; monitoring → analyze; data-connectors → synthetic 3-row CSV) | — |
| **C-W4.9** | [CLEANUP §3.4] | Per-module curriculum 0–10 updates (per change matrix) | — |
| **C-W4.10** | [CLEANUP §3.4] | Muscle-memory refusal message for `--data <csv>` | — |
| **P-W4.1** | [PRES §3.4] | Four pure `distill_*` functions (`distill_intent / distill_design_brief / distill_mid_run / distill_verdict`) | P-W0.2 |
| **P-W4.2** | [PRES §3.4] | Seven chart primitives at viewBox 1020×H | P-W0.4, P-W2.3, C-W2.8 |
| **P-W4.3** | [PRES §3.4] | Existing chart fixes (`lift_bar`, `ci_interval` axis-label collision) | P-W4.2 |
| **P-W4.4** | [PRES §3.4] | `html.py` section-per-question restructure (verdict at TOP) | P-W4.1, P-W4.2 |
| **P-W4.5** | [PRES §3.4] | New `design_brief.py` adapter + template | P-W0.2, P-W0.5, P-W4.2 |
| **P-W4.6** | [PRES §3.4] | New `mid_run.py` adapter (peek-safe by construction) | P-W0.2 |
| **P-W4.7** | [PRES §3.4] | New `intent.py` adapter (HTML + Markdown for share-tail) | P-W0.2 |
| **P-W4.8** | [PRES §3.4] | `card.py` rebuild (verdict-as-hero, real job) | P-W4.2, P-W4.4 |
| **P-W4.9** | [PRES §3.4] | Four library entry points (`render_intent_card / render_design_brief / render_monitor_check / render_verdict`) | P-W4.5, P-W4.6, P-W4.7, P-W4.8 |
| **P-W4.10** | [PRES §3.4] | `/readout` slash command + `agentxp readout` CLI verb (alias `agentxp report` with DeprecationWarning) | P-W4.9 |
| **P-W4.11** | [PRES §3.4] | `agentxp readouts <id>` + `agentxp readouts --index` CLI verbs | P-W3.3, P-W4.10 |
| **P-W4.12** | [PRES §3.4] | Share-tail wiring at Stage 1 | P-W4.9, C-W4.4 |
| **P-W4.13** | [PRES §3.4] | Share-tail wiring at Stage 3 + Stage 8 | P-W4.9, P-W4.12 |
| **P-W4.14** | [PRES §3.4] | Share-tail wiring at Stage 5 halt | P-W4.9, C-W4.5 |

**W4 internal parallel batches (within the atomic PR):**
- **Batch 4-A** (independent): C-W4.1, C-W4.2, C-W4.3, C-W4.6, C-W4.8, C-W4.9, C-W4.10, P-W4.1, P-W4.2
- **Batch 4-B** (after 4-A): C-W4.4, C-W4.5, C-W4.7, P-W4.3, P-W4.4, P-W4.5, P-W4.6, P-W4.7, P-W4.8
- **Batch 4-C** (after 4-B): P-W4.9
- **Batch 4-D** (after 4-C): P-W4.10
- **Batch 4-E** (after 4-D): P-W4.11, P-W4.12, P-W4.13, P-W4.14

The atomic PR consolidates all 24 task outputs at the end.

### §3.5 Wave 5 — 7 tasks (post-W4 polish, 1-week window)

| Task ID | Source | One-line | Depends on |
|---|---|---|---|
| **C-W5.1** | [CLEANUP §3.5] | Module 8 gauntlet rewrite (18 → 21 questions) | C-W4.9 |
| **C-W5.2** | [CLEANUP §3.5] | trace.md numeric re-verification | C-W2.8 |
| **C-W5.3** | [CLEANUP §3.5] | README aha-index + module-map + fixture cheat-sheet update | C-W4.9 |
| **C-W5.4** | [CLEANUP §3.5] | `docs/SYSTEM_AUDIT.md` §11 final entries | — |
| **P-W5.1** | [PRES §3.5] | Module 10 curriculum extension (continuous-spine sub-section) | C-W4.9 |
| **P-W5.2** | [PRES §3.5] | `agentxp prune --readouts` extension | C-W0.16, P-W0.7 |
| **P-W5.3** | [PRES §3.5] | Cross-experiment readouts-index regeneration | P-W4.11 |

**W5 parallel batches:**
- **Batch 5-A** (all independent within W5): every task can run concurrently.

---

## §4 Dependency Graph (high-level)

```
W0 Schema foundations
   ├── Audit primitives: Sha256Hex (C-W0.1) → hash-typed fields everywhere
   ├── Feature flag: SURFACE_V01_ENABLED (C-W0.2)
   ├── Event subtype Literal (C-W0.3) → Invariant 6 (C-W0.4) → inline-mode (Wave 3)
   ├── State schema v3→v4 (C-W0.5) + LastActionMetadata (C-W0.7) + bootstrap (C-W0.14) + recovery (C-W0.15)
   ├── Closed-enum extensions: VerdictKind +UNVERIFIABLE (C-W0.11) → walk_tree fix (Wave 1)
   ├── Schema cleanups: BriefV3 base (C-W0.13) → BriefV3 extensions (P-W0.5) → power_grid (Wave 3)
   ├── Presentation: VMs (P-W0.2) → Bundles (P-W0.3) → ChartData v2 (P-W0.4)
   └── Catalog primitives: ReadoutKind (P-W0.6) + Catalog events (P-W0.7)
        ↓
W1 SQL chokepoint
   ├── dispatch_sql wrapper (C-W1.1) ← C-W0.3 + DuckDB adapter (C-W1.3) → parquet (C-W1.4)
   ├── result_hash fix (C-W1.2)
   ├── SupportedTestType registry (C-W1.5, audit B6)
   ├── walk_tree UNVERIFIABLE (C-W1.6 / P-W1.2, audit B5) ← C-W0.11
   └── compute_n_required_curve (P-W1.1)
        ↓
W2 Warehouse fixture
   ├── Six tables DDL (C-W2.2) → generate warehouse (C-W2.1) ← C-W1.1 + C-W1.3
   │     ↓
   │     ├── semantic_models (C-W2.3) ← C-W0.12
   │     ├── metrics (C-W2.4) ← C-W0.13
   │     ├── assignments README (C-W2.5)
   │     ├── EXPERIMENTS.md (C-W2.6)
   │     ├── fixture.lock.yaml (C-W2.7)
   │     ├── test bundles regenerated (C-W2.8)
   │     ├── PowerGridData seed (P-W2.1) ← P-W0.5 + P-W1.1
   │     ├── Interim monitor snapshot (P-W2.2)
   │     └── Per-arm means/SEs seed (P-W2.3) ← P-W0.4
   └── Cross-format matrix scaffolding (P-W2.4) ← P-W0.2
        ↓
W3 Inline dispatch + brief integrity
   ├── dispatch_agent inline (C-W3.1) ← C-W0.3, C-W0.4 → inline.txt (C-W3.2)
   ├── 3-part brief lock (C-W3.3) ← C-W0.1, C-W0.13
   ├── Power refusal at brief-commit (C-W3.4) ← C-W3.3, C-W2.1
   ├── Two-state lifecycle (C-W3.5) ← C-W0.5
   ├── prepare_power_grid (P-W3.1) ← P-W0.5, P-W1.1
   ├── Per-readout-kind build_provenance (P-W3.2) ← P-W0.6, P-W0.2, C-W3.3
   └── persist_render helper (P-W3.3) ← P-W0.7
        ↓
W4 ATOMIC SURFACE FLIP (one PR)
   ├── Flag flip (C-W4.1) + CSV delete (C-W4.2)
   ├── Slash command + SKILL.md + STAGES rewrite (C-W4.3/4/5)
   ├── CLAUDE.md §1, QUICKSTART, USER_JOURNEYS, walkthroughs, per-module curriculum (C-W4.6/7/8/9)
   ├── Muscle-memory refusal (C-W4.10)
   ├── Four distill_* (P-W4.1) ← P-W0.2
   ├── Seven chart primitives + chart fixes (P-W4.2, P-W4.3) ← P-W0.4, P-W2.3, C-W2.8
   ├── html.py restructure (P-W4.4) + new adapters design_brief/mid_run/intent (P-W4.5/6/7) + card rebuild (P-W4.8)
   ├── Four library entry points (P-W4.9)
   ├── /readout slash + agentxp readout/readouts/--index CLI (P-W4.10, P-W4.11)
   └── Share-tail wiring at Stages 1/3/5-halt/8 (P-W4.12/13/14) ← P-W4.9, C-W4.4, C-W4.5
        ↓
W5 polish (1-week post-W4)
   ├── Module 8 gauntlet 18→21 (C-W5.1) ← C-W4.9
   ├── trace.md re-walk (C-W5.2) ← C-W2.8
   ├── README aha-index + map + cheat-sheet (C-W5.3) ← C-W4.9
   ├── SYSTEM_AUDIT.md §11 (C-W5.4)
   ├── Module 10 continuous-spine extension (P-W5.1) ← C-W4.9
   ├── agentxp prune --readouts (P-W5.2) ← C-W0.16, P-W0.7
   └── Cross-experiment index regen (P-W5.3) ← P-W4.11
```

---

## §5 Files Changed Summary (combined)

Full per-task file lists live in the source plans. Summary by wave + theme:

**Wave 0 schema files (25 tasks):**
- `agentxp/schemas/_types.py` (new) — Sha256Hex
- `agentxp/schemas/state.py` (extended) — v4 schema, LastActionMetadata, terminal, design_ref
- `agentxp/schemas/report.py` (extended) — BriefV3 + presentation extensions, MetricResult per-arm fields, ChartData v2
- `agentxp/schemas/catalog.py` (new) — catalog event schemas
- `agentxp/render/viewmodel.py` (extended) — per-type VMs, Bundle subtypes
- `agentxp/render/readout_kind.py` (new) — ReadoutKind enum
- `agentxp/render/brand.py` (extended) — stripe tokens
- `agentxp/render/adapters/html.py` (modified) — `_VERDICT_MODIFIER["UNVERIFIABLE"]`
- `agentxp/assets/design/components.css` (extended) — `.xp-verdict-badge-incomplete`
- `agentxp/audit/events.py` (extended) — `EventMetadataSubtype` Literal
- `agentxp/audit/chain.py` (extended) — Invariant 6
- `agentxp/_flags.py` (new) — `SURFACE_V01_ENABLED`
- `agentxp/cli/migrate_state.py` (new), `agentxp/cli/recovery/` (new namespace), `agentxp/cli/prune.py` (new), `agentxp/cli/new.py` (new)
- `agentxp/orchestrator/store.py` (extended) — bootstrap_experiment, allocate_experiment_id
- `pyproject.toml` (modified) — python-ulid pin
- `metrics/*.yaml` v1 orphans (deleted)
- Closure tests (many new)

**Wave 1 SQL files (8 tasks):**
- `agentxp/orchestrator/store.py` (extended) — `dispatch_sql` wrapper
- `agentxp/sql/dispatch.py` (existing, kept) — the worker
- `agentxp/sql/duckdb_adapter.py` (new)
- `agentxp/sql/parquet_emit.py` (new)
- `agentxp/sql/hashing.py` (new) — `canonical_result_hash`
- `agentxp/analyze/tests.py` (extended) — `SupportedTestType` registry + refusal
- `agentxp/interpret/tree.py` (extended) — UNVERIFIABLE-on-null
- `agentxp/stats/power.py` (extended) — `compute_n_required_curve`

**Wave 2 warehouse fixture files (11 tasks):**
- `sample-data/agentxp_demo.duckdb` (new, generated)
- `agentxp/fixtures/generate_demo_warehouse.py` (new)
- `agentxp/fixtures/E_F12345_seed_contract.yaml` (new) — byte-for-byte contract
- `semantic_models/users.yaml`, `metrics/conversion_rate.yaml` etc. (new project root files)
- `assignments/README.md` (new), `sample-data/EXPERIMENTS.md` (new)
- `fixture.lock.yaml` (new)
- `tests/render/fixtures/bundles_ship/*` (regenerated)
- `tests/render/test_cross_format_equality.py` (extended) + `tests/golden/canonical_strs/` (new)

**Wave 3 inline dispatch + brief integrity files (8 tasks):**
- `agentxp/orchestrator/store.py` (extended) — `dispatch_agent` inline branch, `prepare_power_grid`
- `agentxp/orchestrator/inline_persist.py` (new) — inline raw-text writer
- `agentxp/schemas/brief.py` (extended) — three-part integrity lock
- `agentxp/render/provenance.py` (extended) — per-readout-kind discriminator
- `agentxp/render/persistence.py` (new) — `persist_render` helper
- StateYaml lifecycle handlers (terminal field set at Stage 4 design / Stage 8 analyze)

**Wave 4 atomic surface flip files (24 tasks, one PR):**
- `agentxp/render/distill.py` (extended) — 4 `distill_*` functions
- `agentxp/render/charts.py` (replaced) — 7 primitives at 1020-viewBox + 2 fixes
- `agentxp/render/adapters/html.py` (modified) — section-per-question restructure
- `agentxp/render/adapters/design_brief.py` (new)
- `agentxp/render/adapters/mid_run.py` (new)
- `agentxp/render/adapters/intent.py` (new)
- `agentxp/render/adapters/card.py` (replaced) — verdict-as-hero
- `templates/` directory — `experiment-report.html.j2` (replaced), `design-brief.html.j2` (new), `mid-run.html.j2` (new), `intent.html.j2` + `intent.md.j2` (new), `social-card.html.j2` (replaced), `partials/xp-verdict-hero.html.j2` (new), `partials/xp-srm-section.html.j2` (new), `partials/xp-primary-section.html.j2` (new), `partials/xp-guardrail-section.html.j2` (new)
- `agentxp/render/__init__.py` (extended) — 4 library entry points
- `.claude/commands/readout.md` (new); `.claude/commands/share-experiment.md` (deleted); `.claude/commands/experiment.md` (rewritten for sub-verbs)
- `agentxp/cli/readout.py` (new); `agentxp/cli/readouts.py` (new); `agentxp/cli/report.py` (modified — alias + DeprecationWarning)
- `.claude/skills/experiment/SKILL.md` (rewrite); `.claude/skills/experiment/STAGES_DESIGN.md` (new); `.claude/skills/experiment/STAGES_ANALYZE.md` (new)
- Root `CLAUDE.md` (modified — literal 3 sentences for §1; §2 + §4 updates)
- `docs/QUICKSTART.md` (rewrite), `docs/USER_JOURNEYS.md` (rewrite)
- `docs/walkthroughs/your-first-experiment.md` (rewrite to meta), `docs/walkthroughs/pre-registration.md` (rewrite to design), `docs/walkthroughs/monitoring.md` → `docs/walkthroughs/analyze.md` (renamed + rewrite), `docs/walkthroughs/data-connectors.md` (rewrite with synthetic 3-row CSV)
- `docs/learn/*.md` (per-module updates per CLEANUP §3.4 W4.9 change matrix)
- `sample-data/*.csv` (8 files deleted)

**Wave 5 polish files (7 tasks):**
- `docs/learn/08_capstone.md` (gauntlet 18→21)
- `docs/learn/trace.md` (numeric re-walk)
- `docs/learn/README.md` (aha-index + map + cheat-sheet)
- `docs/learn/10_presentation.md` (continuous-spine sub-section)
- `docs/SYSTEM_AUDIT.md` (§11 final entries)
- `agentxp/cli/prune.py` (extended — `--readouts` flag)
- `agentxp/cli/readouts.py` (extended — `--index` regeneration)

---

## §6 Open Questions

All conflicts resolved through Phases 1–2b (cleanup arc) + Phase B.1–B.2 (presentation arc) + Round 2 revisions + Shane's eight binding decisions. **The plan is execution-ready.**

Items deferred to v0.2 (out of scope for this build, flagged here so they don't get lost):
- `Bundle.builder()` convenience classes for Lin's notebook path.
- Slot tab-completion in `/readout <id> --type design_brief --slot <ts>`.
- Headless-mode `auto_render_public_card` config flag default.

Items where synthesis lands per moderator recommendation; Shane can revisit later:
- Brief-drift cascade status = DRAFT_UNVERIFIED (not UNVERIFIABLE).
- Pruning policy default = `--keep-latest`.

---

## §7 Execution Protocol (Phase E)

Each wave executes:

1. **Read this combined plan §3.X** for the wave's task index + parallel batches.
2. **For each task**: read the source plan section [CLEANUP §3.X.Y] or [PRES §3.X.Y] for the spec, file paths, owner persona, acceptance criteria.
3. **Launch builder agents** in parallel per the batch grouping. Same-file conflicts force sequential execution (see methodology §6).
4. **Per-task tracker update**: status → in_progress → completed (or failed).
5. **Wave-end review**: a review agent verifies every task's acceptance criteria, runs the closure tests, runs `.venv/bin/python -m pytest -q`.
6. **Review-and-fix loop**: review findings route to follow-up builder tasks; re-review until clean.
7. **Progress to next wave** when the current wave's tasks are all `completed` and the review agent has signed off.

Standing constraints from prior session: local commits only, no push without explicit approval; create NEW commits not amends; specific-file staging; `.venv/bin/python` for agentxp tests; no emojis in files; anti-hype flat technical voice.

---

End of combined build plan. Phase D generates `BUILD_STATUS_COMBINED.yaml` from §3's 83 task entries. Phase E begins execution at Wave 0 Batch 0-A.
