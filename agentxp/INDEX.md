# agentxp/INDEX.md — Python helper catalog

Single source of truth for what skills can import. Adding a new helper:
land it in `agentxp/X.py`, register the entry here, then reference from
the relevant skill.

Skills MUST cite functions through this index. Closure test in
`tests/docs/test_claude_md.py` asserts that every function name appearing
in a `.claude/skills/<name>/SKILL.md` is registered here.

---

## Discipline modules (do not reimplement)

These are the load-bearing modules. The orchestrator wraps these as tools
and never duplicates their logic. R4 (numbers from whitelist only), R3
(verdict from tree only), R8 (confidence label from `map_confidence` only).

### `agentxp.stats.*` — statistical truth

| Function | Module | Signature (abbreviated) | Used by skill |
|---|---|---|---|
| `srm_check` | `agentxp.stats.srm` | `(observed_counts, expected_ratios, *, threshold=0.0005) -> SrmResult` | analyze (R2 — first read) |
| `welch_test` | `agentxp.stats.ab_tests` | `(control: Series, treatment: Series) -> TestResult` | analyze (metric type=mean) |
| `proportion_test` | `agentxp.stats.ab_tests` | `(c_success, c_n, t_success, t_n) -> TestResult` | analyze (metric type=proportion) |
| `ratio_metric_test` | `agentxp.stats.ab_tests` | `(num_c, den_c, num_t, den_t) -> TestResult` | analyze (metric type=ratio) |
| `guardrail_test` | `agentxp.stats.guardrails` | `(observed, direction, nim_relative) -> GuardrailResult` | analyze (per guardrail) |
| `cohens_d` | `agentxp.stats.effect_size` | `(control, treatment) -> EffectSizeResult` | analyze (continuous effect size) |
| `cohens_h` | `agentxp.stats.effect_size` | `(p1, p2) -> EffectSizeResult` | analyze (proportion effect size) |
| `relative_lift` | `agentxp.stats.effect_size` | `(baseline, observed) -> float` | analyze (display) |
| `detectable_effect` | `agentxp.stats.power` | `(n, baseline, power=0.8, alpha=0.05) -> float` | design (power calc), analyze (post-hoc MDE) |
| `adjust_pvalues` | `agentxp.stats.corrections` | `(pvalues, *, method='holm') -> list[float]` | analyze (multi-segment) |
| `winsorize` | `agentxp.stats.ab_tests` | `(series, *, bounds=(0.01, 0.99)) -> Series` | analyze (heavy-tail cleanup) |
| `compute_late_ratio` | `agentxp.interpret.tree` | `(early, late) -> Optional[float]` | analyze (novelty diagnostic) |

### `agentxp.interpret.tree` — the 8-step verdict tree

| Function | Signature | Notes |
|---|---|---|
| `walk_tree` | `(inputs: TreeInput) -> TreeResult` | The only path to a verdict (R3). Returns `Verdict` (9 values including `UNVERIFIABLE`) + `terminal_step`. |
| `compute_late_ratio` | `(early: float, late: float) -> Optional[float]` | M106 novelty signal. |

### `agentxp.interpret.confidence` — seven confidence labels

| Function | Signature | Notes |
|---|---|---|
| `map_confidence` | `(ci_low, ci_high, orientation) -> ConfidenceLabel` | The only path to a label (R8). Seven values. |

### `agentxp.sql.safety` — 6-layer SQL pipeline

| Function | Signature | Notes |
|---|---|---|
| `run_pipeline` | `(sql, dialect, purpose, *, mode: SafetyMode, ...) -> SafetyResult` | **`mode` is required (R11).** `mode="design"` activates Layer 3d outcome-column reject. |

### `agentxp.schemas.bundles` — R10 enforcement

| Symbol | Notes |
|---|---|
| `BUNDLE_SCHEMAS` | dict: role → Pydantic bundle schema. 5 entries. |
| `BLINDNESS_MANIFEST` | dict: role → forbidden field names. Closure-tested. |
| `UnderstanderBundle, DesignerBundle, CriticBundle, SqlSpecialistBundle, AnalystNarratorBundle` | The five bundle types. |

### `agentxp.schemas.brief_seal` — three-part integrity lock (R11)

| Function | Signature | Notes |
|---|---|---|
| `seal_brief` | `(*, brief_content, design_chain_path, metric_paths, expected_shape, sealed_by, agentxp_version, sealed_at=None) -> SealedBrief` | Keyword-only. No `--force`. |
| `verify_brief_seal` | `(*, sealed, design_chain_path, metric_paths) -> VerifyResult` | Never raises; returns structured result. |
| `verify_or_raise` | `(*, sealed, design_chain_path, metric_paths) -> None` | Raises `BriefSealMismatch` on fail. The CLI entry point. |

---

## Workflow modules (skill helpers)

These are the Python entry points that skills call. One module per verb.

### `agentxp.workflows.design`

| Function | Signature | Used by |
|---|---|---|
| `allocate_experiment` | `(project_root: Path, *, data_path=None, exp_id=None) -> Path` | `design` skill step 1 |
| `record_intent` | `(exp_dir: Path, intent_text: str, captured_by: str) -> Path` | `design` skill step 2 |

### `agentxp.workflows.analyze`

| Function | Signature | Used by |
|---|---|---|
| `verify_and_open` | `(brief_path: Path, project_root: Path) -> SealedBrief` | `analyze` skill step 1 — raises `BriefSealMismatch` on fail |

### `agentxp.workflows.audit`

| Function | Signature | Used by |
|---|---|---|
| `walk_log` | `(exp_dir: Path) -> Iterator[LogEntry]` | `audit` skill |
| `diff_logs` | `(exp_a: Path, exp_b: Path) -> Iterator[Diff]` | `audit` skill `--diff` |

### `agentxp.workflows.readouts`

| Function | Signature | Used by |
|---|---|---|
| `list_catalog` | `(exp_dir: Path) -> list[CatalogEntry]` | `readouts` skill |
| `build_index` | (re-exported from `agentxp.render.catalog`) | `readouts` skill `--index` |

### `agentxp.workflows.resume`

| Function | Signature | Used by |
|---|---|---|
| `list_in_flight` | `(project_root: Path) -> list[ExperimentSnapshot]` | first-turn behavior (CLAUDE.md §8) |
| `classify` | `(snapshot: ExperimentSnapshot) -> ResumeState` | first-turn behavior |

NOTE: `resume` is NOT a slash command (conflicts with Claude Code's built-in `/resume`). The helper exists for first-turn behavior + `/design --exp-id` continuation.

### `agentxp.workflows.connect`

| Function | Signature | Used by |
|---|---|---|
| `run_wizard` | `(dialect: str, *, interactive=True) -> Path` | `connect-data` skill |

---

## Orchestration modules

### `agentxp.orchestrator.bundle_assembler`

| Function | Signature | Notes |
|---|---|---|
| `assemble` | `(role: str, sources: dict) -> AssembledBundle` | R10 enforcement: rejects fields outside the role's BundleSchema. |
| `assert_blindness_manifest_holds` | `() -> None` | Defense-in-depth startup check. |

### `agentxp.orchestrator.loop`

| Function | Signature | Notes |
|---|---|---|
| `dispatch_specialist` | `(*, role, sources, project_root, llm_caller=...) -> dict` | Validates bundle, calls LLM with role prompt + bundle. |
| `dispatch_critic` | `(*, artifact_ref, artifact_payload, claimed_scope, cited_inputs, judging_mode, project_root, llm_caller=...) -> dict` | Blind critic dispatch (R6). |
| `require_critic_pass` | `(*, judgment: dict) -> None` | Raises `ToolRefusal` on block, no-op on warn. |
| `design_verb_initial_snapshot` | `(exp_dir: Path) -> VerbContext` | Constructs VerbContext for design CLI entry. |
| `analyze_verb_initial_snapshot` | `(*, exp_dir, sealed_brief_path) -> VerbContext` | Same for analyze. |

### `agentxp.orchestrator.tools`

| Function | Signature | Notes |
|---|---|---|
| `read_experiment_dir` | `(exp_dir: Path) -> ExperimentSnapshot` | Disk → state, no mutation. |
| `probe_data` | `(sql, *, mode: SafetyMode, dialect='duckdb', purpose='shape_probe', semantic_models=None) -> SafetyResult` | Wrapper for `run_pipeline`. |
| `decision_tree` | `(tree_input: TreeInput) -> TreeResult` | Wrapper for `walk_tree`. |
| `map_confidence` | `(ci_low, ci_high, orientation) -> ConfidenceLabel` | Wrapper. |
| `seal_brief_tool` | `(*, brief_content, design_chain_path, metric_paths, expected_shape, sealed_by, agentxp_version) -> SealedBrief` | Wrapper. |
| `verify_brief_seal_tool` | `(*, sealed, design_chain_path, metric_paths) -> VerifyResult` | Wrapper. |
| `render_share_tail` | `(*, exp_dir, experiment_id, readout_type, vm, vm_sha256, provenance_render_status, audience='exec', fmt='md', entry_id=None, timestamp=None) -> Path` | distill + catalog + write. |
| `commit_artifact` | `(*, exp_dir, artifact_name, content, log_entry, git_message=None) -> str` | Atomic file + log.md + git commit. Returns SHA. |

---

## Render modules

### `agentxp.render.distill` — pure projection (no I/O, no clock)

| Function | Signature | Produces |
|---|---|---|
| `distill_intent` | `(*, experiment_id, intent_text, captured_at, captured_by) -> IntentVM` | Intent share-tail VM |
| `distill_design_brief` | `(*, experiment_id, sealed_brief_payload, integrity_lock) -> DesignBriefVM` | Design-brief share-tail VM |
| `distill_mid_run` | `(*, experiment_id, halt_reason, halt_summary_text, triggered_at, elapsed_text, suggested_resolutions, srm_chi2=None, srm_threshold=None) -> MidRunVM` | Monitor-halt share-tail VM. **Signature does NOT accept analyzer outputs (R10 peek-prevention).** |
| `distill_verdict` | `(report: Report) -> VerdictVM` | Verdict share-tail VM |
| `distill` | `(report: Report) -> ReportVM` | Final report VM |
| `distill_index` | `(rows: list[IndexRowVM]) -> IndexVM` | Cross-experiment index |

### `agentxp.render.catalog` — hash-chained ledger

| Function | Signature | Notes |
|---|---|---|
| `catalog_append` | `(*, catalog_path, experiment_id, entry_id, payload, timestamp=None) -> CatalogEntry` | One JSONL row, prev-hash chained. |
| `validate_catalog` | `(catalog_path: Path) -> None` | Raises `CatalogChainBreak` on first break. |
| `build_index` | `(project_root: Path) -> list[CatalogIndexRow]` | Worst-case status per experiment. |

### `agentxp.render.viewmodel` — Pydantic VMs

`IntentVM`, `DesignBriefVM`, `MidRunVM`, `VerdictVM` (=`ReportVM`), `ReportVM`, `ViewBundle`. All `extra="forbid"`. `MidRunVM` lacks peek-revealing fields (closure-tested via `_MID_RUN_FORBIDDEN_FIELDS`).

### `agentxp.render.charts` — SVG primitives at viewBox 1020×H

Existing 4: `lift_bar`, `ci_interval`, `srm_split`, `power_curve`. Pending 3 (T42 deferred): `arm_allocation_bar`, `srm_observed_bar`, `metric_callout_strip`.

### `agentxp.render.voice_audit` — banned-phrase ruleset

Pure scan. Used by readout commits + by `tests/smoke/test_voice_ci_suite.py` + by `tests/docs/test_claude_md.py`.

---

## Schema modules

### `agentxp.schemas.experiment`

| Symbol | Notes |
|---|---|
| `ExperimentStatus` | v0.1 carryover; v2 verbs terminate on artifact presence, not enum transitions. |
| Other models | hypothesis, brief, data plan fields. |

### `agentxp.schemas.data_plan`

`DataPlanV2`, `SourceType` (8-value enum: file + 7 warehouse adapters).

### `agentxp.schemas.report`

`Verdict` (re-exported from `agentxp.interpret.tree`), `ConfidenceLabel`, `NoShipReasonCode`, `AuditPaths`, `MetricResult`, `SegmentResult`, `EdgeCaseFlag`, `DiagnosticGate`, `Report`. R7 enforced via required `audit_paths`.

### `agentxp.schemas.state`

What survives v2: `SrmOverrideReasonCode`, `Cohort`, `_enforce_utc`. The 11-stage state machine + `PendingDecisionKind` + `GateKind` + `Stage3bChoice` are deleted.

### `agentxp.schemas.profiler`

`ProfileReport`, `ProfileReportRow`, etc. — output shape of the profiler tool.

### `agentxp.schemas._types`

`Sha256Hex` — `Annotated[str, Field(pattern="^[a-f0-9]{64}$", ...)]`. Use everywhere a 64-char hex digest is expected.

---

## Data modules

### `agentxp.data.demo`

| Function | Notes |
|---|---|
| `build` (in `build.py`) | Regenerate `sample-data/agentxp_demo.duckdb`. Deterministic via MASTER_SEED + FIXTURE_VERSION. |
| `write_lock` / `verify_lock` (in `fixture_lock.py`) | Read/write `fixture.lock.yaml`. |
| `SCENARIOS` (in `scenarios.py`) | 8 target scenarios spanning the verdict tree. |
| `streams` (in `seed.py`) | Per-experiment numpy SeedSequence streams. |

---

## Adding a new helper

1. Land the function in `agentxp/<module>/<file>.py`. Pure where possible.
2. Add a row to this index.
3. If a skill should call it, reference it in `.claude/skills/<name>/SKILL.md` by import path + function name.
4. If it produces or consumes a schema, add the schema to `agentxp/schemas/` and reference here.
5. The closure test in `tests/docs/test_claude_md.py` will surface drift.
