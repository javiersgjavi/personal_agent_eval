"""Canonical evaluation profile schema and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError, model_validator

from personal_agent_eval.config._base import (
    ID_PATTERN,
    ConfigError,
    ConfigModel,
    load_yaml_mapping,
)


class JudgeConfig(ConfigModel):
    """A judge definition."""

    model_config = ConfigDict(extra="allow", frozen=True)

    judge_id: str = Field(pattern=ID_PATTERN)
    type: str


class JudgeRunConfig(ConfigModel):
    """A concrete judge execution plan."""

    judge_run_id: str = Field(pattern=ID_PATTERN)
    judge_id: str = Field(pattern=ID_PATTERN)
    repetitions: int = Field(default=1, ge=1)
    sample_size: int | None = Field(default=None, ge=1)


class JudgeAggregationConfig(ConfigModel):
    """Aggregation policy for repeated judge outputs."""

    method: Literal["median", "mean", "majority_vote", "all_pass"] = "median"
    pass_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class FinalDimensionAggregationConfig(ConfigModel):
    """Per-dimension hybrid aggregation policy."""

    policy: Literal["judge_only", "deterministic_only", "weighted"] = "judge_only"
    judge_weight: float | None = Field(default=None, gt=0)
    deterministic_weight: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _validate_weighted_policy(self) -> FinalDimensionAggregationConfig:
        if self.policy == "weighted":
            if self.judge_weight is None or self.deterministic_weight is None:
                raise ValueError(
                    "Weighted final aggregation requires both 'judge_weight' and "
                    "'deterministic_weight'."
                )
        return self


class FinalAggregationDimensions(ConfigModel):
    """Dimension-level aggregation policy overrides."""

    task: FinalDimensionAggregationConfig = Field(default_factory=FinalDimensionAggregationConfig)
    process: FinalDimensionAggregationConfig = Field(
        default_factory=FinalDimensionAggregationConfig
    )
    autonomy: FinalDimensionAggregationConfig = Field(
        default_factory=FinalDimensionAggregationConfig
    )
    closeness: FinalDimensionAggregationConfig = Field(
        default_factory=FinalDimensionAggregationConfig
    )
    efficiency: FinalDimensionAggregationConfig = Field(
        default_factory=FinalDimensionAggregationConfig
    )
    spark: FinalDimensionAggregationConfig = Field(default_factory=FinalDimensionAggregationConfig)


class FinalScoreWeights(ConfigModel):
    """Weights used to compute the final score from final dimensions."""

    task: float = Field(default=1.0, ge=0)
    process: float = Field(default=1.0, ge=0)
    autonomy: float = Field(default=1.0, ge=0)
    closeness: float = Field(default=1.0, ge=0)
    efficiency: float = Field(default=1.0, ge=0)
    spark: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def _validate_non_zero_sum(self) -> FinalScoreWeights:
        if (
            self.task
            + self.process
            + self.autonomy
            + self.closeness
            + self.efficiency
            + self.spark
            <= 0
        ):
            raise ValueError("At least one final_score_weight must be greater than zero.")
        return self


class FinalAggregationConfig(ConfigModel):
    """Config-driven policy for hybrid final aggregation."""

    default_policy: Literal["judge_only"] = "judge_only"
    dimensions: FinalAggregationDimensions = Field(default_factory=FinalAggregationDimensions)
    final_score_weights: FinalScoreWeights = Field(default_factory=FinalScoreWeights)


class Anchor(ConfigModel):
    """An anchor example that can be referenced by judges."""

    anchor_id: str = Field(pattern=ID_PATTERN)
    label: str
    text: str


class AnchorsConfig(ConfigModel):
    """Anchor configuration."""

    enabled: bool = False
    references: list[Anchor] = Field(default_factory=list)


class SecurityPolicy(ConfigModel):
    """Security policy for evaluation execution."""

    allow_local_python_hooks: bool = False
    network_access: Literal["deny", "allow"] = "deny"
    redact_secrets: bool = True


class EvaluationProfileConfig(ConfigModel):
    """Canonical evaluation profile config."""

    schema_version: Literal[1]
    evaluation_profile_id: str = Field(pattern=ID_PATTERN)
    title: str
    judges: list[JudgeConfig] = Field(default_factory=list)
    judge_runs: list[JudgeRunConfig] = Field(default_factory=list)
    aggregation: JudgeAggregationConfig = Field(default_factory=JudgeAggregationConfig)
    final_aggregation: FinalAggregationConfig = Field(default_factory=FinalAggregationConfig)
    anchors: AnchorsConfig = Field(default_factory=AnchorsConfig)
    security_policy: SecurityPolicy = Field(default_factory=SecurityPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_evaluation_profile(path: str | Path) -> EvaluationProfileConfig:
    """Load and validate a canonical evaluation profile."""
    payload, resolved_path = load_yaml_mapping(path)

    try:
        config = EvaluationProfileConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid evaluation profile '{resolved_path}': {exc}") from exc

    return config.with_source_path(resolved_path)
