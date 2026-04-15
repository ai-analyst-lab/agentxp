# Skill: /experiment — OpenXP Experimentation Platform

## Purpose
Multi-mode skill for the full experiment lifecycle — from design through analysis to ship/no-ship decision. Orchestrates experiment agents and calls coded statistical functions from `openxp.stats` instead of improvising Python.

## When to Use
Invoke as `/experiment [mode]` or trigger on experiment-related intents:
- "I want to run an experiment"
- "Analyze this A/B test"
- "Did this experiment work?"
- "What's the power for this test?"
- "How many users do I need?"

## Modes

### `/experiment design`
**Purpose:** Create a pre-registered experiment config.
**Agent:** `agents/experiment-designer.md`
**Flow:**
1. Interactive conversation: hypothesis → metrics → guardrails
2. Power calculation using `openxp.stats.power`
3. Output: `experiment.yaml` (from `templates/experiment.yaml`)
**Checkpoint:** Config review (Type B — skippable with --just-do-it)

### `/experiment power`
**Purpose:** Power analysis + duration estimation.
**Flow:**
1. Get metric type, baseline, MDE from user or experiment.yaml
2. Call the right power function:
   ```python
   from openxp.stats import power_proportion, power_mean, duration_estimate, power_sensitivity_table

   # Proportion metric
   result = power_proportion(baseline_rate, mde_relative)

   # Continuous metric
   result = power_mean(baseline_mean, baseline_std, mde_relative)

   # Duration
   dur = duration_estimate(result["total_sample_size"], daily_traffic)

   # Sensitivity table
   table = power_sensitivity_table(baseline_rate, [0.03, 0.05, 0.10], [traffic])
   ```
3. Update experiment.yaml with computed values (sample_size, duration, viable)
**Checkpoint:** Power viability (Type C — NOT_VIABLE fires mandatory checkpoint)

### `/experiment analyze [file]`
**Purpose:** Run statistical tests on experiment data.
**Agent:** `agents/experiment-analyzer.md`
**Flow:**
1. Load data, discover schema (auto-detect treatment/metric/segment columns)
2. **SRM Gate (mandatory first step):**
   ```python
   from openxp.stats import srm_check
   result = srm_check(observed_counts, expected_ratios)
   if result["verdict"] == "BLOCK":
       # HALT — do not proceed to treatment effect analysis
   ```
3. Treatment effect analysis:
   ```python
   from openxp.stats import welch_test, proportion_test, ratio_metric_test
   # Select based on metric type
   ```
4. Effect size: `cohens_d(control, treatment)`
5. Multiple comparisons: `adjust_pvalues(all_p_values, method="holm")`
6. Guardrail checks
7. Segment analysis
8. Output: analysis report
**Checkpoint:** SRM gate (Type C — BLOCK halts everything)

### `/experiment interpret`
**Purpose:** Walk the Result Interpretation Tree and classify the outcome.
**Agent:** `agents/experiment-interpreter.md`
**Flow:**
1. Read analysis results
2. Walk the Result Interpretation Tree:
   - Positive + clean guardrails → **SHIP**
   - Positive + degraded guardrails → **INVESTIGATE**
   - Null (powered) → **LEARN** (feature doesn't work)
   - Null (underpowered) → **LEARN** (extend or redesign)
   - Negative → **ABORT**
   - SRM → **INVALID**
3. Output: classification + rationale + next steps
**Checkpoint:** Ship decision (Type C — always fires)

### `/experiment monitor [file]`
**Purpose:** SRM check + guardrail status + sample tracking during a running experiment.
**Agent:** `agents/experiment-monitor.md`
**Flow:**
1. Load current data
2. `srm_check()` with p < 0.0005 threshold (Microsoft standard)
3. Guardrail tests
4. Sample accumulation vs plan
5. Output: Traffic light dashboard (GREEN / YELLOW / RED)
**Checkpoint:** RED guardrail (Type C — triggers halt)

### `/experiment report [audience]`
**Purpose:** Generate stakeholder-ready report.
**Agent:** `agents/experiment-readout.md`
**Flow:**
1. Read analysis + interpretation results
2. Adapt to audience: `executive`, `technical`, or `cross-functional` (default)
3. Output: formatted markdown report

### `/experiment status`
**Purpose:** Show experiment lifecycle state.
**Flow:**
1. Read experiment.yaml
2. Display: current status, key metrics, timeline, any blockers
3. No agent needed — direct YAML read and format

### `/experiment full [file]`
**Purpose:** End-to-end: design → power → analyze → interpret → report.
**Flow:** Runs design, power, analyze, interpret, report in sequence.
**Checkpoints:** All Type C checkpoints fire. Type B skipped with --just-do-it.

## Data Discovery

OpenXP is data-agnostic. When data is provided:
1. Read first 5 rows + dtypes
2. Auto-detect: treatment column, outcome columns, segment columns, timestamps
3. If ambiguous, ask the user
4. **Never assume column names**

## Stats Function Reference

| Function | Module | Use For |
|----------|--------|---------|
| `welch_test()` | `openxp.stats.ab_tests` | Continuous metric A/B test |
| `proportion_test()` | `openxp.stats.ab_tests` | Binary metric A/B test |
| `ratio_metric_test()` | `openxp.stats.ab_tests` | Ratio metric (delta method) |
| `winsorize()` | `openxp.stats.ab_tests` | Outlier-robust pre-processing |
| `power_proportion()` | `openxp.stats.power` | Sample size for proportions |
| `power_mean()` | `openxp.stats.power` | Sample size for means |
| `detectable_effect()` | `openxp.stats.power` | MDE from fixed sample |
| `duration_estimate()` | `openxp.stats.power` | Timeline planning |
| `power_sensitivity_table()` | `openxp.stats.power` | MDE × traffic trade-offs |
| `srm_check()` | `openxp.stats.srm` | Sample ratio mismatch |
| `srm_diagnose()` | `openxp.stats.srm` | Segmented SRM root cause |
| `cohens_d()` | `openxp.stats.effect_size` | Standardized effect size |
| `relative_lift()` | `openxp.stats.effect_size` | Percentage change |
| `adjust_pvalues()` | `openxp.stats.corrections` | Multiple comparison correction |
