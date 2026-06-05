"""Tests for agentxp.workflows.connect (V15) — non-interactive only."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from agentxp.workflows.connect import run_wizard


def test_run_wizard_unknown_dialect_raises():
    with pytest.raises(KeyError):
        run_wizard("postgres", interactive=False, overrides={})


def test_run_wizard_non_interactive_requires_overrides():
    with pytest.raises(ValueError):
        run_wizard("duckdb", interactive=False)


def test_run_wizard_duckdb_writes_credential_file(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("AGENTXP_HOME", tmp)
        out = run_wizard(
            "duckdb",
            interactive=False,
            overrides={"profile_name": "demo", "db_path": "/x/foo.duckdb"},
        )
        assert out.exists()
        # chmod 600
        assert (os.stat(out).st_mode & 0o777) == 0o600
        loaded = yaml.safe_load(out.read_text())
        assert loaded["dialect"] == "duckdb"
        assert loaded["db_path"] == "/x/foo.duckdb"


def test_run_wizard_snowflake_validates_required_fields(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("AGENTXP_HOME", tmp)
        with pytest.raises(ValueError) as excinfo:
            run_wizard(
                "snowflake",
                interactive=False,
                overrides={"profile_name": "prod"},
            )
        assert "account" in str(excinfo.value) or "user" in str(excinfo.value)


def test_run_wizard_bigquery_uses_defaults(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("AGENTXP_HOME", tmp)
        out = run_wizard(
            "bigquery",
            interactive=False,
            overrides={
                "profile_name": "prod",
                "project_id": "my-project",
                "dataset": "analytics",
            },
        )
        loaded = yaml.safe_load(out.read_text())
        assert loaded["location"] == "US"  # default
        assert loaded["project_id"] == "my-project"
