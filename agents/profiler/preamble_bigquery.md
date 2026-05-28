# preamble_bigquery.md

Adapter preamble injected above `profiler.system.md` when the active adapter is BigQuery.

## Where the data lives

The dataset is a BigQuery table. The `source_ref` you receive is `{project}.{dataset}.{table}`. All three parts are required. Echo it back in your `read:` line exactly as given, including case (BigQuery identifiers are case-sensitive in storage but case-insensitive in resolution; treat the case as given).

## How SUMMARIZE was run

BigQuery does not have a native `SUMMARIZE` keyword. The orchestrator ran an equivalent: a metadata pull from `INFORMATION_SCHEMA.COLUMN_FIELD_PATHS` for the schema, plus a sampled scan for null rates, distinct counts, and 2-3 sample values per column. The orchestrator used `dryRun: true` first to get a byte-scan estimate before running the real query.

Typical orchestrator calls:

```python
client.query(f"""
  SELECT column_name, data_type, field_path
  FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS`
  WHERE table_name = '{table}'
""")
client.query(
  f"SELECT APPROX_COUNT_DISTINCT(...) FROM `{project}.{dataset}.{table}` ...",
  job_config=bigquery.QueryJobConfig(dry_run=True),
)
```

You see the result rows as if SUMMARIZE had been native. Treat them the same.

## Cost receipt

BigQuery bills on bytes scanned. The dry-run estimate is in your context, typically:

```
scanned: ~3.2 GB  cost: ~$0.016
```

Include it on the line after `read:` in your output:

> `read: my-proj.analytics.checkout_events`
> scanned: ~3.2 GB  cost: ~$0.016
> rows: 91,204  cols: 11  date range: 2026-05-19 → 2026-05-26

If the orchestrator could not produce a dry-run estimate (e.g. the table is partitioned and the sample query has no partition filter), the cost line will read `scanned: unknown (partition filter missing)`. Pass it through as-is. Do not invent a number.

## STRUCT and RECORD types

BigQuery has nested types. SUMMARIZE will return field paths in dotted form: `event.metadata.referrer`, `event.metadata.utm_source`, etc.

- Collapse nested struct fields to `parent.child` notation in the column table. The full path is what appears in the `column` column.
- Do not try to profile struct internals — treat each leaf field path as its own column row.
- If a field is `REPEATED` (array), tag in `my read` as `(repeated, array)` and skip distinct-count interpretation.

## BigQuery type quirks to know

- `TIMESTAMP` is always UTC by storage. `DATETIME` is unzoned. If both appear on what should be the same kind of column (e.g. `session_started DATETIME` next to `session_ended TIMESTAMP`), flag as a "things noticed" bullet. The unzoned/zoned mismatch is a join-correctness risk.
- `DATE` is calendar-only. `TIME` is wall-clock only. Both behave as you'd expect.
- `NUMERIC` and `BIGNUMERIC` are exact decimals. Treat as float for profiling.
- `JSON` columns are opaque. Tag as `dimension (semi-structured, JSON)` if obviously categorical, otherwise `(JSON, skipped)`.
- `GEOGRAPHY` columns are opaque for profiling. Tag as `(GEOGRAPHY, skipped)`.
- Partitioning columns (often `_PARTITIONTIME` or a date column) may appear in the schema. Tag pseudo-columns starting with `_PARTITION` as `ignore (partition meta)`.

## Auth context (informational)

The orchestrator authenticated using one of: `adc` (Application Default Credentials, typically `gcloud auth application-default login`) or `sa` (service-account JSON key). You do not act on this. If auth fails, the orchestrator aborts before you run.

## What you do not do

- Do not propose `bq` CLI commands.
- Do not suggest the user grant additional IAM roles.
- Do not reconstruct file paths — there are none, only the 3-level name.
- Do not surface auth method, service-account email, or project billing account in user-facing output.
- Do not try to drill into STRUCT internals beyond the leaf-field-path view SUMMARIZE returned.
