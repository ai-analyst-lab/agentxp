"""CLI dispatcher for the agentxp binary.

v0.1: only `agentxp profile` is wired. The other six subcommands print a
"ships in <wave>" message and exit with EXIT_USER_ERROR. W5 / W_sql /
W_hooks fill in the registry rows as their CLIs land.

Entry point per pyproject.toml `[project.scripts] agentxp = agentxp.cli.__main__:main`.

Also callable via `python -m agentxp`.
"""
from __future__ import annotations

import importlib
import sys
from typing import Callable, Optional

from agentxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR

# Subcommand registry. Value is either:
#   - tuple[str, str] — (module_path, function_name) to dispatch to
#   - str             — wave id where the subcommand will ship (placeholder)
SUBCOMMANDS: dict[str, tuple[str, str] | str] = {
    "profile":    ("agentxp.cli.profile", "main"),    # W_pre2 — wired
    "list":       ("agentxp.cli.list", "main"),       # W5.6 — wired
    "unlock":     ("agentxp.cli.unlock", "main"),     # W5.7 — wired
    "resume":     ("agentxp.cli.resume", "main"),     # W5.3 — wired
    "connect":    ("agentxp.cli.connect", "main"),    # W2.A — wired
    "audit":      ("agentxp.cli.audit", "main"),       # §15 — wired
    "experiment": ("agentxp.cli.experiment", "main"), # W5.2 — wired
}


def main(argv: Optional[list[str]] = None) -> int:
    """Top-level entry. Dispatches to subcommand or prints help."""
    if argv is None:
        argv = sys.argv[1:]

    # No args, or top-level help — print usage, exit 0
    if not argv or argv[0] in ("-h", "--help"):
        _print_help(sys.stdout)
        return EXIT_OK

    # Version flag — print and exit
    if argv[0] in ("-V", "--version"):
        _print_version(sys.stdout)
        return EXIT_OK

    subcommand = argv[0]
    rest = argv[1:]

    if subcommand not in SUBCOMMANDS:
        print(f"agentxp: unknown subcommand {subcommand!r}", file=sys.stderr)
        _print_help(sys.stderr)
        return EXIT_USER_ERROR

    target = SUBCOMMANDS[subcommand]

    # Placeholder — not yet wired
    if isinstance(target, str):
        print(
            f"agentxp {subcommand}: not yet implemented (ships in {target})",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    # Dispatched — dynamic import, call main(argv)
    module_name, fn_name = target
    module = importlib.import_module(module_name)
    fn: Callable[[Optional[list[str]]], int] = getattr(module, fn_name)
    try:
        return fn(rest)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else EXIT_OK
        # argparse raises SystemExit(2) on a usage error (unknown flag, missing
        # required arg). That is a user-input error, not a "completed with
        # warnings" result — and EXIT_WARNING is also 2, so passing argparse's
        # code through would be ambiguous to a caller. Normalize argparse's 2 to
        # EXIT_USER_ERROR. Real warnings are *returned* (not raised), so they
        # never reach this branch.
        if code == 2:
            return EXIT_USER_ERROR
        return code


def _print_help(stream) -> None:
    print("usage: agentxp <subcommand> [args]", file=stream)
    print("", file=stream)
    print("Subcommands:", file=stream)
    for name, target in SUBCOMMANDS.items():
        if isinstance(target, str):
            status = f"(ships in {target})"
        else:
            status = "(v0.1)"
        print(f"  {name:<12} {status}", file=stream)
    print("", file=stream)
    print("Run `agentxp <subcommand> --help` for subcommand-specific options.", file=stream)


def _print_version(stream) -> None:
    try:
        from importlib.metadata import version
        v = version("agentxp")
    except Exception:
        v = "0.1.0"
    print(f"agentxp {v}", file=stream)


if __name__ == "__main__":
    sys.exit(main())
