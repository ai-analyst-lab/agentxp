"""Tests for agentxp.cli.__main__ dispatcher."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, Mock

import pytest

from agentxp.cli import __main__ as dispatcher
from agentxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR


def test_no_args_prints_help_and_returns_ok(capsys):
    rc = dispatcher.main([])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "usage: agentxp" in captured.out
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
    assert "usage: agentxp" in captured.out


def test_version_flag(capsys):
    rc = dispatcher.main(["--version"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "agentxp" in captured.out
    # version-shaped: contains at least one digit and a dot
    assert any(ch.isdigit() for ch in captured.out)
    assert "." in captured.out


def test_unknown_subcommand_returns_user_error(capsys):
    rc = dispatcher.main(["foo"])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "unknown subcommand 'foo'" in captured.err


def test_placeholder_subcommand_returns_user_error(capsys):
    # `connect` is now wired (W2.A), so inject a synthetic placeholder row to
    # exercise the "not yet implemented" dispatch path.
    with patch.dict(
        dispatcher.SUBCOMMANDS,
        {"future": "W_future (placeholder)"},
        clear=False,
    ):
        rc = dispatcher.main(["future"])
    captured = capsys.readouterr()
    assert rc == EXIT_USER_ERROR
    assert "ships in W_future" in captured.err


def test_connect_is_wired(capsys):
    # `connect` dispatches to the connect router; with no dialect it prints
    # help and exits OK (the router's own help path).
    rc = dispatcher.main(["connect"])
    captured = capsys.readouterr()
    assert rc == EXIT_OK
    assert "connect <dialect>" in captured.out


def test_dispatch_to_profile_main():
    mock_main = Mock(return_value=7)
    with patch("agentxp.cli.profile.main", mock_main):
        rc = dispatcher.main(["profile", "/tmp/x.parquet"])
    assert rc == 7
    mock_main.assert_called_once_with(["/tmp/x.parquet"])


def test_argparse_help_forwarded_to_subcommand():
    def raise_help(argv):
        raise SystemExit(0)
    with patch("agentxp.cli.profile.main", side_effect=raise_help):
        rc = dispatcher.main(["profile", "--help"])
    assert rc == EXIT_OK


def test_argparse_usage_error_normalized_to_user_error():
    # argparse exits SystemExit(2) on a usage error. Since EXIT_WARNING is also
    # 2, the dispatcher normalizes the raised 2 to EXIT_USER_ERROR so callers
    # can tell "bad flags" from "completed with warnings".
    def raise_usage(argv):
        raise SystemExit(2)
    with patch("agentxp.cli.profile.main", side_effect=raise_usage):
        rc = dispatcher.main(["profile", "--bogus-flag"])
    assert rc == EXIT_USER_ERROR


def test_returned_warning_code_passes_through():
    # A subcommand that *returns* 2 (EXIT_WARNING) is a real warning, not an
    # argparse usage error, and must pass through unchanged.
    with patch("agentxp.cli.profile.main", Mock(return_value=2)):
        rc = dispatcher.main(["profile", "/tmp/x.parquet"])
    assert rc == 2
