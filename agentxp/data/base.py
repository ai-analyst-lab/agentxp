"""
Shared dataclasses for the AgentXP data layer.

These are deliberately framework-light (standard dataclasses, not Pydantic) to
match the style of ``agentxp.stats`` where functions return plain dicts and
results objects are simple data containers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SchemaDiscovery:
    """Result of auto-detecting experiment schema from a DataFrame.

    Every field is discovered — no column name is ever hardcoded. Callers
    should inspect ``needs_disambiguation`` and prompt the user when the
    detector is not confident.
    """

    treatment_column: str | None = None
    control_value: Any | None = None
    treatment_values: list[Any] = field(default_factory=list)
    metric_columns: list[str] = field(default_factory=list)
    segment_columns: list[str] = field(default_factory=list)
    timestamp_columns: list[str] = field(default_factory=list)
    unit_columns: list[str] = field(default_factory=list)

    # Confidence / quality flags
    confidence: dict[str, str] = field(default_factory=dict)
    needs_disambiguation: list[str] = field(default_factory=list)
    n_rows: int = 0
    n_columns: int = 0
    interpretation: str = ""

    def to_dict(self) -> dict:
        return {
            "treatment_column": self.treatment_column,
            "control_value": self.control_value,
            "treatment_values": self.treatment_values,
            "metric_columns": self.metric_columns,
            "segment_columns": self.segment_columns,
            "timestamp_columns": self.timestamp_columns,
            "unit_columns": self.unit_columns,
            "confidence": self.confidence,
            "needs_disambiguation": self.needs_disambiguation,
            "n_rows": self.n_rows,
            "n_columns": self.n_columns,
            "interpretation": self.interpretation,
        }


@dataclass
class DataSource:
    """Descriptor for where experiment data came from.

    Used for audit logging and to let downstream agents distinguish CSV
    flat-file loads from warehouse queries.
    """

    kind: str  # 'csv' | 'duckdb' | 'dataframe'
    location: str | None = None  # path, db_path, or "<in-memory>"
    query: str | None = None  # SQL if applicable
    table: str | None = None


@dataclass
class LoadResult:
    """Result of loading data from a source.

    Wraps a pandas DataFrame plus metadata so downstream code never has to
    re-inspect the source to know how many rows it has or where it came from.
    """

    dataframe: Any  # pandas.DataFrame (avoid hard import for dataclass default)
    source: DataSource
    n_rows: int
    n_columns: int
    warnings: list[str] = field(default_factory=list)
    interpretation: str = ""

    def to_dict(self) -> dict:
        return {
            "source": {
                "kind": self.source.kind,
                "location": self.source.location,
                "query": self.source.query,
                "table": self.source.table,
            },
            "n_rows": self.n_rows,
            "n_columns": self.n_columns,
            "warnings": self.warnings,
            "interpretation": self.interpretation,
        }
