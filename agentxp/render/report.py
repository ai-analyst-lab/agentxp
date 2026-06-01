"""Jinja2 renderer for the verdict-first experiment report (report.md).

Distills the canonical `agentxp.schemas.report.Report` (the report.json sidecar
written by the readout agent) into a flat view model used purely for rendering,
and emits the Stage-8 markdown readout described in §21 of OPENXP_V01_PLAN.md.

Verdict-first ordering, diagnostics gate, guardrail-violations subsection (only
when populated), "What I'm not sure about" bullets, and the per-stage audit
trail with truncated 12-char action-id prefixes are all defined by §21.

The renderer is intentionally side-effect-free except for `write_report`, which
writes atomically with chmod 600 via `agentxp.audit.storage._atomic_write_bytes`.
"""
from __future__ import annotations

from pathlib import Path

import jinja2

from agentxp.audit.storage import _atomic_write_bytes

# The render view-models now live in viewmodel.py (presentation layer W1-T1).
# They are re-exported here so existing imports
# (`from agentxp.render.report import MetricRow, Diagnostics, AuditRow, Report`)
# keep working. ``Report`` is a back-compat alias for ``ReportVM``.
from agentxp.render.viewmodel import (
    AuditRow,
    Diagnostics,
    GuardrailViolation,
    MetricRow,
    ReportVM,
)

Report = ReportVM


# ──────────────────────────────────────────────────────────────────────────
# Renderer
# ──────────────────────────────────────────────────────────────────────────

_DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "templates" / "experiment-report.md"
)


def _build_env(template_dir: Path) -> jinja2.Environment:
    """Construct the Jinja2 environment for markdown rendering.

    autoescape=False because we emit markdown, not HTML. The audit CLI does
    its own HTML escaping in a different code path.
    """
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
    )


def render_report(
    report: ReportVM,
    template_path: Path | None = None,
) -> str:
    """Render report.json → report.md as a string. Returns the rendered markdown.

    template_path defaults to <repo>/templates/experiment-report.md.
    """
    tpl_path = template_path if template_path is not None else _DEFAULT_TEMPLATE_PATH
    tpl_path = Path(tpl_path).resolve()
    env = _build_env(tpl_path.parent)
    template = env.get_template(tpl_path.name)
    return template.render(report=report)


def write_report(
    report: ReportVM,
    output_path: Path,
    template_path: Path | None = None,
) -> Path:
    """Render + write atomically. chmod 600. Returns the output path."""
    rendered = render_report(report, template_path=template_path)
    output_path = Path(output_path)
    _atomic_write_bytes(output_path, rendered.encode("utf-8"), mode=0o600)
    return output_path


__all__ = [
    "MetricRow",
    "GuardrailViolation",
    "Diagnostics",
    "AuditRow",
    "ReportVM",
    "Report",
    "render_report",
    "write_report",
]
