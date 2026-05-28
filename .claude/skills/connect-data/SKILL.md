---
name: connect-data
description: Connect a warehouse. DuckDB, BigQuery, Snowflake, and Databricks all have working connect wizards.
---

# Skill: `/connect-data` — Warehouse Connection

## Purpose

Wire a warehouse connection so SQL dispatches can execute. All four dialects have a working `agentxp connect <dialect>` wizard that collects credentials, runs a live `SELECT 1` probe, and writes a chmod-600 credential profile under `~/.agentxp/credentials/{dialect}/{name}.yaml`:

- **DuckDB** — file-based or in-memory; no credentials.
- **BigQuery** — Application Default Credentials (ADC) or service-account JSON.
- **Snowflake** — four auth surfaces: password, externalbrowser SSO, OAuth token, key-pair.
- **Databricks** — Personal Access Token (PAT) or OAuth M2M (service principal).

This skill routes the user to the right wizard. Secrets are read with no-echo prompts, never printed back, and only ever written to the chmod-600 profile file.

## When to invoke

- `/connect-data` (no warehouse specified) — ask which warehouse the user wants
- `/connect-data duckdb` — wire a local DuckDB file or in-memory database
- `/connect-data bigquery` — run the BigQuery wizard (ADC or service account)
- `/connect-data snowflake` — run the Snowflake wizard (four auth surfaces)
- `/connect-data databricks` — run the Databricks wizard (PAT or OAuth M2M)
- Plain-English routing:
  - "Hook up my Snowflake instance" → `/connect-data snowflake`
  - "Use this DuckDB file" → `/connect-data duckdb` (with path)
  - "Point AgentXP at BigQuery" → `/connect-data bigquery`
  - "Connect my Databricks warehouse" → `/connect-data databricks`

## Arguments

```
/connect-data [warehouse] [name]
```

- `<warehouse>` — optional; one of `duckdb | bigquery | snowflake | databricks`. If omitted, ask once.
- `<name>` — profile name (e.g. `prod`, `dev`); stored as `{name}.yaml`. If omitted, default to `default` or ask.

## Workflow

Every dialect routes to its wizard via `agentxp connect <dialect> <name>`. The wizard prompts for that dialect's fields, runs a live `SELECT 1` probe, and on success writes the profile. On a failed probe nothing is written.

### Branch A: DuckDB

1. Run `agentxp connect duckdb <name>`. It prompts for a DuckDB file path, or in-memory.
2. DuckDB is file-based: no credentials, no secret persistence.
3. Suggest the next step:
   - `/profile <path>` to inspect a table
   - `/experiment --data <path>` to run a full pipeline

### Branch B: BigQuery

1. Run `agentxp connect bigquery <name>`. It prompts for the GCP project and the auth method (ADC or service-account JSON).
2. ADC is the safer default (no key material in the app). A service-account key is stored as a *path reference*; an inline JSON paste lives only in the chmod-600 profile.

### Branch C: Snowflake

1. Run `agentxp connect snowflake <name>`. It prompts for `account`, `user`, `warehouse`, `database`, `schema`, `role`, then the auth method:
   - `password` — no-echo password prompt
   - `externalbrowser` — browser SSO, no secret stored
   - `oauth` — no-echo OAuth token prompt
   - `keypair` — private-key file path plus optional passphrase (no-echo)
2. The chosen `auth_method` is stored in the profile so the adapter selects the surface directly.

### Branch D: Databricks

1. Run `agentxp connect databricks <name>`. It prompts for `server_hostname`, `http_path`, optional Unity Catalog defaults, then the auth method:
   - `pat` — no-echo Personal Access Token prompt
   - `oauth_m2m` — service-principal `client_id` plus no-echo `client_secret`
2. The chosen `auth_method` is stored in the profile.

## What this skill does not do

- It does not store secrets in the clear. Every secret is read with a no-echo prompt and only written to the chmod-600 profile; confirmation output is always redacted.
- It does not modify project state. No `state.yaml` update, no `stage.committed` event.

## Cross-references

- For DuckDB inspection after connecting: `/profile`
- For top-level orientation: `CLAUDE.md` at the repo root
- Auth-surface ground truth: `experimentation-platform/research/v0.1.1-warehouse-auth/WAREHOUSE_AUTH_BRIEF.md`
- Adapter table: Plan §12

## Example walkthrough — Snowflake

```
User: /connect-data snowflake prod

$ agentxp connect snowflake prod
Snowflake account identifier (e.g. myorg-myaccount, no domain suffix): myorg-acct
User: SVC_AGENTXP
Warehouse (e.g. WH_XS): WH_XS
Database (e.g. ANALYTICS): ANALYTICS
Schema (e.g. PUBLIC): PUBLIC
Role (optional):
Auth method (password (default), externalbrowser, oauth, keypair): password
Password:                       # no echo
  connection OK (SELECT 1 returned a row)
wrote profile: ~/.agentxp/credentials/snowflake/prod.yaml
  contents (redacted): {... 'password': '[REDACTED]'}
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

Banned patterns: throat-clearing openers; manufactured emotional beats; over-promising on auth surfaces a dialect does not support. State what each wizard collects plainly and route to the right wizard.
