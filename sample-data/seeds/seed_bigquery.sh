#!/usr/bin/env bash
# seed_bigquery.sh — load the canonical checkout_events A/B table into BigQuery.
#
# NOT EXECUTED IN THIS REPO: no BigQuery / GCP credentials are available in the
# build environment, so this script is written and syntactically validated but
# has not been run here. Run it with the `bq` CLI authenticated to your project.
# It mirrors the exact schema seeded on DuckDB (see seed_duckdb.py) so the
# Tier-B matrix sees an identical checkout_events table across warehouses.
#
# Source CSV (single source of truth): checkout_events.csv (5,000 rows).
#
# Usage:
#   PROJECT=my-gcp-project DATASET=agentxp_sample ./seed_bigquery.sh
#
# Prereqs: gcloud auth login && gcloud config set project <PROJECT>; bq installed.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT to your GCP project id}"
DATASET="${DATASET:-agentxp_sample}"
TABLE="checkout_events"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSV="${HERE}/checkout_events.csv"

# Create the dataset if it does not exist (no-op if present).
bq --project_id="${PROJECT}" mk --dataset --force "${PROJECT}:${DATASET}" || true

# Load the CSV. Schema matches the DuckDB seed exactly. assigned_at/event_ts
# are 'YYYY-MM-DD HH:MM:SS' which BigQuery parses as TIMESTAMP directly.
bq --project_id="${PROJECT}" load \
    --source_format=CSV \
    --skip_leading_rows=1 \
    --replace \
    "${PROJECT}:${DATASET}.${TABLE}" \
    "${CSV}" \
    "user_id:STRING,variant:STRING,assigned_at:TIMESTAMP,converted:INT64,revenue:FLOAT64,event_ts:TIMESTAMP"

# Sanity check: expect 5000.
bq --project_id="${PROJECT}" query --use_legacy_sql=false \
    "SELECT COUNT(*) AS row_count FROM \`${PROJECT}.${DATASET}.${TABLE}\`"
