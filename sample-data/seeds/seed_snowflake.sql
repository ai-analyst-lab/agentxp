-- seed_snowflake.sql — load the canonical checkout_events A/B table into Snowflake.
--
-- NOT EXECUTED IN THIS REPO: no Snowflake credentials are available in the
-- build environment, so this script is written and syntactically validated but
-- has not been run here. Run it via SnowSQL:  snowsql -f seed_snowflake.sql
-- It mirrors the exact schema seeded on DuckDB (see seed_duckdb.py) so the
-- Tier-B matrix sees an identical checkout_events table across warehouses.
--
-- Source CSV (single source of truth): checkout_events.csv (5,000 rows).
-- Adjust the database/schema/warehouse names to your account before running.

USE WAREHOUSE COMPUTE_WH;
CREATE DATABASE IF NOT EXISTS AGENTXP;
USE DATABASE AGENTXP;
CREATE SCHEMA IF NOT EXISTS SAMPLE;
USE SCHEMA SAMPLE;

CREATE OR REPLACE TABLE checkout_events (
    user_id      STRING     NOT NULL,
    variant      STRING     NOT NULL,   -- 'control' | 'treatment'
    assigned_at  TIMESTAMP_NTZ NOT NULL,
    converted    NUMBER(1,0) NOT NULL,  -- 0 | 1
    revenue      FLOAT      NOT NULL,    -- USD, 0.0 if not converted
    event_ts     TIMESTAMP_NTZ NOT NULL
);

-- File format: comma-delimited, one header row, double-quote optional.
CREATE OR REPLACE FILE FORMAT agentxp_csv
    TYPE = CSV
    FIELD_DELIMITER = ','
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    NULL_IF = ('', 'NULL')
    TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS';

-- Internal named stage to receive the local CSV.
CREATE OR REPLACE STAGE agentxp_stage FILE_FORMAT = agentxp_csv;

-- Upload the local CSV to the stage. PUT runs client-side (SnowSQL); the path
-- below assumes you invoke snowsql from sample-data/seeds/.
PUT file://checkout_events.csv @agentxp_stage AUTO_COMPRESS=TRUE OVERWRITE=TRUE;

-- Load staged data into the table.
COPY INTO checkout_events
    FROM @agentxp_stage/checkout_events.csv.gz
    FILE_FORMAT = (FORMAT_NAME = agentxp_csv)
    ON_ERROR = 'ABORT_STATEMENT';

-- Sanity check: expect 5000.
SELECT COUNT(*) AS row_count FROM checkout_events;
