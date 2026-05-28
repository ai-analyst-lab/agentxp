-- seed_databricks.sql — load the canonical checkout_events A/B table into Databricks.
--
-- NOT EXECUTED IN THIS REPO: no Databricks workspace / credentials are available
-- in the build environment, so this script is written and syntactically
-- validated but has not been run here. Run it in a Databricks SQL editor or
-- via the Databricks SQL CLI / `dbsqlcli -e`. It mirrors the exact schema
-- seeded on DuckDB (see seed_duckdb.py) so the Tier-B matrix sees an identical
-- checkout_events table across warehouses.
--
-- Source CSV (single source of truth): checkout_events.csv (5,000 rows).
--
-- This uses COPY INTO from a volume/cloud path. Upload checkout_events.csv to
-- the volume path below first (Databricks UI, `databricks fs cp`, or PUT), then
-- run this script. Edit the catalog / schema / volume path for your workspace.

CREATE CATALOG IF NOT EXISTS agentxp;
CREATE SCHEMA IF NOT EXISTS agentxp.sample;
USE CATALOG agentxp;
USE SCHEMA sample;

CREATE TABLE IF NOT EXISTS checkout_events (
    user_id      STRING    NOT NULL,
    variant      STRING    NOT NULL,   -- 'control' | 'treatment'
    assigned_at  TIMESTAMP NOT NULL,
    converted    INT       NOT NULL,   -- 0 | 1
    revenue      DOUBLE    NOT NULL,   -- USD, 0.0 if not converted
    event_ts     TIMESTAMP NOT NULL
);

-- Idempotent reload: clear any existing rows before COPY INTO.
TRUNCATE TABLE checkout_events;

-- Load from a Unity Catalog volume. Replace the path with where you uploaded
-- checkout_events.csv (e.g. /Volumes/agentxp/sample/seeds/).
COPY INTO checkout_events
FROM '/Volumes/agentxp/sample/seeds/checkout_events.csv'
FILEFORMAT = CSV
FORMAT_OPTIONS (
    'header' = 'true',
    'inferSchema' = 'false',
    'timestampFormat' = 'yyyy-MM-dd HH:mm:ss'
)
COPY_OPTIONS ('mergeSchema' = 'false');

-- Sanity check: expect 5000.
SELECT COUNT(*) AS row_count FROM checkout_events;
