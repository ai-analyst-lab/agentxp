---
name: connect-data
description: Wire a warehouse profile via an interactive wizard. Supports DuckDB, Snowflake, BigQuery, Databricks. Writes ~/.agentxp/credentials/<dialect>/<profile>.yaml at chmod 600.
---

# Skill: `/connect-data`

## Purpose

Wire a warehouse profile so the design and analyze verbs can `probe_data` against it. The wizard walks the user through the connection fields for their chosen dialect, tests the connection, and writes the credentials file.

## When to invoke

Direct:
- `/connect-data <dialect>` — start the wizard for one dialect
- `/connect-data` — ask the user which dialect first

Supported dialects: `duckdb`, `snowflake`, `bigquery`, `databricks`.

Plain-English routing:

| Phrase | What to do |
|---|---|
| "Connect to my Snowflake warehouse" | `/connect-data snowflake` |
| "Wire up the demo DuckDB" | `/connect-data duckdb` |
| "I need to set up BigQuery" | `/connect-data bigquery` |
| "Hook up Databricks" | `/connect-data databricks` |

## Procedure

### 1. Pick the dialect

If the user did not supply one, ask. Then:

```python
from agentxp.workflows.connect import run_wizard

out_path = run_wizard(dialect)
```

The wizard prompts for each field per the dialect schema. Fields with defaults can be left blank; required fields prompt until non-empty. The wizard writes `~/.agentxp/credentials/<dialect>/<profile>.yaml` at chmod 600.

### 2. Test the connection

After the wizard returns, attempt a minimal query (e.g., `SELECT 1`) through the safety pipeline:

```python
from agentxp.orchestrator.tools import probe_data

result = probe_data("SELECT 1", mode="analyze", dialect=dialect)
```

If the query fails: surface the error to the user and offer to re-run the wizard.

### 3. Confirm + print next step

```
Profile written to ~/.agentxp/credentials/<dialect>/<profile>.yaml
Next: /design --data <path-or-profile> to begin an experiment.
```

## Tools you call

- `run_wizard` from `agentxp.workflows.connect`
- `probe_data(mode="analyze")` from `agentxp.orchestrator.tools` for the connection test

## Rules cited

- **R10** — credential file shape is a Pydantic-validated schema (no ad-hoc fields)
- **R11** — once wired, design queries against this warehouse run in `mode="design"` and refuse outcome columns

## What this skill does NOT do

- Migrate credentials between formats
- Store credentials in version control — files land at `~/.agentxp/credentials/` outside the project, at chmod 600
- Choose a dialect for the user — you ask

## Terminal artifact

`~/.agentxp/credentials/<dialect>/<profile>.yaml` exists, the test connection succeeded.

## Banned vocabulary

The voice audit at `agentxp/render/voice_audit.py` rejects the marketing-register phrases listed in CLAUDE.md §13. The wizard narration is plain — what each field collects, what is stored where, what happens on failure.
