"""Tier-A (always-on, NO network) tests for the Databricks adapter (W1.C).

Patches the ``databricks.sql.connect`` import boundary with an in-process fake
so these run green whether or not ``databricks-sql-connector`` is installed in
the venv. Covers:

* the two auth surfaces build the correct ``connect`` kwargs — PAT
  (``access_token``) vs OAuth (U2M ``auth_type="databricks-oauth"`` and M2M
  ``credentials_provider``);
* ``AdapterResult`` shape + ``dialect="databricks"`` + ``bytes_scanned is None``
  (the connector exposes no scan stats — honest-unknown contract);
* a Unity Catalog three-level ``catalog.schema.table`` name is handled (passes
  through verbatim, no choke);
* a ``socket_timeout`` comms ceiling is set from ``timeout_s``;
* auth error → :class:`AuthExpiredError`; ``ServerOperationError``
  ``DEADLINE_EXCEEDED`` / socket timeout → :class:`QueryTimeoutError`;
* honest no-dry-run :class:`PreviewResult`; ``EXPLAIN`` used by :meth:`explain`;
* conformance to :class:`BaseAdapter` via the W0 harness;
* the credential-leakage bar (clones the SE-001 / DE-019 redaction pattern):
  a planted ``access_token`` / ``client_secret`` never reaches ``caplog`` or
  any raised exception.
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
    PreviewResult,
    QueryTimeoutError,
)
from agentxp.sql.adapters.databricks_adapter import DatabricksAdapter
from tests.sql._adapter_contract import (
    assert_conforms_to_base_adapter,
    make_adapter,
)


# ----------------------------------------------------------------------
# In-process fake of databricks.sql (no driver install, no network)
# ----------------------------------------------------------------------


# The adapter maps driver exceptions by CLASS NAME (it does not hard-import
# databricks.sql.exc), so these fakes deliberately use the exact class names
# the real driver raises.
class ServerOperationError(Exception):
    """Stand-in for databricks.sql.exc.ServerOperationError (DEADLINE_EXCEEDED)."""


class RequestError(Exception):
    """Stand-in for databricks.sql.exc.RequestError (auth, HTTP 401/403)."""


class OperationalError(Exception):
    """Stand-in for databricks.sql.exc.OperationalError."""


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection"):
        self._conn = conn
        self.description = [("x",), ("name",)]
        # Default single row keeps the result-shape tests exact; a connection
        # may seed more rows so a truncation test can prove max_rows is honored.
        self._rows = (
            list(conn._seed_rows) if conn._seed_rows is not None else [(1, "alice")]
        )
        self.closed = False
        self.executed: list[str] = []
        self.fetchmany_calls: list[int] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)
        behavior = self._conn._execute_behavior
        if behavior == "timeout":
            raise ServerOperationError(
                "DEADLINE_EXCEEDED: This operation took too long..."
            )
        if behavior == "auth":
            raise RequestError("HTTP 403 Forbidden: invalid access token")
        if behavior == "boom":
            raise OperationalError(
                getattr(self._conn, "_boom_message", "syntax error near 'SELCT'")
            )
        if sql.upper().startswith("EXPLAIN"):
            self.description = [("plan",)]
            self._rows = [("== Physical Plan ==",)]

    def fetchmany(self, n: int):
        self.fetchmany_calls.append(n)
        return self._rows[:n]

    def fetchall(self):
        return self._rows

    def close(self):
        self.closed = True


class _FakeConnection:
    def __init__(self, **kwargs: Any):
        self.connect_kwargs = kwargs
        self.closed = False
        self._execute_behavior = "ok"
        self._seed_rows: list[tuple[Any, ...]] | None = None
        self._cursors: list[_FakeCursor] = []

    def cursor(self) -> _FakeCursor:
        c = _FakeCursor(self)
        self._cursors.append(c)
        return c

    def close(self):
        self.closed = True


class _FakeSqlModule(types.ModuleType):
    """Fake ``databricks.sql`` exposing ``connect``."""

    def __init__(self):
        super().__init__("databricks.sql")
        self.last_connect_kwargs: dict[str, Any] | None = None
        self.connect_behavior = "ok"  # ok|auth|boom (at connect time)
        self.execute_behavior = "ok"  # propagated onto each connection
        # Optional rows to seed each cursor with (None -> the default 1 row).
        self.seed_rows: list[tuple[Any, ...]] | None = None
        # Optional custom message for the "boom" generic exception, used by the
        # BLOCKER-1 tests to plant a secret INSIDE the raw driver exception.
        self.boom_message = "could not establish connection"

    def connect(self, **kwargs: Any) -> _FakeConnection:
        self.last_connect_kwargs = kwargs
        if self.connect_behavior == "auth":
            raise RequestError("HTTP 401 Unauthorized: invalid access token")
        if self.connect_behavior == "boom":
            raise OperationalError(self.boom_message)
        conn = _FakeConnection(**kwargs)
        conn._execute_behavior = self.execute_behavior
        conn._seed_rows = self.seed_rows
        conn._boom_message = self.boom_message
        return conn


@pytest.fixture
def fake_databricks(monkeypatch):
    """Install a fake ``databricks.sql`` into sys.modules for the test."""
    pkg = types.ModuleType("databricks")
    sql_mod = _FakeSqlModule()
    pkg.sql = sql_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "databricks", pkg)
    monkeypatch.setitem(sys.modules, "databricks.sql", sql_mod)
    return sql_mod


_HOST = "adb-1234.5.azuredatabricks.net"
_PATH = "/sql/1.0/warehouses/abc123"


# ----------------------------------------------------------------------
# Auth surface → connect kwargs
# ----------------------------------------------------------------------


def test_pat_auth_builds_kwargs(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST,
        http_path=_PATH,
        access_token="dapi_secret",
    )
    adapter.execute("SELECT 1")
    kw = fake_databricks.last_connect_kwargs
    assert kw["server_hostname"] == _HOST
    assert kw["http_path"] == _PATH
    assert kw["access_token"] == "dapi_secret"
    assert "auth_type" not in kw
    assert "credentials_provider" not in kw
    adapter.close()


def test_oauth_u2m_auth_builds_kwargs(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST,
        http_path=_PATH,
        auth_method="oauth_u2m",
    )
    adapter.execute("SELECT 1")
    kw = fake_databricks.last_connect_kwargs
    assert kw["auth_type"] == "databricks-oauth"
    assert "access_token" not in kw
    assert "credentials_provider" not in kw
    adapter.close()


def test_oauth_m2m_auth_builds_credentials_provider(fake_databricks, monkeypatch):
    # M2M lazily imports databricks.sdk.core — install a fake for it.
    sdk_pkg = types.ModuleType("databricks.sdk")
    core_mod = types.ModuleType("databricks.sdk.core")

    class _Config:
        def __init__(self, host=None, client_id=None, client_secret=None):
            self.host = host
            self.client_id = client_id
            self.client_secret = client_secret

    def _osp(cfg):
        return lambda: {"token": "minted"}

    core_mod.Config = _Config  # type: ignore[attr-defined]
    core_mod.oauth_service_principal = _osp  # type: ignore[attr-defined]
    sdk_pkg.core = core_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "databricks.sdk", sdk_pkg)
    monkeypatch.setitem(sys.modules, "databricks.sdk.core", core_mod)

    adapter = DatabricksAdapter(
        server_hostname=_HOST,
        http_path=_PATH,
        client_id="sp-app-id",
        client_secret="sp_secret",
    )
    adapter.execute("SELECT 1")
    kw = fake_databricks.last_connect_kwargs
    assert callable(kw["credentials_provider"])
    assert "access_token" not in kw
    adapter.close()


def test_auth_method_inferred_from_access_token(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="dapi_x"
    )
    adapter.execute("SELECT 1")
    assert fake_databricks.last_connect_kwargs["access_token"] == "dapi_x"
    adapter.close()


def test_unknown_auth_method_raises_adapter_error(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, auth_method="magic"
    )
    with pytest.raises(AdapterError, match="Unknown Databricks auth_method"):
        adapter.execute("SELECT 1")


def test_missing_server_hostname_raises(fake_databricks):
    adapter = DatabricksAdapter(http_path=_PATH, access_token="dapi_x")
    with pytest.raises(AdapterError, match="server_hostname"):
        adapter.execute("SELECT 1")


def test_undeterminable_auth_raises(fake_databricks):
    adapter = DatabricksAdapter(server_hostname=_HOST, http_path=_PATH)
    with pytest.raises(AdapterError, match="Could not determine"):
        adapter.execute("SELECT 1")


def test_m2m_without_secret_raises(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST,
        http_path=_PATH,
        auth_method="oauth_m2m",
        client_id="only-id",
    )
    with pytest.raises(AdapterError, match="OAuth M2M"):
        adapter.execute("SELECT 1")


# ----------------------------------------------------------------------
# execute / result shape / dialect / bytes_scanned / timeout
# ----------------------------------------------------------------------


def test_execute_returns_adapter_result_shape(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="dapi_x"
    )
    result = adapter.execute("SELECT 1 AS x, 'alice' AS name")
    assert isinstance(result, AdapterResult)
    assert result.dialect == "databricks"
    assert result.row_count == 1
    assert result.rows == [{"x": 1, "name": "alice"}]
    # Connector exposes no scan stats — honest None (DuckDB contract).
    assert result.bytes_scanned is None
    assert result.elapsed_seconds >= 0.0
    adapter.close()


def test_three_level_unity_catalog_name_handled(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="dapi_x"
    )
    # catalog.schema.table must pass through verbatim, no choke.
    result = adapter.execute("SELECT * FROM main.sales.orders")
    assert isinstance(result, AdapterResult)
    cur = adapter._conn._cursors[-1]
    assert cur.executed[-1] == "SELECT * FROM main.sales.orders"
    adapter.close()


def test_socket_timeout_set_from_timeout_s(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="dapi_x"
    )
    adapter.execute("SELECT 1", timeout_s=45)
    assert fake_databricks.last_connect_kwargs["socket_timeout"] == 45
    adapter.close()


def test_max_rows_truncation(fake_databricks):
    # Seed MORE rows than the cap so the cap is actually exercised: with a
    # 1-row fake, max_rows=1 would pass even if max_rows were ignored entirely.
    fake_databricks.seed_rows = [(i, f"name{i}") for i in range(10)]
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="dapi_x"
    )
    result = adapter.execute("SELECT * FROM t", max_rows=3)
    assert result.row_count == 3
    # And prove the adapter forwarded the cap to the driver's fetchmany.
    cur = adapter._conn._cursors[-1]
    assert cur.fetchmany_calls[-1] == 3
    adapter.close()


def test_timeout_maps_to_query_timeout_error(fake_databricks):
    fake_databricks.execute_behavior = "timeout"
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="dapi_x"
    )
    with pytest.raises(QueryTimeoutError):
        adapter.execute("SELECT * FROM huge")
    adapter.close()


def test_auth_error_on_execute_maps_to_auth_expired(fake_databricks):
    fake_databricks.execute_behavior = "auth"
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="expired"
    )
    with pytest.raises(AuthExpiredError):
        adapter.execute("SELECT 1")
    adapter.close()


def test_auth_error_on_connect_maps_to_auth_expired(fake_databricks):
    fake_databricks.connect_behavior = "auth"
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="wrong"
    )
    with pytest.raises(AuthExpiredError):
        adapter.execute("SELECT 1")


def test_generic_connect_error_maps_to_adapter_error(fake_databricks):
    fake_databricks.connect_behavior = "boom"
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="x"
    )
    with pytest.raises(AdapterError):
        adapter.execute("SELECT 1")


def test_generic_execute_error_maps_to_adapter_error(fake_databricks):
    fake_databricks.execute_behavior = "boom"
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="x"
    )
    with pytest.raises(AdapterError):
        adapter.execute("SELECT bad")
    adapter.close()


# ----------------------------------------------------------------------
# explain / dry_run
# ----------------------------------------------------------------------


def test_explain_uses_explain_keyword(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="x"
    )
    plan = adapter.explain("SELECT 1")
    assert isinstance(plan, str)
    cur = adapter._conn._cursors[-1]
    assert cur.executed[-1].startswith("EXPLAIN")
    adapter.close()


def test_dry_run_is_honest_no_estimate(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="x"
    )
    pv = adapter.dry_run("SELECT 1")
    assert isinstance(pv, PreviewResult)
    assert pv.estimated_rows is None
    assert pv.estimated_bytes_scanned is None
    assert pv.estimated_cost_usd is None
    assert any("dry-run" in w.lower() for w in pv.warnings)


# ----------------------------------------------------------------------
# Connection lifecycle
# ----------------------------------------------------------------------


def test_get_dialect():
    assert DatabricksAdapter().get_dialect() == "databricks"


def test_close_releases_connection(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="x"
    )
    adapter.execute("SELECT 1")
    assert adapter._conn is not None
    conn = adapter._conn
    adapter.close()
    assert adapter._conn is None
    assert conn.closed is True
    adapter.close()  # idempotent
    assert adapter._conn is None


def test_multiple_execute_reuse_connection(fake_databricks):
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="x"
    )
    adapter.execute("SELECT 1")
    first = adapter._conn
    adapter.execute("SELECT 2")
    assert adapter._conn is first
    adapter.close()


def test_no_network_at_construction(fake_databricks):
    DatabricksAdapter(server_hostname=_HOST, http_path=_PATH, access_token="x")
    assert fake_databricks.last_connect_kwargs is None


# ----------------------------------------------------------------------
# Contract conformance (W0 harness)
# ----------------------------------------------------------------------


def test_conforms_to_base_adapter():
    adapter = DatabricksAdapter()
    assert isinstance(adapter, BaseAdapter)
    assert_conforms_to_base_adapter(adapter, "databricks")


def test_registry_make_adapter_conforms():
    assert_conforms_to_base_adapter(make_adapter("databricks"), "databricks")


# ----------------------------------------------------------------------
# Credential-leakage bar (SE-001 / DE-019 redaction pattern)
# ----------------------------------------------------------------------


def _walk_exception_chain(exc: BaseException) -> str:
    text = ""
    err: BaseException | None = exc
    while err is not None:
        text += str(err)
        err = err.__cause__
    return text


def test_planted_access_token_never_leaks_on_connect_error(fake_databricks, caplog):
    """Auth failure at connect must not echo the PAT anywhere."""
    fake_databricks.connect_behavior = "auth"
    secret = "dapi_secret"
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token=secret
    )
    with caplog.at_level("DEBUG"):
        with pytest.raises(AuthExpiredError) as excinfo:
            adapter.execute("SELECT 1")
    chain_text = _walk_exception_chain(excinfo.value)
    assert secret not in chain_text
    assert secret not in caplog.text


def test_planted_client_secret_never_leaks_on_generic_error(
    fake_databricks, caplog, monkeypatch
):
    # Install a fake SDK so the M2M path can build a provider, then fail connect.
    sdk_pkg = types.ModuleType("databricks.sdk")
    core_mod = types.ModuleType("databricks.sdk.core")
    core_mod.Config = lambda **kw: None  # type: ignore[attr-defined]
    core_mod.oauth_service_principal = lambda cfg: (lambda: {})  # type: ignore[attr-defined]
    sdk_pkg.core = core_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "databricks.sdk", sdk_pkg)
    monkeypatch.setitem(sys.modules, "databricks.sdk.core", core_mod)

    fake_databricks.connect_behavior = "boom"
    secret = "sp_super_secret"
    adapter = DatabricksAdapter(
        server_hostname=_HOST,
        http_path=_PATH,
        client_id="sp-id",
        client_secret=secret,
    )
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.execute("SELECT 1")
    chain_text = _walk_exception_chain(excinfo.value)
    assert secret not in chain_text
    assert secret not in caplog.text


def test_redacted_dict_used_in_connect_error_message(fake_databricks):
    """The connect-error message includes the REDACTED token, not the secret."""
    fake_databricks.connect_behavior = "boom"
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="dapi_secret"
    )
    with pytest.raises(AdapterError) as excinfo:
        adapter.execute("SELECT 1")
    msg = str(excinfo.value)
    assert "[REDACTED]" in msg
    assert "dapi_secret" not in msg


# BLOCKER-1: the RAW driver exception must not be interpolated into the new
# query-path error message.
_PLANTED = "access_token=dapi_LEAKED_9999"


def test_planted_secret_in_driver_exc_never_leaks_on_execute(
    fake_databricks, caplog
):
    fake_databricks.execute_behavior = "boom"
    fake_databricks.boom_message = f"backend rejected {_PLANTED} on host"
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="dapi_x"
    )
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.execute("SELECT 1")
    assert _PLANTED not in str(excinfo.value)
    assert "dapi_LEAKED_9999" not in str(excinfo.value)
    assert "dapi_LEAKED_9999" not in caplog.text
    assert excinfo.value.__cause__ is not None


def test_planted_secret_in_driver_exc_never_leaks_on_explain(
    fake_databricks, caplog
):
    fake_databricks.execute_behavior = "boom"
    fake_databricks.boom_message = f"backend rejected {_PLANTED} on host"
    adapter = DatabricksAdapter(
        server_hostname=_HOST, http_path=_PATH, access_token="dapi_x"
    )
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.explain("SELECT 1")
    assert _PLANTED not in str(excinfo.value)
    assert "dapi_LEAKED_9999" not in str(excinfo.value)
    assert "dapi_LEAKED_9999" not in caplog.text
    assert excinfo.value.__cause__ is not None
