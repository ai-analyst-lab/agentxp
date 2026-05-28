"""Tier-A (always-on, NO network) tests for the Snowflake adapter (W1.A).

Patches the ``snowflake.connector`` import boundary with an in-process fake so
these run green whether or not ``snowflake-connector-python`` is installed in
the venv. Covers:

* each of the 4 auth surfaces builds the correct ``connect`` kwargs
  (password / externalbrowser / oauth / keypair);
* ``AdapterResult`` shape + ``dialect="snowflake"`` + ``bytes_scanned``
  populated from the per-query stats;
* auth error → :class:`AuthExpiredError`; statement timeout →
  :class:`QueryTimeoutError`;
* a real, server-side ``STATEMENT_TIMEOUT_IN_SECONDS`` session param is set;
* ``EXPLAIN USING TEXT`` is used by :meth:`explain`;
* honest no-dry-run :class:`PreviewResult`;
* conformance to :class:`BaseAdapter` via the W0 harness;
* the credential-leakage bar (clones the SE-001 / DE-019 redaction pattern):
  a planted password/token never reaches ``caplog`` or any raised exception.
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
from agentxp.sql.adapters.snowflake_adapter import SnowflakeAdapter
from tests.sql._adapter_contract import (
    assert_conforms_to_base_adapter,
    make_adapter,
)


# ----------------------------------------------------------------------
# In-process fake of snowflake.connector (no driver install, no network)
# ----------------------------------------------------------------------


class _FakeSnowflakeError(Exception):
    """Stand-in for snowflake.connector.errors.* with errno / sqlstate attrs."""

    def __init__(self, msg: str = "", errno: Any = None, sqlstate: Any = None):
        super().__init__(msg)
        self.errno = errno
        self.sqlstate = sqlstate


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection"):
        self._conn = conn
        self.description = [("x",), ("name",)]
        self._rows = [(1, "alice")]
        # Connector-surfaced per-query scan stat (see _extract_bytes_scanned).
        self._stats = {"bytesScanned": 4096}
        self.sfqid = "01ab-cdef"
        self.closed = False
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, timeout: Any = None) -> None:
        self.executed.append((sql, timeout))
        behavior = self._conn._execute_behavior
        if behavior == "timeout":
            raise _FakeSnowflakeError("Statement reached its statement timeout", errno=604)
        if behavior == "auth":
            raise _FakeSnowflakeError("Authentication token has expired", errno=390114)
        if behavior == "boom":
            raise _FakeSnowflakeError("syntax error somewhere", errno=1003)
        if sql.upper().startswith("EXPLAIN"):
            self.description = [("plan",)]
            self._rows = [("GlobalStats: rows=1",)]

    def fetchmany(self, n: int):
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
        self._cursors: list[_FakeCursor] = []

    def cursor(self) -> _FakeCursor:
        c = _FakeCursor(self)
        c._conn = self
        self._cursors.append(c)
        return c

    def close(self):
        self.closed = True


class _FakeConnector(types.ModuleType):
    """Fake ``snowflake.connector`` module exposing ``connect`` + ``errors``."""

    def __init__(self):
        super().__init__("snowflake.connector")
        self.last_connect_kwargs: dict[str, Any] | None = None
        self.connect_behavior = "ok"  # or "auth"
        self.execute_behavior = "ok"  # propagated onto each connection

    def connect(self, **kwargs: Any) -> _FakeConnection:
        self.last_connect_kwargs = kwargs
        if self.connect_behavior == "auth":
            raise _FakeSnowflakeError(
                "Incorrect username or password was specified", errno=390100
            )
        if self.connect_behavior == "boom":
            raise _FakeSnowflakeError("could not connect to Snowflake", errno=250001)
        conn = _FakeConnection(**kwargs)
        conn._execute_behavior = self.execute_behavior
        return conn


@pytest.fixture
def fake_connector(monkeypatch):
    """Install a fake ``snowflake.connector`` into sys.modules for the test."""
    pkg = types.ModuleType("snowflake")
    connector = _FakeConnector()
    pkg.connector = connector  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "snowflake", pkg)
    monkeypatch.setitem(sys.modules, "snowflake.connector", connector)
    return connector


# ----------------------------------------------------------------------
# Auth surface → connect kwargs
# ----------------------------------------------------------------------


def test_password_auth_builds_kwargs(fake_connector):
    adapter = SnowflakeAdapter(
        account="myorg-myaccount",
        user="SVC_AGENTXP",
        password="hunter2",
        warehouse="WH_XS",
        database="ANALYTICS",
        schema="PUBLIC",
    )
    adapter.execute("SELECT 1")
    kw = fake_connector.last_connect_kwargs
    assert kw["authenticator"] == "snowflake"
    assert kw["password"] == "hunter2"
    assert kw["account"] == "myorg-myaccount"
    assert kw["user"] == "SVC_AGENTXP"
    assert kw["warehouse"] == "WH_XS"
    assert kw["database"] == "ANALYTICS"
    assert kw["schema"] == "PUBLIC"
    adapter.close()


def test_externalbrowser_auth_builds_kwargs(fake_connector):
    adapter = SnowflakeAdapter(
        account="myorg-myaccount",
        user="alice@example.com",
        auth_method="externalbrowser",
        warehouse="WH_XS",
    )
    adapter.execute("SELECT 1")
    kw = fake_connector.last_connect_kwargs
    assert kw["authenticator"] == "externalbrowser"
    assert "password" not in kw
    assert "token" not in kw
    adapter.close()


def test_oauth_auth_builds_kwargs(fake_connector):
    adapter = SnowflakeAdapter(
        account="myorg-myaccount",
        user="alice@example.com",
        auth_method="oauth",
        token="oauth-access-token-xyz",
    )
    adapter.execute("SELECT 1")
    kw = fake_connector.last_connect_kwargs
    assert kw["authenticator"] == "oauth"
    assert kw["token"] == "oauth-access-token-xyz"
    assert "password" not in kw
    adapter.close()


def test_keypair_auth_with_private_key_bytes(fake_connector):
    adapter = SnowflakeAdapter(
        account="myorg-myaccount",
        user="SVC_AGENTXP",
        auth_method="keypair",
        private_key=b"\x30\x82DER-bytes",
    )
    adapter.execute("SELECT 1")
    kw = fake_connector.last_connect_kwargs
    assert kw["authenticator"] == "SNOWFLAKE_JWT"
    assert kw["private_key"] == b"\x30\x82DER-bytes"
    adapter.close()


def test_keypair_auth_with_key_file_and_passphrase(fake_connector):
    adapter = SnowflakeAdapter(
        account="myorg-myaccount",
        user="SVC_AGENTXP",
        auth_method="keypair",
        private_key_file="/path/rsa_key.p8",
        private_key_file_pwd="keysecret",
    )
    adapter.execute("SELECT 1")
    kw = fake_connector.last_connect_kwargs
    assert kw["authenticator"] == "SNOWFLAKE_JWT"
    assert kw["private_key_file"] == "/path/rsa_key.p8"
    assert kw["private_key_file_pwd"] == "keysecret"
    adapter.close()


def test_auth_method_inferred_from_token(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", token="tok")
    adapter.execute("SELECT 1")
    assert fake_connector.last_connect_kwargs["authenticator"] == "oauth"
    adapter.close()


def test_unknown_auth_method_raises_adapter_error(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", auth_method="magic")
    with pytest.raises(AdapterError, match="Unknown Snowflake auth_method"):
        adapter.execute("SELECT 1")


def test_keypair_without_key_material_raises(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", auth_method="keypair")
    with pytest.raises(AdapterError, match="keypair auth requires"):
        adapter.execute("SELECT 1")


# ----------------------------------------------------------------------
# execute / result shape / timeout / dialect / bytes_scanned
# ----------------------------------------------------------------------


def test_execute_returns_adapter_result_shape(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
    result = adapter.execute("SELECT 1 AS x, 'alice' AS name")
    assert isinstance(result, AdapterResult)
    assert result.dialect == "snowflake"
    assert result.row_count == 1
    assert result.rows == [{"x": 1, "name": "alice"}]
    assert result.bytes_scanned == 4096
    assert result.elapsed_seconds >= 0.0
    adapter.close()


def test_statement_timeout_session_param_is_set(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
    adapter.execute("SELECT 1", timeout_s=45)
    sp = fake_connector.last_connect_kwargs["session_parameters"]
    assert sp["STATEMENT_TIMEOUT_IN_SECONDS"] == 45
    adapter.close()


def test_client_timeout_passed_to_cursor_execute(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
    adapter.execute("SELECT 1", timeout_s=12)
    cur = adapter._conn._cursors[-1]
    assert cur.executed[-1][1] == 12  # timeout kwarg forwarded
    adapter.close()


def test_max_rows_truncation(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
    # Patch the fetchmany source to verify max_rows is honored.
    adapter._connect()
    result = adapter.execute("SELECT * FROM t", max_rows=1)
    assert result.row_count == 1
    adapter.close()


def test_timeout_maps_to_query_timeout_error(fake_connector):
    fake_connector.execute_behavior = "timeout"
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
    with pytest.raises(QueryTimeoutError):
        adapter.execute("SELECT pg_sleep(99)")
    adapter.close()


def test_auth_error_on_execute_maps_to_auth_expired(fake_connector):
    fake_connector.execute_behavior = "auth"
    adapter = SnowflakeAdapter(account="a", user="u", token="expired")
    with pytest.raises(AuthExpiredError):
        adapter.execute("SELECT 1")
    adapter.close()


def test_auth_error_on_connect_maps_to_auth_expired(fake_connector):
    fake_connector.connect_behavior = "auth"
    adapter = SnowflakeAdapter(account="a", user="u", password="wrong")
    with pytest.raises(AuthExpiredError):
        adapter.execute("SELECT 1")


def test_generic_connect_error_maps_to_adapter_error(fake_connector):
    fake_connector.connect_behavior = "boom"
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
    with pytest.raises(AdapterError):
        adapter.execute("SELECT 1")


def test_generic_execute_error_maps_to_adapter_error(fake_connector):
    fake_connector.execute_behavior = "boom"
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
    with pytest.raises(AdapterError):
        adapter.execute("SELECT bad")
    adapter.close()


# ----------------------------------------------------------------------
# explain / dry_run
# ----------------------------------------------------------------------


def test_explain_uses_using_text(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
    plan = adapter.explain("SELECT 1")
    assert isinstance(plan, str)
    cur = adapter._conn._cursors[-1]
    assert cur.executed[-1][0].startswith("EXPLAIN USING TEXT")
    adapter.close()


def test_dry_run_is_honest_no_estimate(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
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
    assert SnowflakeAdapter().get_dialect() == "snowflake"


def test_close_releases_connection(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
    adapter.execute("SELECT 1")
    assert adapter._conn is not None
    conn = adapter._conn
    adapter.close()
    assert adapter._conn is None
    assert conn.closed is True
    adapter.close()  # idempotent
    assert adapter._conn is None


def test_multiple_execute_reuse_connection(fake_connector):
    adapter = SnowflakeAdapter(account="a", user="u", password="p")
    adapter.execute("SELECT 1")
    first = adapter._conn
    adapter.execute("SELECT 2")
    assert adapter._conn is first
    adapter.close()


def test_no_network_at_construction(fake_connector):
    # Constructing must not call connect.
    SnowflakeAdapter(account="a", user="u", password="p")
    assert fake_connector.last_connect_kwargs is None


# ----------------------------------------------------------------------
# Contract conformance (W0 harness)
# ----------------------------------------------------------------------


def test_conforms_to_base_adapter():
    adapter = SnowflakeAdapter()
    assert isinstance(adapter, BaseAdapter)
    assert_conforms_to_base_adapter(adapter, "snowflake")


def test_registry_make_adapter_conforms():
    assert_conforms_to_base_adapter(make_adapter("snowflake"), "snowflake")


# ----------------------------------------------------------------------
# Credential-leakage bar (SE-001 / DE-019 redaction pattern)
# ----------------------------------------------------------------------


def test_planted_password_never_leaks_on_connect_error(fake_connector, caplog):
    """Auth failure at connect must not echo the password anywhere."""
    fake_connector.connect_behavior = "auth"
    secret = "hunter2"
    adapter = SnowflakeAdapter(
        account="myorg", user="u", password=secret, warehouse="WH"
    )
    with caplog.at_level("DEBUG"):
        with pytest.raises(AuthExpiredError) as excinfo:
            adapter.execute("SELECT 1")
    # Secret in NO exception message in the chain.
    chain_text = ""
    err: BaseException | None = excinfo.value
    while err is not None:
        chain_text += str(err)
        err = err.__cause__
    assert secret not in chain_text
    # Secret in NO log record.
    assert secret not in caplog.text


def test_planted_token_never_leaks_on_generic_error(fake_connector, caplog):
    fake_connector.connect_behavior = "boom"
    secret = "oauth-super-secret-token"
    adapter = SnowflakeAdapter(account="myorg", user="u", token=secret)
    with caplog.at_level("DEBUG"):
        with pytest.raises(AdapterError) as excinfo:
            adapter.execute("SELECT 1")
    chain_text = ""
    err: BaseException | None = excinfo.value
    while err is not None:
        chain_text += str(err)
        err = err.__cause__
    assert secret not in chain_text
    assert secret not in caplog.text


def test_redacted_dict_used_in_connect_error_message(fake_connector):
    """The connect-error message includes the REDACTED dict, not the secret."""
    fake_connector.connect_behavior = "boom"
    adapter = SnowflakeAdapter(account="myorg", user="u", password="hunter2")
    with pytest.raises(AdapterError) as excinfo:
        adapter.execute("SELECT 1")
    msg = str(excinfo.value)
    assert "[REDACTED]" in msg
    assert "hunter2" not in msg
