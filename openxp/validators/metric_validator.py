"""Structured validator for metric YAML definitions.

Thin wrapper around :func:`openxp.metrics.schema.validate`. Catches the
underlying :class:`MetricValidationError` and re-shapes it into a
:class:`ValidationReport` containing a single ``E_SCHEMA_INVALID``
finding, so callers get the same interface as the experiment validator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml

from openxp.errors import ValidationError, codes
from openxp.metrics.schema import MetricValidationError, validate
from openxp.validators.experiment_validator import ValidationReport

PathOrDict = Union[str, Path, dict, None]


def _load(path_or_dict: PathOrDict) -> tuple[dict, ValidationError | None]:
    if path_or_dict is None:
        return {}, ValidationError(
            code=codes.E_SCHEMA_INVALID,
            message="No metric document was provided",
            hint="Pass a path, dict, or YAML string to validate_metric_yaml.",
        )
    if isinstance(path_or_dict, dict):
        return path_or_dict, None
    if isinstance(path_or_dict, (str, Path)):
        as_path = Path(path_or_dict)
        try:
            try:
                path_exists = as_path.exists()
            except OSError:
                path_exists = False
            if path_exists:
                text = as_path.read_text(encoding="utf-8")
            else:
                text = str(path_or_dict)
            data = yaml.safe_load(text) or {}
        except (OSError, yaml.YAMLError) as e:
            return {}, ValidationError(
                code=codes.E_SCHEMA_INVALID,
                message=f"Could not parse metric YAML: {e}",
                hint="Fix the YAML syntax / path and re-run.",
            )
        if not isinstance(data, dict):
            return {}, ValidationError(
                code=codes.E_BAD_TYPE,
                message=f"Metric document must be a mapping, got {type(data).__name__}",
                hint="Rewrite the YAML so the root is a key: value mapping.",
            )
        return data, None
    return {}, ValidationError(
        code=codes.E_BAD_TYPE,
        message=(
            f"validate_metric_yaml expected path/dict/str, got "
            f"{type(path_or_dict).__name__}"
        ),
        hint="Pass a filesystem path, a dict, or a YAML string.",
    )


def validate_metric_yaml(path_or_dict: PathOrDict) -> ValidationReport:
    """Validate a metric definition YAML document.

    Returns a :class:`ValidationReport`. Unlike the experiment validator,
    the underlying metric schema stops at the first failure — so the
    report will contain at most one finding per call.
    """
    report = ValidationReport()
    data, fatal = _load(path_or_dict)
    if fatal is not None:
        report.add(fatal)
        return report

    try:
        validate(data)
    except MetricValidationError as e:
        report.add(
            ValidationError(
                code=codes.E_SCHEMA_INVALID,
                message=codes.message_for(codes.E_SCHEMA_INVALID, reason=str(e)),
                hint=codes.hint_for(codes.E_SCHEMA_INVALID),
                details={"underlying": str(e)},
            )
        )
    return report
