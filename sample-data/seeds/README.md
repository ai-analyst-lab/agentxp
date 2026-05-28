# Warehouse seed scripts — `checkout_events`

Reproducible seeds that build an identical `checkout_events` A/B-test table on
each supported warehouse, so the Tier-B cross-warehouse adapter matrix can
query a **known, identical** table everywhere.

## Single source of truth

`checkout_events.csv` (5,000 rows) is the one source of truth. Every seed
script loads this same CSV. Regenerate it deterministically with:

```
.venv/bin/python sample-data/seeds/generate_checkout_events.py
```

(Fixed RNG seed → byte-stable output. It's a clean, balanced A/B test with a
real positive treatment effect: control ≈ 12% conversion, treatment ≈ 15.5%.)

## Table schema

| Column        | Type (canonical) | Notes |
|---------------|------------------|-------|
| `user_id`     | STRING/VARCHAR   | Unique user id, `u000000`… |
| `variant`     | STRING/VARCHAR   | `control` or `treatment` |
| `assigned_at` | TIMESTAMP        | When the user entered the experiment |
| `converted`   | INT              | `0` / `1` — completed checkout |
| `revenue`     | DOUBLE/FLOAT     | USD; `0.0` when not converted |
| `event_ts`    | TIMESTAMP        | Last checkout-flow event for the user |

Each warehouse seed maps these to its idiomatic types (see each file's DDL).

## Seeds

| Warehouse  | File                  | Runnable here? | Load mechanism |
|------------|-----------------------|----------------|----------------|
| DuckDB     | `seed_duckdb.py`      | **Yes** (run as part of build) | `read_csv_auto` |
| Snowflake  | `seed_snowflake.sql`  | No (no creds)  | `PUT` + `COPY INTO` |
| BigQuery   | `seed_bigquery.sh`    | No (no creds)  | `bq load` |
| Databricks | `seed_databricks.sql` | No (no creds)  | `COPY INTO` from volume |

Only DuckDB is installed in this repo's venv, so only `seed_duckdb.py` is
executed during the build (it asserts the loaded row count equals the CSV row
count). The three cloud seeds are written and syntactically validated but
cannot be executed without credentials — each says so in its header comment.

### Run the DuckDB seed

```
.venv/bin/python sample-data/seeds/seed_duckdb.py [out.duckdb]
```

Default output is `checkout_events.duckdb` (a binary; not committed). Pass a
path under `/tmp` to keep the working tree clean.

### Cloud seeds

See each file's header for prerequisites. Snowflake: `snowsql -f
seed_snowflake.sql`. BigQuery: `PROJECT=... DATASET=... ./seed_bigquery.sh`.
Databricks: upload the CSV to a Unity Catalog volume, then run the SQL.
