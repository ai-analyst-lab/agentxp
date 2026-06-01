"""W5-T3 — visual-QA gate for the 1200×1500 social card adapter.

Like the exec-HTML gate, this is a structural + invariant snapshot (no browser
in CI), pinning the load-bearing guarantees specific to the card:

  - the verdict WORD is always present and the verdict-hero colour modifier
    tracks the verdict (badge never relies on colour alone);
  - a DRAFT status strikes the diagonal RIBBON across the verdict hero — never a
    footer note (the footer is the croppable part of a LinkedIn screenshot);
  - the compact receipts footer is always present (status + replay command);
  - the page is self-contained and offline (embedded fonts, inline SVG, no JS,
    no CDN) and byte-identical from the same bundle;
  - the fixed 1200×1500 frame is pinned;
  - cross-format equality: the lift / CI / verdict strings the card prints are
    byte-identical to what the html and md tiers print (numbers formatted once).
"""
from __future__ import annotations

import pytest

from agentxp.render.adapters.card import CardAdapter
from agentxp.render.adapters.html import HtmlAdapter
from agentxp.render.adapters.markdown import MarkdownAdapter
from agentxp.render.provenance import Provenance, RenderStatus
from agentxp.render.viewmodel import (
    ChartData,
    Diagnostics,
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


def _vm(*, verdict: str = "SHIP", sample_pct=107) -> ReportVM:
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
            guardrails_violated=[],
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


def _render(bundle, *, theme="editorial-light") -> str:
    return CardAdapter(theme=theme).render(bundle)


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
def test_verdict_word_and_hero_modifier(verdict, modifier):
    out = _render(_bundle(_vm(verdict=verdict)))
    assert f">{verdict}</span>" in out
    assert f"xp-card-verdict--{modifier}" in out


# ── DRAFT ribbon (over the hero, not the footer) ─────────────────────────────

def test_draft_strikes_ribbon_over_hero_calm_does_not():
    ribbon_el = '<div class="xp-card-ribbon"'
    draft = _render(_bundle(status=RenderStatus.DRAFT_UNVERIFIED))
    assert ribbon_el in draft
    assert "DRAFT — UNVERIFIED" in draft
    # the ribbon must sit inside the hero block, ahead of the verdict word.
    # (compare body-only tokens — the class names also appear in the <style>.)
    assert draft.index(ribbon_el) < draft.index(">SHIP</span>")

    for calm in (RenderStatus.VERIFIED, RenderStatus.UNVERIFIABLE):
        out = _render(_bundle(status=calm))
        assert ribbon_el not in out


# ── receipts footer (compact, always present) ────────────────────────────────

def test_receipts_footer_always_present():
    status_class = {
        RenderStatus.VERIFIED: "verified",
        RenderStatus.DRAFT_UNVERIFIED: "draft",
        RenderStatus.UNVERIFIABLE: "unverifiable",
    }
    for status in RenderStatus:
        out = _render(_bundle(status=status))
        assert "xp-card-footer" in out
        assert "agentxp audit exp_001" in out  # replay command travels with it
        assert f"xp-render-status--{status_class[status]}" in out


# ── fixed frame + themes ─────────────────────────────────────────────────────

def test_fixed_1200x1500_frame():
    out = _render(_bundle())
    assert "width: 1200px;" in out
    assert "height: 1500px;" in out


def test_light_and_dark_carry_their_paper():
    light = _render(_bundle(), theme="editorial-light")
    dark = _render(_bundle(), theme="editorial-dark")
    assert "--xp-paper: #f6f2e9;" in light
    assert "--xp-paper: #14120d;" in dark


# ── determinism + self-containment ───────────────────────────────────────────

def test_byte_identical_from_same_bundle():
    bundle = _bundle()
    assert _render(bundle) == _render(bundle)


def test_self_contained_offline():
    out = _render(_bundle())
    assert "@font-face" in out
    assert "base64," in out
    assert "<svg" in out
    assert "<script" not in out
    assert "http://" not in out.replace("http://www.w3.org/2000/svg", "")


# ── cross-format equality (numbers formatted exactly once) ───────────────────

def test_lift_ci_verdict_byte_identical_across_card_html_md():
    bundle = _bundle()
    card = _render(bundle)
    html = HtmlAdapter(theme="editorial-light").render(bundle)
    md = MarkdownAdapter().render(bundle)

    lift = bundle.vm.metric_table[0].lift_str
    ci = bundle.vm.metric_table[0].ci_95
    verdict = bundle.vm.verdict
    for out in (card, html, md):
        assert lift in out
        assert ci in out
        assert verdict in out
