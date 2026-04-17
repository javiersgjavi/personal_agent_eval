"""Canonical run artifact schema for V1."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent_eval.config._base import ID_PATTERN

RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"


class ArtifactModel(BaseModel):
    """Base class for canonical artifact objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable mapping."""
        return self.model_dump(mode="json")


class RunStatus(StrEnum):
    """Supported terminal run states for V1."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INVALID = "invalid"
    PROVIDER_ERROR = "provider_error"


class RunArtifactIdentity(ArtifactModel):
    """Canonical identity fields for a run artifact."""

    schema_version: Literal[1]
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    case_id: str = Field(pattern=ID_PATTERN)
    suite_id: str = Field(pattern=ID_PATTERN)
    run_profile_id: str = Field(pattern=ID_PATTERN)
    runner_type: str = Field(pattern=ID_PATTERN)


class RunTiming(ArtifactModel):
    """Wall-clock timing metadata for a run."""

    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_timestamps(self) -> RunTiming:
        if self.started_at is not None and self.completed_at is not None:
            if self.completed_at < self.started_at:
                raise ValueError("'completed_at' must be greater than or equal to 'started_at'.")
        if self.queued_at is not None and self.started_at is not None:
            if self.started_at < self.queued_at:
                raise ValueError("'started_at' must be greater than or equal to 'queued_at'.")
        return self


class LlmExecutionParameters(ArtifactModel):
    """Effective execution parameters used for the LLM request."""

    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    seed: int | None = None
    max_turns: int | None = Field(default=None, ge=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    retries: int | None = Field(default=None, ge=0)
    tool_choice: str | dict[str, Any] | None = None


class RunRequestMetadata(ArtifactModel):
    """Requested run inputs and effective request settings."""

    requested_model: str
    gateway: str | None = None
    execution_parameters: LlmExecutionParameters = Field(default_factory=LlmExecutionParameters)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderMetadata(ArtifactModel):
    """Provider-returned metadata recorded for the run."""

    gateway: str | None = None
    provider_name: str | None = None
    provider_model_id: str | None = None
    request_id: str | None = None
    response_id: str | None = None
    finish_reason: str | None = None
    native_finish_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedUsage(ArtifactModel):
    """Provider-agnostic normalized token usage."""

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)


class UsageMetadata(ArtifactModel):
    """Usage metrics with a normalized view plus raw provider payload."""

    normalized: NormalizedUsage = Field(default_factory=NormalizedUsage)
    raw_provider_usage: dict[str, Any] | None = None


class OutputArtifactRef(ArtifactModel):
    """Reference metadata for an output artifact stored outside the run artifact."""

    artifact_id: str = Field(pattern=ID_PATTERN)
    artifact_type: str = Field(pattern=ID_PATTERN)
    uri: str
    media_type: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunError(ArtifactModel):
    """Explicit error information for unsuccessful runs."""

    code: str
    message: str
    error_type: str | None = None
    retryable: bool | None = None
    provider_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseTraceEvent(ArtifactModel):
    """Shared fields for sequential trace events."""

    sequence: int = Field(ge=0)
    timestamp: datetime | None = None


class MessageTraceEvent(BaseTraceEvent):
    """Message emitted or observed during the run."""

    event_type: Literal["message"]
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallTraceEvent(BaseTraceEvent):
    """Tool call event with stable identity and raw arguments."""

    event_type: Literal["tool_call"]
    call_id: str
    tool_name: str
    raw_arguments: Any
    parsed_arguments: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResultTraceEvent(BaseTraceEvent):
    """Result associated with a previously recorded tool call."""

    event_type: Literal["tool_result"]
    call_id: str
    status: Literal["success", "error"] | None = None
    output: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunnerTraceEvent(BaseTraceEvent):
    """Runner lifecycle or implementation-specific event."""

    event_type: Literal["runner"]
    name: str
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalOutputTraceEvent(BaseTraceEvent):
    """Final output emitted by the runner."""

    event_type: Literal["final_output"]
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


type TraceEvent = Annotated[
    MessageTraceEvent
    | ToolCallTraceEvent
    | ToolResultTraceEvent
    | RunnerTraceEvent
    | FinalOutputTraceEvent,
    Field(discriminator="event_type"),
]


class RunArtifact(ArtifactModel):
    """Canonical serialized record for one runner execution."""

    identity: RunArtifactIdentity
    status: RunStatus
    timing: RunTiming = Field(default_factory=RunTiming)
    request: RunRequestMetadata
    provider: ProviderMetadata = Field(default_factory=ProviderMetadata)
    usage: UsageMetadata = Field(default_factory=UsageMetadata)
    trace: list[TraceEvent] = Field(default_factory=list)
    output_artifacts: list[OutputArtifactRef] = Field(default_factory=list)
    error: RunError | None = None
    runner_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_error_and_trace(self) -> RunArtifact:
        expected_sequences = list(range(len(self.trace)))
        actual_sequences = [event.sequence for event in self.trace]
        if actual_sequences != expected_sequences:
            raise ValueError(
                "Trace event sequences must be contiguous and zero-based in recorded order."
            )

        if self.status is RunStatus.SUCCESS and self.error is not None:
            raise ValueError("Successful runs cannot include an error object.")

        if self.status is not RunStatus.SUCCESS and self.error is None:
            raise ValueError("Non-successful runs must include an error object.")

        return self
