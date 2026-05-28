"""agentxp connect <dialect> — dispatcher to the per-dialect connect wizards.

``agentxp connect duckdb prod`` / ``agentxp connect bigquery prod`` register a
warehouse credential profile under ``~/.agentxp/credentials/{dialect}/``.

This module is a thin router: it imports the wizard modules (which register
themselves in :data:`agentxp.cli.connect_common.WIZARD_REGISTRY` on import),
resolves the requested dialect to its ``main`` entry point, and forwards the
remaining argv. W2.B drops ``connect_snowflake`` / ``connect_databricks`` into
``_WIZARD_MODULES`` and the new dialects work with no other change.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §12 / §18.
"""
from __future__ import annotations

import importlib
import sys
from typing import Callable, Optional

from agentxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR

__all__ = ["main"]

#: dialect → wizard module path. Each module exposes ``main(argv)`` and
#: registers a ConnectWizard on import. W2.B extends this map (snowflake,
#: databricks) — the dispatcher needs no other change.
_WIZARD_MODULES: dict[str, str] = {
    "duckdb": "agentxp.cli.connect_duckdb",
    "bigquery": "agentxp.cli.connect_bigquery",
    "snowflake": "agentxp.cli.connect_snowflake",
    "databricks": "agentxp.cli.connect_databricks",
}


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for ``agentxp connect``. Routes by dialect."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        _print_help(sys.stdout)
        return EXIT_OK

    dialect = argv[0]
    rest = argv[1:]

    module_path = _WIZARD_MODULES.get(dialect)
    if module_path is None:
        print(
            f"agentxp connect: unknown dialect {dialect!r}",
            file=sys.stderr,
        )
        _print_help(sys.stderr)
        return EXIT_USER_ERROR

    module = importlib.import_module(module_path)
    fn: Callable[[Optional[list[str]]], int] = getattr(module, "main")
    try:
        return fn(rest)
    except SystemExit as e:  # argparse --help / parse errors inside the wizard
        return int(e.code) if e.code is not None else EXIT_OK


def _print_help(stream) -> None:
    print("usage: agentxp connect <dialect> <name> [options]", file=stream)
    print("", file=stream)
    print("Register a warehouse credential profile under", file=stream)
    print("  ~/.agentxp/credentials/{dialect}/{name}.yaml", file=stream)
    print("", file=stream)
    print("Dialects:", file=stream)
    for name in _WIZARD_MODULES:
        print(f"  {name}", file=stream)
    print("", file=stream)
    print(
        "Run `agentxp connect <dialect> --help` for dialect-specific options.",
        file=stream,
    )


if __name__ == "__main__":
    sys.exit(main())
