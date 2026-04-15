---
name: experiment
description: Multi-mode orchestrator for the full A/B experiment lifecycle — design, power, analyze, interpret, monitor, report. Routes to the 5 OpenXP agents and calls `openxp.stats` functions instead of improvising statistics. Invoke as `/experiment <mode> [args]`. Modes — design | power | analyze | interpret | monitor | report | full | status.
---

# Skill: `/experiment` — OpenXP Multi-Mode Orchestrator

## Purpose

One skill, eight modes. The entire OpenXP product surface. This file is the **dispatcher** — it picks the mode, validates required inputs, enforces checkpoints, advances `experiment.yaml` state, and hands off to the correct agent + stats functions. Deep per-mode implementation detail lives in `MODES.md` alongside this file.

**Non-negotiable rules (inherited from `CLAUDE.md`):**
1. Never improvise statistics — every test must call a function from `openxp.stats.*`.
2. Never assume column names — always run the Data Discovery Protocol.
3. Never skip Type C checkpoints (power viability, SRM gate, guardrail violation, ship decision).
4. Never mutate files outside the current experiment directory.
5. Every state transition is written to `experiment.yaml` `status` field and `timeline` block.
6. Always import stats functions from the top-level `openxp.stats` namespace — never from submodules (`from openxp.stats import welch_test`, not `from openxp.stats.ab_tests import welch_test`).
7. Stats functions return a `computation_trace` dict by default (the D.9 audit trail). The `interpret` mode validates this field — do not disable trace via `openxp.stats.set_trace(False)` unless the user explicitly asks.

## When to Use

Invoke as `/experiment <mode> [args]` or on any of these intents:

| Intent | Mode |
|--------|------|
| "I want to run an experiment" / "design a test" | `design` |
| "How many users do I need?" / "power calc" / "sample size" | `power` |
| "Analyze this A/B test" / "did the experiment work?" | `analyze` |
| "Should we ship?" / "what does this result mean?" | `interpret` |
| "Is my running experiment healthy?" / "check SRM" | `monitor` |
| "Write the readout" / "give me the stakeholder report" | `report` |
| "Run the whole pipeline" / "end-to-end" | `full` |
| "What state is this in?" / "show experiment status" | `status` |

If the mode is ambiguous, ask once: "Do you want to (a) design a new experiment, (b) analyze existing data, or (c) check the status of an in-flight experiment?"

## Arguments

```
/experiment <mode> [positional] [--flags]

Modes:       design | power | analyze | interpret | monitor | report | full | status
Positional:  data file (for analyze/monitor/full) or experiment slug (for others)
Flags:
  --yaml <path>        Explicit path to experiment.yaml (default: ./experiment.yaml)
  --audience <a>       report audience: executive | technical | cross-functional (default: cross-functional)
  --just-do-it         Skip Type B checkpoints (config review, draft review). Type C still fire.
  --sequential         Use always-valid confidence sequences (analyze mode, v0.5+)
  --dry-run            Show plan without executing agents/code
```

## Mode Matrix (dispatch summary)

| Mode | Agent | Stats Calls | Type B Checkpoints | Type C Checkpoints | State Before → After |
|------|-------|-------------|--------------------|--------------------|----------------------|
| `design` | `agents/experiment-designer.md` | `openxp.stats.power.*` | Config review | Power viability (if NOT_VIABLE) | (none) → `DESIGNING` → `POWERED` |
| `power` | (inline, no agent) | `openxp.stats.power.*` | — | Power viability | `DESIGNING` → `POWERED` |
| `analyze` | `agents/experiment-analyzer.md` | `srm_check`, `srm_diagnose`, `welch_test`, `proportion_test`, `fishers_exact_test`, `ratio_metric_test`, `guardrail_test`, `cohens_d`, `cohens_h`, `relative_lift`, `detectable_effect`, `adjust_pvalues`, `winsorize`, `denominator_srm` | Draft review | **SRM gate**, **Guardrail violation**, **Min-sample guard** | `COLLECTING` → `ANALYZING` |
| `interpret` | `agents/experiment-interpreter.md` | `detectable_effect`, `extension_estimate`, `relative_lift` | — | **Ship decision** | `ANALYZING` → `INTERPRETED` |
| `monitor` | `agents/experiment-monitor.md` | `srm_check`, `srm_diagnose`, `guardrail_test`, `detectable_effect`, `denominator_srm` | — | **Guardrail RED**, **SRM RED** | `COLLECTING` → `COLLECTING` (or emergency halt) |
| `report` | `agents/experiment-readout.md` | (none — reads `analysis_results.json`) | Draft review | — | `INTERPRETED` → `REPORTED` |
| `full` | all 5 in sequence | all of the above | Config review, draft review | All Type C gates | (none) → `REPORTED` |
| `status` | (inline, no agent) | (none — YAML read) | — | — | (read-only) |

> For the full step-by-step contract of each mode (inputs, step ordering, artifact paths, error handling), read **`MODES.md`** in this directory. skill.md dispatches; MODES.md implements.

## Dispatch Algorithm

```
1. Parse mode and args.
2. Locate experiment.yaml:
   - If --yaml provided, use it.
   - Else walk up from cwd looking for experiment.yaml.
   - If design mode and none found, create experiments/<slug>/experiment.yaml from templates/experiment.yaml.
   - If any other mode and none found, AND mode is analyze, trigger cold-start path (PRD §5.1): run analyze with defaults, emit upgrade nudge.
3. Read current status field. Validate that the requested mode is legal for the current state (see Appendix B state machine).
   - Invalid transition → print error + hint and exit.
4. Run the mode's Data Discovery Protocol if data is required.
5. Dispatch to the mode section in MODES.md. Each mode:
   a. Invokes its agent via Read-and-execute pattern (read agents/<name>.md, substitute context, execute its instructions).
   b. Calls openxp.stats functions directly — never writes Python that re-implements the math.
   c. Writes artifacts to experiments/<slug>/ and working/.
   d. Fires checkpoints in order (Type C first — never skip).
6. On success, update experiment.yaml: status, timeline.<stage>, and any results.* fields produced by the stage.
7. Return a one-screen summary: what ran, what it decided, what the next mode is.
```

## Cold-Start Path (`analyze` without `experiment.yaml`)

Per PRD §5.1, `analyze` is the lowest-friction entry point. If no YAML exists:
1. Run Data Discovery Protocol on the data file.
2. Ask only the minimum: "Which column is the treatment indicator?" + "Which is the primary metric?" (only if ambiguous).
3. Apply defaults: `alpha=0.05`, `alternative='two-sided'`, no guardrails, no practical significance threshold, no MDE target.
4. Run the full `analyze` pipeline (SRM gate included — it is **not** skippable in cold-start mode).
5. Run `interpret` with generic decision rules (SHIP on significant positive, ABORT on significant negative, LEARN on null — no INVESTIGATE branch because no guardrails).
6. Report appends upgrade nudge: *"This analysis used defaults. For pre-registered decision rules, guardrails, and power analysis, run `/experiment design` to create an experiment.yaml."*

## Checkpoint Enforcement

| Checkpoint | Type | Fires In | Skip Rule |
|------------|------|----------|-----------|
| Experiment config review | B | `design` step 6 | Skippable with `--just-do-it` |
| Power viability | C | `design`, `power` when `viable == NOT_VIABLE` | **Never skip.** Must surface options (larger MDE, more traffic, different metric, longer timeline, quasi-experimental alternative) and require user choice. |
| Min-sample guard | C | `analyze` pre-flight (PRD §5.2, D.15) | **Never skip.** If `n < 50%` of planned sample → hard stop. |
| SRM gate | C | `analyze` step 1, `monitor` check 1 | **Never skip.** If `srm_check` returns `BLOCK` → halt, run `srm_diagnose`, mark INVALID. |
| Guardrail violation | C | `analyze` step 5, `monitor` check 2 | **Never skip.** RED guardrail → surface, require user acknowledgment, offer emergency halt. |
| Analyzer draft review | B | `analyze` step 9 | Skippable with `--just-do-it` |
| Ship decision | C | `interpret` end | **Never skip.** Never auto-ship; always present recommendation + rationale + conditions and wait for human confirmation. |
| Readout draft review | B | `report` end | Skippable with `--just-do-it` |

**Type C behavior:** When a Type C fires, the skill stops agent execution, prints a clearly-labeled `[HARD STOP]` block (verdict, evidence, options), and waits for the user to choose. `--just-do-it` does **not** bypass these. If the user tries to force past one, respond: "This is a Type C safety gate and cannot be skipped. Here are the valid paths forward: ..."

## Lifecycle State Transitions (Appendix B reference)

Every mode updates the `experiment.yaml` `status` field. Valid transitions:

```
DESIGNING --power calc--> POWERED --start--> COLLECTING --analyze--> ANALYZING
ANALYZING --interpret--> INTERPRETED --readout--> REPORTED --ship--> SHIPPED --archive--> COMPLETED

Backward (allowed):
POWERED    --redesign-->    DESIGNING    (viable == NOT_VIABLE)
ANALYZING  --re-collect-->  COLLECTING   (SRM with fixable root cause, salt change, data discard)
INTERPRETED --extend-->     COLLECTING   (underpowered LEARN, extension_estimate computed)

Terminal:
ANALYZING --srm unfixable--> INVALID
(any active) --user kill--> ABANDONED
```

If the user invokes a mode that would require an invalid transition, emit:
```
Error: Cannot transition from <CURRENT> to <REQUIRED>.
Valid next modes from <CURRENT>: <list>.
Hint: Run /experiment <suggestion> first.
```

## Agent Dispatch Convention

When a mode invokes an agent, follow this contract (inherited from the repo's agent pattern):

1. Read `agents/<agent>.md` verbatim — it is the system prompt for that sub-task.
2. Substitute inputs explicitly: experiment YAML path, data path, audience, upstream artifact paths.
3. Execute the agent's instructions turn-by-turn. The agent **is not allowed** to call stats functions by re-implementing them — it must invoke `openxp.stats.*` imports.
4. Agent writes intermediate output to `experiments/<slug>/working/` and final artifacts to `experiments/<slug>/` (or `experiments/<slug>/reports/` for readouts).
5. After the agent returns, skill.md validates the output (presence of required files, valid computation traces per D.9) before advancing state.

## Stats Function Quick Reference

(All functions are re-exported at the top-level `openxp.stats` namespace. Import every function from there — never from a submodule. When tracing is enabled (default), every function returns a dict with `interpretation` and `computation_trace` fields.)

| Category | Import | Functions |
|----------|--------|-----------|
| Data prep | `from openxp.stats import ...` | `prepare_experiment_data(df, treatment_col, metric_cols, segment_cols, winsorize_spec)`, `winsorize(series, lower, upper)` |
| A/B tests | `from openxp.stats import ...` | `welch_test(control, treatment, alpha)` (two-sided only), `proportion_test(c_success, c_n, t_success, t_n, alpha)`, `fishers_exact_test`, `ratio_metric_test(num_c, den_c, num_t, den_t, alpha)` |
| Power | `from openxp.stats import ...` | `power_proportion(baseline_rate, mde_relative, alpha, power)`, `power_mean(baseline_mean, baseline_std, mde_relative, alpha, power)`, `power_ratio(baseline_num_mean, baseline_den_mean, baseline_num_std, baseline_den_std, correlation_num_den, mde_relative, alpha, power)`, `detectable_effect(n_per_group, baseline_rate=, baseline_std=, alpha, power)`, `duration_estimate(n_required, daily_traffic, allocation)`, `power_sensitivity_table(baseline_rate, mde_values, daily_traffic_values, alpha, power)` |
| SRM | `from openxp.stats import ...` | `srm_check(observed_counts, expected_ratios, threshold)` — library default `threshold=0.01`; orchestrator always passes `threshold=0.0005`. `srm_diagnose(assignments_df, group_col, segments)` |
| Guardrails | `from openxp.stats import ...` | `guardrail_test(control, treatment, metric_type, nim_relative, alpha, invert)` — implicit one-sided non-inferiority, no `alternative=` kwarg. `denominator_srm(num_c, den_c, num_t, den_t, expected_ratio, threshold)` — requires all four counts |
| Effect size | `from openxp.stats import ...` | `cohens_d(control, treatment)`, `cohens_h(p_control, p_treatment)` — point estimate only, no CI. `relative_lift(control_mean, treatment_mean)` |
| Corrections | `from openxp.stats import ...` | `adjust_pvalues(pvalues, method="holm", alpha)` |
| Extension | `from openxp.stats import ...` | `extension_estimate(current_n, current_mde_observed, required_power, baseline_variance, daily_traffic, alpha)` |
| CUPED | `from openxp.stats import ...` | `cuped_adjust(y_pre, y_post, treatment=None)`, `cuped_welch_test(control_pre, control_post, treatment_pre, treatment_post, alpha)`, `variance_reduction(y_pre, y_post)` |
| Sequential | `from openxp.stats import ...` | `msprt_test`, `always_valid_ci`, `group_sequential_boundaries`, `sequential_proportion_test` |
| Bayesian | `from openxp.stats import ...` | `beta_binomial_test`, `normal_normal_test`, `expected_loss`, `probability_to_beat` |
| Tracing | `from openxp.stats import ...` | `set_trace(enabled)`, `is_trace_enabled()` — controls D.9 `computation_trace` emission (default: on) |

Agents must import from the top-level `openxp.stats` namespace only. If a function is missing, stop and report — **never improvise**.

## Data Discovery Protocol (delegated)

Used by `analyze`, `monitor`, and `full` whenever data is provided. Full protocol in `CLAUDE.md` §Data Discovery Protocol. Summary:

1. Read first 5 rows + dtypes + shape.
2. Auto-detect treatment column from: `variant`, `group`, `treatment`, `arm`, `experiment_group`, `bucket`.
3. Numeric columns → metric candidates. Categorical (2–20 uniques) → segment candidates. Datetime → timestamp.
4. If ambiguous, ask the user. Never assume.

## Dry Run

With `--dry-run`, print the planned execution (mode → agent → stats calls → artifacts → checkpoints) without invoking agents or writing files. Useful for `full` mode to preview the entire pipeline.

## Output Artifacts (per mode, under `experiments/<slug>/`)

| Mode | Writes |
|------|--------|
| `design` | `experiment.yaml` (status: POWERED), `design-brief.md`, `working/designer-conversation.md` |
| `power` | updates `experiment.yaml` (power block + status), `power-report.md`, `working/sensitivity-table.csv` |
| `analyze` | `analysis_results.json`, `reports/analysis.md`, updates `experiment.yaml` results block, `working/analyzer-trace.md` |
| `interpret` | `interpretation.md`, updates `experiment.yaml` (status: INTERPRETED, results.classification), `working/interpretation-trace.md` |
| `monitor` | `monitoring/<date>.md` (traffic-light dashboard), appends to `monitoring/history.yaml` |
| `report` | `reports/readout-<audience>.md`, updates `experiment.yaml` (status: REPORTED) |
| `full` | all of the above in sequence |
| `status` | (none — stdout only) |

## Failure and Recovery

- **Agent error:** Preserve working/ files, emit clear error with the failed step, do not advance state.
- **Stats function error:** Log the `computation_trace`, halt the agent, return the specific function + inputs for debugging.
- **YAML corruption:** Refuse to run; instruct user to restore from git or re-run `/experiment design`.
- **SRM BLOCK:** Hand-off to the SRM recovery flow (Appendix B note on fixable vs unfixable root cause) — ask the user "Do you know the root cause?" to choose COLLECTING vs INVALID path.

## See Also

- **`MODES.md`** (this directory) — deep spec for each of the 8 modes.
- **`CLAUDE.md`** (repo root) — identity, agent index, stats reference, checkpoint definitions.
- **`agents/experiment-*.md`** — the 5 agent prompts this skill dispatches to.
- **`templates/experiment.yaml`** — pre-registration schema.
- **PRD Appendix A** — Result Interpretation Tree (for `interpret`).
- **PRD Appendix B** — experiment.yaml state machine (for `status` and state transitions).
