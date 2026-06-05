---
name: readouts
description: Walk the renders catalog for an experiment, validate the hash chain, or regenerate the cross-experiment HTML index navigator.
---

# Skill: `/readouts`

## Purpose

Every readout produced by the presentation spine appends one entry to `experiments/<id>/readouts/catalog.jsonl` — an append-only hash-chained ledger. This skill walks the catalog (per-experiment or cross-experiment), validates the chain, and regenerates the static HTML index navigator.

The catalog is the only surviving hash chain in v2; tampering breaks it independently of git.

## When to invoke

Direct:
- `/readouts <exp_id>` — list this experiment's renders
- `/readouts --index` — regenerate the cross-experiment HTML navigator
- `/readouts <exp_id> --validate` — walk the chain, exit non-zero on break

Plain-English routing:

| Phrase | What to do |
|---|---|
| "Show me the renders for exp_001" | `/readouts exp_001` |
| "Rebuild the audit index" | `/readouts --index` |
| "Is the catalog intact" | `/readouts <exp_id> --validate` |
| "What readouts have I made across all experiments" | `/readouts --index` |

## Procedure

### Catalog mode

```python
from pathlib import Path
from agentxp.workflows.readouts import list_catalog

entries = list_catalog(Path.cwd() / "experiments" / args.exp_id)
for i, entry in enumerate(entries):
    payload = entry.payload
    print(f"{i:>3}  {entry.timestamp}  {payload.event:<26}  ...")
```

### Index mode

```python
from agentxp.workflows.readouts import build_index

rows = build_index(Path.cwd())
# Each row: experiment_id, n_renders, worst_status, latest_render_type, latest_render_at
```

Render an HTML table from the rows and write to `readouts/index.html`. The worst-case status per experiment uses the cascade: `UNVERIFIABLE > DRAFT_UNVERIFIED > VERIFIED`.

### Validate mode

```python
from agentxp.render.catalog import validate_catalog, CatalogChainBreak

try:
    validate_catalog(Path.cwd() / "experiments" / args.exp_id / "readouts" / "catalog.jsonl")
    print("catalog chain ok")
except CatalogChainBreak as exc:
    print(f"catalog chain break: {exc}", file=sys.stderr)
    raise SystemExit(1)
```

## Tools you call

- `list_catalog` / `build_index` from `agentxp.workflows.readouts`
- `validate_catalog` from `agentxp.render.catalog`

## Rules cited

- **R7** — catalog entries cite the artifacts they record
- **R9** — `RenderStatus` computed at read time; cascade preserved in `build_index`'s worst-case-per-experiment

## What this skill does NOT do

- Produce new readouts — those fire automatically at share-tail moments during `/design` (intent, brief seal) and `/analyze` (monitor halt, verdict commit)
- Re-render with different data — that requires re-running the verb against the updated artifacts; the catalog records the supersession via `RenderSupersededEvent`

## Terminal output

Catalog mode: tab-separated rows to stdout.
Index mode: writes `readouts/index.html`, prints summary table.
Validate mode: exit 0 (chain ok) or exit 1 with chain-break details.
