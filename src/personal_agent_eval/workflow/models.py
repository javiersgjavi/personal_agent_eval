"""Typed workflow outputs for CLI orchestration."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from personal_agent_eval.aggregation.models import DimensionScores
from personal_agent_eval.artifacts.run_artifact import ArtifactModel


class UsageSummary(ArtifactModel):
    """Aggregated usage and cost metrics for one workflow result row."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)


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


class OpenClawWorkflowEvidenceSummary(ArtifactModel):
    """OpenClaw evidence locations relative to the workflow workspace root."""

    agent_id: str = Field(min_length=1)
    container_image: str | None = None
    evidence_paths: dict[str, str] = Field(
        default_factory=dict,
        description="Maps stable artifact_type (or key_output key) to workspace-relative paths.",
    )


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
    run_latency_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Wall-clock duration of the subject-model run in seconds.",
    )
    run_usage: UsageSummary = Field(
        default_factory=UsageSummary,
        description="Usage/cost for subject-model runs only.",
    )
    evaluation_usage: UsageSummary = Field(
        default_factory=UsageSummary,
        description="Usage/cost for judge/evaluation calls only.",
    )
    usage: UsageSummary = Field(default_factory=UsageSummary)
    warnings: list[str] = Field(default_factory=list)
    runner_type: str | None = Field(
        default=None,
        min_length=1,
        description="Subject run runner when a run artifact is available for this row.",
    )
    stored_run_artifact_path: str | None = Field(
        default=None,
        min_length=1,
        description="Path to run_N.json relative to the workspace root.",
    )
    stored_run_fingerprint_input_path: str | None = Field(
        default=None,
        min_length=1,
        description="Path to run_N.fingerprint_input.json relative to the workspace root.",
    )
    stored_run_artifacts_dir: str | None = Field(
        default=None,
        min_length=1,
        description="Path to run_N.artifacts/ relative to the workspace root.",
    )
    openclaw_evidence: OpenClawWorkflowEvidenceSummary | None = None


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
    run_cost_usd: float = Field(
        default=0.0,
        ge=0,
        description="Sum of run costs across result rows.",
    )
    evaluation_cost_usd: float = Field(
        default=0.0,
        ge=0,
        description="Sum of judge/evaluation costs across result rows.",
    )
    total_cost_usd: float = Field(
        default=0.0,
        ge=0,
        description="Total cost (runs + evaluation) for this workflow invocation.",
    )


class WorkflowResult(ArtifactModel):
    """Structured output returned by CLI orchestration."""

    command: str
    workspace_root: str
    suite_id: str
    run_profile_id: str
    evaluation_profile_id: str | None = None
    results: list[WorkflowCaseResult] = Field(default_factory=list)
    summary: WorkflowSummary
