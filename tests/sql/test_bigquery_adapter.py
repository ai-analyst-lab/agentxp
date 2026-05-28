"""Tier-A (always-on, NO network) tests for the BigQuery adapter (W1.B).

Patches the ``google.cloud.bigquery`` + ``google.oauth2.service_account``
import boundaries with in-process fakes so these run green whether or not
``google-cloud-bigquery`` is installed in the venv. Covers:

* the two auth surfaces build the correct client (ADC vs service-account JSON
  — both path and inline dict);
* ``AdapterResult`` shape + ``dialect="bigquery"`` + ``bytes_scanned`` from
  ``total_bytes_processed``;
* dry-run cost math (bytes → ``estimated_cost_usd`` at the on-demand rate);
* a ``maximum_bytes_billed`` rejection → :class:`BytesLimitExceededError`;
* auth error → :class:`AuthExpiredError`; job timeout → :class:`QueryTimeoutError`;
* conformance to :class:`BaseAdapter` via the W0 harness;
* the credential-leakage bar (clones the SE-001 / DE-019 redaction pattern):
  a planted service-account ``private_key`` never reaches ``caplog`` or any
  raised exception.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from agentxp.sql.adapter import (
    AdapterError,
    AdapterResult,
    AuthExpiredError,
    BaseAdapter,
    BytesLimitExceededError,
    PreviewResult,
    QueryTimeoutError,
)
from agentxp.sql.adapters.bigquery_adapter import (
    _BYTES_PER_TIB,
    _ON_DEMAND_USD_PER_TIB,
    BigQueryAdapter,
)
from tests.sql._adapter_contract import (
    assert_conforms_to_base_adapter,
    make_adapter,
)


# ----------------------------------------------------------------------
# In-process fake of google-cloud-bigquery (no driver install, no network)
# ----------------------------------------------------------------------


# The adapter maps driver exceptions by CLASS NAME (it does not hard-import the
# google packages). So these fakes deliberately use the exact class names the
# real driver raises: google.api_core.exceptions.{Forbidden,BadRequest,Unauthorized}.
class Forbidden(Exception):
    """Stand-in for google.api_core.exceptions.Forbidden (403)."""


class BadRequest(Exception):
    """Stand-in for google.api_core.exceptions.BadRequest (400)."""


class Unauthorized(Exception):
    """Stand-in for google.api_core.exceptions.Unauthorized (401)."""


class _FakeRow(dict):
    """BigQuery Row is mapping-like; dict(row) yields {col: value}."""


class _FakeQueryJob:
    def __init__(self, client: "_FakeClient", sql: str, job_config: Any):
        self._client = client
        self._sql = sql
        self._job_config = job_config
        self.total_bytes_processed = client.total_bytes_processed

    def result(self, timeout: Any = None, max_results: Any = None):
        behavior = self._client.result_behavior
        if behavior == "timeout":
            raise TimeoutError("job exceeded job_timeout_ms")
        if behavior == "bytes_limit":
            raise Forbidden(
                "Query exceeded limit for bytes billed: 1000000. "
                "reason=bytesBilledLimitExceeded"
            )
        if behavior == "auth":
            raise Unauthorized("Request had invalid authentication credentials.")
        if behavior == "boom":
            raise BadRequest(
                getattr(self._client, "boom_message", "Syntax error: unexpected token")
            )
        rows = [_FakeRow({"x": 1, "name": "alice"})]
        return rows


class _FakeClient:
    def __init__(self, project: Any = None, credentials: Any = None):
        self.project = project
        self.credentials = credentials
        self.closed = False
        # Tunable behavior set by the fixture / per-test.
        self.total_bytes_processed = 4096
        self.result_behavior = "ok"      # ok|timeout|bytes_limit|auth|boom
        self.query_behavior = "ok"       # ok|bytes_limit|auth|boom (at submit time)
        self.boom_message = "Syntax error"  # custom "boom" message (BLOCKER-1)
        self.last_query: tuple[str, Any] | None = None

    def query(self, sql: str, job_config: Any = None):
        self.last_query = (sql, job_config)
        if self.query_behavior == "bytes_limit":
            raise Forbidden(
                "Query exceeded limit for bytes billed. "
                "reason=bytesBilledLimitExceeded"
            )
        if self.query_behavior == "auth":
            raise Unauthorized("invalid authentication credentials")
        if self.query_behavior == "boom":
            raise BadRequest(self.boom_message)
        return _FakeQueryJob(self, sql, job_config)

    def close(self):
        self.closed = True


class _FakeQueryJobConfig:
    """Captures kwargs the adapter sets (dry_run, maximum_bytes_billed, ...)."""

    def __init__(self, **kwargs: Any):
        self.dry_run = kwargs.get("dry_run", False)
        self.use_query_cache = kwargs.get("use_query_cache", None)
        self.job_timeout_ms = kwargs.get("job_timeout_ms", None)
        self.maximum_bytes_billed = kwargs.get("maximum_bytes_billed", None)


class _FakeBigQueryModule(types.ModuleType):
    """Fake ``google.cloud.bigquery`` exposing Client + QueryJobConfig."""

    def __init__(self):
        super().__init__("google.cloud.bigquery")
        self.last_client: _FakeClient | None = None
        self.client_behavior = "ok"  # ok|auth|boom — at Client() construction
        self.QueryJobConfig = _FakeQueryJobConfig

    def Client(self, project: Any = None, credentials: Any = None):
        if self.client_behavior == "auth":
            raise Unauthorized("ADC could not be refreshed")
        if self.client_behavior == "boom":
            raise BadRequest("bad client config")
        c = _FakeClient(project=project, credentials=credentials)
        c.result_behavior = self.result_behavior
        c.query_behavior = self.query_behavior
        c.total_bytes_processed = self.total_bytes_processed
        c.boom_message = self.boom_message
        self.last_client = c
        return c

    # Behavior knobs propagated onto each constructed client.
    result_behavior = "ok"
    query_behavior = "ok"
    total_bytes_processed = 4096
    boom_message = "Syntax error"


class _FakeCredentials:
    def __init__(self, source: Any, kind: str):
        self.source = source
        self.kind = kind
        self.project_id = "sa-project"


class _FakeServiceAccountModule(types.ModuleType):
    """Fake ``google.oauth2.service_account`` with the Credentials factory."""

    def __init__(self):
        super().__init__("google.oauth2.service_account")
        self.last_from_file: Any = None
        self.last_from_info: Any = None

        class _Credentials:
            @staticmethod
            def from_service_account_file(path, scopes=None):
                mod.last_from_file = (path, scopes)
                return _FakeCredentials(path, "file")

            @staticmethod
            def from_service_account_info(info, scopes=None):
                mod.last_from_info = (info, scopes)
                return _FakeCredentials(info, "info")

        mod = self
        self.Credentials = _Credentials


@pytest.fixture
def fake_bq(monkeypatch):
    """Install fake google.cloud.bigquery + google.oauth2.service_account."""
    google_pkg = types.ModuleType("google")
    cloud_pkg = types.ModuleType("google.cloud")
    oauth2_pkg = types.ModuleType("google.oauth2")
    bq_mod = _FakeBigQueryModule()
    sa_mod = _FakeServiceAccountModule()

    google_pkg.cloud = cloud_pkg  # type: ignore[attr-defined]
    google_pkg.oauth2 = oauth2_pkg  # type: ignore[attr-defined]
    cloud_pkg.bigquery = bq_mod  # type: ignore[attr-defined]
    oauth2_pkg.service_account = sa_mod  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_pkg)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", bq_mod)
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2_pkg)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", sa_mod)
    return types.SimpleNamespace(bigquery=bq_mod, service_account=sa_mod)


# ----------------------------------------------------------------------
# Auth surface → client construction
# ----------------------------------------------------------------------


def test_adc_auth_builds_default_client(fake_bq):
    adapter = BigQueryAdapter(project="my-gcp-project")
    adapter.execute("SELECT 1")
    client = fake_bq.bigquery.last_client
    assert client is not None
    assert client.project == "my-gcp-project"
    # ADC path: no explicit credentials object handed to Client.
    assert client.credentials is None
    # No SA factory was invoked.
    assert fake_bq.service_account.last_from_file is None
    assert fake_bq.service_account.last_from_info is None
    adapter.close()


def test_service_account_file_builds_client_with_creds(fake_bq):
    adapter = BigQueryAdapter(
        project="my-proj", credentials_path="/path/to/key.json"
    )
    adapter.execute("SELECT 1")
    assert fake_bq.service_account.last_from_file[0] == "/path/to/key.json"
    client = fake_bq.bigquery.last_client
    assert client.credentials is not None
    assert client.credentials.kind == "file"
    adapter.close()


def test_service_account_inline_dict_builds_client_with_creds(fake_bq):
    sa_info = {"type": "service_account", "private_key": "x", "project_id": "p"}
    adapter = BigQueryAdapter(project="my-proj", credentials_info=sa_info)
    adapter.execute("SELECT 1")
    assert fake_bq.service_account.last_from_info[0] == sa_info
    client = fake_bq.bigquery.last_client
    assert client.credentials is not None
    assert client.credentials.kind == "info"
    adapter.close()


def test_no_network_at_construction(fake_bq):
    BigQueryAdapter(project="p")
    assert fake_bq.bigquery.last_client is None


# ----------------------------------------------------------------------
# execute / result shape / dialect / bytes_scanned
# ----------------------------------------------------------------------


def test_execute_returns_adapter_result_shape(fake_bq):
    adapter = BigQueryAdapter(project="p")
    result = adapter.execute("SELECT 1 AS x, 'alice' AS name")
    assert isinstance(result, AdapterResult)
    assert result.dialect == "bigquery"
    assert result.row_count == 1
    assert result.rows == [{"x": 1, "name": "alice"}]
    assert result.bytes_scanned == 4096
    assert result.elapsed_seconds >= 0.0
    adapter.close()


def test_bytes_scanned_from_total_bytes_processed(fake_bq):
    fake_bq.bigquery.total_bytes_processed = 123_456_789
    adapter = BigQueryAdapter(project="p")
    result = adapter.execute("SELECT 1")
    assert result.bytes_scanned == 123_456_789
    adapter.close()


def test_job_timeout_ms_set_from_timeout_s(fake_bq):
    adapter = BigQueryAdapter(project="p")
    adapter.execute("SELECT 1", timeout_s=45)
    _, job_config = fake_bq.bigquery.last_client.last_query
    assert job_config.job_timeout_ms == 45_000
    adapter.close()


def test_maximum_bytes_billed_passed_when_ceiling_set(fake_bq):
    adapter = BigQueryAdapter(project="p", maximum_bytes_billed=5 * 10**9)
    adapter.execute("SELECT 1")
    _, job_config = fake_bq.bigquery.last_client.last_query
    assert job_config.maximum_bytes_billed == 5 * 10**9
    adapter.close()


# ----------------------------------------------------------------------
# error mapping
# ----------------------------------------------------------------------


def test_bytes_limit_rejection_maps_to_bytes_limit_error(fake_bq):
    fake_bq.bigquery.result_behavior = "bytes_limit"
    adapter = BigQueryAdapter(project="p", maximum_bytes_billed=1_000_000)
    with pytest.raises(BytesLimitExceededError):
        adapter.execute("SELECT * FROM huge")
    adapter.close()


def test_bytes_limit_at_submit_maps_to_bytes_limit_error(fake_bq):
    fake_bq.bigquery.query_behavior = "bytes_limit"
    adapter = BigQueryAdapter(project="p", maximum_bytes_billed=1_000_000)
    with pytest.raises(BytesLimitExceededError):
        adapter.execute("SELECT * FROM huge")
    adapter.close()


def test_auth_error_maps_to_auth_expired(fake_bq):
    fake_bq.bigquery.query_behavior = "auth"
    adapter = BigQueryAdapter(project="p")
    with pytest.raises(AuthExpiredError):
        adapter.execute("SELECT 1")
    adapter.close()


def test_client_construction_auth_error_maps_to_auth_expired(fake_bq):
    fake_bq.bigquery.client_behavior = "auth"
    adapter = BigQueryAdapter(project="p")
    with pytest.raises(AuthExpiredError):
        adapter.execute("SELECT 1")


def test_timeout_maps_to_query_timeout_error(fake_bq):
    fake_bq.bigquery.result_behavior = "timeout"
    adapter = BigQueryAdapter(project="p")
    with pytest.raises(QueryTimeoutError):
        adapter.execute("SELECT 1")
    adapter.close()


def test_generic_error_maps_to_adapter_error(fake_bq):
    fake_bq.bigquery.query_behavior = "boom"
    adapter = BigQueryAdapter(project="p")
    with pytest.raises(AdapterError):
        adapter.execute("SELECT bad")
    adapter.close()


# ----------------------------------------------------------------------
# dry_run cost math
# ----------------------------------------------------------------------


def test_dry_run_returns_estimate_and_cost(fake_bq):
    one_tib = _BYTES_PER_TIB
    fake_bq.bigquery.total_bytes_processed = one_tib
    adapter = BigQueryAdapter(project="p")
    pv = adapter.dry_run("SELECT * FROM t")
    assert isinstance(pv, PreviewResult)
    assert pv.estimated_bytes_scanned == one_tib
    # 1 TiB at $6.25/TiB == $6.25.
    assert pv.estimated_cost_usd == pytest.approx(_ON_DEMAND_USD_PER_TIB)
    assert pv.warnings  # rate-assumption disclaimer present
    adapter.close()


def test_dry_run_cost_scales_with_bytes(fake_bq):
    half_tib = _BYTES_PER_TIB // 2
    fake_bq.bigquery.total_bytes_processed = half_tib
    adapter = BigQueryAdapter(project="p")
    pv = adapter.dry_run("SELECT 1")
    assert pv.estimated_cost_usd == pytest.approx(_ON_DEMAND_USD_PER_TIB / 2, rel=1e-6)
    adapter.close()


def test_dry_run_sets_dry_run_flag(fake_bq):
    adapter = BigQueryAdapter(project="p")
    adapter.dry_run("SELECT 1")
    _, job_config = fake_bq.bigquery.last_client.last_query
    assert job_config.dry_run is True
    assert job_config.use_query_cache is False
    adapter.close()


def test_dry_run_no_bytes_yields_unavailable_warning(fake_bq):
    fake_bq.bigquery.total_bytes_processed = None
    adapter = BigQueryAdapter(project="p")
    pv = adapter.dry_run("SELECT 1")
    assert pv.estimated_bytes_scanned is None
    assert pv.estimated_cost_usd is None
    assert any("unavailable" in w.lower() for w in pv.warnings)
    adapter.close()


# ----------------------------------------------------------------------
# explain
# ----------------------------------------------------------------------


def test_explain_returns_dry_run_estimate_string(fake_bq):
    fake_bq.bigquery.total_bytes_processed = 2048
    adapter = BigQueryAdapter(project="p")
    plan = adapter.explain("SELECT 1")
    assert isinstance(plan, str)
    assert "estimated_bytes_scanned=2048" in plan
    adapter.close()


# ----------------------------------------------------------------------
# Connection lifecycle
# ----------------------------------------------------------------------


def test_get_dialect():
    assert BigQueryAdapter().get_dialect() == "bigquery"


def test_close_releases_client(fake_bq):
    adapter = BigQueryAdapter(project="p")
    adapter.execute("SELECT 1")
    client = adapter._client
    assert client is not None
    adapter.close()
    assert adapter._client is None
    assert client.closed is True
    adapter.close()  # idempotent
    assert adapter._client is None


def test_multiple_execute_reuse_client(fake_bq):
    adapter = BigQueryAdapter(project="p")
    adapter.execute("SELECT 1")
    first = adapter._client
    adapter.execute("SELECT 2")
    assert adapter._client is first
    adapter.close()


# ----------------------------------------------------------------------
# Contract conformance (W0 harness)
# ----------------------------------------------------------------------


def test_conforms_to_base_adapter():
    adapter = BigQueryAdapter()
    assert isinstance(adapter, BaseAdapter)
    assert_conforms_to_base_adapter(adapter, "bigquery")


def test_registry_make_adapter_conforms():
    assert_conforms_to_base_adapter(make_adapter("bigquery"), "bigquery")


# ----------------------------------------------------------------------
# Credential-leakage bar (SE-001 / DE-019 redaction pattern)
# ----------------------------------------------------------------------


_FAKE_SA_PRIVATE_KEY = (
    "-----BEGIN PRIVATE KEY-----\n"
    "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDfakefakefake\n"
    "-----END PRIVATE KEY-----\n"
)


def _walk_exception_chain(exc: BaseException) -> str:
    text = ""
    err: BaseException | None = exc
    while err is not None:
        text += str(err)
        err = err.__cause__
    return text


def test_planted_sa_private_key_never_leaks_on_client_error(fake_bq, caplog):
    """SA inline dict with a private_key must not echo anywhere on failure."""
    fake_bq.bigquery.client_behavior = "boom"
    sa_info = {
        "type": "service_account",
        "project_id": "p",
        "private_key": _FAKE_SA_PRIVATE_KEY,
        "client_email": "svc@p.iam.gserviceaccount.com",
    }
    adapter = BigQueryAdapter(project="p", credentials_info=sa_info)
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.execute("SELECT 1")
    chain_text = _walk_exception_chain(excinfo.value)
    assert _FAKE_SA_PRIVATE_KEY not in chain_text
    assert "fakefakefake" not in chain_text
    assert _FAKE_SA_PRIVATE_KEY not in caplog.text
    assert "fakefakefake" not in caplog.text


def test_planted_sa_private_key_never_leaks_on_query_error(fake_bq, caplog):
    fake_bq.bigquery.query_behavior = "boom"
    sa_info = {
        "type": "service_account",
        "project_id": "p",
        "private_key": _FAKE_SA_PRIVATE_KEY,
    }
    adapter = BigQueryAdapter(project="p", credentials_info=sa_info)
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.execute("SELECT bad")
    chain_text = _walk_exception_chain(excinfo.value)
    assert _FAKE_SA_PRIVATE_KEY not in chain_text
    assert "fakefakefake" not in chain_text
    assert _FAKE_SA_PRIVATE_KEY not in caplog.text
    assert "fakefakefake" not in caplog.text


def test_redacted_dict_used_in_query_error_message(fake_bq):
    """The error message includes the REDACTED private_key, not the key bytes."""
    fake_bq.bigquery.query_behavior = "boom"
    sa_info = {"private_key": _FAKE_SA_PRIVATE_KEY, "project_id": "p"}
    adapter = BigQueryAdapter(project="p", credentials_info=sa_info)
    with pytest.raises(AdapterError) as excinfo:
        adapter.execute("SELECT 1")
    msg = str(excinfo.value)
    assert "[REDACTED]" in msg
    assert _FAKE_SA_PRIVATE_KEY not in msg
    assert "fakefakefake" not in msg


# BLOCKER-1: the RAW driver exception must not be interpolated into the new
# query-path error message.
_PLANTED = "access_token=tok_LEAKED_9999"


def test_planted_secret_in_driver_exc_never_leaks_on_execute(fake_bq, caplog):
    fake_bq.bigquery.query_behavior = "boom"
    fake_bq.bigquery.boom_message = f"backend rejected {_PLANTED} on request"
    adapter = BigQueryAdapter(project="p")
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.execute("SELECT 1")
    assert _PLANTED not in str(excinfo.value)
    assert "tok_LEAKED_9999" not in str(excinfo.value)
    assert "tok_LEAKED_9999" not in caplog.text
    assert excinfo.value.__cause__ is not None


def test_planted_secret_in_driver_exc_never_leaks_on_explain(fake_bq, caplog):
    # explain() routes through dry_run() -> client.query() -> _map_query_error.
    fake_bq.bigquery.query_behavior = "boom"
    fake_bq.bigquery.boom_message = f"backend rejected {_PLANTED} on request"
    adapter = BigQueryAdapter(project="p")
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.explain("SELECT 1")
    assert _PLANTED not in str(excinfo.value)
    assert "tok_LEAKED_9999" not in str(excinfo.value)
    assert "tok_LEAKED_9999" not in caplog.text
    assert excinfo.value.__cause__ is not None
