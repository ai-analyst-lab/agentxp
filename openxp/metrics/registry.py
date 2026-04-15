"""
Metric registry for OpenXP.

The MetricRegistry loads YAML metric definitions from a directory and exposes
them by name so that experiments can reference metrics without restating the
math each time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from openxp.metrics.schema import MetricDefinition, MetricValidationError, validate


def _default_metrics_dir() -> Optional[Path]:
    """Return the first metrics directory that exists: ./metrics then ~/.openxp/metrics."""
    cwd_metrics = Path.cwd() / "metrics"
    if cwd_metrics.is_dir():
        return cwd_metrics
    home_metrics = Path.home() / ".openxp" / "metrics"
    if home_metrics.is_dir():
        return home_metrics
    return None


class MetricRegistry:
    """In-memory registry of metric definitions keyed by name."""

    def __init__(self, metrics_dir: Path | None = None, autoload: bool = True) -> None:
        self._metrics: dict[str, MetricDefinition] = {}
        self.metrics_dir: Optional[Path] = (
            Path(metrics_dir) if metrics_dir is not None else _default_metrics_dir()
        )
        if autoload and self.metrics_dir and self.metrics_dir.is_dir():
            self.load_from_directory(self.metrics_dir)

    def register(self, md: MetricDefinition) -> None:
        """Add or replace a metric definition in the registry."""
        if not isinstance(md, MetricDefinition):
            raise TypeError(f"expected MetricDefinition, got {type(md).__name__}")
        self._metrics[md.name] = md

    def get(self, name: str) -> MetricDefinition:
        """Retrieve a metric by name. Raises KeyError if missing."""
        if name not in self._metrics:
            raise KeyError(f"metric '{name}' not found in registry")
        return self._metrics[name]

    def list(self) -> list[str]:  # noqa: A003 - intentional public API name
        """Return all registered metric names, sorted."""
        return sorted(self._metrics.keys())

    def __contains__(self, name: object) -> bool:
        return name in self._metrics

    def __len__(self) -> int:
        return len(self._metrics)

    def load_from_file(self, path: Path) -> MetricDefinition:
        """Load a single metric YAML file into the registry and return it."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"metric file not found: {path}")
        with path.open("r") as f:
            raw = yaml.safe_load(f)
        if raw is None:
            raise MetricValidationError(f"metric file is empty: {path}")
        md = validate(raw)
        self.register(md)
        return md

    def load_from_directory(self, dir_path: Path) -> list[MetricDefinition]:
        """Scan *.yaml files in dir_path and register each as a metric."""
        dir_path = Path(dir_path)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"not a directory: {dir_path}")
        loaded: list[MetricDefinition] = []
        for yaml_path in sorted(dir_path.glob("*.yaml")):
            loaded.append(self.load_from_file(yaml_path))
        return loaded


def load_metric(path: Path) -> MetricDefinition:
    """Load and validate a single metric YAML file without touching a registry."""
    path = Path(path)
    with path.open("r") as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raise MetricValidationError(f"metric file is empty: {path}")
    return validate(raw)


def load_all_metrics(dir_path: Path | None = None) -> MetricRegistry:
    """Build a MetricRegistry loaded from dir_path (or the default location)."""
    return MetricRegistry(metrics_dir=dir_path, autoload=True)
