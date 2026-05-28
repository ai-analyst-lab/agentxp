"""openxp audit — the audit-trail CLI for an experiment (§15 / D4).

v0.1 ships 3 surfaces (Theme 7 cut, per D4 / M64):
  - ``openxp audit <exp_id>``                       — text timeline (default)
  - ``openxp audit <exp_id> --diff <other_exp_id>`` — pairwise diff
  - ``openxp audit <exp_id> --html``                — self-contained HTML report

Source spec: experimentation-platform/OPENXP_V01_PLAN.md §15.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from openxp.cli.exit_codes import (
    EXIT_FATAL,
    EXIT_OK,
    EXIT_USER_ERROR,
    EXIT_WARNING,
)

__all__ = ["main"]


# ──────────────────────────────────────────────────────────────────────────
# argparse setup
# ──────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openxp audit",
        description=(
            "Render the audit trail for an experiment. Default text "
            "timeline; use --diff for pairwise diff or --html for a "
            "self-contained report."
        ),
    )
    parser.add_argument(
        "exp_id",
        help="Experiment id (directory name under {project}/experiments/).",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Project root containing experiments/ (default: cwd).",
    )
    parser.add_argument(
        "--diff",
        dest="diff",
        default=None,
        help="Diff against another experiment id (text mode).",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Render the chain as a self-contained HTML report.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output path for --html (default: "
            "experiments/{exp_id}/audit.html)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the chain as a JSON array of events (for piping).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-essential output (headers, footers).",
    )
    return parser


# ──────────────────────────────────────────────────────────────────────────
# Disk helpers (shared with audit_html.py and prune.py)
# ──────────────────────────────────────────────────────────────────────────


def _resolve_exp_dir(project: Optional[Path], exp_id: str) -> Path:
    root = (project if project is not None else Path.cwd()).resolve()
    return root / "experiments" / exp_id


def _load_log_events(exp_dir: Path) -> list[dict]:
    """Read log.jsonl from disk. Returns [] when missing or empty."""
    log_path = exp_dir / "log.jsonl"
    if not log_path.exists():
        return []
    events: list[dict] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _load_decisions(exp_dir: Path) -> list[tuple[str, str]]:
    """Read decisions/*.yaml as (filename, raw_text) pairs, sorted.

    Returns [] when the directory doesn't exist (W_hooks.3 not done yet).
    The renderer treats decisions as pretty-printed raw YAML — no schema
    coupling here so the audit CLI works even if the decisions writer hasn't
    landed.
    """
    decisions_dir = exp_dir / "decisions"
    if not decisions_dir.exists():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(decisions_dir.glob("*.yaml")):
        try:
            out.append((path.name, path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return out


# ──────────────────────────────────────────────────────────────────────────
# Text rendering
# ──────────────────────────────────────────────────────────────────────────


def _short_metadata(event: dict) -> str:
    """Render a one-line summary of the event-specific fields.

    Keeps the most useful identifier(s) per event_name. Anything not in the
    table here renders as an empty tail — the timestamp + actor + event name
    is still informative on its own.
    """
    name = event.get("event_name", "")
    parts: list[str] = []
    if "stage" in event and event["stage"]:
        parts.append(f"stage={event['stage']}")
    if "kind" in event and event["kind"]:
        parts.append(f"kind={event['kind']}")
    if name in ("agent.dispatched", "agent.completed"):
        if event.get("agent_name"):
            parts.append(f"agent={event['agent_name']}")
        if event.get("bundle_hash"):
            parts.append(f"bundle={event['bundle_hash'][:12]}")
        if name == "agent.completed" and event.get("classification"):
            parts.append(f"status={event['classification']}")
    if name.startswith("query.") and event.get("query_id"):
        parts.append(f"query={event['query_id']}")
    if name == "gate.blocked" and event.get("reason"):
        parts.append(f"reason={event['reason']}")
    if name == "gate.resolved" and event.get("choice"):
        parts.append(f"choice={event['choice']}")
    return " ".join(parts)


def _render_text(
    exp_id: str,
    events: list[dict],
    decisions: list[tuple[str, str]],
    *,
    quiet: bool,
    chain_status: Optional[str],
) -> str:
    """Build the full text rendering as a single string."""
    lines: list[str] = []
    if not quiet:
        lines.append(f"Audit trail for {exp_id}")
        lines.append("-" * (len(lines[0])))

    if not events:
        lines.append("no events recorded yet")
    else:
        # Index decisions by stage prefix so we can interleave them under the
        # matching stage.committed row. Filename convention (§10.6 / W_hooks.3):
        # "{NN}-{stage}.yaml" — e.g., "00-data_loaded.yaml", "03b-contradiction.yaml".
        decisions_by_stage: dict[str, list[tuple[str, str]]] = {}
        for fname, body in decisions:
            # Strip leading digits + dash, drop .yaml suffix.
            stem = fname[:-5] if fname.endswith(".yaml") else fname
            key = stem.split("-", 1)[1] if "-" in stem else stem
            decisions_by_stage.setdefault(key, []).append((fname, body))

        gates_opened = 0
        gates_resolved = 0
        bundle_hashes: set[str] = set()

        for ev in events:
            ts = ev.get("timestamp", "")
            actor = ev.get("actor_name") or ev.get("actor_kind") or "-"
            name = ev.get("event_name", "-")
            tail = _short_metadata(ev)
            lines.append(f"{ts}  {actor:<20.20}  {name:<25.25}  {tail}")
            if name == "gate.opened":
                gates_opened += 1
            elif name == "gate.resolved":
                gates_resolved += 1
            if name in ("agent.dispatched", "stage.committed"):
                bh = ev.get("bundle_hash")
                if isinstance(bh, str) and bh:
                    bundle_hashes.add(bh)
            if name == "stage.committed":
                stage_name = ev.get("stage", "")
                for fname, body in decisions_by_stage.get(stage_name, []):
                    lines.append(f"    decision: {fname}")
                    for body_line in body.splitlines():
                        lines.append(f"      {body_line}")

        if not quiet:
            lines.append("")
            lines.append(
                f"total events: {len(events)} | "
                f"gates opened: {gates_opened} | "
                f"gates resolved: {gates_resolved} | "
                f"bundle hashes: {len(bundle_hashes)}"
            )

    if chain_status is not None and not quiet:
        lines.append(f"chain integrity: {chain_status}")

    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# Chain validation wrapper
# ──────────────────────────────────────────────────────────────────────────


def _validate_chain_for_cli(project_root: Path, exp_id: str) -> tuple[str, int]:
    """Run validate_chain against the experiment; return (status_str, exit_code).

    The validate_chain function takes a private ``_root`` kwarg pointing at
    the experiments root directory; the CLI passes the resolved project's
    ``experiments/`` here so the validator works regardless of cwd.
    """
    try:
        from openxp.audit.chain import validate_chain
    except Exception as e:  # pragma: no cover — defensive
        return (f"FAILED ({type(e).__name__})", EXIT_WARNING)

    experiments_root = project_root / "experiments"
    try:
        result = validate_chain(exp_id, _root=experiments_root)
    except Exception as e:
        return (f"FAILED ({type(e).__name__}: {e})", EXIT_WARNING)

    if result.ok:
        return ("OK", EXIT_OK)
    first = result.violations[0] if result.violations else None
    if first is not None:
        return (f"FAILED — {first.description}", EXIT_WARNING)
    return ("FAILED", EXIT_WARNING)


# ──────────────────────────────────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """argparse entry. Returns an EXIT_* code (see exit_codes.py)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    project_root = (args.project if args.project is not None else Path.cwd()).resolve()
    exp_dir = _resolve_exp_dir(args.project, args.exp_id)

    # --diff path — delegate to prune.py (text-mode diff).
    if args.diff is not None:
        try:
            from openxp.cli.prune import render_diff
        except Exception as e:
            print(f"unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
            return EXIT_FATAL
        other_dir = _resolve_exp_dir(args.project, args.diff)
        if not exp_dir.exists():
            print(f"unknown experiment: {args.exp_id}", file=sys.stderr)
            return EXIT_USER_ERROR
        if not other_dir.exists():
            print(f"unknown experiment: {args.diff}", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            text = render_diff(
                args.exp_id,
                exp_dir,
                args.diff,
                other_dir,
                use_color=sys.stdout.isatty(),
            )
        except Exception as e:
            print(f"unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
            return EXIT_FATAL
        sys.stdout.write(text)
        return EXIT_OK

    # --html path — delegate to audit_html.py.
    if args.html:
        if not exp_dir.exists():
            print(f"unknown experiment: {args.exp_id}", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            from openxp.cli.audit_html import render_html_report, write_html_report
        except Exception as e:
            print(f"unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
            return EXIT_FATAL
        events = _load_log_events(exp_dir)
        decisions = _load_decisions(exp_dir)
        html = render_html_report(args.exp_id, events, decisions)
        out_path = args.out if args.out is not None else exp_dir / "audit.html"
        try:
            write_html_report(out_path, html)
        except OSError as e:
            print(f"failed to write {out_path}: {e}", file=sys.stderr)
            return EXIT_FATAL
        if not args.quiet:
            print(f"wrote: {out_path}")
        return EXIT_OK

    # Default text path.
    if not exp_dir.exists():
        print(f"unknown experiment: {args.exp_id}", file=sys.stderr)
        return EXIT_USER_ERROR

    try:
        events = _load_log_events(exp_dir)
    except OSError as e:
        print(f"failed to read log.jsonl: {e}", file=sys.stderr)
        return EXIT_FATAL

    # --json: emit the raw event list, skip chain validation chrome.
    if args.json:
        sys.stdout.write(json.dumps(events, indent=2) + "\n")
        return EXIT_OK

    decisions = _load_decisions(exp_dir)

    # Validate the chain only when there's something to validate.
    if events:
        chain_status, exit_code = _validate_chain_for_cli(project_root, args.exp_id)
    else:
        chain_status, exit_code = (None, EXIT_WARNING)

    text = _render_text(
        args.exp_id,
        events,
        decisions,
        quiet=args.quiet,
        chain_status=chain_status,
    )
    sys.stdout.write(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
