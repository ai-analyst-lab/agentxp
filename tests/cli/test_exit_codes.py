"""Closure test for CLI exit codes."""
from openxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR, EXIT_WARNING, EXIT_FATAL


def test_exit_codes_are_canonical_values():
    assert EXIT_OK == 0
    assert EXIT_USER_ERROR == 1
    assert EXIT_WARNING == 2
    assert EXIT_FATAL == 3


def test_exit_codes_are_distinct():
    codes = {EXIT_OK, EXIT_USER_ERROR, EXIT_WARNING, EXIT_FATAL}
    assert len(codes) == 4


def test_exit_codes_are_integers():
    for code in (EXIT_OK, EXIT_USER_ERROR, EXIT_WARNING, EXIT_FATAL):
        assert isinstance(code, int)
        assert 0 <= code <= 255  # standard exit code range
