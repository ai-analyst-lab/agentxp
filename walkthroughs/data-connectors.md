# Data Connectors

OpenXP is data-agnostic. It loads experiment data from wherever you keep it — CSVs on disk, a DuckDB warehouse, or a live Snowflake connection — and discovers the schema on the fly.

## The Principle: Data-Agnostic

No agent, skill, or stats function in OpenXP references a specific column name, dataset, or file path. Everything is discovered at runtime from whatever data you hand it.

That's why `/experiment analyze foo.csv` works on any CSV, not just the sample data. The discovery layer inspects the first few rows, matches column names against a hint list, falls back to structural detection, and returns a `SchemaDiscovery` object with the treatment column, control value, metric columns, segments, and timestamps — each tagged with a confidence level.

If discovery is confident, analysis proceeds. If not, you're asked to disambiguate. Nothing is ever silently guessed.

## CSV: the Default

```python
from openxp.data.csv_loader import CSVLoader

loader = CSVLoader()
result = loader.load("sample-data/clean_ab.csv")

df = result.dataframe
print(result.interpretation)
# "Loaded 10,000 rows x 6 columns from CSV 'sample-data/clean_ab.csv'."
```

The loader has built-in row-count guards (PRD §5.20):

| Rows | Behavior |
|------|----------|
| < 100K | Load directly, no warnings |
| 100K – 1M | Load + warn "DuckDB will be faster" |
| 1M – 10M | Load + stronger warning about memory |
| > 10M | **Block** unless `force=True` |

For the blocked case, the error message tells you what to do: switch to DuckDB, or pass `force=True` if you know what you're doing.

```python
# Streaming for memory-constrained environments
loader = CSVLoader()
for chunk in loader.stream("big_experiment.csv", chunk_size=100_000):
    process(chunk)
```

## DuckDB: the Scale Answer

For datasets over a million rows, or when you want to keep the data in a persistent analytical database, use DuckDB:

```python
from openxp.data.duckdb_loader import DuckDBLoader

with DuckDBLoader() as loader:
    loader.connect(":memory:")
    loader.load_csv_as_table("sample-data/clean_ab.csv", "exp")

    # Run any SQL you want
    summary = loader.query("""
        SELECT variant, COUNT(*) as n, AVG(revenue) as avg_revenue
        FROM exp
        GROUP BY variant
    """)

    # Or load the whole experiment table for downstream analysis
    result = loader.load_experiment("exp", treatment_col="variant")
    df = result.dataframe
```

DuckDB is an optional dependency. Install it with `pip install 'openxp[duckdb]'`. If it's missing, importing the loader still works; instantiating it fails with a pointer to the install command.

DuckDB can also point at a persistent file:

```python
loader.connect("/path/to/warehouse.duckdb")
```

## Snowflake: MCP + Direct

Snowflake has two modes. Both respect a 10M-row guardrail on unbounded queries.

### Direct mode

Uses `snowflake-connector-python` (optional extra: `pip install 'openxp[snowflake]'`). Credentials come from `connection_params` or `OPENXP_SNOWFLAKE_*` environment variables.

```python
from openxp.data.snowflake_loader import SnowflakeLoader

with SnowflakeLoader() as loader:
    df = loader.query("""
        SELECT user_id, variant, revenue, segment
        FROM analytics.experiments.checkout_redesign
        WHERE exposure_date BETWEEN '2026-03-01' AND '2026-03-14'
    """)
```

Or use the high-level helper with identifier validation:

```python
df = loader.load_experiment(
    table="analytics.experiments.checkout_redesign",
    treatment_col="variant",
    metric_cols=["revenue", "checkout_completion"],
    where="exposure_date >= '2026-03-01'",
)
```

Identifiers are validated against `[A-Za-z_][A-Za-z0-9_]*` to block SQL injection through table/column names. The `where` clause is passed through verbatim — only use trusted static values there.

### MCP mode (inside Claude Code)

When you're running `/experiment analyze` inside Claude Code, OpenXP prefers the Snowflake MCP server over direct connections — the credentials live in the Claude Code config, not the Python process.

```python
loader = SnowflakeLoader(mcp_mode=True)
# loader.query() returns an empty stub; the skill calls
# mcp__snowflake__run_snowflake_query itself and passes results back.
```

In MCP mode, `query()` intentionally doesn't execute. The orchestrator skill calls the Snowflake MCP tool and injects the resulting DataFrame into OpenXP's analysis path.

## Schema Discovery

Given a DataFrame, `discover_schema` returns a `SchemaDiscovery` with every field the rest of OpenXP needs.

```python
from openxp.data.discovery import discover_schema

schema = discover_schema(df)
print(schema.treatment_column)    # 'variant'
print(schema.control_value)       # 'control'
print(schema.metric_columns)      # ['revenue', 'session_duration']
print(schema.segment_columns)     # ['plan_tier', 'region']
print(schema.confidence)          # {'treatment_column': 'high', ...}
print(schema.needs_disambiguation)  # list of questions to ask the user
print(schema.interpretation)
# "Discovered schema for 10,000-row dataset: treatment column 'variant'
#  (control='control', treatment=['treatment']); 2 metric column(s): ['revenue',
#  'session_duration']; 2 segment column(s): ['plan_tier', 'region']."
```

The detection rules (7 steps, all in the discovery module):

1. Treatment column from hint names (`variant`, `group`, `treatment`, `arm`, `bucket`...) or structural fallback (low-cardinality non-numeric, 2-5 uniques)
2. Control value from common labels (`control`, `ctrl`, `baseline`, `0`, `a`)
3. Treatment values = everything else in the treatment column
4. Metric columns = numeric, non-id
5. Segment columns = 2-20 unique values, non-id, non-treatment
6. Timestamp columns = datetime dtype OR parseable by name pattern
7. Everything uncertain goes in `needs_disambiguation`

## Gotchas

- **Ambiguous treatment column.** If two columns both look variant-like (e.g., you have both `variant` and `experiment_group`), `confidence["treatment_column"]` comes back `"low"` and a disambiguation question is queued. Pick one explicitly before analysis.
- **Numeric variant labels.** A column of 0/1 where 0 is control works fine. But `variant` = {0, 1, 2, 3} will be detected as a metric column, not the treatment column. Rename or cast to string first.
- **Id-like columns.** Anything with `id`, `uuid`, `user`, `session`, `device`, or `account` in its name is excluded from metric and segment candidates. Rename your metric column if it unfortunately contains the word "user".
- **Snowflake in MCP mode.** `query()` returns an empty DataFrame by design. If you're confused why nothing is analyzing, check `mcp_mode`.
- **Row-count guards are real.** A 12M-row CSV fails loudly. Use DuckDB or pass `force=True` after you've thought about memory.

## See Also

- `your-first-experiment.md` — the end-to-end flow that uses these loaders
- PRD §5.5, §5.13 (Data discovery and loading)
- `docs/snowflake-setup.md` for credential setup
