"""agentxp report — render a finalized experiment's report.json to a chosen format.

The presentation counterpart to ``agentxp audit``. It performs NO analysis: it
loads the committed ``report.json``, validates it, projects it through the pure
``distill()``, assembles a :class:`ViewBundle` with freshly-built provenance, and
hands the bundle to one format adapter. Add a format = add an adapter; this verb
never grows a per-format branch beyond output plumbing.

Surfaces: ``glance`` (3-line terminal default on a TTY), ``md`` (the full
verdict-first readout, default when piped), ``html`` (exec one-pager, W4) and
``card`` (1200×1500 social card, W5). ``png``/``pdf`` are recognised so the verb
can fail fast with a "ships in the agentxp[png] extra" note rather than an opaque
error. With ``--index`` (and no positional exp_id) it renders the static
cross-experiment navigator (W6) to disk instead of one report.

Source spec: PRESENTATION_LAYER_MASTER_PLAN.md §Wave 2.
"""
from __future__ import annotations

import argparse
import json
import sys
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

# Formats recognised but not yet built — used to fail fast with a helpful note.
# png/pdf are a deferred rasterization of the html/card pages, shipped as the
# optional ``agentxp[png]`` extra (playwright + pinned Chromium), not in core.
_DEFERRED_FORMATS: dict[str, str] = {
    "png": "the optional agentxp[png] extra",
    "pdf": "the optional agentxp[png] extra",
}

# --audience sugar. ``None`` means "use the isatty default" (glance on a TTY,
# md when piped) — that is what an operator wants. The others name a format id.
_AUDIENCE_FORMAT: dict[str, Optional[str]] = {
    "operator": None,       # isatty default (glance / md)
    "exec": "html",         # polished one-pager (ships W4)
    "skeptic": "md",        # full readout; also points at `audit --html`
    "public": "card",       # social card (ships W5)
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentxp report",
        description=(
            "Render a finalized experiment's report.json. Default: glance on a "
            "terminal, md when piped. Use --format or --audience to choose."
        ),
    )
    parser.add_argument(
        "exp_id",
        nargs="?",
        default=None,
        help="Experiment id (directory name under {project}/experiments/). "
        "Omit it (and pass --index) to render the cross-experiment navigator.",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Render the static cross-experiment index instead of one report. "
        "Mutually exclusive with a positional exp_id.",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Project root containing experiments/ (default: cwd).",
    )
    parser.add_argument(
        "--format",
        dest="format",
        default=None,
        help="Output format: glance, md, html, card, json, csv (png/pdf via agentxp[png]).",
    )
    parser.add_argument(
        "--audience",
        dest="audience",
        choices=sorted(_AUDIENCE_FORMAT),
        default=None,
        help="Sugar for --format: operator|exec|skeptic|public.",
    )
    parser.add_argument(
        "--theme",
        dest="theme",
        choices=["editorial-light", "editorial-dark"],
        default="editorial-light",
        help="Brand theme for the html/card formats (default: editorial-light).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write to this path (atomic, chmod 600) instead of stdout.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-essential output (the glance hint line).",
    )
    return parser


def _resolve_exp_dir(project: Optional[Path], experiment_id: str) -> Path:
    root = (project if project is not None else Path.cwd()).resolve()
    return root / "experiments" / experiment_id


def _resolve_format(args: argparse.Namespace, *, isatty: bool) -> str:
    """Apply the resolution order: --format > --audience > isatty default."""
    if args.format is not None:
        return args.format
    if args.audience is not None:
        mapped = _AUDIENCE_FORMAT[args.audience]
        if mapped is not None:
            return mapped
    # operator audience, or nothing specified → isatty default.
    return "glance" if isatty else "md"


def _render_companion_artifacts(
    args: argparse.Namespace, experiments_root: Path
) -> None:
    """Render the per-experiment artifacts every index row links OUT to.

    The index links each row to ``{dir}/report.html`` and ``{dir}/audit.html``;
    those are dead links unless something writes them. ``--index`` owns that:
    for each discovered experiment it shells the existing ``report`` and
    ``audit`` verbs (render path only, no pipeline re-run) into the canonical
    on-disk locations, so the navigator's links resolve next to it.

    Per-experiment isolation mirrors the adapter's per-row isolation — a verb
    that exits non-zero (an experiment whose report.json can't render) simply
    leaves no artifact, and the matching index row is already an error row with
    no link. One bad experiment never aborts the companion pass.
    """
    from agentxp.cli import audit as audit_cli
    from agentxp.render.adapters.index_html import _discover

    project_args = (
        ["--project", str(args.project)] if args.project is not None else []
    )
    for exp_dir in _discover(experiments_root):
        name = exp_dir.name
        try:
            main(
                [name, "--format", "html", "--theme", args.theme,
                 "--out", str(exp_dir / "report.html"), "--quiet", *project_args]
            )
        except Exception:  # noqa: BLE001 — a bad experiment never aborts the pass
            pass
        try:
            audit_cli.main(
                [name, "--html",
                 "--out", str(exp_dir / "audit.html"), "--quiet", *project_args]
            )
        except Exception:  # noqa: BLE001
            pass


def _render_index(args: argparse.Namespace) -> int:
    """Render the cross-experiment navigator to a file (default or --out).

    Reuses ``list.py``'s resolver for the experiments root so discovery matches
    ``agentxp list`` exactly. Writes to disk by default (the page links out to
    sibling per-experiment artifacts, so a relative on-disk location is what
    makes those links resolve); ``--out`` overrides the path. Per-row isolation
    lives in the adapter, so this never fails over one bad experiment — it
    returns EXIT_OK once the page is written.

    Before the page itself, it renders each row's companion artifacts
    (``report.html`` + ``audit.html``) so the navigator's out-links resolve.
    """
    from agentxp.cli.list import _resolve_experiments_root
    from agentxp.render.adapters.index_html import render_index

    experiments_root = _resolve_experiments_root(args.project)
    out_path = args.out if args.out is not None else experiments_root / "index.html"

    _render_companion_artifacts(args, experiments_root)

    payload = render_index(experiments_root, theme=args.theme)

    from agentxp.audit.storage import _atomic_write_bytes

    try:
        _atomic_write_bytes(out_path, payload.encode("utf-8"), mode=0o600)
    except OSError as e:
        print(f"failed to write {out_path}: {e}", file=sys.stderr)
        return EXIT_FATAL
    if not args.quiet:
        print(f"wrote: {out_path}")
    return EXIT_OK


def main(argv: Optional[list[str]] = None) -> int:
    """argparse entry. Returns an EXIT_* code (see exit_codes.py)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --index and a positional exp_id are mutually exclusive: exactly one names
    # what to render. Both, or neither, is a usage error with a named reason.
    if args.index and args.exp_id is not None:
        print(
            "--index renders the whole navigator; drop the positional exp_id "
            f"(got exp_id={args.exp_id!r} with --index)",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR
    if not args.index and args.exp_id is None:
        print(
            "nothing to render: pass an experiment id, or --index for the "
            "cross-experiment navigator",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    if args.index:
        return _render_index(args)

    # --format and --audience are mutually exclusive — EXCEPT for html, where
    # --audience exec|skeptic configures the adapter's audit-trail switch rather
    # than acting as format sugar (exec hides the audit trail, skeptic shows it).
    _html_audience_combo = (
        args.format == "html" and args.audience in ("exec", "skeptic")
    )
    if args.format is not None and args.audience is not None and not _html_audience_combo:
        print(
            "--format and --audience are mutually exclusive "
            f"(got --format {args.format} and --audience {args.audience})",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    isatty = sys.stdout.isatty()
    fmt = _resolve_format(args, isatty=isatty)

    # Fail fast on a deferred / unknown format BEFORE touching disk.
    from agentxp.render.adapters import ADAPTERS, get_adapter
    from agentxp.render.adapters import raster

    if fmt in raster._RASTER_FORMATS:
        # png/pdf rasterize the html/card pages via the optional agentxp[png]
        # extra. When it is absent, fail fast with the extra's name (and the
        # second install step) rather than an opaque ImportError at render time.
        if not raster.is_available():
            print(
                f"format {fmt!r} ships in {_DEFERRED_FORMATS[fmt]} "
                f"(pip install 'agentxp[png]' then: playwright install chromium); "
                f"available now: {', '.join(sorted(ADAPTERS))}",
                file=sys.stderr,
            )
            return EXIT_USER_ERROR
        adapter = raster.build_adapter(fmt, theme=args.theme, audience=args.audience)
    elif fmt not in ADAPTERS:
        print(
            f"unknown format {fmt!r}; choose from: "
            f"{', '.join(sorted(ADAPTERS))}",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR
    else:
        adapter = get_adapter(fmt)

        # html carries config (theme + audience audit-trail switch); build a
        # configured instance rather than the registry default. exec hides the
        # audit trail, skeptic shows it; default is exec.
        if fmt == "html":
            from agentxp.render.adapters.html import HtmlAdapter

            html_audience = args.audience if args.audience == "skeptic" else "exec"
            adapter = HtmlAdapter(theme=args.theme, audience=html_audience)

        # card carries the theme too (the social card honours light/dark).
        if fmt == "card":
            from agentxp.render.adapters.card import CardAdapter

            adapter = CardAdapter(theme=args.theme)

    # glance is a terminal surface; writing it to a file is a usage error.
    if fmt == "glance" and args.out is not None:
        print("--out is not supported with --format glance", file=sys.stderr)
        return EXIT_USER_ERROR

    # A binary format must go to a file, never to stdout.
    if getattr(adapter, "binary", False) and args.out is None:
        print(f"format {fmt!r} is binary; --out is required", file=sys.stderr)
        return EXIT_USER_ERROR

    exp_dir = _resolve_exp_dir(args.project, args.exp_id)
    if not exp_dir.exists():
        print(f"unknown experiment: {args.exp_id}", file=sys.stderr)
        return EXIT_USER_ERROR

    report_path = exp_dir / "report.json"
    if not report_path.exists():
        print(
            f"no report.json for {args.exp_id} — run the experiment to Stage 8 first",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    try:
        raw = json.loads(report_path.read_text(encoding="utf-8"))
    except OSError as e:
        print(f"failed to read {report_path}: {e}", file=sys.stderr)
        return EXIT_FATAL
    except json.JSONDecodeError as e:
        print(f"report.json is not valid JSON: {e}", file=sys.stderr)
        return EXIT_FATAL

    # extra="forbid" stays on: an unknown field is a real version skew, not
    # something to silently ignore. Supported skew is OLD v1 read by NEW v2.
    from agentxp.schemas.report import Report

    try:
        report = Report.model_validate(raw)
    except ValidationError:
        print(
            "report.json failed schema validation (version mismatch or corruption)",
            file=sys.stderr,
        )
        return EXIT_FATAL

    from agentxp.render.distill import distill
    from agentxp.render.provenance import RenderStatus, build_provenance
    from agentxp.render.viewmodel import ViewBundle

    bundle = ViewBundle(vm=distill(report), provenance=build_provenance(report, exp_dir))
    payload = adapter.render(bundle)

    # Skeptic audience: nudge toward the immutable audit trail (not a renderer).
    if args.audience == "skeptic" and not args.quiet:
        print(
            f"for the full chain + decisions: agentxp audit {args.exp_id} --html",
            file=sys.stderr,
        )

    if args.out is not None:
        from agentxp.audit.storage import _atomic_write_bytes

        data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        try:
            _atomic_write_bytes(args.out, data, mode=0o600)
        except OSError as e:
            print(f"failed to write {args.out}: {e}", file=sys.stderr)
            return EXIT_FATAL
        if not args.quiet:
            print(f"wrote: {args.out}")
    else:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        # glance hint (line 3): only on an interactive, non-quiet stdout.
        if fmt == "glance" and isatty and not args.quiet:
            from agentxp.render.adapters.glance import GLANCE_HINT

            sys.stdout.write(GLANCE_HINT + "\n")

    # A live contradiction (hash mismatch / tree-reproduction failure) renders
    # but signals a warning, mirroring audit's failed-chain return.
    if bundle.render_status == RenderStatus.DRAFT_UNVERIFIED:
        return EXIT_WARNING
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
