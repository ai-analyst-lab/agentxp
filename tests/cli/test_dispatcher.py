"""Tests for openxp.cli.__main__ dispatcher."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, Mock

import pytest

from openxp.cli import __main__ as dispatcher
from openxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR


def test_no_args_prints_help_and_returns_ok(capsys):
    rc = dispatcher.main([])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "usage: openxp" in captured.out
    assert "profile" in captured.out


def test_dash_h_prints_help(capsys):
    rc = dispatcher.main(["-h"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "Subcommands:" in captured.out


def test_double_dash_help_prints_help(capsys):
    rc = dispatcher.main(["--help"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "usage: openxp" in captured.out


def test_version_flag(capsys):
    rc = dispatcher.main(["--version"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "openxp" in captured.out
    # version-shaped: contains at least one digit and a dot
    assert any(ch.isdigit() for ch in captured.out)
    assert "." in captured.out


def test_unknown_subcommand_returns_user_error(capsys):
    rc = dispatcher.main(["foo"])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "unknown subcommand 'foo'" in captured.err


def test_placeholder_subcommand_returns_user_error(capsys):
    rc = dispatcher.main(["connect"])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "ships in W_sql" in captured.err


def test_dispatch_to_profile_main():
    mock_main = Mock(return_value=7)
    with patch("openxp.cli.profile.main", mock_main):
        rc = dispatcher.main(["profile", "/tmp/x.parquet"])
    assert rc == 7
    mock_main.assert_called_once_with(["/tmp/x.parquet"])


def test_argparse_help_forwarded_to_subcommand():
    def raise_help(argv):
        raise SystemExit(0)
    with patch("openxp.cli.profile.main", side_effect=raise_help):
        rc = dispatcher.main(["profile", "--help"])
    assert rc == EXIT_OK
