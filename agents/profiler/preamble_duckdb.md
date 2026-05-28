# preamble_duckdb.md

Adapter preamble injected above `profiler.system.md` when the active adapter is DuckDB.

## Where the data lives

The dataset is a local file. The `source_ref` you receive is a file path on the user's machine — typically a `.parquet`, `.csv`, `.json`, or `.jsonl`. There is no warehouse, no role, no project, no dataset. Just rows in a file that DuckDB reads on demand.

The orchestrator has already strpped the user's home directory from the path before injecting it into the conversation. You will see `~/data/checkout_test_pull.parquet`, not `/Users/<name>/data/checkout_test_pull.parquet`. Echo it back as `~/...` in your output. Do not reconstruct the absolute path.

## How SUMMARIZE was run

The orchestrator executed one of:

```python
duckdb.execute("SUMMARIZE SELECT * FROM read_parquet(?)", [path])
duckdb.execute("SUMMARIZE SELECT * FROM read_csv_auto(?)", [path])
duckdb.execute("SUMMARIZE SELECT * FROM read_json_auto(?)", [path])
```

The rows you see in the SUMMARIZE output are the canonical schema. Column names are exactly what the file produced — for parquet that's preserved case, for CSV that's whatever the header row had. Trust the names verbatim.

## What's missing vs warehouse adapters

There is no:

- Role or permission context — DuckDB runs in-process under the user's local file permissions.
- Project / dataset / database / schema namespace — there is only a path.
- Query cost or byte-scan estimate — local file reads are not billed.
- Re-auth flow — if the file isn't readable, the orchestrator fails before you run.

Do not surface cost, role, or auth context in your output for DuckDB sessions. There is none.

## DuckDB type quirks to know

- DuckDB infers `TIMESTAMP` (no timezone) by default. If the file has both `TIMESTAMPTZ` and `TIMESTAMP` columns, the mixed-format check in §6 applies — flag it.
- `read_csv_auto` may guess a column type wrong on small samples. If a sample value looks like a number but the type is `VARCHAR`, mention it once in "things noticed."
- Parquet preserves `DECIMAL(p,s)` precisely. You'll see `decimal(18,2)` etc. — treat as float for profiling purposes.
- JSON files may produce nested `STRUCT` columns. Collapse to `parent.child` notation in the column table.

## File path handling

In your output:

- Use `~/...` form. Never the absolute path.
- Truncate paths longer than 60 characters with `.../` in the middle: `~/data/.../checkout_test_pull.parquet`.
- The `read:` line uses the abbreviated form.
- Do not include the file size in bytes. The row count from SUMMARIZE is enough.
