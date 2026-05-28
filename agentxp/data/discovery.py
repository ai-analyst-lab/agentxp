"""
Data discovery protocol for AgentXP.

Implements the 7-step detection rules from ``CLAUDE.md`` §"Data Discovery
Protocol" and PRD §5.5 / §5.13. The discovery layer is the only place that
knows about common column names — everywhere else in AgentXP, columns are
passed in by the caller.
"""

from __future__ import annotations

import pandas as pd
from pandas.api import types as ptypes

from agentxp.data.base import SchemaDiscovery


# Common names for the treatment / variant column.  These are *hints* used
# only by the discovery layer — no other AgentXP code should reference them.
TREATMENT_COLUMN_HINTS: tuple[str, ...] = (
    "variant",
    "group",
    "treatment",
    "arm",
    "experiment_group",
    "bucket",
)

# Values that commonly indicate the control arm.  Matched case-insensitively.
CONTROL_VALUE_HINTS: tuple[str, ...] = (
    "control",
    "ctrl",
    "c",
    "baseline",
    "a",
    "0",
)

# Hint patterns for id-like columns that should never be treated as segments
# or metrics.
ID_COLUMN_PATTERNS: tuple[str, ...] = (
    "id",
    "uuid",
    "guid",
    "user",
    "session",
    "device",
    "account",
)

# Hint patterns for timestamp columns (used when dtype detection is
# inconclusive).
TIMESTAMP_NAME_PATTERNS: tuple[str, ...] = (
    "time",
    "date",
    "timestamp",
    "_at",
    "created",
    "updated",
    "exposed",
    "assigned",
)


def _looks_like_id(colname: str) -> bool:
    lowered = colname.lower()
    return any(tok in lowered for tok in ID_COLUMN_PATTERNS)


def _detect_treatment_column(df: pd.DataFrame) -> tuple[str | None, str]:
    """Return (column_name, confidence) using hint names + structural fallback."""
    lowered = {c.lower(): c for c in df.columns}

    # 1. Exact-hint match (highest confidence).
    for hint in TREATMENT_COLUMN_HINTS:
        if hint in lowered:
            return lowered[hint], "high"

    # 2. Structural fallback: a low-cardinality non-numeric column with 2-5
    #    unique values is very likely the variant column.
    candidates: list[tuple[str, int]] = []
    for col in df.columns:
        if _looks_like_id(col):
            continue
        if ptypes.is_numeric_dtype(df[col]):
            continue
        nunique = df[col].dropna().nunique()
        if 2 <= nunique <= 5:
            candidates.append((col, nunique))

    if len(candidates) == 1:
        return candidates[0][0], "medium"
    if len(candidates) > 1:
        # Prefer the column with the fewest unique values, but flag as low.
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0], "low"

    return None, "none"


def _detect_control_value(series: pd.Series) -> tuple[object | None, str]:
    """Return (control_value, confidence) from a treatment series."""
    values = series.dropna().unique().tolist()
    if len(values) == 0:
        return None, "none"

    lowered = {str(v).lower(): v for v in values}
    for hint in CONTROL_VALUE_HINTS:
        if hint in lowered:
            return lowered[hint], "high"

    # If there are exactly two values and one is numeric 0, assume 0 = control.
    if len(values) == 2:
        for v in values:
            try:
                if float(v) == 0:
                    return v, "medium"
            except (TypeError, ValueError):
                pass

    return None, "low"


def _detect_metric_columns(
    df: pd.DataFrame, treatment_column: str | None
) -> list[str]:
    """Numeric columns that aren't id-like or the treatment column."""
    metrics: list[str] = []
    for col in df.columns:
        if col == treatment_column:
            continue
        if _looks_like_id(col):
            continue
        if ptypes.is_numeric_dtype(df[col]):
            metrics.append(col)
    return metrics


def _detect_segment_columns(
    df: pd.DataFrame, treatment_column: str | None
) -> list[str]:
    """Categorical / low-cardinality columns with 2-20 unique values.

    Excludes id-like columns and the treatment column itself.
    """
    segments: list[str] = []
    for col in df.columns:
        if col == treatment_column:
            continue
        if _looks_like_id(col):
            continue
        s = df[col].dropna()
        if len(s) == 0:
            continue

        nunique = s.nunique()
        if not (2 <= nunique <= 20):
            continue

        # Numeric columns count as segments only if they look like discrete
        # buckets (small integer range), otherwise they're metrics.
        if ptypes.is_numeric_dtype(s):
            # e.g. converted {0,1} — let these through so boolean-ish flags
            # can still serve as a segmentation dimension.
            if nunique <= 5 and ptypes.is_integer_dtype(s):
                segments.append(col)
            continue

        segments.append(col)
    return segments


def _detect_timestamp_columns(df: pd.DataFrame) -> list[str]:
    """Columns that are datetime dtype OR look parseable as dates by name."""
    timestamps: list[str] = []
    for col in df.columns:
        if ptypes.is_datetime64_any_dtype(df[col]):
            timestamps.append(col)
            continue
        lowered = col.lower()
        if any(pat in lowered for pat in TIMESTAMP_NAME_PATTERNS):
            # Try a soft parse on the first non-null sample.
            sample = df[col].dropna().head(5)
            if len(sample) == 0:
                continue
            try:
                pd.to_datetime(sample, errors="raise")
                timestamps.append(col)
            except (ValueError, TypeError):
                pass
    return timestamps


def _detect_unit_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if _looks_like_id(c)]


def discover_schema(df: pd.DataFrame) -> SchemaDiscovery:
    """Auto-detect experiment schema from a DataFrame.

    Follows the 7-step detection rules:
      1. Treatment column from common names / structural fallback
      2. Control value from common labels
      3. Treatment values = everything in the treatment column minus control
      4. Metric columns = numeric, non-id
      5. Segment columns = categorical with 2-20 unique values
      6. Timestamp columns = datetime dtype or parseable by name
      7. Ambiguities collected in ``needs_disambiguation``

    Args:
        df: pandas DataFrame to inspect. Not mutated.

    Returns:
        SchemaDiscovery with confidence flags and a plain-language
        ``interpretation`` string.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"discover_schema expected a pandas DataFrame, got {type(df).__name__}"
        )

    disambiguation: list[str] = []
    confidence: dict[str, str] = {}

    treatment_column, t_conf = _detect_treatment_column(df)
    confidence["treatment_column"] = t_conf
    if treatment_column is None:
        disambiguation.append(
            "Which column is the treatment indicator? (no variant-like column found)"
        )

    control_value: object | None = None
    treatment_values: list[object] = []
    if treatment_column is not None:
        control_value, c_conf = _detect_control_value(df[treatment_column])
        confidence["control_value"] = c_conf
        all_values = df[treatment_column].dropna().unique().tolist()
        if control_value is not None:
            treatment_values = [v for v in all_values if v != control_value]
        else:
            treatment_values = all_values
            disambiguation.append(
                f"What value in column '{treatment_column}' represents control?"
            )
        if t_conf == "low":
            disambiguation.append(
                f"Column '{treatment_column}' was detected as the treatment"
                " column with low confidence — please confirm."
            )

    metric_columns = _detect_metric_columns(df, treatment_column)
    segment_columns = _detect_segment_columns(df, treatment_column)
    timestamp_columns = _detect_timestamp_columns(df)
    unit_columns = _detect_unit_columns(df)

    confidence["metric_columns"] = "high" if metric_columns else "none"
    confidence["segment_columns"] = "high" if segment_columns else "none"
    confidence["timestamp_columns"] = "high" if timestamp_columns else "none"

    if not metric_columns:
        disambiguation.append(
            "No numeric metric columns detected — please specify the outcome column(s)."
        )

    interpretation = _format_interpretation(
        treatment_column=treatment_column,
        control_value=control_value,
        treatment_values=treatment_values,
        metric_columns=metric_columns,
        segment_columns=segment_columns,
        timestamp_columns=timestamp_columns,
        n_rows=len(df),
    )

    return SchemaDiscovery(
        treatment_column=treatment_column,
        control_value=control_value,
        treatment_values=treatment_values,
        metric_columns=metric_columns,
        segment_columns=segment_columns,
        timestamp_columns=timestamp_columns,
        unit_columns=unit_columns,
        confidence=confidence,
        needs_disambiguation=disambiguation,
        n_rows=len(df),
        n_columns=df.shape[1],
        interpretation=interpretation,
    )


def _format_interpretation(
    *,
    treatment_column: str | None,
    control_value: object | None,
    treatment_values: list[object],
    metric_columns: list[str],
    segment_columns: list[str],
    timestamp_columns: list[str],
    n_rows: int,
) -> str:
    parts: list[str] = [f"Discovered schema for {n_rows:,}-row dataset:"]
    if treatment_column is not None:
        if control_value is not None:
            parts.append(
                f"treatment column '{treatment_column}' (control='{control_value}',"
                f" treatment={treatment_values})"
            )
        else:
            parts.append(
                f"treatment column '{treatment_column}' with values {treatment_values}"
                " (control value ambiguous)"
            )
    else:
        parts.append("no treatment column detected (needs user input)")

    if metric_columns:
        parts.append(f"{len(metric_columns)} metric column(s): {metric_columns}")
    else:
        parts.append("no numeric metric columns detected")

    if segment_columns:
        parts.append(f"{len(segment_columns)} segment column(s): {segment_columns}")
    if timestamp_columns:
        parts.append(f"timestamp column(s): {timestamp_columns}")

    return "; ".join(parts) + "."
