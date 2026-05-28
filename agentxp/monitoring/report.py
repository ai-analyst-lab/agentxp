"""
Monitoring orchestrator — runs SRM trend + guardrail health + sample
accumulation checks, aggregates verdicts (worst of the three wins), builds
recommendations, and optionally persists via ``ExperimentStore.save_analysis``.

The ``data_loader`` contract is intentionally loose: it is any callable
returning a ``MonitorContext``-like dict with at least:

    {
        "df": pd.DataFrame,
        "treatment_col": str,
        "timestamp_col": str | None,
        "guardrail_metrics": list[str],
        "thresholds": dict[str, dict],
        "required_n": int,
        "daily_traffic": float,
        "days_elapsed": float,
        "planned_duration_days": float | None,    # optional
        "control_value": Any | None,              # optional
        "srm_window": str,                        # optional, default "1d"
        "srm_threshold": float,                   # optional, default 0.0005
        "alpha": float,                           # optional, default 0.05
        "expected_ratios": list[float] | None,    # optional
    }

Callers can pass either a dict directly or a zero-arg callable returning one.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from agentxp.monitoring.base import (
    MonitorReport,
    verdict_to_light,
    worst_light,
)
from agentxp.monitoring.guardrail_health import guardrail_health
from agentxp.monitoring.sample_accumulation import sample_accumulation
from agentxp.monitoring.srm_trend import srm_trend


DataLoaderLike = Mapping[str, Any] | Callable[[], Mapping[str, Any]]


def _resolve_context(data_loader: DataLoaderLike) -> Mapping[str, Any]:
    if callable(data_loader):
        ctx = data_loader()
    else:
        ctx = data_loader
    if not isinstance(ctx, Mapping):
        raise TypeError(
            "data_loader must return a mapping (dict) or be a mapping itself, "
            f"got {type(ctx).__name__}."
        )
    return ctx


def _build_recommendations(
    srm_result: dict,
    guardrail_result: dict,
    sample_result: dict,
) -> list[str]:
    recs: list[str] = []

    # RED issues first.
    if srm_result.get("verdict") == "BLOCK":
        recs.append(
            "HALT ANALYSIS: SRM trend is RED. Run srm_diagnose() to localize the "
            "mismatch and investigate deploy / assignment history near "
            f"{srm_result.get('first_violation_timestamp')}."
        )
    if guardrail_result.get("verdict") == "BLOCK":
        flagged = guardrail_result.get("flagged_metrics", [])
        recs.append(
            f"GUARDRAIL VIOLATION on {flagged}: escalate to experiment owner "
            "and consider emergency halt."
        )
    if sample_result.get("verdict") == "BLOCK":
        recs.append(
            "SAMPLE ACCUMULATION RED: experiment is stalled or >50% behind "
            "plan. Investigate traffic / allocation before continuing."
        )

    # YELLOW issues next.
    if srm_result.get("verdict") == "WARNING":
        recs.append(
            "SRM trend WARNING: marginal mismatch in one or more windows. "
            "Re-check tomorrow; run srm_diagnose() if the signal persists."
        )
    if guardrail_result.get("verdict") == "WARNING":
        flagged = guardrail_result.get("flagged_metrics", [])
        recs.append(
            f"Guardrail WARNING on {flagged}: movement in the bad direction "
            "but still within NIM. Keep watching."
        )
    if sample_result.get("verdict") == "WARNING":
        recs.append(
            "Sample pacing YELLOW: running slow. Consider increasing "
            "allocation or extending the runway, and recompute duration."
        )

    if not recs:
        recs.append(
            "All checks GREEN. Continue monitoring on the normal cadence."
        )

    return recs


def run_monitor(
    experiment_id: str,
    data_loader: DataLoaderLike,
    store: Any | None = None,
    current_n_fn: Callable[[Any], int] | None = None,
) -> MonitorReport:
    """Orchestrate the three monitoring checks and return a ``MonitorReport``.

    Args:
        experiment_id: Slug / id for persistence.
        data_loader: Callable or mapping producing the context dict.
            See module docstring for the required keys.
        store: Optional ``ExperimentStore``. If provided, the report is
            persisted via ``store.save_analysis``.
        current_n_fn: Optional callable ``(df) -> int`` used to compute the
            current enrolled user count when the context dict does not
            supply ``current_n`` explicitly. If ``None``, falls back to
            ``len(df)``, which is row count — correct for one-row-per-user
            tables but WRONG for panel data (repeat events per user).
            Panel-data callers should pass either an explicit ``current_n``
            in the context or a ``current_n_fn`` that counts unique users
            (e.g. ``lambda df: df["user_id"].nunique()``).

    Returns:
        ``MonitorReport`` with aggregated status, per-check results,
        recommendations, and interpretation. If persistence fails with
        ``FileNotFoundError`` (experiment dir not registered in the store),
        the returned report has ``persistence_error`` set and a
        recommendation line noting the failure. Other I/O errors
        (``PermissionError``, ``OSError``) are re-raised.
    """
    ctx = _resolve_context(data_loader)

    df = ctx.get("df")
    if df is None:
        raise ValueError("data_loader context missing required key 'df'.")

    treatment_col = ctx.get("treatment_col")
    if not treatment_col:
        raise ValueError("data_loader context missing required key 'treatment_col'.")

    timestamp_col = ctx.get("timestamp_col")
    guardrail_metrics = list(ctx.get("guardrail_metrics", []) or [])
    thresholds = dict(ctx.get("thresholds", {}) or {})

    srm_window = ctx.get("srm_window", "1d")
    srm_threshold = float(ctx.get("srm_threshold", 0.0005))
    alpha = float(ctx.get("alpha", 0.05))
    expected_ratios = ctx.get("expected_ratios")
    control_value = ctx.get("control_value")

    # ---------- Check 1: SRM trend ----------
    if timestamp_col:
        srm_result = srm_trend(
            df,
            treatment_col=treatment_col,
            timestamp_col=timestamp_col,
            window=srm_window,
            threshold=srm_threshold,
            expected_ratios=expected_ratios,
        )
    else:
        # With no timestamps we cannot trend — return a minimal PASS/WARN
        # block so the report still has three entries.
        srm_result = {
            "test": "srm_trend",
            "verdict": "WARNING",
            "interpretation": (
                "No timestamp column available; skipped SRM trending. "
                "Run srm_check() on the aggregate counts separately."
            ),
        }

    # ---------- Check 2: Guardrail health ----------
    guardrail_result = guardrail_health(
        df,
        treatment_col=treatment_col,
        guardrail_metrics=guardrail_metrics,
        thresholds=thresholds,
        alpha=alpha,
        control_value=control_value,
    )

    # ---------- Check 3: Sample accumulation ----------
    required_n = int(ctx.get("required_n", 0))
    daily_traffic = float(ctx.get("daily_traffic", 0.0))
    days_elapsed = float(ctx.get("days_elapsed", 0.0))
    planned_duration_days = ctx.get("planned_duration_days")
    if "current_n" in ctx:
        current_n = int(ctx["current_n"])
    elif current_n_fn is not None:
        current_n = int(current_n_fn(df))
    else:
        current_n = int(len(df))
    sample_result = sample_accumulation(
        current_n=current_n,
        required_n=required_n,
        daily_traffic=daily_traffic,
        days_elapsed=days_elapsed,
        planned_duration_days=planned_duration_days,
    )

    # ---------- Aggregate ----------
    lights = [
        verdict_to_light(srm_result.get("verdict", "BLOCK")),
        verdict_to_light(guardrail_result.get("verdict", "BLOCK")),
        verdict_to_light(sample_result.get("verdict", "BLOCK")),
    ]
    overall_light = worst_light(lights)

    recommendations = _build_recommendations(
        srm_result, guardrail_result, sample_result
    )

    summary_bits = [
        f"SRM={srm_result.get('verdict')}",
        f"Guardrail={guardrail_result.get('verdict')}",
        f"Sample={sample_result.get('verdict')}",
    ]
    interpretation = (
        f"Overall monitor status: {overall_light} "
        f"({', '.join(summary_bits)}). "
        f"{len(recommendations)} recommendation(s)."
    )

    report = MonitorReport(
        status=overall_light,
        checks={
            "srm_trend": srm_result,
            "guardrail_health": guardrail_result,
            "sample_accumulation": sample_result,
        },
        recommendations=recommendations,
        interpretation=interpretation,
        experiment_id=experiment_id,
    )

    if store is not None:
        try:
            store.save_analysis(experiment_id, report.to_dict())
        except FileNotFoundError as e:
            # Narrow expected case: caller passed a store but the experiment
            # dir doesn't exist (unregistered experiment id). Surface it on
            # the report so agents can see the persistence failure instead
            # of silently getting a success-looking report back.
            err_msg = str(e)
            report.persistence_error = err_msg
            report.recommendations.append(
                f"Persistence failed: {err_msg}; report was not saved. "
                "Hint: call store.save_experiment(experiment_id, ...) first "
                "or double-check the experiment id."
            )
            # Other I/O errors (PermissionError, OSError, etc.) are NOT
            # swallowed — they indicate a real bug and should propagate.

    return report
