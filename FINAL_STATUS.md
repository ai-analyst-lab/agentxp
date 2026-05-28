# AgentXP Final Status

Final end-to-end review after W0 baseline + Wave 1 + Wave 2 + Wave 3. Monitoring fix-up was landing in parallel; the monitoring walkthrough rewrite may still be in flight.

## 1. TL;DR

- **v0.1 is shippable as a library** (`agentxp.stats` + `agentxp.data` + `agentxp.storage`). 367 tests green, fully deterministic across 3 reruns, every PRD-mandated function exported.
- **v0.5 is shippable on the library side** (monitoring module, amendments, validators, errors). Agent/skill layer advertises function signatures that drifted from the real code — an agent trusting MODES.md literally will hit TypeErrors and ImportErrors on the `analyze` and `interpret` critical path.
- **v1.0 features shipped as code** (CUPED, Bayesian, sequential), but the Pydantic result schemas (`agentxp/schemas/results.py`) and PRD §5.3 return-type contracts are unfulfilled and Snowflake MCP is not actually MCP.

One-line verdict: **Library layer is shippable. Skill/agent layer needs a signature-reconciliation pass before `full` mode works end-to-end without a human reading the real function bodies.**

## 2. What shipped

### Wave 0 baseline
- `agentxp.stats.ab_tests` (welch, proportion, ratio, winsorize)
- `agentxp.stats.power` (power_proportion, power_mean, detectable_effect, duration_estimate, sensitivity table)
- `agentxp.stats.srm` (srm_check, srm_diagnose)
- `agentxp.stats.effect_size` (cohens_d, relative_lift)
- `agentxp.stats.corrections` (adjust_pvalues)
- 5 agent markdown files, skill dispatcher
- Template experiment.yaml, report template, stats cheat sheet
- 7 sample-data CSVs

### Wave 1 (10 workstreams)
- `agentxp.data.*` — CSV/DuckDB/Snowflake loaders, schema discovery, unified LoadResult
- `agentxp.storage.*` — atomic experiment store, lifecycle state machine (11 states), log.jsonl history
- `agentxp.metrics.*` — MetricDefinition, MetricRegistry, test_function dispatch
- `agentxp.stats.cuped` — cuped_adjust, cuped_welch_test, variance_reduction
- `agentxp.stats.bayesian` — beta_binomial_test, normal_normal_test, expected_loss, probability_to_beat
- `agentxp.stats.sequential` — msprt_test, always_valid_ci, group_sequential_boundaries, sequential_proportion_test
- Pydantic `ExperimentConfig` schema at `agentxp/schemas/experiment.py` (partial — see gaps)
- 183 new tests

### Wave 2 (monitoring/amendments/validators/walkthroughs)
- `agentxp.monitoring.*` — srm_trend, guardrail_health, sample_accumulation, run_monitor with MonitorReport
- `agentxp.amendments.*` — AmendmentTracker, diff_experiments, classify_change, require_amendment_for_transition
- `agentxp.errors.*` — AgentXPError envelope + 5 subclasses + 17 error codes
- `agentxp.validators.*` — validate_experiment_yaml, validate_metric_yaml
- 72 new tests, 8 walkthrough markdown files + DEMO.md
- 11 walkthroughs total at `walkthroughs/` (over-delivery on the PRD's "7 walkthroughs")

### Wave 3 (missing fns + bayesian fix + trace + coverage)
- `agentxp.stats.ratio_power.power_ratio` — fills the Wave 1 C1 blocker
- `agentxp.stats.extension.extension_estimate` — fills C1 blocker
- `agentxp.stats.fishers.fishers_exact_test` — fills C1 blocker
- `agentxp.stats.guardrails.guardrail_test` + `denominator_srm` — fills C1 blocker
- `agentxp.stats.effect_size_extras.cohens_h` — fills C1 blocker (no CI)
- `agentxp.stats.prep.prepare_experiment_data` — fills C1 blocker
- `agentxp.stats._trace` — opt-in `computation_trace` per D.9 (Wave 1 C2)
- Normal-Normal Bayesian fix (Wave 1 M1)
- Additional test files (`test_missing_functions.py`, `test_trace.py`)

### Wave 3 parallel fix-up (in flight during this review)
- `srm_trend` threshold default tightened from 0.01 to 0.0005 (Wave 2 S4)
- `MonitorReport.persistence_error` field added (Wave 2 M5)
- Possibly more monitoring edits — not audited in this pass

## 3. Test suite state

Command: `cd /Users/shanebutler/projects/openxp && for i in 1 2 3; do .venv/bin/python -m pytest tests/ -q 2>&1 | tail -2; done`

```
367 passed in 4.94s
367 passed in 5.05s
367 passed in 5.04s
```

- **Total:** 367 tests
- **Runtime:** ~5 seconds, stable across runs
- **Flakiness:** Zero. Three consecutive reruns produced identical pass count and sub-5% runtime variance
- **Determinism:** All random-number generators use pinned seeds. No time-of-day dependencies. No filesystem pollution (every test uses `tmp_path`)

Test count trajectory: Wave 0 (~55) → Wave 1 (238) → Wave 2 (310) → Wave 3 (367). Each wave added tests covering new code.

## 4. PRD coverage summary

| Section | Area | v0.1 | v0.5 | v1.0 |
|---|---|---|---|---|
| §5.1 | `/experiment` modes | ~95% (8/8 modes documented, cold-start partial) | 100% | 100% |
| §5.2 | Agents | ~90% (5/5 v0.1+v0.5 agents, analyzer markdown lags MODES.md) | 100% | 0% (experiment-program deferred) |
| §5.3 | Stats functions | ~80% (all 32 functions exist; ~15 have signature drift from PRD) | ~70% (bootstrap + mann_whitney missing) | ~85% (all code exists; `monitor_trend` novelty/primacy detector missing) |
| §5.4 | experiment.yaml schema | ~60% (core blocks present; randomization/ramp_plan/holdback/alert_threshold/analysis_population missing; enum has 6 of 11 states) | ~60% | ~60% |
| §5.5 | Data discovery | 100% | 100% | 100% |
| §5.6 | Sample data | 100% | n/a | n/a |
| §5.7 | Metric definitions | ~60% (registry scaffolded, no yaml files, no test_family routing, no `templates/metric.yaml`) | ~60% | ~60% |
| §5.8 | Data architecture | 100% (CSV) | 100% (DuckDB) | ~60% (Snowflake not actually MCP) |
| §5.9 | Storage + history | 100% | 100% | 100% |
| §5.10 | Change tracking | n/a | 100% | 100% |
| §5.14 | Error handling | ~75% (AgentXPError envelope present, not universally wired into stats error returns) | ~75% | ~75% |
| §5.15 | Schema validation | ~70% (validator collects findings; Pydantic schema incomplete; result-type schemas empty) | ~70% | ~70% |
| App A | Interpretation tree | 100% (documented in MODES.md + interpreter agent) | 100% | 100% |
| App B | State machine | ~95% (11 states in `storage/lifecycle.py`; Pydantic enum conflict) | ~95% | ~95% |
| §9 | Build plan deliverables | ~75% | ~90% | ~80% |

Rough rollup: **v0.1 ~80% done, v0.5 ~80% done, v1.0 ~75% done** (counting the library surface only; GTM/PyPI/demo-GIF deliverables are out-of-scope for code review).

## 5. Known gaps (numbered)

1. **MODES.md and skill.md stats function import paths are wrong.** `agentxp.stats.power.power_ratio`, `.extension_estimate` live in `ratio_power.py` and `extension.py`. `agentxp.stats.ab_tests.fishers_exact_test` and `guardrail_test` live in `fishers.py` and `guardrails.py`. `agentxp.stats.srm.denominator_srm` lives in `guardrails.py`. `agentxp.stats.effect_size.cohens_h` lives in `effect_size_extras.py`. All are re-exported at `agentxp.stats` top level, but `from agentxp.stats.power import power_ratio` ImportErrors. `skill.md:151-158` and `MODES.md §2 step 2`, `MODES.md §3 step 5-6`, `MODES.md §4 step 2b`.

2. **Signature drift between MODES.md and real stats functions.** `prepare_experiment_data` uses `treatment_col=/metric_cols=/segment_cols=/winsorize_spec=`, not MODES.md's `variant_col/metric_col/unit_col/metric_type`. `power_ratio` uses `baseline_num_mean/baseline_den_mean/baseline_num_std/baseline_den_std/correlation_num_den`, not MODES.md's `num_mean/num_var/den_mean/den_var/cov`. `extension_estimate` uses `(current_n, current_mde_observed, required_power, baseline_variance, daily_traffic, alpha)`, not MODES.md's `(current_n, required_n, daily_traffic, allocation)`. `guardrail_test` uses `nim_relative=` not `nim=`. `cohens_h(p_control, p_treatment)` (no sample sizes, no CI). Full list in PRD_COVERAGE.md §5.3.

3. **Computation trace is opt-in and nothing turns it on.** `agentxp/stats/_trace.py` ships `_TRACE_ENABLED = False` by default. Live probe: `welch_test` returns a dict with no `computation_trace` key unless `set_trace(True)` was called. `MODES.md §4 interpret` step 2 validates `computation_trace` before advancing state — **this silently breaks the analyze→interpret handoff for every run** unless the orchestrator toggles the flag. The skill dispatcher does not mention `set_trace`.

4. **`agentxp/schemas/experiment.py` `ExperimentStatus` enum has 6 states, not 11.** Missing SHIPPED/COMPLETED/ABANDONED/INVALID/BLOCKED. `storage/lifecycle.py` `ALL_STATES` has all 11. Writing a COLLECTING-status yaml and loading it via `ExperimentConfig(**data)` fails Pydantic. The storage path round-trips as a dict so no current test hits this, but any future code path that validates-on-load crashes.

5. **`agentxp/schemas/results.py` is an empty scaffold.** PRD §5.3 mandates Pydantic models for TestResult / GuardrailResult / PowerResult / MDEResult / DurationResult / SRMResult / DiagnosisResult / EffectSize / LiftResult / ExtensionResult / CUPEDResult / SequentialResult / BayesianResult / TrendResult. None exist. Stats functions return plain dicts. The D.9 computation_trace contract is partially unenforceable because there's no typed schema to validate against.

6. **`srm_check` default threshold is 0.01, not 0.0005.** PRD §5.3 D.7 mandates 0.0005 as the hard-stop default. MODES.md passes `threshold=0.0005` at call sites, but direct library users (or Wave 1-era code) get the wrong tier. `agentxp/stats/srm.py` `srm_check(observed_counts, expected_ratios=None, threshold=0.01)`.

7. **`walkthroughs/monitoring.md` still documents the fabricated Wave 2 API.** The file exports `run_monitor(data=..., experiment_yaml=...)`, verdicts `HEALTHY/WATCH/WARN/STOP`, `srm_trend(..., window_days=7)`, `guardrail_health(guardrails=[...])`, `sample_accumulation(target_n=..., elapsed_days=...)`. None of these match the real API. Wave 2 C1 blocker not fixed. The "Note: the API above is the planned contract" disclaimer at `monitoring.md:101` is still there. If the fix-up agent is rewriting this file, this finding is moot.

8. **`pyproject.toml` not published to PyPI.** `pip install agentxp` from the README quick-start does not work against any registry. `pip install -e .` from a clone works.

9. **Missing v0.1 scaffolding:** `CONTRIBUTING.md`, hero GIF, two-path quick-start in README (CSV vs SQL), `templates/metric.yaml`, Decision framework presets (Strict/Balanced/Exploratory), Teaching mode (first-time user detection).

10. **v0.5 bootstrap_test and mann_whitney_test missing** — PRD §5.3 advanced block (v0.5). Not implemented. Nonparametric metrics path unavailable.

11. **v1.0 `monitor_trend` (novelty/primacy detector) missing.** PRD §5.3 advanced v1.0 block. `monitoring.srm_trend` is a per-window SRM drift check, not the D.37 time-windowed effect estimation the PRD calls for. No agent mode implements novelty/primacy detection.

12. **Wave 1 residual findings:** M1 `normal_normal_test` strong-prior math (believed fixed in Wave 3 per `bayesian.py` revisions, not re-verified in this pass); M2 `_msprt_core` dead algebra at `sequential.py:104`; S4 `snowflake_loader.where` raw-SQL injection; I3 microsecond-sort bug in `load_latest_analysis`.

13. **Metric registry not wired to designer agent.** `MetricDefinition.to_test_function` only routes to `proportion_test`/`welch_test`/`ratio_metric_test`. No `test_family` field for Bayesian/CUPED/sequential dispatch. Wave 1 I2 and Wave 2 I8 both flagged; unresolved.

14. **`experiment.yaml` template is incomplete** — no `randomization`, `alert_threshold`, `ramp_plan`, `holdback`, `analysis_population`, `schema_version`, `suspicious_lift_threshold`. Template at `templates/experiment.yaml`.

15. **Error envelope not universally wired into stats error returns.** PRD §5.14 wants `{error: True, error_type: ..., message: ..., suggestion: ...}` from stats functions. `sequential.py` mixes shapes (Wave 1 S2). `ab_tests.py` uses a plain `"error"` string. No stats function wraps `AgentXPError` yet.

## 6. What didn't get built (v2.0 punts + deferrals)

- **experiment-program.md** — program-level agent, velocity tracking, win/learning rate, EQ scoring, culture insights. PRD §5.2 v1.0 deliverable, deliberately punted.
- **Multi-armed bandits** — PRD §9 v2.0.
- **Interaction effects / subgroup analysis** — v2.0.
- **Metric recommendation engine** — v2.0.
- **Automated cron monitoring** — v2.0. Current monitoring is on-demand only.
- **Long-term holdout experiments** — v2.0 schema placeholder only.
- **Experiment knowledge graph** — v2.0.
- **Expression-eval pandas formulas with AST whitelist** — PRD §5.8 D.18 security model. Not implemented; metric definitions use SQL or column-ref only, which sidesteps the issue.
- **`schema_version` field on experiment.yaml** — deferred. No migration path yet.
- **Teaching mode / first-time user detection** — PRD v0.1 deliverable, not shipped.

## 7. Recommendations for post-review work (top 5)

1. **Signature reconciliation pass.** Either (a) rewrite MODES.md and skill.md to use the actual function signatures from `agentxp/stats/`, or (b) add shim wrappers in `agentxp.stats.power`, `agentxp.stats.ab_tests`, `agentxp.stats.srm`, `agentxp.stats.effect_size` that expose the PRD-spec signatures and forward to the real implementations. Option (a) is faster; option (b) preserves PRD-literal agent portability. Either way, the import paths in skill.md's Quick Reference table must match the real module layout or the re-exports at the `agentxp.stats` top level.

2. **Make computation_trace on by default for `/experiment` runs.** Either flip `_TRACE_ENABLED = True` at `agentxp/stats/_trace.py:36`, or have skill.md's dispatcher call `set_trace(True)` before every mode execution, or decorate every stats function to call `trace_dict` unconditionally. Current state is a silent analyze→interpret breakage on every run.

3. **Unify the state-machine source of truth.** Remove the `ExperimentStatus` enum from `agentxp/schemas/experiment.py` and have `ExperimentConfig.status` be `str` validated against `storage.lifecycle.ALL_STATES`. Or extend the enum to all 11 states. Current dual-source-of-truth will silently break anyone who instantiates `ExperimentConfig` from a yaml in a post-COLLECTING state.

4. **Fix `walkthroughs/monitoring.md` or delete it.** Wave 2 C1 blocker. Every code example in that file will TypeError against the real monitoring API. If the fix-up agent is rewriting it, verify against the live `run_monitor` / `srm_trend` / `guardrail_health` / `sample_accumulation` signatures from `agentxp.monitoring`.

5. **Fill `agentxp/schemas/results.py` with the 14 Pydantic models from PRD §5.3.** This lets the D.9 trace validator actually validate something, and lets the analyzer agent type-check its outputs before writing `analysis_results.json`. It's also the lowest-effort way to close the §5.15 gap.

## 8. README accuracy check

Read `/Users/shanebutler/projects/openxp/README.md` against the shipped code.

### Accurate
- "Statsig gives you a dashboard..." tagline — matches CLAUDE.md
- 8-mode command table — accurate, all modes are defined in skill.md
- "Every statistical function is auditable Python" — accurate
- Python usage example (welch_test, proportion_test, power_proportion, srm_check) — all imports resolve, all signatures match the example code
- Sample data table — all 6 CSVs exist in `sample-data/`
- Roadmap versioning (v0.1 working MVP / v0.5 monitoring / v1.0 CUPED+sequential+Bayesian+Snowflake) — accurate reflection of what shipped
- "MIT. Use it however you want." — `LICENSE` file present

### Inaccurate / outdated
- **"55 tests covering..."** (line 127) — actually 367 tests. Off by 312. Probably carried over from W0 baseline README.
- **"pip install agentxp"** (line 27) implies PyPI publication. Not published. Line 32 does say `cd agentxp && pip install -e .` which works, but the README cadence reads like `pip install agentxp` is an option.
- **Comparison table** claims CUPED, Sequential, Bayesian as "v1.0" (accurate as roadmap) but says "Every function" under "Code auditable" — which is true but glosses over the D.9 computation_trace being opt-in and off by default.
- **"How It Compares" — "Pre-registration | experiment.yaml"** — v0.1 label implies schema is complete. The schema is missing `schema_version`, `randomization`, `ramp_plan`, `holdback`, `alert_threshold`, `analysis_population`, `suspicious_lift_threshold` from PRD §5.4. The template at `templates/experiment.yaml` is incomplete relative to the PRD.
- **"Quick Start" `/experiment analyze sample-data/clean_ab.csv`** — will run successfully IF the orchestrator turns on tracing. See gap 3 above.
- **Docs table** — all 5 walkthrough links exist. Plus 6 more walkthroughs not linked (`bayesian.md`, `cuped.md`, `data-connectors.md`, `metric-definitions.md`, `monitoring.md`, `sequential.md`, `state-machine.md`). Under-links the shipped documentation.
- **No mention** of the monitoring, amendments, errors, validators modules. README Roadmap says "Monitoring" is v0.5 but the user-facing README reads as if the v0.5 surface is only `/experiment full` + `/experiment monitor` + DuckDB, omitting the amendments/validators/errors machinery that also shipped.
- **No hero GIF or demo video** — PRD §9 v0.1 explicitly mandates hero GIF + Power GIF for README. Not shipped.

Not a crisis — the README is broadly accurate on features, inaccurate on the test count number and the PyPI-install claim.
