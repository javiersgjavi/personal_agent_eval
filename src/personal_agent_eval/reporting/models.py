"""Structured reporting models built on top of workflow outputs."""

from __future__ import annotations

from pydantic import Field

from personal_agent_eval.aggregation.models import DimensionScores
from personal_agent_eval.artifacts.run_artifact import ArtifactModel


class ModelSummary(ArtifactModel):
    """Per-model reporting summary derived from workflow case results."""

    model_id: str = Field(min_length=1)
    case_count: int = Field(ge=0)
    run_executed: int = Field(ge=0)
    run_reused: int = Field(ge=0)
    run_skipped: int = Field(ge=0)
    evaluation_executed: int = Field(ge=0)
    evaluation_reused: int = Field(ge=0)
    evaluation_skipped: int = Field(ge=0)
    scored_case_count: int = Field(ge=0)
    average_final_score: float | None = Field(default=None, ge=0, le=10)
    average_dimensions: DimensionScores = Field(default_factory=DimensionScores)
    warning_count: int = Field(ge=0)


class StructuredReport(ArtifactModel):
    """JSON-serializable report output for workflow results."""

    suite_id: str = Field(min_length=1)
    run_profile_id: str | None = Field(default=None, min_length=1)
    evaluation_profile_id: str | None = Field(default=None, min_length=1)
    case_results: list[dict[str, object]] = Field(default_factory=list)
    model_summaries: list[ModelSummary] = Field(default_factory=list)
