"""Three-part integrity lock for the design / analyze wall (R11, T02).

A sealed brief is the only contract between ``agentxp design`` and
``agentxp analyze``. Sealing a brief computes three hashes that the analyze
verb re-verifies on open:

  1. ``design_chain_hash``  — sha256 of the design conversation/log up to
     seal time. Detects edits to the design history after sealing.
  2. ``metric_snapshot``    — name → sha256 of each referenced metric YAML.
     Detects edits to the metric definitions the brief depends on.
  3. ``expected_shape``     — the assignment-table shape the brief
     pre-registers (assignment unit, arm count, ratio, cohorts). Compared
     against the actual warehouse data at analyze-open time.

Any mismatch raises :class:`BriefSealMismatch` and the analyze verb refuses
to open. There is no ``--force`` flag; the user resolves the drift (rev the
brief, restore the metric, etc.) and re-invokes.

The actual analyze-time shape-vs-warehouse check is the orchestrator's job
(it queries the warehouse). This module owns the static hash-based checks
and the data structures.

Closure-test invariant: ``seal_brief(content, ...).verify_against(content, ...)``
returns ``VerifyResult(passed=True, ...)`` for identical inputs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentxp.schemas._types import Sha256Hex


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class BriefSealMismatch(Exception):
    """Brief seal verification failed; the analyze verb refuses to open.

    The exception's ``args[0]`` is a structured :class:`VerifyResult` with the
    specific lock components that mismatched and a human-readable reason for
    each. Catch this at the analyze CLI entry point; do not swallow it
    elsewhere — R11 enforcement depends on this being terminal.
    """

    def __init__(self, verify_result: "VerifyResult") -> None:
        self.verify_result = verify_result
        super().__init__(self._format_message(verify_result))

    @staticmethod
    def _format_message(vr: "VerifyResult") -> str:
        if vr.passed:
            return "verify_result.passed=True; BriefSealMismatch should not be raised"
        lines = ["brief seal verification failed; analyze verb cannot open:"]
        for reason in vr.mismatches:
            lines.append(f"  - {reason}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Expected shape — assignment-table contract recorded at seal time
# ─────────────────────────────────────────────────────────────────────────────


class ExpectedShape(BaseModel):
    """The assignment-table shape the brief pre-registers.

    Recorded at seal time; the orchestrator compares this to the actual
    warehouse data at analyze-open. A real mismatch (e.g., the brief
    pre-registered a 50/50 split but the data shows 30/70) is a hard
    refusal — the user resolves the drift.
    """

    model_config = ConfigDict(extra="forbid")

    assignment_unit: Literal["user_id", "session_id", "device_id", "account_id"]
    arms: list[str] = Field(min_length=2, description="Arm labels, e.g. ['control', 'treatment'].")
    expected_arm_count_ratio: dict[str, float] = Field(
        description="Per-arm expected share. Must sum to ~1.0; tolerance enforced at compare time, not here."
    )
    cohort_definitions: list[str] = Field(
        default_factory=list,
        description="Cohort identifiers the brief scopes (e.g., 'new_users', 'us_only').",
    )


# ─────────────────────────────────────────────────────────────────────────────
# SealedBrief — the brief + three-part integrity lock
# ─────────────────────────────────────────────────────────────────────────────


class SealedBrief(BaseModel):
    """A brief sealed with the three-part integrity lock (R11).

    The ``brief_content`` field is currently ``dict[str, Any]`` placeholder;
    T04 replaces this with the canonical ``BriefDraft`` schema from
    ``agentxp.schemas.experiment`` once that module is tweaked. The hash on
    disk is computed against the serialized JSON of this whole model, so
    promoting ``brief_content`` to a richer type is non-breaking for the
    seal itself.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1

    # The brief content — TODO(T04): replace with BriefDraft from experiment.py
    brief_content: dict[str, Any] = Field(
        description="The brief body. T04 promotes to BriefDraft."
    )

    # Three-part integrity lock — R11 wall
    design_chain_hash: Sha256Hex = Field(
        description="sha256 of the design log/conversation at seal time."
    )
    metric_snapshot: dict[str, Sha256Hex] = Field(
        description="metric name -> sha256 of its YAML at seal time."
    )
    expected_shape: ExpectedShape

    # Audit metadata
    sealed_at: datetime = Field(description="UTC; timezone-aware.")
    sealed_by: str = Field(min_length=1, description="User identifier of the sealer.")
    agentxp_version: str = Field(description="agentxp.__version__ at seal time.")

    @field_validator("sealed_at")
    @classmethod
    def _enforce_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) != timezone.utc.utcoffset(v):
            raise ValueError("sealed_at must be timezone-aware UTC")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# VerifyResult — output of verify_brief_seal
# ─────────────────────────────────────────────────────────────────────────────


class VerifyResult(BaseModel):
    """Output of :func:`verify_brief_seal`. Never raises by itself; the
    analyze CLI inspects this and either proceeds or raises
    :class:`BriefSealMismatch`."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    design_chain_match: bool
    metric_snapshot_matches: dict[str, bool] = Field(
        default_factory=dict,
        description="Per-metric name -> match. Missing metric -> False.",
    )
    missing_metrics: list[str] = Field(
        default_factory=list,
        description="Metric names in the snapshot whose YAML file no longer exists.",
    )
    mismatches: list[str] = Field(
        default_factory=list,
        description="Human-readable reasons for each lock component that failed.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Hash helpers
# ─────────────────────────────────────────────────────────────────────────────


def _sha256_file(path: Path) -> str:
    """Return the lowercase hex sha256 of ``path``'s bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    """Return the lowercase hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Public API — seal / verify
# ─────────────────────────────────────────────────────────────────────────────


def seal_brief(
    *,
    brief_content: dict[str, Any],
    design_chain_path: Path,
    metric_paths: dict[str, Path],
    expected_shape: ExpectedShape,
    sealed_by: str,
    agentxp_version: str,
    sealed_at: Optional[datetime] = None,
) -> SealedBrief:
    """Compute the three-part integrity lock and return a SealedBrief.

    Raises :class:`FileNotFoundError` if any of the input paths does not
    exist. The seal computation is deterministic for a fixed input set —
    re-sealing with identical inputs produces identical hashes.

    Keyword-only to make the call site unambiguous (which path is which
    is otherwise easy to mix up).
    """
    if not design_chain_path.exists():
        raise FileNotFoundError(
            f"design_chain_path does not exist: {design_chain_path}"
        )

    design_chain_hash = _sha256_file(design_chain_path)

    metric_snapshot: dict[str, str] = {}
    for name, path in metric_paths.items():
        if not path.exists():
            raise FileNotFoundError(
                f"metric path for {name!r} does not exist: {path}"
            )
        metric_snapshot[name] = _sha256_file(path)

    return SealedBrief(
        brief_content=brief_content,
        design_chain_hash=design_chain_hash,
        metric_snapshot=metric_snapshot,
        expected_shape=expected_shape,
        sealed_at=sealed_at or datetime.now(timezone.utc),
        sealed_by=sealed_by,
        agentxp_version=agentxp_version,
    )


def verify_brief_seal(
    *,
    sealed: SealedBrief,
    design_chain_path: Path,
    metric_paths: dict[str, Path],
) -> VerifyResult:
    """Re-check all three lock components against current files.

    Returns a :class:`VerifyResult` with per-component pass/fail. Never
    raises (file-not-found surfaces as a mismatch reason, not an exception)
    so the analyze CLI can render the full picture to the user before
    refusing.

    Note: the ``expected_shape`` vs warehouse-data check is the
    orchestrator's job (it requires querying the warehouse) and is not
    performed here. This function owns the static hash checks only.
    """
    mismatches: list[str] = []
    missing_metrics: list[str] = []

    # 1. design_chain_hash
    if not design_chain_path.exists():
        design_chain_match = False
        mismatches.append(
            f"design chain file missing: {design_chain_path}"
        )
    else:
        current_design_hash = _sha256_file(design_chain_path)
        design_chain_match = current_design_hash == sealed.design_chain_hash
        if not design_chain_match:
            mismatches.append(
                f"design chain hash mismatch: "
                f"sealed={sealed.design_chain_hash[:12]}…, "
                f"current={current_design_hash[:12]}…"
            )

    # 2. metric_snapshot
    metric_snapshot_matches: dict[str, bool] = {}
    for name, sealed_hash in sealed.metric_snapshot.items():
        path = metric_paths.get(name)
        if path is None or not path.exists():
            metric_snapshot_matches[name] = False
            missing_metrics.append(name)
            mismatches.append(
                f"metric YAML missing for {name!r}: "
                f"{path if path else '(no path supplied)'}"
            )
            continue
        current_hash = _sha256_file(path)
        match = current_hash == sealed_hash
        metric_snapshot_matches[name] = match
        if not match:
            mismatches.append(
                f"metric YAML hash mismatch for {name!r}: "
                f"sealed={sealed_hash[:12]}…, current={current_hash[:12]}…"
            )

    passed = design_chain_match and all(metric_snapshot_matches.values())

    return VerifyResult(
        passed=passed,
        design_chain_match=design_chain_match,
        metric_snapshot_matches=metric_snapshot_matches,
        missing_metrics=missing_metrics,
        mismatches=mismatches,
    )


def verify_or_raise(
    *,
    sealed: SealedBrief,
    design_chain_path: Path,
    metric_paths: dict[str, Path],
) -> None:
    """Convenience wrapper: verify, raise BriefSealMismatch on failure.

    The CLI ``agentxp analyze --brief <path>`` calls this as the first
    action; the raise terminates the verb before any outcome data is read.
    """
    result = verify_brief_seal(
        sealed=sealed,
        design_chain_path=design_chain_path,
        metric_paths=metric_paths,
    )
    if not result.passed:
        raise BriefSealMismatch(result)


__all__ = [
    "ExpectedShape",
    "SealedBrief",
    "VerifyResult",
    "BriefSealMismatch",
    "seal_brief",
    "verify_brief_seal",
    "verify_or_raise",
]
