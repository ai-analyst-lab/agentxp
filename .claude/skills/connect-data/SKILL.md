---
name: connect-data
description: Connect a warehouse. DuckDB ships v0.1; Snowflake and BigQuery wizards ship v0.1.1.
---

# Skill: `/connect-data` — Warehouse Connection

## Purpose

Wire a warehouse connection so SQL dispatches can execute. v0.1 ships only DuckDB (file-based or in-memory). Snowflake and BigQuery adapters exist as stubs at `openxp/sql/adapters/` that raise `NotImplementedError`; the connect wizards (`agentxp connect snowflake|bigquery`) ship in v0.1.1 within two weeks of v0.1 ship. This skill makes that boundary explicit and routes users who need Snowflake or BigQuery today toward workable v0.1 paths instead of failing into a stub.

## When to invoke

- `/connect-data` (no warehouse specified) — ask which warehouse the user wants
- `/connect-data duckdb` — wire a local DuckDB file or in-memory database
- `/connect-data snowflake` — print the v0.1.1 deferral message and route to DuckDB
- `/connect-data bigquery` — same as Snowflake: deferral message plus DuckDB route
- Plain-English routing:
  - "Hook up my Snowflake instance" → `/connect-data snowflake`
  - "Use this DuckDB file" → `/connect-data duckdb` (with path)
  - "Point AgentXP at BigQuery" → `/connect-data bigquery`

## Arguments

```
/connect-data [warehouse] [path]
```

- `<warehouse>` — optional; one of `duckdb | snowflake | bigquery`. If omitted, ask once.
- `<path>` — DuckDB only; file path or `:memory:`. If omitted on the DuckDB branch, ask.

## Workflow

### Branch A: DuckDB (ships v0.1)

1. Prompt for a path to a DuckDB file, or `:memory:` for an in-memory database.
2. If a file path was given, confirm the file exists on disk. If it does not, print `file not found: <path>` to stderr and exit.
3. Note that DuckDB is file-based: no credentials, no credential persistence.
4. Suggest the immediate next step:
   - `/profile <path>` to inspect a table
   - `/experiment --data <path>` to run a full pipeline

### Branch B: Snowflake or BigQuery (ships v0.1.1)

1. Print the deferral message verbatim:

   ```
   Snowflake and BigQuery connect wizards ship in v0.1.1 within two weeks of
   v0.1. The Snowflake adapter has four auth surfaces (password, externalbrowser
   SSO, OAuth, key-pair); the BigQuery adapter uses ADC or service account JSON.
   Both adapters' Python stubs already exist at openxp/sql/adapters/, but they
   raise NotImplementedError until v0.1.1.
   ```

2. Offer the v0.1 workable paths:

   ```
   For v0.1 today, you can:
   - Point at a local DuckDB file: /connect-data duckdb
   - Export a Snowflake/BigQuery table to parquet and run /profile on it
   - Wait two weeks for the v0.1.1 release
   ```

3. Ask which path the user wants and exit.

## What this skill does not do

- It does not dispatch the Snowflake or BigQuery adapter. Those stubs raise `NotImplementedError`; surfacing that error is a worse experience than the explicit deferral message.
- It does not write credentials. Credential persistence at `.openxp/credentials/` is a v0.1.1 deliverable shipped alongside the wizards.
- It does not modify project state. No `state.yaml` update, no `stage.committed` event.

## Cross-references

- For DuckDB inspection after connecting: `/profile`
- For top-level orientation: `CLAUDE.md` at the repo root
- v0.1.1 deliverables list: `experimentation-platform/BUILD_OUTCOMES_v0.1.md`
- Adapter table: Plan §12

## Example walkthrough — Snowflake (deferred)

```
User: /connect-data snowflake

Snowflake and BigQuery connect wizards ship in v0.1.1 within two weeks
of v0.1. The Snowflake adapter has four auth surfaces (password,
externalbrowser SSO, OAuth, key-pair); the BigQuery adapter uses ADC
or service account JSON. Both adapters' Python stubs already exist at
openxp/sql/adapters/, but they raise NotImplementedError until v0.1.1.

For v0.1 today, you can:
- Point at a local DuckDB file: /connect-data duckdb
- Export a Snowflake table to parquet and run /profile on it
- Wait two weeks for the v0.1.1 release

Which do you want to do?
```

## Banned vocabulary

The output produced by this skill must avoid the tokens below. These mirror the standard list and are treated as syntax errors.

- `leverage`
- `powerful`
- `delightful`
- `robust`
- `seamless`
- `cutting-edge`
- `great question`
- `excellent observation`
- `we're excited`
- `successfully` (as a self-congratulatory adverb)
- `Let me walk you through`
- `Before we begin, let me explain`
- `co-pilot`
- `colleague`

Banned patterns: throat-clearing openers; manufactured emotional beats; framing the deferral as anything other than what it is. State the v0.1.1 boundary plainly and route to the workable path.
