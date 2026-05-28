"""Tests for openxp.render.report — verdict-first markdown renderer (§21)."""
from __future__ import annotations

import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from openxp.render.report import (
    AuditRow,
    Diagnostics,
    GuardrailViolation,
    MetricRow,
    Report,
    render_report,
    write_report,
)


def _audit_row(stage: str = "Stage 6 — Analyze", action_id: str = "01HXYZABCDEFGHIJKLMNOPQRST") -> AuditRow:
    return AuditRow(stage=stage, committed_at="2026-05-27T15:42:00Z", action_id=action_id)


def _basic_report(**overrides) -> Report:
    defaults = dict(
        experiment_id="exp_001",
        experiment_name="Checkout button color",
        verdict="SHIP",
        confidence_label="highly likely positive",
        rationale_one_line="Completion +3.2pp [+1.4, +5.0] at 95% CI; guardrails clear; late-window 0.87x.",
        metric_table=[
            MetricRow(
                name="completion_rate",
                direction="higher_is_better",
                lift_str="+3.2pp",
                ci_95="[+1.4, +5.0]",
                ci_90="[+1.8, +4.6]",
                status="SHIP",
            )
        ],
        diagnostics=Diagnostics(
            srm_pass=True,
            n_observed=19204,
            n_required=18000,
            sample_pct=107,
            late_ratio=0.87,
            guardrails_violated=[],
        ),
        uncertainty_notes=["Late-window ratio close to the 0.7 threshold."],
        audit_trail=[_audit_row()],
    )
    defaults.update(overrides)
    return Report(**defaults)


# ──────────────────────────────────────────────────────────────────────────


def test_render_minimal_report():
    """Report with one metric, verdict=SHIP → assert "SHIP" and metric name appear."""
    report = _basic_report()
    out = render_report(report)
    assert "SHIP" in out
    assert "completion_rate" in out
    assert "Checkout button color" in out


def test_render_no_guardrail_violations_section_omitted():
    """guardrails_violated: [] → no '### Guardrail violations' subsection."""
    report = _basic_report()
    out = render_report(report)
    assert "### Guardrail violations" not in out


def test_render_late_ratio_unavailable():
    """late_ratio: None → renders 'unavailable'."""
    report = _basic_report(
        diagnostics=Diagnostics(
            srm_pass=True,
            n_observed=19204,
            n_required=18000,
            sample_pct=107,
            late_ratio=None,
            guardrails_violated=[],
        )
    )
    out = render_report(report)
    assert "unavailable" in out


def test_render_uncertainty_notes_bulleted():
    """Pass 3 notes → 3 lines with '-' prefix."""
    notes = [
        "Late-window ratio close to threshold.",
        "Sample skewed toward iOS.",
        "Holiday traffic in last 2 days.",
    ]
    report = _basic_report(uncertainty_notes=notes)
    out = render_report(report)
    # Each note should appear as its own bullet line.
    for note in notes:
        assert f"- {note}" in out
    # Confirm there are at least 3 bullet lines in the uncertainty section.
    uncertainty_section = out.split("## What I'm not sure about", 1)[1].split("## Audit trail", 1)[0]
    bullet_lines = [ln for ln in uncertainty_section.splitlines() if ln.startswith("- ")]
    assert len(bullet_lines) == 3


def test_render_audit_trail_truncates_action_ids():
    """action_id length 32 → renders as 12-char prefix + '...'."""
    long_id = "01HXYZABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 32 chars
    assert len(long_id) == 32
    report = _basic_report(audit_trail=[_audit_row(action_id=long_id)])
    out = render_report(report)
    expected_prefix = long_id[:12]
    assert f"`{expected_prefix}...`" in out
    # And the full id should NOT appear.
    assert long_id not in out


def test_write_report_atomic(tmp_path: Path):
    """write_report chmod 600, exists at output_path."""
    report = _basic_report()
    out_path = tmp_path / "report.md"
    write_report(report, out_path)
    assert out_path.exists()
    mode = stat.S_IMODE(out_path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
    content = out_path.read_text(encoding="utf-8")
    assert "SHIP" in content


def test_write_report_returns_path(tmp_path: Path):
    """write_report returns the output path."""
    report = _basic_report()
    out_path = tmp_path / "report.md"
    returned = write_report(report, out_path)
    assert returned == out_path


def test_render_with_negative_lift_lower_is_better():
    """direction=lower_is_better, lift=-3.2 → status column reads correctly."""
    report = _basic_report(
        metric_table=[
            MetricRow(
                name="time_to_confirm_ms",
                direction="lower_is_better",
                lift_str="-3.2%",
                ci_95="[-5.0, -1.4]",
                ci_90="[-4.6, -1.8]",
                status="SHIP",
            )
        ],
    )
    out = render_report(report)
    assert "time_to_confirm_ms" in out
    assert "lower_is_better" in out
    assert "-3.2%" in out
    assert "[-5.0, -1.4]" in out


def test_render_full_happy_path():
    """Fully populated Report → renders without exception, contains all section headers."""
    report = _basic_report(
        metric_table=[
            MetricRow(
                name="completion_rate",
                direction="higher_is_better",
                lift_str="+3.2pp",
                ci_95="[+1.4, +5.0]",
                ci_90="[+1.8, +4.6]",
                status="SHIP",
            ),
            MetricRow(
                name="time_to_confirm_ms",
                direction="lower_is_better",
                lift_str="+0.8%",
                ci_95="[-0.4, +2.0]",
                ci_90="[-0.1, +1.7]",
                status="clear",
            ),
        ],
        diagnostics=Diagnostics(
            srm_pass=False,
            n_observed=19204,
            n_required=18000,
            sample_pct=107,
            late_ratio=0.62,
            guardrails_violated=[
                GuardrailViolation(
                    metric="error_rate",
                    detail="+8.4% [+4.1, +12.7] at 90% breaches +5% halt threshold",
                )
            ],
        ),
        uncertainty_notes=[
            "Late-window 0.62 below the 0.7 novelty threshold.",
            "Error-rate guardrail breach is large relative to halt threshold.",
        ],
        audit_trail=[
            _audit_row(stage="Stage 3 — Design"),
            _audit_row(stage="Stage 5 — Monitor"),
            _audit_row(stage="Stage 6 — Analyze"),
            _audit_row(stage="Stage 7 — Interpret"),
        ],
    )
    out = render_report(report)
    assert "# Experiment exp_001" in out
    assert "## Verdict" in out
    assert "## Headline metrics" in out
    assert "## Diagnostics" in out
    assert "### Guardrail violations" in out
    assert "## What I'm not sure about" in out
    assert "## Audit trail" in out
    assert "error_rate" in out
    assert "FAIL" in out  # srm_pass=False → FAIL
    assert "0.62" in out  # late_ratio formatted


def test_pydantic_extra_forbid():
    """Report rejects unknown fields."""
    with pytest.raises(ValidationError):
        Report(
            experiment_id="exp_001",
            experiment_name="x",
            verdict="SHIP",
            confidence_label="highly likely positive",
            rationale_one_line="x",
            metric_table=[],
            diagnostics=Diagnostics(
                srm_pass=True,
                n_observed=1,
                n_required=1,
                sample_pct=100,
                late_ratio=None,
                guardrails_violated=[],
            ),
            uncertainty_notes=[],
            audit_trail=[],
            unknown_field="boom",  # should be rejected
        )
