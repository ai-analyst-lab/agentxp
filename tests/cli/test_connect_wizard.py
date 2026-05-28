"""Tests for the agentxp connect wizards — W2.A.

Covers the shared core (connect_common), the DuckDB wizard, and the BigQuery
wizard. No live warehouse: the adapter registry is monkeypatched with a fake
adapter, and prompt helpers are stubbed so the interactive flow runs headless.

Security assertions (the load-bearing ones):
  * a planted secret is NEVER written in the clear to the profile file
  * a planted secret NEVER appears in captured stdout
  * the profile file is written chmod 600
  * ADC vs SA-JSON branching is exercised
"""
from __future__ import annotations

import stat
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

import yaml

from agentxp.cli import (
    connect_bigquery,
    connect_common,
    connect_databricks,
    connect_duckdb,
    connect_snowflake,
)
from agentxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR


# ---------------------------------------------------------------------------
# Fake adapter + registry helpers
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row_count: int = 1) -> None:
        self.row_count = row_count


class _FakeAdapter:
    """Records the kwargs it was constructed with and whether execute ran."""

    last_init_kwargs: dict[str, Any] = {}
    executed_sql: list[str] = []
    raise_on_execute: BaseException | None = None

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_init_kwargs = dict(kwargs)

    def execute(self, sql: str, max_rows: int = 10_000, timeout_s: int = 30):
        type(self).executed_sql.append(sql)
        if type(self).raise_on_execute is not None:
            raise type(self).raise_on_execute
        return _FakeResult(row_count=1)

    def close(self) -> None:  # pragma: no cover — trivial
        pass


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeAdapter.last_init_kwargs = {}
    _FakeAdapter.executed_sql = []
    _FakeAdapter.raise_on_execute = None
    yield


@pytest.fixture
def patch_registry(monkeypatch: pytest.MonkeyPatch):
    """Point ADAPTER_REGISTRY (as seen by connect_common) at the fake adapter."""
    fake_registry = {
        "duckdb": _FakeAdapter,
        "bigquery": _FakeAdapter,
        "snowflake": _FakeAdapter,
        "databricks": _FakeAdapter,
    }
    monkeypatch.setattr(connect_common, "ADAPTER_REGISTRY", fake_registry)
    return fake_registry


# ---------------------------------------------------------------------------
# live_probe
# ---------------------------------------------------------------------------


def test_live_probe_calls_adapter_execute(patch_registry):
    ok, msg = connect_common.live_probe("duckdb", {"file_path": None})
    assert ok is True
    assert "OK" in msg
    assert _FakeAdapter.executed_sql == ["SELECT 1"]


def test_live_probe_auth_error_is_friendly_no_traceback(patch_registry):
    from agentxp.sql.adapter import AuthExpiredError

    _FakeAdapter.raise_on_execute = AuthExpiredError(
        "BigQuery auth failed for conn={'project': 'p'}: Unauthorized"
    )
    ok, msg = connect_common.live_probe("bigquery", {"project": "p"})
    assert ok is False
    assert "authentication failed" in msg
    # Must NOT echo the raw exception text / connection dict.
    assert "conn=" not in msg
    assert "project" not in msg


def test_live_probe_generic_error_hides_exception_text(patch_registry):
    _FakeAdapter.raise_on_execute = RuntimeError(
        "connection string user:secretpw@host blew up"
    )
    ok, msg = connect_common.live_probe("duckdb", {"file_path": None})
    assert ok is False
    # Only the class name surfaces — never the message with the secret.
    assert "RuntimeError" in msg
    assert "secretpw" not in msg


def test_live_probe_unknown_dialect(patch_registry):
    ok, msg = connect_common.live_probe("oracle", {})
    assert ok is False
    assert "no adapter" in msg


# ---------------------------------------------------------------------------
# write_profile — chmod 600 + redacted confirmation
# ---------------------------------------------------------------------------


def test_write_profile_mode_600(tmp_path: Path, capsys):
    profile = {"adapter": "duckdb", "profile_name": "p", "database": "x.duckdb"}
    target = connect_common.write_profile(
        "duckdb", "p", profile, root=tmp_path
    )
    assert target.exists()
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600, oct(mode)
    # Parent dir locked down too.
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700


def test_write_profile_redacts_secret_in_stdout(tmp_path: Path, capsys):
    secret = "SUPER-SECRET-PRIVATE-KEY-VALUE"
    profile = {
        "adapter": "bigquery",
        "profile_name": "p",
        "token": secret,  # a sensitive key
    }
    connect_common.write_profile("bigquery", "p", profile, root=tmp_path)
    out = capsys.readouterr().out
    # The secret must not appear in the confirmation print.
    assert secret not in out
    assert "[REDACTED]" in out


def test_write_profile_roundtrip(tmp_path: Path, capsys):
    profile = {"adapter": "duckdb", "profile_name": "p", "database": "x.duckdb"}
    connect_common.write_profile("duckdb", "p", profile, root=tmp_path)
    loaded = connect_common.load_profile("duckdb", "p", root=tmp_path)
    assert loaded["database"] == "x.duckdb"


# ---------------------------------------------------------------------------
# DuckDB wizard
# ---------------------------------------------------------------------------


def test_duckdb_collect_file_path(monkeypatch):
    monkeypatch.setattr(connect_duckdb, "prompt_yes_no", lambda *a, **k: False)
    monkeypatch.setattr(
        connect_duckdb, "prompt_text", lambda *a, **k: "/tmp/wh.duckdb"
    )
    conn_params, profile = connect_duckdb.collect("prod")
    assert conn_params["file_path"] == Path("/tmp/wh.duckdb")
    assert profile["auth_kind"] == "none"
    assert profile["adapter"] == "duckdb"
    assert profile["profile_name"] == "prod"


def test_duckdb_collect_in_memory(monkeypatch):
    monkeypatch.setattr(connect_duckdb, "prompt_yes_no", lambda *a, **k: True)
    conn_params, profile = connect_duckdb.collect("dev")
    assert conn_params["file_path"] is None
    assert profile["in_memory"] is True


def test_duckdb_main_writes_profile(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    # Headless prompts.
    monkeypatch.setattr(connect_duckdb, "prompt_yes_no", lambda *a, **k: False)
    monkeypatch.setattr(
        connect_duckdb, "prompt_text", lambda *a, **k: str(tmp_path / "wh.duckdb")
    )
    # Redirect the credentials root into tmp_path.
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))

    rc = connect_duckdb.main(["prod"])
    assert rc == EXIT_OK
    written = tmp_path / ".agentxp" / "credentials" / "duckdb" / "prod.yaml"
    assert written.exists()
    assert _FakeAdapter.executed_sql == ["SELECT 1"]


# ---------------------------------------------------------------------------
# BigQuery wizard — ADC vs SA branching
# ---------------------------------------------------------------------------


def test_bigquery_collect_adc(monkeypatch):
    monkeypatch.setattr(connect_bigquery, "prompt_text", lambda *a, **k: "my-proj")
    monkeypatch.setattr(connect_bigquery, "prompt_choice", lambda *a, **k: "adc")
    conn_params, profile = connect_bigquery.collect("prod")
    assert conn_params == {"project": "my-proj"}
    assert profile["auth_kind"] == "adc"
    assert profile["project_id"] == "my-proj"
    # ADC carries no credential material.
    assert "credentials_path" not in profile
    assert "credentials_info" not in profile


def test_bigquery_collect_sa_path(monkeypatch):
    texts = iter(["my-proj", "/keys/sa.json"])
    monkeypatch.setattr(connect_bigquery, "prompt_text", lambda *a, **k: next(texts))
    monkeypatch.setattr(connect_bigquery, "prompt_choice", lambda *a, **k: "sa")
    monkeypatch.setattr(connect_bigquery, "prompt_yes_no", lambda *a, **k: False)
    conn_params, profile = connect_bigquery.collect("prod")
    assert profile["auth_kind"] == "sa"
    # The profile stores the PATH (a reference), never key contents.
    assert profile["credentials_path"].endswith("/keys/sa.json")
    assert conn_params["credentials_path"].endswith("/keys/sa.json")
    assert "credentials_info" not in profile


def test_bigquery_collect_sa_inline_secret_never_in_stdout(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    """Inline SA paste: private key must never reach stdout or the cleartext
    profile confirmation; it lives only in the chmod-600 file."""
    private_key = "-----BEGIN PRIVATE KEY-----PLANTEDKEYMATERIAL-----END PRIVATE KEY-----"
    sa_json = (
        '{"type":"service_account","project_id":"my-proj",'
        f'"private_key":"{private_key}","client_email":"x@my-proj.iam"}}'
    )
    monkeypatch.setattr(connect_bigquery, "prompt_text", lambda *a, **k: "my-proj")
    monkeypatch.setattr(connect_bigquery, "prompt_choice", lambda *a, **k: "sa")
    monkeypatch.setattr(connect_bigquery, "prompt_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(connect_bigquery, "prompt_secret", lambda *a, **k: sa_json)
    # Redirect credentials root into tmp_path.
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))

    rc = connect_bigquery.main(["prod"])
    assert rc == EXIT_OK

    out = capsys.readouterr().out
    # Planted private key must NOT appear in stdout.
    assert private_key not in out
    assert "PLANTEDKEYMATERIAL" not in out

    # The adapter got the inline dict for the probe (in-memory only).
    assert "credentials_info" in _FakeAdapter.last_init_kwargs

    # The profile file exists, chmod 600. (Inline secret is allowed in the
    # 600 file only — the user explicitly pasted it.)
    written = tmp_path / ".agentxp" / "credentials" / "bigquery" / "prod.yaml"
    assert written.exists()
    assert stat.S_IMODE(written.stat().st_mode) == 0o600


def test_bigquery_collect_sa_inline_invalid_json(monkeypatch):
    monkeypatch.setattr(connect_bigquery, "prompt_text", lambda *a, **k: "my-proj")
    monkeypatch.setattr(connect_bigquery, "prompt_choice", lambda *a, **k: "sa")
    monkeypatch.setattr(connect_bigquery, "prompt_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(connect_bigquery, "prompt_secret", lambda *a, **k: "not json")
    with pytest.raises(ValueError):
        connect_bigquery.collect("prod")


def test_bigquery_main_invalid_json_user_error(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    monkeypatch.setattr(connect_bigquery, "prompt_text", lambda *a, **k: "my-proj")
    monkeypatch.setattr(connect_bigquery, "prompt_choice", lambda *a, **k: "sa")
    monkeypatch.setattr(connect_bigquery, "prompt_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(connect_bigquery, "prompt_secret", lambda *a, **k: "garbage")
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))
    rc = connect_bigquery.main(["prod"])
    assert rc == EXIT_USER_ERROR


def test_bigquery_adc_main_probe_then_write(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    monkeypatch.setattr(connect_bigquery, "prompt_text", lambda *a, **k: "my-proj")
    monkeypatch.setattr(connect_bigquery, "prompt_choice", lambda *a, **k: "adc")
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))
    rc = connect_bigquery.main(["prod"])
    assert rc == EXIT_OK
    assert _FakeAdapter.executed_sql == ["SELECT 1"]
    written = tmp_path / ".agentxp" / "credentials" / "bigquery" / "prod.yaml"
    assert written.exists()
    loaded = yaml.safe_load(written.read_text())
    assert loaded["auth_kind"] == "adc"


# ---------------------------------------------------------------------------
# Probe failure → profile NOT written
# ---------------------------------------------------------------------------


def test_probe_failure_does_not_write_profile(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    _FakeAdapter.raise_on_execute = RuntimeError("nope")
    monkeypatch.setattr(connect_duckdb, "prompt_yes_no", lambda *a, **k: False)
    monkeypatch.setattr(
        connect_duckdb, "prompt_text", lambda *a, **k: str(tmp_path / "wh.duckdb")
    )
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))
    rc = connect_duckdb.main(["prod"])
    assert rc == EXIT_USER_ERROR
    written = tmp_path / ".agentxp" / "credentials" / "duckdb" / "prod.yaml"
    assert not written.exists()


# ---------------------------------------------------------------------------
# Re-auth entry point
# ---------------------------------------------------------------------------


def test_reauth_requires_existing_profile(tmp_path: Path, patch_registry):
    with pytest.raises(FileNotFoundError):
        connect_common.reauth_profile("duckdb", "ghost", root=tmp_path)


def test_reauth_refreshes_existing_profile(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    # Seed an existing profile.
    connect_common.write_profile(
        "duckdb",
        "prod",
        {"adapter": "duckdb", "profile_name": "prod", "database": "old.duckdb"},
        root=tmp_path,
        quiet=True,
    )
    # Re-auth re-runs the wizard with a new path.
    monkeypatch.setattr(connect_duckdb, "prompt_yes_no", lambda *a, **k: False)
    monkeypatch.setattr(
        connect_duckdb, "prompt_text", lambda *a, **k: str(tmp_path / "new.duckdb")
    )
    ok, profile = connect_common.reauth_profile(
        "duckdb", "prod", root=tmp_path, quiet=True
    )
    assert ok is True
    assert profile["database"].endswith("new.duckdb")


# ---------------------------------------------------------------------------
# Wizard registration (extensibility for W2.B)
# ---------------------------------------------------------------------------


def test_wizards_registered():
    assert "duckdb" in connect_common.WIZARD_REGISTRY
    assert "bigquery" in connect_common.WIZARD_REGISTRY
    assert "snowflake" in connect_common.WIZARD_REGISTRY
    assert "databricks" in connect_common.WIZARD_REGISTRY
    assert connect_common.WIZARD_REGISTRY["duckdb"].dialect == "duckdb"
    assert connect_common.WIZARD_REGISTRY["snowflake"].dialect == "snowflake"
    assert connect_common.WIZARD_REGISTRY["databricks"].dialect == "databricks"


def test_dispatcher_routes_new_dialects():
    from agentxp.cli import connect as connect_router

    assert connect_router._WIZARD_MODULES["snowflake"] == (
        "agentxp.cli.connect_snowflake"
    )
    assert connect_router._WIZARD_MODULES["databricks"] == (
        "agentxp.cli.connect_databricks"
    )


# ---------------------------------------------------------------------------
# W2.B secret-handling helpers
#
# ``collect_secret`` lives in connect_common and reads the secret via
# ``connect_common.prompt_secret`` then asks (via ``connect_common.prompt_yes_no``)
# whether to store the raw value inline or an env-var reference. These helpers
# patch BOTH the per-wizard prompts and the connect_common secret prompts.
# ---------------------------------------------------------------------------


def _patch_secret(monkeypatch, value: str, *, inline: bool):
    """Patch connect_common's secret + yes/no prompts used by collect_secret."""
    monkeypatch.setattr(connect_common, "prompt_secret", lambda *a, **k: value)
    monkeypatch.setattr(connect_common, "prompt_yes_no", lambda *a, **k: inline)


# ---------------------------------------------------------------------------
# Snowflake wizard — four auth surfaces (W2.B)
# ---------------------------------------------------------------------------


def _patch_snowflake_common(monkeypatch, *, auth_method: str):
    """Stub the common (non-secret) Snowflake prompts."""
    texts = iter(
        [
            "myorg-acct",  # account
            "SVC_AGENTXP",  # user
            "WH_XS",  # warehouse
            "ANALYTICS",  # database
            "PUBLIC",  # schema
            "",  # role (optional)
        ]
    )
    monkeypatch.setattr(connect_snowflake, "prompt_text", lambda *a, **k: next(texts))
    monkeypatch.setattr(
        connect_snowflake, "prompt_choice", lambda *a, **k: auth_method
    )


def test_snowflake_collect_password_inline(monkeypatch):
    _patch_snowflake_common(monkeypatch, auth_method="password")
    _patch_secret(monkeypatch, "pw-PLANTED", inline=True)
    conn_params, profile = connect_snowflake.collect("prod")
    assert conn_params["auth_method"] == "password"
    assert conn_params["account"] == "myorg-acct"
    assert conn_params["user"] == "SVC_AGENTXP"
    assert conn_params["warehouse"] == "WH_XS"
    assert conn_params["password"] == "pw-PLANTED"
    assert profile["auth_method"] == "password"
    assert profile["adapter"] == "snowflake"
    assert profile["password"] == "pw-PLANTED"


def test_snowflake_collect_password_env_ref_default(monkeypatch):
    _patch_snowflake_common(monkeypatch, auth_method="password")
    _patch_secret(monkeypatch, "pw-PLANTED", inline=False)
    conn_params, profile = connect_snowflake.collect("prod")
    assert conn_params["password"] == "pw-PLANTED"
    assert profile["password"].startswith("env:")
    assert "pw-PLANTED" not in profile["password"]


def test_snowflake_collect_externalbrowser_no_secret(monkeypatch):
    _patch_snowflake_common(monkeypatch, auth_method="externalbrowser")

    def _boom(*a, **k):  # pragma: no cover - asserts not reached
        raise AssertionError("externalbrowser must not prompt for a secret")

    monkeypatch.setattr(connect_common, "prompt_secret", _boom)
    conn_params, profile = connect_snowflake.collect("prod")
    assert conn_params["auth_method"] == "externalbrowser"
    assert "password" not in conn_params
    assert "token" not in conn_params
    assert "private_key_file" not in conn_params


def test_snowflake_collect_oauth_branch(monkeypatch):
    _patch_snowflake_common(monkeypatch, auth_method="oauth")
    _patch_secret(monkeypatch, "tok-PLANTED", inline=True)
    conn_params, profile = connect_snowflake.collect("prod")
    assert conn_params["auth_method"] == "oauth"
    assert conn_params["token"] == "tok-PLANTED"
    assert profile["token"] == "tok-PLANTED"


def test_snowflake_collect_keypair_branch(monkeypatch):
    texts = iter(
        [
            "myorg-acct",
            "SVC_AGENTXP",
            "WH_XS",
            "ANALYTICS",
            "PUBLIC",
            "",  # role
            "/keys/rsa_key.p8",  # private key file path
        ]
    )
    monkeypatch.setattr(connect_snowflake, "prompt_text", lambda *a, **k: next(texts))
    monkeypatch.setattr(connect_snowflake, "prompt_choice", lambda *a, **k: "keypair")
    _patch_secret(monkeypatch, "pass-PLANTED", inline=True)
    conn_params, profile = connect_snowflake.collect("prod")
    assert conn_params["auth_method"] == "keypair"
    assert conn_params["private_key_file"].endswith("/keys/rsa_key.p8")
    assert profile["private_key_file"].endswith("/keys/rsa_key.p8")
    assert conn_params["private_key_file_pwd"] == "pass-PLANTED"


def test_snowflake_main_probes_and_redacts_secret(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    _patch_snowflake_common(monkeypatch, auth_method="password")
    _patch_secret(monkeypatch, "pw-PLANTED", inline=False)
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))

    rc = connect_snowflake.main(["prod"])
    assert rc == EXIT_OK

    assert _FakeAdapter.executed_sql == ["SELECT 1"]
    assert _FakeAdapter.last_init_kwargs["password"] == "pw-PLANTED"

    out = capsys.readouterr().out
    assert "pw-PLANTED" not in out
    assert "[REDACTED]" in out

    written = tmp_path / ".agentxp" / "credentials" / "snowflake" / "prod.yaml"
    assert written.exists()
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert "pw-PLANTED" not in written.read_text()
    loaded = yaml.safe_load(written.read_text())
    assert loaded["auth_method"] == "password"
    assert loaded["password"].startswith("env:")


def test_snowflake_password_inline_redacted_in_stdout(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    """Even when the user opts to store inline, the secret never reaches stdout."""
    _patch_snowflake_common(monkeypatch, auth_method="password")
    _patch_secret(monkeypatch, "pw-PLANTED", inline=True)
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))

    rc = connect_snowflake.main(["prod"])
    assert rc == EXIT_OK

    out = capsys.readouterr().out
    assert "pw-PLANTED" not in out
    assert "[REDACTED]" in out

    written = tmp_path / ".agentxp" / "credentials" / "snowflake" / "prod.yaml"
    assert stat.S_IMODE(written.stat().st_mode) == 0o600


def test_snowflake_keypair_passphrase_env_ref_never_in_file_or_stdout(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    texts = iter(
        [
            "myorg-acct",
            "SVC_AGENTXP",
            "",  # warehouse
            "",  # database
            "",  # schema
            "",  # role
            "/keys/rsa_key.p8",
        ]
    )
    monkeypatch.setattr(connect_snowflake, "prompt_text", lambda *a, **k: next(texts))
    monkeypatch.setattr(connect_snowflake, "prompt_choice", lambda *a, **k: "keypair")
    _patch_secret(monkeypatch, "PASSPHRASE-PLANTED", inline=False)
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))

    rc = connect_snowflake.main(["prod"])
    assert rc == EXIT_OK

    out = capsys.readouterr().out
    assert "PASSPHRASE-PLANTED" not in out

    written = tmp_path / ".agentxp" / "credentials" / "snowflake" / "prod.yaml"
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert "PASSPHRASE-PLANTED" not in written.read_text()
    loaded = yaml.safe_load(written.read_text())
    assert loaded["private_key_file"].endswith("/keys/rsa_key.p8")
    assert loaded["private_key_file_pwd"].startswith("env:")


def test_snowflake_password_empty_is_user_error(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    _patch_snowflake_common(monkeypatch, auth_method="password")
    _patch_secret(monkeypatch, "", inline=False)
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))
    rc = connect_snowflake.main(["prod"])
    assert rc == EXIT_USER_ERROR
    written = tmp_path / ".agentxp" / "credentials" / "snowflake" / "prod.yaml"
    assert not written.exists()


# ---------------------------------------------------------------------------
# Databricks wizard — PAT vs OAuth M2M (W2.B)
# ---------------------------------------------------------------------------


def _patch_databricks_common(monkeypatch, *, auth_method: str, extra_text=None):
    base = [
        "adb-1234.5.azuredatabricks.net",  # server_hostname
        "/sql/1.0/warehouses/abc123",  # http_path
        "",  # catalog (optional)
        "",  # schema (optional)
    ]
    if extra_text:
        base += list(extra_text)
    texts = iter(base)
    monkeypatch.setattr(connect_databricks, "prompt_text", lambda *a, **k: next(texts))
    monkeypatch.setattr(
        connect_databricks, "prompt_choice", lambda *a, **k: auth_method
    )


def test_databricks_collect_pat_branch(monkeypatch):
    _patch_databricks_common(monkeypatch, auth_method="pat")
    _patch_secret(monkeypatch, "dapi-PLANTED", inline=True)
    conn_params, profile = connect_databricks.collect("prod")
    assert conn_params["auth_method"] == "pat"
    assert conn_params["server_hostname"] == "adb-1234.5.azuredatabricks.net"
    assert conn_params["http_path"] == "/sql/1.0/warehouses/abc123"
    assert conn_params["access_token"] == "dapi-PLANTED"
    assert profile["auth_method"] == "pat"
    assert profile["adapter"] == "databricks"


def test_databricks_collect_oauth_m2m_branch(monkeypatch):
    _patch_databricks_common(
        monkeypatch, auth_method="oauth_m2m", extra_text=["client-app-id"]
    )
    _patch_secret(monkeypatch, "secret-PLANTED", inline=True)
    conn_params, profile = connect_databricks.collect("prod")
    assert conn_params["auth_method"] == "oauth_m2m"
    assert conn_params["client_id"] == "client-app-id"
    assert conn_params["client_secret"] == "secret-PLANTED"
    assert profile["client_id"] == "client-app-id"


def test_databricks_main_pat_probes_and_redacts(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    _patch_databricks_common(monkeypatch, auth_method="pat")
    _patch_secret(monkeypatch, "dapi-PLANTED", inline=False)
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))

    rc = connect_databricks.main(["prod"])
    assert rc == EXIT_OK

    assert _FakeAdapter.executed_sql == ["SELECT 1"]
    assert _FakeAdapter.last_init_kwargs["access_token"] == "dapi-PLANTED"

    out = capsys.readouterr().out
    # access_token is NOT in adapter._SENSITIVE_KEYS; connect_common must scrub
    # it via _EXTRA_SECRET_KEYS.
    assert "dapi-PLANTED" not in out

    written = tmp_path / ".agentxp" / "credentials" / "databricks" / "prod.yaml"
    assert written.exists()
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert "dapi-PLANTED" not in written.read_text()
    loaded = yaml.safe_load(written.read_text())
    assert loaded["auth_method"] == "pat"
    assert loaded["access_token"].startswith("env:")


def test_databricks_pat_inline_token_redacted_in_stdout(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    """Inline-stored PAT must still never reach stdout — proves the
    _EXTRA_SECRET_KEYS coverage for access_token."""
    _patch_databricks_common(monkeypatch, auth_method="pat")
    _patch_secret(monkeypatch, "dapi-PLANTED", inline=True)
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))

    rc = connect_databricks.main(["prod"])
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert "dapi-PLANTED" not in out
    assert "[REDACTED]" in out


def test_databricks_main_oauth_m2m_secret_never_in_stdout(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    _patch_databricks_common(
        monkeypatch, auth_method="oauth_m2m", extra_text=["client-app-id"]
    )
    _patch_secret(monkeypatch, "secret-PLANTED", inline=False)
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))

    rc = connect_databricks.main(["prod"])
    assert rc == EXIT_OK

    out = capsys.readouterr().out
    assert "secret-PLANTED" not in out

    written = tmp_path / ".agentxp" / "credentials" / "databricks" / "prod.yaml"
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert "secret-PLANTED" not in written.read_text()
    loaded = yaml.safe_load(written.read_text())
    assert loaded["client_id"] == "client-app-id"
    assert loaded["client_secret"].startswith("env:")


def test_databricks_pat_empty_is_user_error(
    tmp_path: Path, monkeypatch, patch_registry, capsys
):
    _patch_databricks_common(monkeypatch, auth_method="pat")
    _patch_secret(monkeypatch, "", inline=False)
    monkeypatch.setattr(connect_common.Path, "home", classmethod(lambda cls: tmp_path))
    rc = connect_databricks.main(["prod"])
    assert rc == EXIT_USER_ERROR
    written = tmp_path / ".agentxp" / "credentials" / "databricks" / "prod.yaml"
    assert not written.exists()
