# AgentXP Test Plan

**Author:** test-architecture pass, post-Wave 3 / pre-public-release.
**Audience:** the future build wave that will write these tests. This file is the *spec* — the tests do not exist yet.
**Repo state at write time:** 391 passing tests, 22 test files, 47 source modules across `openxp/{stats,data,storage,monitoring,amendments,validators,metrics,errors,schemas}`. v0.1 + v0.5 + v1.0 features shipped as code; agent/skill layer has known signature drift documented in `PRD_COVERAGE.md` and `FINAL_STATUS.md`.
**Read-only contract:** Nothing in this document modifies source code. It enumerates what must be tested, how, and in what order to write the tests.

---

## 0. TL;DR

- **Current state:** 391 tests, ~5s runtime, deterministic across reruns. Coverage is heavy on stats happy paths (CUPED, sequential, Bayesian, monitoring) and validators; thin on edge cases, fuzz inputs, simulation-grade statistical correctness, contract stability, and end-to-end skill flows.
- **Target state:** ~1100–1300 tests across 8 build waves (T1–T8), with pre-commit < 5s, PR check < 60s, PR-extended (sims/fuzz/bench) < 10min, nightly mutation + long sims < 60min. Every public function in `openxp.stats.*` has ≥3 unit tests + ≥1 property test; every load-bearing math function has a Monte-Carlo simulation test with explicit tolerance bands; every parser has a fuzz harness; every public API has a contract snapshot.
- **Biggest gaps right now (top 5):**
  1. **No simulation tests of statistical correctness** beyond a single mSPRT Type-I check. No Type-I/Type-II/coverage/calibration sims for `welch_test`, `proportion_test`, `ratio_metric_test`, `power_*`, `cuped_*`, Bayesian, group-sequential.
  2. **No property-based testing** at all (Hypothesis is not a dependency yet).
  3. **No fuzz harness** for the parsers (`CSVLoader`, `validate_experiment_yaml`, `validate_metric_yaml`, `MetricRegistry`, `discover_schema`, `diff_experiments`, YAML loaders).
  4. **No end-to-end mode tests** — the `/experiment` skill dispatcher has zero integration coverage (`tests/integration/` directory is empty). Cold-start path, full-mode resume, every Type-C checkpoint enforcement: untested.
  5. **No contract snapshot** — the public API surface (`openxp.stats.__init__` re-exports + return-dict shapes) can drift silently. Users will hit it; tests won't.

---

## 1. Test taxonomy

This section defines the test types. Every later section assigns each test to one of these types. CI ordering is in §15.

### 1.1 Unit
- **What:** single function, pure logic, no I/O.
- **Triggers in CI:** pre-commit + every PR check.
- **Runtime budget:** sub-millisecond per test; entire unit suite < 3s.
- **Pass/fail:** assertion-based. Hard pass/fail.
- **Examples:** `test_welch_test_returns_dict_with_expected_keys`, `test_relative_lift_zero_control_returns_inf_or_nan_per_contract`.

### 1.2 Integration
- **What:** crosses module boundaries. e.g., `stats → storage → amendments`, `data → discovery → prep → ab_tests`, `validators → schemas → lifecycle`.
- **Triggers in CI:** every PR check.
- **Runtime budget:** < 200ms per test; full integration suite < 20s.
- **Pass/fail:** assertion-based.
- **Examples:** `test_save_analysis_round_trips_through_load_latest_analysis`, `test_validator_rejects_yaml_in_state_not_in_lifecycle_all_states`.

### 1.3 End-to-end (E2E)
- **What:** a full `/experiment <mode>` flow simulated at the Python orchestrator level. The skill is markdown-driven, so E2E means: write a `runner` test that mimics what the agent would do (call the same stats, in the same order, write the same artifacts) and asserts the artifact set + content shape + state transitions. There will be one E2E per mode, plus one per `full` permutation (cold-start, resume from each starting state).
- **Triggers in CI:** every PR check.
- **Runtime budget:** < 1s per E2E; full E2E suite < 15s.
- **Pass/fail:** asserts that (a) all expected artifacts exist, (b) `experiment.yaml.status` ends in the expected state, (c) `analysis_results.json` has the expected verdict for each sample CSV (see §14), (d) every Type-C checkpoint that should fire, fires.

### 1.4 Property-based (Hypothesis)
- **What:** invariants that hold over generated inputs (arrays, dicts, dataframes, YAMLs).
- **Triggers in CI:** every PR check (with default 50 examples), nightly with 1000 examples.
- **Runtime budget:** < 5s per property; full property suite < 30s on PR, < 5min nightly.
- **Pass/fail:** assertion-based. Shrinking on failure.
- **Examples:** `welch_test`'s p-value is always in [0, 1]; `validate_transition` is True iff `(from, to) ∈ VALID_TRANSITIONS`; `diff_experiments` round-trips.

### 1.5 Simulation (Monte Carlo)
- **What:** statistical correctness via repeated sampling. Type-I rate, Type-II rate, CI coverage, calibration of power formulas, decision consistency under repeated draws.
- **Triggers in CI:** PR-extended (label `run-heavy`); always nightly.
- **Runtime budget:** 30s–10min per simulation; full sim suite ≤ 30 min nightly.
- **Pass/fail:** **explicit tolerance bands.** A Type-I rate of 0.05 is allowed in [0.045, 0.055] with N=10000 reps (approximate ±2σ Monte Carlo). A coverage rate of 0.95 is allowed in [0.94, 0.96]. Tolerances written into the test and justified in a comment.
- **Examples:** `test_welch_type_i_rate_under_null` (10k reps, expect ~0.05).

### 1.6 Snapshot
- **What:** freeze a known-good output (a JSON, a markdown, a dict, the public API signature list) and regression-detect.
- **Triggers in CI:** every PR check.
- **Runtime budget:** < 100ms per snapshot.
- **Pass/fail:** byte-equal (or canonical-form-equal for floats with rounding). Failures require the user to re-bless via `pytest --snapshot-update`.
- **Examples:** the contract snapshot in `tests/contracts/`, the `analysis_results.json` shape for `clean_ab.csv`, the `interpretation.md` for each canonical scenario.

### 1.7 Fuzz
- **What:** random malformed inputs, must never crash with an unhandled exception, must always return either a structured `OpenXPError` or a structured `ValidationReport`.
- **Triggers in CI:** PR-extended (label `run-heavy`); always nightly.
- **Runtime budget:** 1k–10k iterations per fuzz target, < 60s each, < 5 min total.
- **Pass/fail:** "no uncaught exception" + "structured error output". Uses Hypothesis strategies with `@settings(suppress_health_check=[...])` for slow generators.
- **Examples:** `fuzz_csv_loader`, `fuzz_validate_experiment_yaml`, `fuzz_diff_experiments`.

### 1.8 Stress / load
- **What:** large data, long experiments, high variant counts, deep nesting.
- **Triggers in CI:** PR-extended (`run-heavy`); always nightly.
- **Runtime budget:** < 60s per test; full stress suite < 5 min.
- **Pass/fail:** "completes within budget" + "no memory blowup" (use `psutil` or `tracemalloc.get_traced_memory()`). Fast-fail tests assert the function refuses (returns `OpenXPError` with `data_too_large` code) rather than OOM-ing.

### 1.9 Determinism
- **What:** same input + same seed → byte-identical output, repeated N=3 times in-process and at least once cross-process.
- **Triggers in CI:** every PR check.
- **Runtime budget:** < 200ms per test.
- **Pass/fail:** assertion-based. Any RNG without a seed argument is a test failure.

### 1.10 Mutation
- **What:** mutate source code (e.g., flip `+` to `-`, change `<` to `<=`), verify the test suite catches the mutation. Run via `mutmut` or `cosmic-ray`.
- **Triggers in CI:** nightly only (or weekly if too slow).
- **Runtime budget:** 10–60 min per target module.
- **Pass/fail:** mutation score ≥ 80% per load-bearing math function (§12).

### 1.11 Benchmark
- **What:** optimize-for, not pass/fail. Time + memory measurements via `pytest-benchmark`. Each benchmark has a baseline locked in via `--benchmark-save`. Regressions > 2× baseline fail CI.
- **Triggers in CI:** PR-extended (`run-heavy`); always nightly.
- **Runtime budget:** see §8.
- **Pass/fail:** alerts (warning) on > 1.5× baseline; fails on > 2× baseline.

### 1.12 Security
- **What:** credential masking, SQL injection, path traversal, YAML bombs, ReDoS, pickle scanning.
- **Triggers in CI:** every PR check.
- **Runtime budget:** < 100ms per test.
- **Pass/fail:** assertion-based.

### 1.13 Contract
- **What:** public API stability. Asserts the set of exported symbols in `openxp.__init__`, `openxp.stats.__init__`, `openxp.data.__init__`, `openxp.storage.__init__`, `openxp.monitoring.__init__`, `openxp.amendments.__init__`, `openxp.validators.__init__`, `openxp.errors.__init__`, `openxp.metrics.__init__`. Asserts the signature of every `__all__` entry (positional args, kwargs, defaults, return annotation if present). Asserts the minimum set of return-dict keys for every stats function (must include `interpretation`).
- **Triggers in CI:** pre-commit + every PR check.
- **Runtime budget:** < 1s for the full contract suite.
- **Pass/fail:** byte-equal against `tests/contracts/api_v1.json`. Breaking changes require a deliberate `--snapshot-update` and a major-version bump in `pyproject.toml`.

### 1.14 Lifecycle / state machine
- **What:** every legal transition + every illegal transition for the 11-state DAG in `openxp/storage/lifecycle.py`. Plus every backward transition's amendment requirement.
- **Triggers in CI:** every PR check.
- **Runtime budget:** < 5s for the full lifecycle suite (it's > 100 small assertions).
- **Pass/fail:** assertion-based.

### 1.15 Compatibility
- **What:** runs under Python 3.10/3.11/3.12 × (linux, macos) × (duckdb on/off, snowflake on/off) × (numpy 1.26/2.0) × (pandas 2.0–2.2).
- **Triggers in CI:** PR-extended (`run-heavy`) for the matrix; always release.
- **Runtime budget:** the unit suite × N matrix entries; usually < 15 min in parallel.
- **Pass/fail:** unit suite passes on every supported combo.

---

## 2. Use case inventory

Every use case AgentXP supports, grouped by layer. Each entry is `intent → input → output → preconditions`.

### 2.1 CLI / skill layer (8 modes)

#### 2.1.1 `/experiment design`
| Variant | Intent | Input | Output | Preconditions |
|---|---|---|---|---|
| Fresh design | "I want to design a new test" | hypothesis (free text), optional baseline data | `experiments/<slug>/experiment.yaml` (POWERED), `design-brief.md`, `working/sensitivity-table.csv` | No yaml in target dir |
| From template | "Use template X for new test" | template path, slug | populated yaml in DESIGNING then POWERED | template exists in `templates/` |
| Invalid args (no hypothesis) | "design" with empty positional | none | error: "hypothesis required" | n/a |
| Resume DESIGNING | "Continue designing experiment X" | existing yaml in DESIGNING | updated yaml | yaml status == DESIGNING |
| Refuse on POWERED+ | "design" against an existing POWERED yaml | yaml in POWERED | error: "already designed; use /experiment power to recompute" | — |
| Power viability NOT_VIABLE | hypothesis with absurd MDE | mde=1e-6 | hard stop, options menu | — |
| Cold-start refuse | "design" with `--data` (a data file) | data file present | resolves ambiguity per dispatch (§4 of MODES.md), prefers analyze cold-start | — |

#### 2.1.2 `/experiment power`
| Variant | Intent | Input | Output | Preconditions |
|---|---|---|---|---|
| Proportion | "How many users to detect 5% lift on a 10% rate?" | `baseline_rate=0.10, mde_relative=0.05` | `power_proportion` result + `duration_estimate` + `power-report.md` | none |
| Mean (continuous) | "Sample size for revenue with std=20" | `baseline_mean=50, baseline_std=20, mde_relative=0.05` | `power_mean` result | none |
| Ratio | "Sample size for revenue/session" | num/den means + stds + correlation | `power_ratio` result | none |
| Sensitivity table | "Show me the MDE × traffic trade-off" | `baseline_rate, mde_values, traffic_values` | `power_sensitivity_table` CSV | none |
| Standalone (no yaml) | "Power calc" | inputs as kwargs | report only | — |
| Recompute against existing yaml | "Re-power experiment X with new MDE" | yaml in POWERED + new mde | overwrites power block, asks user | — |
| Invalid: missing `baseline_std` for continuous | — | only `baseline_mean` | error | — |
| Invalid: `mde_relative >= 1.0` for proportion with rate > 0.5 | — | impossible relative lift | warning or hard stop | — |
| NOT_VIABLE → hard stop | impossibly tight MDE | — | Type-C checkpoint | — |

#### 2.1.3 `/experiment analyze`
| Variant | Intent | Input | Output | Preconditions |
|---|---|---|---|---|
| With yaml (happy path) | "Analyze experiment X" | data file + yaml in COLLECTING | `analysis_results.json`, `reports/analysis.md`, status → ANALYZING | yaml COLLECTING/ANALYZING |
| Cold-start (no yaml) | "analyze X.csv" | csv only | analysis with default decision rules + upgrade nudge | — |
| Each sample CSV | per §14 | each of the 7 sample CSVs | the verdict in §14 | — |
| SRM BLOCK | data with broken randomization | srm_violation.csv | hard stop, INVALID written | — |
| Min-sample BLOCK | < 50% of planned n | underpowered_to_50pct.csv | hard stop | yaml has `power.sample_size_per_group` |
| Min-sample WARN | 50% ≤ n < 100% | half-sample csv | type-B warning + MDE shown | — |
| Guardrail BLOCK | guardrail breach > NIM | guardrail_violation.csv | type-C, INVESTIGATE branch | yaml has guardrails |
| Mixed metric types | proportion + continuous + ratio in one yaml | mixed.csv | three different test_function dispatches | — |
| Wrong state | analyze on yaml in DESIGNING | — | error "no data yet" | — |
| Schema drift | data file has different cols than yaml expects | — | warning + dynamic dispatch | — |

#### 2.1.4 `/experiment interpret`
| Variant | Intent | Input | Output | Preconditions |
|---|---|---|---|---|
| Branch 1 INVALID | from SRM-BLOCK analyze | INVALID `analysis_results.json` | INVALID interpretation, terminal | — |
| Branch 2 SHIP | clean positive | clean_ab.csv post-analyze | SHIP, conditions, monitoring plan | — |
| Branch 3 INVESTIGATE | positive + guardrail breach | guardrail_violation.csv post-analyze | INVESTIGATE, trade-off quantified | — |
| Branch 4 ABORT | significant negative | abort scenario csv (TBD) | ABORT, kill recommendation | — |
| Branch 5a LEARN (powered) | well-powered null | no_effect.csv | LEARN, "feature doesn't move metric" | — |
| Branch 5b LEARN (underpowered) | null + observed MDE > planned | underpowered.csv | LEARN, `extension_estimate` called | — |
| Branch 5c LEARN (practically insignificant) | tiny significant lift below threshold | trivial_lift csv (TBD) | LEARN, "real but too small" | yaml has `minimum_practical_significance` |
| Alert threshold breach | guardrail > absolute alert | extreme guardrail csv | INVALID (hard safety ceiling) | yaml has `alert_threshold` |
| Suspicious lift caveat | abs(rel_lift) > 0.20 | extreme_lift csv | classification unchanged + Twyman caveat | — |
| Missing trace | analyze run with `set_trace(False)` | analysis without `computation_trace` | refuse, surface which call lacks trace | — |

#### 2.1.5 `/experiment monitor`
| Variant | Intent | Input | Output | Preconditions |
|---|---|---|---|---|
| All GREEN | clean midflight data | csv with timestamps, no SRM, no guardrail breach | report.status=GREEN, no recs | — |
| YELLOW SRM | drift but not yet RED | drifting csv | report.status=YELLOW, monitor closely | — |
| RED SRM | SRM p ≤ 0.0005 | broken randomization midflight | report.status=RED, type-C halt, srm_diagnose called | — |
| RED guardrail | guardrail past NIM CI bound | guardrail breach midflight | RED, emergency halt offered | — |
| Sample accumulation behind | days_elapsed=10, current_n=50% expected | — | YELLOW or RED on pace | yaml has `power.sample_size_per_group`, daily_traffic |
| Stalled day-0 | days_elapsed=0, current_n=0, daily_traffic>0 | — | YELLOW per §M1 of WAVE2_REVIEW | — |
| Persistence error | bogus experiment_id passed to store | — | report still produced + `recommendations` annotated | per Wave 2 M5 |
| Trend (multi-day history) | 3+ prior monitoring reports in history.yaml | — | trend annotation in report | — |

#### 2.1.6 `/experiment report`
| Variant | Intent | Input | Output | Preconditions |
|---|---|---|---|---|
| Executive | `--audience executive` | INTERPRETED yaml + analysis | report with no p-values in body | — |
| Technical | `--audience technical` | — | full detail incl methodology | — |
| Cross-functional (default) | — | — | mid-density | — |
| Slack format | `--format slack` | — | `.slack.txt` artifact | — |
| Email format | `--format email` | — | `.email.html` artifact | — |
| Amendment included | yaml has non-empty amendments.jsonl | — | report mentions each amendment | — |
| Refuse on missing classification | yaml without `results.ewl_classification` | — | error | — |

#### 2.1.7 `/experiment full`
| Variant | Intent | Input | Output | Preconditions |
|---|---|---|---|---|
| Happy path (greenfield + data) | hypothesis + data | — | reaches REPORTED | — |
| Resume from POWERED | yaml POWERED + data | — | starts at analyze | — |
| Resume from ANALYZING | analysis_results exists, no interpretation | — | starts at interpret | — |
| Halt at SRM gate | data with SRM | — | halts in analyze | — |
| Halt at ship decision | clean SHIP candidate | — | halts in interpret awaiting confirmation | — |
| Failure at design (NOT_VIABLE) | impossible MDE | — | halts in design | — |
| Failure mid-pipeline preserves state | — | yaml stays at last completed state | — |
| Re-invoke after halt | run `full` again | — | picks up from current status | — |

#### 2.1.8 `/experiment status`
| Variant | Intent | Input | Output | Preconditions |
|---|---|---|---|---|
| Each of the 11 lifecycle states | yaml in each state | — | print + suggested next mode | — |
| Inconsistent state | status=POWERED but power.sample_size_per_group is null | — | warn user | — |
| Missing yaml | run `status` in dir without yaml | — | "no experiment.yaml found" | — |
| Corrupted yaml | broken yaml | — | parse error + line number | — |

### 2.2 Python library layer (every public surface)

#### 2.2.1 `openxp.stats.*` — 31 public functions to test (one of these is missing from the count if you collapse `set_trace`/`is_trace_enabled`)

```
ab_tests:        welch_test, proportion_test, ratio_metric_test, winsorize
fishers:         fishers_exact_test
guardrails:      guardrail_test, denominator_srm
power:           power_proportion, power_mean, detectable_effect, duration_estimate, power_sensitivity_table
ratio_power:     power_ratio
extension:       extension_estimate
srm:             srm_check, srm_diagnose
effect_size:     cohens_d, relative_lift
effect_size_extras: cohens_h
corrections:     adjust_pvalues
prep:            prepare_experiment_data
cuped:           cuped_adjust, variance_reduction, cuped_welch_test
sequential:      msprt_test, always_valid_ci, group_sequential_boundaries, sequential_proportion_test
bayesian:        beta_binomial_test, normal_normal_test, expected_loss, probability_to_beat
_trace:          set_trace, is_trace_enabled
```

For each: user intent (named in CLAUDE.md table), inputs, expected output dict keys, preconditions.

#### 2.2.2 `openxp.data.*`
- `CSVLoader.load(path) → LoadResult`
- `CSVLoader.stream(path, chunksize) → Iterator[DataFrame]`
- `DuckDBLoader.load_query(sql)`, `DuckDBLoader.load_table(table_name)`
- `SnowflakeLoader.load_experiment(experiment_id, where=None)`
- `discover_schema(df) → SchemaDiscovery`
- `LoadResult.to_dict()`, `SchemaDiscovery.to_dict()`

For each: file paths, query strings, expected `LoadResult` shape (`df, schema, source_type, n_rows, n_cols, dtypes, warnings`), error envelope on failure.

#### 2.2.3 `openxp.storage.*`
- `ExperimentStore(root)` — constructor
- `save_experiment`, `load_experiment`
- `save_analysis`, `load_latest_analysis`, `list_analyses`
- `save_interpretation`
- `save_report`
- `history(experiment_id)`
- `list_experiments(status=None)`
- `delete_experiment(experiment_id)`
- `_log_path`, `_yaml_path`, `_analyses_dir` (test as semi-public, used by `amendments`)
- `lifecycle.validate_transition`, `lifecycle.is_backward`

#### 2.2.4 `openxp.amendments.*`
- `Amendment` dataclass (validation in `__post_init__`)
- `AmendmentTracker.append(experiment_id, change_path, before, after, reason)`
- `AmendmentTracker.list(experiment_id)`
- `AmendmentTracker.require_amendment_for_transition(from_state, to_state)`
- `diff_experiments(before_dict, after_dict) → list[Change]`
- `classify_change(change) → "material" | "administrative"`

#### 2.2.5 `openxp.monitoring.*`
- `srm_trend(df, treatment_col, timestamp_col, window, threshold, expected_ratios)`
- `guardrail_health(df, treatment_col, guardrail_metrics, thresholds, ...)`
- `sample_accumulation(current_n, required_n, daily_traffic, days_elapsed, planned_duration_days, now)`
- `run_monitor(experiment_id, data_loader, store=None, current_n_fn=None) → MonitorReport`
- `MonitorReport.to_dict()`, `MonitorReport.persistence_error`

#### 2.2.6 `openxp.validators.*`
- `validate_experiment_yaml(path_or_dict) → ValidationReport`
- `validate_metric_yaml(path_or_dict) → ValidationReport`
- `ValidationReport.ok`, `ValidationReport.findings`, `ValidationReport.errors`, `ValidationReport.warnings`

Plus: every individual validator rule in `experiment_validator.py` and `metric_validator.py` (see edge case atlas §3 and gap analysis §4).

#### 2.2.7 `openxp.metrics.*`
- `MetricDefinition` (Pydantic model — required/optional fields)
- `MetricRegistry` — `load_from_file`, `load_from_dir`, `get`, `list_all`
- `MetricDefinition.to_test_function()` — dispatch routing

#### 2.2.8 `openxp.errors.*`
- `OpenXPError(code, message, hint, severity, details)` — constructor + `__str__` + `to_dict`
- Each subclass: `ValidationError`, `DataError`, `StatsError`, `StorageError`, `LifecycleError`
- `errors.codes.*` — all 17 error codes exist + have a default message + a default hint

#### 2.2.9 `openxp.schemas.*`
- `ExperimentConfig` Pydantic model
- `ExperimentStatus` enum (currently 6 states; should be 11 — see §3 lifecycle edge cases)
- `EwlClassification` enum
- `openxp.schemas.results.*` — empty scaffold today (see §FINAL_STATUS gap 5); test plan assumes it gets populated and includes coverage requirements for the 14 result-type Pydantic models PRD §5.3 mandates

### 2.3 Data / schema layer

- `experiment.yaml` schema (every field, every required vs optional, every enum value, every cross-field rule)
- `metric.yaml` schema (every field)
- Result models (TestResult, GuardrailResult, PowerResult, MDEResult, DurationResult, SRMResult, DiagnosisResult, EffectSize, LiftResult, ExtensionResult, CUPEDResult, SequentialResult, BayesianResult, TrendResult)

---

## 3. Edge case atlas

This is the long section. Each row has: **trigger / expected behavior / test type / pass-or-benchmark**. Grouped by category. References tests in the existing 391-test suite where they already cover the case (so we don't duplicate).

Key for `Type` column: U=Unit, I=Integration, P=Property, S=Simulation, F=Fuzz, St=Stress, D=Determinism, Sn=Snapshot, Se=Security, C=Contract, L=Lifecycle, B=Benchmark, Co=Compatibility.
Key for `P/B` column: P=Pass/fail, B=Benchmark.
Key for `Status`: NEW=needs writing, EXIST=already in suite, EXTEND=in suite but needs broader assertions.

### 3.1 Statistical edge cases (apply to every stats function)

| # | Trigger | Expected | Type | P/B | Status | Notes |
|---|---|---|---|---|---|---|
| ST-001 | Zero variance in control array (all values identical) | `welch_test` returns `error: True, error_type: zero_variance` per PRD §5.3 D.12 | U | P | NEW | ab_tests.py uses string error today; assert the contract |
| ST-002 | Zero variance in treatment array | same | U | P | NEW | |
| ST-003 | Zero variance in BOTH arrays, same mean | `welch_test` returns error or treats as `relative_lift=0, p=1.0` (pick one in contract) | U | P | NEW | currently implementation-defined; needs explicit contract |
| ST-004 | Zero variance in BOTH, different means | unambiguously not equal; expected error | U | P | NEW | |
| ST-005 | Single observation per group (n=1 each) | `error: insufficient_data, n must be >= 2` | U | P | NEW | minimum from PRD: n≥30 for parametric; warn at n<100 for proportions |
| ST-006 | n=2 per group | warning + still computes (welch can do it) | U | P | NEW | edge of mathematical validity |
| ST-007 | n=29 per group (just below PRD minimum 30) | warning emitted | U | P | NEW | PRD §5.14 says "Functions check n>=30" |
| ST-008 | n=30 exactly | no warning, runs cleanly | U | P | NEW | boundary |
| ST-009 | n=99 per group for `proportion_test` | warning per GrowthBook rule (≥100 conversion events) | U | P | NEW | |
| ST-010 | n=1M per arm for `welch_test` | numerically stable; t-stat finite; p-value not 0 or 1 due to underflow | St,B | P+B | NEW | benchmark target <100ms |
| ST-011 | n=10M per arm | either completes in <2s OR returns `data_too_large` error | St | P | NEW | |
| ST-012 | Extreme proportions: c_success=0, c_n=10000 vs t_success=1, t_n=10000 | finite p-value, no division-by-zero, fishers_exact_test fallback recommended | U | P | NEW | perfect separation lower bound |
| ST-013 | Extreme proportions: c_success=10000 vs t_success=10000 (perfect separation upper bound) | finite, p≈1.0 | U | P | NEW | |
| ST-014 | proportion 0.9999 vs 1.0 (boundary near 1) | finite p-value, no log(0) | U | P | NEW | |
| ST-015 | proportion 0.0001 vs 0.0 | finite p-value | U | P | NEW | |
| ST-016 | revenue with extreme positive skew (lognormal sigma=3) | welch is biased; test `winsorize` is recommended; `cohens_d` magnitude tag is meaningful | U,S | P | NEW | the heavy-tail case PRD calls out |
| ST-017 | revenue with one extreme outlier (e.g., $1M in a $50-mean array of n=1000) | post-winsorize result is stable; pre-winsorize result is dominated | U | P | NEW | |
| ST-018 | NaN in control array | dropped per metric type rule (PRD §5.13 D.4); count reported | U | P | NEW | for ratio: drop if numerator OR denom NaN |
| ST-019 | NaN in treatment array | same | U | P | NEW | |
| ST-020 | All NaN in a column | error: `invalid_input`; specific message | U | P | NEW | |
| ST-021 | inf in control | dropped or error per contract | U | P | NEW | needs explicit contract decision |
| ST-022 | -inf in control | same | U | P | NEW | |
| ST-023 | NaN in `power_proportion(baseline_rate=NaN)` | error before any compute | U | P | NEW | |
| ST-024 | `baseline_rate=0.0` for `power_proportion` | error: cannot compute SE on zero rate | U | P | NEW | |
| ST-025 | `baseline_rate=1.0` for `power_proportion` | error or warning | U | P | NEW | |
| ST-026 | `mde_relative=0.0` | error: no detectable effect | U | P | NEW | |
| ST-027 | `mde_relative=-0.1` (negative MDE) | error: must be positive | U | P | NEW | |
| ST-028 | `mde_relative=10.0` (1000% lift) | warning, but still computes (maybe absurdly small n) | U | P | NEW | |
| ST-029 | `alpha=0.0` | error | U | P | NEW | |
| ST-030 | `alpha=1.0` | error | U | P | NEW | |
| ST-031 | `alpha=0.5` (unusual but valid) | runs, no warning | U | P | NEW | |
| ST-032 | `power=0.5` (low) | runs, possibly warns | U | P | NEW | |
| ST-033 | `power=1.0` | error: would require infinite n | U | P | NEW | |
| ST-034 | Duplicate user ids in `prepare_experiment_data` (same unit_id appears in both arms — crossover) | dropped per PRD §5.13; `n_rows_dropped` reflects | I | P | NEW | |
| ST-035 | Same unit_id appears multiple times in same arm | dedup or aggregate per `prepare_experiment_data` config | I | P | NEW | |
| ST-036 | Ties in continuous data | doesn't affect welch; affects mann_whitney (when implemented) | U | P | NEW | |
| ST-037 | Negative counts to `proportion_test` | error | U | P | NEW | |
| ST-038 | `c_success > c_n` | error | U | P | NEW | |
| ST-039 | Float counts to `proportion_test` (e.g., 350.5) | accept (rounds to int) or error per contract | U | P | NEW | |
| ST-040 | `proportion_test` expected cell count < 5 in any cell | warning emitted recommending `fishers_exact_test`; PRD says return error+suggestion | U | P | NEW | currently the analyzer agent handles; assert function emits structured warning |
| ST-041 | `fishers_exact_test` with n=200 (where exact is slow) | completes in <500ms | U,B | P+B | NEW | |
| ST-042 | `fishers_exact_test` with n=10000 (exact intractable) | falls back to a chi-square approximation OR returns error to use proportion_test | U | P | NEW | needs contract |
| ST-043 | Time-varying treatment effects (effect grows over experiment duration) | analyzer doesn't crash; novelty/primacy detector (when implemented) flags it | I | P | NEW | placeholder for `monitor_trend` |
| ST-044 | Multiple observations per user (panel data) — `prepare_experiment_data` collapses to per-user aggregate | counts match, no double-counting in test | I | P | NEW | |
| ST-045 | Day-of-week confound in `srm_trend` | per-window srm_check picks it up if window=1d | I | P | NEW | |
| ST-046 | Bayesian: `beta_binomial_test` with `prior_alpha=0, prior_beta=0` (improper prior) | error or accept with warning | U | P | NEW | |
| ST-047 | Bayesian: `beta_binomial_test` strong prior pulls posterior into impossible region | shouldn't be possible (Beta is bounded); test that it never reports >1 prob | U,P | P | NEW | property test |
| ST-048 | Bayesian: `normal_normal_test` with `prior_sd=0.001` (extremely strong prior) | NIG conjugate posterior now handles strong priors correctly — test should assert CURRENT-correct behavior, remove `xfail` (resolved — see §18 Q4) | U | P | NEW | reference open issue |
| ST-049 | Bayesian: `n_samples=10` (tiny MC) | runs, returns wide CrI; deterministic with seed | U,D | P | NEW | |
| ST-050 | Bayesian: `n_samples=500_000` (huge MC) | completes in <2s; benchmark | St,B | P+B | NEW | |
| ST-051 | Bayesian seed determinism: same seed → byte-identical sample arrays | always | D | P | EXIST | covered in test_bayesian.py; verify |
| ST-052 | CUPED: `var(pre) = 0` → theta = 0 fallback | covered in cuped.py:67 but no test | U | P | NEW | per WAVE1 T5 |
| ST-053 | CUPED: `cov(pre, post) = 0` → theta = 0, no variance reduction | runs cleanly; variance reduction reported as 0 | U | P | NEW | |
| ST-054 | CUPED: ρ = 1.0 (post = pre) → theta = 1, variance reduction = 100% | runs; tests claim 100% reduction | U,P | P | NEW | property: ρ ≥ 0.5 → vr ≥ 20% |
| ST-055 | CUPED: ρ → ∞ when var(pre) → 0 | the `if raw_var > 0` guard in cuped.py:331 catches this; test exercises | U | P | NEW | |
| ST-056 | CUPED: pre and post different lengths | error: aligned arrays required | U | P | NEW | |
| ST-057 | CUPED: pre array contains NaN | error per `_check_no_nan` | U | P | EXIST? | check `test_cuped.py` |
| ST-058 | Sequential: peeking at n=0 (first peek before any data) | error: insufficient data | U | P | NEW | |
| ST-059 | Sequential: peeking at n=1 | error: n_eff < 2 | U | P | NEW | |
| ST-060 | Sequential: first peek at the boundary n_min | runs, returns CONTINUE typically | U | P | NEW | |
| ST-061 | Sequential mSPRT Type-I rate under unlimited peeking, 10k reps × 20 peeks | rate ≤ 0.05 + 1σ MC tolerance | S | P | EXIST/EXTEND | currently 500 reps; tighten to 10k |
| ST-062 | Sequential mSPRT power under H1 with effect = mde | power ≥ 0.70 (slightly degraded vs fixed-n 0.80) | S | P | NEW | |
| ST-063 | Group sequential boundaries: O'Brien-Fleming monotone decreasing | covered | U | P | EXIST | per test_sequential.py |
| ST-064 | Group sequential Type-I under 5 interim looks with O-F spending | rate ≤ 0.05 + tolerance | S | P | NEW | |
| ST-065 | Group sequential Pocock spread is roughly constant | covered | U | P | EXIST | |
| ST-066 | always_valid_ci coverage at α=0.05 with random walks under null | coverage ≥ 0.95 | S | P | NEW | |
| ST-067 | Multiple comparisons: Holm vs Bonferroni vs BH agree on count of rejections under null | with 10k reps, all three reject ~5% of families at α=0.05 | S | P | NEW | |
| ST-068 | adjust_pvalues with empty list | error or empty result | U | P | NEW | |
| ST-069 | adjust_pvalues with single p-value | unchanged | U | P | NEW | |
| ST-070 | adjust_pvalues with all NaN | error | U | P | NEW | |
| ST-071 | adjust_pvalues with p-values outside [0,1] | error | U | P | NEW | |
| ST-072 | `relative_lift(0, 0)` | NaN or 0 (define contract) | U | P | NEW | |
| ST-073 | `relative_lift(0, 1)` | inf (define contract) | U | P | NEW | |
| ST-074 | `relative_lift(-1, 1)` (negative control) | finite negative or NaN per contract | U | P | NEW | edge case for cost metrics |
| ST-075 | `cohens_d` with identical control/treatment | d=0, magnitude=Negligible | U | P | NEW | |
| ST-076 | `cohens_d` huge effect (d=5) | magnitude=Large | U | P | NEW | |
| ST-077 | `cohens_h` with p_control=0, p_treatment=1 | h=π (max) | U | P | NEW | |
| ST-078 | `srm_check` with n_total=0 | error | U | P | NEW | |
| ST-079 | `srm_check` with single arm (1 count, expected 2) | error: must have ≥ 2 groups | U | P | NEW | |
| ST-080 | `srm_check` with 4 variants (multi-arm) | runs, applies multi-cell chi-square | U | P | NEW | |
| ST-081 | `srm_check` with `expected_ratios=[0.1, 0.9]` | runs, asymmetric | U | P | NEW | |
| ST-082 | `srm_check` with `expected_ratios` summing to 0.99 (off by 0.01) | normalize or error per contract | U | P | NEW | |
| ST-083 | `srm_diagnose` with no segments (only one segment column with 1 unique value) | returns "no segments to diagnose" | U | P | NEW | |
| ST-084 | `srm_diagnose` with 100 segments | completes; reports top-N by chi-square contribution | U,B | P+B | NEW | |
| ST-085 | `denominator_srm` with all denominators = 0 | error | U | P | NEW | |
| ST-086 | `denominator_srm` with den_c=1, den_t=1000000 (extreme imbalance) | strong BLOCK | U | P | NEW | |
| ST-087 | `power_proportion` calibration: simulated A/B at the computed n with the planned MDE achieves ≥80% power | with 10k reps, observed power ∈ [0.78, 0.82] | S | P | NEW | calibration sim |
| ST-088 | `power_mean` calibration: same | same | S | P | NEW | |
| ST-089 | `power_ratio` calibration with correlation_num_den=0.7 | same | S | P | NEW | |
| ST-090 | `power_proportion` baseline_rate=0.5 (max variance) gives largest n | property | U,P | P | NEW | |
| ST-091 | `power_proportion` n is monotone-decreasing in mde_relative | property | U,P | P | NEW | |
| ST-092 | `duration_estimate` with daily_traffic=0 | infinite duration; viable=NOT_VIABLE | U | P | NEW | |
| ST-093 | `duration_estimate` with allocation=0 | error | U | P | NEW | |
| ST-094 | `duration_estimate` rounds to 7-day multiple per D.27 | weekly cadence assertion | U | P | NEW | |
| ST-095 | `extension_estimate` when underpowered run is just 1 day short | feasible=True, additional_days=1 | U | P | NEW | |
| ST-096 | `extension_estimate` when extension would exceed 56-day threshold | feasible=False | U | P | NEW | |
| ST-097 | `extension_estimate` accuracy of day prediction within ±1 day on synthetic | empirical: simulate, observe stop day, compare | S | P | NEW | |
| ST-098 | `guardrail_test` with NIM=0 (zero tolerance) | even tiny degradation triggers BLOCK | U | P | NEW | |
| ST-099 | `guardrail_test` with NIM=∞ | always PASS | U | P | NEW | |
| ST-100 | `guardrail_test` with `invert=True` for latency | "lower is better"; positive lift in latency = degradation | U | P | NEW | |
| ST-101 | `prepare_experiment_data` drops > 5% of rows → warning surfaced | per Wave 3 prep contract | I | P | NEW | |
| ST-102 | `prepare_experiment_data` cannot resolve treatment column → raises | per MODES.md §3 step 2 | I | P | NEW | |
| ST-103 | `prepare_experiment_data` with two treatment-column candidates ("variant" and "group") → asks (in test, simulate via parameter) | resolves via explicit `treatment_col=` | I | P | NEW | |

### 3.2 Data edge cases

| # | Trigger | Expected | Type | P/B | Status |
|---|---|---|---|---|---|
| DE-001 | Empty DataFrame to `discover_schema` | returns empty schema, no crash | U | P | NEW |
| DE-002 | Single row DataFrame | runs, all metric candidates flagged with low-confidence | U | P | NEW |
| DE-003 | Single column DataFrame | no treatment col detectable; warning | U | P | NEW |
| DE-004 | Missing treatment column entirely | discovery returns `treatment_col=None`; downstream error from `prepare_experiment_data` | I | P | NEW |
| DE-005 | Two candidates for treatment column ("variant" and "group" both present) | discovery flags ambiguity; both in `treatment_candidates` | U | P | NEW |
| DE-006 | Non-standard control value: "A" / "baseline" / 0 / "False" / "ctrl" | hint matching catches each | U,P | P | EXTEND | partly tested in test_data_discovery.py |
| DE-007 | Unicode in column names: "ärm", "vàriànt", "性别" | discovery treats as opaque strings; no crash | U | P | NEW |
| DE-008 | Mixed-case duplicates: "Variant" and "variant" cols both present | error or de-dup per contract | U | P | NEW |
| DE-009 | 1000-column wide table to `discover_schema` | completes in <500ms | St,B | P+B | NEW |
| DE-010 | 100M-row table (synthetic, generated lazily) | refused via PRD §5.8 D-row-count rule (>1M → DuckDB or error) | St | P | NEW |
| DE-011 | Schema drift: column added in week 2 of experiment, analyze on combined data | discovery reports new column; analyzer doesn't crash | I | P | NEW |
| DE-012 | Datetime parsing failure (column has "2026-04-32") | discovery flags as object dtype, not timestamp | U | P | NEW |
| DE-013 | Timezone confusion (tz-aware UTC vs naive local) | discovery preserves tz; `srm_trend` uses tz-aware grouping if present | I | P | NEW |
| DE-014 | Float precision: sum of allocations 0.4 + 0.4 + 0.2 ≠ 1.0 exactly | validator tolerates `abs(sum-1) < 0.001` | U | P | EXIST | per validator tests |
| DE-015 | DuckDB query returns no rows | `LoadResult` with empty df, no crash | U | P | NEW |
| DE-016 | DuckDB `path` doesn't exist | error: `OpenXPError(code='data_not_found')` | U | P | NEW |
| DE-017 | DuckDB syntax error in SQL | error: `OpenXPError(code='data_load_failed')` with message including the sql | U | P | NEW |
| DE-018 | Snowflake credentials missing (no env vars) | error before connect attempt | U | P | NEW |
| DE-019 | Snowflake credentials present but expired | error: `OpenXPError(code='auth_failed')`; password never in message | U,Se | P | NEW |
| DE-020 | Snowflake wrong warehouse | clear error message naming the warehouse | U | P | NEW |
| DE-021 | Snowflake `snowflake-connector-python` package not installed | ImportError path with "install with `pip install agentxp[snowflake]`" hint | U | P | EXIST | per test_snowflake_loader.py |
| DE-022 | DuckDB package not installed | same import hint | U | P | EXTEND | similar pattern |
| DE-023 | CSV with UTF-8 BOM | auto-handled with `encoding='utf-8-sig'`, no error | U | P | NEW | per PRD §5.14 |
| DE-024 | CSV with CRLF line endings | parsed cleanly | U | P | NEW |
| DE-025 | CSV with quoted embedded commas | parsed cleanly | U | P | NEW |
| DE-026 | CSV with embedded newlines in quoted fields | parsed cleanly | U | P | NEW |
| DE-027 | CSV with non-UTF-8 encoding | error message recommends saving as UTF-8 | U | P | NEW |
| DE-028 | CSV with mixed dtypes in one column | dtype=object; warning | U | P | NEW |
| DE-029 | CSV with missing trailing newline | parsed cleanly | U | P | NEW |
| DE-030 | CSV with header only, no rows | empty df, no crash | U | P | NEW |
| DE-031 | CSV with rows but no header | dtype guess; warning | U | P | NEW |
| DE-032 | CSV file is 0 bytes | error | U | P | NEW |
| DE-033 | CSV file is 1GB | streaming path; benchmark | St,B | P+B | NEW |
| DE-034 | `CSVLoader.stream` on non-existent file | error (currently happy-path only — see WAVE1 §7) | U | P | NEW |
| DE-035 | `CSVLoader.stream` on empty file | yields zero chunks | U | P | NEW |
| DE-036 | `LoadResult.to_dict()` JSON-serializable | round-trip via json.dumps | U | P | NEW |
| DE-037 | `SchemaDiscovery.to_dict()` JSON-serializable | same | U | P | NEW |
| DE-038 | `discover_schema` with column dtype `category` | treats as segment candidate | U | P | NEW |
| DE-039 | `discover_schema` with column dtype `Int64` (nullable int) | treats as numeric | U | P | NEW |
| DE-040 | `discover_schema` with column with > 20 unique values | not a segment candidate | U | P | EXIST? | verify |
| DE-041 | `discover_schema` with column with exactly 2 unique values | segment candidate AND treatment candidate (potentially) | U | P | NEW |

### 3.3 Lifecycle / state machine edge cases

The lifecycle has 11 states, 27 valid transitions (forward + backward), and (11×11 - 27 - 11 self-loops) ≈ 83 illegal transitions. Test all of them. The lifecycle suite has the highest hard-pass test count of any group.

| # | Trigger | Expected | Type | P/B | Status |
|---|---|---|---|---|---|
| LE-001 | DESIGNING → POWERED (forward) | ok | L | P | NEW |
| LE-002 | DESIGNING → BLOCKED | ok | L | P | NEW |
| LE-003 | DESIGNING → ABANDONED | ok | L | P | NEW |
| LE-004 | DESIGNING → COLLECTING (skip POWERED) | error with hint "Run power analysis first" | L | P | EXIST? | verify hint text |
| LE-005 | DESIGNING → ANALYZING | error | L | P | NEW |
| LE-006 | DESIGNING → INTERPRETED | error | L | P | NEW |
| LE-007 | DESIGNING → REPORTED | error | L | P | NEW |
| LE-008 | DESIGNING → SHIPPED | error | L | P | NEW |
| LE-009 | DESIGNING → COMPLETED | error | L | P | NEW |
| LE-010 | DESIGNING → INVALID | error | L | P | NEW |
| LE-011 | POWERED → COLLECTING | ok | L | P | NEW |
| LE-012 | POWERED → DESIGNING (backward, requires amendment) | ok via `is_backward=True` + amendment hook | L,I | P | NEW |
| LE-013 | POWERED → ANALYZING | error | L | P | NEW |
| LE-014 | POWERED → ABANDONED | ok | L | P | NEW |
| LE-015 | POWERED → BLOCKED | ok | L | P | NEW |
| LE-016 | POWERED → INVALID | error | L | P | NEW |
| LE-017 | COLLECTING → ANALYZING | ok | L | P | NEW |
| LE-018 | COLLECTING → ABANDONED | ok | L | P | NEW |
| LE-019 | COLLECTING → BLOCKED | ok | L | P | NEW |
| LE-020 | COLLECTING → DESIGNING | error | L | P | NEW |
| LE-021 | COLLECTING → POWERED | error | L | P | NEW |
| LE-022 | COLLECTING → INTERPRETED | error | L | P | NEW |
| LE-023 | COLLECTING → REPORTED | error with hint | L | P | NEW |
| LE-024 | ANALYZING → INTERPRETED | ok | L | P | NEW |
| LE-025 | ANALYZING → INVALID | ok | L | P | NEW |
| LE-026 | ANALYZING → ABANDONED | ok | L | P | NEW |
| LE-027 | ANALYZING → COLLECTING (backward) | ok via amendment | L,I | P | NEW |
| LE-028 | ANALYZING → DESIGNING | error | L | P | NEW |
| LE-029 | ANALYZING → POWERED | error | L | P | NEW |
| LE-030 | ANALYZING → REPORTED | error | L | P | NEW |
| LE-031 | INTERPRETED → REPORTED | ok | L | P | NEW |
| LE-032 | INTERPRETED → COLLECTING (backward extend) | ok via amendment | L,I | P | NEW |
| LE-033 | INTERPRETED → ABANDONED | ok | L | P | NEW |
| LE-034 | INTERPRETED → SHIPPED | error | L | P | NEW |
| LE-035 | REPORTED → SHIPPED | ok | L | P | NEW |
| LE-036 | REPORTED → ABANDONED | ok | L | P | NEW |
| LE-037 | REPORTED → COMPLETED | error | L | P | NEW |
| LE-038 | SHIPPED → COMPLETED | ok | L | P | NEW |
| LE-039 | SHIPPED → ABANDONED | ok | L | P | NEW |
| LE-040 | COMPLETED → anywhere | error: terminal | L | P | NEW |
| LE-041 | ABANDONED → anywhere | error: terminal | L | P | NEW |
| LE-042 | INVALID → DESIGNING | ok via amendment | L | P | NEW |
| LE-043 | INVALID → ABANDONED | ok | L | P | NEW |
| LE-044 | INVALID → ANALYZING | error | L | P | NEW |
| LE-045 | BLOCKED → DESIGNING | ok | L | P | NEW |
| LE-046 | BLOCKED → POWERED | ok | L | P | NEW |
| LE-047 | BLOCKED → COLLECTING | ok | L | P | NEW |
| LE-048 | BLOCKED → ABANDONED | ok | L | P | NEW |
| LE-049 | BLOCKED → ANALYZING | error | L | P | NEW |
| LE-050 | Self-loop: any state → same state | ok (no-op save) | L,P | P | NEW | covered as a property |
| LE-051 | Unknown current state ("FOO") | error: unknown state | L | P | NEW |
| LE-052 | Unknown target state ("BAR") | error: unknown state | L | P | NEW |
| LE-053 | Property: `validate_transition(s, s)` is True for every s ∈ ALL_STATES | invariant | P | P | NEW |
| LE-054 | Property: `validate_transition(a, b).ok == ((a==b) or b ∈ VALID_TRANSITIONS[a])` | invariant | P | P | NEW |
| LE-055 | Property: `is_backward(a, b)` ↔ b ∈ _BACKWARD[a] | invariant | P | P | NEW |
| LE-056 | Property: every backward transition is also in `VALID_TRANSITIONS` | invariant | P | P | NEW |
| LE-057 | All 11 states have a defined entry in VALID_TRANSITIONS | property | P | P | NEW |
| LE-058 | COMPLETED and ABANDONED have empty VALID_TRANSITIONS (terminal) | property | P | P | NEW |
| LE-059 | `ExperimentStore.save_experiment` with status not in ALL_STATES | rejected | I | P | NEW |
| LE-060 | Two processes write to same experiment_id concurrently | last-write-wins; no corruption (atomic file write) | I,St | P | NEW |
| LE-061 | Amendment with reason 9 chars | rejected | U | P | EXIST? | per amendment tracker |
| LE-062 | Amendment with reason 10 chars | accepted | U | P | EXIST? | |
| LE-063 | Amendment with reason 5000 chars | accepted (no upper bound) | U | P | NEW |
| LE-064 | Amendment with reason containing only whitespace (`"          "`) | rejected | U | P | NEW |
| LE-065 | Amendment with unicode reason ("πιο γρήγορο") | accepted | U | P | NEW |
| LE-066 | Amendment after TERMINATED state (COMPLETED, ABANDONED) | rejected | I | P | NEW |
| LE-067 | `experiment.yaml` corrupted mid-write (interrupt during atomic replace) | original file intact, no .tmp leftover | I | P | EXIST | covered in test_storage |
| LE-068 | Clock skew: timestamp from future (2099) | accepted; storage doesn't validate clock | I | P | NEW |
| LE-069 | Store root path permission denied | `OpenXPError(code='storage_permission_denied')` | I,Se | P | NEW |
| LE-070 | Store root path is a file not a directory | error at construction | I | P | NEW |
| LE-071 | Disk full during save | error: write fails atomically; no half-written file | I | P | NEW |
| LE-072 | Very deep nested yaml (recursion limit) | parser refuses with clear error | I | P | NEW |
| LE-073 | Experiment id collision (same id used twice) | second save overwrites or appends per contract | I | P | NEW |
| LE-074 | Experiment id with `../` (path traversal) | rejected | Se | P | NEW |
| LE-075 | Experiment id with `/etc/passwd` | rejected | Se | P | NEW |
| LE-076 | Experiment id with spaces | rejected per `^[a-z0-9][a-z0-9-]{0,63}$` | Se | P | NEW |
| LE-077 | Experiment id 64 chars (limit) | accepted | U | P | NEW |
| LE-078 | Experiment id 65 chars | rejected | U | P | NEW |
| LE-079 | Experiment id starting with `-` | rejected | U | P | NEW |
| LE-080 | Experiment id with uppercase | rejected | U | P | NEW |
| LE-081 | Experiment id "0" (single digit) | accepted | U | P | NEW |
| LE-082 | `delete_experiment` removes JSONL log | assertion explicit per WAVE1 §7 | I | P | NEW |
| LE-083 | `load_latest_analysis` with two analyses saved in same microsecond | retrieves the actually-latest by counter | I | P | NEW | per WAVE1 I3 |

### 3.4 I/O and environment edge cases

| # | Trigger | Expected | Type | P/B | Status |
|---|---|---|---|---|---|
| IE-001 | No `OPENXP_SNOWFLAKE_*` env vars | clear error at connect, no traceback into snowflake-connector | U | P | NEW |
| IE-002 | `OPENXP_SNOWFLAKE_PASSWORD` set, password contains special chars | passes through, never logged | U,Se | P | NEW |
| IE-003 | `snowflake-connector-python` not installed | ImportError caught, hint to install extras | U | P | EXIST |
| IE-004 | `duckdb` not installed | ImportError caught, hint to install extras | U | P | NEW |
| IE-005 | `PyYAML` version too old (e.g., 3.x) | error at import time | Co | P | NEW |
| IE-006 | scipy 1.11 vs 1.12 vs 1.13 — `welch_test` numerically equivalent within 1e-9 | matrix run | Co | P | NEW |
| IE-007 | numpy 1.26 vs numpy 2.0 — no `np.float_` deprecation crash | matrix run | Co | P | NEW |
| IE-008 | pandas 2.0 vs 2.2 — `pd.Grouper(freq='1D')` vs `'1d'` lowercase | `srm_trend` `_window_alias` handles both | Co | P | NEW |
| IE-009 | Write to read-only filesystem | `OpenXPError(code='storage_permission_denied')` | I | P | NEW |
| IE-010 | SIGINT during save | atomic rollback, no partial file | I | P | EXIST | per test_atomic_write_survives_interrupt |
| IE-011 | Trailing whitespace in YAML values ("primary_metric: revenue   ") | parser strips; cross-field check still passes | I | P | NEW |
| IE-012 | YAML with tab indentation | parser rejects with clear error | I | P | NEW |
| IE-013 | YAML with Windows CRLF | parsed cleanly | I | P | NEW |
| IE-014 | `os.environ["LANG"]` unset (CI sometimes) | no encoding crash | Co | P | NEW |
| IE-015 | TZ environment variable set to "Asia/Tokyo" | datetime tests still deterministic | D,Co | P | NEW |
| IE-016 | Locale set to "de_DE" (decimal commas) | float parsing not affected (CSV loader pins locale) | Co | P | NEW |

### 3.5 Skill / orchestrator edge cases

These are the integration tests for the `/experiment` skill dispatch. They are simulated at the Python level (the runner mimics what the agent does). The skill is markdown, so these tests harness the same stats/storage calls in the same order.

| # | Trigger | Expected | Type | P/B | Status |
|---|---|---|---|---|---|
| SK-001 | `/experiment design` with `experiment.yaml` already present in COLLECTING | rejected with hint | E2E | P | NEW |
| SK-002 | `/experiment design` with cold-start while a stale yaml exists in `working/` | resolves: working is gitignored, treats as fresh | E2E | P | NEW |
| SK-003 | `/experiment power` against yaml in DESIGNING | populates power block, transitions to POWERED | E2E | P | NEW |
| SK-004 | `/experiment power` against yaml in POWERED (recompute) | overwrites with confirmation | E2E | P | NEW |
| SK-005 | `/experiment analyze` with no yaml (cold-start) | runs with defaults, appends upgrade nudge | E2E | P | NEW |
| SK-006 | `/experiment analyze` Type-C SRM gate fires on SRM BLOCK | hard halt, no INTERPRETED transition | E2E | P | NEW |
| SK-007 | `/experiment analyze` Type-C min-sample gate fires at n < 50% | hard halt | E2E | P | NEW |
| SK-008 | `/experiment analyze` Type-C guardrail fires on RED | hard halt, requires user ack | E2E | P | NEW |
| SK-009 | Attempt to skip Type-C with `--just-do-it` | ignored; type-C always fires | E2E | P | NEW |
| SK-010 | Type-B draft review skipped with `--just-do-it` | passes through silently | E2E | P | NEW |
| SK-011 | `/experiment full` partially failed at step 4 (analyze) | yaml stays at COLLECTING; re-run picks up at analyze | E2E | P | NEW |
| SK-012 | `/experiment full` greenfield with data file (ambiguity per FINAL_STATUS gap) | resolved per dispatch contract; assert which path is taken | E2E | P | NEW | resolves §FINAL_STATUS step 0 ambiguity by spec |
| SK-013 | Cross-mode pollution: running analyze while another analyze is in flight (parallel processes, same yaml) | last-write-wins or lock | E2E,St | P | NEW |
| SK-014 | Invalid mode name `/experiment foo` | error: unknown mode | E2E | P | NEW |
| SK-015 | Data file doesn't exist | error: data_not_found | E2E | P | NEW |
| SK-016 | `experiment.yaml` references a metric.yaml that was moved/deleted | error: metric_not_found | E2E | P | NEW |
| SK-017 | `--yaml` without a path | argument parse error | E2E | P | NEW |
| SK-018 | `--audience invalid` | rejected | E2E | P | NEW |
| SK-019 | `/experiment interpret` after analyze that did NOT call `set_trace(True)` | rejects: missing computation_trace | E2E | P | NEW | gates the FINAL_STATUS gap 3 |
| SK-020 | `/experiment interpret` after analyze that DID call `set_trace(True)` | passes the trace validation | E2E | P | NEW |
| SK-021 | `/experiment monitor` with no prior monitoring history | runs single-day report | E2E | P | NEW |
| SK-022 | `/experiment monitor` with 7+ prior reports | trend analysis populated | E2E | P | NEW |
| SK-023 | `/experiment monitor` with persistence error path (bogus experiment_id, store provided) | report still produced; `recommendations` annotated | E2E | P | NEW | per WAVE2 M5 |
| SK-024 | `/experiment report` for each audience | three artifacts produced with correct format | E2E | P | NEW |
| SK-025 | `/experiment status` against each of the 11 states | each prints the correct "next mode" | E2E | P | NEW |
| SK-026 | `/experiment status` with inconsistent state (POWERED + null sample size) | warns | E2E | P | NEW |
| SK-027 | `/experiment full` end-to-end against `clean_ab.csv` reaches REPORTED with verdict SHIP | per §14 | E2E,Sn | P | NEW |
| SK-028 | `/experiment full` against `srm_violation.csv` halts at SRM gate, lands in INVALID | per §14 | E2E,Sn | P | NEW |
| SK-029 | `/experiment full` against `no_effect.csv` lands in LEARN | per §14 | E2E,Sn | P | NEW |
| SK-030 | `/experiment full` against `guardrail_violation.csv` lands in INVESTIGATE | per §14 | E2E,Sn | P | NEW |
| SK-031 | `/experiment full` against `underpowered.csv` calls `extension_estimate` and reports days needed | per §14 | E2E,Sn | P | NEW |
| SK-032 | `/experiment full` against `mixed_results.csv` lands in INVESTIGATE with segment annotation | per §14 | E2E,Sn | P | NEW |
| SK-033 | `/experiment full` against `checkout_redesign.csv` produces documented expected verdict | per §14 | E2E,Sn | P | NEW | document in §14 |

### 3.6 Validation edge cases

Every validator rule in `experiment_validator.py` (11 functions) and `metric_validator.py` (2 functions) needs an assertion that triggers it. The validator already collects all findings in one pass (good); we need explicit per-rule tests.

| # | Trigger | Expected | Type | P/B | Status |
|---|---|---|---|---|---|
| VE-001 | Missing `id` field | error finding "missing_required_field: id" | U | P | EXIST | partial |
| VE-002 | `id` not matching `^[a-z0-9][a-z0-9-]{0,63}$` | error | U | P | NEW |
| VE-003 | Missing `name` field | error | U | P | NEW |
| VE-004 | Missing `hypothesis` block | error | U | P | EXIST? | verify |
| VE-005 | Hypothesis missing `action`, `metric`, `direction`, `magnitude`, `mechanism` | one error per missing subfield | U | P | NEW |
| VE-006 | Empty `metrics` list | error | U | P | NEW |
| VE-007 | Missing `metrics.primary` | error | U | P | NEW |
| VE-008 | `primary_metric` name not in `metrics` list | cross-field error | U | P | EXIST |
| VE-009 | `primary_metric` name in metrics list but with trailing whitespace | error or normalize per contract | U | P | NEW |
| VE-010 | Metric `type` not in {proportion, continuous, ratio, duration} | enum error | U | P | NEW |
| VE-011 | NaN in `metrics.primary.baseline` | error | U | P | NEW |
| VE-012 | `mde` >= 1.0 for proportion (impossible 100% relative lift) | warning or error per contract | U | P | NEW |
| VE-013 | `mde` ≤ 0 | error | U | P | NEW |
| VE-014 | `alpha` ≤ 0 or ≥ 1 | error | U | P | NEW |
| VE-015 | `power` < 0.5 or > 0.99 | warning | U | P | NEW |
| VE-016 | Allocation sum 0.4 + 0.4 (= 0.8) | error | U | P | EXIST |
| VE-017 | Allocation sum 0.4 + 0.6005 (off by 0.0005, below tolerance 0.001) | ok | U | P | EXIST |
| VE-018 | Allocation sum 0.4 + 0.6020 (off by 0.002, above tolerance) | error | U | P | NEW |
| VE-019 | No control variant (no `is_control: true`) | error | U | P | NEW |
| VE-020 | Two control variants | error | U | P | NEW |
| VE-021 | Variant with negative allocation | error | U | P | NEW |
| VE-022 | Variant name with whitespace | error or normalize | U | P | NEW |
| VE-023 | Status not in `lifecycle.ALL_STATES` | error | U | P | EXIST? |
| VE-024 | Pre-Pydantic-enum status (e.g., "SHIPPED") loaded via `ExperimentConfig(**data)` | enum now has all 11 states — should pass, remove `xfail` (resolved — see §18 Q3) | U | P | NEW |
| VE-025 | `decision_rules` block missing | warning (recommended) | U | P | NEW |
| VE-026 | Guardrail without `nim_relative` | warning (PRD says NIM optional) | U | P | NEW |
| VE-027 | Guardrail with `nim_relative=0` | accepted (zero-tolerance) | U | P | NEW |
| VE-028 | Validator collects multiple findings, not just first | verified | U | P | EXIST |
| VE-029 | `validate_metric_yaml` missing `name` | error | U | P | EXIST? |
| VE-030 | `validate_metric_yaml` missing `type` | error | U | P | NEW |
| VE-031 | `validate_metric_yaml` `type` not in enum | error | U | P | NEW |
| VE-032 | `validate_metric_yaml` `formula` with disallowed chars (eval injection vector) | error per PRD §5.16 D.18 | Se | P | NEW |
| VE-033 | `validate_experiment_yaml` against the shipped `templates/experiment.yaml` | doesn't crash; structured findings | I | P | EXIST |
| VE-034 | YAML file is 0 bytes | error: empty file | I | P | NEW |
| VE-035 | YAML file is 100MB (denial-of-resources) | refused with size cap | Se,St | P | NEW |
| VE-036 | YAML billion-laughs attack | refused; PyYAML safe_load is not affected, but assert | Se | P | NEW |
| VE-037 | `validate_experiment_yaml` accepts `dict` directly (not just path) | works | U | P | NEW |

---

## 4. Test coverage gap analysis

Module-by-module. "Public fns" = functions/classes exported via `__init__.py` or used by other modules. "Fns with ≥3 tests" = estimated from spot-checking the test files (not via coverage.py). "Sim tests" = Monte Carlo simulation tests of statistical correctness. "Priority" reflects how exposed the module is on the `/experiment full` critical path.

| Module | Public fns | Fns with ≥3 tests | Sim tests | Gaps | Priority |
|---|---|---|---|---|---|
| `openxp.stats.ab_tests` | 4 (welch, proportion, ratio_metric, winsorize) | 4 | 0 | No Type-I/II/coverage sims; no zero-variance contract; no n<30 warnings | **CRITICAL** |
| `openxp.stats.fishers` | 1 | 1 | 0 | No fallback-from-proportion test; no large-n behavior | HIGH |
| `openxp.stats.guardrails` | 2 (guardrail_test, denominator_srm) | 1 | 0 | No invert=True test; no zero-baseline; no `metric_type='proportion'` path | **CRITICAL** |
| `openxp.stats.power` | 5 (power_proportion, power_mean, detectable_effect, duration_estimate, power_sensitivity_table) | 5 | 0 | No calibration sims; no extreme-baseline (0.5 max variance); no monotonicity properties | HIGH |
| `openxp.stats.ratio_power` | 1 (power_ratio) | 1 | 0 | No correlation-edge tests; no calibration sim | HIGH |
| `openxp.stats.extension` | 1 | 1 | 0 | No accuracy sim; no feasibility-boundary test; major signature drift from PRD/MODES (FINAL_STATUS gap) | HIGH |
| `openxp.stats.srm` | 2 (srm_check, srm_diagnose) | 2 | 0 | Default threshold mismatch with PRD (0.01 vs 0.0005) — the default needs an explicit test that asserts it; no multi-arm test; no segment-diagnose-with-100-segments | **CRITICAL** |
| `openxp.stats.effect_size` | 2 (cohens_d, relative_lift) | 2 | 0 | No `relative_lift(0,0)` contract; no negative-control test | MEDIUM |
| `openxp.stats.effect_size_extras` | 1 (cohens_h) | 1 | 0 | Sig drift with PRD (no n_control/n_treatment kwargs); no boundary test | MEDIUM |
| `openxp.stats.corrections` | 1 (adjust_pvalues) | 1 | 0 | No Holm-vs-BH agreement sim; no NaN handling | MEDIUM |
| `openxp.stats.prep` | 1 (prepare_experiment_data) | 1 (in test_missing_functions) | 0 | Major: no panel/dedup/winsorize chain test; PRD-vs-actual sig drift; no >5% drop warning | **CRITICAL** |
| `openxp.stats.cuped` | 3 (cuped_adjust, variance_reduction, cuped_welch_test) | 3 | 0 | Var(pre)=0 fallback untested; cov=0 untested; sim of variance reduction claim | HIGH |
| `openxp.stats.sequential` | 4 (msprt_test, always_valid_ci, group_sequential_boundaries, sequential_proportion_test) | 4 | 1 (Type-I peeking, 500 reps) | sim count too low (500); no group-seq Type-I sim; no coverage sim for always_valid_ci | HIGH |
| `openxp.stats.bayesian` | 4 (beta_binomial_test, normal_normal_test, expected_loss, probability_to_beat) | 4 | 0 | M1 strong-prior bug locked in by test_strong_prior_pulls_posterior; no posterior coverage sim; no edge `n_samples=2` | HIGH |
| `openxp.stats._trace` | 2 (set_trace, is_trace_enabled) | 2 | 0 | Default-on-vs-off contract is exactly the FINAL_STATUS gap 3; need test that asserts decision | **CRITICAL** |
| `openxp.data.csv_loader` | 1 class | 1 | 0 | stream() error paths untested per WAVE1 §7; BOM/CRLF/encoding edge cases | HIGH |
| `openxp.data.discovery` | 1 (discover_schema) + helpers | 1 | 0 | Empty df, single col, 1000-col, unicode names, schema drift | HIGH |
| `openxp.data.duckdb_loader` | 1 class | 1 | 0 | No-rows query, syntax error, missing duckdb extra | MEDIUM |
| `openxp.data.snowflake_loader` | 1 class | 1 | 0 | S4 SQL injection in `where` param unfixed; credential leakage in stack traces; missing extras | **CRITICAL** (Se) |
| `openxp.data.base` | 2 dataclasses | (transitively) | 0 | `to_dict` JSON-serializability untested per WAVE1 §7 | LOW |
| `openxp.storage.store` | 10 methods | ~7 | 0 | `delete_experiment` JSONL cleanup; corrupt-yaml load; concurrent writes; microsecond sort I3 | HIGH |
| `openxp.storage.lifecycle` | 3 (validate_transition, is_backward, ALL_STATES) | 3 | 0 | Missing exhaustive 11×11 matrix tests (≈83 illegal transitions); property tests | **CRITICAL** |
| `openxp.amendments.diff` | 2 (diff_experiments, classify_change) | 2 | 0 | Missing `data` prefix classify; tuple-vs-list mismatch; round-trip property | MEDIUM |
| `openxp.amendments.tracker` | 1 class + helper | 1 | 0 | Reason whitespace, unicode, max-length; reaching into `store._log_path` (S2) | MEDIUM |
| `openxp.monitoring.srm_trend` | 1 | 1 | 0 | Single-variant outage (T4); window aliasing across pandas versions | HIGH |
| `openxp.monitoring.guardrail_health` | 1 | 1 | 0 | Zero-baseline NIM warning (S5); proportion guardrail path | HIGH |
| `openxp.monitoring.sample_accumulation` | 1 | 1 | 0 | Day-0 stalled branch (M1); planned_duration=None | MEDIUM |
| `openxp.monitoring.report` | 2 (run_monitor, MonitorReport) | 2 | 0 | Persistence error annotation (M5); current_n default (S1); non-trivial dispatch | HIGH |
| `openxp.validators.experiment_validator` | 11 internal rules + `validate_experiment_yaml` | partial | 0 | Each rule needs a dedicated trigger test; YAML bomb; size cap | HIGH |
| `openxp.validators.metric_validator` | 2 functions | partial | 0 | Type enum, formula injection | MEDIUM |
| `openxp.metrics.registry` | 4 methods | 4 | 0 | `_default_metrics_dir` HOME monkeypatch; no test_family routing | LOW |
| `openxp.metrics.schema` | 1 model + dispatch | 1 | 0 | Missing test_family field per WAVE1 I2; routing to bayesian/cuped/sequential | MEDIUM |
| `openxp.errors.base` | 1 class + 5 subclasses | 1 | 0 | Empty code/message; non-JSON details (T7); `default=str` discipline | MEDIUM |
| `openxp.errors.codes` | 17 constants | partial | 0 | Each code has a default message + hint | LOW |
| `openxp.schemas.experiment` | 1 model + 2 enums | 1 | 0 | 11-state enum (FINAL_STATUS gap 4); cross-field validation; field defaults | HIGH |
| `openxp.schemas.results` | 14 models (currently empty) | 0 | 0 | Entire module needs population (FINAL_STATUS gap 5) — testing waits on the build | DEFER |

**Public function count (rough, including helpers used cross-module):** ~85
**Public functions with ≥3 tests today:** ~50
**Public functions with simulation tests:** 1 (mSPRT Type-I)
**Modules with no edge case coverage:** ~10
**Modules with security tests:** 1 (snowflake credential masking)

---

## 5. Property-based test plan

Property tests need Hypothesis. Add `hypothesis>=6.100` to the dev dependency group (do not edit pyproject.toml — recommend it). Each property runs with default 50 examples on PR, 1000 examples nightly.

| # | Function | Strategy | Invariant | Notes |
|---|---|---|---|---|
| PR-001 | `welch_test` | two `arrays(dtype=float, shape=integers(2, 1000))` of finite floats with positive variance | `0 <= p_value <= 1` | basic shape |
| PR-002 | `welch_test` | as above, identical arrays | `p_value > 0.99` | self-equality |
| PR-003 | `welch_test` | swap control and treatment | `t_stat` flips sign; `p_value` unchanged (two-sided) | symmetry |
| PR-004 | `proportion_test` | `(c_success, c_n, t_success, t_n)` integers with constraints | `0 <= p_value <= 1`, `c_success <= c_n`, `t_success <= t_n` | basic |
| PR-005 | `proportion_test` | identical proportions | `p_value > 0.5` | self-equality (not strict, can be small for tiny n) |
| PR-006 | `ratio_metric_test` | random num/den arrays | `p_value` finite, no NaN | |
| PR-007 | `srm_check` | `observed_counts` ints + matching `expected_ratios` summing to 1 | `verdict ∈ {PASS, WARNING, BLOCK}` | enum invariant |
| PR-008 | `srm_check` | observed exactly equals expected (e.g., 5000/5000 with [0.5, 0.5]) | `verdict == PASS`, `p_value` ≈ 1.0 | known-answer |
| PR-009 | `cuped_welch_test` | `(pre, post)` with high correlation (ρ ≥ 0.5) | `variance_reduction.realized >= 0.20` (allowing some MC slack) | the "CUPED actually reduces variance" claim |
| PR-010 | `cuped_welch_test` | `(pre, post)` with zero correlation | `variance_reduction.realized ≈ 0.0` | null case |
| PR-011 | `power_proportion` | `baseline_rate ∈ [0.01, 0.99]`, `mde_relative ∈ [0.01, 0.5]` | `sample_size_per_group > 0`, finite | basic |
| PR-012 | `power_proportion` | vary `mde_relative` while holding others constant | `sample_size_per_group` is monotone-decreasing in `mde_relative` | monotonicity |
| PR-013 | `power_proportion` | vary `baseline_rate` from 0.01 to 0.5 | `sample_size_per_group` is monotone-increasing (variance grows) | |
| PR-014 | `power_proportion` ↔ `detectable_effect` | round-trip: compute n from (baseline, mde), then compute mde back from n | within 5% of original | round-trip |
| PR-015 | `validate_experiment_yaml` | a `dictionaries` strategy that builds well-formed yaml dicts | `report.ok == True` | self-soundness |
| PR-016 | `validate_experiment_yaml` | random valid yaml + random single-field deletion | exactly one finding per deleted required field | mutation detection |
| PR-017 | `diff_experiments` | random pair `(before, after)` of nested dicts | applying the diff to `before` → `after` | round-trip |
| PR-018 | `diff_experiments` | identical inputs | empty diff | reflexivity |
| PR-019 | `validate_transition` | `(from_state, to_state)` from `ALL_STATES × ALL_STATES` | result is True iff `(from, to) ∈ VALID_TRANSITIONS or from==to` | |
| PR-020 | `is_backward` | same domain | result is True iff `to ∈ _BACKWARD[from]` | |
| PR-021 | `winsorize` | random `(series, lower, upper)` | output min ≥ input quantile(lower), output max ≤ input quantile(upper) | trim contract |
| PR-022 | `relative_lift` | `(c_mean, t_mean)` with `c_mean != 0` | `result == (t_mean - c_mean) / c_mean` | known formula |
| PR-023 | `cohens_d` | two arrays | result is finite when both have positive variance | |
| PR-024 | `adjust_pvalues` | random p-value vectors | output values ≥ input (corrections never decrease p) | |
| PR-025 | `discover_schema` | random DataFrame with mixed dtypes | result has same n_rows as input; dtypes mapped consistently | |

---

## 6. Simulation test plan

Statistical correctness via Monte Carlo. Each sim has: data-generating process, sample count, tolerance band, justification, expected runtime.

### SIM-001 — `welch_test` Type-I rate under null
- **DGP:** control ~ N(0, 1), treatment ~ N(0, 1), n=500 each.
- **Reps:** 10,000.
- **Test:** rejection rate at α=0.05 should be ≈ 0.05.
- **Tolerance:** [0.045, 0.055] (≈ ±2σ MC at p=0.05, n=10000).
- **Why:** Welch is exact-ish for normal data; Type-I rate must hit nominal.
- **Runtime budget:** 5s.

### SIM-002 — `welch_test` Type-I under heavy tails
- **DGP:** control ~ t-distribution with df=3, treatment ~ same. n=500.
- **Reps:** 10,000.
- **Tolerance:** [0.04, 0.06] (slightly wider — Welch is approximate for heavy tails).
- **Why:** robustness check. Document any inflation.
- **Runtime:** 6s.

### SIM-003 — `welch_test` Type-II / power calibration
- **DGP:** control ~ N(0, 1), treatment ~ N(0.2, 1) (Cohen's d = 0.2). n derived from `power_mean(baseline_mean=0, baseline_std=1, mde_relative=...) — actually use `power=0.8` to back into n, then run `welch_test` at that n.
- **Reps:** 5,000.
- **Test:** observed power should be ≈ 0.80.
- **Tolerance:** [0.78, 0.82].
- **Why:** validates `power_mean` is calibrated.
- **Runtime:** 8s.

### SIM-004 — `proportion_test` Type-I under null
- **DGP:** Bernoulli(0.10) vs Bernoulli(0.10), n=2000 each.
- **Reps:** 10,000.
- **Tolerance:** [0.045, 0.055].
- **Runtime:** 4s.

### SIM-005 — `proportion_test` Type-I at low rate (small-cell regime)
- **DGP:** Bernoulli(0.005) vs Bernoulli(0.005), n=200 each.
- **Reps:** 10,000.
- **Tolerance:** [0.03, 0.07] (looser — z-test is approximate at small expected counts).
- **Why:** documents the regime where Fisher's exact is recommended.
- **Runtime:** 5s.

### SIM-006 — `proportion_test` power calibration
- **DGP:** Bernoulli(0.10) vs Bernoulli(0.11) — 10% relative lift. n from `power_proportion(0.10, 0.10)`.
- **Reps:** 5,000.
- **Tolerance:** observed power ∈ [0.78, 0.82].
- **Runtime:** 6s.

### SIM-007 — `ratio_metric_test` Type-I under null
- **DGP:** correlated num/den with no treatment effect. n=1000 each.
- **Reps:** 10,000.
- **Tolerance:** [0.04, 0.06] (delta method is approximate).
- **Runtime:** 8s.

### SIM-008 — `fishers_exact_test` Type-I
- **DGP:** Bernoulli(0.05) vs Bernoulli(0.05), n=100 each.
- **Reps:** 10,000.
- **Tolerance:** [0.04, 0.06] (Fisher's is exact, but conservative — allow upper tolerance).
- **Runtime:** 12s (Fisher's is slow).

### SIM-009 — `guardrail_test` calibration (one-sided NI)
- **DGP:** treatment effect exactly at the NIM (the boundary case). 5000 reps.
- **Test:** rejection rate (i.e., declares "non-inferior") should be ≈ α at the boundary.
- **Tolerance:** [0.03, 0.07].
- **Runtime:** 6s.

### SIM-010 — `srm_check` Type-I at threshold=0.0005
- **DGP:** balanced 5000/5000.
- **Reps:** 100,000 (need many reps because the rejection threshold is small).
- **Tolerance:** rate ∈ [0.0003, 0.0007].
- **Runtime:** 30s.

### SIM-011 — `power_proportion` calibration end-to-end
- **DGP:** for each baseline ∈ {0.05, 0.10, 0.30, 0.50}, mde ∈ {0.05, 0.10, 0.20}: compute `n = power_proportion(baseline, mde).sample_size_per_group`. Simulate 5000 reps of A/B at that `n` with the true effect.
- **Test:** observed power per cell ∈ [0.78, 0.82].
- **Tolerance:** as above.
- **Runtime:** 60s.

### SIM-012 — `power_mean` calibration end-to-end
- Same shape as SIM-011 for continuous metric.
- **Runtime:** 60s.

### SIM-013 — `power_ratio` calibration with `correlation_num_den ∈ {0.0, 0.5, 0.9}`
- **Reps:** 3000 per cell.
- **Tolerance:** [0.76, 0.84] (looser — delta method).
- **Runtime:** 90s.

### SIM-014 — `cuped_welch_test` variance reduction claim
- **DGP:** generate `(pre, post)` with explicit ρ ∈ {0.3, 0.5, 0.7, 0.9}.
- **Reps:** 2000.
- **Test:** observed variance reduction ≈ ρ^2 within ±5 percentage points.
- **Why:** PRD claim and walkthrough teaching point.
- **Runtime:** 30s.

### SIM-015 — `cuped_welch_test` Type-I under null
- **DGP:** treatment effect = 0; `(pre, post)` correlated.
- **Reps:** 10,000.
- **Tolerance:** [0.045, 0.055].
- **Runtime:** 25s.

### SIM-016 — `msprt_test` Type-I under unlimited peeking
- **DGP:** null A/A. Peek every 50 obs starting at n=100, up to n=2000. Reject if any peek crosses.
- **Reps:** 10,000 (current test does 500 — extend).
- **Tolerance:** rate ≤ 0.05 + 0.005 = 0.055.
- **Why:** the "always-valid" guarantee is the whole point of mSPRT.
- **Runtime:** 30s. The slow one. Acceptable.

### SIM-017 — `msprt_test` power
- **DGP:** H1 with Cohen's d=0.2, peek every 50.
- **Reps:** 2000.
- **Tolerance:** observed power ∈ [0.65, 0.80] (sequential is slightly less powerful than fixed-n).
- **Runtime:** 30s.

### SIM-018 — `group_sequential_boundaries` Type-I under O'Brien-Fleming, 5 looks
- **DGP:** null A/B; reject at any look that crosses the precomputed boundary.
- **Reps:** 10,000.
- **Tolerance:** [0.04, 0.06].
- **Runtime:** 25s.

### SIM-019 — `group_sequential_boundaries` Type-I under Pocock, 5 looks
- Same as SIM-018, Pocock spending.
- **Runtime:** 25s.

### SIM-020 — `always_valid_ci` coverage
- **DGP:** null A/B random walks. At each peek, check if 0 ∈ CI.
- **Reps:** 5000.
- **Test:** coverage ≥ 0.95 at every peek (anytime-valid).
- **Tolerance:** ≥ 0.94 at any individual peek.
- **Runtime:** 20s.

### SIM-021 — `beta_binomial_test` posterior coverage
- **DGP:** true rate = 0.10; sample n=500 successes from Binomial(n=5000, 0.10).
- **Reps:** 5000.
- **Test:** 95% credible interval for rate covers 0.10 in ≥ 95% of reps.
- **Tolerance:** ≥ 0.94.
- **Runtime:** 30s.

### SIM-022 — `normal_normal_test` posterior coverage (weak prior)
- **DGP:** N(0, 1) data; `prior_sd=1e6`.
- **Reps:** 5000.
- **Test:** 95% CrI for mean covers true mean ≥ 95%.
- **Runtime:** 25s.

### SIM-023 — `normal_normal_test` posterior coverage (strong prior) — **remove xfail (resolved — see §18 Q4)**
- **DGP:** as above with `prior_sd=0.5`.
- **Reps:** 5000.
- **Test:** coverage ≥ 0.94.
- **Why:** locks in correct behavior. NIG conjugate posterior now implemented (W17) — this test should pass. Remove the `xfail` marker.
- **Runtime:** 25s.

### SIM-024 — `extension_estimate` accuracy
- **DGP:** simulate underpowered run, compute extension_estimate, simulate the extension, observe whether the experiment reaches the planned MDE.
- **Reps:** 1000.
- **Tolerance:** the extension reaches power 0.80 in ≥ 75% of reps (the prediction is a point estimate, not a guarantee).
- **Runtime:** 20s.

### SIM-025 — Holm vs Bonferroni vs BH agreement under null
- **DGP:** 10 metrics, all under null. 10,000 reps.
- **Test:** family-wise rejection rate of Holm and Bonferroni ≤ 0.05; BH FDR ≤ 0.05.
- **Tolerance:** [0, 0.06].
- **Runtime:** 5s.

**Total simulation suite runtime budget:** ~10 minutes. Runs nightly + on PR-extended.

---

## 7. Fuzz test plan

Every user-facing parser/loader has a fuzz harness. Fuzz contract: **never crash with an unhandled exception, always return either a structured `OpenXPError` or a structured `ValidationReport` (or, for parsers, raise a documented exception type).**

| # | Target | Generator | Iterations | Assertion | Runtime |
|---|---|---|---|---|---|
| FZ-001 | `CSVLoader.load(tmpfile)` | `binary()` written to a tempfile | 1,000 | result is `LoadResult` OR raises `OpenXPError`, never `pd.errors.ParserError` unwrapped | 10s |
| FZ-002 | `validate_experiment_yaml(path)` | YAML strings: random keys, random nesting up to depth 5, random values | 5,000 | result is `ValidationReport`; `report.ok` is bool; never raises | 20s |
| FZ-003 | `validate_experiment_yaml(dict)` | `dictionaries(text(), one_of(text(), integers(), floats(), lists(text())))` | 5,000 | same | 15s |
| FZ-004 | `validate_metric_yaml` | same shape | 3,000 | same | 10s |
| FZ-005 | `MetricRegistry.load_from_file(path)` | random YAML | 2,000 | raises `OpenXPError` or returns `MetricDefinition` | 8s |
| FZ-006 | `discover_schema(df)` | random DataFrames with random dtypes | 2,000 | returns `SchemaDiscovery`, never raises | 12s |
| FZ-007 | `diff_experiments(before, after)` | random nested dict pairs | 5,000 | returns a list; round-trip property holds | 15s |
| FZ-008 | `srm_check(observed_counts, expected_ratios)` | random non-negative int lists, random ratio lists | 5,000 | returns dict with `verdict` ∈ enum, OR raises `OpenXPError` | 10s |
| FZ-009 | `welch_test(c, t)` | random arrays with NaN/inf injected | 3,000 | returns dict with `error: True` or finite p-value | 10s |
| FZ-010 | `proportion_test(...)` | random ints with sometimes c_success > c_n | 3,000 | structured error or finite result | 8s |
| FZ-011 | `ExperimentStore.save_experiment(id, dict)` | random ids + random dicts | 2,000 | rejects bad ids; never writes outside store root | 15s |
| FZ-012 | `Amendment(...)` constructor | random reasons + random dicts | 2,000 | rejects short/whitespace reasons; never crashes | 5s |
| FZ-013 | `validate_transition(from, to)` | random strings | 2,000 | returns `(bool, str|None)`; never raises | 3s |
| FZ-014 | `winsorize(series, lower, upper)` | random series + random `(lower, upper)` including invalid ranges | 2,000 | rejects `lower > upper`; never crashes | 5s |
| FZ-015 | `adjust_pvalues(pvalues, method)` | random float lists + random method strings | 2,000 | rejects unknown methods; never crashes | 5s |

**Total fuzz budget:** ~3 minutes nightly. PR-extended runs at lower iteration counts (300-500 each) for ~30s.

---

## 8. Benchmark plan

Each benchmark has a baseline that gets locked in via `pytest-benchmark --benchmark-save=baseline`. Regression alert: warn at 1.5×, fail at 2× baseline.

| # | Target | Workload | Threshold | Notes |
|---|---|---|---|---|
| BN-001 | `welch_test` | 1M-row arrays | <100ms | numerical stability bound |
| BN-002 | `proportion_test` | scalar ints | <1ms | trivial; sanity check |
| BN-003 | `ratio_metric_test` | 1M arrays | <300ms | delta method |
| BN-004 | `srm_check` | 1M observed_counts (10 cells) | <50ms | scipy chi-square is fast |
| BN-005 | `srm_diagnose` | 100k assignments × 5 segments | <500ms | per-segment SRM scan |
| BN-006 | `cuped_welch_test` | 1M arrays for pre + post | <300ms | |
| BN-007 | `power_proportion` | scalar | <1ms | |
| BN-008 | `power_sensitivity_table` | 4 mde × 4 traffic = 16 cells | <50ms | |
| BN-009 | `fishers_exact_test` | n=200 | <500ms | scipy.stats.fisher_exact |
| BN-010 | `msprt_test` | 1000 obs per arm, single peek | <50ms | |
| BN-011 | `beta_binomial_test` | 50,000 MC samples | <200ms | |
| BN-012 | `normal_normal_test` | 50,000 MC samples | <200ms | |
| BN-013 | `discover_schema` | 50-col DataFrame, 10k rows | <20ms | |
| BN-014 | `discover_schema` | 1000-col DataFrame, 1k rows | <500ms | wide stress |
| BN-015 | `CSVLoader.load` | 100MB csv (synthetic) | <5s | |
| BN-016 | `CSVLoader.stream` | 1GB csv, chunksize=100k | <30s wall, <500MB RSS | streaming bound |
| BN-017 | `DuckDBLoader.load_query` | 1M-row table, simple SELECT | <2s | |
| BN-018 | `validate_experiment_yaml` | the shipped template | <50ms | |
| BN-019 | `validate_experiment_yaml` | a 1000-line yaml | <500ms | |
| BN-020 | `prepare_experiment_data` | 1M rows, 3 metrics, 2 segments, winsorize | <2s | the analyzer hot path |
| BN-021 | `run_monitor` | 100k rows, 3 guardrails | <2s | the monitor hot path |
| BN-022 | `ExperimentStore.save_experiment` | typical yaml (~5KB) | <10ms | round trip via atomic write |
| BN-023 | `ExperimentStore.load_experiment` | same | <5ms | |
| BN-024 | `ExperimentStore.history` | 1000-event log | <50ms | |
| BN-025 | `diff_experiments` | two 100-key dicts with 10 differences | <10ms | |
| BN-026 | `adjust_pvalues` | 1000 p-values | <5ms | |
| BN-027 | full `/experiment analyze` runner trace | sample-data/clean_ab.csv | <50ms wall | static dispatch budget |
| BN-028 | full `/experiment full` runner trace | sample-data/clean_ab.csv (greenfield) | <500ms wall | end-to-end |
| BN-029 | mSPRT Type-I sim (10k reps × 20 peeks) | nightly only | <30s | the slow sim |
| BN-030 | `power_proportion` end-to-end calibration sim (12 cells × 5k reps) | nightly only | <60s | the slowest power sim |

**Regression policy:** any benchmark > 2× baseline fails CI. >1.5× warns. Re-baseline only with deliberate `--benchmark-save` and a comment in the commit message explaining why.

---

## 9. Security test plan

| # | Concern | Trigger | Expected | Type | Status |
|---|---|---|---|---|---|
| SE-001 | Snowflake password leakage in logs | run `SnowflakeLoader.load_experiment` with `OPENXP_SNOWFLAKE_PASSWORD="hunter2"` and a verbose logger | "hunter2" appears nowhere in `caplog.records` | EXIST | partial — extend to every log path |
| SE-002 | Snowflake password leakage in stack trace | force a connect failure | `caplog.records` and `exc.__str__()` contain no password substring | NEW | |
| SE-003 | Snowflake password leakage in `to_dict()` of `OpenXPError` | wrap a Snowflake auth error in `OpenXPError(details={...})` | password not in `to_dict()` | NEW | |
| SE-004 | SQL injection via `SnowflakeLoader.load_experiment(where="x'; drop table users; --")` | call with the evil where | rejected (validate single quotes / semicolons) OR parameterized; assert via mock cursor | NEW | this is the unfixed S4 |
| SE-005 | SQL injection via DuckDB `load_query("DROP TABLE; SELECT 1")` | DuckDB allows multi-statement; we should reject or warn | document policy + assert | NEW | |
| SE-006 | SQL injection via experiment_id | `save_experiment("'; drop table; --", ...)` | rejected by id regex | NEW | |
| SE-007 | Path traversal: experiment_id `"../../etc/passwd"` | rejected | NEW | |
| SE-008 | Path traversal: experiment_id `"/absolute/path"` | rejected | NEW | |
| SE-009 | Symlink attack: store root contains a symlink to /etc | resolved path is checked to be under store root | NEW | |
| SE-010 | YAML billion-laughs: `&a [&b [&c [...]]]` deeply nested | rejected at parse (PyYAML safe_load is OK; assert) | NEW | |
| SE-011 | YAML bomb: 1MB yaml with 100k keys | rejected with size cap or completes without OOM | NEW | |
| SE-012 | ReDoS in discovery hint patterns | feed pathological inputs to the regex matchers | completes in <100ms | NEW | discovery uses tuples, not regex — assert this stays the case |
| SE-013 | Pickle: ensure no module imports pickle | grep the entire codebase for `import pickle` | zero matches | NEW | |
| SE-014 | `eval`/`exec` ban: ensure no module uses `eval` or `exec` | grep | zero matches | NEW | |
| SE-015 | Metric formula injection (when expression eval lands) | `"__import__('os').system('rm -rf /')"` | rejected by AST whitelist | NEW | depends on PRD §5.16 D.18 implementation |
| SE-016 | OpenXPError to_dict serialization with malicious nested dict | recursion bomb in `details` | bounded depth | NEW | |
| SE-017 | Disk full while writing yaml | atomic write rolls back | NEW | |
| SE-018 | `os.environ` poisoning: `OPENXP_STORE_ROOT=/etc` | accepted only if writable; otherwise clear error | NEW | |

---

## 10. Compatibility matrix

| Python | OS | duckdb | snowflake | numpy | pandas | scipy | Support tier |
|---|---|---|---|---|---|---|---|
| 3.10 | linux | on | on | 1.26 | 2.0 | 1.11 | **Supported** |
| 3.10 | linux | on | off | 1.26 | 2.0 | 1.11 | **Supported** |
| 3.10 | linux | off | off | 1.26 | 2.0 | 1.11 | **Supported** (core only) |
| 3.10 | macos | on | off | 1.26 | 2.2 | 1.13 | **Supported** |
| 3.11 | linux | on | on | 1.26 | 2.1 | 1.12 | **Supported** |
| 3.11 | linux | on | on | 2.0 | 2.2 | 1.13 | **Supported** (numpy 2!) |
| 3.11 | macos | on | off | 2.0 | 2.2 | 1.13 | **Supported** |
| 3.12 | linux | on | on | 2.0 | 2.2 | 1.13 | **Supported** (target) |
| 3.12 | macos | on | on | 2.0 | 2.2 | 1.13 | **Supported** (target) |
| 3.12 | windows | on | on | 2.0 | 2.2 | 1.13 | **Best effort** |
| 3.13 | any | any | any | any | any | any | **Best effort** (no CI) |
| 3.9 or earlier | any | any | any | any | any | any | **Not supported** |

Compatibility tests just run the unit suite under each tier-1 combo. PR-extended runs the matrix in parallel via `tox` or GitHub Actions matrix. Numpy 2 is the most likely break (`np.float_`, `np.product` removed).

---

## 11. Determinism plan

Every RNG user must accept a `seed` (or `rng`) parameter. Every Monte Carlo test runs twice with the same seed and asserts byte-equal output.

**RNG users in the codebase (audit list — verify each accepts seed):**
- `openxp.stats.bayesian.beta_binomial_test` — `seed=None` (verified)
- `openxp.stats.bayesian.normal_normal_test` — `seed=None` (verified)
- `openxp.stats.bayesian.probability_to_beat` — uses MC, takes seed
- `openxp.stats.bayesian.expected_loss` — uses MC, takes seed
- `openxp.stats.cuped.*` — no RNG (deterministic given inputs); confirm
- `openxp.stats.sequential.msprt_test` — deterministic
- `openxp.stats.sequential.always_valid_ci` — deterministic
- `openxp.stats.power.*` — deterministic
- `openxp.stats.power_sensitivity_table` — deterministic
- `openxp.data.snowflake_loader` — uses cursor; no RNG; confirm
- (None elsewhere)

**Determinism tests to add:**
- DT-001: `beta_binomial_test(seed=42)` produces byte-identical output across 3 calls.
- DT-002: same across 2 processes (subprocess invocation).
- DT-003: `normal_normal_test(seed=42)` — same.
- DT-004: All sims in §6 with `seed=42` are byte-identical across reruns.
- DT-005: Property tests with Hypothesis seed pinned via `--hypothesis-seed=42` are reproducible.
- DT-006: pytest-randomly is enabled but tests pass with `--randomly-seed=last`.
- DT-007: Storage timestamps in `log.jsonl` use a `now=` injection point so tests can pin time.
- DT-008: `Amendment.author` defaults to `os.getenv("USER", "unknown")` → tests use `monkeypatch.setenv("USER", "test-user")` to pin.
- DT-009: `MonitorReport` includes a `report_id` derived from inputs, not from time, so two identical inputs produce identical reports.

---

## 12. Mutation testing plan

Run `mutmut` against the 10 most load-bearing math functions. Target: ≥80% mutation score per file. Run nightly only — full mutation passes are slow (10–60 min per file).

| # | Function | File | Why load-bearing | Target score |
|---|---|---|---|---|
| MU-001 | `welch_test` | `ab_tests.py` | t-stat formula + Welch-Satterthwaite df | 85% |
| MU-002 | `proportion_test` | `ab_tests.py` | pooled SE + z-stat | 85% |
| MU-003 | `ratio_metric_test` | `ab_tests.py` | delta method variance formula | 85% |
| MU-004 | `srm_check` | `srm.py` | chi-square statistic + threshold logic | 90% |
| MU-005 | `power_proportion` | `power.py` | sample size closed form | 80% |
| MU-006 | `power_mean` | `power.py` | sample size closed form | 80% |
| MU-007 | `power_ratio` | `ratio_power.py` | delta-method-based n | 80% |
| MU-008 | `cuped_welch_test` | `cuped.py` | θ computation + adjustment | 80% |
| MU-009 | `_compute_theta` | `cuped.py` | the inner cov/var math | 90% |
| MU-010 | `msprt_test` (`_msprt_core`) | `sequential.py` | mixture radius (also has dead algebra to clean up per WAVE1 M2) | 80% |
| MU-011 | `group_sequential_boundaries` | `sequential.py` | alpha spending | 80% |
| MU-012 | `beta_binomial_test` | `bayesian.py` | Beta posterior update | 80% |
| MU-013 | `normal_normal_test` | `bayesian.py` | NIG-ish posterior (currently buggy per WAVE1 M1) | 80% — gate on M1 fix |
| MU-014 | `validate_transition` | `lifecycle.py` | the entire DAG | 95% (it's table-driven, mutations should be caught) |
| MU-015 | `adjust_pvalues` | `corrections.py` | Holm + BH stepwise | 85% |

Survivors get triaged: either a real mutation that needs a test, or an equivalent mutation that should be ignored via a comment.

---

## 13. Contract tests

Public API stability. Every exported function must keep its signature; every return dict must keep its minimum key set.

### 13.1 Symbol export contract
`tests/contracts/test_public_api.py` asserts:
- `set(openxp.stats.__all__) == EXPECTED_STATS_API` (committed list)
- `set(openxp.data.__all__) == EXPECTED_DATA_API`
- … one assertion per package
- Each name in `__all__` resolves to a callable or class
- Each name's `inspect.signature()` matches a snapshot in `tests/contracts/api_v1.json`

### 13.2 Return dict contract
For every stats function:
- Required keys: `interpretation` (always), `error` (always), plus function-specific keys per `tests/contracts/return_shapes.json`.
- Required keys for test functions: `p_value`, `significant`, `point_estimate`, `ci_lower`, `ci_upper` (plus `interpretation`).
- Required keys for power functions: `sample_size_per_group`, `total_sample_size`, `interpretation`.
- Required keys for SRM: `verdict`, `p_value`, `interpretation`.
- Required keys for guardrail: `verdict`, `point_estimate`, `worst_case`, `interpretation`.

### 13.3 Snapshot reference
`tests/contracts/api_v1.json` is the locked snapshot. Generated once via a helper script that introspects every public function and writes:
```json
{
  "openxp.stats.welch_test": {
    "kind": "function",
    "params": [
      {"name": "control", "kind": "POSITIONAL_OR_KEYWORD", "default": null},
      {"name": "treatment", "kind": "POSITIONAL_OR_KEYWORD", "default": null},
      {"name": "alpha", "kind": "POSITIONAL_OR_KEYWORD", "default": 0.05}
    ],
    "return_keys_minimum": ["interpretation", "p_value", "significant", "point_estimate", "ci_lower", "ci_upper"]
  },
  ...
}
```
A test reads this file, introspects the live module, and asserts equality. Drift fails the test. Re-blessing requires `pytest --snapshot-update` and a comment in the PR.

### 13.4 Module export tests
- `from openxp.stats import welch_test, proportion_test, ...` (explicit list of every documented import) — the CLAUDE.md and skill.md examples must work as written. This test mirrors every `from openxp.stats import X` example in the docs.
- `from openxp.stats.power import power_ratio` — currently fails because `power_ratio` lives in `ratio_power.py`. Per FINAL_STATUS gap 1, decide: either add re-exports at the submodule level, OR fix the docs and add tests that the documented submodule paths work.

---

## 14. Sample data test matrix

Every sample CSV has a documented expected verdict. The runner test feeds each CSV through `/experiment analyze` (or `full`), captures the resulting `analysis_results.json` + `interpretation.md`, and snapshot-asserts the verdict + key numbers.

| File | Scenario | SRM | Primary effect | Guardrails | Expected verdict | Notes |
|---|---|---|---|---|---|---|
| `clean_ab.csv` | Standard A/B | PASS | Significant positive | clean | **SHIP** | proportion test on `converted` |
| `no_effect.csv` | Null result, well-powered | PASS | Null, n large | clean | **LEARN (powered)** | observed MDE ≤ planned |
| `srm_violation.csv` | Broken randomization | BLOCK | n/a | n/a | **INVALID** | terminates at SRM gate |
| `guardrail_violation.csv` | Primary up, guardrail down | PASS | Significant positive | RED on latency | **INVESTIGATE** | trade-off quantified |
| `underpowered.csv` | Null, insufficient power | PASS | Null, n small | clean | **LEARN (underpowered)** | calls `extension_estimate` |
| `mixed_results.csv` | Segment-level reversals | PASS | Significant overall | one segment reverses | **INVESTIGATE** | segment table populated |
| `checkout_redesign.csv` | TBD — document expected verdict | TBD | TBD | TBD | **TBD** | in progress — see §18 Q1 |

For each row, write:
- An E2E test (`test_full_pipeline_<scenario>`).
- A snapshot of the `analysis_results.json` shape (not exact numbers — those drift; assert keys + verdict + sign of effect).
- A snapshot of the `interpretation.md` heading for the verdict.

---

## 15. CI/CD ordering and runtime budget

Five stages, ordered fastest-to-slowest. Each stage's failure behavior is in the table.

| Stage | Trigger | Test groups | Max runtime | Failure behavior |
|---|---|---|---|---|
| Pre-commit (local) | `git commit` via hook | unit (subset: stats math + lifecycle), contract, determinism | <5s | block commit |
| PR check (GitHub Actions) | every PR push | unit (full), integration, property (50 examples), snapshot, validators, lifecycle, security, contract, E2E | <60s | block merge |
| PR extended | label `run-heavy` on PR | simulation, fuzz, benchmark, compatibility matrix | <10 min | block merge |
| Nightly (cron) | nightly UTC midnight | full mutation (all 15 targets), long-horizon sims (100k+ reps), large-data stress, fuzz at 10× iterations, bench regression check | <60 min | open an issue, slack alert |
| Release (manual gate) | tagged release | everything + manual smoke + compatibility on every supported python/os combo via tox + PyPI publish dry-run | <120 min | block release |

### 15.1 Stage details

**Pre-commit** — runs the smallest fast subset:
- Tests in `tests/unit/test_*_fast.py` only
- `tests/contracts/test_public_api.py`
- `tests/test_determinism_smoke.py`
- Aim: catch obvious breakage in <5s. No I/O, no network, no large data.

**PR check** — the main gate. Must be green for merge.
- Everything in `tests/unit/` (391 + new)
- `tests/integration/` (currently empty — to be populated)
- `tests/property/` with `--hypothesis-profile=fast` (50 examples)
- `tests/snapshot/`
- `tests/lifecycle/`
- `tests/security/`
- `tests/contracts/`
- `tests/e2e/` (the runner-based skill flows)
- Run via `pytest -n auto --maxfail=5`

**PR extended** — opt-in via PR label.
- `tests/sim/`
- `tests/fuzz/`
- `tests/bench/` with regression check vs locked baseline
- Compatibility matrix (a subset: 3.11 + 3.12 × linux+macos)

**Nightly** — runs unattended.
- Full simulation suite (10k+ reps)
- Mutation testing on §12 targets
- Stress tests with synthetic 1GB CSVs
- Hypothesis at `--hypothesis-profile=ci` (1000 examples)
- Benchmarks with regression alerts to slack/issue

**Release** — manual.
- Everything + PyPI publish dry-run (`twine check`)
- Run on every supported python × os combo
- Smoke test the `pip install agentxp` flow on a fresh venv

---

## 16. Tooling and dependencies

**To install (recommend adding to `[project.optional-dependencies]` `dev` group in pyproject.toml — do not edit yourself):**

```
pytest >= 8.0
pytest-xdist >= 3.5         # parallel test execution
pytest-benchmark >= 4.0     # benchmarks
pytest-cov >= 4.1           # coverage (for the gap analysis re-runs)
pytest-randomly >= 3.15     # randomize test order, surface order-dependencies
pytest-snapshot >= 0.9      # snapshot testing
hypothesis >= 6.100         # property-based + fuzz
faker >= 22.0               # fuzz data generation
mutmut >= 2.4               # mutation testing
psutil >= 5.9               # memory measurements in benchmarks
```

**Optional / nightly-only:**
```
cosmic-ray >= 8.3           # alternative mutation runner
locust >= 2.20              # load testing (not currently planned)
```

**Pin discipline:** lock to compatible major versions in pyproject.toml; pin exact versions in a `requirements-dev.lock` for nightly/CI reproducibility.

**Hypothesis profiles:**
- `dev`: 50 examples, no shrinking budget
- `ci`: 1000 examples, full shrinking
- `fast`: 25 examples, used in pre-commit if needed

---

## 17. Recommended sequence to execute this plan

Eight build waves. Each wave: name, scope, rough test count, dependencies on earlier waves, review gate.

### Wave T1 — Contract snapshot + API stability
- **Scope:** §13. `tests/contracts/test_public_api.py`, `tests/contracts/api_v1.json` snapshot, return-dict shape contract, every documented `from openxp... import X` is asserted to actually work.
- **New tests:** ~25
- **Dependencies:** none
- **Review gate:** Shane reviews the api_v1.json snapshot; this is the thing that makes future signature drift loud.

### Wave T2 — Property-based invariants
- **Scope:** §5. 25 properties using Hypothesis. Mostly stats functions, lifecycle, validators, diff_experiments.
- **New tests:** ~25 properties (each covers ~50 generated cases)
- **Dependencies:** Hypothesis installed (T1 doesn't strictly require it, but it's cheap to add at the same time)
- **Review gate:** Shane reviews the property list to confirm the invariants are the *right* ones.

### Wave T3 — Exhaustive lifecycle state machine coverage
- **Scope:** §3.3 (LE-001 through LE-083) + property tests for the DAG.
- **New tests:** ~85
- **Dependencies:** none
- **Review gate:** all 11 states × 11 states = 121 transitions explicitly tested (legal + illegal). Should catch any future silent edits to `lifecycle.py`.

### Wave T4 — Validators and edge case unit tests
- **Scope:** §3.6 (VE-001 through VE-037) + §3.1 statistical edge cases (ST-001 through ST-103) + §3.2 data edge cases (DE-001 through DE-041) + §3.4 I/O (IE-001 through IE-016).
- **New tests:** ~200
- **Dependencies:** none (these are unit tests; no fancy infra needed)
- **Review gate:** the 5 priority modules in §4 (`ab_tests`, `guardrails`, `srm`, `prep`, `_trace`) each have ≥3 tests per public function.

### Wave T5 — Simulation tests (statistical correctness)
- **Scope:** §6. 25 simulations.
- **New tests:** ~25 (each is one test function, but one test = many MC reps = several seconds runtime)
- **Dependencies:** T1 + T2 (so we have stable contracts and properties)
- **Review gate:** Shane reviews tolerance bands. ST-048 and SIM-023 xfails are now resolved (see §18 Q4) — remove markers and expect pass.
- **Runtime cost:** adds ~10 min to nightly. PR-extended runs at lower rep counts.

### Wave T6 — Fuzz + security
- **Scope:** §7 + §9. 15 fuzz harnesses + 18 security tests.
- **New tests:** ~33
- **Dependencies:** Hypothesis (from T2)
- **Review gate:** SE-004 (Snowflake `where` injection) is the unfixed S4 — either patch the loader or document the contract. Shane decides.

### Wave T7 — Benchmarks + mutation
- **Scope:** §8 + §12. 30 benchmarks + mutation runs on 15 functions.
- **New tests:** ~30 benchmarks; mutation runs are not "tests" per se but produce a score per file
- **Dependencies:** T1–T5 (mutation needs strong tests to score well)
- **Review gate:** baselines locked. Mutation scores reviewed for survivors.
- **Runtime cost:** ~60 min nightly for mutation. Benchmarks add ~5 min PR-extended.

### Wave T8 — Integration + E2E (the big one)
- **Scope:** §3.5 (SK-001 through SK-033) + the use case × edge case combos. Every `/experiment` mode flow against every relevant edge case.
- **New tests:** ~200 (this is where the explosion happens — every mode × every checkpoint × every state × every sample CSV)
- **Dependencies:** T1–T7 (you want stable contracts and good unit coverage before integrating)
- **Review gate:** every mode in §2.1 has end-to-end coverage; every Type-C checkpoint is exercised; every state in the lifecycle has at least one E2E test that lands in it.

### Cumulative
- Test count after T1–T8: 391 (existing) + ~625 (new) ≈ **1016**, give or take, depending on how tight you write the integration tests.
- The "200 from T8" is the loose number. If integration tests are tight (one test per `(mode, edge case)` instead of one per `(mode, edge case, sample csv)`), it can be 100–250.

---

## 18. Open questions for Shane — ALL RESOLVED

All 14 questions have been resolved: 6 via code changes in build waves, 5 via policy decisions, 1 via analysis, and 2 are being handled by a parallel agent.

### Q1: `checkout_redesign.csv` expected verdict
**Status:** IN PROGRESS (parallel agent)
**Resolution:** Resolution pending from parallel analysis. The parallel agent is running the analysis now to determine expected verdict, SRM outcome, primary metric result, guardrail status, and EWL classification.
**Test impact:** The §14 E2E matrix row for `checkout_redesign.csv` remains TBD until the analysis completes; all other 6 CSVs are unaffected.

### Q2: Default for `set_trace`
**Status:** RESOLVED (W19)
**Resolution:** `_TRACE_ENABLED = True` is set at module level in `openxp/stats/_trace.py` (line 43). The D.9 audit-trail contract requires traces by default — the orchestrator does not need to call `set_trace(True)` explicitly. Callers who want slimmer dicts opt out via `set_trace(False)`.
**Test impact:** SK-019, SK-020 unblocked. Tests should assert trace is ON by default (i.e., `is_trace_enabled() is True` at import time and `computation_trace` key present in all stats return dicts).

### Q3: `ExperimentStatus` enum unification
**Status:** RESOLVED (W19)
**Resolution:** The Pydantic `ExperimentStatus` enum in `openxp/schemas/experiment.py` now carries all 11 states (DESIGNING, POWERED, COLLECTING, ANALYZING, INTERPRETED, REPORTED, SHIPPED, COMPLETED, ABANDONED, INVALID, BLOCKED), matching `lifecycle.ALL_STATES`. `test_schema_lifecycle_sync.py` asserts bidirectional equality between the enum members and `ALL_STATES`.
**Test impact:** VE-024 unblocked — remove the `xfail` marker. The test should now pass: loading `ExperimentConfig(**{"status": "SHIPPED"})` succeeds.

### Q4: `normal_normal_test` strong-prior fix
**Status:** RESOLVED (W17)
**Resolution:** Option (a) was implemented: full Normal-Inverse-Gamma conjugate posterior in `openxp/stats/bayesian.py`. The update is `sigma^2 ~ InvGamma(alpha_0 + n/2, beta_0 + SS/2 + shrinkage)` where shrinkage = `0.5 * (prec_pri * n / (prec_pri + n)) * (xbar - prior_mean)^2`, then `mu | sigma^2 ~ N(posterior_mean, sigma^2 / (prec_pri + n))`. This correctly widens posterior variance under strong priors. Three new tests were added in W17.
**Test impact:** SIM-023, ST-048 unblocked — remove `xfail` markers. Both should now pass with the NIG implementation.

### Q5: `extension_estimate` signature
**Status:** RESOLVED (W16 + W20)
**Resolution:** Kept the real signature: `extension_estimate(current_n, current_mde_observed, required_power, baseline_variance, daily_traffic, alpha=0.05)`. No PRD-literal wrapper was added — the real signature is better (it exposes the actual inputs the z-formula needs). MODES.md was updated in W20 to document the real signature instead of the PRD stub.
**Test impact:** SK-019, SK-020 unblocked. All §3.5 tests should use the real 6-parameter signature. SIM-024 uses the real signature as well.

### Q6: Submodule re-exports
**Status:** RESOLVED (W20)
**Resolution:** `from openxp.stats import X` is the canonical import path. `openxp/stats/__init__.py` re-exports all public functions including `set_trace` and `is_trace_enabled` (lines 83-84, in `__all__` at lines 134-135). MODES.md and skill.md were rewritten in W20 to use this path exclusively. No per-submodule re-exports (e.g., `from openxp.stats.power import power_ratio`) are guaranteed.
**Test impact:** Contract tests (section 13.4) should assert the top-level `from openxp.stats import ...` path only. Do not test submodule import paths.

### Q7: Welch one-sided
**Status:** DECIDED
**Resolution:** Permanent two-sided. `welch_test` stays simple with no `alternative=` kwarg. One-sided non-inferiority testing goes through `guardrail_test(metric_type="mean", nim_relative=..., invert=...)`, which already handles the directional hypothesis correctly. The MODES.md blockquote was updated by the parallel agent to reflect this routing.
**Test impact:** ST-001 through ST-005 should test two-sided behavior only. Any one-sided tests belong in the guardrail test suite, not the Welch suite.

### Q8: `SnowflakeLoader.where` parameter
**Status:** IN PROGRESS (parallel agent)
**Resolution:** The parallel agent is replacing the raw `where` string parameter with a parameterized `filters=` dict plus identifier validation. This eliminates the SQL injection surface while keeping the filtering capability.
**Test impact:** SE-004 and fuzz tests should target the `filters=` dict path once the change lands. Do not write tests against the old `where` string interface.

### Q9: `run_monitor` `current_n` default
**Status:** RESOLVED (W18)
**Resolution:** `run_monitor` now accepts `current_n_fn: Callable[[Any], int] | None = None` as a parameter (see `openxp/monitoring/report.py` line 115). Resolution order: (1) explicit `current_n` in context dict, (2) `current_n_fn(df)` if provided, (3) `len(df)` fallback. The docstring (lines 126-131) warns that `len(df)` is wrong for panel data and advises passing `current_n_fn=lambda df: df["user_id"].nunique()`.
**Test impact:** SK-021 through SK-023 should test the explicit `current_n_fn` path (pass a lambda, verify it is called). Also test the fallback to `len(df)` when neither `current_n` nor `current_n_fn` is provided.

### Q10: Result Pydantic models
**Status:** RESOLVED (W19)
**Resolution:** 15 Pydantic models are scaffolded in `openxp/schemas/results.py`: TestResult, PowerResult, DurationResult, MDEResult, SensitivityTable, SRMResult, DiagnosisResult, EffectSizeResult, LiftResult, CorrectionResult, CUPEDResult, SequentialResult, BayesianResult, ExtensionResult, MonitorReportModel. All inherit from `_Result` which sets `extra="allow"` so additional keys (like `computation_trace`) round-trip without error.
**Test impact:** Contract tests should assert Pydantic model construction from live function outputs (e.g., `TestResult(**welch_test(c, t))` succeeds), not just plain dict key checks.

### Q11: Integration test runtime budget
**Status:** DECIDED
**Resolution:** Use `pytest-xdist -n auto` for PR checks. Split E2E into two tiers: fast E2E (<5s total, happy paths only) runs in the PR check; full E2E (all 200 tests including edge cases) runs in PR-extended (triggered by `run-heavy` label). This keeps PR check under 60s while still covering the critical paths.
**Test impact:** T8 tests need a `@pytest.mark.slow` or equivalent marker so the CI config can split them. Fast E2E tests should be self-contained and not depend on external state.

### Q12: Mutation testing tool choice
**Status:** DECIDED
**Resolution:** `mutmut`. It is simpler, adequate for the 15 mutation targets, well-maintained, and pip-installable without extra configuration. Run in nightly CI only (too slow for PR checks). Pin the version in `requirements-dev.txt`.
**Test impact:** Section 12 mutation scoring runs use `mutmut run --paths-to-mutate=<target>`. No changes to test structure needed.

### Q13: Benchmark baseline storage
**Status:** DECIDED
**Resolution:** In-repo at `tests/benchmarks/baselines/`. Commit the JSON baseline files. CI compares against committed baselines via `pytest-benchmark --benchmark-compare`. Update baselines via `pytest-benchmark --benchmark-save=baseline` + commit. This is simpler than out-of-band artifact management and makes baselines reviewable in PRs.
**Test impact:** Section 8 benchmark tests load baselines from `tests/benchmarks/baselines/*.json`. The `.gitignore` must NOT exclude this directory.

### Q14: Compatibility matrix scope
**Status:** DECIDED
**Resolution:** Blessed combo (Python 3.12 + linux + numpy 2 + pandas 2.2 + scipy 1.13) runs in PR check. The full 9-combo matrix runs nightly. This saves approximately 10 minutes of CI time per PR while still catching compatibility breaks within 24 hours.
**Test impact:** Section 10 compatibility matrix config should define `BLESSED_COMBO` as the PR-check target and `FULL_MATRIX` as the nightly target. No test code changes needed — only CI workflow config.

---

## Appendix A — Quick reference: how many tests will exist when we're done

| Wave | New tests | Cumulative |
|---|---:|---:|
| Existing | 391 | 391 |
| T1 Contracts | 25 | 416 |
| T2 Properties | 25 | 441 |
| T3 Lifecycle | 85 | 526 |
| T4 Edge cases (validators + statistical + data + I/O) | 200 | 726 |
| T5 Simulations | 25 | 751 |
| T6 Fuzz + security | 33 | 784 |
| T7 Benchmarks (15) + mutation runs (15 targets) | 30 | 814 |
| T8 Integration / E2E | 200 | **1014** |

(Mutation runs aren't counted as tests in the suite count; they're separate scoring runs.)

## Appendix B — Edge case totals by category

- Statistical edge cases (ST): 103 cases
- Data edge cases (DE): 41 cases
- Lifecycle edge cases (LE): 83 cases
- I/O / environment edge cases (IE): 16 cases
- Skill / orchestrator edge cases (SK): 33 cases
- Validation edge cases (VE): 37 cases
- Property tests (PR): 25 cases
- Simulations (SIM): 25 cases
- Fuzz harnesses (FZ): 15 targets
- Benchmarks (BN): 30 targets
- Security tests (SE): 18 cases
- Determinism tests (DT): 9 cases
- Mutation targets (MU): 15 functions

**Total enumerated cases: 453** (some overlap between categories, e.g., a property test may also satisfy a unit test row).

## Appendix C — How to read the edge case rows

Every row in §3 has:
- A stable id (`ST-001`, `LE-042`, etc.) — reference these in test names.
- A trigger column — what makes the test fire.
- An expected behavior column — the contract to assert.
- A `Type` column — which test type from §1 this falls under.
- A `P/B` column — pass/fail or benchmark.
- A `Status` column — NEW (write it), EXIST (already covered, leave alone), EXTEND (covered but assertions need to be broader).

A row can have multiple types (e.g., `U,P` means unit + property test of the same invariant). When writing the test file, prefer to put the unit test in `tests/unit/test_<module>.py` and the property test in `tests/property/test_<module>_props.py`.

## Appendix D — File layout for new tests

Recommended directory structure (the existing flat `tests/` layout will be reorganized when T1 lands):

```
tests/
├── conftest.py                     # shared fixtures (tmp_path, store, sample CSVs, seed pinning)
├── unit/
│   ├── test_ab_tests.py            # existing
│   ├── test_ab_tests_edge.py       # NEW — ST-001..ST-103 unit half
│   ├── test_validators_rules.py    # NEW — VE-001..VE-037
│   ├── test_csv_loader_edge.py     # NEW — DE-023..DE-035
│   └── ...
├── integration/
│   ├── test_analyze_flow.py        # NEW — SK-005..SK-009
│   ├── test_full_pipeline.py       # NEW — SK-027..SK-033
│   └── ...
├── e2e/
│   ├── test_full_clean_ab.py       # NEW
│   ├── test_full_srm_violation.py  # NEW
│   └── ...
├── property/
│   ├── test_stats_invariants.py    # NEW — PR-001..PR-014
│   ├── test_lifecycle_props.py     # NEW — LE-053..LE-058
│   ├── test_validator_props.py     # NEW — PR-015..PR-016
│   └── ...
├── sim/
│   ├── test_welch_type_i.py        # NEW — SIM-001
│   ├── test_power_calibration.py   # NEW — SIM-011..SIM-013
│   ├── test_msprt_anytime_valid.py # EXTEND — SIM-016 (existing test_sequential.py:18)
│   └── ...
├── fuzz/
│   ├── test_fuzz_csv_loader.py     # NEW — FZ-001
│   ├── test_fuzz_validator.py      # NEW — FZ-002..FZ-004
│   └── ...
├── bench/
│   ├── test_bench_stats.py         # NEW — BN-001..BN-014
│   ├── test_bench_io.py            # NEW — BN-015..BN-021
│   ├── baselines/                  # locked baselines (committed)
│   └── ...
├── security/
│   ├── test_snowflake_secrets.py   # EXTEND — SE-001..SE-003
│   ├── test_path_traversal.py      # NEW — SE-007..SE-009
│   ├── test_yaml_bomb.py           # NEW — SE-010..SE-011
│   └── ...
├── lifecycle/
│   └── test_state_machine_full.py  # NEW — LE-001..LE-058
├── contracts/
│   ├── test_public_api.py          # NEW
│   ├── api_v1.json                 # NEW snapshot
│   └── return_shapes.json          # NEW
└── snapshot/
    ├── test_analysis_snapshots.py  # NEW — sample CSV verdict snapshots
    └── snapshots/                  # auto-generated by pytest-snapshot
```

---

## Appendix E — Things explicitly out of scope for this plan

- Coverage.py runs (the gap analysis in §4 is estimated by inspection, not by `coverage.py`). Add to nightly if you want hard numbers.
- Load testing (locust / k6) — AgentXP runs in Claude Code, not as a service. There's no QPS to load-test.
- API documentation generation (Sphinx, mkdocs) — out of scope for the test plan.
- Performance regression dashboards (e.g., bencher.dev integration) — nice-to-have for v2.
- Property-based testing of report markdown format — possible but expensive to express invariants over markdown. Snapshot tests are the right tool for §14.
- Testing the agent prose itself (the `agents/*.md` files) — these are read-and-execute prompts, not code. The runner-based E2E in T8 covers the same ground from the orchestrator side.
- Testing the markdown `walkthroughs/*.md` against the real API — this is a documentation hygiene concern (per WAVE2 C1), not a test plan concern. A separate "doctest the walkthroughs" pass would be a different work item.

---

End of TEST_PLAN.md.
