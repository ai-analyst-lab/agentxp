"""CLI exit-code constants for AgentXP v0.1.

Four values used across all agentxp CLI commands. Sourced from W_pre0 §1.8 canonical
constants. Closure-tested.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §1.8 (exit-code constants).
"""
from __future__ import annotations

EXIT_OK: int = 0
"""Command completed successfully."""

EXIT_USER_ERROR: int = 1
"""User input was invalid; the command refused to run. Examples: malformed YAML in user-supplied brief, invalid experiment_id."""

EXIT_WARNING: int = 2
"""Command completed but with caveats. Examples: voice-CI banned-phrase warning shipped to stderr; chain validation perf warning.

Note: argparse also exits 2 on a usage error. Subcommands signal a warning by
*returning* this value; argparse signals a usage error by *raising*
SystemExit(2). The top-level dispatcher (``agentxp.cli.__main__``) tells the two
apart and normalizes the raised argparse 2 to :data:`EXIT_USER_ERROR`, so the
process exit code is unambiguous to callers."""

EXIT_FATAL: int = 3
"""Internal error, unrecoverable. Examples: corrupted state.yaml, disk full, validate_chain hard-cap exceeded."""

__all__ = ["EXIT_OK", "EXIT_USER_ERROR", "EXIT_WARNING", "EXIT_FATAL"]
