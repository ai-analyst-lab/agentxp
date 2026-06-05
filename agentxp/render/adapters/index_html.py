"""Static experiment-index navigator — one self-contained cross-experiment page.

The cross-experiment counterpart to the single-report adapters. It is the ONLY
adapter that walks a directory rather than rendering one bundle: it discovers
every experiment under ``{root}/experiments/`` the way ``cli/list.py`` does (a
child dir is an experiment iff it holds a ``state.yaml``), projects each through
the same pure ``distill()`` the single-report path uses, resolves each row's
render status with ``build_provenance()``, and aggregates the rows with the pure
``distill_index()``.

Per-row isolation is the load-bearing invariant: one unreadable / unvalidatable
experiment renders a status-only ERROR row (UNVERIFIABLE) and NEVER aborts the
whole index. The 400ms ``PerfBudgetExceeded`` cap is per-experiment, so N
experiments are N independent budgets — a row that blows its budget degrades to
UNVERIFIABLE rather than failing the page.

Self-containment matches the html/card adapters: one file, inlined brand CSS,
base64 fonts, no CDN. The one departure is a small block of inline vanilla JS for
client-side filter/sort — it DEGRADES GRACEFULLY: every row is server-rendered,
so the table is complete and readable with JS disabled. Links go OUT to the
per-experiment artifacts (no iframe). ``autoescape=True`` escapes every string.
"""
from __future__ import annotations

import json
from pathlib import Path

import jinja2
from pydantic import ValidationError

class PerfBudgetExceeded(Exception):
    """v3: validate_chain is gone; this stub exists so build_provenance's
    legacy exception path still type-resolves. The exception is never
    raised in v3 since the per-row time-budget logic moved with
    validate_chain itself."""
from agentxp.render import brand
from agentxp.render.distill import distill, distill_index
from agentxp.render.provenance import RenderStatus, build_provenance
from agentxp.render.viewmodel import IndexRowVM, IndexVM
from agentxp.schemas.report import Report

_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "templates"
    / "experiment-index.html.j2"
)
_COMPONENTS_CSS = (
    Path(__file__).resolve().parent.parent.parent
    / "assets"
    / "design"
    / "components.css"
)

# Verdict → badge style modifier (presentation only; the badge always carries the
# verdict WORD). Kept identical to the single-report adapters so a verdict reads
# the same colour on the index as on its own page.
_VERDICT_MODIFIER = {
    "SHIP": "ship",
    "LIFT-WITH-CAVEAT": "hold",
    "DIRECTIONAL-ONLY": "hold",
    "INCONCLUSIVE": "hold",
    "LEARN": "hold",
    "NO-LIFT": "no-ship",
    "NO-SHIP-GUARDRAIL": "no-ship",
    "INVALID-SRM": "no-ship",
}

_STATUS_CLASS = {
    RenderStatus.VERIFIED: "verified",
    RenderStatus.DRAFT_UNVERIFIED: "draft",
    RenderStatus.UNVERIFIABLE: "unverifiable",
}


def _inline_css(theme: str) -> str:
    """The complete inlined stylesheet: brand vars + @font-face + components."""
    return "\n".join([
        brand.css_vars(theme),
        brand.font_face_css(),
        _COMPONENTS_CSS.read_text(encoding="utf-8"),
    ])


def _discover(experiments_root: Path) -> list[Path]:
    """Sorted experiment dirs under ``experiments_root`` (state.yaml present).

    Mirrors ``cli/list.py``: a child directory is an experiment iff it carries a
    ``state.yaml``. Deterministic order (sorted by name) so the page is
    byte-stable across runs.
    """
    if not experiments_root.exists():
        return []
    out: list[Path] = []
    for child in sorted(experiments_root.iterdir()):
        if child.is_dir() and (child / "state.yaml").exists():
            out.append(child)
    return out


def _build_row(exp_dir: Path) -> IndexRowVM:
    """Project one experiment dir into an IndexRowVM, isolating every failure.

    A read / JSON / schema / distill failure yields a status-only ERROR row; a
    ``build_provenance`` blow-out (incl. the per-experiment ``PerfBudgetExceeded``
    cap) degrades the row to UNVERIFIABLE. Either way the exception is contained
    to this one row — the index never aborts over a single bad experiment.
    """
    exp_id = exp_dir.name
    report_path = exp_dir / "report.json"
    if not report_path.exists():
        return IndexRowVM.error_row(exp_id, "no report.json")

    try:
        raw = json.loads(report_path.read_text(encoding="utf-8"))
    except OSError as e:
        return IndexRowVM.error_row(exp_id, f"unreadable report.json ({type(e).__name__})")
    except json.JSONDecodeError:
        return IndexRowVM.error_row(exp_id, "report.json is not valid JSON")

    try:
        report = Report.model_validate(raw)
    except ValidationError:
        return IndexRowVM.error_row(exp_id, "report.json failed schema validation")

    try:
        vm = distill(report)
    except Exception as e:  # noqa: BLE001 — a bad row must never abort the index
        return IndexRowVM.error_row(exp_id, f"distill failed ({type(e).__name__})")

    # Provenance: the per-experiment 400ms cap means a blow-out is a "can't
    # check" for THIS row, never an accusation and never a page-level abort.
    try:
        status = build_provenance(report, exp_dir).render_status
    except PerfBudgetExceeded:
        status = RenderStatus.UNVERIFIABLE
    except Exception:  # noqa: BLE001 — never crash the index over verification
        status = RenderStatus.UNVERIFIABLE

    # Row identity is the DISCOVERY directory name, not the report's embedded
    # experiment_id — that is what every CLI verb (`agentxp report/audit <id>`)
    # resolves against, so it is what the out-links must point at. The embedded
    # name stays as the human-readable display string (experiment_name).
    return vm.to_index_row(status).model_copy(update={"experiment_id": exp_dir.name})


def _row_view(row: IndexRowVM) -> dict:
    """Flatten an IndexRowVM into the fields the template renders.

    Links go OUT to the conventional per-experiment artifacts (relative paths,
    no iframe). An ERROR row carries no verdict word, so it gets a neutral
    modifier and surfaces its error marker instead of report/audit links.
    """
    return {
        "experiment_id": row.experiment_id,
        "experiment_name": row.experiment_name,
        "verdict": row.verdict,
        "verdict_modifier": _VERDICT_MODIFIER.get(row.verdict, "hold"),
        "confidence_label": row.confidence_label,
        "lift_str": row.lift_str,
        "ci_95": row.ci_95,
        "generated_at": row.generated_at,
        "status": row.render_status.value,
        "status_class": _STATUS_CLASS[row.render_status],
        "error": row.error,
        "report_href": f"{row.experiment_id}/report.html",
        "audit_href": f"{row.experiment_id}/audit.html",
    }


def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_PATH.parent)),
        autoescape=True,  # HTML output — escape every string
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
    )


def render_index(experiments_root: Path, *, theme: str = "editorial-light") -> str:
    """Discover, project, and render the cross-experiment navigator to one page.

    PURE-over-the-rows in spirit: each row is built once (via the same
    ``distill()`` the single-report path uses) and the tallies come from the pure
    ``distill_index()``. The only impurity is the directory walk + per-row
    provenance, both isolated in ``_build_row``.
    """
    rows = [_build_row(d) for d in _discover(Path(experiments_root))]
    index: IndexVM = distill_index(rows)
    template = _env().get_template(_TEMPLATE_PATH.name)
    return template.render(
        index=index,
        rows=[_row_view(r) for r in rows],
        css=_inline_css(theme),
    )


__all__ = ["render_index"]
