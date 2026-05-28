"""CLI stub: ``agentxp migrate state <exp_id>``.

In v0.1 this command is a no-op stub that prints a friendly message and exits
zero. It exists so the load-refusal contract in :mod:`agentxp.schemas._versioning`
can point users at a real command (``SchemaVersionTooOld`` messages tell the
user to run ``agentxp migrate state <exp_id>``).

In v0.5+ when the first major schema bump happens, the migration logic for
``schema_version: N → N+1`` lives here: rewrite old files in place with a
``.bak`` backup, then emit a ``stage.committed(metadata.subtype=
"schema_migration", metadata.from=N, metadata.to=N+1)`` audit row (per
§1.7.6 + §1.8.5).

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §1.7.6 migration command.
"""
from __future__ import annotations

import argparse
import sys

from agentxp.cli.exit_codes import EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``agentxp migrate state <exp_id>``.

    Returns ``EXIT_OK`` (0) in v0.1 — there is nothing to migrate yet.
    """
    parser = argparse.ArgumentParser(
        prog="agentxp migrate state",
        description=(
            "Migrate an experiment's persisted state files from a prior "
            "schema_version to the version supported by this AgentXP."
        ),
    )
    parser.add_argument(
        "experiment_id",
        help="Experiment ID to migrate (matches the directory under experiments/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing.",
    )
    args = parser.parse_args(argv)

    print(f"No migrations needed for experiment {args.experiment_id}.")
    print(
        "v0.1 ships with state.yaml v3, experiment.yaml v2, data_plan.yaml v2, "
        "metrics/*.yaml v2; all other persisted files are at v1."
    )
    print(
        "Migration logic will be added in v0.5+ when the first major "
        "schema_version bump occurs (see OPENXP_V01_PLAN.md §1.7.6)."
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
