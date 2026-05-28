# AgentXP PRD Coverage Matrix

Final end-to-end review. Snapshot: 367 tests passing, 3/3 deterministic runs.

PRD: `/Users/shanebutler/projects/ai-analytics-for-builders/experimentation-platform/OPENXP_PRD.md`

Legend: **DONE** / **PARTIAL** / **MISSING** / **DEFERRED** (v2.0 punt) — no recommendations here, see `FINAL_STATUS.md`.

---

## §5.1 — `/experiment` skill (8 modes)

| PRD ref | Requirement | Version | Status | Evidence | Notes |
|---|---|---|---|---|---|
| §5.1 | `/experiment design` | v0.1 | DONE | `.claude/skills/experiment/MODES.md` §1; `agents/experiment-designer.md` | Conversation flow + power dispatch documented |
| §5.1 | `/experiment power` | v0.1 | DONE | `MODES.md` §2 | Direct stats call, no agent |
| §5.1 | `/experiment analyze` | v0.1 | DONE | `MODES.md` §3; `agents/experiment-analyzer.md` | 8-question framework |
| §5.1 | `/experiment interpret` | v0.1 | DONE | `MODES.md` §4; `agents/experiment-interpreter.md` | Walks Appendix A tree |
| §5.1 | `/experiment monitor` | v0.5 | DONE | `MODES.md` §5; `agents/experiment-monitor.md`; `openxp/monitoring/` | GREEN/YELLOW/RED dispatch |
| §5.1 | `/experiment report` | v0.5 | DONE | `MODES.md` §6; `agents/experiment-readout.md` | Audience-adaptable (executive/technical/cross-functional) |
| §5.1 | `/experiment full` | v0.5 | DONE | `MODES.md` §7 | Pipeline orchestration with resume-from-state |
| §5.1 | `/experiment status` | v0.1 | DONE | `MODES.md` §8 | Read-only YAML inspector |
| §5.1 | Cold-start `/experiment analyze` without yaml | v0.1 | DONE | `skill.md:87-96` | Documented; no direct test for cold-start code path |
| §5.1 | `--just-do-it`, `--sequential`, `--dry-run`, `--yaml`, `--audience` flags | v0.1 | PARTIAL | `skill.md:38-49` | Flags documented in skill dispatcher; not wired into any CLI since modes are markdown-driven (they're agent-interpreted) |

## §5.2 — Agents

| PRD ref | Requirement | Version | Status | Evidence | Notes |
|---|---|---|---|---|---|
| §5.2 | experiment-designer.md (7-step flow) | v0.1 | DONE | `agents/experiment-designer.md` | Calls power_proportion/power_mean/power_ratio/duration_estimate/power_sensitivity_table/detectable_effect |
| §5.2 | experiment-analyzer.md (10-step flow) | v0.1 | PARTIAL | `agents/experiment-analyzer.md` | Walks 8-question variant of PRD's 10-step spec. No explicit `prepare_experiment_data` call in agent prose (only in MODES.md); no denominator_srm step wired into analyzer markdown; no cohens_h in agent prose; no fishers_exact fallback language in the agent markdown. MODES.md §3 has all of this, so the orchestrator covers it — but the agent doc lags the MODES doc |
| §5.2 | experiment-interpreter.md | v0.1 | DONE | `agents/experiment-interpreter.md` | Appendix A tree, extension_estimate, alert_threshold check |
| §5.2 | experiment-monitor.md | v0.5 | DONE | `agents/experiment-monitor.md` | Three-tier SRM + guardrails + sample tracking |
| §5.2 | experiment-readout.md | v0.5 | DONE | `agents/experiment-readout.md` | Six-section report + audience adaptation |
| §5.2 | experiment-program.md | v1.0 | DEFERRED | — | Not in scope for current waves |
| §5.2 | "SHIP_WITH_CAVEATS as modifier, not 6th outcome" | v0.1 | PARTIAL | `openxp/schemas/experiment.py:41-46` EwlClassification enum has 5 canonical values | No enforcement in agent prose to use `reasoning`/`monitoring_plan` for the caveats modifier |

## §5.3 — Stats functions

All 32 PRD-required functions are exported via `openxp.stats`. Signatures resolved via live `inspect.signature` probe.

### Data prep (v0.1)

| PRD function | PRD signature | Version | Status | File:line | Sig match? |
|---|---|---|---|---|---|
| `prepare_experiment_data` | `(df, variant_col, metric_col, unit_col, metric_type=None)` | v0.1 | DONE | `openxp/stats/prep.py` | **NO** — actual: `(df, treatment_col=None, metric_cols=None, segment_cols=None, winsorize_spec=None)`. Different parameter model (multi-metric, segment-aware, winsorize spec) — a semantic superset but breaks PRD literal contract. Agent docs should reference the real signature |
| `winsorize` | `(values, lower=0.0, upper=0.99)` | v0.1 | DONE | `openxp/stats/ab_tests.py` | `(series, lower=0.01, upper=0.99)` — lower default differs (0.01 vs 0.0); semantically the same symmetric-percentile trim |

### A/B tests (v0.1)

| PRD function | PRD signature | Version | Status | File:line | Sig match? |
|---|---|---|---|---|---|
| `welch_test` | `(control, treatment, alternative='two-sided')` | v0.1 | DONE | `openxp/stats/ab_tests.py` | **NO** — actual: `(control, treatment, alpha=0.05)`. No `alternative` parameter. One-sided tests for guardrails are only available via `guardrail_test`. Breaks PRD §5.3 D.1 one-sided-vs-two-sided contract for primary/secondary metrics |
| `proportion_test` | `(c_success, c_n, t_success, t_n, alternative='two-sided')` | v0.1 | DONE | `openxp/stats/ab_tests.py` | **NO** — actual: `(c_success, c_n, t_success, t_n, alpha=0.05)`. Same missing `alternative`. No small-sample guard referenced in PRD (auto-fallback to Fisher's) — skill/agent layer handles this manually |
| `fishers_exact_test` | `(c_success, c_n, t_success, t_n, alternative='two-sided')` | v0.1 | DONE | `openxp/stats/fishers.py` | Match |
| `ratio_metric_test` | `(num_c, den_c, num_t, den_t, alternative='two-sided')` | v0.1 | DONE | `openxp/stats/ab_tests.py` | **NO** — actual: `(num_c, den_c, num_t, den_t, alpha=0.05)`. Same missing `alternative` |
| `guardrail_test` | `(control, treatment, nim=None, metric_type='continuous', alternative='less')` | v0.1 | DONE | `openxp/stats/guardrails.py` | **NO** — actual: `(control, treatment, metric_type='mean', nim_relative=0.02, alpha=0.05, invert=False)`. Kwarg names drift (`nim` → `nim_relative`, `metric_type='continuous'` → `'mean'`), `alternative='less'` is implicit, no-NIM inferiority mode not exposed via `nim=None` but via `nim_relative=0.02` default |

### Power (v0.1)

| PRD function | PRD signature | Version | Status | File:line | Sig match? |
|---|---|---|---|---|---|
| `power_proportion` | `(baseline, mde, alpha=0.05, power=0.80, mde_type='relative')` | v0.1 | DONE | `openxp/stats/power.py` | **NO** — actual: `(baseline_rate, mde_relative, alpha=0.05, power=0.8)`. `mde_type` not exposed (relative-only hardcoded) — D.2 absolute-vs-relative contract not implemented |
| `power_mean` | `(baseline_mean, baseline_std, mde, alpha=0.05, power=0.80, mde_type='relative')` | v0.1 | DONE | `openxp/stats/power.py` | Same — no `mde_type` |
| `power_ratio` | `(num_mean, num_var, den_mean, den_var, cov, mde, alpha=0.05, power=0.80, mde_type='relative')` | v0.1 | DONE | `openxp/stats/ratio_power.py` | **NO** — actual: `(baseline_num_mean, baseline_den_mean, baseline_num_std, baseline_den_std, correlation_num_den, mde_relative, alpha=0.05, power=0.8)`. Takes `std`+`correlation` not `var`+`cov`; PRD math spec (`Var(R) = (num_var - 2*R*cov + R²*den_var) / ...`) is an equivalent reparameterization but docs mismatch |
| `detectable_effect` | `(n, baseline, alpha=0.05, power=0.80, metric_type='proportion', baseline_std=None)` | v0.1 | DONE | `openxp/stats/power.py` | **NO** — actual: `(n_per_group, baseline_rate=None, baseline_std=None, alpha=0.05, power=0.8)`. No explicit `metric_type` — inferred from which baseline is passed. Ratio metric path missing |
| `duration_estimate` | `(n_required, daily_traffic, allocation=0.5)` | v0.1 | DONE | `openxp/stats/power.py` | Signature match (default `allocation=1.0` not `0.5`); 7-day rounding per D.27 — needs verification in test |
| `extension_estimate` | `(current_n, required_n, daily_traffic, allocation=0.5)` | v0.1 | DONE | `openxp/stats/extension.py` | **NO** — actual: `(current_n, current_mde_observed, required_power, baseline_variance, daily_traffic, alpha=0.05)`. Wildly different parameterization. Takes MDE + variance + power target instead of required_n; mathematically equivalent input set but agents following PRD literally will call it wrong |
| `power_sensitivity_table` | `(baseline, mde_values, traffic_values, mde_type='relative')` | v0.1 | DONE | `openxp/stats/power.py` | **NO** — actual: `(baseline_rate, mde_values, daily_traffic_values, alpha=0.05, power=0.8)`. No `mde_type`. Proportion-only (no `power_mean` sensitivity path) |

### Experiment health (v0.1)

| PRD function | PRD signature | Version | Status | File:line | Sig match? |
|---|---|---|---|---|---|
| `srm_check` | `(observed_counts, expected_ratios, threshold=0.0005)` | v0.1 | DONE | `openxp/stats/srm.py` | **NO** — actual default `threshold=0.01`. PRD mandates 0.0005 default. `run_monitor` and MODES.md override it at call sites, but the function default still violates D.7. Wave 1 M5 flagged this |
| `srm_diagnose` | `(assignments_df, segments)` | v0.1 | DONE | `openxp/stats/srm.py` | Match (`group_col='variant'`, `segments=None` defaults) |
| `denominator_srm` | `(metric_den_c, metric_den_t, expected_ratio)` | v0.1 | DONE | `openxp/stats/guardrails.py` | **NO** — actual: `(num_c, den_c, num_t, den_t, expected_ratio=1.0, threshold=0.05)`. Takes full numerator+denominator arrays, not just denominators |

### Effect sizes (v0.1)

| PRD function | PRD signature | Version | Status | File:line | Sig match? |
|---|---|---|---|---|---|
| `cohens_d` | `(control, treatment)` | v0.1 | DONE | `openxp/stats/effect_size.py` | Match |
| `cohens_h` | `(p_control, p_treatment, n_control, n_treatment)` | v0.1 | DONE | `openxp/stats/effect_size_extras.py` | **NO** — actual: `(p_control, p_treatment)`. Sample sizes not taken → no CI for Cohen's h. PRD explicitly says "Without sample sizes, only the point estimate is computable — CI would be missing" — current impl is the no-CI variant, so D.24 is partial |
| `relative_lift` | `(control_mean, treatment_mean, control_se, treatment_se, n_control, n_treatment)` | v0.1 | DONE | `openxp/stats/effect_size.py` | **NO** — actual: `(control_mean, treatment_mean)`. Point estimate only, no CI. PRD mandates overloaded API (aggregates OR raw arrays). Overload not implemented |

### Corrections (v0.1)

| PRD function | PRD signature | Version | Status | File:line | Sig match? |
|---|---|---|---|---|---|
| `adjust_pvalues` | `(pvalues, method='holm')` | v0.1 | DONE | `openxp/stats/corrections.py` | Match (plus `alpha=0.05`) |

### Advanced v0.5 — bootstrap/nonparam

| PRD function | Version | Status | Notes |
|---|---|---|---|
| `bootstrap_test` | v0.5 | MISSING | Not implemented. PRD §5.3 "Advanced (v0.5)" |
| `mann_whitney_test` | v0.5 | MISSING | Not implemented |

### Advanced v1.0

| PRD function | PRD signature | Version | Status | File:line | Sig match? |
|---|---|---|---|---|---|
| `cuped_adjust` | `(pre, post, treatment, metric_type='continuous')` | v1.0 | DONE | `openxp/stats/cuped.py` | **NO** — actual: `(y_pre, y_post, treatment=None)`. Lost `metric_type`. Additional helpers `cuped_welch_test`, `variance_reduction` provide the full pipeline — a superset of PRD |
| `confidence_sequence` | `(control, treatment, alpha=0.05, metric_type='continuous')` | v1.0 | DONE | `openxp/stats/sequential.py` | Renamed to `msprt_test` + `always_valid_ci` + `group_sequential_boundaries` + `sequential_proportion_test`. PRD name not exported; functionally covered via mSPRT + Howard et al. 2021. Agent docs must use the new names |
| `bayesian_proportion` | `(c_success, c_n, t_success, t_n, prior_alpha=1, prior_beta=1)` | v1.0 | DONE | `openxp/stats/bayesian.py` | Renamed to `beta_binomial_test`. Match on params (plus n_samples, seed, loss thresholds) |
| `normal_normal_test` | (not in PRD by name) | v1.0 | DONE | `openxp/stats/bayesian.py` | Continuous Bayesian analog — PRD bonus |
| `prob_best` | `(posteriors)` → float | v1.0 | DONE | `openxp/stats/bayesian.py` | Renamed to `probability_to_beat` |
| `expected_loss` | `(posteriors)` → float | v1.0 | DONE | `openxp/stats/bayesian.py` | Match |
| `monitor_trend` | `(monitoring_history, metric_name)` | v1.0 | MISSING | — | No novelty/primacy trend detector across monitoring runs. Monitoring module has `srm_trend` which is a per-window SRM drift check — not the D.37 time-windowed effect estimation for novelty/primacy |

### Computation trace (D.9)

| Requirement | Status | Evidence |
|---|---|---|
| Every stats call emits `computation_trace` | DONE | `openxp/stats/_trace.py` — opt-in via `set_trace(True)`. Functions check `is_trace_enabled()` and attach `computation_trace` dict |
| Trace dict shape: `inputs`, `intermediate_values`, `formula_ref`, `timestamp` | DONE | `_trace.py:50-62` |
| Skill validates trace before advancing state | PARTIAL | `skill.md:145` advertises D.9 validation — no runtime enforcement in code, enforcement lives in the agent-interpreted markdown layer |
| Default trace-enabled for `/experiment` runs | MISSING | `_trace.py:36` `_TRACE_ENABLED = False`. Orchestrator must call `set_trace(True)` before every analyze, which is documented nowhere. Live probe confirms: calling `welch_test` without `set_trace(True)` returns dict with no `computation_trace` key |

## §5.4 — experiment.yaml schema

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| §5.4 | `schema_version: 1` | MISSING | `openxp/schemas/experiment.py` `ExperimentConfig` has no `schema_version` field |
| §5.4 | Full lifecycle statuses: DESIGNING, POWERED, COLLECTING, ANALYZING, INTERPRETED, REPORTED, SHIPPED, COMPLETED, ABANDONED, INVALID, BLOCKED | PARTIAL | `openxp/schemas/experiment.py:15-22` `ExperimentStatus` has only 6 (DESIGNING/POWERED/COLLECTING/ANALYZING/INTERPRETED/REPORTED). Missing SHIPPED/COMPLETED/ABANDONED/INVALID/BLOCKED. `openxp.storage.lifecycle.ALL_STATES` has all 11 — **two sources of truth conflict**. The validator uses `lifecycle.ALL_STATES`; the Pydantic schema uses the 6-state enum. A yaml with `status: SHIPPED` passes the validator but fails Pydantic parse |
| §5.4 | `hypothesis` block (action/metric/direction/magnitude/mechanism) | DONE | `schemas/experiment.py:49-54` |
| §5.4 | `hypothesis.goal_alignment`, `estimated_impact` | MISSING | Pydantic model doesn't have these fields |
| §5.4 | `priority` / `priority_rationale` | MISSING | Not in schema |
| §5.4 | `randomization` block | MISSING | Not in schema |
| §5.4 | `metrics.primary` with type/definition/mde/baseline/sql | DONE | `schemas/experiment.py:57-64` |
| §5.4 | `metrics.guardrail[]` with nim/direction | DONE | `schemas/experiment.py:72-82` |
| §5.4 | `variants[]` with allocation + is_control | DONE | `schemas/experiment.py:90-94` |
| §5.4 | `power` block | DONE | `schemas/experiment.py:96-105` |
| §5.4 | `decision_rules` | DONE | `schemas/experiment.py:108-113` |
| §5.4 | `data` block | PARTIAL | `schemas/experiment.py:116-120` — only `assignment_table`, `outcome_table`, `date_column`, `unit_column`. PRD has `source`, `exposure_query`, `pre_experiment_query`, `analysis_population` etc. — not implemented |
| §5.4 | `timeline` (created/powered/started/analyzed/decided) | DONE | `schemas/experiment.py:123-128` |
| §5.4 | `results` block with ewl_classification | DONE | `schemas/experiment.py:131-138` |
| §5.4 | `holdback`, `ramp_plan`, `alert_threshold` (guardrails), `analysis_population`, `amendments` fields | MISSING | Not in Pydantic schema. Monitoring agent references `ramp_plan` at read time |
| §5.4 | `suspicious_lift_threshold` (default 0.20) | MISSING | Not in schema; hardcoded in MODES.md prose |

## §5.5 — Data discovery protocol

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| §5.5 | Schema-agnostic; no hardcoded column names | DONE | `openxp/data/discovery.py:20-62` — hint tuples (`TREATMENT_COLUMN_HINTS`, `CONTROL_VALUE_HINTS`, `ID_COLUMN_PATTERNS`, `TIMESTAMP_NAME_PATTERNS`), used only via iteration. Verified in Wave 1 review M5 |
| §5.5 | Auto-detect treatment col from hints | DONE | `discovery.py` |
| §5.5 | Numeric → metric candidates, categorical 2-20 → segments, datetime → timestamps | DONE | `discovery.py` |
| §5.5 | Ask user when ambiguous | PARTIAL | Agent-layer behavior (`agents/experiment-analyzer.md:13-18`), not enforced in code |
| §5.5 | Works on CSV / DuckDB / Snowflake | DONE | `openxp/data/csv_loader.py`, `duckdb_loader.py`, `snowflake_loader.py`, unified via `LoadResult` |

## §5.6 — Sample data

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| §5.6 | `sample-data/` isolated, nothing depends on it | DONE | `sample-data/` contains 7 CSVs (clean_ab, no_effect, srm_violation, guardrail_violation, underpowered, mixed_results, checkout_redesign); no code imports these paths |
| §5.6 | Practice scenarios cover SHIP/LEARN/INVALID/INVESTIGATE/underpowered/mixed | DONE | All 6 canonical scenarios present + `checkout_redesign.csv` |

## §5.7 — Metric definitions

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| §5.7 | `metrics/*.yaml` format with name/type/definition/unit/formula | PARTIAL | `openxp/metrics/schema.py` `MetricDefinition` Pydantic model + `openxp/metrics/registry.py` `MetricRegistry`. Missing `test_family` field to route metrics to Bayesian/CUPED/sequential tests — Wave 1 I2 flagged, Wave 2 did not address. Only routes to proportion_test/welch_test/ratio_metric_test |
| §5.7 | `metrics/` directory at repo root | PARTIAL | `metrics/` exists at repo root (separate from `openxp/metrics/`); contains no yaml files — just empty scaffold |
| §5.7 | Metric registry with `/experiment design` lookup | PARTIAL | `MetricRegistry` class exists, agent-layer lookup not wired |
| §5.7 | SQL and column-ref metric types | DONE | `schema.py` supports both |

## §5.8 — Data architecture

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| §5.8 | CSV connector | DONE | `openxp/data/csv_loader.py` |
| §5.8 | DuckDB connector | DONE | `openxp/data/duckdb_loader.py` — v0.5 target met |
| §5.8 | Snowflake MCP connector | DONE (code only) | `openxp/data/snowflake_loader.py` — v1.0 target. S4 from Wave 1 (`where` param raw-SQL injection) still present |
| §5.8 | Unified `LoadResult` with discovery metadata | DONE | `openxp/data/base.py` |
| §5.8 | Expression-eval pandas formulas with whitelist | MISSING | D.18 security model — no AST-parsed formula evaluator for metric definitions |

## §5.9 — Results storage and history

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| §5.9 | `ExperimentStore` with atomic writes | DONE | `openxp/storage/store.py` — `_atomic_write_bytes` uses tempfile + fsync + os.replace. Interrupt test present |
| §5.9 | `save_experiment` / `load_experiment` | DONE | `store.py` public API |
| §5.9 | `save_analysis` / `load_latest_analysis` | DONE | `store.py`. Wave 1 I3 microsecond-sort bug unaddressed |
| §5.9 | `save_interpretation` / `save_report` | DONE | `store.py` |
| §5.9 | `history(experiment_id)` from `log.jsonl` | DONE | `store.py` |
| §5.9 | `list_experiments` with status filter | DONE | `store.py` |
| §5.9 | `delete_experiment` | DONE | `store.py` |
| §5.9 | Lifecycle state machine (`is_backward`, `ALL_STATES`) | DONE | `storage/lifecycle.py` — 11 states per Appendix B (see conflict with schemas/experiment.py) |

## §5.10 — Change tracking

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| §5.10 | `amendments.jsonl` per experiment | DONE | `openxp/amendments/tracker.py` — AmendmentTracker |
| §5.10 | Amendment with date/author/change/reason | DONE | `tracker.py` `Amendment` dataclass, min-10-char reason, USER default |
| §5.10 | `diff_experiments` | DONE | `openxp/amendments/diff.py` |
| §5.10 | `classify_change` material/administrative | DONE | `diff.py:104-187` |
| §5.10 | `require_amendment_for_transition` | DONE | `tracker.py:107` — delegates to `is_backward` |

## §5.14 — Error handling

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| §5.14 | `OpenXPError` envelope with code/message/hint/severity/details | DONE | `openxp/errors/base.py` |
| §5.14 | Subclasses: ValidationError, DataError, StatsError, StorageError, LifecycleError | DONE | `openxp/errors/base.py` |
| §5.14 | `codes.py` with error code constants + MESSAGES/HINTS templates | DONE | `openxp/errors/codes.py` — 17 codes defined |
| §5.14 | Error format `[CODE] message\n  hint: ...` | DONE | `base.py:63-67` |
| §5.14 | `to_dict` JSON-serializable | DONE | `base.py:75-84` |
| §5.14 | Stats functions return `{error: True, error_type: ...}` on failure | PARTIAL | `openxp/stats/sequential.py:145-153` mixes error-return shapes (Wave 1 S2); `ab_tests.py` uses string `"error"`; no unified convention |
| §5.14 | Data loading errors with specific types | PARTIAL | `openxp/data/*` raises Python exceptions but no consistent `OpenXPError` wrapping |

## §5.15 — Schema validation

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| §5.15 | `validate_experiment_yaml` collects all findings in one pass | DONE | `openxp/validators/experiment_validator.py:272-477` |
| §5.15 | Cross-field validation (primary_metric in metric_names, allocation sum = 1.0 ± 0.001) | DONE | `experiment_validator.py`. Tested |
| §5.15 | `validate_metric_yaml` | DONE | `openxp/validators/metric_validator.py` |
| §5.15 | Pydantic model for experiment.yaml | PARTIAL | `openxp/schemas/experiment.py` present but incomplete vs §5.4 (see above) |
| §5.15 | Pydantic result-type schemas (TestResult, GuardrailResult, PowerResult, etc.) | MISSING | `openxp/schemas/results.py` — file exists but empty/minimal scaffolding. Stats functions return plain dicts, not Pydantic models, contradicting §5.3 "(Pydantic model in v0.1)" |

## Appendix A — Result Interpretation Tree

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| App A | Five canonical outcomes: SHIP, INVESTIGATE, ABORT, LEARN, INVALID | DONE | `schemas/experiment.py:41-46` EwlClassification enum; `MODES.md:229-234` interpret spec |
| App A | Branch logic (significant positive + guardrails clean → SHIP, etc.) | DONE | `MODES.md §4` + `agents/experiment-interpreter.md` |
| App A | INVESTIGATE requires quantified trade-off (`primary_gain_$ - guardrail_cost_$`) | DONE | `MODES.md:230` |
| App A | LEARN (powered) vs LEARN (underpowered, uses `extension_estimate`) vs LEARN (practically insignificant) | DONE | `MODES.md:232-234` |
| App A | Alert threshold → INVALID (hard safety ceiling) | DONE | `MODES.md:226` |
| App A | Powered-as-spectrum (D.26) | DONE | `MODES.md:235` |

## Appendix B — State machine

| PRD ref | Requirement | Status | Evidence |
|---|---|---|---|
| App B | 11 states (DESIGNING / POWERED / COLLECTING / ANALYZING / INTERPRETED / REPORTED / SHIPPED / COMPLETED / ABANDONED / INVALID / BLOCKED) | DONE | `openxp/storage/lifecycle.py` `ALL_STATES` |
| App B | Forward transitions per Table | DONE | `lifecycle.py` |
| App B | Backward transitions (POWERED→DESIGNING, ANALYZING→COLLECTING, INTERPRETED→COLLECTING) | DONE | `lifecycle.py` `_BACKWARD` |
| App B | Backward transition requires amendment reason | DONE | `amendments/tracker.py:107` delegates to `is_backward` |
| App B | INVALID → ABANDONED or DESIGNING | DONE | `lifecycle.py` |
| App B | BLOCKED inbound/outbound edges | PARTIAL | Wave 1 M6 noted PRD is silent on BLOCKED edges; implementation allows DESIGNING/POWERED/COLLECTING ↔ BLOCKED as a reasonable extension, undocumented in comment |
| App B | Skill validates every transition | DONE | `skill.md` dispatcher enforces legal transitions before mode execution |

## PRD §9 Build plan deliverables

### v0.1 (MVP)

| Deliverable | Status | Evidence |
|---|---|---|
| Repo scaffold (CLAUDE.md, README, LICENSE, pyproject.toml) | DONE | All present at repo root |
| Vendor stats engine | DONE | `openxp/stats/` — 18 modules |
| Test suite | DONE | 367 tests, 3× deterministic |
| CLAUDE.md orchestrator | DONE | Root `CLAUDE.md` |
| `/experiment design` | DONE | Skill + agent |
| `/experiment power` | DONE | Skill |
| `/experiment analyze` | DONE | Skill + agent |
| `/experiment interpret` | DONE | Skill + agent |
| 5 agents | DONE | `agents/*.md` |
| Metric definitions | PARTIAL | `openxp/metrics/` registry present, no `metrics/` yaml files, no test_family routing |
| Experiment directories | DONE | `ExperimentStore` handles `experiments/<slug>/` structure |
| `analysis_results.json` | DONE | `store.save_analysis` |
| Templates (experiment.yaml, metric.yaml, report template, stats cheat sheet) | PARTIAL | `templates/experiment.yaml`, `templates/experiment-report.md`, `templates/stats-cheat-sheet.md`. **No `templates/metric.yaml`** |
| 7 walkthroughs | DONE | 11 walkthroughs shipped (`walkthroughs/`) — over-delivered |
| sample-data/ | DONE | 7 CSVs |
| README per spec (hero GIF, two-path quick start, version-annotated comparison, walkthrough learning path) | PARTIAL | README present but no hero GIF, no two-path quick start, walkthrough learning path is a link list only |
| Cold-start analyze path | PARTIAL | Documented in skill.md; no direct integration test |
| Fisher's exact fallback | DONE | `fishers_exact_test` + auto-fallback logic prescribed in MODES.md |
| Suspicious uplift detection (Twyman's Law) | PARTIAL | Documented in MODES.md §3 step 9; no code module enforces the 0.20 threshold |
| Decision framework presets (Strict/Balanced/Exploratory) | MISSING | Not found in designer agent prose or any template |
| Guardrail NIM maturity path (optional NIM) | PARTIAL | `guardrail_test` takes `nim_relative=0.02` as hardcoded default; no-NIM inferiority-only mode is not exposed |
| Teaching mode (first-time default) | MISSING | No first-time-user detection or tutorial scaffolding |
| Extension calculator | DONE | `extension_estimate` exported |
| PyPI publishing | MISSING | `pyproject.toml` present but not published; not a code deliverable |
| CONTRIBUTING.md | MISSING | No CONTRIBUTING.md at repo root |
| Demo GIFs | MISSING | No GIFs in repo |

### v0.5

| Deliverable | Status | Evidence |
|---|---|---|
| `/experiment full` | DONE | `MODES.md §7` |
| `/experiment monitor` | DONE | `MODES.md §5` + `openxp/monitoring/` |
| `/experiment report` | DONE | `MODES.md §6` + `agents/experiment-readout.md` |
| experiment.yaml lifecycle | DONE | `storage/lifecycle.py` |
| amendments.yaml | DONE | `amendments/` module (uses `.jsonl` not `.yaml` — same audit log semantics) |
| Exposure filtering (`exposure_query`, `analysis_population: exposed`) | MISSING | Not in schema or prep |
| Metric registry | PARTIAL | Scaffolded, not wired to designer |
| DuckDB connector | DONE | `openxp/data/duckdb_loader.py` |
| Monitoring history | DONE | `monitoring/history.yaml` per `MODES.md §5`; amendments tracker for cross-session audit |

### v1.0

| Deliverable | Status | Evidence |
|---|---|---|
| CUPED | DONE | `openxp/stats/cuped.py` (cuped_adjust, cuped_welch_test, variance_reduction) |
| Sequential testing (always-valid CIs) | DONE | `openxp/stats/sequential.py` (msprt_test, always_valid_ci, group_sequential_boundaries, sequential_proportion_test) |
| Bayesian mode | DONE | `openxp/stats/bayesian.py` (beta_binomial_test, normal_normal_test, expected_loss, probability_to_beat) |
| Snowflake MCP | PARTIAL | Code present. Not wired through MCP protocol — direct `snowflake-connector-python` usage. S4 `where` injection unresolved |
| Metric reuse (cross-experiment trending) | MISSING | No cross-experiment metric trending UI or agent mode |
| Polish (error messages, edges, docs) | PARTIAL | Error envelope exists, not universally wired |

---

## End-to-end trace: `/experiment full sample-data/clean_ab.csv`

Static trace: I read `skill.md`, `MODES.md`, each referenced agent and function, and probed real signatures with `inspect.signature`. No Python executed against actual data.

### Step 0 — Dispatcher (skill.md)

- Parse mode = `full`, positional = `sample-data/clean_ab.csv`.
- Locate experiment.yaml: none in `sample-data/` — `full` mode §7 step 1 says "if no experiment.yaml, run `design` first."
- **Runtime risk:** `skill.md:72` says for `analyze` with no yaml → cold-start path. For `full` with no yaml, the dispatch algorithm is underspecified. The mode §7 prose fires `design` first, but `design` requires a hypothesis conversation — which contradicts the `/experiment full <data-file>` entry point. The skill offers two irreconcilable paths here and MODES.md §7 step 3 says to "Pause for data collection" if transitioning to POWERED with no data, but we already have data.

### Step 1 — `/experiment design` (MODES.md §1)

1. Scaffold `experiments/<slug>/` — slug derived from conversation or flag.
2. Invoke `agents/experiment-designer.md` — agent doc exists. 7-step flow documented.
3. Step 2.4 power calc: dispatch on metric type. Agent says "Calls: power_proportion()/power_mean()/power_ratio()/..." — functions exist.
4. MODES.md §1 step 2 → "Step 4: Power calculation via `openxp.stats.power.power_proportion` / `power_mean` / `power_ratio`".
   - `power_proportion(baseline_rate, mde_relative, alpha=0.05, power=0.8)` — agent would pass `(baseline, mde)`. OK.
   - `power_ratio` — **signature drift.** MODES.md §2 step 2 literally says: `power_ratio(num_mean, num_var, den_mean, den_var, cov, mde, alpha, power)`. Actual is `(baseline_num_mean, baseline_den_mean, baseline_num_std, baseline_den_std, correlation_num_den, mde_relative, alpha, power)`. **An agent following MODES.md §2 verbatim will TypeError: unexpected keyword argument 'num_var'.**
5. Power viability check: C.
6. Config review checkpoint: B.

### Step 2 — `/experiment power` (skipped if design already did it)

Same signature drift as above for `power_ratio`.

### Step 3 — Pause

MODES.md §7 step 3: "If YAML transitions to POWERED and no data file is present, exit." But we gave a data file. Ambiguity: in `full` mode, does the skill skip the pause? MODES.md doesn't say.

### Step 4 — `/experiment analyze sample-data/clean_ab.csv` (MODES.md §3)

1. **Data Discovery Protocol** — calls `openxp.data.discovery.discover_schema` implicitly via the analyzer agent. Function exists. `sample-data/clean_ab.csv` has columns `user_id,variant,converted,revenue,platform,signup_days` — discovery would flag `variant` as treatment (hint match), `converted`/`revenue`/`signup_days` as metric candidates, `platform` as segment (2-20 unique).

2. **Data preparation**: `prepare_experiment_data(df, variant_col, metric_col, unit_col, metric_type)` per MODES.md §3 step 2. **Signature drift.** Actual: `prepare_experiment_data(df, treatment_col=None, metric_cols=None, segment_cols=None, winsorize_spec=None)`. MODES.md's kwarg names (`variant_col`, `metric_col`, `unit_col`, `metric_type`) are wrong — an agent passing them verbatim will TypeError.

3. **Min-sample guard** — no code in the stats layer; the skill is supposed to compare observed n to `power.sample_size_per_group`. No helper function; done in agent prose.

4. **SRM gate** — `srm_check(observed_counts, expected_ratios, threshold=0.0005)` per MODES.md. Actual: `srm_check(observed_counts, expected_ratios=None, threshold=0.01)`. **Default threshold wrong (0.01 vs PRD's 0.0005)** — but MODES.md passes `threshold=0.0005` explicitly, so the call succeeds. For `clean_ab.csv` (5000/5000 split, perfect) this returns PASS.

5. **Analyzer agent Q2 primary metric test** — dispatch on metric type:
   - `variant="treatment"` vs `"control"` on `converted` (binary) → `proportion_test(c_success, c_n, t_success, t_n)`. Agent markdown at `agents/experiment-analyzer.md:52-67` uses positional args — signature matches. OK.
   - Small-sample guard: MODES.md §3 step 5 says "if expected cell count < 5, fall back to `fishers_exact_test`." `fishers_exact_test(c_success, c_n, t_success, t_n, alpha=0.05, alternative='two-sided')` exists. OK for fallback wiring but no runtime cell-count check inside `proportion_test` itself — the analyzer agent must manually compute this.

6. **Q3 effect size** — `cohens_d(control, treatment)` (OK), `cohens_h(p_control, p_treatment)` — **signature drift.** PRD and MODES.md call for `cohens_h(p_control, p_treatment, n_control, n_treatment)` to produce CIs. Actual is point estimate only. An agent calling `cohens_h(..., n_control=N, n_treatment=N)` will TypeError.

7. **`relative_lift(control_mean, treatment_mean)`** — matches simplest overload. PRD wants a richer signature with SEs for CI; the actual function returns only point lift. No CI on relative lift.

8. **`detectable_effect(n_per_group, baseline_rate=...)` for MDE at observed n** — matches for proportions. For continuous path, need `baseline_std=...`. OK.

9. **Segment analysis** — no dedicated function; done in agent prose by calling `proportion_test` per segment.

10. **Guardrail tests** — `guardrail_test(control, treatment, metric_type='mean', nim_relative=0.02, alpha=0.05, invert=False)`. MODES.md §3 step 6 says: `guardrail_test(control, treatment, nim=..., alternative='less')`. **Signature drift.** Agent would pass `nim=` → TypeError (kwarg is `nim_relative`). Also no `alternative` kwarg; use `invert=True` to flip direction. `clean_ab.csv` has no declared guardrails, so this path wouldn't fire on this specific file, but any yaml-driven guardrail on any file will break.

11. **`adjust_pvalues(secondary_pvalues, method='holm')`** — match. OK.

12. **Denominator SRM** — MODES.md §3 step 5 says call `denominator_srm` for ratio metrics. Actual: `denominator_srm(num_c, den_c, num_t, den_t, expected_ratio=1.0, threshold=0.05)`. PRD signature is `(metric_den_c, metric_den_t, expected_ratio)` — different inputs. Non-fatal if MODES.md is used as the source of truth, but PRD-literal agents will pass the wrong number of args.

13. **Artifacts:**
    - `analysis_results.json` — written by `store.save_analysis` (exists).
    - `reports/analysis.md` — written by `store.save_report` (exists).
    - `working/analyzer-trace.md` — per-call computation traces. **Trace is opt-in** via `set_trace(True)`. Nothing in skill.md/MODES.md calls `set_trace`. Live probe: calling `welch_test` without `set_trace(True)` returns dict with NO `computation_trace` key. **Downstream:** `interpret` step 2 validates `computation_trace` per D.9. If traces are absent, interpret will refuse. **This is a breakage between `analyze` and `interpret` unless the orchestrator starts by toggling the trace flag.**

14. **State transition** COLLECTING → ANALYZING: enforced by `storage/lifecycle.py`. Pydantic `ExperimentStatus` enum (`schemas/experiment.py:15-22`) does NOT include COLLECTING. Writing `status: COLLECTING` to the yaml file will **fail Pydantic parse** if the model is loaded to round-trip the yaml. Saved via `store.save_experiment` which serializes via `yaml.safe_dump` of a plain dict — OK. Loading via `store.load_experiment` returns a dict, not a Pydantic model — also OK. But `ExperimentConfig(...)` instantiation would fail. This is a **latent landmine**: the Pydantic schema exists but is not used as the canonical load path. Any future caller that does `ExperimentConfig(**data)` on a COLLECTING yaml crashes.

### Step 5 — `/experiment interpret` (MODES.md §4)

1. **Alert threshold scan** — agent prose.
2. **Interpreter agent** — walks Appendix A tree, calls `extension_estimate`, `detectable_effect`, `relative_lift`.
   - `extension_estimate` — **major signature drift.** MODES.md §4 step 2b: `extension_estimate(current_n, required_n, daily_traffic, allocation)`. Actual: `extension_estimate(current_n, current_mde_observed, required_power, baseline_variance, daily_traffic, alpha=0.05)`. **An agent following PRD literally will TypeError on the 2nd positional arg.** The semantic model is different: actual wants the observed MDE + baseline variance, PRD wants required_n + allocation.
3. **D.9 trace validation** — fails if `set_trace(True)` wasn't called (see step 4.13 above).
4. **Ship decision checkpoint** C.

### Step 6 — `/experiment report`

1. Load analysis_results.json + interpretation.md + yaml.
2. Invoke `agents/experiment-readout.md` — agent doesn't call stats functions. OK.
3. No signature drift — agent reads pre-computed values.
4. `store.save_report(experiment_id, report_md)` — exists.

### End-to-end trace summary

**Will runtime-break on `sample-data/clean_ab.csv`** (cold-start or full):

1. **Trace opt-in not set** — `interpret`'s D.9 trace validation rejects the analyze output. Highest-impact breakage because it's on the critical path of every `full` run.
2. **`extension_estimate` signature mismatch** — `interpret` with LEARN-underpowered branch throws TypeError. Only fires on underpowered null results, so `clean_ab.csv` (clean positive → SHIP) dodges it, but `underpowered.csv` hits it immediately.
3. **`prepare_experiment_data` signature mismatch** — `analyze` step 2 throws TypeError on any file if the agent uses PRD kwargs. MODES.md uses PRD kwargs.
4. **`power_ratio` signature mismatch** — only fires for ratio metrics, but `clean_ab.csv` is a proportion, so it dodges. Any ratio-metric yaml hits it.
5. **`cohens_h` signature mismatch** — only if agent tries to pass `n_control/n_treatment` for CIs. Fails with unexpected kwarg.
6. **`guardrail_test` kwarg drift (`nim` vs `nim_relative`)** — any yaml with guardrails breaks. `clean_ab.csv` has no declared guardrails so it dodges.
7. **Pydantic schema lag** — writing COLLECTING/ANALYZING/etc. to the yaml is fine via the storage path (dict round-trip), but any attempt to validate-on-load via `ExperimentConfig(**data)` fails because those states aren't in the enum.
8. **`schemas/results.py` empty scaffold** — no TypeError, but PRD §5.3 return-type contract (Pydantic models with typed fields) is unfulfilled. Stats return plain dicts.
9. **`full` mode on a data file with no yaml** — dispatch prose is contradictory (design requires conversation; full-with-data wants to run analyze). Ambiguity, not a hard break.

**Will work cleanly on clean_ab.csv if the orchestrator:**
- Calls `openxp.stats._trace.set_trace(True)` before step 4.
- Uses MODES.md §3's (incorrect-per-actual-signature) positional calls but the agent author reads the actual function signatures from `openxp/stats/*.py` rather than copying MODES.md verbatim.
- Skips the `extension_estimate` path (only hit on underpowered-learn, `clean_ab.csv` is SHIP).
- Ignores the Pydantic `ExperimentStatus` enum and treats the yaml as a plain dict.

Net: **a competent agent that reads the real signatures rather than trusting MODES.md can complete `full` on `clean_ab.csv` and reach SHIP.** An agent that trusts MODES.md literally cannot, because too many function signatures drifted between Wave 1 and Wave 3.

---

## Import/resolution check for every skill/MODES reference

| Symbol referenced in skill.md / MODES.md | Exists? | Notes |
|---|---|---|
| `openxp.stats.prep.prepare_experiment_data` | Yes | Kwarg names differ from MODES.md |
| `openxp.stats.ab_tests.welch_test` | Yes | No `alternative` param |
| `openxp.stats.ab_tests.proportion_test` | Yes | No `alternative` param |
| `openxp.stats.ab_tests.fishers_exact_test` | **Lives in `openxp.stats.fishers`** | Re-exported via `openxp.stats` top-level. `openxp.stats.ab_tests.fishers_exact_test` does NOT exist. MODES.md §3 says "from openxp.stats.ab_tests import proportion_test" (OK for that symbol) and lists fishers in the ab_tests block of the skill.md Quick Reference — an agent doing `from openxp.stats.ab_tests import fishers_exact_test` ImportErrors |
| `openxp.stats.ab_tests.ratio_metric_test` | Yes | No `alternative` param |
| `openxp.stats.ab_tests.guardrail_test` | **Lives in `openxp.stats.guardrails`** | Re-exported at top level. `openxp.stats.ab_tests.guardrail_test` does NOT exist. Same submodule-path hazard as above |
| `openxp.stats.power.power_proportion` | Yes | No `mde_type` |
| `openxp.stats.power.power_mean` | Yes | No `mde_type` |
| `openxp.stats.power.power_ratio` | **Lives in `openxp.stats.ratio_power`** | Re-exported at top level. `openxp.stats.power.power_ratio` does NOT exist. Same hazard |
| `openxp.stats.power.detectable_effect` | Yes | No metric_type kwarg |
| `openxp.stats.power.duration_estimate` | Yes | Match |
| `openxp.stats.power.extension_estimate` | **Lives in `openxp.stats.extension`** | Re-exported at top level. `openxp.stats.power.extension_estimate` does NOT exist. Plus signature drift described above |
| `openxp.stats.power.power_sensitivity_table` | Yes | Proportion-only; no `mde_type` |
| `openxp.stats.srm.srm_check` | Yes | Default threshold wrong (0.01 vs 0.0005) |
| `openxp.stats.srm.srm_diagnose` | Yes | Match |
| `openxp.stats.srm.denominator_srm` | **Lives in `openxp.stats.guardrails`** | Re-exported at top level. `openxp.stats.srm.denominator_srm` does NOT exist |
| `openxp.stats.effect_size.cohens_d` | Yes | Match |
| `openxp.stats.effect_size.cohens_h` | **Lives in `openxp.stats.effect_size_extras`** | Re-exported at top level. `openxp.stats.effect_size.cohens_h` does NOT exist. Plus no sample-size kwargs |
| `openxp.stats.effect_size.relative_lift` | Yes | No CI overload |
| `openxp.stats.corrections.adjust_pvalues` | Yes | Match |

**Observation:** skill.md §"Stats Function Quick Reference" tables list functions under their submodule path (`openxp.stats.power.extension_estimate` etc.), but the actual submodule structure is split into narrower files (`ratio_power.py`, `fishers.py`, `guardrails.py`, `effect_size_extras.py`, `extension.py`, `prep.py`). The functions are re-exported at the `openxp.stats` top level and importable as `from openxp.stats import extension_estimate`, but **not** from the submodule path the skill claims. An agent that does `from openxp.stats.power import power_ratio` will ImportError. This is the modern replay of Wave 1 C1 — the exports exist, but the import paths the skill documents don't match the actual module layout.

---

## Monitoring — reviewed last per instructions

Monitoring was under fix-up edit during this review. Live state as of final review:

| Item | Status | Notes |
|---|---|---|
| `run_monitor(experiment_id, data_loader, store=None, current_n_fn=None)` | DONE | Signature differs from Wave 2 walkthrough fabricated API (C1 unfixed) |
| `srm_trend(df, treatment_col, timestamp_col, window='1d', threshold=0.0005, ...)` | DONE | Default threshold 0.0005 — fixes Wave 2 S4 |
| `guardrail_health(df, treatment_col, guardrail_metrics, thresholds, ...)` | DONE | NIM applied to CI bound per Wave 2 M3 |
| `sample_accumulation(current_n, required_n, daily_traffic, days_elapsed, ...)` | DONE | Wave 2 M1 (`days_elapsed=0 and current_n==0`) — not verified in this pass |
| `MonitorReport.persistence_error` | DONE | New field — fixes Wave 2 M5 (persistence swallowed silently) |
| `walkthroughs/monitoring.md` | **UNFIXED** | Still documents the hallucinated API (HEALTHY/WATCH/WARN/STOP, `run_monitor(data=..., experiment_yaml=...)`). Wave 2 C1 blocker remains |
| `run_monitor` default `current_n = len(df)` | UNKNOWN | Wave 2 S1 — not re-verified |

Fix-up was in progress; anything below the "unfixed" line may be moot if the fix-up agent ships the walkthrough rewrite.
