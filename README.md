# AgentXP

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/runs%20in-Claude%20Code-blueviolet.svg)](https://claude.ai/code)

> **This is exploratory work — a sketch of what agentic experimentation *could* look like, not a production-ready tool.** AgentXP is a thinking aid for ourselves and a way to tease out where AI agents can genuinely help with experiment design and analysis (and where they shouldn't be trusted). Expect rough edges, opinionated choices, and active rework. If you fork it for real work, you own the result.

AgentXP is a single-user system for the design and analysis of controlled experiments. **You drive it by talking to Claude Code.** The orchestrator never reads outcome data before a brief is sealed, never improvises a verdict, and produces a readout at every moment of the loop so the work is visible as it happens.

There is **no CLI**. There is no shell command to learn. You open this repository inside Claude Code, type a slash command (or just describe what you want), and the agent walks the procedure with you.

Apache 2.0. Local. DuckDB ships in v0.2; Snowflake / BigQuery / Databricks adapters carry forward from v0.1.

## How you actually use this

### One-time setup (terminal)

```bash
# 1. Clone + sync the Python environment
uv sync

# 2. Open the repo in Claude Code
cd path/to/agentxp
claude
```

You're now in the orchestrator's session. The system prompt is `CLAUDE.md`; the orchestrator already knows the eleven worldview rules (R1–R11) and the five slash commands below.

### Connect your warehouse

Inside Claude Code, run `/connect-data` and pick your dialect — DuckDB, Snowflake, BigQuery, or Databricks. The wizard writes a `chmod-600` credentials file under `~/.agentxp/credentials/<dialect>/<profile>.yaml`. You only do this once per warehouse.

### Define your metrics

`metrics/` and `semantic_models/` ship as empty directories with a single `_TEMPLATE.yaml` each. Copy the templates and define your catalog before running real experiments — `metrics/conversion_rate.yaml`, `semantic_models/user.yaml`, etc. The brief-seal hashes every referenced metric file (R11), so changing a metric definition after seal will fail verification — which is the point.

### Talk to it

Five slash commands. The orchestrator also routes plain English to the right one.

| Type this | Or say something like | What happens |
|---|---|---|
| `/design` | "I want to test the new checkout button" | Allocates `experiments/<id>/`, captures intent, dispatches the designer + critic to draft + judge the brief, ends when you seal the brief |
| `/analyze --brief experiments/<id>/brief.sealed.yaml` | "Analyze the brief I just sealed" | Verifies the three-part integrity lock first, then walks SRM → guardrails → stats → narrator → verdict tree, ends with a readout |
| `/audit <exp_id>` | "Why did experiment exp_a3f9 halt?" | Walks `log.md` + `git log` + the renders catalog for that experiment |
| `/readouts <exp_id>` | "Show me the renders from exp_a3f9" | Lists the catalog entries; `/readouts --index` rebuilds the cross-experiment HTML navigator |
| `/connect-data <dialect>` | "Wire up my Snowflake warehouse" | Interactive wizard for `duckdb`, `snowflake`, `bigquery`, or `databricks`; writes a chmod-600 credentials file |

### Your first experiment

1. In Claude Code, describe the change you want to test — e.g. **"design an experiment testing whether moving the Buy Now button above the fold improves conversion"**.
2. The orchestrator allocates an experiment dir, captures the intent, dispatches the designer to draft a brief, dispatches the critic to judge it, and asks you to confirm the seal.
3. Confirm. The brief seals (three-part integrity lock locks it).
4. When the test is done collecting data, type: **"analyze the sealed brief"**.
5. The orchestrator verifies the seal, runs SRM (R2 — always first), the stats whitelist, the decision tree, dispatches the analyst-narrator (blind to your hypothesis direction), commits the report, and asks you to confirm the readout.
6. You read the verdict.

The audit log is in `experiments/<id>/log.md`; the readout is at `experiments/<id>/report.md`; every commit is a real git commit on the `experiments/<id>/` directory.

## What the orchestrator will and won't do

The orchestrator operates under **eleven worldview rules** (CLAUDE.md §4). It cites them by number when it refuses something:

- **R1** pre-register before observation • **R2** SRM before metrics • **R3** verdicts only from the decision tree • **R4** numbers only from the stats whitelist • **R5** producers blind to judges • **R6** critic fires at every commit • **R7** every claim cites an artifact • **R8** confidence labels computed not chosen • **R9** render status cascades at read time • **R10** bundles assembled by schema • **R11** the design / analyze wall is architectural

If you ask the orchestrator to "just peek at the lift before sealing the brief", it will refuse and tell you it's R1 + R11. The SQL safety pipeline literally cannot return outcome columns in design mode.

## What's in the box

- **One orchestrator + five specialists** (designer, critic, sql_specialist, analyst_narrator, understander). Specialists dispatch with schema-validated bundles. The critic is blind to producer reasoning; the metric drafter is blind to experiment intent; the analyst-narrator is blind to hypothesis direction. Per-role detail in [agents/INDEX.md](agents/INDEX.md). Machine-readable DAG in [agents/registry.yaml](agents/registry.yaml).
- **Deterministic statistical core** in `agentxp/stats/*`, `agentxp/interpret/*`, `agentxp/sql/safety.py`. The orchestrator never computes a statistic itself; every number traces to a named whitelist function. Full catalog in [agentxp/INDEX.md](agentxp/INDEX.md).
- **Continuous presentation spine**. Five readout types fire at four moments (intent capture, brief seal, monitor halt, verdict). Per-type Pydantic ViewModels with `extra="forbid"`; `MidRunVM` structurally lacks lift / CI / p-value fields so peek-prevention is enforced by the type system, not by agent discipline.
- **Renders catalog as its own hash chain** at `experiments/<id>/readouts/catalog.jsonl`. Tampering is detectable; `/readouts --index` walks every experiment to compose a cross-experiment HTML navigator.
- **Warehouse adapters** for DuckDB, Snowflake, BigQuery, and Databricks. The SQL safety pipeline (`agentxp/sql/safety.py`) is dialect-agnostic — adapters only translate, never bypass the six-layer pipeline.

## When you want to do something the orchestrator does not

The Python library `agentxp` is importable. If you want to script something for CI or a notebook, you call the workflow helpers directly:

```python
from agentxp.schemas.brief_seal import verify_or_raise, SealedBrief
from agentxp.interpret.tree import walk_tree, TreeInput
from agentxp.stats.ab_tests import proportion_test
from agentxp.stats.srm import srm_check
```

The function catalog is [agentxp/INDEX.md](agentxp/INDEX.md). Skills cite functions through it.

## Project layout

```
CLAUDE.md                        system prompt — the worldview the orchestrator follows
agentxp/                         Python library (no CLI)
  INDEX.md                       function catalog skills cite
  workflows/                     skill-callable helpers (design, analyze, audit, readouts, resume, connect)
  schemas/bundles.py             5 specialist bundle schemas (R10 foundation)
  schemas/brief_seal.py          3-part integrity lock (R11)
  interpret/tree.py              8-step decision tree, 9 verdicts including UNVERIFIABLE
  sql/safety.py                  6-layer SQL pipeline (Layer 3d = design-mode wall)
  orchestrator/loop.py           specialist dispatch + critic firing
  orchestrator/tools.py          typed tool surface
  render/                        presentation spine, distill, catalog, charts
  stats/                         statistical truth — never reimplement these
agents/                          5 specialist prompts + CONTRACT blocks + registry.yaml
.claude/skills/                  5 slash command skills (design, analyze, audit, readouts, connect-data)
metrics/                         your metric catalog (one YAML per metric; _TEMPLATE.yaml documents the schema)
semantic_models/                 your semantic-model catalog (same pattern)
tests/                           pytest suite
```

## License

Apache 2.0.
