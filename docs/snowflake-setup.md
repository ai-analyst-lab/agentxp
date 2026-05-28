# Snowflake Setup

AgentXP can pull experiment data from a Snowflake warehouse via two modes: a
direct Python connection using `snowflake-connector-python`, or MCP mode,
which defers actual query execution to the Snowflake MCP server that Claude
Code already has access to.

## Install the optional extra (direct mode only)

```bash
pip install "openxp[snowflake]"
```

MCP mode requires no extra installs — it uses the MCP tools configured in
Claude Code.

## Direct mode

Set environment variables (recommended) or pass a `connection_params` dict
explicitly.

### Environment variables

```bash
export OPENXP_SNOWFLAKE_ACCOUNT=xy12345.us-east-1
export OPENXP_SNOWFLAKE_USER=alice
export OPENXP_SNOWFLAKE_PASSWORD=***                  # or use OAuth / key pair
export OPENXP_SNOWFLAKE_WAREHOUSE=ANALYTICS_WH
export OPENXP_SNOWFLAKE_DATABASE=PROD_ANALYTICS
export OPENXP_SNOWFLAKE_SCHEMA=EXPERIMENTS
export OPENXP_SNOWFLAKE_ROLE=ANALYST                  # optional
```

Then:

```python
from openxp.data.snowflake_loader import SnowflakeLoader

with SnowflakeLoader() as loader:
    df = loader.query(
        "SELECT user_id, variant, revenue FROM experiment_results "
        "WHERE experiment_id = 'checkout-redesign-2026q1'"
    )
```

### Passing params explicitly

```python
loader = SnowflakeLoader({
    "account": "xy12345.us-east-1",
    "user": "alice",
    "password": "...",
    "warehouse": "ANALYTICS_WH",
    "database": "PROD_ANALYTICS",
    "schema": "EXPERIMENTS",
})
```

### High-level helper

```python
df = loader.load_experiment(
    table="PROD_ANALYTICS.EXPERIMENTS.checkout_redesign_results",
    treatment_col="variant",
    metric_cols=["converted", "revenue", "session_duration_ms"],
    where="assigned_at >= '2026-03-01'",
)
```

`load_experiment()` validates all identifiers against
`[A-Za-z_][A-Za-z0-9_]*` per dotted segment before building the SQL. The
`where` clause is interpolated as-is — only pass trusted static values there.

## MCP mode (inside Claude Code)

Claude Code ships with a Snowflake MCP server exposing tools such as
`mcp__snowflake__run_snowflake_query` and `mcp__snowflake__list_objects`.
When AgentXP is driven by the `/experiment` skill, the orchestrator can call
those tools directly — no Python Snowflake driver needed.

```python
from openxp.data.snowflake_loader import SnowflakeLoader

loader = SnowflakeLoader(mcp_mode=True)
df = loader.query("SELECT 1")   # returns an empty stub DataFrame + logs a notice
```

In MCP mode:

- `query()` returns an empty `pd.DataFrame` and logs a notice reminding the
  orchestrator to call the MCP tool from the skill layer.
- `_connect()` raises `RuntimeError` — direct connections are disabled.
- `load_experiment()` still validates identifiers, so you can use it to build
  the SQL safely and then hand the SQL to the MCP tool.

The intended flow inside a skill:

1. Construct a `SnowflakeLoader(mcp_mode=True)` to get identifier validation
   and SQL assembly helpers.
2. Call the Snowflake MCP tool (`mcp__snowflake__run_snowflake_query`) from
   the agent/skill layer with the assembled SQL.
3. Convert the MCP result into a DataFrame and feed it to `openxp.stats`.

## Security notes

- Credentials are never logged, printed, or echoed in exceptions. The debug
  log masks the `password`, `private_key`, `token`, and `oauth_token` fields
  before emitting any connection log line.
- Prefer environment variables or a secret manager over hard-coded params.
- Prefer key-pair authentication or OAuth over passwords in production.
- A row-count guardrail rejects queries that would return more than
  10 million rows. Pass `force=True` to `query()` to override, but only
  after confirming the query is bounded.
- `load_experiment()` validates identifiers against a strict regex. Do not
  bypass this by assembling raw SQL from user input.
- AgentXP never modifies data. Restrict the warehouse role to `SELECT` only.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ImportError: ... pip install openxp[snowflake]` | Install the optional extra. |
| `ValueError: No Snowflake connection parameters supplied` | Set `OPENXP_SNOWFLAKE_*` env vars or pass `connection_params`. |
| `ValueError: Query would return N rows, which exceeds the guardrail` | Narrow the query with a `WHERE` clause, or pass `force=True`. |
| `RuntimeError: SnowflakeLoader is in MCP mode` | You called `_connect()` in MCP mode. Use `mcp_mode=False` for direct mode. |
