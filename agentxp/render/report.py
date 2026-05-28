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
from typing import Literal, Optional

import jinja2
from pydantic import BaseModel, ConfigDict

from agentxp.audit.storage import _atomic_write_bytes


# ──────────────────────────────────────────────────────────────────────────
# View models — the Report passed to render_report is a flat projection.
# This is NOT the canonical agentxp.schemas.report.Report (which models the
# report.json sidecar). This is the per-render input shape per §21.
# ──────────────────────────────────────────────────────────────────────────


class MetricRow(BaseModel):
    """One row in the headline-metrics table."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    name: str
    direction: Literal["higher_is_better", "lower_is_better"]
    lift_str: str        # e.g., "+3.2pp" or "-1.4%"
    ci_95: str           # e.g., "[+1.4, +5.0]"
    ci_90: str           # e.g., "[+1.8, +4.6]"
    status: str          # e.g., "SHIP", "violated", "clear"


class GuardrailViolation(BaseModel):
    """One row in the optional guardrail-violations subsection."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    metric: str
    detail: str


class Diagnostics(BaseModel):
    """Flat diagnostics block — the 5-flag panel inputs from §21."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    srm_pass: bool
    n_observed: int
    n_required: int
    sample_pct: int                                     # e.g., 107 for 107%
    late_ratio: Optional[float] = None                  # None → "unavailable"
    guardrails_violated: list[GuardrailViolation] = []


class AuditRow(BaseModel):
    """One row in the audit-trail table — stage + commit timestamp + action id."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    stage: str           # e.g., "Stage 3 — Design"
    committed_at: str    # ISO-8601 string, already formatted by caller
    action_id: str       # ULID, full-length; template truncates to 12 chars


class Report(BaseModel):
    """Input to the renderer — distilled from interpreter.out.yaml + audit log.

    The renderer holds no opinions about how this is populated; the caller
    (the readout agent or a CLI replay path) is responsible for distilling
    the canonical `agentxp.schemas.report.Report` into this shape.
    """
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    experiment_id: str
    experiment_name: str
    verdict: str                       # one of §1.8.17 8 values
    confidence_label: str              # one of §1.8.10 7 values
    rationale_one_line: str            # interpreter's three-clause summary
    metric_table: list[MetricRow]
    diagnostics: Diagnostics
    uncertainty_notes: list[str]       # 1-5 caveats
    audit_trail: list[AuditRow]


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
    report: Report,
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
    report: Report,
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
    "Report",
    "render_report",
    "write_report",
]
