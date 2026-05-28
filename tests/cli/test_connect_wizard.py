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

from agentxp.cli import connect_bigquery, connect_common, connect_duckdb
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
    assert connect_common.WIZARD_REGISTRY["duckdb"].dialect == "duckdb"
