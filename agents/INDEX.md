# agents/INDEX.md — specialist roster

Five specialists, plus the orchestrator. The orchestrator's prompt is the
project root `CLAUDE.md`. Each specialist's prompt is at `agents/<role>.md`
with a top-of-file CONTRACT block (HTML-commented YAML, parseable).

Full per-role detail lives in each `agents/<role>.md`. The machine-readable
DAG (inputs/outputs, dispatched_by, depends_on) lives in `agents/registry.yaml`,
generated from CONTRACT blocks by `python -m agentxp.agents.gen_registry`.

| Role | Lines | Dispatched by | Bundle schema | Blind to (excerpt) |
|---|---|---|---|---|
| `understander` | ~120 | `design` (semantic_models + metrics tasks) | `UnderstanderBundle` | intent, hypothesis, brief, experiment_intent |
| `designer` | ~150 | `design` (hypothesis + brief + data_plan tasks) | `DesignerBundle` | analysis output, lift, CI, p_value |
| `critic` | ~180 | `design` + `analyze` (4 `judging_mode` values) | `CriticBundle` | producer_reasoning, conversation_history, prior_judgments |
| `sql_specialist` | ~150 | `design` + `analyze` (mode-aware) | `SqlSpecialistBundle` | (bounded, not adversarially blind) |
| `analyst_narrator` | ~150 | `analyze` (analysis narration only) | `AnalystNarratorBundle` | hypothesis, hypothesis_prose, designer_narrative, expected_direction |

## DAG summary (from `agents/registry.yaml`)

```
Level 0: understander, sql_specialist     (no specialist deps)
Level 1: designer                         (consumes understander outputs)
Level 2: analyst_narrator                 (consumes sql_specialist + brief_seal)
Level 3: critic                           (consumes anyone's output for review)
```

## Closure tests (`tests/agents/test_contracts.py`)

1. Every `agents/*.md` has a parseable CONTRACT block.
2. Every `bundle_schema` named exists in `agentxp.schemas.bundles.BUNDLE_SCHEMAS`.
3. Every `blind_to` field matches `BLINDNESS_MANIFEST`.
4. Every `dispatched_by` references a real `.claude/skills/<name>/SKILL.md`.
5. `agents/registry.yaml` parses + topologically sorts (Kahn) without cycle.

## Adding a new specialist

1. Decide what the role is blind to and why. Cite a rule from CLAUDE.md §4.
2. Add a new bundle schema to `agentxp/schemas/bundles.py` (with `extra="forbid"`).
3. Add the role name + forbidden field set to `BLINDNESS_MANIFEST`.
4. Write `agents/<role>.md` with a CONTRACT block + body.
5. Register the role in `BUNDLE_SCHEMAS`.
6. Regenerate `agents/registry.yaml`.
7. Update this table.

The closure tests will fail until all six steps land.
