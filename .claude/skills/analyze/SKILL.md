---
name: analyze
description: Drive a sealed brief through verdict + readout. Verifies the three-part integrity lock first (R11). SRM check first (R2). Verdict from the decision tree only (R3).
---

# Skill: `/analyze`

## Purpose

The analyze verb runs from a sealed brief through verdict + readout. Its first action is to verify the brief's three-part integrity lock (`design_chain_hash` + `metric_snapshot` + `expected_shape`). Any mismatch refuses entry; there is no `--force`.

On verify pass, the loop is fixed by the worldview:
1. SRM first (R2) — no metric value is read before the assignment ratio is checked
2. Stats only from the whitelist (R4) — every number comes from `agentxp.stats.*`
3. Verdict from the decision tree (R3) — `walk_tree()` is the only path
4. Narrator blind to hypothesis direction (R5) — `AnalystNarratorBundle` enforces this
5. Critic fires at every commit (R6)
6. Confidence labels computed, not chosen (R8)
7. Every readout claim cites an artifact (R7)

## When to invoke

Direct: `/analyze --brief experiments/<id>/brief.sealed.yaml`

Plain-English routing:

| Phrase | What to do |
|---|---|
| "Analyze experiment exp_001" | `/analyze --brief experiments/exp_001/brief.sealed.yaml` |
| "What does the data say" (sealed brief in context) | `/analyze --brief <path>` |
| "Run the analysis for the checkout test" | `/analyze --brief <path>` |
| "Analyze before sealing the brief" | **REFUSE** — R1 + R11 require a sealed pre-registration |

## Procedure (do these in order)

### 1. Verify the seal (R11 wall)

```python
from pathlib import Path
from agentxp.workflows.analyze import verify_and_open
from agentxp.schemas.brief_seal import BriefSealMismatch

try:
    sealed = verify_and_open(Path(args.brief), Path.cwd())
except BriefSealMismatch as exc:
    print(f"REFUSED: {exc}")
    raise SystemExit(1)
```

If verify fails: print the specific reason (which lock component, current vs sealed hash), exit. The user resolves the drift (rev the brief, restore the metric, etc.) and re-invokes.

If verify passes: print the experiment id + the integrity-lock receipt (truncated hashes for display).

### 2. SRM check (R2 — always first)

Before any metric value is read, run SRM:

```python
from agentxp.orchestrator.tools import probe_data
from agentxp.stats.srm import srm_check

# Query observed counts per arm
result = probe_data(
    "SELECT arm, count(*) FROM assignments WHERE experiment_id = '<id>' GROUP BY arm",
    mode="analyze",  # analyze mode — outcome columns allowed
)
# Parse into {arm_name: count}
observed = {...}

expected_ratios = sealed.expected_shape.expected_arm_count_ratio

srm_result = srm_check(
    observed_counts=observed,
    expected_ratios=expected_ratios,
    threshold=0.0005,
)
```

If `srm_result.verdict == "BLOCK"`: open the `srm_override` gate. Ask the user to resolve (override with reason code, or abort). If `WARNING`: surface to user with the data; user decides whether to override or extend monitoring. **You do not read any metric value until SRM has passed or been resolved.**

### 3. Guardrails

For each guardrail in `sealed.brief_content["guardrails"]`:

```python
from agentxp.stats.guardrails import guardrail_test

result = guardrail_test(
    observed=<from query>,
    direction=guardrail.direction,
    nim_relative=guardrail.nim_relative,
)
```

If any guardrail's lower 90% CI crosses the harm threshold: this is a **NO-SHIP-GUARDRAIL** at step 2 of the verdict tree. Render the monitor halt share-tail (`distill_mid_run` with `halt_reason="guardrail_breach"`), and continue to the verdict step rather than aborting — the tree owns the decision.

### 4. Primary metric(s)

For each primary metric in the brief:

```python
from agentxp.metrics.registry import load_metric

metric = load_metric(<project_root>, name=metric_name)
test_fn = metric.to_test_function()
# E.g. proportion_test for type=proportion
result = test_fn(c_success=..., c_n=..., t_success=..., t_n=...)
```

Use `run_stat(test_name, **args)` if available for the refusal-on-invalid-combo discipline.

### 5. Segments (Holm-Bonferroni adjustment if > 1)

If the brief pre-registers multiple segments:

```python
from agentxp.stats.corrections import adjust_pvalues

adjusted = adjust_pvalues(
    [r.p_value for r in segment_results],
    method="holm",
)
```

### 6. Confidence labels (computed, not chosen — R8)

```python
from agentxp.interpret.confidence import map_confidence

label = map_confidence(
    ci_low=result.ci_95_lower,
    ci_high=result.ci_95_upper,
    orientation=metric.direction,
)
```

You **quote** the label that `map_confidence` returns. You do not upgrade `leaning positive` to `very likely positive` because the lift "feels real." The label is a number-derived fact.

### 7. Dispatch analyst-narrator (blind to hypothesis direction)

```python
from agentxp.orchestrator.loop import dispatch_specialist

narrative = dispatch_specialist(
    role="analyst_narrator",
    sources={
        "metric_results": [<MetricResult per metric>],
        "brief_decision_rules": [<DecisionRule per rule from brief>],
        "srm_result": srm_result,
        "guardrail_results": [<GuardrailResult per guardrail>],
        "confidence_labels": [<ConfidenceLabelEntry per metric>],
    },
    project_root=Path.cwd(),
)
```

Commit `analysis.json` with the narrative. Dispatch the critic in `analysis_vs_brief` mode.

### 8. Decision tree (R3 — verdict comes from here, nowhere else)

```python
from agentxp.interpret.tree import TreeInput, walk_tree, GuardrailEval

tree_input = TreeInput(
    srm_pass=srm_result.verdict == "PASS",
    srm_override_resolved=<user override resolved?>,
    guardrails=[GuardrailEval(...) for each guardrail],
    n_observed=<from query>,
    n_required=<from brief>,
    primary_ci_lower_95=primary_result.ci_95_lower,
    primary_ci_upper_95=primary_result.ci_95_upper,
    primary_ci_lower_90=primary_result.ci_90_lower,
    primary_ci_upper_90=primary_result.ci_90_upper,
    primary_lift_magnitude=primary_result.lift_relative,
    primary_direction=primary_metric.direction,
    mde_pct=brief.mde_pct,
    baseline=brief.baseline,
    late_ratio=<if you computed one>,
)

tree_result = walk_tree(tree_input)
# tree_result.verdict   — one of 9 Verdict values
# tree_result.terminal_step  — 1..8
```

Commit `interpretation.json` with the tree result. Dispatch critic in `verdict_vs_analysis` mode.

If the tree returns `UNVERIFIABLE`: do not soften, do not re-run, do not improvise. The `diagnostics["missing_inputs"]` field tells you which required input was None; surface that to the user as the reason.

### 9. Render the verdict share-tail

```python
from agentxp.render.distill import distill_verdict
from agentxp.render.viewmodel import ViewBundle
from agentxp.render.provenance import build_provenance

vm = distill_verdict(<Report object>)
provenance = build_provenance(<Report>, exp_dir)
# Bundle them — every adapter renders against ViewBundle, not raw Report
bundle = ViewBundle(vm=vm, provenance=provenance)

render_share_tail(
    exp_dir=exp_dir,
    experiment_id=exp_dir.name,
    readout_type="verdict",
    vm=vm,
    vm_sha256=<sha>,
    provenance_render_status=bundle.render_status.name,
)
```

Commit `report.md` + `report.json`. Dispatch the critic in `readout_faithfulness` mode against the rendered report. The critic checks every quantitative claim has an `AuditPaths` reference (R7).

### 10. Confirm readout gate

Print the verdict + step_fired. Ask the user to confirm the readout. This is the `confirm_readout` gate. On confirm, the experiment is marked done; the analyze verb terminates.

## Tools you call

| Tool | Module |
|---|---|
| `verify_and_open` | `agentxp.workflows.analyze` |
| `srm_check` / `guardrail_test` / metric test functions / `adjust_pvalues` / `winsorize` | `agentxp.stats.*` |
| `walk_tree` / `compute_late_ratio` | `agentxp.interpret.tree` |
| `map_confidence` | `agentxp.interpret.confidence` |
| `dispatch_specialist` / `dispatch_critic` / `require_critic_pass` | `agentxp.orchestrator.loop` |
| `probe_data(mode="analyze")` | `agentxp.orchestrator.tools` |
| `render_share_tail` / `commit_artifact` | `agentxp.orchestrator.tools` |
| `distill_verdict` / `distill_mid_run` | `agentxp.render.distill` |

See `agentxp/INDEX.md` for full signatures.

## Specialists you dispatch

| Specialist | When | Blind to |
|---|---|---|
| `sql_specialist` | Each query against the warehouse | (bounded, not adversarial) |
| `analyst_narrator` | Step 7 (narrative prose) | Hypothesis direction, designer narrative (R5) |
| `critic` | After every commit (3 modes: `analysis_vs_brief`, `verdict_vs_analysis`, `readout_faithfulness`) | Producer reasoning (R6) |

## Rules cited

- **R2** — SRM before any metric value
- **R3** — verdict from `walk_tree()` only
- **R4** — numbers from `agentxp.stats.*` only
- **R5** — analyst-narrator blind to hypothesis direction
- **R6** — critic fires at every commit
- **R7** — every claim cites
- **R8** — confidence label from `map_confidence()`
- **R11** — three-part integrity lock verified before opening

## What this skill does NOT do

- Re-draft the brief — that's the design verb. Edit and re-seal in design mode.
- Compute statistics outside the whitelist (R4).
- Soften the verdict the tree returns (R3).
- Upgrade a `leaning positive` label by adjective choice (R8).

## Terminal artifact

`experiments/<id>/report.md` + `report.json` committed, critic-passed, user-confirmed. The experiment is done.

## Banned vocabulary

The voice audit rejects marketing-register phrases (see CLAUDE.md §13). Every claim in the narrative cites an `AuditPaths` reference. The narrator quotes confidence labels verbatim from `map_confidence`.
