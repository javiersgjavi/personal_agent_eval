"""Typed evaluation aggregation models."""

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


class SecurityBlock(ArtifactModel):
    """Security status preserved on the final evaluation result."""

    verdict: Literal["not_evaluated", "passed", "needs_review", "critical_fail"] = "not_evaluated"
    warnings: list[str] = Field(default_factory=list)


class HybridAggregationSummary(ArtifactModel):
    """Execution-level summary of judge and deterministic inputs."""

    deterministic_passed_checks: int = Field(ge=0)
    deterministic_failed_checks: int = Field(ge=0)
    deterministic_error_checks: int = Field(ge=0)
    judge_successful_iterations: int = Field(ge=0)
    judge_failed_iterations: int = Field(ge=0)


class OverallAssessment(ArtifactModel):
    """Overall evaluation score and brief supporting evidence."""

    score: float = Field(ge=0, le=10)
    evidence: list[str] = Field(default_factory=list)


class FinalEvaluationResult(ArtifactModel):
    """Final evaluation artifact for one run/case pair."""

    schema_version: Literal[1] = 1
    case_id: str
    run_id: str
    deterministic_dimensions: DimensionScores = Field(default_factory=DimensionScores)
    judge_dimensions: DimensionScores = Field(default_factory=DimensionScores)
    final_dimensions: DimensionScores = Field(default_factory=DimensionScores)
    judge_overall: OverallAssessment | None = None
    final_score: float = Field(ge=0, le=10)
    summary: HybridAggregationSummary
    security: SecurityBlock = Field(default_factory=SecurityBlock)
    warnings: list[str] = Field(default_factory=list)
