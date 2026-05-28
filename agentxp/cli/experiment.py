"""agentxp experiment — v0.1 entry-point placeholder for the 11-stage journey (W5.2).

The full agent orchestration in v0.1 is driven by Claude Code reading the
``agents/*.system.md`` prompts and dispatching through ``orchestrator.dispatch``;
this CLI does not run a long-lived Python loop. It prints guidance so the
user knows how to start the experiment conversation. v0.2+ may fork a
long-lived orchestrator process from this entry point.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §10 / W5.2.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from agentxp.cli.exit_codes import EXIT_OK

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentxp /experiment",
        description=(
            "Start a new experiment. In v0.1 this prints guidance for opening "
            "the project in Claude Code, which drives the 11-stage journey."
        ),
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="Path to a data file (parquet/csv/json) to seed Stage 0.",
    )
    parser.add_argument(
        "--brief",
        type=Path,
        default=None,
        help="Path to an existing brief YAML to resume from Stage 3.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Project root (default: cwd).",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Print the Claude-Code-driven start-up guidance. Always returns EXIT_OK."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    print("AgentXP v0.1 — experiment orchestration", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "v0.1 is driven through Claude Code conversation, not a CLI runtime.",
        file=sys.stderr,
    )
    print("To start an experiment:", file=sys.stderr)
    print("  1. Open this directory in Claude Code: `claude`", file=sys.stderr)
    if args.data is not None:
        print(
            f"  2. Tell Claude: 'I want to test something with my data at {args.data}'",
            file=sys.stderr,
        )
    elif args.brief is not None:
        print(
            f"  2. Tell Claude: 'Resume the brief at {args.brief}'",
            file=sys.stderr,
        )
    else:
        print("  2. Tell Claude what you want to test in plain English", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "Claude will walk you through the 11 stages, using the agent prompts at",
        file=sys.stderr,
    )
    print("`agents/*.system.md`. See README.md for details.", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
