"""Typed workflow outputs for CLI orchestration."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from personal_agent_eval.aggregation.models import DimensionScores
from personal_agent_eval.artifacts.run_artifact import ArtifactModel


class RunAction(StrEnum):
    """How one run artifact was produced for a model/case pair."""

    EXECUTED = "executed"
    REUSED = "reused"
    SKIPPED = "skipped"


class EvaluationAction(StrEnum):
    """How one evaluation artifact set was produced for a model/case pair."""

    EXECUTED = "executed"
    REUSED = "reused"
    FINAL_RECOMPUTED = "final_recomputed"
    SKIPPED = "skipped"


class WorkflowCaseResult(ArtifactModel):
    """One workflow result row scoped to one model/case pair."""

    model_id: str
    case_id: str
    run_fingerprint: str
    evaluation_fingerprint: str | None = None
    run_action: RunAction
    evaluation_action: EvaluationAction = EvaluationAction.SKIPPED
    run_status: str
    evaluation_status: str | None = None
    final_score: float | None = Field(default=None, ge=0, le=10)
    final_dimensions: DimensionScores | None = None
    warnings: list[str] = Field(default_factory=list)


class WorkflowSummary(ArtifactModel):
    """Execution summary suitable for later reporting."""

    models_requested: int = Field(ge=0)
    cases_requested: int = Field(ge=0)
    model_case_pairs: int = Field(ge=0)
    runs_executed: int = Field(ge=0)
    runs_reused: int = Field(ge=0)
    evaluations_executed: int = Field(ge=0)
    evaluations_reused: int = Field(ge=0)
    final_results_recomputed: int = Field(ge=0)


class WorkflowResult(ArtifactModel):
    """Structured output returned by CLI orchestration."""

    command: str
    workspace_root: str
    suite_id: str
    run_profile_id: str
    evaluation_profile_id: str | None = None
    results: list[WorkflowCaseResult] = Field(default_factory=list)
    summary: WorkflowSummary
