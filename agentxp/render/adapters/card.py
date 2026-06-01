"""Social card adapter — a single pixel-locked 1200×1500 portrait share page.

Productizes the editorial prototype card as one self-contained HTML, fed by the
SAME :class:`ViewBundle` as every other tier. Like all adapters it is a PURE
renderer: it reads preformatted strings off the VM, plots ONLY the one stored
hero number (the primary lift, via ``charts.lift_bar``), and reads verification
state off the bundled provenance — it never re-derives a number or a status.

Self-containment is inherited wholesale from the exec HTML tier: the stylesheet
(``brand.css_vars`` + ``brand.font_face_css`` + ``components.css``) is inlined,
fonts are base64-embedded, the hero chart is inline SVG, there is no JS and no
CDN. The shared verdict/status maps and the receipts flattener are reused from
``html.py`` so the two tiers can never drift apart.

DRAFT discipline: a DRAFT_UNVERIFIED status stamps a diagonal ribbon ACROSS the
verdict hero (``is_draft`` in the template), never a footer note — the footer is
the part a LinkedIn screenshot crops away.

Card-as-HTML ships here; card-as-PNG is a deferred rasterization step over this
exact page.
"""
from __future__ import annotations

from pathlib import Path

import jinja2

from agentxp.render import brand, charts
from agentxp.render.adapters.html import (
    _VERDICT_MODIFIER,
    _inline_css,
    _receipts,
)
from agentxp.render.provenance import RenderStatus
from agentxp.render.viewmodel import ViewBundle

_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "templates"
    / "social-card.html.j2"
)


def _hero_chart(bundle: ViewBundle, theme: str) -> str:
    """The single hero plot: the primary-lift bar, in the active theme's palette.

    The card carries exactly one chart (the verdict's headline number); the CI
    and sample land in the callout strip. Always present — the primary metric is
    always present — so unlike the report tier this never returns None.
    """
    cd = bundle.vm.charts
    palette = brand.svg_palette(theme)
    return charts.lift_bar(
        cd.lift_absolute, cd.ci_95_lower, cd.ci_95_upper, cd.direction, palette
    )


class CardAdapter:
    """Render a ViewBundle to a single self-contained 1200×1500 social card."""

    format_id = "card"
    binary = False
    requires_node = False

    def __init__(self, *, theme: str = "editorial-light"):
        self.theme = theme

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
            verdict_modifier=_VERDICT_MODIFIER.get(bundle.vm.verdict, "hold"),
            css=_inline_css(self.theme),
            hero_chart=_hero_chart(bundle, self.theme),
            receipts=_receipts(prov),
            is_draft=prov.render_status is RenderStatus.DRAFT_UNVERIFIED,
        )

    def default_filename(self, bundle: ViewBundle) -> str:
        return f"{bundle.vm.experiment_id}.card.html"


__all__ = ["CardAdapter"]
