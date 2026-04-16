# MODES.md — Deep Spec for `/experiment` Modes

This file is the implementation reference for each of the 8 modes dispatched by `skill.md`. Each section is self-contained and specifies: **trigger**, **required inputs**, **preconditions (state)**, **step-by-step execution**, **checkpoints**, **output artifacts**, and **next-state transition**.

Mode index:
1. [`design`](#1-design)
2. [`power`](#2-power)
3. [`analyze`](#3-analyze)
4. [`interpret`](#4-interpret)
5. [`monitor`](#5-monitor)
6. [`report`](#6-report)
7. [`full`](#7-full)
8. [`status`](#8-status)

All stats calls use the top-level import path (e.g., `from openxp.stats import power_proportion`) — every function in `openxp.stats.*` is re-exported at the `openxp.stats` namespace and agents must import from there, never from submodules. All agent references use the repo-relative path (e.g., `agents/experiment-analyzer.md`).

---

## 1. `design`

### Trigger
- `/experiment design`
- "I want to design an experiment"
- "Create an experiment.yaml for X"
- "Pre-register a test for X"

### Required Inputs
- **Hypothesis** (at minimum, vague is OK — the designer agent will sharpen it).
- **Slug** (kebab-case id). If not provided, derive from hypothesis and confirm once.
- Optional: baseline data file (CSV) for metric baseline estimation, daily traffic estimate.

### Preconditions
- No existing `experiment.yaml` in the target directory, **OR** explicit `--yaml` pointing to a file in `DESIGNING` state.
- If YAML exists in a later state, refuse and point to `status` mode.

### Execution Steps

1. **Scaffold directory.** Create `experiments/<slug>/` with subdirs `working/`, `reports/`, `monitoring/`. Copy `templates/experiment.yaml` to `experiments/<slug>/experiment.yaml`. Set `status: DESIGNING`, `timeline.created: <today>`.
2. **Invoke designer agent.** Read `agents/experiment-designer.md` and execute its 7-step conversation flow:
   - Step 1: Sharpen the hypothesis (action/metric/direction/magnitude/mechanism).
   - Step 2: Define metrics (primary, secondary[], guardrail[] with NIM).
   - Step 3: Randomization unit + targeting + traffic allocation.
   - Step 4: Power calculation (via `from openxp.stats import power_proportion` / `power_mean` / `power_ratio` depending on metric type).
   - Step 5: Duration estimate via `from openxp.stats import duration_estimate` (rounds to 7-day multiple, D.27).
   - Step 6: Sensitivity table via `from openxp.stats import power_sensitivity_table`.
   - Step 7: Interaction risk / concurrent experiments check.
3. **Viability verdict.** Based on `duration_estimate` return value: VIABLE (<=28d), MARGINAL (29-56d), NOT_VIABLE (>56d).
4. **Write decision rules block** (pre-registered outcomes table) from the designer agent's step 5 output.
5. **Generate `experiment.yaml`** populated with all fields. Write `design-brief.md` summary into `experiments/<slug>/`.
6. **Checkpoint: Experiment config review (Type B).**
   - Show the populated YAML + decision rules + power summary.
   - Ask "Approve, edit, or abort?"
   - Skippable with `--just-do-it`.
7. **Checkpoint: Power viability (Type C, fires only if NOT_VIABLE).**
   - **Never skip.**
   - Present options: (a) increase MDE, (b) use more sensitive metric, (c) increase allocation, (d) accept longer timeline, (e) switch to quasi-experimental method.
   - User must choose before any YAML is finalized.

### Checkpoints
| # | Name | Type | Skippable |
|---|------|------|-----------|
| 6 | Config review | B | Yes |
| 7 | Power viability | C | **No** |

### Output Artifacts
- `experiments/<slug>/experiment.yaml` with `status: POWERED` (or `DESIGNING` if user aborted).
- `experiments/<slug>/design-brief.md` (human-readable summary).
- `experiments/<slug>/working/designer-conversation.md` (raw turn log).
- `experiments/<slug>/working/sensitivity-table.csv` (from `power_sensitivity_table`).

### Next-State Transition
`(none)` → `DESIGNING` → `POWERED`. `timeline.created` and `timeline.powered` set. Next suggested mode: `monitor` (once data starts flowing) or direct-to-`analyze` on completed data.

### Error Paths
- Missing baseline: ask user to provide or use a conservative default (e.g., baseline_rate=0.5 for proportions — widest SE, longest sample).
- User rejects all viability options: exit with `status: DESIGNING` retained, write note to `working/`.

---

## 2. `power`

### Trigger
- `/experiment power`
- "Power calc for X"
- "How many users do I need to detect a 5% lift?"

### Required Inputs
- Metric type: `proportion` | `continuous` | `ratio`.
- Baseline: `baseline_rate` (proportion), or `baseline_mean` + `baseline_std` (continuous), or numerator/denominator stats (ratio).
- MDE (relative). Default 0.05 for proportions, 0.10 for continuous if omitted.
- Daily traffic (for duration estimate).
- Optional: alpha (default 0.05), power (default 0.80), allocation (default 1.0).

### Preconditions
- Can run standalone (no experiment.yaml required) OR inline against an existing YAML in `DESIGNING` or `POWERED` state.
- If YAML present and `status == POWERED`, this is a recompute and will overwrite the power block on confirmation.

### Execution Steps

1. **Gather inputs.** If `experiment.yaml` exists, read `metrics.primary.type`, `metrics.primary.baseline`, `metrics.primary.mde`, and `power.alpha`/`power.power` from it. Else ask the user.
2. **Dispatch to the correct power function** (no agent — this is direct stats):
   - `proportion` → `from openxp.stats import power_proportion; power_proportion(baseline_rate, mde_relative, alpha=0.05, power=0.80)`
   - `continuous` → `from openxp.stats import power_mean; power_mean(baseline_mean, baseline_std, mde_relative, alpha=0.05, power=0.80)`
   - `ratio` → `from openxp.stats import power_ratio; power_ratio(baseline_num_mean, baseline_den_mean, baseline_num_std, baseline_den_std, correlation_num_den, mde_relative, alpha=0.05, power=0.80)` — pass `correlation_num_den=0.0` as a conservative default when the covariance is unknown.
3. **Duration estimate.** `from openxp.stats import duration_estimate; duration_estimate(n_required=result['total_sample_size'], daily_traffic=daily_traffic, allocation=allocation)`. Returns `{days, weeks, daily_enrollment, viable, interpretation}`. The `viable` field is one of `VIABLE` (<=28d), `MARGINAL` (29-56d), `NOT_VIABLE` (>56d) per D.27.
4. **Sensitivity table.** `from openxp.stats import power_sensitivity_table; power_sensitivity_table(baseline_rate=baseline, mde_values=[0.03, 0.05, 0.10, 0.15], daily_traffic_values=[daily_traffic, 2*daily_traffic], alpha=0.05, power=0.80)`. Save to `working/sensitivity-table.csv`. Note: `power_sensitivity_table` is currently proportion-only — for continuous/ratio metrics, generate the table manually by iterating `power_mean`/`power_ratio` over MDE values.
5. **Write `power-report.md`** with: inputs summary, sample size per group, total sample, duration, viability verdict, sensitivity table, trade-off options.
6. **Update `experiment.yaml`** power block: `baseline_rate` or `baseline_mean`/`baseline_std`, `sample_size_per_group`, `total_sample_size`, `duration_days`, `viable`. Set `timeline.powered: <today>`. Transition `status: DESIGNING -> POWERED` (only if currently DESIGNING).
7. **Checkpoint: Power viability (Type C).**
   - **Never skip.**
   - If `viable == "NOT_VIABLE"`: hard stop. Present the 5 options (larger MDE, more traffic, different metric, longer timeline, quasi-experimental). User chooses → re-run power with new params, or back-transition `POWERED -> DESIGNING`.
   - If `viable == "MARGINAL"`: surface warning but continue.
   - If `viable == "VIABLE"`: proceed.

### Checkpoints
| # | Name | Type | Skippable |
|---|------|------|-----------|
| 7 | Power viability | C | **No** |

### Output Artifacts
- `experiments/<slug>/power-report.md`
- `experiments/<slug>/working/sensitivity-table.csv`
- Updated `experiments/<slug>/experiment.yaml` (power block, status, timeline.powered)

### Next-State Transition
`DESIGNING -> POWERED` (forward) or `POWERED -> DESIGNING` (backward redesign per Appendix B). Next suggested mode: user starts experiment externally, then `monitor` or `analyze`.

### Error Paths
- Missing baseline_std for continuous: ask or refuse (cannot compute).
- Ratio metric without covariance: warn user that assuming `correlation_num_den=0.0` is conservative and may overestimate duration.

---

## 3. `analyze`

### Trigger
- `/experiment analyze <data-file>`
- "Analyze this A/B test"
- "Did the experiment work?"

### Required Inputs
- **Data file**: CSV / Parquet / DuckDB table. Must contain treatment assignment and outcome columns.
- **experiment.yaml** (optional but strongly recommended). If missing → cold-start path (skill.md §Cold-Start Path).

### Preconditions
- `status in {COLLECTING, ANALYZING}` (re-run allowed). If `DESIGNING` or `POWERED`, error: "No data yet — run the experiment first."

### Execution Steps

1. **Data Discovery Protocol.** Read first 5 rows + dtypes + shape. Auto-detect treatment column, outcome columns, segment columns, timestamp. Ask only when ambiguous.
2. **Data preparation.** Call `from openxp.stats import prepare_experiment_data; prepare_experiment_data(df, treatment_col=<col>, metric_cols=[<...>], segment_cols=[<...>], winsorize_spec={"revenue": (0.0, 0.99)})`. Returns `{cleaned_df, schema, treatment_col, metric_cols, segment_cols, n_rows_input, n_rows_output, n_rows_dropped, reasons, winsorized, warnings, interpretation}`. If drop rate exceeds 5% or the warnings list is populated, surface them; if the schema cannot resolve a treatment column it raises — catch and escalate to **INVALID** with specific diagnosis (skip to interpret).
3. **Checkpoint: Min-sample guard (Type C, D.15).**
   - Compare observed n to `experiment.yaml` `power.sample_size_per_group`.
   - If `n < 50%` of plan → **hard stop**. Message: "Analysis unreliable — only X% of required observations. Continue collecting or accept the caveat explicitly."
   - If `50% <= n < 100%` → Type B warning with MDE at current sample via `detectable_effect`.
   - **Never skip the 50% gate.**
4. **SRM gate (Type C).** Call `from openxp.stats import srm_check; srm_check(observed_counts=[n_c, n_t], expected_ratios=[0.5, 0.5], threshold=0.0005)`. The library default for `threshold` is `0.01`; the orchestrator explicitly passes `threshold=0.0005` (Microsoft's production default, D.14).
   - Verdict `PASS` (p > 0.05): continue.
   - Verdict `WARNING` (`threshold` < p <= 0.05): surface warning, continue with caveat.
   - Verdict `BLOCK` (p <= `threshold`): **halt**. Run `from openxp.stats import srm_diagnose; srm_diagnose(assignments_df, group_col="variant", segments=[<...>])`. Write INVALID verdict to `analysis_results.json`. Transition to `interpret` mode which will finalize INVALID, or offer the SRM recovery path (`ANALYZING -> COLLECTING` if root cause is fixable).
5. **Invoke experiment-analyzer agent.** Read `agents/experiment-analyzer.md`. The agent walks the 8-question framework:
   - Q1: Setup validation (SRM already done above, report here).
   - Q2: Primary metric test. Dispatch on metric type:
     - proportion → `from openxp.stats import proportion_test; proportion_test(c_success, c_n, t_success, t_n, alpha=0.05)`. If expected cell count < 5, fall back to `from openxp.stats import fishers_exact_test`.
     - continuous → `from openxp.stats import welch_test; welch_test(control, treatment, alpha=0.05)`. Winsorize first via `winsorize_spec` in prep if skewness > 3.
     - ratio → `from openxp.stats import ratio_metric_test; ratio_metric_test(num_c, den_c, num_t, den_t, alpha=0.05)`. Also call `denominator_srm` (D.23).
   - Q3: Effect size. `from openxp.stats import cohens_d; cohens_d(control, treatment)` (continuous, returns `{d, magnitude, interpretation}`); `from openxp.stats import cohens_h; cohens_h(p_control, p_treatment)` (proportion, returns `{h, abs_h, magnitude, p_control, p_treatment, interpretation}` — point estimate only, no CI); always `from openxp.stats import relative_lift; relative_lift(control_mean, treatment_mean)`. MDE at observed n via `detectable_effect`.
   - Q4: Segment analysis. Run primary test within each detected segment (n >= 100 per group required to be reliable).
   - Q5: Temporal effects (novelty / maturation / day-of-week).
   - Q6: Business impact projection (CI lower/point/upper × users/year).
   - Q7: Apply pre-registered decision rules (or cold-start defaults).
   - Q8: Follow-up experiment suggestions.
6. **Guardrail tests.** For each guardrail metric: `from openxp.stats import guardrail_test; guardrail_test(control, treatment, metric_type="mean", nim_relative=0.02, alpha=0.05, invert=False)`. Pass `metric_type="proportion"` with `(success, n)` tuples for binary guardrails; pass `invert=True` when lower-is-better (latency, error rate). The test is implicitly one-sided non-inferiority — there is no `alternative=` kwarg. Verdicts: `PASS` / `WARNING` / `BLOCK`. For ratio-metric guardrails, also call `from openxp.stats import denominator_srm; denominator_srm(num_c, den_c, num_t, den_t, expected_ratio=1.0, threshold=0.05)` — all four sums are required even though the test only uses the denominators.
7. **Checkpoint: Guardrail violation (Type C).**
   - **Never skip.**
   - If any `guardrail_test` returns verdict `BLOCK` (or `WARNING` on a hard-safety metric): surface with point estimate, oriented effect, NIM, worst-case one-sided CI bound, and ask user to acknowledge before proceeding.
8. **Multiple comparisons.** Secondary metrics only: `from openxp.stats import adjust_pvalues; adjust_pvalues(secondary_pvalues, method="holm", alpha=0.05)`. Primary never corrected. Guardrails never corrected.
9. **Suspicious uplift check.** For each metric, if `abs(relative_lift) > 0.20`, append Twyman's Law warning to `analysis_results.json`.
10. **Write artifacts.**
    - `analysis_results.json`: structured machine-readable output (SRM verdict, per-metric results with `computation_trace`, guardrail verdicts, segment results, business impact).
    - `reports/analysis.md`: human-readable 8-question report.
    - Update `experiment.yaml` results block: `srm_verdict`, `primary_significant`, `primary_lift`, `primary_p_value`, `guardrail_violations`, `analysis_file`. Set `status: ANALYZING`, `timeline.analyzed: <today>`.
11. **Checkpoint: Analyzer draft review (Type B).** Show the analysis summary. Skippable with `--just-do-it`.

> **Design decision (Q7):** `welch_test` is permanently two-sided. One-sided non-inferiority for guardrail metrics routes through `guardrail_test(metric_type="mean", nim_relative=..., invert=...)`. This is intentional — keeping `welch_test` simple and routing specialized use cases to specialized functions.

### Checkpoints
| # | Name | Type | Skippable |
|---|------|------|-----------|
| 3 | Min-sample guard | C | **No** |
| 4 | SRM gate | C | **No** |
| 7 | Guardrail violation | C | **No** |
| 11 | Draft review | B | Yes |

### Output Artifacts
- `experiments/<slug>/analysis_results.json`
- `experiments/<slug>/reports/analysis.md`
- `experiments/<slug>/working/analyzer-trace.md` (per-call computation traces, D.9)
- Updated `experiments/<slug>/experiment.yaml`

### Next-State Transition
`COLLECTING -> ANALYZING`. On SRM BLOCK with fixable root cause: `ANALYZING -> COLLECTING` (backward, with salt change). Next suggested mode: `interpret`.

### Error Paths
- Data quality failure in prep → write INVALID directly to `analysis_results.json` and skip to interpret.
- Missing primary metric column → ask user (Data Discovery Protocol fallback).
- Stats function error → preserve trace, halt, report exact inputs.

---

## 4. `interpret`

### Trigger
- `/experiment interpret`
- "Should we ship?"
- "What does this mean?"

### Required Inputs
- `analysis_results.json` from the previous analyze run (must exist).
- `experiment.yaml` (for pre-registered decision rules, practical significance threshold, alert thresholds).

### Preconditions
- `status == ANALYZING` (analyzer must have completed).
- `analysis_results.json` exists and has valid `computation_trace` entries (D.9 validation).

### Execution Steps

1. **Pre-check: Alert threshold scan.** For each guardrail with `alert_threshold` defined, check if treatment absolute value exceeds it. If yes → **INVALID** (hard safety ceiling, bypasses entire interpretation tree). Write result, jump to step 5.
2. **Invoke experiment-interpreter agent.** Read `agents/experiment-interpreter.md`. The agent walks PRD **Appendix A Result Interpretation Tree**:
   - **Branch 1: INVALID** — SRM BLOCK or data quality failure. Terminate here.
   - **Branch 2: SHIP** — Primary significant positive AND above practical significance (point estimate >= `minimum_practical_significance`) AND all guardrails clean (PASS).
   - **Branch 3: INVESTIGATE** — Primary significant positive AND a guardrail is degraded beyond NIM OR a segment reversal is detected. Agent must quantify trade-off numerically: `primary_gain_$ - guardrail_cost_$` using `relative_lift` × affected population.
   - **Branch 4: ABORT** — Primary significant negative, OR severe guardrail violation with no compensating primary gain.
   - **Branch 5a: LEARN (powered)** — Null primary + achieved MDE <= planned MDE (adequately powered). The feature doesn't move the metric.
   - **Branch 5b: LEARN (underpowered)** — Null primary + achieved MDE > planned MDE. Call `from openxp.stats import extension_estimate; extension_estimate(current_n=n_per_group, current_mde_observed=observed_effect, required_power=0.80, baseline_variance=var, daily_traffic=daily_traffic_total, alpha=0.05)` and report: `required_n_per_group`, `additional_n_needed`, `additional_days`, `total_duration`, and whether `feasible` is True (within the 56-day threshold).
   - **Branch 5c: LEARN (practically insignificant)** — Significant positive BUT point estimate < `minimum_practical_significance`. Real but too small to matter.
3. **Powered-as-spectrum reporting (D.26).** Never binary. Always report: "At N=X, you can detect effects >= Y%. Smaller effects cannot be ruled out." Use `from openxp.stats import detectable_effect; detectable_effect(n_per_group, baseline_rate=<r>, alpha=0.05, power=0.80)` (proportion) or `detectable_effect(n_per_group, baseline_std=<s>, alpha=0.05, power=0.80)` (continuous).
4. **Suspicious uplift caveat.** If analyzer flagged any metric with `abs(relative_lift) > suspicious_lift_threshold`, append the Twyman's Law note to the interpretation. Does not change classification — adds caveat only.
5. **Write `interpretation.md`.** Format per agent spec: Classification, Evidence Summary, Decision, Reasoning (reference specific branch of the tree), Conditions (monitoring plan for SHIP/INVESTIGATE), Follow-up.
6. **Update `experiment.yaml`.** Set `results.ewl_classification` to one of `SHIP | INVESTIGATE | ABORT | LEARN | INVALID`. Set `status: INTERPRETED`, `timeline.decided: <today>`.
7. **Checkpoint: Ship decision (Type C).**
   - **Never skip.** Never auto-ship.
   - Present recommendation + rationale + conditions + confidence level.
   - Require explicit user confirmation before the YAML is written as `INTERPRETED`.
   - If user disputes classification, offer a single re-run with the specific node of the tree the user contests.

### Checkpoints
| # | Name | Type | Skippable |
|---|------|------|-----------|
| 7 | Ship decision | C | **No** |

### Output Artifacts
- `experiments/<slug>/interpretation.md`
- `experiments/<slug>/working/interpretation-trace.md` (tree walk log)
- Updated `experiments/<slug>/experiment.yaml` (results.ewl_classification, status, timeline.decided)

### Next-State Transition
`ANALYZING -> INTERPRETED`. Backward: `INTERPRETED -> COLLECTING` if user chooses to extend (LEARN underpowered path). Terminal INVALID stays INVALID unless user explicitly restarts with new slug. Next suggested mode: `report`.

### Error Paths
- Missing `analysis_results.json` → refuse: "Run /experiment analyze first."
- Invalid `computation_trace` → refuse and surface which stat call has no trace.
- Mixed results that don't fit a branch → apply PRD §5.12 Mixed Results Framework (Scenarios A/B/C/D) and classify conservatively (prefer LEARN over SHIP on ambiguity).

---

## 5. `monitor`

### Trigger
- `/experiment monitor <data-file>`
- "How's my running experiment?"
- "Check SRM"
- "Daily health check"

### Required Inputs
- **Data file** with current (not final) experiment data. Timestamps strongly recommended for daily trending.
- **experiment.yaml** (optional). If present, uses planned sample size, guardrail NIMs, ramp plan.
- Optional: previous monitoring reports in `experiments/<slug>/monitoring/` for trend comparison.

### Preconditions
- `status == COLLECTING` (typical). Also allowed for `ANALYZING` (sanity re-check).

### Execution Steps

1. **Data Discovery Protocol.** Same as analyze. Re-read the data file fresh — the monitor does not maintain its own pipeline.
2. **Invoke experiment-monitor agent.** Read `agents/experiment-monitor.md`. The agent runs 4 checks, each producing a traffic-light status:
   - **Check 1: SRM trending.** `from openxp.stats import srm_check; srm_check(observed_counts=[n_c, n_t], expected_ratios=[0.5, 0.5], threshold=0.0005)` + per-day `srm_check` if timestamps available. Three-tier (D.14): GREEN (p > 0.05), YELLOW (0.0005 < p <= 0.05), RED (p <= 0.0005). Orchestrator always passes `threshold=0.0005` explicitly; the library default is 0.01.
   - **Check 2: Guardrail status.** For each guardrail: `from openxp.stats import guardrail_test; guardrail_test(control, treatment, metric_type="mean", nim_relative=<nim>, alpha=0.05, invert=<lower_is_better>)`. Map verdicts: RED = `BLOCK`, YELLOW = `WARNING`, GREEN = `PASS`. Also check `emergency_stop` rule from YAML (>15% relative degradation of the point estimate).
   - **Check 3: Sample accumulation.** Current n vs planned. GREEN (on track / ahead), YELLOW (>20% behind), RED (>50% behind). Compute projected completion date from daily enrollment rate.
   - **Check 4: Detectable effect at current sample.** `from openxp.stats import detectable_effect; detectable_effect(n_per_group, baseline_rate=<r>, alpha=0.05, power=0.80)` (proportion) or `detectable_effect(n_per_group, baseline_std=<s>, alpha=0.05, power=0.80)` (continuous). Shows what MDE is currently detectable vs planned MDE.
3. **Data quality checks (Gap 5.3).** Row counts, null rates, data freshness, volume anomalies. Flag if today's data didn't arrive or volume dropped >30%.
4. **Ramp decisions (Gap 5.5).** If `ramp_plan` exists in YAML and current traffic % is near a milestone: ask "SRM clean, guardrails clean. Safe to ramp from X% to Y%?"
5. **Write monitoring dashboard.** `experiments/<slug>/monitoring/<YYYY-MM-DD>.md`. Append entry to `monitoring/history.yaml` with date, per-check status, overall status.
6. **Checkpoint: Guardrail RED / SRM RED (Type C).**
   - **Never skip.**
   - Any RED → hard-stop block. Cannot continue without user acknowledgment.
   - SRM RED → offer immediate `from openxp.stats import srm_diagnose; srm_diagnose(assignments_df, group_col="variant", segments=[<...>])` + SRM recovery path (ANALYZING -> COLLECTING with salt change if fixable).
   - Guardrail RED → offer emergency halt (recommend stopping the experiment now).
7. **Trend analysis** (if >=2 prior reports exist in `monitoring/history.yaml`): SRM p-value trend (stable/improving/worsening), guardrail trend, enrollment rate trend.

### Checkpoints
| # | Name | Type | Skippable |
|---|------|------|-----------|
| 6 | SRM RED | C | **No** |
| 6 | Guardrail RED | C | **No** |

### Output Artifacts
- `experiments/<slug>/monitoring/<YYYY-MM-DD>.md` (traffic-light dashboard)
- `experiments/<slug>/monitoring/history.yaml` (appended)
- `experiments/<slug>/experiment.yaml` unchanged on normal run; may transition to `ABANDONED` on emergency halt.

### Next-State Transition
`COLLECTING -> COLLECTING` (normal). Emergency halt: `COLLECTING -> ABANDONED` (user-chosen) or `COLLECTING -> ANALYZING` (proceed to analysis despite warning). Next suggested mode: same mode tomorrow, or `analyze` when sample complete.

### Error Paths
- Data freshness failure (today's data missing) → YELLOW, suggest checking pipeline.
- Ambiguous treatment column → fall back to Data Discovery Protocol user prompt.
- No YAML → run checks with generic thresholds but cannot evaluate against plan or NIM.

---

## 6. `report`

### Trigger
- `/experiment report [--audience <a>]`
- "Generate the readout"
- "Write the stakeholder report"

### Required Inputs
- `analysis_results.json` (from analyze).
- `interpretation.md` + `results.ewl_classification` from YAML (from interpret).
- Audience: `executive | technical | cross-functional` (default `cross-functional`).
- Optional format: `markdown | slack | email` (Gap 10.4).

### Preconditions
- `status == INTERPRETED`. Must have passed both analyze and interpret successfully.

### Execution Steps

1. **Load inputs.** Read `analysis_results.json`, `interpretation.md`, `experiment.yaml`. Verify `results.ewl_classification` is set to one of the 5 canonical outcomes.
2. **Invoke experiment-readout agent.** Read `agents/experiment-readout.md`. The agent reads pre-computed values only — it does not call stats functions. Produces a 6-section report:
   - Section 1: Executive Summary (decision + confidence + 2-3 sentence narrative).
   - Section 2: Key Results table (Control / Treatment / Lift / p-value / Significant? for primary, secondary, guardrail).
   - Section 3: Business Impact (Conservative / Best / Optimistic annual $ from CI bounds).
   - Section 4: Segment Highlights (only if notable — reversals, significantly-different effects, segment-specific guardrail violations).
   - Section 5: Decision & Next Steps (rationale, action items, monitoring plan if SHIP).
   - Section 6: Appendix (methodology, full results, power assessment, SRM check).
3. **Audience adaptation.**
   - `executive`: lead with decision, 1-paragraph summary, $ impact, confidence level. **No p-values in body.** Stats details go to appendix.
   - `technical`: full detail, effect sizes, CIs, p-values, segment tables, power assessment, methodology notes, code snippets for reproducibility.
   - `cross-functional` (default): decision + 1-sentence rationale, key metrics table, segment highlights, business impact, next steps, stats in collapsible section.
4. **Site-wide impact projection (Gap 6.6).** "If rolled out to all [total_population] users, this represents ~X additional conversions/month (~$Y revenue)." Simple arithmetic, not a stats call.
5. **Amendments note.** If `amendments.yaml` exists with non-empty entries, include: "This experiment was amended on [date]: [change] ([reason])."
6. **Write artifact.** `experiments/<slug>/reports/readout-<audience>.md`. For non-markdown formats, also write `readout-<audience>.slack.txt` or `readout-<audience>.email.html`.
7. **Checkpoint: Readout draft review (Type B).** Show the report. Ask "Approve, request edits, or change audience?" Skippable with `--just-do-it`.
8. **Update `experiment.yaml`.** Set `status: REPORTED`, `timeline.reported: <today>`. Store `results.report_file` path.

### Checkpoints
| # | Name | Type | Skippable |
|---|------|------|-----------|
| 7 | Readout draft review | B | Yes |

### Output Artifacts
- `experiments/<slug>/reports/readout-<audience>.md` (and optional format variants).
- Updated `experiments/<slug>/experiment.yaml` (status: REPORTED).

### Next-State Transition
`INTERPRETED -> REPORTED`. Next (external to OpenXP): user executes ship decision in flag system, transitions to `SHIPPED`, then `COMPLETED` after post-ship monitoring window.

### Error Paths
- Missing classification → refuse: "Run /experiment interpret first."
- Numeric inconsistencies (analysis vs interpretation) → refuse and surface the mismatch.

---

## 7. `full`

### Trigger
- `/experiment full <data-file>`
- "Run the whole pipeline"
- "End-to-end analysis"

### Required Inputs
- Mode-dependent. For a green-field full run: hypothesis + data file (or promise of data later).
- For a post-collection full run: `experiment.yaml` in `COLLECTING` state + data file.

### Preconditions
- Flexible. Accepts any starting state and runs remaining stages.

### Execution Steps

Runs the modes in sequence, honoring all checkpoints. Each step's artifacts become the inputs to the next.

1. **`design`** (if no experiment.yaml) — produces experiment.yaml in `POWERED` state.
   - Fires: config review (B, skippable), power viability (C, never skip).
2. **`power`** (if YAML exists in `DESIGNING`) — completes power calc.
   - Fires: power viability (C).
3. **Pause for data collection.** If YAML transitions to `POWERED` and no data file is present, `full` exits with instructions: "Design + power complete. Start the experiment in your flag system, then re-run `/experiment full <data>` when data is ready."
4. **`analyze`** — runs the 8-question analyzer on the data.
   - Fires: min-sample guard (C), SRM gate (C), guardrail violation (C), draft review (B, skippable).
5. **`interpret`** — walks the Result Interpretation Tree.
   - Fires: ship decision (C, never skip).
6. **`report`** — produces the readout (default audience: cross-functional; override with `--audience`).
   - Fires: draft review (B, skippable).

### Checkpoints
All Type C gates from the 5 modes fire in order. Type B gates are all skippable via `--just-do-it`. If **any** Type C fires a hard stop, `full` halts — the user must resolve before continuing. `full` can be re-invoked and will pick up from the current `status`.

### Output Artifacts
Union of artifacts from design + power + analyze + interpret + report (see individual mode sections).

### Next-State Transition
Any valid starting state → `REPORTED`. Intermediate states updated as each mode completes.

### Error Paths
- If the pipeline halts mid-run, the last-completed state is preserved in `experiment.yaml`. A subsequent `/experiment full` or `/experiment <mode>` picks up from there.
- `--dry-run` prints the full planned execution (all modes, agents, stats calls, artifacts, checkpoints) without invoking anything.

---

## 8. `status`

### Trigger
- `/experiment status`
- "What state is this in?"
- "Show lifecycle status"

### Required Inputs
- `experiment.yaml` path (default: walk up from cwd).

### Preconditions
- None. Read-only operation.

### Execution Steps

1. **Read `experiment.yaml`.** No agent needed. No stats calls.
2. **Display lifecycle state.** Show:
   - `experiment.id`, `experiment.name`, `experiment.status`.
   - Current state position on the Appendix B state diagram.
   - `timeline.*` fields populated so far.
   - `power` block summary (sample size, duration, viability).
   - `results.*` fields if present (srm_verdict, primary_significant, primary_lift, guardrail_violations, ewl_classification).
   - Any blockers or pending checkpoints.
3. **Suggest next mode.** Based on current state:
   | State | Suggested next mode |
   |-------|---------------------|
   | `DESIGNING` | `/experiment power` (if not done) or continue `/experiment design` |
   | `POWERED` | Start experiment externally, then `/experiment monitor <data>` |
   | `COLLECTING` | `/experiment monitor <data>` daily, then `/experiment analyze <data>` when complete |
   | `ANALYZING` | `/experiment interpret` |
   | `INTERPRETED` | `/experiment report` |
   | `REPORTED` | Ship externally, then archive |
   | `INVALID` | Diagnose root cause; either restart with new slug or `ABANDONED` |
   | `ABANDONED` / `COMPLETED` | Terminal — no next action |
4. **Validate state.** If `status` is inconsistent with populated fields (e.g., `status: POWERED` but `power.sample_size_per_group == null`), surface the inconsistency.

### Checkpoints
None. Pure read.

### Output Artifacts
None. Stdout only.

### Next-State Transition
None. Read-only.

### Error Paths
- YAML missing → "No experiment.yaml found at <cwd>. Run `/experiment design` to create one."
- YAML corrupted → print parse error + line number, suggest `git restore` or recreate.

---

## Cross-Cutting Rules (apply to all modes)

1. **Every stats call logs a `computation_trace`** (D.9). Before any mode advances state, skill.md validates that every result has a trace. Missing trace → refuse.
2. **Agents never re-implement math.** If an agent is tempted to write `import scipy.stats` directly, stop it. Use `from openxp.stats import ...` imports only (top-level namespace, not submodules).
3. **Data-agnostic.** No mode assumes column names. Every data-touching mode runs the Data Discovery Protocol.
4. **State transitions are atomic.** Either the YAML is fully updated (status + timeline + results) or not at all. Partial writes go to `working/` and are discarded on failure.
5. **Working dir is disposable.** Everything in `experiments/<slug>/working/` is intermediate and gitignored. Artifacts promoted to `experiments/<slug>/` (or `reports/`, `monitoring/`) are tracked.
6. **Type C never skips.** Ever. `--just-do-it` affects Type B only.
