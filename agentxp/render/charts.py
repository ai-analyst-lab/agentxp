"""Deterministic, dependency-free inline-SVG charts for the presentation layer.

Every function is PURE: same numeric inputs → byte-identical SVG string, every
time. No randomness, no clock, no layout engine, no JS — the SVG is static and
renders offline inside a single self-contained HTML file.

Hard rule (mirrors distill()'s "numbers once" discipline): a chart plots ONLY
numbers that are stored in ``report.json``. It never runs a statistic. The two
charts that would require a stat we do not persist are gated:

  - :func:`srm_split` returns ``None`` unless BOTH per-arm counts are stored.
  - :func:`power_curve` returns ``None`` unless the engine actually emitted
    curve points (n_required across a sweep of MDE) — it does not today, so the
    function omits rather than fabricating a curve.

The one piece of arithmetic allowed is display-only ratio over two stored ints
(e.g. arm balance) — never inference.

Colors arrive as a resolved ``palette`` (role → hex) from
``brand.svg_palette(theme)`` so no hex literal lives here.
"""
from __future__ import annotations

from typing import Optional

# Fixed geometry so output is byte-stable and theme-independent in layout.
_W = 480
_H_BAR = 72
_H_CI = 96
_PAD_X = 56
_PAD_R = 16


def _f(x: float) -> str:
    """Format a coordinate to 2 decimals, no trailing-zero churn, '-0' normalized."""
    s = f"{x:.2f}"
    return "0.00" if s == "-0.00" else s


def _favorable_role(lift: float, direction: Optional[str]) -> str:
    """Pick the brand role for a lift's bar given the metric's direction.

    Presentation decision only (which stored color to use), never a verdict:
    a positive lift is good when higher_is_better, bad when lower_is_better,
    neutral when direction is unknown/'neither'.
    """
    if direction == "higher_is_better":
        return "bar_positive" if lift >= 0 else "bar_negative"
    if direction == "lower_is_better":
        return "bar_negative" if lift >= 0 else "bar_positive"
    return "point"  # neutral ink for 'neither' / unknown


def _domain(values: list[float]) -> tuple[float, float]:
    """Symmetric-ish domain that always includes zero, padded 8% each side."""
    lo = min(0.0, *values)
    hi = max(0.0, *values)
    span = hi - lo
    pad = span * 0.08 if span else 1.0
    return lo - pad, hi + pad


def _scaler(lo: float, hi: float):
    """Return value→x-pixel mapping over the plot area [_PAD_X, _W-_PAD_R]."""
    x0, x1 = _PAD_X, _W - _PAD_R
    span = hi - lo or 1.0

    def to_x(v: float) -> float:
        return x0 + (v - lo) / span * (x1 - x0)

    return to_x


def _svg_open(height: int, palette: dict) -> str:
    return (
        f"<svg class='xp-chart-svg' viewBox='0 0 {_W} {height}' "
        f"width='{_W}' height='{height}' role='img' "
        f"xmlns='http://www.w3.org/2000/svg'>"
    )


def lift_bar(
    lift_absolute: float,
    ci_95_lower: float,
    ci_95_upper: float,
    direction: Optional[str],
    palette: dict,
) -> str:
    """Point-lift bar against a zero baseline, colored favorable/unfavorable.

    Domain spans the 95% CI (and zero) so the bar is never clipped. Always
    renderable — the primary metric is always present in a report.
    """
    lo, hi = _domain([ci_95_lower, ci_95_upper, lift_absolute])
    to_x = _scaler(lo, hi)
    zero_x = to_x(0.0)
    val_x = to_x(lift_absolute)
    bar_y, bar_h = _H_BAR / 2 - 12, 24
    x_left, x_right = (zero_x, val_x) if val_x >= zero_x else (val_x, zero_x)
    role = _favorable_role(lift_absolute, direction)
    return "".join([
        _svg_open(_H_BAR, palette),
        # baseline rule
        f"<line x1='{_PAD_X}' y1='{_f(bar_y + bar_h + 14)}' "
        f"x2='{_W - _PAD_R}' y2='{_f(bar_y + bar_h + 14)}' "
        f"stroke='{palette['rule']}' stroke-width='1'/>",
        # zero marker
        f"<line x1='{_f(zero_x)}' y1='{_f(bar_y - 6)}' "
        f"x2='{_f(zero_x)}' y2='{_f(bar_y + bar_h + 6)}' "
        f"stroke='{palette['axis']}' stroke-width='1' stroke-dasharray='2 2'/>",
        # the bar
        f"<rect x='{_f(x_left)}' y='{_f(bar_y)}' "
        f"width='{_f(x_right - x_left)}' height='{bar_h}' "
        f"fill='{palette[role]}'/>",
        f"<text x='{_f(zero_x)}' y='{_f(bar_y + bar_h + 28)}' "
        f"font-size='11' fill='{palette['label']}' text-anchor='middle'>0</text>",
        "</svg>",
    ])


def ci_interval(
    lift_absolute: float,
    ci_95_lower: float,
    ci_95_upper: float,
    ci_90_lower: float,
    ci_90_upper: float,
    palette: dict,
) -> str:
    """Nested 95%/90% confidence interval with the point estimate as a dot.

    The 90% whisker sits inside the 95% whisker; the point is the stored lift.
    Always renderable.
    """
    lo, hi = _domain([ci_95_lower, ci_95_upper, lift_absolute])
    to_x = _scaler(lo, hi)
    cy = _H_CI / 2 - 6
    zero_x = to_x(0.0)
    x95l, x95u = to_x(ci_95_lower), to_x(ci_95_upper)
    x90l, x90u = to_x(ci_90_lower), to_x(ci_90_upper)
    xpt = to_x(lift_absolute)
    return "".join([
        _svg_open(_H_CI, palette),
        f"<line x1='{_f(zero_x)}' y1='12' x2='{_f(zero_x)}' y2='{_f(cy + 22)}' "
        f"stroke='{palette['axis']}' stroke-width='1' stroke-dasharray='2 2'/>",
        # 95% line (thin)
        f"<line x1='{_f(x95l)}' y1='{_f(cy)}' x2='{_f(x95u)}' y2='{_f(cy)}' "
        f"stroke='{palette['interval']}' stroke-width='2'/>",
        f"<line x1='{_f(x95l)}' y1='{_f(cy - 8)}' x2='{_f(x95l)}' y2='{_f(cy + 8)}' "
        f"stroke='{palette['interval']}' stroke-width='2'/>",
        f"<line x1='{_f(x95u)}' y1='{_f(cy - 8)}' x2='{_f(x95u)}' y2='{_f(cy + 8)}' "
        f"stroke='{palette['interval']}' stroke-width='2'/>",
        # 90% line (thick, inset)
        f"<line x1='{_f(x90l)}' y1='{_f(cy)}' x2='{_f(x90u)}' y2='{_f(cy)}' "
        f"stroke='{palette['interval']}' stroke-width='6' stroke-opacity='0.45'/>",
        # point estimate
        f"<circle cx='{_f(xpt)}' cy='{_f(cy)}' r='4' fill='{palette['point']}'/>",
        f"<text x='{_f(zero_x)}' y='{_f(cy + 36)}' font-size='11' "
        f"fill='{palette['label']}' text-anchor='middle'>0</text>",
        f"<text x='{_PAD_X}' y='{_f(cy + 36)}' font-size='11' "
        f"fill='{palette['label']}'>95% CI</text>",
        "</svg>",
    ])


def srm_split(
    n_arm_control: Optional[int],
    n_arm_treatment: Optional[int],
    palette: dict,
) -> Optional[str]:
    """Observed arm-balance bar. OMITS (returns None) unless both counts stored.

    Plots only the two stored integers; the 50% reference line is the only
    arithmetic and is display-only, not an SRM test (the verdict already
    carries the SRM result).
    """
    if n_arm_control is None or n_arm_treatment is None:
        return None
    total = n_arm_control + n_arm_treatment
    if total <= 0:
        return None
    x0, x1 = _PAD_X, _W - _PAD_R
    plot_w = x1 - x0
    ctrl_w = n_arm_control / total * plot_w
    bar_y, bar_h = 24, 26
    mid_x = x0 + plot_w / 2
    return "".join([
        _svg_open(_H_BAR, palette),
        f"<rect x='{_PAD_X}' y='{bar_y}' width='{_f(ctrl_w)}' height='{bar_h}' "
        f"fill='{palette['axis']}'/>",
        f"<rect x='{_f(x0 + ctrl_w)}' y='{bar_y}' width='{_f(plot_w - ctrl_w)}' "
        f"height='{bar_h}' fill='{palette['interval']}'/>",
        # 50% reference
        f"<line x1='{_f(mid_x)}' y1='{bar_y - 6}' x2='{_f(mid_x)}' "
        f"y2='{bar_y + bar_h + 6}' stroke='{palette['rule']}' "
        f"stroke-width='1' stroke-dasharray='3 2'/>",
        f"<text x='{_PAD_X}' y='{bar_y + bar_h + 20}' font-size='11' "
        f"fill='{palette['label']}'>control {n_arm_control}</text>",
        f"<text x='{_W - _PAD_R}' y='{bar_y + bar_h + 20}' font-size='11' "
        f"fill='{palette['label']}' text-anchor='end'>treatment "
        f"{n_arm_treatment}</text>",
        "</svg>",
    ])


def power_curve(
    points: Optional[list[tuple[float, int]]],
    palette: dict,
) -> Optional[str]:
    """Required-N across an MDE sweep. OMITS unless curve points were emitted.

    The engine does not persist this sweep today, so callers pass ``None`` and
    the chart is omitted. Kept so that adding the stat upstream needs only a
    renderer here — never a recomputation in the presentation layer.
    """
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [float(p[1]) for p in points]
    x_to = _scaler(*_domain(xs))
    y_lo, y_hi = min(ys), max(ys)
    y_span = (y_hi - y_lo) or 1.0
    top, bottom = 16, _H_CI - 28

    def y_to(v: float) -> float:
        return bottom - (v - y_lo) / y_span * (bottom - top)

    pts = " ".join(f"{_f(x_to(x))},{_f(y_to(y))}" for x, y in zip(xs, ys))
    return "".join([
        _svg_open(_H_CI, palette),
        f"<polyline points='{pts}' fill='none' "
        f"stroke='{palette['interval']}' stroke-width='2'/>",
        f"<text x='{_PAD_X}' y='{_H_CI - 8}' font-size='11' "
        f"fill='{palette['label']}'>MDE →</text>",
        "</svg>",
    ])


__all__ = ["lift_bar", "ci_interval", "srm_split", "power_curve"]
