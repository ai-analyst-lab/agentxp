"""Router for ``agentxp migrate <state|metrics> ...``.

The top-level dispatcher (:mod:`agentxp.cli.__main__`) maps one token to one
``main`` callable, but ``migrate`` has two sub-subcommands. This router parses
the first token and forwards the remainder:

* ``state``   → :func:`agentxp.cli.migrate_state.main` — the no-op v0.1 state
  migrator the schema-version load-refusal contract points users to
  (``SchemaVersionTooOld`` / ``resume`` tell users to run
  ``agentxp migrate state <exp_id>``). Registering this router is what makes
  that recovery command actually resolve instead of "unknown subcommand".
* ``metrics`` → :func:`agentxp.cli.migrate_metrics.main` — the real v1→v2
  metric-YAML migrator.
"""
from __future__ import annotations

import sys

from agentxp.cli.exit_codes import EXIT_OK, EXIT_USER_ERROR

_SUBCOMMANDS = ("state", "metrics")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        _print_help(sys.stdout)
        return EXIT_OK

    sub = argv[0]
    rest = argv[1:]

    if sub == "state":
        from agentxp.cli.migrate_state import main as state_main

        return state_main(rest)
    if sub == "metrics":
        from agentxp.cli.migrate_metrics import main as metrics_main

        return metrics_main(rest)

    print(f"agentxp migrate: unknown target {sub!r}", file=sys.stderr)
    _print_help(sys.stderr)
    return EXIT_USER_ERROR


def _print_help(stream) -> None:
    print("usage: agentxp migrate <state|metrics> [args]", file=stream)
    print("", file=stream)
    print("Targets:", file=stream)
    print("  state    Migrate an experiment's persisted state files (no-op in v0.1).", file=stream)
    print("  metrics  Migrate metrics/*.yaml from v1 to v2.", file=stream)
    print("", file=stream)
    print("Run `agentxp migrate <target> --help` for target-specific options.", file=stream)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
