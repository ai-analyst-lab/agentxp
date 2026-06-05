"""HTML + PDF rendering for the four share-tail moments.

This module wires the Jinja2 templates in ``agentxp/render/templates/`` to
the share-tail VMs. ``render_share_tail`` in ``agentxp.orchestrator.tools``
calls into ``render_html`` / ``html_to_pdf`` here for ``fmt`` in
``{"html", "pdf"}``.

PDF backend is Playwright (lifted from ``scratch/walk_experiment.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import jinja2

from agentxp.render.viewmodel import (
    DesignBriefVM,
    IntentVM,
    MidRunVM,
    VerdictVM,
)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Module-level cache flag to avoid repeated playwright probes.
_PLAYWRIGHT_AVAILABLE: Optional[bool] = None


def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(["html", "xml"]),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Per-kind context builders + render functions
# ─────────────────────────────────────────────────────────────────────────────


def _intent_context(vm: IntentVM, audience: str) -> dict:
    return {
        "title": f"intent · {vm.experiment_id}",
        "audience": audience,
        "experiment_id": vm.experiment_id,
        "intent_text": vm.intent_text,
        "captured_at": vm.captured_at,
        "captured_by": vm.captured_by,
    }


def render_intent_html(*, vm: IntentVM, audience: str = "exec") -> str:
    """Render the intent share-tail to a self-contained HTML string."""
    return _env().get_template("intent.html.j2").render(**_intent_context(vm, audience))


def _design_brief_context(vm: DesignBriefVM, audience: str) -> dict:
    return {
        "title": f"design brief · {vm.experiment_id}",
        "audience": audience,
        # Identity
        "experiment_id": vm.experiment_id,
        "display_name": vm.display_name or vm.experiment_id,
        "owner_team": vm.owner_team,
        # Hypothesis / mechanism
        "hypothesis_prose": vm.hypothesis_text,
        "mechanism_prose": vm.mechanism_prose,
        "historical_baseline_context": vm.historical_baseline_context,
        # Primary metric + decision
        "primary_metric_name": vm.primary_metric_name,
        "primary_metric_type": vm.primary_metric_type,
        "primary_direction": vm.primary_direction,
        "primary_decision_rule": vm.primary_decision_rule,
        "decision_rule_prose": vm.primary_decision_rule,
        "decision_rule_short": vm.decision_rule_short or "the pre-registered rules below",
        "secondary_metric_names": vm.secondary_metric_names,
        # Power / sample
        "mde_text": vm.mde_text,
        "baseline": vm.baseline,
        "power_text": vm.power_text,
        "n_per_group": vm.n_per_group,
        "n_total": vm.n_total,
        "duration_text": vm.duration_text,
        # Guardrails / cohorts
        "guardrails": vm.guardrails,
        "guardrails_summary": vm.guardrails_summary,
        "cohorts": vm.cohorts or vm.cohorts_summary,
        "cohorts_summary": vm.cohorts_summary,
        "assignment_unit": vm.assignment_unit,
        "arms": vm.arms,
        "expected_arm_ratio_text": vm.expected_arm_ratio_text,
        # Section prose
        "at_a_glance_prose": vm.at_a_glance_prose,
        "metrics_section_prose": vm.metrics_section_prose,
        "power_section_prose": vm.power_section_prose,
        "assignment_section_prose": vm.assignment_section_prose,
        # Power curve
        "power_curve_points": vm.power_curve_points,
        "power_x_ticks": vm.power_x_ticks,
        "power_y_ticks": vm.power_y_ticks,
        "design_x": vm.design_x,
        "design_y": vm.design_y,
        # Integrity lock
        "design_chain_hash": vm.design_chain_hash,
        "design_chain_hash_short": vm.design_chain_hash_short,
        "metric_snapshot": vm.metric_snapshot,
        "metric_snapshot_count": vm.metric_snapshot_count,
        "sealed_at": vm.sealed_at,
        "sealed_by": vm.sealed_by,
    }


def render_design_brief_html(*, vm: DesignBriefVM, audience: str = "exec") -> str:
    """Render the design-brief share-tail to a self-contained HTML string."""
    return (
        _env()
        .get_template("design_brief.html.j2")
        .render(**_design_brief_context(vm, audience))
    )


def render_verdict_html(*, vm: VerdictVM, audience: str = "exec") -> str:
    """Render the verdict share-tail using analysis.html.j2.

    The analysis template expects a rich context that ReportVM does not
    carry verbatim — for now we surface the most common fields the
    template reads and the rest fall through Jinja's default behavior
    (since the env above does NOT use StrictUndefined). The proper fix is
    a dedicated VerdictDistill step that mirrors the walk's
    ``_analysis_context`` builder; this is a placeholder until that
    lands.
    """
    ctx = {
        "title": f"verdict · {vm.experiment_id}",
        "audience": audience,
        "experiment_id": vm.experiment_id,
        "generated_at": vm.generated_at,
        "render_status": "VERIFIED",
        "primary_metric_name": vm.metric_table[0].name if vm.metric_table else "",
    }
    return _env().get_template("analysis.html.j2").render(**ctx)


def render_mid_run_html(*, vm: MidRunVM, audience: str = "exec") -> str:
    """Render the mid-run halt share-tail via srm_check.html.j2.

    The srm_check template is closest in spirit to a mid-run halt
    readout. As with verdict, this is a stop-gap until a dedicated
    mid_run template lands.
    """
    ctx = {
        "title": f"halt · {vm.experiment_id}",
        "audience": audience,
        "experiment_id": vm.experiment_id,
        "halt_reason": vm.halt_reason,
        "halt_summary_text": vm.halt_summary_text,
        "triggered_at": vm.triggered_at,
        "elapsed_text": vm.elapsed_text,
        "suggested_resolutions": vm.suggested_resolutions,
        "srm_chi2": vm.srm_chi2,
        "srm_threshold": vm.srm_threshold,
    }
    return _env().get_template("srm_check.html.j2").render(**ctx)


# ─────────────────────────────────────────────────────────────────────────────
# HTML → PDF (Playwright)
# ─────────────────────────────────────────────────────────────────────────────


def html_to_pdf(html: str, out_path: Path) -> bool:
    """Rasterize HTML to PDF using Playwright Chromium.

    Returns True on success, False if Playwright (or Chromium) is not
    available. Document flows naturally; pages break at 8.5x11 with
    standard margins.
    """
    global _PLAYWRIGHT_AVAILABLE
    if _PLAYWRIGHT_AVAILABLE is False:
        return False
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        _PLAYWRIGHT_AVAILABLE = False
        return False
    _PLAYWRIGHT_AVAILABLE = True

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 900, "height": 1300})
            page.set_content(html, wait_until="networkidle")
            page.pdf(
                path=str(out_path),
                format="Letter",
                print_background=True,
                margin={"top": "0.6in", "bottom": "0.6in",
                        "left": "0.7in", "right": "0.7in"},
                prefer_css_page_size=True,
            )
        finally:
            browser.close()
    return True


__all__ = [
    "render_intent_html",
    "render_design_brief_html",
    "render_verdict_html",
    "render_mid_run_html",
    "html_to_pdf",
]
