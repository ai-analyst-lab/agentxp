"""Stage-0 profiler driver — runs SUMMARIZE + HG-D4 heuristics, emits ProfileReport."""
from __future__ import annotations

# Stage-0 profiler entry point for AgentXP v0.1.
# Spec refs (experimentation-platform/OPENXP_V01_PLAN.md):
#   §3   stage table  — profiler is the Stage-0 agent (purpose=profile).
#   §5   agent table  — emits bundles/profiler.out.yaml at schema_version 1.
#   HG-D4             — null-rate-on-identifier + mixed-timestamp-format heuristics.
#   F.PRACTICE.01/02  — referenced_artifact_changed / mixed_timestamp_formats gates.
# The ydata sidecar (W_pre2.3) is intentionally NOT invoked here — it's an
# optional CLI pathway (W_pre2.4) layered on top of this driver.

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import yaml

from agentxp.schemas.profiler import ColumnProfile, ProfileReport

__all__ = ["profile_dataset", "write_profile_bundle", "compute_schema_fingerprint"]


def compute_schema_fingerprint(columns: list[ColumnProfile]) -> str:
    """SHA256 hex digest of ``\\n``-joined sorted ``"{name}:{dtype}"`` pairs."""
    pairs = sorted(f"{c.name}:{c.dtype}" for c in columns)
    return hashlib.sha256("\n".join(pairs).encode("utf-8")).hexdigest()


def _aggregate_table_flags(
    columns: list[ColumnProfile],
) -> tuple[bool, list[str], bool, Optional[str]]:
    mixed = any(c.mixed_format_detected for c in columns)
    samples: list[str] = []
    seen: set[str] = set()
    for c in columns:
        for s in c.format_samples:
            if s not in seen:
                seen.add(s)
                samples.append(s)
            if len(samples) >= 10:
                break
        if len(samples) >= 10:
            break

    flagged = any(c.flagged_for_review for c in columns)
    reasons = [c.flag_reason for c in columns if c.flagged_for_review and c.flag_reason]
    reason = "; ".join(reasons) if reasons else None
    return mixed, samples, flagged, reason


def _compose_suggestions(columns: list[ColumnProfile], row_count: int) -> list[str]:
    out: list[str] = []
    for c in columns:
        if (
            c.dtype in ("integer", "string")
            and c.null_rate == 0.0
            and c.distinct_count is not None
            and c.distinct_count == row_count
        ):
            out.append(f"{c.name} looks like an entity primary key")
    return out


def profile_dataset(
    source_ref: str,
    *,
    adapter_type: Literal["duckdb", "snowflake", "bigquery"] = "duckdb",
    file_path: Optional[Path] = None,
    sample_values_n: int = 10,
    flag_null_rate_threshold: float = 0.5,
    flag_format_min_distinct_formats: int = 2,
) -> ProfileReport:
    """Run Stage-0 profiling for ``source_ref`` and return a ``ProfileReport``."""
    if adapter_type != "duckdb":
        raise NotImplementedError(f"adapter {adapter_type!r} ships in W_sql")

    # Deferred imports — the SUMMARIZE adapter + HG-D4 heuristics land in
    # W_pre2.2; importing them at module load would break ``from
    # agentxp.profiler import ...`` while that work is in flight.
    from agentxp.profiler.duckdb_summarize import run_duckdb_summarize  # type: ignore[import-not-found]
    from agentxp.profiler.heuristics import apply_hg_d4_heuristics  # type: ignore[import-not-found]

    summarize = run_duckdb_summarize(
        source_ref,
        file_path=file_path,
        sample_values_n=sample_values_n,
    )
    row_count: int = summarize["row_count"]
    raw_columns: list[dict] = summarize["columns"]

    columns: list[ColumnProfile] = []
    for raw in raw_columns:
        enriched = apply_hg_d4_heuristics(
            raw,
            row_count=row_count,
            flag_null_rate_threshold=flag_null_rate_threshold,
            flag_format_min_distinct_formats=flag_format_min_distinct_formats,
        )
        columns.append(ColumnProfile(**enriched))

    mixed, samples, flagged, reason = _aggregate_table_flags(columns)
    schema_sha256 = compute_schema_fingerprint(columns)

    return ProfileReport(
        schema_version=1,
        source_ref=source_ref,
        profiled_at=datetime.now(timezone.utc),
        row_count=row_count,
        column_count=len(columns),
        schema_sha256=schema_sha256,
        columns=columns,
        mixed_format_detected=mixed,
        format_samples=samples,
        flagged_for_review=flagged,
        flag_reason=reason,
        suggestions=_compose_suggestions(columns, row_count),
        metadata={},
    )


def write_profile_bundle(report: ProfileReport, bundle_path: Path) -> None:
    """Atomically write ``report`` as YAML to ``bundle_path`` with mode 0o600."""
    bundle_path = Path(bundle_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)

    payload = yaml.safe_dump(
        report.model_dump(mode="json"),
        sort_keys=False,
    ).encode("utf-8")

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{bundle_path.name}.",
        suffix=".tmp",
        dir=str(bundle_path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, bundle_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
