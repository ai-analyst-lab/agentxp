"""
Canonical data preparation step for AgentXP experiments.

This is the mandatory first step in any analysis pipeline. Raw user data
never reaches a statistical test function directly — it always flows
through ``prepare_experiment_data`` first for schema discovery, missing-
value handling, type coercion, and optional winsorization.

See PRD §5.13 "Data Preparation Protocol" for the canonical pipeline.
"""

from __future__ import annotations

import pandas as pd
from pandas.api import types as ptypes

from agentxp.data.discovery import discover_schema
from agentxp.stats.ab_tests import winsorize


def prepare_experiment_data(
    df,
    treatment_col=None,
    metric_cols=None,
    segment_cols=None,
    winsorize_spec=None,
):
    """Clean and validate an experiment DataFrame before hypothesis testing.

    Pipeline:
        1. Schema discovery (if any column args are None).
        2. Drop rows with missing treatment.
        3. Coerce metric columns to numeric (invalid entries → NaN → dropped
           for that metric only via downstream analyzers).
        4. Optional per-metric winsorization.
        5. Warn if drop rate exceeds 5% of input rows.

    Args:
        df: pandas DataFrame to prepare.
        treatment_col: name of the treatment/variant column. If None, schema
            is auto-discovered.
        metric_cols: list of outcome column names. If None, discovered.
        segment_cols: list of segment column names. If None, discovered.
        winsorize_spec: optional dict mapping metric name to a (lower, upper)
            quantile tuple, e.g. ``{"revenue": (0.0, 0.99)}``. Metrics not
            listed are not winsorized (default is no winsorization).

    Returns:
        dict with: cleaned_df (pd.DataFrame), schema (SchemaDiscovery),
        n_rows_input, n_rows_output, n_rows_dropped, reasons (list[str]),
        winsorized (list[str]), warnings (list[str]), interpretation.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"prepare_experiment_data expected a pandas DataFrame, got {type(df).__name__}"
        )
    if winsorize_spec is not None and not isinstance(winsorize_spec, dict):
        raise TypeError(
            "winsorize_spec must be a dict mapping metric name to (lower, upper) "
            "quantile tuples."
        )

    n_rows_input = len(df)
    reasons: list[str] = []
    warnings: list[str] = []

    # 1. Schema discovery / resolution.
    schema = discover_schema(df)

    resolved_treatment = treatment_col or schema.treatment_column
    if resolved_treatment is None:
        raise ValueError(
            "Could not determine treatment column — pass treatment_col explicitly. "
            f"Discovery notes: {schema.needs_disambiguation}"
        )
    if resolved_treatment not in df.columns:
        raise ValueError(
            f"treatment_col '{resolved_treatment}' not found in DataFrame columns."
        )

    resolved_metrics = metric_cols if metric_cols is not None else schema.metric_columns
    if not resolved_metrics:
        raise ValueError(
            "No metric columns resolved — pass metric_cols explicitly or ensure "
            "the DataFrame has numeric outcome columns."
        )
    for col in resolved_metrics:
        if col not in df.columns:
            raise ValueError(f"metric column '{col}' not found in DataFrame.")

    resolved_segments = (
        segment_cols if segment_cols is not None else schema.segment_columns
    )
    for col in resolved_segments:
        if col not in df.columns:
            raise ValueError(f"segment column '{col}' not found in DataFrame.")

    cleaned = df.copy()

    # 2. Drop rows with missing treatment.
    n_before = len(cleaned)
    cleaned = cleaned[cleaned[resolved_treatment].notna()]
    n_dropped_treatment = n_before - len(cleaned)
    if n_dropped_treatment > 0:
        reasons.append(
            f"Dropped {n_dropped_treatment} rows with missing '{resolved_treatment}'."
        )

    # 3. Type-coerce metric cols to numeric (non-parseable → NaN).
    for col in resolved_metrics:
        if not ptypes.is_numeric_dtype(cleaned[col]):
            coerced = pd.to_numeric(cleaned[col], errors="coerce")
            n_coerced = int(coerced.isna().sum() - cleaned[col].isna().sum())
            cleaned[col] = coerced
            if n_coerced > 0:
                warnings.append(
                    f"Metric '{col}' had {n_coerced} non-numeric values coerced to NaN."
                )

    # 4. Winsorize per spec.
    winsorized_cols: list[str] = []
    if winsorize_spec:
        for col, bounds in winsorize_spec.items():
            if col not in cleaned.columns:
                warnings.append(
                    f"winsorize_spec references unknown column '{col}' — skipped."
                )
                continue
            try:
                lower, upper = bounds
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"winsorize_spec[{col!r}] must be a (lower, upper) tuple."
                ) from exc
            if not (0 <= lower < upper <= 1):
                raise ValueError(
                    f"winsorize_spec[{col!r}] bounds must satisfy 0 <= lower < upper <= 1 "
                    f"(got {bounds})."
                )
            cleaned[col] = winsorize(cleaned[col], lower=lower, upper=upper).reindex(
                cleaned.index
            )
            winsorized_cols.append(col)

    n_rows_output = len(cleaned)
    n_rows_dropped = n_rows_input - n_rows_output

    # 5. Warn on high drop rate.
    if n_rows_input > 0 and n_rows_dropped / n_rows_input > 0.05:
        warnings.append(
            f"Dropped {n_rows_dropped}/{n_rows_input} rows "
            f"({n_rows_dropped / n_rows_input:.1%}) — data quality issue?"
        )

    interp_parts = [
        f"Prepared {n_rows_output:,}/{n_rows_input:,} rows "
        f"(dropped {n_rows_dropped}).",
        f"Treatment column: '{resolved_treatment}'.",
        f"Metric columns: {resolved_metrics}.",
    ]
    if winsorized_cols:
        interp_parts.append(f"Winsorized: {winsorized_cols}.")
    if warnings:
        interp_parts.append(f"Warnings: {len(warnings)}.")
    interpretation = " ".join(interp_parts)

    return {
        "cleaned_df": cleaned,
        "schema": schema,
        "treatment_col": resolved_treatment,
        "metric_cols": list(resolved_metrics),
        "segment_cols": list(resolved_segments),
        "n_rows_input": int(n_rows_input),
        "n_rows_output": int(n_rows_output),
        "n_rows_dropped": int(n_rows_dropped),
        "reasons": reasons,
        "winsorized": winsorized_cols,
        "warnings": warnings,
        "interpretation": interpretation,
    }
