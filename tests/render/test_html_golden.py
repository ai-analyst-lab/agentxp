"""W4-T8 — visual-QA gate for the exec HTML adapter.

Not a pixel diff (we have no browser in CI); instead a structural + invariant
snapshot over the single self-contained page the adapter emits, across:

  - every verdict shape that changes the page: ship / don't-ship / inconclusive
    / guardrail-violated / underpowered;
  - every render status: VERIFIED / DRAFT_UNVERIFIED / UNVERIFIABLE;
  - both themes: editorial-light / editorial-dark.

The gate pins the load-bearing guarantees of the layer:
  - the verdict WORD is always present (badge never relies on colour alone);
  - the receipts footer is ALWAYS present (a page is un-renderable without it);
  - a DRAFT status stamps a loud top banner; calm statuses do not;
  - output is byte-identical from the same bundle (deterministic renderer);
  - the muted grey (#8a8580) is reserved — it appears ONLY as the :root var
    definition, never hardcoded onto body text (the contrast reservation).
"""
from __future__ import annotations

import pytest

from agentxp.render.adapters.html import HtmlAdapter
from agentxp.render.provenance import Provenance, RenderStatus
from agentxp.render.viewmodel import (
    ChartData,
    Diagnostics,
    GuardrailViolation,
    MetricRow,
    ReportVM,
    ViewBundle,
)

_CHARTS = ChartData(
    lift_absolute=0.032,
    ci_95_lower=0.014,
    ci_95_upper=0.05,
    ci_90_lower=0.018,
    ci_90_upper=0.046,
    direction="higher_is_better",
    n_arm_control=9602,
    n_arm_treatment=9602,
)


def _vm(
    *,
    verdict: str = "SHIP",
    sample_pct=107,
    guardrails_violated=None,
) -> ReportVM:
    return ReportVM(
        experiment_id="exp_001",
        experiment_name="Checkout button color",
        verdict=verdict,
        confidence_label="highly likely positive",
        rationale_one_line="Completion up; guardrails clear.",
        generated_at="2026-06-02T17:55:11+00:00",
        metric_table=[
            MetricRow(
                name="completion_rate",
                direction="higher_is_better",
                lift_str="+0.032 (+18.0%)",
                ci_95="[+0.014, +0.05]",
                ci_90="[+0.018, +0.046]",
                status=verdict,
            )
        ],
        diagnostics=Diagnostics(
            srm_pass=True,
            n_observed=19204,
            n_required=18000,
            sample_pct=sample_pct,
            late_ratio=0.87,
            guardrails_violated=guardrails_violated or [],
        ),
        uncertainty_notes=["Late-window ratio close to the 0.7 threshold."],
        audit_trail=[],
        charts=_CHARTS,
    )


def _prov(status: RenderStatus) -> Provenance:
    reason = {
        RenderStatus.VERIFIED: "chain verified; verdict reproduces",
        RenderStatus.DRAFT_UNVERIFIED: "recomputed chain hash does not match recorded",
        RenderStatus.UNVERIFIABLE: "no chain_hash recorded — cannot verify",
    }[status]
    return Provenance(
        experiment_id="exp_001",
        render_status=status,
        status_reason=reason,
        chain_hash_stored="a" * 64,
        locked_brief_hash="brief123",
        agentxp_version="0.1.0",
        chain_hash_live="a" * 64,
        hash_matches=status is not RenderStatus.DRAFT_UNVERIFIED,
        replay_command="agentxp audit exp_001",
    )


def _bundle(vm=None, status=RenderStatus.VERIFIED) -> ViewBundle:
    return ViewBundle(vm=vm or _vm(), provenance=_prov(status))


def _render(bundle, *, theme="editorial-light", audience="exec") -> str:
    return HtmlAdapter(theme=theme, audience=audience).render(bundle)


# ── verdict shapes ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "verdict,modifier",
    [
        ("SHIP", "ship"),
        ("NO-SHIP-GUARDRAIL", "no-ship"),
        ("INCONCLUSIVE", "hold"),
        ("NO-LIFT", "no-ship"),
        ("LIFT-WITH-CAVEAT", "hold"),
    ],
)
def test_verdict_word_and_badge_modifier(verdict, modifier):
    out = _render(_bundle(_vm(verdict=verdict)))
    # the WORD is always present — the badge never relies on colour alone.
    assert f">{verdict}</span>" in out
    assert f"xp-verdict-badge--{modifier}" in out


def test_guardrail_violated_section_renders():
    vm = _vm(
        verdict="NO-SHIP-GUARDRAIL",
        guardrails_violated=[
            GuardrailViolation(metric="latency_p95", detail="+120ms over the 50ms cap")
        ],
    )
    out = _render(_bundle(vm))
    assert "Guardrail violations" in out
    assert "latency_p95" in out
    assert "+120ms over the 50ms cap" in out


def test_underpowered_sample_pct_renders():
    out = _render(_bundle(_vm(verdict="INCONCLUSIVE", sample_pct=64)))
    assert "64%" in out


# ── render statuses ──────────────────────────────────────────────────────────

def test_receipts_footer_always_present():
    for status in RenderStatus:
        out = _render(_bundle(status=status))
        assert "xp-receipts-footer" in out
        assert "agentxp audit exp_001" in out  # replay command travels with it


def test_draft_status_stamps_banner_calm_statuses_do_not():
    # Assert on the banner ELEMENT, not the class name — the .xp-draft-banner
    # CSS rule is always inlined in <style>; only the <div> is conditional.
    banner_el = '<div class="xp-draft-banner"'
    draft = _render(_bundle(status=RenderStatus.DRAFT_UNVERIFIED))
    assert banner_el in draft
    assert "DRAFT — UNVERIFIED" in draft

    for calm in (RenderStatus.VERIFIED, RenderStatus.UNVERIFIABLE):
        out = _render(_bundle(status=calm))
        assert banner_el not in out


def test_status_class_matches_render_status():
    cases = {
        RenderStatus.VERIFIED: "xp-render-status--verified",
        RenderStatus.DRAFT_UNVERIFIED: "xp-render-status--draft",
        RenderStatus.UNVERIFIABLE: "xp-render-status--unverifiable",
    }
    for status, css_class in cases.items():
        assert css_class in _render(_bundle(status=status))


# ── themes ───────────────────────────────────────────────────────────────────

def test_light_and_dark_carry_their_paper():
    light = _render(_bundle(), theme="editorial-light")
    dark = _render(_bundle(), theme="editorial-dark")
    assert "--xp-paper: #f6f2e9;" in light
    assert "--xp-paper: #14120d;" in dark


def test_chart_palette_tracks_theme():
    # the favorable lift bar uses the pass colour; it must be the theme's pass,
    # not the default-theme pass, so charts match the page they sit on.
    light = _render(_bundle(), theme="editorial-light")
    dark = _render(_bundle(), theme="editorial-dark")
    assert "#146c2e" in light  # light pass green in the chart svg
    assert "#3fa45f" in dark   # dark pass green in the chart svg


# ── determinism + self-containment + contrast ────────────────────────────────

def test_byte_identical_from_same_bundle():
    bundle = _bundle()
    assert _render(bundle) == _render(bundle)


def test_self_contained_offline():
    out = _render(_bundle())
    assert "@font-face" in out          # fonts embedded, not linked
    assert "base64," in out             # …as data URLs
    assert "<svg" in out                # charts inline
    assert "<script" not in out         # no JS
    assert "http://" not in out.replace("http://www.w3.org/2000/svg", "")  # no CDN


def test_muted_grey_reserved_for_labels_not_body():
    """The muted grey (--xp-muted) is reserved for label-type text only.

    It is the lowest-contrast token, so it must never colour body copy, the
    headline, a metric value, or the verdict word — only eyebrows, labels,
    captions, and footer terms. We audit the component sheet directly: every
    rule that sets `color: var(--xp-muted)` must target a label-type selector.

    (The hex itself legitimately appears in chart SVG axis strokes — those are
    1px rules, not text — so we audit the CSS source, not the rendered hex.)
    """
    from agentxp.render.adapters.html import _COMPONENTS_CSS

    css = _COMPONENTS_CSS.read_text(encoding="utf-8")
    label_tokens = ("eyebrow", "label", "caption", " dt", "unverifiable")
    forbidden = (".xp-doc", ".xp-headline", ".xp-metric-value", ".xp-verdict-word")

    # Walk each `selector { ... }` block; if it assigns color: var(--xp-muted),
    # the selector must read as a label-type element and never a body one.
    for block in css.split("}"):
        if "color: var(--xp-muted)" not in block:
            continue
        selector = block.split("{", 1)[0]
        assert any(tok in selector for tok in label_tokens), selector
        assert not any(bad in selector for bad in forbidden), selector
