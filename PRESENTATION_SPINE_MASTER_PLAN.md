# AgentXP Presentation Spine — Master Plan

**Status:** Synthesized from 5 Round 1 plans + debate summary + 5 Round 2 revisions + Shane's two resolutions on flagged questions.
**Layers onto:** `~/projects/agentxp/AGENTXP_V01_CLEANUP_MASTER_PLAN.md` (6 waves, 50 tasks).
**Source of truth for:** the presentation-spine extension that turns Module 10's terminal-render layer into a continuous share-out spine integrated into the agentic flow.
**Audience:** the persona panel + Shane + the synthesizer who merges this with the cleanup plan.

---

## §1 Executive Summary

### 1.1 What we're building

The Module-10 presentation layer ships today as a **terminal spine**: `report.json` commits at Stage 8, then `agentxp report <id>` re-renders on demand. The walk-through showed this is fundamentally a UX miss — the polished surfaces should be inside the agentic flow, not bolted on at the end as a verb the user has to remember. Plus the live render quality is broken (axis collisions, missing guardrail charts, missing distribution overlap, "format without a job" card).

This plan extends presentation from terminal to **continuous**: share-tail readouts fire at every safe `stage.committed` moment, in formats appropriate to the moment's audience, written to a persisted catalog that survives the experiment's lifecycle. The chart layer gets rebuilt at editorial quality matching the reference HTMLs Shane prototyped (`agentxp-01-experiment-design.html`, `agentxp-02-experiment-analysis.html`).

Four categories of work, integrated:

**A. Continuous share-out spine.** Five readout types (`intent`, `design_brief`, `monitor_check`, `verdict`, `audit`), share-tails wired into four moments (Stage 1, 3, 5-on-halt, 8). Stages 2/4 fold inline; Stages 6/7 surface nothing. Interaction modes per the existing infer/ask/menu contract.

**B. Render quality at editorial bar.** Seven chart primitives (control_vs_treatment_bars, distribution_overlap, guardrail_threshold, power_design_curve, arm_allocation_bar, srm_observed_bar, metric_callout_strip). New per-type adapters (`design_brief.py`, `mid_run.py`, `intent.py`). Section-per-question template restructure. Card adapter rebuilt with a real job. Standardize on viewBox 1020×H; kill the 480px scale problem.

**C. Output organization at scale.** Per-experiment readouts directory (`experiments/<id>/readouts/<type>/<slot>/<audience>.<format>`), per-format provenance sidecars, append-only hash-chained `catalog.jsonl`, derived `catalog.json` cache, cross-experiment `readouts-index.html`. Versioning via supersession events; amendments via cascade. New `agentxp prune --readouts` verb.

**D. User-journey grounding.** Three personas (Maya/PM, Mira/Eng, Lin/DS) each get a path. Maya: inline share-tails + paste-ready Slack paragraphs. Mira: library + audit. Lin: pure `render_*` library calls accepting hand-built bundles, returning strings, never touching disk.

### 1.2 The thesis being preserved

Three Module-10 axioms must survive the extension:

1. **Pure-renderer axiom.** Every `distill_*` function is pure: no I/O, no clock, no chain access, no re-derivation. Each takes pre-validated Pydantic models, returns a VM. Four functions: `distill_intent`, `distill_design_brief`, `distill_mid_run`, `distill_verdict`.
2. **Polish-and-proof-in-same-object.** Every readout's `ViewBundle` welds its type-specific VM with its type-specific Provenance. No adapter can emit the polish without the receipts. No `--skip-provenance` flag exists.
3. **Three-state RenderStatus extended via cascade.** VERIFIED / DRAFT_UNVERIFIED / UNVERIFIABLE applies per readout type. Provenance cascades downward: a mid-run over a DRAFT brief is itself DRAFT; a verdict over a post-lock-edited brief is DRAFT even when `report.json` was committed cleanly. Cascade is read-time, not write-time.

Two thesis-extensions added by this work:

4. **Peek-prevention by schema.** `MidRunVM` literally lacks lift/CI/p-value/per-arm-magnitude fields. `extra="forbid"`. The schema is the wall — a developer cannot accidentally show a peek-revealing number without an explicit schema edit visible in code review.
5. **Renders live outside `log.jsonl` but inside their own hash chain.** EventName-at-13 closure holds. Renders track in `readouts/catalog.jsonl` with a `prev_catalog_entry_hash` per entry. This is **Invariant 7** (a new sibling invariant to the cleanup plan's Invariant 6, which adds "every bundle paired with dispatches").

### 1.3 Shane's six binding decisions (carried forward from cleanup)

1. **Wave-4 ships as one atomic PR** (the user-facing surface flip).
2. **Warehouse seeds reproduce `E_F12345 = 314/384/+22.3%`** byte-for-byte.
3. **State migration is the explicit `agentxp migrate-state` verb.**
4. **Sample-data CSVs clean-deleted** when warehouse fixture lands.
5. **Power-feasibility threshold: strict 1.0×** at brief commit.
6. **`commit-stage` ships as `python3 -m agentxp.recovery commit-stage`.**

### 1.4 Shane's two presentation-specific resolutions

7. **Verdict position on HTML report:** TOP. Editorial+viz's F-pattern argument. Card stays verdict-as-hero in upper third.
8. **Mid-run teaching prose tone:** matter-of-fact (matches the editorial register of the existing reference HTMLs).

### 1.5 What success looks like

A fresh-clone user runs `/experiment` and never has to invoke `/share-experiment` or `agentxp report` to see their readouts. After Stage 3 commits, the brief readout renders inline in chat AND lands on disk in `experiments/<id>/readouts/design_brief/<slot>/`. After Stage 8 commits, the verdict readout fires inline with a single follow-up question for the public card. A days-later return shows every readout ever rendered for every experiment via `agentxp readouts <id>` + `agentxp readouts --index`.

A skeptic running `agentxp audit <id>` sees both chains validate independently: `log.jsonl` (the experiment's state chain) and `catalog.jsonl` (the renders chain). Tampering either is detectable.

A data scientist (Lin) imports `from agentxp.render import render_verdict`, builds a `ViewBundle` from her own DataFrames, and renders an HTML readout to a string. Her bundle has no chain, so the renderer respects `RenderStatus.UNVERIFIABLE` and stamps the receipt footer honestly. She cannot construct a `VERIFIED` render without supplying a chain to anchor against — the Pydantic validator on `Provenance` refuses.

### 1.6 Layering with the cleanup plan

This plan layers onto the cleanup's existing 6-wave structure. No new top-level waves; presentation deliverables fold into the existing waves per dependency:

- **Wave 0 (schema foundations)** grows by 8 tasks — the per-type VMs, `ChartData` schema_version 2, `BriefV3` power/curve/decision_rules additions, `ReadoutKind` enum, catalog event schemas, the `Sha256Hex` reuse, the `_VERDICT_MODIFIER` extension.
- **Wave 1 (SQL chokepoint)** grows by 2 tasks — `compute_n_required_curve` in `agentxp.stats.power`, `walk_tree` UNVERIFIABLE-on-null-input path.
- **Wave 2 (warehouse fixture)** grows by 3 tasks — seed extensions (PowerGridData, interim monitor snapshot, per-arm means/SEs), Pydantic validator on `Provenance`, cross-format equality matrix test scaffolding.
- **Wave 3 (inline dispatch + brief integrity)** grows by 3 tasks — `prepare_power_grid` at brief lock, per-readout-kind `build_provenance` discriminator, persist_render helper.
- **Wave 4 (atomic surface flip)** grows by 14 tasks — the four `distill_*` functions, the new adapters (`design_brief`, `mid_run`, `intent`), the chart primitive library, template restructures, library entry points, `/readout` rename + new CLI verbs, share-tail wiring at Stages 1/3/5-halt/8, catalog write paths.
- **Wave 5 (polish)** grows by 3 tasks — Module 10 curriculum extension teaching continuous-spine, the `agentxp prune --readouts` verb, the cross-experiment index regeneration.

Combined wave count stays 6. Combined task count grows from 50 to 83 (33 new tasks). Combined plan name will be `AGENTXP_V01_COMBINED_BUILD_PLAN.md` after Phase C synthesis.

---

## §2 Wave Structure (presentation-only summary; full combined table in Phase C)

| # | Cleanup theme | Presentation deliverables (additive) | New tasks | Ships |
|---|---|---|---|---|
| 0 | Schema + hygiene foundations | Per-type VMs, ChartData v2, BriefV3 power/curve/rules, ReadoutKind enum, catalog event schemas, _VERDICT_MODIFIER UNVERIFIABLE entry, brand tokens for incomplete stripe, Provenance validator | 8 | dark |
| 1 | SQL chokepoint + result_hash | compute_n_required_curve, walk_tree UNVERIFIABLE path | 2 | dark |
| 2 | Warehouse fixture + semantic models + metrics | E_F12345 seed PowerGridData + interim monitor snapshot + per-arm means/SEs; golden-file fixture scaffolding; cross-format equality matrix runner | 3 | dark |
| 3 | Inline dispatch + brief integrity | prepare_power_grid at brief lock; per-readout-kind build_provenance discriminator; persist_render helper | 3 | dark |
| 4 | **ATOMIC SURFACE FLIP** | 4 distill_* functions, 3 new adapters, 7 chart primitives, template restructures, 4 library entry points, /readout rename + agentxp readout / readouts CLI verbs, share-tail wiring at Stages 1/3/5-halt/8, catalog writer + reconciliation, cross-experiment index | 14 | flag flips |
| 5 | Gauntlet + trace.md + polish | Module 10 curriculum extension; agentxp prune --readouts verb; index regeneration | 3 | docs only |

---

## §3 Detailed Waves

Task IDs use the prefix `P` (presentation) to distinguish from cleanup tasks (`C`). When merged in Phase C, IDs renumber.

### §3.0 Wave 0 — Schema foundations (presentation additions, all dark)

#### P0.1 — `Sha256Hex` reuse in catalog schemas
- **File:** `agentxp/schemas/catalog.py` (new)
- **Spec:** Use the cleanup plan's `Sha256Hex = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]` type alias for `prev_catalog_entry_hash`, `source_chain_hash`, `source_artifact_sha256`, `output_content_hash` fields throughout the catalog event schemas.
- **Depends on:** Cleanup W0.1 (Sha256Hex landing).
- **Acceptance:** all catalog schema fields that should be hashes carry the pattern validator.

#### P0.2 — Per-type ViewModel schemas
- **Files:** `agentxp/render/viewmodel.py` extended with `IntentVM`, `DesignBriefVM`, `MidRunVM`; `ReportVM` renamed to `VerdictVM` with `ReportVM` kept as alias for one release.
- **Spec:** Each VM is its own `BaseModel` with `extra="forbid"` and `schema_version: Literal[1]`. Field shapes per the Round 2 plans:
 - `IntentVM`: experiment_id, experiment_name, user_intent_verbatim, inferred_primary_metric, inferred_arm_count, open_questions, teaching_line (Optional), generated_at, replay_command.
 - `DesignBriefVM`: experiment_id, experiment_name, hypothesis (Action/Metric/Direction/Magnitude/Mechanism), metrics (primary/secondary/guardrails), power_stats, power_curve, allocation, decision_rules, lock_teaching_line, generated_at, replay_command.
 - `MidRunVM`: exact schema in Thesis-keeper Round 2 §3, `extra="forbid"`, NO lift/CI/p-value/per-arm-magnitude fields.
 - `VerdictVM`: existing ReportVM extended with `frame_line`, `test_type_used` per row.
- **Depends on:** Cleanup W0.13 (BriefV3 schema work).
- **Acceptance:** schema closure test + extra="forbid" enforcement test for each VM; `len(<TypeVM>.model_fields) == expected` pin.

#### P0.3 — Per-type ViewBundle subtypes
- **File:** `agentxp/render/viewmodel.py`
- **Spec:** `IntentBundle`, `DesignBriefBundle`, `MidRunBundle`, `ViewBundle` (verdict, kept as the existing name). Each welds `vm: <TypeVM>` + `provenance: Provenance`. The existing `ViewBundle` becomes the verdict-specific one; the others are new.
- **Acceptance:** schema validation refuses constructing a bundle without provenance.

#### P0.4 — `ChartData` schema_version 2 (per-arm means + SEs)
- **File:** `agentxp/render/viewmodel.py` `ChartData` class.
- **Spec:** Bump `schema_version` to 2. Add `mean_arm_control`, `mean_arm_treatment`, `se_arm_control`, `se_arm_treatment` — all `Optional[float] = None`. v1 → v2 is additive; old fixtures still load.
- **Depends on:** P0.2.
- **Acceptance:** `distribution_overlap` chart omits cleanly when any of the four are None.

#### P0.5 — `BriefV3` extensions for power-grid and decision rules
- **File:** `agentxp/schemas/report.py` (or wherever cleanup W0.13 lands `BriefV3`).
- **Spec:** Add `power_stats: Optional[PowerStats]`, `power_curve: list[PowerCurvePointRecord]`, `allocation: dict[str, float]`, `decision_rules: list[DecisionRuleRecord]` per Orchestrator-pres Round 2 §6 literal Pydantic models.
- **Depends on:** Cleanup W0.13.
- **Acceptance:** v2 brief → v3 brief migration via `agentxp migrate-state` populates these fields as empty when migrating an existing brief; new briefs at lock time populate them via P3.1.

#### P0.6 — `ReadoutKind` enum + closure test
- **File:** `agentxp/render/readout_kind.py` (new).
- **Spec:** `class ReadoutKind(str, Enum): INTENT = "intent"; DESIGN_BRIEF = "design_brief"; MONITOR_CHECK = "monitor_check"; VERDICT = "verdict"; AUDIT = "audit"`. Closure test asserts `len(ReadoutKind) == 5`.
- **Acceptance:** closure test pinned.

#### P0.7 — Catalog event schemas
- **File:** `agentxp/schemas/catalog.py` (extends P0.1).
- **Spec:** Pydantic models for `RenderCompletedEvent`, `RenderFailedEvent`, `RenderSupersededEvent`, `RenderBriefDriftFlaggedEvent`, `PruneCompletedEvent` per Info-architect Round 2 §1. All inherit a `CommonFields` base with `prev_catalog_entry_hash: Sha256Hex`, `render_id: str` (ULID), `timestamp`, `agentxp_version`.
- **Depends on:** P0.1, P0.6.
- **Acceptance:** schema validation tests; closure on event_kind Literal.

#### P0.8 — `_VERDICT_MODIFIER["UNVERIFIABLE"] = "incomplete"` + brand tokens
- **Files:** `agentxp/render/adapters/html.py`, `agentxp/render/brand.py`, `agentxp/assets/design/components.css`.
- **Spec:** Add the 4th map entry per Orchestrator-pres Round 2 §5. Add brand tokens `--xp-incomplete-stripe-a` and `--xp-incomplete-stripe-b` per Editorial+viz Round 2 §4. Add `.xp-verdict-badge-incomplete` and `.xp-verdict-reason` CSS classes per Editorial+viz Round 2 §4.3.
- **Depends on:** Cleanup W0.11 (VerdictKind UNVERIFIABLE addition).
- **Acceptance:** golden HTML test fixture with UNVERIFIABLE verdict renders the stripe badge + the "the verdict tree could not complete" reason copy.

### §3.1 Wave 1 — SQL chokepoint additions (presentation)

#### P1.1 — `compute_n_required_curve` in `agentxp.stats.power`
- **File:** `agentxp/stats/power.py`
- **Spec:** `compute_n_required_curve(baseline: float, alpha: float, power: float, mde_grid: list[float]) -> list[PowerCurvePointRecord]` — pure deterministic Python over the existing per-point `n_required` formula. Returns the list of (mde_relative_pct, n_required_per_arm) tuples.
- **Acceptance:** unit test on the 9-point grid for E_F12345 matches the literal values in Orchestrator-pres Round 2 §1.1.

#### P1.2 — `walk_tree` UNVERIFIABLE-on-null-input path
- **File:** `agentxp/interpret/tree.py`
- **Spec:** Audit B5 finding — when any tree step input is null, return `VerdictKind.UNVERIFIABLE` for that step instead of falling through to SHIP-default. Per cleanup W1.6.
- **Depends on:** Cleanup W0.11.
- **Acceptance:** unit test with null `late_ratio` returns UNVERIFIABLE, not SHIP.

### §3.2 Wave 2 — Warehouse fixture extensions (presentation)

#### P2.1 — `E_F12345` seed adds `PowerGridData`
- **File:** `agentxp/fixtures/generate_demo_warehouse.py`
- **Spec:** When generating the canonical brief for E_F12345, emit `power_stats`, `power_curve`, `allocation`, `decision_rules` per Orchestrator-pres Round 2 §1.1. Power-curve points are computed via `compute_n_required_curve` (P1.1) so the seed and the chart stay in sync.
- **Depends on:** P0.5, P1.1, Cleanup W2.1.
- **Acceptance:** generating the fixture twice produces byte-identical YAML; the design point at 22% MDE lands on the curve.

#### P2.2 — Interim `monitor.50pct.snapshot.yaml` for E_F12345
- **File:** `agentxp/fixtures/generate_demo_warehouse.py`
- **Spec:** Add a Stage-5-interim snapshot per Orchestrator-pres Round 2 §1.2. Literal values: n_collected=3024, days_running=7, srm clean, guardrails not firing, eligible_for_stop=False.
- **Depends on:** Cleanup W2.1.
- **Acceptance:** snapshot file present; `distill_mid_run(snapshot, brief, state)` produces a MidRunVM with the literal expected fields.

#### P2.3 — Per-arm means and SEs in `MetricResult` + `ChartData`
- **Files:** `agentxp/fixtures/generate_demo_warehouse.py`, the analyzer-output projection that builds `MetricResult`.
- **Spec:** Populate `mean_arm_control=0.10467`, `mean_arm_treatment=0.12800`, `se_arm_control=0.00560`, `se_arm_treatment=0.00610` for E_F12345's primary metric per Orchestrator-pres Round 2 §1.3. `ChartData` gets these via the distill projection.
- **Depends on:** P0.4, Cleanup W2.1.
- **Acceptance:** `distribution_overlap` chart rendered against E_F12345 produces a stable golden SVG.

#### P2.4 — Cross-format equality test matrix scaffolding
- **File:** `tests/render/test_cross_format_equality.py` (extended), `tests/golden/canonical_strs/` (new directory).
- **Spec:** Per Orchestrator-pres Round 2 §2 — parametrize over `seeds × readout_kinds × audiences × formats`. Golden manifest format per §2.3. Editorial+viz authors the literal golden manifests in Wave 4.
- **Depends on:** P0.2.
- **Acceptance:** test runs (empty matrix is OK at this wave); fails loud when a manifest references a non-existent format.

### §3.3 Wave 3 — Inline dispatch + brief integrity (presentation)

#### P3.1 — `prepare_power_grid(brief)` at brief lock
- **File:** `agentxp/orchestrator/store.py` (extend `_commit_stage` for `brief_drafted` stage).
- **Spec:** When committing Stage 3 (brief lock), compute the power grid via `compute_n_required_curve` (P1.1) and persist it into `experiment.yaml`'s `power_curve` field. PowerGridData is committed-at-lock, never re-derived at readout time.
- **Depends on:** P0.5, P1.1.
- **Acceptance:** post-lock `experiment.yaml` always carries a populated `power_curve`; rerunning `prepare_power_grid` on the same brief produces identical output.

#### P3.2 — Per-readout-kind `build_provenance` discriminator
- **File:** `agentxp/render/provenance.py`
- **Spec:** Per Thesis-keeper Round 2 §4 — single function with `readout_kind: ReadoutKind` discriminator parameter. Per-kind precedence chains literally per §4.1–§4.5. Cascade rule per §2.1.
- **Depends on:** P0.6, P0.2, Cleanup W3.4 (three-part brief integrity lock — supplies the brief_chain_hash binding).
- **Acceptance:** unit tests per kind: each precedence chain verified against a constructed fixture exhibiting each resolution path (VERIFIED, DRAFT_UNVERIFIED, UNVERIFIABLE).

#### P3.3 — `persist_render` helper
- **File:** `agentxp/render/persistence.py` (new).
- **Spec:** Exact signature per Orchestrator-pres Round 2 §4. Writes content + provenance sidecar atomically; appends `render.completed` event to `catalog.jsonl` with hash chain link; updates `latest/` pointer; regenerates `catalog.json` derived cache.
- **Depends on:** P0.7.
- **Acceptance:** integration test: call twice with same source hash → second call raises `ReadoutUpToDate` unless `force=True`; chain validates after multiple writes.

### §3.4 Wave 4 — Atomic surface flip (presentation deliverables)

All 14 tasks ship behind `SURFACE_V01_ENABLED` until the wave's atomic flip. This is the bulk of the presentation work.

#### P4.1 — Four pure `distill_*` functions
- **Files:** `agentxp/render/distill.py` (extended) — rename existing `distill` to `distill_verdict`; add `distill_intent`, `distill_design_brief`, `distill_mid_run`.
- **Spec:**
 - `distill_intent(state_yaml, experiment_yaml) -> IntentVM` — pure.
 - `distill_design_brief(brief, data_plan, power_grid) -> DesignBriefVM` — pure.
 - `distill_mid_run(monitor_snapshot, brief, state) -> MidRunVM` — pure. **Never** takes analyzer outputs. Signature is the peek wall.
 - `distill_verdict(report) -> VerdictVM` — existing `distill` renamed.
- **Depends on:** P0.2.
- **Acceptance:** Thesis-keeper §6.2 integration test — signature introspection confirms forbidden parameter names absent from `distill_mid_run`.

#### P4.2 — Seven chart primitives at viewBox 1020×H
- **File:** `agentxp/render/charts.py` (replaced/extended).
- **Spec:** Per Editorial+viz Round 1 §1. Each primitive:
 - `control_vs_treatment_bars(rate_c, rate_t, ci_lower, ci_upper, ...)` — side-by-side bars on shared axis with CI bracket nested.
 - `distribution_overlap(mean_c, se_c, mean_t, se_t, ...)` — two normal density curves with overlap region shaded.
 - `guardrail_threshold(ci_lower, ci_upper, point, threshold_pct, favorable_direction, ...)` — CI bracket with harm-threshold dashed line + tinted floor zone.
 - `power_design_curve(curve_points, design_point, ...)` — sample-size-vs-MDE curve with design point marked.
 - `arm_allocation_bar(allocations, ...)` — split visualization.
 - `srm_observed_bar(n_c, n_t, chi_sq, p_value, ...)` — replaces broken `srm_split`, axis labels in a row BELOW the plot (fixes "95% CCI" bug pattern at the geometry level).
 - `metric_callout_strip(stats: list[CalloutStat])` — CSS primitive, the 3-stat horizontal strip with big serif numerals (RELATIVE LIFT / P-VALUE / 95% CI).
- **Depends on:** P0.4, P2.3, Cleanup W2.8.
- **Acceptance:** golden SVG diff per primitive × theme × E_F12345 fixture (Editorial+viz authors the goldens; the test runs them).

#### P4.3 — Existing chart fixes (lift_bar, ci_interval)
- **File:** `agentxp/render/charts.py`
- **Spec:** Fix `lift_bar` to include axis values + MDE marker + scale (per Editorial+viz §1). Fix `ci_interval` to put axis labels in a dedicated row BELOW the plot (eliminates the "95% CI" → "95% CCI" overlap).
- **Depends on:** P4.2.
- **Acceptance:** golden SVG diff catches no overlap at the chart's label-row position.

#### P4.4 — `html.py` adapter — section-per-question restructure
- **Files:** `agentxp/render/adapters/html.py`, `templates/experiment-report.html.j2` (restructured), `templates/partials/xp-verdict-hero.html.j2` (new), `templates/partials/xp-srm-section.html.j2` (new), `templates/partials/xp-primary-section.html.j2` (new), `templates/partials/xp-guardrail-section.html.j2` (new, repeated per-guardrail), `templates/partials/xp-receipts-footer.html.j2` (existing, kept).
- **Spec:** Per Editorial+viz Round 1 §2. Verdict at TOP (Shane's Q1). Sections in order: Verdict → SRM → Primary → Guardrails (one section per guardrail) → Receipts.
- **Depends on:** P4.1, P4.2.
- **Acceptance:** golden HTML diff for E_F12345 verdict readout × exec audience × editorial-light theme.

#### P4.5 — New `design_brief.py` adapter
- **Files:** `agentxp/render/adapters/design_brief.py` (new), `templates/design-brief.html.j2` (new).
- **Spec:** Per Editorial+viz Round 1 §3. Sections: Headline + eyebrow → Hypothesis block → Metrics block (Primary/Secondary/Guardrail rows) → Power analysis callout strip + power curve chart → Decision rules table with `lock_teaching_line` embedded.
- **Depends on:** P0.2, P0.5, P4.2.
- **Acceptance:** golden HTML diff for E_F12345 design-brief readout × exec audience.

#### P4.6 — New `mid_run.py` adapter (peek-safe by construction)
- **Files:** `agentxp/render/adapters/mid_run.py` (new), `templates/mid-run.html.j2` (new).
- **Spec:** Per Editorial+viz Round 2 §1. Four blocks: header + receipts row → progress rail → status grid (srm_status + guardrails_firing + eligible_for_stop pills) → teaching strip with `why_no_estimates_one_line` verbatim. **NO charts. NO magnitudes. NO metric names.**
- **Depends on:** P0.2.
- **Acceptance:** Thesis-keeper §6.3 property test — rendered bytes contain no lift-shaped pattern.

#### P4.7 — New `intent.py` adapter
- **Files:** `agentxp/render/adapters/intent.py` (new), `templates/intent.html.j2` (new), `templates/intent.md.j2` (new for the inline-chat share-tail body).
- **Spec:** Per Editorial+viz Round 2 §5. Sections: Headline + eyebrow → Hypothesis shape block → Open questions list → Teaching strip (optional) → What comes next → Receipts footer. No charts.
- **Depends on:** P0.2.
- **Acceptance:** golden HTML + MD diffs against the IntentVM constructed from E_F12345's Stage 1 commit.

#### P4.8 — `card.py` adapter rebuild
- **Files:** `agentxp/render/adapters/card.py` (replaced), `templates/social-card.html.j2` (restructured).
- **Spec:** Card adapter becomes the VERDICT readout in portrait 1200×1500. Verdict-as-hero in upper third (Shane's Q1 for card). Sections: Header → `.xp-verdict-hero` partial (shared with html.py) → callout strip → control_vs_treatment_bars → optional distribution_overlap → receipts footer. The card has a real job per Editorial+viz Round 1 §5.
- **Depends on:** P4.2, P4.4 (verdict-hero partial).
- **Acceptance:** golden HTML diff; 1200×1500 dimensions preserved; verdict hero crops within LinkedIn screenshot zone.

#### P4.9 — Four library entry points
- **File:** `agentxp/render/__init__.py`
- **Spec:** Per Journey-designer Round 2 §6.1 literal signatures. `render_intent_card / render_design_brief / render_monitor_check / render_verdict`. Each accepts `source: str | <Type>Bundle` and renders pure. Returns string for text formats, bytes for binary (card PNG/PDF).
- **Depends on:** P4.5, P4.6, P4.7, P4.8 (the adapters they wrap).
- **Acceptance:** Lin's hand-built bundle test from Journey-designer Round 2 §6.2 passes; Pydantic validator on Provenance refuses constructing VERIFIED without chain hashes.

#### P4.10 — `/readout` slash command rename + `agentxp readout` CLI verb
- **Files:** `.claude/commands/readout.md` (new, replaces `share-experiment.md`), `agentxp/cli/readout.py` (new).
- **Spec:** Per Journey-designer Round 2 §3 literal `/help` text. Arguments: `<exp_id> [--type] [--audience] [--format] [--out] [--theme] [--force]`. `agentxp report` is aliased to `agentxp readout --type verdict` with `DeprecationWarning` for one minor version.
- **Depends on:** P4.9.
- **Acceptance:** integration test — `/readout exp_E_F12345 --type design_brief` produces the expected HTML; old `agentxp report` invocation still works with warning.

#### P4.11 — `agentxp readouts <id>` (catalog view) + `agentxp readouts --index` (cross-experiment)
- **Files:** `agentxp/cli/readouts.py` (new).
- **Spec:** `agentxp readouts <id>` reads the experiment's `catalog.json`, displays sorted table (type / audience / format / status / generated_at / brief_drift / superseded_by). `agentxp readouts --index` regenerates and displays `experiments/readouts-index.html` per Info-architect Round 2 §3.
- **Depends on:** P3.3, P4.10.
- **Acceptance:** `agentxp readouts exp_E_F12345` after rendering all four types lists all readouts with correct effective statuses.

#### P4.12 — Share-tail wiring at Stage 1
- **Files:** `.claude/skills/experiment/SKILL.md` extension; `.claude/skills/experiment/STAGES.md` extension for Stage 1.
- **Spec:** Per Journey-designer §1 — after `stage.committed(stage="intent_captured")`, the orchestrator (Claude in the skill) calls `render_intent_card(exp_id, format="md", audience="operator")` and displays the result inline + calls `persist_render` to land it. Interaction mode: infer & proceed.
- **Depends on:** P4.9.
- **Acceptance:** end-to-end test — `/experiment` walk from Stage 0 to Stage 1 commit produces an intent readout in chat AND on disk.

#### P4.13 — Share-tail wiring at Stage 3 + Stage 8
- **Files:** `.claude/skills/experiment/SKILL.md` + STAGES.md for Stages 3 and 8.
- **Spec:** Stage 3 — after `stage.committed(stage="brief_drafted")`, render design_brief inline + on-disk (infer & proceed). Stage 8 — after `stage.committed(stage="readout")`, render verdict inline + on-disk, follow up with single question "public card too? enter to skip" (per Journey-designer §2.1).
- **Depends on:** P4.9, P4.12.
- **Acceptance:** end-to-end walk from Stage 0 to Stage 8 produces inline + on-disk artifacts at each safe commit.

#### P4.14 — Share-tail wiring at Stage 5 halt
- **Files:** `.claude/skills/experiment/SKILL.md` + STAGES.md for Stage 5.
- **Spec:** ONLY on `gate.opened(kind="srm_override" | "guardrail_breach" | "exposure_stale")` — render monitor_check (operator audience, md format). On clean Stage 5 commit (no gate), silent.
- **Depends on:** P4.9.
- **Acceptance:** test fixtures: clean monitor commit → no readout; SRM-tripped commit → halt readout written.

### §3.5 Wave 5 — Polish (presentation deliverables)

#### P5.1 — Module 10 curriculum extension (continuous-spine)
- **File:** `docs/learn/10_presentation.md` (extended).
- **Spec:** Add a new sub-section after the existing "Walkthrough" — "The continuous share-out spine: stage-by-stage readouts." Walks through the five readout types, the four share-tail moments, the peek-prevention-by-schema discipline, the catalog hash chain (Invariant 7). Preserves existing axioms (pure-renderer, polish-and-proof-same-object, three-state RenderStatus) and extends them.
- **Depends on:** Wave 4 complete.
- **Acceptance:** the module reads as a continuation of the existing Module 10, not a replacement.

#### P5.2 — `agentxp prune --readouts` verb
- **File:** `agentxp/cli/prune.py` (extends existing prune verb from cleanup W0.16).
- **Spec:** Per Info-architect Round 2 §4 literal argument shape. Filters AND; default `--keep-latest`; `--dry-run` mode; refusal conditions per §4.3; exit codes per §4.4. Appends `prune.completed` event to each affected catalog.
- **Depends on:** P0.7, Cleanup W0.16.
- **Acceptance:** end-to-end test — render 3 verdict slots, prune `--older-than 0d --keep-latest`, 2 slots deleted + `prune.completed` events appended to each catalog.

#### P5.3 — Cross-experiment readouts-index regeneration
- **File:** `agentxp/cli/readouts.py` (extends P4.11).
- **Spec:** `agentxp readouts --index` walks every `experiments/*/readouts/catalog.json`, composes `ReadoutsIndex` per Info-architect Round 2 §3, writes both `experiments/readouts-index.html` and `experiments/readouts-index.json`. Includes generated_at timestamp.
- **Depends on:** P4.11.
- **Acceptance:** after rendering for 3 experiments, `agentxp readouts --index` produces an HTML page listing all three with verdict badges + type chips + worst-case render status.

---

## §4 Dependency Graph

```
Wave 0 (schemas)
  P0.1 Sha256Hex ─┐
  P0.2 VMs ───────┼─── P0.3 Bundles ──┐
  P0.6 ReadoutKind┘                   │
  P0.4 ChartData v2 ──────────────────┤
  P0.5 BriefV3 extensions ────────────┤
  P0.7 Catalog events ────────────────┤
  P0.8 _VERDICT_MODIFIER UNVERIFIABLE ┘
                                      │
Wave 1 (SQL chokepoint)               │
  P1.1 compute_n_required_curve ──────┤
  P1.2 walk_tree UNVERIFIABLE path ───┤
                                      │
Wave 2 (warehouse fixture)            │
  P2.1 PowerGridData seed ────────────┤
  P2.2 Interim monitor snapshot ──────┤
  P2.3 Per-arm means/SEs seed ────────┤
  P2.4 Cross-format matrix scaffold ──┤
                                      │
Wave 3 (inline dispatch + brief)      │
  P3.1 prepare_power_grid ────────────┤
  P3.2 per-kind build_provenance ─────┤
  P3.3 persist_render ────────────────┤
                                      │
Wave 4 (ATOMIC SURFACE FLIP — all behind SURFACE_V01_ENABLED until atomic flip)
  P4.1 distill_* functions ───────────┤
  P4.2 7 chart primitives ────────────┼─── P4.3 chart fixes ─┐
                                      │                      │
  P4.4 html.py restructure ───────────┤                      │
  P4.5 design_brief.py adapter ───────┤                      │
  P4.6 mid_run.py adapter (peek-safe) ┤                      │
  P4.7 intent.py adapter ─────────────┤                      │
  P4.8 card.py rebuild ───────────────┤                      │
  P4.9 library entry points ──────────┤                      │
  P4.10 /readout rename + CLI ────────┤                      │
  P4.11 readouts CLI + index ─────────┤                      │
  P4.12 Stage 1 share-tail ───────────┤                      │
  P4.13 Stages 3+8 share-tails ───────┤                      │
  P4.14 Stage 5 halt share-tail ──────┘                      │
                                                              │
Wave 5 (polish)                                               │
  P5.1 Module 10 curriculum extension ────────────────────────┤
  P5.2 agentxp prune --readouts ──────────────────────────────┤
  P5.3 cross-experiment index regen ──────────────────────────┘

The atomic surface flip in Wave 4 ships behind SURFACE_V01_ENABLED (cleanup W0.2).
Waves 0–3 land "dark" — schemas + helpers + persist_render exist but no user-facing surface invokes them until Wave 4's flag flip.
```

---

## §5 Files Changed Summary

| Wave | File | Change | Description |
|------|------|--------|-------------|
| 0 | `agentxp/schemas/catalog.py` | new | Catalog event schemas (P0.7) |
| 0 | `agentxp/render/viewmodel.py` | modified | Per-type VMs (P0.2), Bundle subtypes (P0.3), ChartData v2 (P0.4) |
| 0 | `agentxp/render/readout_kind.py` | new | ReadoutKind enum (P0.6) |
| 0 | `agentxp/render/adapters/html.py` | modified | `_VERDICT_MODIFIER` UNVERIFIABLE entry (P0.8) |
| 0 | `agentxp/render/brand.py` | modified | New tokens for stripe pattern (P0.8) |
| 0 | `agentxp/assets/design/components.css` | modified | `.xp-verdict-badge-incomplete` + `.xp-verdict-reason` (P0.8) |
| 0 | `agentxp/schemas/report.py` | modified | BriefV3 extensions (P0.5); MetricResult per-arm fields (P0.5 layered) |
| 1 | `agentxp/stats/power.py` | modified | `compute_n_required_curve` (P1.1) |
| 1 | `agentxp/interpret/tree.py` | modified | UNVERIFIABLE-on-null path (P1.2) |
| 2 | `agentxp/fixtures/generate_demo_warehouse.py` | modified | PowerGridData (P2.1), interim monitor snapshot (P2.2), per-arm means/SEs (P2.3) |
| 2 | `tests/render/test_cross_format_equality.py` | modified | Matrix scaffolding (P2.4) |
| 2 | `tests/golden/canonical_strs/` | new dir | Golden manifests (P2.4) |
| 3 | `agentxp/orchestrator/store.py` | modified | `prepare_power_grid` at brief lock (P3.1) |
| 3 | `agentxp/render/provenance.py` | modified | Per-readout-kind `build_provenance` discriminator + cascade (P3.2) |
| 3 | `agentxp/render/persistence.py` | new | `persist_render` helper (P3.3) |
| 4 | `agentxp/render/distill.py` | modified | Rename `distill` → `distill_verdict`; add 3 sibling distill functions (P4.1) |
| 4 | `agentxp/render/charts.py` | replaced | 7 new primitives + 2 fixes (P4.2, P4.3) |
| 4 | `agentxp/render/adapters/html.py` | modified | Section-per-question restructure (P4.4) |
| 4 | `agentxp/render/adapters/design_brief.py` | new | (P4.5) |
| 4 | `agentxp/render/adapters/mid_run.py` | new | (P4.6) |
| 4 | `agentxp/render/adapters/intent.py` | new | (P4.7) |
| 4 | `agentxp/render/adapters/card.py` | replaced | Verdict-as-hero rebuild (P4.8) |
| 4 | `templates/experiment-report.html.j2` | replaced | Sectioned (P4.4) |
| 4 | `templates/design-brief.html.j2` | new | (P4.5) |
| 4 | `templates/mid-run.html.j2` | new | (P4.6) |
| 4 | `templates/intent.html.j2` | new | (P4.7) |
| 4 | `templates/intent.md.j2` | new | Inline-chat share-tail body (P4.7) |
| 4 | `templates/social-card.html.j2` | replaced | Verdict-as-hero (P4.8) |
| 4 | `templates/partials/xp-verdict-hero.html.j2` | new | Shared across html + card (P4.4, P4.8) |
| 4 | `templates/partials/xp-srm-section.html.j2` | new | (P4.4) |
| 4 | `templates/partials/xp-primary-section.html.j2` | new | (P4.4) |
| 4 | `templates/partials/xp-guardrail-section.html.j2` | new | (P4.4) |
| 4 | `agentxp/render/__init__.py` | modified | 4 library entry points (P4.9) |
| 4 | `.claude/commands/readout.md` | new | `/readout` slash command (P4.10) |
| 4 | `.claude/commands/share-experiment.md` | deleted | Renamed to `/readout` |
| 4 | `agentxp/cli/readout.py` | new | `agentxp readout` CLI verb (P4.10) |
| 4 | `agentxp/cli/report.py` | modified | Alias to `readout --type verdict` with DeprecationWarning |
| 4 | `agentxp/cli/readouts.py` | new | `agentxp readouts` + `--index` (P4.11) |
| 4 | `.claude/skills/experiment/SKILL.md` | modified | Share-tail wiring at Stages 1/3/5-halt/8 (P4.12–P4.14) |
| 4 | `.claude/skills/experiment/STAGES.md` | modified | Per-stage share-tail prose |
| 5 | `docs/learn/10_presentation.md` | modified | Continuous-spine sub-section (P5.1) |
| 5 | `agentxp/cli/prune.py` | modified | `--readouts` extension (P5.2) |

---

## §6 Open Questions

All conflicts resolved through Phases B.1–B.2 + Round 2 revisions + Shane's two resolutions. The plan is execution-ready.

Two items deferred to v0.2 (out of scope for this cleanup, flagged here so they don't get lost):

1. **Bundle.builder() convenience classes** for Lin's notebook path (Journey-designer Round 2 §6.3). The raw Pydantic constructors are sufficient for v0.1.
2. **Slot tab-completion** in `/readout <id> --type design_brief --slot <ts>` (Journey-designer Round 2 §4.2). The default-to-latest behavior covers the common case.

Two items flagged in Round 2 as judgment calls that synthesis lands per the recommendation, but Shane can override later:

1. **Brief-drift cascade status: DRAFT_UNVERIFIED** (Thesis-keeper Round 2 §8.1). The argument FOR UNVERIFIABLE was less compelling; the hash comparison is concrete.
2. **Pruning policy default: `--keep-latest`** (Info-architect Round 2 §8.1). Stricter default would make the verb feel useless.

---

End of presentation master plan. Phase C merges this with `AGENTXP_V01_CLEANUP_MASTER_PLAN.md` into `AGENTXP_V01_COMBINED_BUILD_PLAN.md`.
