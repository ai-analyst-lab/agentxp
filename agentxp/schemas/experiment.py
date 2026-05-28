"""
Experiment configuration schema — the experiment.yaml contract.

Defines the structure for pre-registering experiments: hypothesis, metrics,
variants, power calculations, decision rules, and results tracking.
"""

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ExperimentStatus(str, Enum):
    """Experiment lifecycle states.

    Canonical 11-state superset matching `agentxp.storage.lifecycle.ALL_STATES`.
    The state machine (forward/backward transitions, retreats-require-amendment)
    is enforced by the storage layer — this enum is only the Pydantic-validated
    surface used when loading/serializing `experiment.yaml`.
    """
    DESIGNING = "DESIGNING"
    POWERED = "POWERED"
    COLLECTING = "COLLECTING"
    ANALYZING = "ANALYZING"
    INTERPRETED = "INTERPRETED"
    REPORTED = "REPORTED"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"
    INVALID = "INVALID"
    BLOCKED = "BLOCKED"


class Viability(str, Enum):
    VIABLE = "VIABLE"
    MARGINAL = "MARGINAL"
    NOT_VIABLE = "NOT_VIABLE"


class MetricType(str, Enum):
    PROPORTION = "proportion"
    CONTINUOUS = "continuous"
    RATIO = "ratio"


class GuardrailDirection(str, Enum):
    DO_NOT_INCREASE = "do_not_increase"
    DO_NOT_DECREASE = "do_not_decrease"


class EwlClassification(str, Enum):
    SHIP = "SHIP"
    INVESTIGATE = "INVESTIGATE"
    ABORT = "ABORT"
    LEARN = "LEARN"
    INVALID = "INVALID"


class Hypothesis(BaseModel):
    action: str = Field(default="", description="What change are we making?")
    metric: str = Field(default="", description="Primary metric we expect to move")
    direction: str = Field(default="", description="'increase' or 'decrease'")
    magnitude: str = Field(default="", description="Expected effect size (e.g., '5% relative lift')")
    mechanism: str = Field(default="", description="Why we believe this will work")


class PrimaryMetric(BaseModel):
    name: str = ""
    type: MetricType = MetricType.PROPORTION
    definition: str = Field(default="", description="Precise definition (numerator / denominator / time window)")
    mde: Optional[float] = Field(default=None, description="Minimum detectable effect (relative)")
    baseline: Optional[float] = Field(default=None, description="Current baseline value")
    sql: str = Field(default="", description="Optional SQL to compute this metric")


class SecondaryMetric(BaseModel):
    name: str = ""
    type: MetricType = MetricType.PROPORTION
    definition: str = ""


class GuardrailMetric(BaseModel):
    name: str = ""
    type: MetricType = MetricType.CONTINUOUS
    threshold: Optional[float] = Field(default=None, description="Absolute threshold not to exceed")
    direction: GuardrailDirection = GuardrailDirection.DO_NOT_INCREASE
    definition: str = ""
    nim: Optional[float] = Field(
        default=None,
        description="Non-Inferiority Margin. If not set, uses simple inferiority test.",
    )


class Metrics(BaseModel):
    primary: PrimaryMetric = PrimaryMetric()
    secondary: list[SecondaryMetric] = Field(default_factory=list)
    guardrail: list[GuardrailMetric] = Field(default_factory=list)


class Variant(BaseModel):
    name: str = ""
    allocation: float = 0.50
    is_control: bool = False


class PowerConfig(BaseModel):
    alpha: float = 0.05
    power: float = 0.80
    test_type: str = "two-sided"
    baseline_rate: Optional[float] = None
    baseline_std: Optional[float] = None
    sample_size_per_group: Optional[int] = None
    total_sample_size: Optional[int] = None
    duration_days: Optional[int] = None
    viable: Optional[Viability] = None


class DecisionRules(BaseModel):
    ship_if: str = "Primary metric significant positive, no guardrail violations"
    do_not_ship_if: str = "Any guardrail violation OR negative primary metric"
    inconclusive_if: str = "Underpowered null — extend or increase allocation"
    mixed_results: str = "Primary up but guardrail degraded — quantify trade-off"
    emergency_stop: str = "Guardrail degrades by >15% relative — halt immediately"


class DataConfig(BaseModel):
    assignment_table: str = Field(default="", description="Table/file containing variant assignments")
    outcome_table: str = Field(default="", description="Table/file containing outcome metrics")
    date_column: str = ""
    unit_column: str = ""


class Timeline(BaseModel):
    created: Optional[date] = None
    powered: Optional[date] = None
    started: Optional[date] = None
    analyzed: Optional[date] = None
    decided: Optional[date] = None


class Results(BaseModel):
    srm_verdict: Optional[str] = None
    primary_significant: Optional[bool] = None
    primary_lift: Optional[float] = None
    primary_p_value: Optional[float] = None
    guardrail_violations: list[str] = Field(default_factory=list)
    ewl_classification: Optional[EwlClassification] = None
    analysis_file: str = ""


class ExperimentConfig(BaseModel):
    """Top-level experiment configuration.

    Represents the experiment.yaml lifecycle document.
    """
    id: str = Field(default="", description="kebab-case slug (e.g., checkout-redesign-2026q1)")
    name: str = Field(default="", description="Human-readable experiment name")
    status: ExperimentStatus = ExperimentStatus.DESIGNING

    hypothesis: Hypothesis = Hypothesis()
    metrics: Metrics = Metrics()
    variants: list[Variant] = Field(
        default_factory=lambda: [
            Variant(name="control", allocation=0.50, is_control=True),
            Variant(name="treatment", allocation=0.50, is_control=False),
        ]
    )
    power: PowerConfig = PowerConfig()
    decision_rules: DecisionRules = DecisionRules()
    data: DataConfig = DataConfig()
    timeline: Timeline = Timeline()
    results: Results = Results()
