"""Judge orchestration result models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from personal_agent_eval.artifacts.run_artifact import ArtifactModel


class JudgeIterationStatus(StrEnum):
    """Terminal status for one logical judge iteration."""

    SUCCESS = "success"
    FAILED = "failed"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"
    TIMED_OUT = "timed_out"


class JudgeDimensions(ArtifactModel):
    """Base judge dimension scores."""

    task: float
    process: float
    autonomy: float
    closeness: float
    efficiency: float
    spark: float


class JudgeEvidence(ArtifactModel):
    """Dimension-scoped judge evidence snippets."""

    task: list[str] = Field(default_factory=list)
    process: list[str] = Field(default_factory=list)
    autonomy: list[str] = Field(default_factory=list)
    closeness: list[str] = Field(default_factory=list)
    efficiency: list[str] = Field(default_factory=list)
    spark: list[str] = Field(default_factory=list)


class RawJudgeRunResult(ArtifactModel):
    """Raw provider-facing result for one judge attempt."""

    schema_version: Literal[1] = 1
    raw_result_ref: str
    judge_name: str
    judge_model: str
    repetition_index: int = Field(ge=0)
    attempt_index: int = Field(ge=0)
    status: JudgeIterationStatus
    request_messages: list[dict[str, Any]] = Field(default_factory=list)
    response_content: str | None = None
    parsed_response: dict[str, Any] | None = None
    provider_name: str | None = None
    provider_model_id: str | None = None
    request_id: str | None = None
    response_id: str | None = None
    finish_reason: str | None = None
    native_finish_reason: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)


class NormalizedJudgeIterationResult(ArtifactModel):
    """Normalized result for one logical judge repetition."""

    judge_name: str
    judge_model: str
    repetition_index: int = Field(ge=0)
    status: JudgeIterationStatus
    dimensions: JudgeDimensions | None = None
    summary: str | None = None
    evidence: JudgeEvidence | None = None
    warnings: list[str] = Field(default_factory=list)
    raw_result_ref: str | None = None

    @model_validator(mode="after")
    def _validate_success_payload(self) -> NormalizedJudgeIterationResult:
        if self.status is JudgeIterationStatus.SUCCESS:
            if self.dimensions is None or self.evidence is None or self.summary is None:
                raise ValueError(
                    "Successful judge iterations require dimensions, summary, and evidence."
                )
            if self.raw_result_ref is None:
                raise ValueError("Successful judge iterations require a raw_result_ref.")
        return self


class AggregatedJudgeResult(ArtifactModel):
    """Aggregated judge result for one judge across multiple repetitions."""

    schema_version: Literal[1] = 1
    judge_name: str
    judge_model: str
    aggregation_method: Literal["median"] = "median"
    configured_repetitions: int = Field(ge=1)
    successful_iterations: int = Field(ge=0)
    failed_iterations: int = Field(ge=0)
    used_repetition_indices: list[int] = Field(default_factory=list)
    excluded_repetition_indices: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    dimensions: JudgeDimensions | None = None
    summary: str | None = None
    evidence: JudgeEvidence | None = None
    iteration_results: list[NormalizedJudgeIterationResult] = Field(default_factory=list)
    raw_results: list[RawJudgeRunResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_counts(self) -> AggregatedJudgeResult:
        if self.successful_iterations + self.failed_iterations != self.configured_repetitions:
            raise ValueError("Iteration counts must sum to configured_repetitions.")
        if len(self.iteration_results) != self.configured_repetitions:
            raise ValueError("One normalized iteration result is required per repetition.")
        return self


class JudgeOutputContract(ArtifactModel):
    """Strict JSON contract expected from the judge model."""

    dimensions: JudgeDimensions
    summary: str = Field(min_length=1)
    evidence: JudgeEvidence
