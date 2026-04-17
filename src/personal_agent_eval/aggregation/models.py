"""Typed hybrid aggregation models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from personal_agent_eval.artifacts.run_artifact import ArtifactModel


class DimensionScores(ArtifactModel):
    """Dimension score payload on the shared 0-10 scale."""

    task: float | None = Field(default=None, ge=0, le=10)
    process: float | None = Field(default=None, ge=0, le=10)
    autonomy: float | None = Field(default=None, ge=0, le=10)
    closeness: float | None = Field(default=None, ge=0, le=10)
    efficiency: float | None = Field(default=None, ge=0, le=10)
    spark: float | None = Field(default=None, ge=0, le=10)


class DimensionResolution(ArtifactModel):
    """How one final dimension score was resolved."""

    policy: Literal["judge_only", "deterministic_only", "weighted"]
    source_used: Literal["judge", "deterministic", "weighted", "missing"]
    judge_score: float | None = Field(default=None, ge=0, le=10)
    deterministic_score: float | None = Field(default=None, ge=0, le=10)
    final_score: float | None = Field(default=None, ge=0, le=10)


class DimensionResolutions(ArtifactModel):
    """Resolution metadata for every tracked dimension."""

    task: DimensionResolution
    process: DimensionResolution
    autonomy: DimensionResolution
    closeness: DimensionResolution
    efficiency: DimensionResolution
    spark: DimensionResolution


class SecurityBlock(ArtifactModel):
    """Security status preserved on the final evaluation result."""

    verdict: Literal["not_evaluated", "passed", "needs_review", "critical_fail"] = "not_evaluated"
    warnings: list[str] = Field(default_factory=list)


class HybridAggregationSummary(ArtifactModel):
    """Execution-level summary of hybrid aggregation inputs."""

    deterministic_passed_checks: int = Field(ge=0)
    deterministic_failed_checks: int = Field(ge=0)
    deterministic_error_checks: int = Field(ge=0)
    judge_successful_iterations: int = Field(ge=0)
    judge_failed_iterations: int = Field(ge=0)


class FinalEvaluationResult(ArtifactModel):
    """Final hybrid evaluation artifact for one run/case pair."""

    schema_version: Literal[1] = 1
    case_id: str
    run_id: str
    deterministic_dimensions: DimensionScores = Field(default_factory=DimensionScores)
    judge_dimensions: DimensionScores = Field(default_factory=DimensionScores)
    final_dimensions: DimensionScores = Field(default_factory=DimensionScores)
    dimension_resolutions: DimensionResolutions
    final_score: float = Field(ge=0, le=10)
    summary: HybridAggregationSummary
    security: SecurityBlock = Field(default_factory=SecurityBlock)
    warnings: list[str] = Field(default_factory=list)
