"""Tier-B live-warehouse tests for the BigQuery adapter (W1.B).

These hit a REAL BigQuery project and are skipped by default. They run only
when credentials are present, gated three ways so collection never errors when
the driver or creds are missing:

1. ``@pytest.mark.integration`` — excluded from the default run.
2. A module-level skip if ``google-cloud-bigquery`` is not importable.
3. A module-level skip if neither ADC (``GOOGLE_APPLICATION_CREDENTIALS`` /
   gcloud user creds) nor an explicit project env var is configured.

Configure via env vars:

* ``AGENTXP_BQ_PROJECT`` — GCP project id (required to run).
* ``GOOGLE_APPLICATION_CREDENTIALS`` — optional SA key file path (else ADC).
* ``AGENTXP_BQ_DATASET`` — optional dataset for the table-scan queries
  (defaults to BigQuery public ``bigquery-public-data.samples``).

With no creds this whole module skips cleanly — that is the expected state in
CI and on a dev box without BigQuery access.
"""
from __future__ import annotations

import importlib.util
import os

import pytest

from agentxp.sql.adapter import (
    AdapterResult,
    BytesLimitExceededError,
    PreviewResult,
)
from agentxp.sql.adapters.bigquery_adapter import BigQueryAdapter

pytestmark = pytest.mark.integration


# --- clean collection-time skips (no import/collection error) -------------

def _bigquery_importable() -> bool:
    # find_spec raises ModuleNotFoundError when a *parent* package (``google``)
    # is missing, so guard it rather than relying on a None return.
    try:
        return importlib.util.find_spec("google.cloud.bigquery") is not None
    except ModuleNotFoundError:
        return False


if not _bigquery_importable():
    pytest.skip(
        "google-cloud-bigquery not installed; skipping live BigQuery tests",
        allow_module_level=True,
    )

_BQ_PROJECT = os.environ.get("AGENTXP_BQ_PROJECT")
_HAS_CREDS = bool(
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    # ADC may also come from `gcloud auth application-default login`; we still
    # require an explicit project so the test target is unambiguous.
    or _BQ_PROJECT
)

if not (_BQ_PROJECT and _HAS_CREDS):
    pytest.skip(
        "BigQuery credentials/project not configured "
        "(set AGENTXP_BQ_PROJECT and ADC / GOOGLE_APPLICATION_CREDENTIALS); "
        "skipping live BigQuery tests",
        allow_module_level=True,
    )


# A small public table so the live matrix needs no private dataset.
_PUBLIC_TABLE = "`bigquery-public-data.samples.shakespeare`"


@pytest.fixture
def adapter():
    a = BigQueryAdapter(project=_BQ_PROJECT)
    try:
        yield a
    finally:
        a.close()


# --- the live 10-query matrix --------------------------------------------


def test_live_select_literal(adapter):
    result = adapter.execute("SELECT 1 AS x")
    assert isinstance(result, AdapterResult)
    assert result.dialect == "bigquery"
    assert result.rows[0]["x"] == 1


def test_live_select_string(adapter):
    result = adapter.execute("SELECT 'alice' AS name")
    assert result.rows[0]["name"] == "alice"


def test_live_multi_column(adapter):
    result = adapter.execute("SELECT 1 AS a, 2 AS b, 3 AS c")
    assert result.rows[0] == {"a": 1, "b": 2, "c": 3}


def test_live_public_table_scan(adapter):
    result = adapter.execute(
        f"SELECT word, word_count FROM {_PUBLIC_TABLE} "
        "ORDER BY word_count DESC LIMIT 5"
    )
    assert result.row_count == 5
    assert result.bytes_scanned is not None and result.bytes_scanned > 0


def test_live_max_rows_truncation(adapter):
    result = adapter.execute(
        f"SELECT word FROM {_PUBLIC_TABLE}", max_rows=3
    )
    assert result.row_count == 3


def test_live_aggregate(adapter):
    result = adapter.execute(
        f"SELECT COUNT(*) AS n FROM {_PUBLIC_TABLE}"
    )
    assert result.rows[0]["n"] > 0


def test_live_dry_run_estimate(adapter):
    pv = adapter.dry_run(f"SELECT * FROM {_PUBLIC_TABLE}")
    assert isinstance(pv, PreviewResult)
    assert pv.estimated_bytes_scanned is not None
    assert pv.estimated_cost_usd is not None and pv.estimated_cost_usd >= 0.0


def test_live_explain_returns_text(adapter):
    plan = adapter.explain(f"SELECT word FROM {_PUBLIC_TABLE} LIMIT 1")
    assert isinstance(plan, str)
    assert len(plan) > 0


def test_live_bytes_ceiling_rejects_over_scan():
    # A 1-byte ceiling forces BigQuery to reject the public-table scan pre-run.
    a = BigQueryAdapter(project=_BQ_PROJECT, maximum_bytes_billed=1)
    try:
        with pytest.raises(BytesLimitExceededError):
            a.execute(f"SELECT * FROM {_PUBLIC_TABLE}")
    finally:
        a.close()


def test_live_bytes_scanned_populated(adapter):
    result = adapter.execute(
        f"SELECT corpus FROM {_PUBLIC_TABLE} LIMIT 10"
    )
    assert result.bytes_scanned is not None
