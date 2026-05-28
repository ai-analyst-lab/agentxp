"""agentxp profile — Stage-0 profiler CLI (W_pre2.4).

Wires the fast SUMMARIZE-based driver (W_pre2.1) and the optional
ydata-profiling deep sidecar (W_pre2.3) into a single ``agentxp profile``
entry point. Default path writes ``bundles/profiler.out.yaml`` only;
``--deep`` additionally emits an HTML (and optional JSON) deep report.

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §3 / §5 / HG-D4.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from agentxp.cli.exit_codes import (
    EXIT_FATAL,
    EXIT_OK,
    EXIT_USER_ERROR,
    EXIT_WARNING,
)

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentxp profile",
        description=(
            "Run the Stage-0 profiler on a parquet/csv/json/jsonl file "
            "or a qualified warehouse table. Writes a profiler.out.yaml "
            "bundle and, with --deep, a ydata-profiling HTML report."
        ),
    )
    parser.add_argument(
        "source_ref",
        help=(
            "Path to file (parquet/csv/json/jsonl) OR a qualified warehouse "
            "table name."
        ),
    )
    parser.add_argument(
        "--file",
        dest="file",
        type=Path,
        default=None,
        help="Explicit file path (overrides treating source_ref as a path).",
    )
    parser.add_argument(
        "--adapter",
        choices=("duckdb", "snowflake", "bigquery", "databricks"),
        default="duckdb",
        help="Warehouse adapter (default: duckdb).",
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path("./bundles/profiler.out.yaml"),
        help="Where to write profiler.out.yaml (default: ./bundles/profiler.out.yaml).",
    )
    parser.add_argument(
        "--sample-values-n",
        type=int,
        default=10,
        help="Max sample values per column (default: 10).",
    )
    parser.add_argument(
        "--flag-null-rate",
        type=float,
        default=0.5,
        help="Null-rate threshold for the HG-D4 flag (default: 0.5).",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Also run the ydata-profiling deep sidecar.",
    )
    parser.add_argument(
        "--deep-html",
        type=Path,
        default=None,
        help=(
            "Where to write the deep HTML report "
            "(default: ./bundles/profiler.deep.html). Implies --deep."
        ),
    )
    parser.add_argument(
        "--deep-json",
        type=Path,
        default=None,
        help="Also emit a JSON sidecar from ydata.",
    )
    parser.add_argument(
        "--deep-minimal",
        action="store_true",
        help="Pass minimal=True to ydata (fast path on wide tables).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print column table to stderr after profiling.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-error output.",
    )
    return parser


def _validate_path_under_allowed_roots(path: Path, *, arg_name: str) -> Path:
    """Resolve path and assert it's under cwd or ~/.agentxp/.

    Raises ValueError with a user-facing message naming the arg if the
    resolved path is outside both allowed roots. Symlinks are followed by
    Path.resolve(), so a symlink pointing outside cwd is rejected.

    Args:
        path: the path the user supplied (typically from argparse)
        arg_name: name of the CLI flag, used in the error message
            (e.g. "--bundle")
    """
    resolved = path.resolve()
    cwd = Path.cwd().resolve()
    agentxp_home = (Path.home() / ".agentxp").resolve()
    for root in (cwd, agentxp_home):
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError(
        f"{arg_name} path must be under {cwd} or {agentxp_home}; got {resolved}"
    )


def _resolve_file_path(source_ref: str, explicit: Optional[Path]) -> Optional[Path]:
    if explicit is not None:
        return explicit
    # source_ref doubles as a path when it points to something that exists.
    candidate = Path(source_ref)
    if candidate.exists():
        return candidate
    return None


def _render_column_table(report) -> str:
    """Compact column table matching agents/fixtures/voice_samples/profiler_sample.md."""
    header = (
        f"{'column':<22}{'type':<11}{'null%':<8}{'sample':<24}flag\n"
        + "-" * 70
    )
    lines = [header]
    for c in report.columns:
        sample = (c.sample_values[0] if c.sample_values else "")
        if len(sample) > 22:
            sample = sample[:21] + "..."
        flag = c.flag_reason if c.flagged_for_review else ""
        null_pct = f"{c.null_rate * 100:.0f}%"
        lines.append(
            f"{c.name[:21]:<22}{c.dtype:<11}{null_pct:<8}{sample:<24}{flag}"
        )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point. Returns an EXIT_* code (see exit_codes.py)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Path guards — write only under cwd or ~/.agentxp/
    try:
        args.bundle = _validate_path_under_allowed_roots(
            args.bundle, arg_name="--bundle"
        )
        if args.deep_html is not None:  # may be unset if --deep not passed
            args.deep_html = _validate_path_under_allowed_roots(
                args.deep_html, arg_name="--deep-html"
            )
        if args.deep_json is not None:
            args.deep_json = _validate_path_under_allowed_roots(
                args.deep_json, arg_name="--deep-json"
            )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return EXIT_USER_ERROR

    # --deep-html / --deep-json / --deep-minimal all imply --deep.
    deep_requested = bool(
        args.deep or args.deep_html or args.deep_json or args.deep_minimal
    )
    deep_html_path = args.deep_html or Path("./bundles/profiler.deep.html")

    # Deferred import — driver pulls in duckdb (optional extra); keep CLI
    # importable for --help even when duckdb isn't installed.
    try:
        from agentxp.profiler.driver import profile_dataset, write_profile_bundle
    except ImportError as e:
        print(f"unexpected error: ImportError: {e}", file=sys.stderr)
        return EXIT_FATAL

    file_path = _resolve_file_path(args.source_ref, args.file)

    # If the user supplied --file or a path-shaped source_ref that doesn't
    # exist, fail fast with a clear message before touching the driver.
    if args.file is not None and not args.file.exists():
        print(f"file not found: {args.file}", file=sys.stderr)
        return EXIT_USER_ERROR
    # Heuristic: source_ref looks like a path (has a known suffix) but doesn't
    # exist — fail fast. Avoid false positives on warehouse refs like
    # ``schema.table``.
    if args.file is None and file_path is None:
        suffix = Path(args.source_ref).suffix.lower()
        if suffix in {".parquet", ".csv", ".json", ".jsonl", ".tsv", ".ndjson", ".duckdb"}:
            print(f"file not found: {args.source_ref}", file=sys.stderr)
            return EXIT_USER_ERROR

    try:
        report = profile_dataset(
            args.source_ref,
            adapter_type=args.adapter,
            file_path=file_path,
            sample_values_n=args.sample_values_n,
            flag_null_rate_threshold=args.flag_null_rate,
        )
    except FileNotFoundError as e:
        target = file_path if file_path is not None else args.source_ref
        print(f"file not found: {target}", file=sys.stderr)
        return EXIT_USER_ERROR
    except NotImplementedError as e:
        print(str(e), file=sys.stderr)
        return EXIT_USER_ERROR
    except ValidationError as e:
        print(f"profile_dataset failed: {e}", file=sys.stderr)
        return EXIT_FATAL
    except Exception as e:
        print(
            f"unexpected error: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        return EXIT_FATAL

    try:
        write_profile_bundle(report, args.bundle)
    except Exception as e:
        print(
            f"unexpected error: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        return EXIT_FATAL

    if not args.quiet:
        print(f"wrote: {args.bundle}")

    if args.verbose:
        print(_render_column_table(report), file=sys.stderr)

    if deep_requested:
        # Deferred import keeps ydata optional at module-load time.
        from agentxp.profiler.ydata_sidecar import run_ydata_deep_profile

        try:
            run_ydata_deep_profile(
                args.source_ref,
                file_path=file_path,
                html_output_path=deep_html_path,
                json_output_path=args.deep_json,
                title=f"Deep profile: {args.source_ref}",
                minimal=args.deep_minimal,
            )
        except ImportError as e:
            print(str(e), file=sys.stderr)
            return EXIT_USER_ERROR
        except NotImplementedError:
            print(
                "deep profile of warehouse tables ships in v0.1.1",
                file=sys.stderr,
            )
            return EXIT_USER_ERROR
        except Exception as e:
            print(
                f"unexpected error: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            if args.verbose:
                traceback.print_exc(file=sys.stderr)
            return EXIT_FATAL

        if not args.quiet:
            print(f"wrote: {deep_html_path}")
            if args.deep_json is not None:
                print(f"wrote: {args.deep_json}")

    # Soft warning: profiling completed, but a column was flagged for review.
    if report.flagged_for_review:
        print(f"flag: {report.flag_reason}", file=sys.stderr)
        return EXIT_WARNING

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
