"""Exec HTML adapter — a single self-contained, offline-safe report page.

Like every adapter it is a PURE renderer over a :class:`ViewBundle`: it reads
preformatted strings off the VM, plots ONLY the stored numbers the VM carries
(via ``charts.py``), and reads verification state off the bundled provenance —
it never re-derives a number or decides a status.

Self-containment discipline (inherited from ``cli/audit_html.py``):
  - one file, no external assets — CSS is inlined from the brand layer
    (``brand.css_vars`` + ``brand.font_face_css`` + ``components.css``), fonts
    are base64-embedded, charts are inline SVG, no JS, no CDN;
  - ``autoescape=True`` on the Jinja env — every VM string is HTML-escaped;
    the only ``|safe`` values are SVG fragments WE generated in ``charts.py``.

Audience switch:
  - ``exec`` (default): verdict-first, headline metrics, compact receipts
    footer; the full audit trail is hidden.
  - ``skeptic``: same, plus the full audit-trail table.

The ``.xp-receipts-footer`` is mandatory and built from the LIVE render status;
a DRAFT_UNVERIFIED status also stamps a loud top banner.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import jinja2

from agentxp.render import brand, charts
from agentxp.render.provenance import Provenance, RenderStatus
from agentxp.render.receipts import chain_hash_short, chain_token
from agentxp.render.viewmodel import ViewBundle

_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "templates"
    / "experiment-report.html.j2"
)
_COMPONENTS_CSS = (
    Path(__file__).resolve().parent.parent.parent
    / "assets"
    / "design"
    / "components.css"
)

Audience = Literal["exec", "skeptic"]

# Verdict → badge style modifier. This is presentation styling only — the badge
# ALWAYS carries the verdict WORD, so colour is redundant reinforcement, never
# the signal, and this map never re-decides the verdict.
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


def _chart_svgs(bundle: ViewBundle, theme: str) -> list[dict]:
    """Pre-render the present charts to (caption, safe-svg) entries, in order.

    Omitted charts (srm_split without arm counts, power_curve without points)
    simply do not appear — the renderer never fabricates a plot. The palette is
    resolved for the active theme so chart colours match the page (dark charts
    on dark paper), keeping the brand the single source for every colour.
    """
    cd = bundle.vm.charts
    palette = brand.svg_palette(theme)
    entries: list[dict] = []

    entries.append({
        "caption": "Primary lift (point estimate)",
        "svg": charts.lift_bar(
            cd.lift_absolute, cd.ci_95_lower, cd.ci_95_upper, cd.direction, palette
        ),
    })
    entries.append({
        "caption": "Confidence interval (95% / 90%)",
        "svg": charts.ci_interval(
            cd.lift_absolute, cd.ci_95_lower, cd.ci_95_upper,
            cd.ci_90_lower, cd.ci_90_upper, palette,
        ),
    })
    srm = charts.srm_split(cd.n_arm_control, cd.n_arm_treatment, palette)
    if srm is not None:
        entries.append({"caption": "Arm balance (observed)", "svg": srm})
    # power_curve omitted: the engine emits no curve points today.
    return entries


def _receipts(prov: Provenance) -> dict:
    """Flatten the provenance into the fields the receipts footer renders."""
    return {
        "status": prov.render_status.value,
        "status_class": _STATUS_CLASS[prov.render_status],
        "status_reason": prov.status_reason,
        "chain_token": chain_token(prov),
        "replay_command": prov.replay_command,
        "chain_hash_short": chain_hash_short(prov.chain_hash_stored),
        "chain_hash_full": prov.chain_hash_stored,
        "locked_brief_hash": prov.locked_brief_hash,
        "agentxp_version": prov.agentxp_version,
    }


class HtmlAdapter:
    """Render a ViewBundle to a single self-contained HTML report page."""

    format_id = "html"
    binary = False
    requires_node = False

    def __init__(self, *, theme: str = "editorial-light", audience: Audience = "exec"):
        self.theme = theme
        self.audience = audience

    def _env(self) -> jinja2.Environment:
        return jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_PATH.parent)),
            autoescape=True,  # HTML output — escape every VM string
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=jinja2.StrictUndefined,
        )

    def render(self, bundle: ViewBundle) -> str:
        prov = bundle.provenance
        template = self._env().get_template(_TEMPLATE_PATH.name)
        return template.render(
            vm=bundle.vm,
            audience=self.audience,
            verdict_modifier=_VERDICT_MODIFIER.get(bundle.vm.verdict, "hold"),
            css=_inline_css(self.theme),
            charts=_chart_svgs(bundle, self.theme),
            receipts=_receipts(prov),
            is_draft=prov.render_status is RenderStatus.DRAFT_UNVERIFIED,
            show_audit=self.audience == "skeptic",
        )

    def default_filename(self, bundle: ViewBundle) -> str:
        return f"{bundle.vm.experiment_id}.report.html"


__all__ = ["HtmlAdapter", "Audience"]
