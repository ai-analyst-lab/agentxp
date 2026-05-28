"""agentxp connect duckdb — register a DuckDB credential profile (W2.A).

The simplest wizard: DuckDB has no credential surface (``auth_kind="none"``).
It prompts for the database file path (or in-memory), live-probes with
``SELECT 1``, and writes the profile to
``~/.agentxp/credentials/duckdb/{name}.yaml``.

For a true one-off (no profile needed), ``agentxp profile <file>`` already
takes a path directly — the wizard suggests that when the user picks
in-memory, since an in-memory profile points at nothing reusable.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 / §18.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Optional

from agentxp.cli.connect_common import (
    ConnectWizard,
    prompt_text,
    prompt_yes_no,
    reauth_profile,
    register_wizard,
    run_wizard,
)
from agentxp.cli.exit_codes import EXIT_FATAL, EXIT_OK, EXIT_USER_ERROR

__all__ = ["main", "collect"]

DIALECT = "duckdb"


def collect(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prompt for DuckDB connection details.

    Returns ``(conn_params, profile)``:
      * ``conn_params`` — ``{"file_path": Path | None}`` for the adapter.
      * ``profile`` — the YAML-serialisable profile (DuckDB has no secrets).
    """
    print(
        "DuckDB has no credentials — only a database file path (or in-memory).",
        file=sys.stderr,
    )
    in_memory = prompt_yes_no(
        "Use an in-memory database?", default=False
    )

    if in_memory:
        print(
            "Note: an in-memory DuckDB profile points at nothing reusable. "
            "For a one-off, prefer `agentxp profile <file>` instead.",
            file=sys.stderr,
        )
        conn_params: dict[str, Any] = {"file_path": None}
        profile: dict[str, Any] = {
            "schema_version": 1,
            "adapter": DIALECT,
            "auth_kind": "none",
            "profile_name": name,
            "in_memory": True,
        }
        return conn_params, profile

    path_str = prompt_text("DuckDB database file path (e.g. ./warehouse.duckdb)")
    file_path = Path(path_str).expanduser()
    conn_params = {"file_path": file_path}
    profile = {
        "schema_version": 1,
        "adapter": DIALECT,
        "auth_kind": "none",
        "profile_name": name,
        "database": str(file_path),
    }
    return conn_params, profile


# Register on import so the dispatcher resolves `connect duckdb` to us.
register_wizard(ConnectWizard(DIALECT, collect))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentxp connect duckdb",
        description=(
            "Register a DuckDB credential profile under "
            "~/.agentxp/credentials/duckdb/. Prompts for a database file path "
            "(or in-memory), live-probes with SELECT 1, and writes the profile."
        ),
    )
    parser.add_argument(
        "name",
        help="Profile name (e.g. 'prod', 'dev'). Stored as {name}.yaml.",
    )
    parser.add_argument(
        "--reauth",
        action="store_true",
        help="Refresh an EXISTING profile (re-run collect + live-probe).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-error output.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point. Returns an EXIT_* code (see exit_codes.py)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.reauth:
            ok, _ = reauth_profile(DIALECT, args.name, quiet=args.quiet)
        else:
            ok, _ = run_wizard(DIALECT, args.name, quiet=args.quiet)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return EXIT_USER_ERROR
    except KeyboardInterrupt:  # pragma: no cover — interactive abort
        print("\naborted", file=sys.stderr)
        return EXIT_USER_ERROR
    except Exception as e:
        print(f"unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_FATAL

    if not ok:
        print("connection probe failed — profile not written", file=sys.stderr)
        return EXIT_USER_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
