# Wave 2 Independent Code Review

**Reviewer:** independent pass (no code changes)
**Scope:** `agentxp/monitoring/`, `agentxp/amendments/`, `agentxp/errors/`, `agentxp/validators/`, 3 new test files, 8 walkthrough markdown files, `DEMO.md`
**Test suite:** `310 passed in 4.86s` on a clean run; ran 3 consecutive passes — all green, byte-identical counts (`4.86s / 4.96s / 4.81s`). No flakiness observed. Wave 1's 238 tests still pass; Wave 2 adds 72 on top.
**Import probe:** `from agentxp import monitoring, amendments, errors, validators` → OK, no circular imports, no name collisions with Wave 1.
**End-to-end scratch run:** wired a fake 10-day dataframe through `run_monitor` with an `ExperimentStore` on a tmp path — aggregated GREEN, persisted one analysis JSON, recommendations populated. The Python surface composes cleanly.

---

## 1. TL;DR

- **Verdict: SHIP WITH FIXES.** The Python modules are tight — `srm_trend` handles empty windows and binning correctly, `guardrail_health` actually applies the NI margin to the CI bound (not the point estimate), `AgentXPError.__str__` matches spec, the validator collects all findings in one pass. Determinism is clean, 310/310 three times in a row.
- **One real blocker before integration:** `walkthroughs/monitoring.md` documents a fabricated API that does not match `agentxp.monitoring`. Every code example in that file — `run_monitor(data=..., experiment_yaml=...)`, `srm_trend(..., window_days=7)`, `guardrail_health(guardrails=[...])`, `sample_accumulation(target_n=..., elapsed_days=...)`, verdicts `HEALTHY/WATCH/WARN/STOP` — is wrong. The real module uses a context-dict contract, `window="1d"`, `(guardrail_metrics, thresholds)`, `(current_n, required_n, daily_traffic, days_elapsed)`, and `GREEN/YELLOW/RED`. Any reader who copies that snippet will get an immediate `TypeError`.
- **One sharper math point (non-blocking):** `sample_accumulation` degenerates to `pace_ratio=1.0` → GREEN when `days_elapsed=0` and traffic is positive. This is the intended "nothing should be expected yet" branch, but it hides a stalled-on-day-0 case where `daily_traffic > 0` but `current_n == 0`. Minor — document or special-case it.

---

## 2. Critical Issues (would break things)

### C1. `walkthroughs/monitoring.md:62-99` — hallucinated API, wrong verdicts, wrong field names
The "Python API" block is a spec from an earlier draft, not the code that shipped:

| Walkthrough shows | Reality in `agentxp/monitoring/` |
|---|---|
| `run_monitor(data=df, experiment_yaml="…")` | `run_monitor(experiment_id, data_loader, store=None)` where `data_loader` is a dict or zero-arg callable returning `{df, treatment_col, timestamp_col, guardrail_metrics, thresholds, required_n, daily_traffic, days_elapsed, …}` |
| `report["verdict"]` → `"HEALTHY" / "WATCH" / "WARN" / "STOP"` | `report.status` → `"GREEN" / "YELLOW" / "RED"` |
| `srm_trend(df, treatment_col="variant", window_days=7)` | `srm_trend(df, treatment_col, timestamp_col, window="1d", threshold=0.01, expected_ratios=None)` — no `window_days`, **`timestamp_col` is required** |
| `guardrail_health(df, guardrails=[{"name": ..., "threshold": ..., "direction": ...}])` | `guardrail_health(df, treatment_col, guardrail_metrics, thresholds={metric: {nim, direction, type}}, …)` — split into two args, NIM instead of "threshold" |
| `sample_accumulation(df, target_n=25000, planned_duration_days=14, elapsed_days=6)` | `sample_accumulation(current_n, required_n, daily_traffic, days_elapsed, planned_duration_days=None, now=None)` — takes scalars, not a dataframe |

The walkthrough even acknowledges this with a "Note: the API above is the planned contract" disclaimer at the bottom (`monitoring.md:101`) — but the shipped implementation diverged, and the disclaimer was never removed. Every other Wave 2 walkthrough grep-checks clean against the real API; this one is the outlier. **Rewrite before integration.**

### C2. `walkthroughs/monitoring.md:44-48` — verdict vocabulary contradicts the rest of AgentXP
The walkthrough documents the monitor as producing `HEALTHY / WATCH / WARN / STOP`. `MonitorReport.status` is `GREEN / YELLOW / RED`. Individual checks use the Wave 1 vocabulary `PASS / WARNING / BLOCK`. That's already two layers — adding a third that doesn't exist in the code will confuse agents and readers. Pick one and make the walkthrough match.

---

## 3. Math / Correctness Issues

### M1. `sample_accumulation` pace math is correct but has a blind spot at day 0 — `agentxp/monitoring/sample_accumulation.py:84-91`
```python
if planned_duration_days > 0 and planned_duration_days != float("inf"):
    expected_fraction = min(1.0, days_elapsed / planned_duration_days)
else:
    expected_fraction = 0.0

pace_ratio = (
    fraction_complete / expected_fraction if expected_fraction > 0 else 1.0
)
```
At `days_elapsed = 0`, `expected_fraction = 0` → `pace_ratio = 1.0` → GREEN regardless of `current_n`. That's correct in the "nothing expected yet" sense, but it silently passes a pipeline that has been running a day with zero enrollments (covered by the `stalled` branch only if `daily_traffic <= 0`). Low-impact because `run_monitor` rarely runs on day 0, but worth a one-line special case: if `days_elapsed == 0 and current_n == 0 and daily_traffic > 0`, return a YELLOW "too early to tell" instead of GREEN.

### M2. `srm_trend` time-window binning is correct and covered — verified
`pd.Grouper(freq=freq)` with `_window_alias` resolving `"1d" → "1D"`, `"1w" → "7D"`, etc. Empty chunks are skipped (`if len(chunk) == 0: continue`). Missing variants per window are reindexed to 0 against a global sorted variant order (`variant_order = sorted(work[treatment_col].dropna().unique().tolist())`) so a full arm outage in a given window registers as the intended `[N, 0]` input to `srm_check`. First window at experiment start with 1 row is handled gracefully — `srm_check` will WARN/BLOCK, not crash. Edge cases verified in `test_srm_trend_empty_df_returns_block`, `test_srm_trend_missing_timestamp_column_returns_block`. Clean.

### M3. `guardrail_health` NI margin is applied to the CI bound, not the point estimate — verified
`guardrail_health.py:95-106`:
```python
if direction == "decrease":
    worst_case = ci_lower
    margin = -nim_abs
    violated = worst_case < margin
...
else:
    worst_case = ci_upper
    margin = nim_abs
    violated = worst_case > margin
```
This is the correct non-inferiority formulation. The diff (point estimate) is only used for the `marginal` WARNING case. `invert=True` per-check is not a parameter — the `direction` string handles it: `"decrease"` means decreases are bad (treats `ci_lower` as worst-case), `"increase"` means increases are bad (treats `ci_upper` as worst-case). NIM is a relative margin (`nim * |baseline|`) with a fallback to absolute for zero baselines (`nim_abs = abs(nim) * abs(baseline) if baseline != 0 else abs(nim)`). Covered by `test_guardrail_health_clean_metric_returns_pass` and `test_guardrail_health_degraded_metric_blocks`. Correct.

### M4. `run_monitor` worst-of-three aggregation is correct — verified
`report.py:196-201` → `verdict_to_light` maps each check's internal PASS/WARNING/BLOCK to GREEN/YELLOW/RED, then `worst_light` picks the max by rank `{GREEN:0, YELLOW:1, RED:2}`. Covered by `test_run_monitor_worst_of_three_wins_red`. Clean.

### M5. `run_monitor` store persistence silently swallows `FileNotFoundError` — `agentxp/monitoring/report.py:230-237`
```python
if store is not None:
    try:
        store.save_analysis(experiment_id, report.to_dict())
    except FileNotFoundError:
        pass
```
The comment says this handles the case where "the caller passed a store but the experiment dir doesn't exist." That's *only* the `FileNotFoundError` raised by `save_analysis` when `_yaml_path(...).exists()` is false — no other errors are swallowed. So this is **narrow-by-design**, which is what you want, but there's no corresponding warning in the report. An agent that passes a bogus experiment id and gets back a report with `experiment_id="bogus"` will have no idea the persistence failed. Suggest: append to `report.recommendations` a "NOTE: report not persisted — experiment id not registered in store" line so the failure is observable.

### M6. `diff_experiments` nested-dict diff is correct; list rename collapses to one "changed" at the index — verified
`diff.py:45-79`. Recurses into dicts key-by-key over the union of sorted keys, recurses into lists index-by-index padding with `_SENTINEL`, reports scalar/type-mismatch changes, and reports added/removed for length deltas. Stable ordering (sorted keys), no mutation of inputs. List key-renames at the same index are detected as nested `.name` changes (`test_diff_deep_list_fields`). The "key rename shows as one remove + one add" case is accepted as-is and called out in the module docstring. Correct.

### M7. `classify_change` matches the PRD material/administrative split — verified
`diff.py:104-187`. Prefix match over `_MATERIAL_PREFIXES = (hypothesis, metrics, power, decision_rules, variants, data)`. Admin leaves (`description, notes, tags, owner`) win even inside material trees; admin prefixes (`description, notes, tags, owner, timeline, results`) win at top level. `experiment.name` stays admin via the leaf rule — but **metric/variant names** (`metrics.primary.name`) are material because the leaf rule only strips top-level `experiment.` before classification. `_leaf_name("experiment.metrics.primary.name") = "name"` → NOT in `_ADMIN_LEAVES` → material. Wait — "name" IS in `_ADMIN_LEAVES`. Let me re-read.

Actually, `_ADMIN_LEAVES = frozenset({"description", "notes", "tags", "owner"})` — "name" is deliberately NOT there. The comment at `diff.py:113-116` explains: "we deliberately do NOT put 'name' here — metric/variant renames are material." But then `test_classify_experiment_name_is_administrative` passes. How? Because `experiment.name` at the top level has head `name` — and `name` is NOT in `_ADMIN_PREFIXES` either, which means `classify_change({"path": "experiment.name", ...})` falls through to the "Unknown top-level field → administrative" fallback at line 187. That works only because `"name"` is a top-level field. A rename to `metrics.primary.name` has head `metrics` → material branch, correct. The classifier is correct but the mechanism is subtle — a one-line comment at the fallback explaining "top-level `name` is intentionally caught here, not in admin leaves" would save a future reader 5 minutes.

### M8. `AmendmentTracker` reason enforcement and default author — verified
`tracker.py:73-79` enforces `len(reason.strip()) >= 10` in `__post_init__`, raising `ValueError` with a hint. `test_reason_too_short_raises` covers the `"short"` (5 chars) case. Default author from `os.getenv("USER", "unknown") or "unknown"` — handles the CI case where `USER` is unset cleanly. Note: on GitHub Actions `USER=runner`, on typical Docker `USER` may be empty string → double fallback kicks in. Acceptable.

### M9. `AgentXPError.__str__` format matches the spec — verified
`base.py:63-67`:
```python
def __str__(self) -> str:
    header = f"[{self.code}] {self.message}"
    if self.hint:
        return f"{header}\n  hint: {self.hint}"
    return header
```
Exactly `"[CODE] message\n  hint: ..."`. `to_dict` round-trips cleanly through `json.dumps` (tested at `test_agentxp_error_to_dict_is_json_serializable`). Severity validation via `frozenset` membership. Empty code and empty message both rejected with `ValueError`. Clean.

### M10. `validate_experiment_yaml` collects all findings in one pass — verified
`experiment_validator.py:272-477` never returns early on a finding (only on the fatal load error, which is correct — there's nothing to validate if the YAML can't parse). Sequentially checks id, name, hypothesis, metrics, primary_metric, success_criteria, power block (with nested alpha / mde / power / duration / baseline checks), treatment/variants (with allocation sum tolerance `abs(total - 1.0) > 0.001`), cross-field `primary_metric in metric_names`, and `lifecycle_state in ALL_STATES`. `test_validator_collects_multiple_findings_not_first` deletes three fields and confirms all three appear. Allocation tolerance tested at `test_allocation_sum_within_tolerance_ok` (0.5005 + 0.4995 = OK) and `test_bad_allocation_sum_emits_schema_invalid` (0.4 + 0.4 = not OK). Cross-field primary_metric check verified at `test_primary_metric_not_in_metrics_list_fails`. All correct.

---

## 4. Style / Convention Violations

### S1. `monitoring/report.py:186` — `current_n` default is `len(df)`, which is row count, not unique users
```python
current_n = int(ctx.get("current_n", len(df)))
```
If the df has multiple events per user (the common case for revenue/latency metrics), `len(df)` over-counts. The ctx dict already accepts a `current_n` key, so the caller can pass the right thing — but the default is wrong for any panel data. Suggest: add a warning to the module docstring that `current_n` should be "unique enrolled users" and recommend callers pass it explicitly, OR change the default to `df[treatment_col].nunique() * something` (still wrong in general). Leaving the default but documenting it is the pragmatic fix.

### S2. `amendments/tracker.py:124` — reaches into `store._log_path`
```python
exp_dir = self.store._log_path(experiment_id).parent  # type: ignore[attr-defined]
```
The comment admits `_log_path` is semi-public. Wave 1 already uses it inside `store.py` itself, so the contract is stable — but Wave 2 now depends on it from a sibling package. Consider promoting `_log_path` (and `_yaml_path`, `_analyses_dir`) to public `experiment_dir(experiment_id)` on `ExperimentStore` so the tracker isn't reaching into an underscored name.

### S3. `amendments/tracker.py:107` docstring is slightly stale
```python
def require_amendment_for_transition(from_state: str, to_state: str) -> bool:
    """...
    Mirrors lifecycle._BACKWARD: POWERED->DESIGNING, ANALYZING->COLLECTING,
    INTERPRETED->COLLECTING, INVALID->DESIGNING.
    """
```
The actual `_BACKWARD` map in `lifecycle.py` has `INVALID -> [ABANDONED, DESIGNING]` — two targets, not one. The function itself is correct because it delegates to `is_backward`, but the docstring list is incomplete. One-line fix.

### S4. `monitoring/srm_trend.py:98` hardcodes `threshold` default as 0.01 but `run_monitor` passes 0.0005
The function default is `threshold=0.01` (standard SRM α), but `report.py:144` passes `srm_threshold=ctx.get("srm_threshold", 0.0005)`. Two different defaults for the "same knob" — one for direct callers, one for the orchestrator. Not wrong (the orchestrator is stricter because it's running per-window with many looks), but document the discrepancy in both docstrings or pick one.

### S5. `monitoring/guardrail_health.py:93` — zero baseline fallback
```python
nim_abs = abs(nim) * abs(baseline) if baseline != 0 else abs(nim)
```
If `baseline == 0` (genuinely zero mean or zero rate), the relative NIM collapses to the absolute NIM in raw units — which may be a very different number than intended. Not wrong per se (the math can't multiply by a zero baseline), but worth raising a warning in the result dict so callers know the NIM was reinterpreted.

### S6. `errors/base.py` subclass names don't collide with builtins — verified
`ValidationError`, `DataError`, `StatsError`, `StorageError`, `LifecycleError` — none shadow a Python builtin. `AgentXPError` cleanly inherits from `Exception`. No name-collision risk.

### S7. Consistent dict-return shape with `interpretation` across Wave 2 — verified
`srm_trend`, `guardrail_health`, `sample_accumulation` all return a dict with `"interpretation"` (plain-language) and `"verdict"`. `MonitorReport.to_dict()` also includes `interpretation`. `diff_experiments` returns a list (correct for a diff), `classify_change` returns a string (correct for a classifier). No violators.

### S8. Public API clean via `__init__.py` — verified
- `agentxp/monitoring/__init__.py`: exports `MonitorReport, run_monitor, srm_trend, guardrail_health, sample_accumulation`. No leakage of `_resolve_context`, `_build_recommendations`, etc.
- `agentxp/amendments/__init__.py`: exports `Amendment, AmendmentTracker, classify_change, diff_experiments, require_amendment_for_transition`. No leakage of `_walk`, `_SENTINEL`, etc.
- `agentxp/errors/__init__.py`: exports the five subclasses + `AgentXPError` + `codes` module. Clean.
- `agentxp/validators/__init__.py`: exports `ValidationReport, validate_experiment_yaml, validate_metric_yaml`. Clean.

---

## 5. Test Quality Issues

### T1. `test_run_monitor_persists_via_store` doesn't assert payload content — `tests/test_monitoring.py:382-401`
Confirms one file was written. Does not open it and check the persisted JSON matches `report.to_dict()`. Two-line addition:
```python
payload = json.loads(analyses[0].read_text())
assert payload["status"] == report.status
assert payload["report_type"] == "monitor"
```

### T2. `test_guardrail_health_degraded_metric_blocks` uses `n_per_arm=1500` and `treatment_effect=80.0` on `scale=50.0` — borderline tight but deterministic — `tests/test_monitoring.py:178-194`
Effect size is 80/50 ≈ 1.6σ per observation. With n=1500, the z-statistic is enormous and the CI lower bound is comfortably past the 10ms NIM tolerance. Reproducibly BLOCK given the pinned seed (`_make_guardrail_df(seed=2)`). Not flaky — but a comment on why `n_per_arm=1500` was picked (enough signal to cross the 2% NIM on a 500ms baseline) would save a future reviewer the arithmetic.

### T3. Tests use `tmp_path` throughout storage fixtures — verified
`test_amendments.py:76-78` (`store` fixture uses `tmp_path / "exps"`), `test_monitoring.py:382` (`ExperimentStore(root=tmp_path)`). No pollution of `~/.agentxp`. Good pattern. Wave 1's `test_store_from_env_default_not_touched` precedent is followed.

### T4. No test for `srm_trend` when only one variant observed — `tests/test_monitoring.py`
`_make_clean_srm_df` always produces both variants. Missing: a df where the treatment arm drops out entirely mid-experiment (all rows after day 7 are control). Should produce a `[N, 0]` per-window count for later windows → `srm_check` BLOCK → expected behavior, but not tested. `_make_drift_srm_df` is close (30/70 split) but doesn't go to 100/0.

### T5. No test for `diff_experiments` with `tuple` vs `list` mismatch — `tests/test_amendments.py`
`_is_sequence` accepts both tuple and list (`diff.py:33-35`). If `before` has a `tuple` at a path and `after` has a `list` with the same values, the diff correctly recurses and reports no changes. If they differ in contents, it reports scalar changes per index. Worth one assertion to lock in.

### T6. No test for `classify_change` on a change under `data` prefix — `tests/test_amendments.py`
`_MATERIAL_PREFIXES` includes `"data"` but no test asserts `{"path": "experiment.data.source", ...}` classifies as material. One-liner.

### T7. No test for `AgentXPError` with `details` containing non-JSON-serializable objects — `tests/test_errors_and_validators.py`
`to_dict` uses `dict(self.details)` — a datetime or numpy array in details will serialize as their `str()` in `json.dumps(..., default=str)` at the call site, but if the caller uses plain `json.dumps(err.to_dict())` without `default=str`, it will raise. Either document the constraint or add `default=str` to the error envelope's own serialization helper.

### T8. `test_template_experiment_yaml_file_loads_without_crash` is a smoke test only — `tests/test_errors_and_validators.py:199-211`
Asserts the validator doesn't crash on the skeleton and findings are structured — but doesn't pin the number or content of findings. That's fine (the template is expected to evolve), but add a comment saying so: otherwise a future edit that silently empties `templates/experiment.yaml` will still pass this test.

### T9. Determinism under 3× reruns — verified
310 passed in 4.86s / 4.96s / 4.81s, identical pass counts across runs. `_make_clean_srm_df`, `_make_drift_srm_df`, `_make_guardrail_df` all use `np.random.default_rng(seed=...)` with pinned seeds. No time-of-day dependency. Clean.

---

## 6. Integration Risks

### I1. `monitoring/report.py` composes Wave 1 cleanly — verified
Scratch script: `run_monitor("exp-1", ctx, store=store)` on a 5000-row dataframe with guardrails + timestamps → returns `MonitorReport(status="GREEN", checks={...three keys}, recommendations=[...])`, persists one analysis JSON, log.jsonl appended with `analysis_saved` event. Composes with `ExperimentStore`, `srm_check` (via `srm_trend`), `welch_test` + `proportion_test` (via `guardrail_health`). No import cycles.

### I2. `amendments` ↔ `lifecycle` stays in sync via delegation — verified
`require_amendment_for_transition` delegates to `storage.lifecycle.is_backward`. If Wave 3 adds a new backward edge, the tracker automatically picks it up without code changes. Only the docstring list is stale (see S3).

### I3. `validators` depend on `storage.lifecycle.ALL_STATES` as the authoritative state name list — verified
`experiment_validator.py:25` imports `ALL_STATES` directly. Confirmed: `ALL_STATES` contains the 11 states from the PRD (`ABANDONED, ANALYZING, BLOCKED, COLLECTING, COMPLETED, DESIGNING, INTERPRETED, INVALID, POWERED, REPORTED, SHIPPED`). `test_invalid_lifecycle_state_emits_lifecycle_skip` locks it in. If Wave 3 adds a state, adding it to `ALL_STATES` automatically propagates to validation.

### I4. `errors/base.py` subclass names don't collide with builtins or Wave 1 symbols — verified
Explicitly ran `dir(agentxp.errors)` mentally: nothing shadows `ValueError`, `TypeError`, `OSError`. Wave 1 didn't have a `ValidationError` — the closest was `MetricValidationError` in `agentxp.metrics.schema`, which `metric_validator.py` wraps explicitly. No collision.

### I5. `run_monitor` store-persistence swallow is too quiet — see M5

Not a failure, a visibility gap. An agent invoking `run_monitor` with a bogus `experiment_id` gets a successful-looking `MonitorReport` back, no warning logged, no recommendation added. When the agent later tries `store.load_latest_analysis("bogus")` it will hit a different error with no trail back to the original misspelling. One-line fix: append a recommendation string if the `save_analysis` call raised.

### I6. Walkthrough imports verified against real module paths — partial
Ran `from agentxp.stats.cuped import cuped_welch_test, variance_reduction, cuped_adjust; from agentxp.monitoring import ...; from agentxp.stats.bayesian import ...; from agentxp.stats.sequential import ...; from agentxp.stats import power_proportion, power_mean, duration_estimate, power_sensitivity_table, detectable_effect; from agentxp.metrics.registry import MetricRegistry, load_all_metrics; from agentxp.metrics.schema import to_test_function, validate, MetricValidationError; from agentxp.data.csv_loader import CSVLoader; from agentxp.data.discovery import discover_schema` — **ALL imports succeed**. Every walkthrough `from agentxp` line resolves. The problem in C1 is not a missing module — the module exists and imports cleanly. The problem is that `monitoring.md`'s example code calls the functions with the **wrong signatures**. `inspect.signature` of every other walkthrough's cited function matches the docs; `monitoring.md` is the sole mismatch.

### I7. `DEMO.md` references `/experiment analyze`, `/experiment full`, `/experiment interpret`, `/experiment monitor` — verified
All four modes are declared in `.claude/skills/experiment/skill.md:3` (the description field) and `skill.md:41` (the mode dispatch line). No hallucinated modes. The output strings shown in the demo (row counts, SRM chi-square, SHIP verdicts) are illustrative, not literal — appropriate for a recording script.

### I8. `MetricDefinition` vs Wave 2 validators — already flagged in Wave 1 review (I2), still unresolved
`validate_metric_yaml` wraps `agentxp.metrics.schema.validate`, which still only knows about `proportion / mean / ratio`. Wave 2 did not add a `test_family` field to route metrics to Bayesian/CUPED/sequential tests. Not a Wave 2 regression, but a persistent gap that Wave 3 integration will trip on.

---

## 7. Coverage Gaps

- **`monitoring/report.py:59-108` `_build_recommendations`** — only the happy GREEN path and one BLOCK path are tested. No test covers the "guardrail WARNING but srm PASS and sample PASS" branch, or the all-WARNING tri-combo.
- **`monitoring/srm_trend.py:178-187` trend direction** — `trend_direction` branches `improving / stable / worsening` have no direct assertion. `test_srm_trend_mid_experiment_bug_detected` only asserts `in ("worsening", "stable")`, allowing either. Tighten.
- **`monitoring/sample_accumulation.py:83-87` `planned_duration_days` inferred from `required_n / daily_traffic`** — no test exercises the `planned_duration_days=None` code path.
- **`amendments/tracker.py:216-220` corrupt `amendments.jsonl`** — the `json.JSONDecodeError → RuntimeError` path is defined but not tested. Write `{invalid json}` to the file and assert `list_amendments` raises.
- **`amendments/tracker.py:198-206` `list_amendments` on a non-existent experiment dir** — the `FileNotFoundError` branch is defined but not tested (you'd call `list_amendments("no-such-id")` with no matching experiment dir).
- **`amendments/diff.py:40-42` path joining with `[` starting child** — tested transitively via list indexing but not directly.
- **`errors/base.py:75-84` `to_dict` with nested details dict** — single-level details dict is tested; nested isn't.
- **`validators/experiment_validator.py:265-267` `_resolve_power_block` when `power` is a list** — no test covers the "power is a list, not a dict" malformed case (gets silently treated as `None` and emits "missing power").
- **`validators/experiment_validator.py:129-131` template wrapper key unwrap** — happy path tested, but no test covers `{experiment: {...}, id: "foo"}` where both exist (the `and "id" not in data` guard).
- **`validators/metric_validator.py:43-49` raw YAML string parse** — `test_metric_validator_handles_bad_yaml_string` covers a non-parseable string but not a valid YAML string that parses to a non-dict (e.g., `"- just a list"`).

---

## 8. Positive Highlights

- **`validator.add` severity routing** (`experiment_validator.py:48-54`) — warnings go to `warnings`, errors go to `findings` and flip `ok = False`. Exactly the right decomposition for agent-facing reporting, and `all_messages()` renders both for a unified output.
- **`AmendmentTracker` breadcrumb in `log.jsonl`** (`tracker.py:174-190`) — amendments are the source of truth, but a one-line `amendment_recorded` event lands in the existing event log so `store.history()` surfaces them without the caller needing to know about the amendments module. Clean separation of "audit source" and "discovery surface."
- **`classify_change` path prefix walker with admin-leaf override** (`diff.py:157-187`) — the "top-level admin prefix" → "admin leaf inside material tree" → "material prefix" → "unknown → admin" fallback chain is readable, ordered correctly, and locks in the "metric renames are material, experiment.name is admin" nuance explicitly.
- **`AgentXPError.__str__` format** is exactly `"[CODE] message\n  hint: ..."` — machine-parseable, human-readable, and every Wave 2 test asserts against the format. This is the right primitive for an LLM-facing error envelope.
- **`codes.MESSAGES` + `codes.HINTS` template registry** with `message_for` / `hint_for` helpers that silently fall back to the template on missing placeholders. Removes a whole class of `KeyError` noise at error-raise time.
- **`_msprt`-style worst-wins aggregation** at three different layers (per-metric in guardrail_health, per-window in srm_trend, across-three in run_monitor) all use the same `PASS < WARNING < BLOCK` ordering. Consistent mental model.
- **Test determinism:** 310/310 three runs, identical timings. Every numpy RNG is seeded, no `datetime.now()` in hot paths, no filesystem pollution.
- **`guardrail_health._evaluate_metric` NI math** — uses the CI bound, not the diff, to decide violation. One of the most common mistakes in guardrail implementations and it's correct here.

---

## 9. Required Fixes List (prioritized)

1. **[BLOCKER]** Rewrite `walkthroughs/monitoring.md:62-99` to use the real `agentxp.monitoring` API. Remove the `HEALTHY/WATCH/WARN/STOP` verdict vocabulary; use `GREEN/YELLOW/RED` (with internal `PASS/WARNING/BLOCK` only in per-check sections). Fix every function signature to match: `run_monitor(experiment_id, data_loader)` with a dict context, `srm_trend(df, treatment_col, timestamp_col, window="1d", ...)`, `guardrail_health(df, treatment_col, guardrail_metrics, thresholds, ...)`, `sample_accumulation(current_n, required_n, daily_traffic, days_elapsed, ...)`. Remove the "planned contract" disclaimer at line 101.
2. **[HIGH]** Fix `run_monitor` store-error visibility (`report.py:230-237`): when `save_analysis` raises, append a recommendation string noting the persistence failed so agents can see it.
3. **[HIGH]** Special-case the `days_elapsed == 0 and current_n == 0 and daily_traffic > 0` path in `sample_accumulation` — return YELLOW "too early to tell" instead of the current silent GREEN.
4. **[MEDIUM]** Update `amendments/tracker.py:107` docstring to list the full `_BACKWARD` map (`INVALID -> [ABANDONED, DESIGNING]`, not just `INVALID -> DESIGNING`).
5. **[MEDIUM]** Promote `ExperimentStore._log_path` (and `_yaml_path`, `_analyses_dir`) to public `experiment_dir()` so `AmendmentTracker` stops reaching into underscored names.
6. **[MEDIUM]** Document the `run_monitor` default for `current_n = len(df)` caveat — or change the default behavior to require the caller pass it explicitly when the df has non-user rows.
7. **[MEDIUM]** Reconcile `srm_trend`'s `threshold=0.01` default with `run_monitor`'s `srm_threshold=0.0005` override. Pick one default and document the rationale, or document why they differ.
8. **[LOW]** Add a one-line classifier-mechanism comment at `diff.py:187` explaining that top-level `name` is caught by the "unknown top-level → administrative" fallback, not the admin-leaf list.
9. **[LOW]** Fill the coverage gaps in §7, especially the corrupt `amendments.jsonl` RuntimeError branch and the `_build_recommendations` WARNING-only combinations.
10. **[LOW]** Tighten `test_srm_trend_mid_experiment_bug_detected` to assert `trend_direction == "worsening"` (currently accepts `stable`).
11. **[LOW]** Assert persisted analysis JSON content in `test_run_monitor_persists_via_store`, not just the file's existence.
12. **[LOW]** Emit a warning in `guardrail_health._evaluate_metric` when `baseline == 0` and the relative NIM collapses to absolute.
