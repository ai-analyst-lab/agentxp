---
name: design
description: Drive an experiment from intent through a sealed brief. Pre-registration only — refuses outcome-column queries (R11). Terminates when brief.sealed.yaml lands and the user confirms.
---

# Skill: `/design`

## Purpose

The design verb pre-registers an experiment. You walk from intent → semantic models → metrics → hypothesis → brief → data plan → sealed brief, dispatching specialists at each step. The SQL safety pipeline runs in `mode="design"` — Layer 3d rejects any query that references outcome columns (`variant`, `arm`, `assigned_arm`, metric values). There is no `--force`.

The verb terminates when the brief seals with the three-part integrity lock (`design_chain_hash` + `metric_snapshot` + `expected_shape`). At that point the user invokes `/analyze --brief experiments/<id>/brief.sealed.yaml` to enter the analyze verb.

## When to invoke

Direct: `/design [--data PATH] [--exp-id ID]`

Plain-English routing:

| Phrase | What to do |
|---|---|
| "I want to test a new checkout button" | `/design`, then capture intent (step 2) |
| "Design an experiment against the demo warehouse" | `/design --data sample-data/agentxp_demo.duckdb` |
| "Continue exp_a3f9c102" | `/design --exp-id exp_a3f9c102` |
| "Show me the lift" (in design mode) | **REFUSE** — R11 wall; that is the analyze verb's job |

## Procedure (do these in order)

### 1. Allocate the experiment directory

```python
from pathlib import Path
from agentxp.workflows.design import allocate_experiment

exp_dir = allocate_experiment(
    project_root=Path.cwd(),
    data_path=Path(args.data) if args.data else None,
    exp_id=args.exp_id,  # None → ULID-flavored auto-id
)
```

The helper creates `experiments/<id>/`, seeds `log.md`, and stashes the data path if supplied. Print the experiment id so the user can reference it later.

### 2. Capture intent

Ask the user for their intent in plain English. When you have it, persist:

```python
from agentxp.workflows.design import record_intent

intent_path = record_intent(
    exp_dir,
    intent_text=user_supplied_text,
    captured_by=user_email_or_handle,
)
```

This writes `intent.yaml` and appends to `log.md`. Then render the intent share-tail:

```python
from agentxp.render.distill import distill_intent
from agentxp.orchestrator.tools import render_share_tail

vm = distill_intent(
    experiment_id=exp_dir.name,
    intent_text=user_supplied_text,
    captured_at=<from intent.yaml>,
    captured_by=user_email_or_handle,
)
render_share_tail(
    exp_dir=exp_dir,
    experiment_id=exp_dir.name,
    readout_type="intent",
    vm=vm,
    vm_sha256=<sha of vm.model_dump_json()>,
    provenance_render_status="DRAFT_UNVERIFIED",
)
```

Open the `confirm_intent` gate: ask the user "the intent looks like this — does it capture what you want to test?" Wait for a confirmation before continuing.

### 3. Ensure semantic models exist

Read `<project_root>/semantic_models/`. If empty (or missing the entities the user's intent implies), dispatch the **understander** specialist for `task="draft_semantic_models"`.

```python
from agentxp.orchestrator.loop import dispatch_specialist
from agentxp.schemas.bundles import UnderstanderBundle, WarehouseProfile
from agentxp.profiler.driver import profile_warehouse  # or similar

profile = profile_warehouse(exp_dir.read_text(".data_path"))

proposals = dispatch_specialist(
    role="understander",
    sources={
        "warehouse_profile": profile,
        "existing_semantic_models": [],
        "existing_metrics": [],
        "task": "draft_semantic_models",
    },
    project_root=Path.cwd(),
)
```

Dispatch the **critic** in `brief_consistency` mode against each proposal before committing.

### 4. Ensure metrics exist

Same shape as step 3 but `task="draft_metrics"`. The understander is **blind to experiment intent** (R5) — its bundle structurally lacks the intent field, which prevents metric-fishing. Do not pass the user's intent into this dispatch.

### 5. Dispatch the designer for the hypothesis

```python
from agentxp.schemas.bundles import DesignerBundle, AssignmentSurface

surface = AssignmentSurface(
    units_available=<from warehouse>,
    accrual_per_day=<from warehouse>,
    segments=<from semantic models>,
    assignment_unit="user_id",  # or whatever the brief targets
)

hypothesis_draft = dispatch_specialist(
    role="designer",
    sources={
        "intent": {"text": <intent_text>, "captured_at": <ts>},
        "semantic_models": <loaded>,
        "metrics": <loaded>,
        "assignment_surface": surface,
        "prior_drafts": [],
        "task": "draft_hypothesis",
    },
    project_root=Path.cwd(),
)
```

Commit `hypothesis.yaml` via `commit_artifact`. Dispatch the critic in `brief_consistency` mode. If blocked, synthesize the objection (don't delegate to designer with "fix it" — understand and direct), re-dispatch designer with the objection attached.

### 6. Dispatch the designer for the brief

Same shape as step 5 but `task="draft_brief"`. The brief must declare:

- A primary metric (one, by name)
- A decision rule that is **tight enough that a real treatment effect could fail it** (R1)
- An MDE
- Cohort definitions expressible against the assignment surface
- A list of guardrails (each with direction + nim_relative)

Commit `brief.yaml`. Dispatch critic.

### 7. Dispatch the designer for the data plan

Same shape, `task="draft_data_plan"`. Commit `data_plan.yaml`. Dispatch critic.

### 8. Run the power-feasibility check

Required-n vs available units. The `seal_brief` step refuses with a math-rich message if required-n exceeds the surface; **no `--force`** (R11). If it would fail, either widen the MDE or expand the surface — return to step 6.

### 9. Confirm seal gate with user

```python
from agentxp.orchestrator.tools import confirm_with_user  # if implemented
# or inline: print the brief summary, ask "ready to seal?"
```

This is the **`confirm_brief_seal`** gate. Closing it crosses the design/analyze wall (R11); the user knows.

### 10. Seal the brief

```python
from agentxp.schemas.brief_seal import seal_brief, ExpectedShape

expected_shape = ExpectedShape(
    assignment_unit=<from brief>,
    arms=<from brief>,
    expected_arm_count_ratio=<from brief>,
    cohort_definitions=<from brief>,
)

sealed = seal_brief(
    brief_content=<dict from brief.yaml>,
    design_chain_path=exp_dir / "log.md",
    metric_paths={name: project_root / "metrics" / f"{name}.yaml"
                  for name in <metric names from brief>},
    expected_shape=expected_shape,
    sealed_by=<user>,
    agentxp_version=agentxp.__version__,
)

# Write the sealed brief
import yaml
(exp_dir / "brief.sealed.yaml").write_text(yaml.safe_dump(sealed.model_dump(mode="json"), sort_keys=False))
```

Then `commit_artifact("brief.sealed.yaml", ..., "brief sealed")`.

### 11. Render the design-brief share-tail

```python
from agentxp.render.distill import distill_design_brief

vm = distill_design_brief(
    experiment_id=exp_dir.name,
    sealed_brief_payload=<dict>,
    integrity_lock={
        "design_chain_hash": sealed.design_chain_hash,
        "metric_snapshot": sealed.metric_snapshot,
        "expected_shape": expected_shape.model_dump(),
        "sealed_at": sealed.sealed_at.isoformat(),
    },
)
render_share_tail(
    exp_dir=exp_dir,
    experiment_id=exp_dir.name,
    readout_type="design_brief",
    vm=vm,
    vm_sha256=<sha>,
    provenance_render_status="VERIFIED",
)
```

### 12. Print next-step guidance and terminate

```
Brief sealed at experiments/<id>/brief.sealed.yaml
To analyze, invoke: /analyze --brief experiments/<id>/brief.sealed.yaml
```

The design verb is done.

## Tools you call

| Tool | Module |
|---|---|
| `allocate_experiment` / `record_intent` | `agentxp.workflows.design` |
| `dispatch_specialist` / `dispatch_critic` / `require_critic_pass` | `agentxp.orchestrator.loop` |
| `probe_data(mode="design")` | `agentxp.orchestrator.tools` |
| `seal_brief` / `verify_brief_seal` | `agentxp.schemas.brief_seal` |
| `commit_artifact` / `render_share_tail` | `agentxp.orchestrator.tools` |
| `distill_intent` / `distill_design_brief` | `agentxp.render.distill` |

See `agentxp/INDEX.md` for full signatures.

## Specialists you dispatch

| Specialist | Bundle | When | Blind to |
|---|---|---|---|
| `understander` | `UnderstanderBundle` | Steps 3, 4 (semantic models, metrics) | Experiment intent (R5) |
| `designer` | `DesignerBundle` | Steps 5, 6, 7 (hypothesis, brief, data plan) | Analysis output (R10) |
| `critic` | `CriticBundle(judging_mode="brief_consistency")` | After every commit | Producer reasoning (R6) |

See `agents/<role>.md` for each system prompt.

## Rules cited

- **R1** — pre-register the primary metric, decision rule, MDE, cohorts before any number is read
- **R5** — understander blind to intent (structurally enforced by `UnderstanderBundle`)
- **R6** — critic fires at every commit
- **R10** — bundles assembled by schema, not by you
- **R11** — design / analyze wall is architectural; design verb cannot reach outcome data

## What this skill does NOT do

- Compute any statistic (R4 — only the analyze verb runs `agentxp.stats.*`)
- Read outcome-bearing columns (R11 — the SQL safety pipeline refuses)
- Improvise a verdict (R3 — that comes from `decision_tree()` in analyze)
- Auto-seal the brief — sealing requires the user's `confirm_brief_seal` gate

## Terminal artifact

`experiments/<id>/brief.sealed.yaml` exists, was produced by `seal_brief()`, and the user has confirmed it. From this moment the design verb is closed; the user invokes `/analyze --brief experiments/<id>/brief.sealed.yaml` to continue.

## Banned vocabulary

The voice audit at `agentxp/render/voice_audit.py` rejects the marketing-register phrases listed in CLAUDE.md §13. The brief and every commit narration must use the academic register.
