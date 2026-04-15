"""Validator for experiment.yaml documents.

Philosophy
----------
Collect ALL problems in a single pass. Never stop at the first finding.
Each finding is an :class:`OpenXPError` with a stable code, a human
message, and an actionable hint. The returned :class:`ValidationReport`
lets callers render every fix the user needs in one go.

This validator accepts either a filesystem path, a dict already parsed
from YAML, or a raw YAML string. It is deliberately tolerant of the
``experiment:`` wrapper key used by the canonical template in
``templates/experiment.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union

import yaml

from openxp.errors import ValidationError, codes
from openxp.storage.lifecycle import ALL_STATES

PathOrDict = Union[str, Path, dict, None]


@dataclass
class ValidationReport:
    """Outcome of a structured validation pass.

    Attributes
    ----------
    ok:
        ``True`` iff there are zero ``severity == "error"`` findings.
    findings:
        All error-severity findings collected during the pass.
    warnings:
        All warning-severity findings (non-fatal).
    """

    ok: bool = True
    findings: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    def add(self, err: ValidationError) -> None:
        """Append a finding and update ``ok`` based on its severity."""
        if err.severity == "warning":
            self.warnings.append(err)
        else:
            self.findings.append(err)
            self.ok = False

    def all_messages(self) -> list[str]:
        """Return every finding + warning rendered as a string."""
        return [str(e) for e in self.findings] + [str(w) for w in self.warnings]


# --- Helpers ------------------------------------------------------------

def _load(path_or_dict: PathOrDict) -> tuple[dict, ValidationError | None]:
    """Load YAML/dict/path into a plain dict.

    Returns (data, fatal_error). If ``fatal_error`` is not None, the caller
    should short-circuit and return a report containing only that error
    (there's nothing to validate).
    """
    if path_or_dict is None:
        return {}, ValidationError(
            code=codes.E_SCHEMA_INVALID,
            message="No experiment document was provided",
            hint="Pass a path, dict, or YAML string to validate_experiment_yaml.",
        )
    if isinstance(path_or_dict, dict):
        data = path_or_dict
    elif isinstance(path_or_dict, (str, Path)):
        as_path = Path(path_or_dict)
        try:
            path_exists = as_path.exists()
        except OSError:
            # Very long strings (raw YAML text) can blow up os.stat.
            path_exists = False
        if path_exists:
            try:
                text = as_path.read_text(encoding="utf-8")
            except OSError as e:
                return {}, ValidationError(
                    code=codes.E_SCHEMA_INVALID,
                    message=f"Could not read {as_path}: {e}",
                    hint="Check the path and file permissions.",
                )
            try:
                data = yaml.safe_load(text) or {}
            except yaml.YAMLError as e:
                return {}, ValidationError(
                    code=codes.E_SCHEMA_INVALID,
                    message=f"YAML parse error in {as_path}: {e}",
                    hint="Fix the YAML syntax and re-run validation.",
                )
        else:
            # Treat as raw YAML text.
            try:
                data = yaml.safe_load(str(path_or_dict)) or {}
            except yaml.YAMLError as e:
                return {}, ValidationError(
                    code=codes.E_SCHEMA_INVALID,
                    message=f"YAML parse error: {e}",
                    hint="Fix the YAML syntax and re-run validation.",
                )
    else:
        return {}, ValidationError(
            code=codes.E_BAD_TYPE,
            message=(
                f"validate_experiment_yaml expected path/dict/str, got "
                f"{type(path_or_dict).__name__}"
            ),
            hint="Pass a filesystem path, a dict, or a YAML string.",
        )

    if not isinstance(data, dict):
        return {}, ValidationError(
            code=codes.E_BAD_TYPE,
            message=f"Top-level document must be a mapping, got {type(data).__name__}",
            hint="Rewrite the YAML so the root is a key: value mapping.",
        )

    # Support templates/experiment.yaml wrapper: {experiment: {...}}.
    if "experiment" in data and isinstance(data["experiment"], dict) and "id" not in data:
        data = data["experiment"]
    return data, None


def _missing(report: ValidationReport, field_name: str) -> None:
    report.add(
        ValidationError(
            code=codes.E_MISSING_FIELD,
            message=codes.message_for(codes.E_MISSING_FIELD, field=field_name),
            hint=codes.hint_for(codes.E_MISSING_FIELD, field=field_name),
            details={"field": field_name},
        )
    )


def _bad_type(
    report: ValidationReport, field_name: str, expected: str, got: Any
) -> None:
    report.add(
        ValidationError(
            code=codes.E_BAD_TYPE,
            message=codes.message_for(
                codes.E_BAD_TYPE,
                field=field_name,
                expected=expected,
                got=type(got).__name__,
            ),
            hint=codes.hint_for(codes.E_BAD_TYPE, field=field_name, expected=expected),
            details={"field": field_name, "expected": expected, "got": type(got).__name__},
        )
    )


def _schema(report: ValidationReport, reason: str, **details: Any) -> None:
    report.add(
        ValidationError(
            code=codes.E_SCHEMA_INVALID,
            message=codes.message_for(codes.E_SCHEMA_INVALID, reason=reason),
            hint=codes.hint_for(codes.E_SCHEMA_INVALID),
            details=details,
        )
    )


def _is_empty(value: Any) -> bool:
    """True for None, empty string, empty list, empty dict."""
    if value is None:
        return True
    if isinstance(value, (str, list, dict, tuple, set)) and len(value) == 0:
        return True
    return False


# --- Metric extraction --------------------------------------------------

def _collect_metric_names(metrics: Any) -> list[str]:
    """Extract all metric names from whatever shape ``metrics`` takes.

    Accepts:
      * a list of strings
      * a list of dicts with a ``name`` key
      * a dict with ``primary``, ``secondary``, ``guardrail`` sub-keys
        (the template shape)
    """
    names: list[str] = []
    if isinstance(metrics, list):
        for m in metrics:
            if isinstance(m, str):
                if m:
                    names.append(m)
            elif isinstance(m, dict) and m.get("name"):
                names.append(str(m["name"]))
    elif isinstance(metrics, dict):
        primary = metrics.get("primary")
        if isinstance(primary, dict) and primary.get("name"):
            names.append(str(primary["name"]))
        elif isinstance(primary, str) and primary:
            names.append(primary)
        for key in ("secondary", "guardrail"):
            sub = metrics.get(key) or []
            if isinstance(sub, list):
                for m in sub:
                    if isinstance(m, str) and m:
                        names.append(m)
                    elif isinstance(m, dict) and m.get("name"):
                        names.append(str(m["name"]))
    return names


def _resolve_primary_metric_name(data: dict) -> str | None:
    """Find the primary metric name from either explicit or nested form."""
    # Explicit top-level primary_metric: "checkout_rate"
    explicit = data.get("primary_metric")
    if isinstance(explicit, str) and explicit:
        return explicit
    if isinstance(explicit, dict) and explicit.get("name"):
        return str(explicit["name"])
    # Nested: metrics.primary.name (template shape)
    metrics = data.get("metrics")
    if isinstance(metrics, dict):
        primary = metrics.get("primary")
        if isinstance(primary, dict) and primary.get("name"):
            return str(primary["name"])
        if isinstance(primary, str) and primary:
            return primary
    return None


def _resolve_variants(data: dict) -> list[dict]:
    """Return a normalized list of variant dicts.

    Accepts either ``variants: [...]`` (template shape) or
    ``treatment: {variants: [...], allocation: [...]}`` (spec shape).
    """
    if isinstance(data.get("variants"), list):
        return [v for v in data["variants"] if isinstance(v, dict)]
    treatment = data.get("treatment")
    if isinstance(treatment, dict):
        vs = treatment.get("variants")
        alloc = treatment.get("allocation")
        if isinstance(vs, list):
            out: list[dict] = []
            for i, v in enumerate(vs):
                if isinstance(v, dict):
                    out.append(v)
                else:
                    d: dict[str, Any] = {"name": str(v)}
                    if isinstance(alloc, list) and i < len(alloc):
                        d["allocation"] = alloc[i]
                    out.append(d)
            return out
    return []


def _resolve_power_block(data: dict) -> dict | None:
    power = data.get("power")
    return power if isinstance(power, dict) else None


# --- Public API ---------------------------------------------------------

def validate_experiment_yaml(path_or_dict: PathOrDict) -> ValidationReport:
    """Validate an experiment.yaml document.

    Collects ALL problems — never bails at the first finding. Returns a
    :class:`ValidationReport` with ``ok`` ``True`` iff there are zero
    error-severity findings.
    """
    report = ValidationReport()
    data, fatal = _load(path_or_dict)
    if fatal is not None:
        report.add(fatal)
        return report

    # ---- Required top-level fields ----------------------------------
    # Spec required: id, name, hypothesis, metrics, primary_metric,
    # success_criteria, power, treatment, lifecycle_state.
    # Template-friendly: also accept metrics.primary / variants / status.

    if _is_empty(data.get("id")):
        _missing(report, "id")
    elif not isinstance(data["id"], str):
        _bad_type(report, "id", "str", data["id"])

    if _is_empty(data.get("name")):
        _missing(report, "name")
    elif not isinstance(data["name"], str):
        _bad_type(report, "name", "str", data["name"])

    hypothesis = data.get("hypothesis")
    if hypothesis is None:
        _missing(report, "hypothesis")
    elif not isinstance(hypothesis, (dict, str)):
        _bad_type(report, "hypothesis", "dict or str", hypothesis)
    elif isinstance(hypothesis, dict) and _is_empty(hypothesis.get("action")):
        _missing(report, "hypothesis.action")

    metrics = data.get("metrics")
    if metrics is None:
        _missing(report, "metrics")
    elif not isinstance(metrics, (list, dict)):
        _bad_type(report, "metrics", "list or dict", metrics)

    metric_names = _collect_metric_names(metrics) if metrics is not None else []
    if metrics is not None and not metric_names:
        _schema(report, "metrics must contain at least one named metric")

    primary_metric = _resolve_primary_metric_name(data)
    if not primary_metric:
        _missing(report, "primary_metric")

    # success_criteria is required by the spec but the template doesn't
    # have a dedicated key — accept decision_rules as an alias.
    success_criteria = data.get("success_criteria") or data.get("decision_rules")
    if _is_empty(success_criteria):
        _missing(report, "success_criteria")
    elif not isinstance(success_criteria, (dict, str, list)):
        _bad_type(report, "success_criteria", "dict / str / list", success_criteria)

    # ---- Power block ------------------------------------------------
    power = _resolve_power_block(data)
    if power is None:
        _missing(report, "power")
    else:
        # baseline: accept baseline, baseline_rate, or baseline_std
        baseline = (
            power.get("baseline")
            if "baseline" in power
            else power.get("baseline_rate")
            if power.get("baseline_rate") is not None
            else power.get("baseline_std")
        )
        if baseline is None:
            _missing(report, "power.baseline")
        elif not isinstance(baseline, (int, float)):
            _bad_type(report, "power.baseline", "number", baseline)

        # mde may live on power OR on metrics.primary.mde
        mde = power.get("mde")
        if mde is None and isinstance(metrics, dict):
            primary = metrics.get("primary")
            if isinstance(primary, dict):
                mde = primary.get("mde")
        if mde is None:
            _missing(report, "power.mde")
        elif not isinstance(mde, (int, float)):
            _bad_type(report, "power.mde", "number", mde)
        else:
            if not (0 < float(mde) < 1):
                _schema(
                    report,
                    f"mde must be in (0, 1), got {mde}",
                    field="power.mde",
                    value=mde,
                )

        alpha = power.get("alpha")
        if alpha is None:
            _missing(report, "power.alpha")
        elif not isinstance(alpha, (int, float)):
            _bad_type(report, "power.alpha", "number", alpha)
        elif not (0 < float(alpha) < 0.5):
            _schema(
                report,
                f"alpha must be in (0, 0.5), got {alpha}",
                field="power.alpha",
                value=alpha,
            )

        pwr = power.get("power")
        if pwr is None:
            _missing(report, "power.power")
        elif not isinstance(pwr, (int, float)):
            _bad_type(report, "power.power", "number", pwr)
        elif not (0.5 < float(pwr) < 1.0):
            _schema(
                report,
                f"power must be in (0.5, 1.0), got {pwr}",
                field="power.power",
                value=pwr,
            )

        duration = power.get("duration")
        if duration is None:
            duration = power.get("duration_days")
        if duration is None:
            _missing(report, "power.duration")
        elif not isinstance(duration, (int, float)):
            _bad_type(report, "power.duration", "number", duration)

    # ---- Treatment / variants --------------------------------------
    variants = _resolve_variants(data)
    has_treatment_or_variants = (
        "treatment" in data or "variants" in data
    )
    if not has_treatment_or_variants:
        _missing(report, "treatment")
    elif not variants:
        _schema(report, "treatment.variants must be a non-empty list")
    else:
        if len(variants) < 2:
            _schema(
                report,
                f"at least 2 variants required, got {len(variants)}",
                field="variants",
                count=len(variants),
            )
        total_alloc = 0.0
        any_alloc_seen = False
        for i, v in enumerate(variants):
            name = v.get("name")
            if _is_empty(name):
                _missing(report, f"variants[{i}].name")
            alloc = v.get("allocation")
            if alloc is None:
                continue
            any_alloc_seen = True
            if not isinstance(alloc, (int, float)):
                _bad_type(report, f"variants[{i}].allocation", "number", alloc)
            else:
                total_alloc += float(alloc)
        if any_alloc_seen and abs(total_alloc - 1.0) > 0.001:
            _schema(
                report,
                f"variant allocations must sum to 1.0 (±0.001), got {total_alloc}",
                field="variants.allocation",
                total=total_alloc,
            )

    # ---- Cross-field: primary metric must be in metrics list --------
    if primary_metric and metric_names and primary_metric not in metric_names:
        _schema(
            report,
            (
                f"primary_metric '{primary_metric}' is not listed in "
                f"metrics ({metric_names})"
            ),
            field="primary_metric",
            value=primary_metric,
            metrics=metric_names,
        )

    # ---- Lifecycle state -------------------------------------------
    lifecycle = data.get("lifecycle_state")
    if lifecycle is None:
        lifecycle = data.get("status")
    if lifecycle is None:
        _missing(report, "lifecycle_state")
    elif not isinstance(lifecycle, str):
        _bad_type(report, "lifecycle_state", "str", lifecycle)
    elif lifecycle not in ALL_STATES:
        report.add(
            ValidationError(
                code=codes.E_LIFECYCLE_SKIP,
                message=(
                    f"Invalid lifecycle_state '{lifecycle}'. "
                    f"Valid states: {sorted(ALL_STATES)}"
                ),
                hint=(
                    "Use one of the canonical states from "
                    "openxp.storage.lifecycle.ALL_STATES."
                ),
                details={"field": "lifecycle_state", "value": lifecycle},
            )
        )

    return report
